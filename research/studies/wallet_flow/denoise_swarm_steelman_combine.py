"""
STEELMAN — prosecute the α≈0.90 denoise win as REAL & MORE deployable, and push CLAIM B (q2≈0.30 taker, reb=2 maker)
to resolution. Iterates off the leak-free panel_cache (no DuckDB). Reuses the exact CB engine + dense_ema.

Legs (FOCUS): taker_top_smallclip, taker_top_impact, maker_earn_a30, maker_earn_a50.

Sections:
  0  reproduce baseline gate (α=1 pooled reb4 -> maker_a30 +4.35, taker_smallclip +1.42)
  1  COMBINE levers: denoise(α)×hold-band(q2)×reb×regime — does the TAKER leg clear zero robustly?
  2  DENOISE deployability: robust across all reb-phase offsets, reb∈{3,4,6}, both regimes; PAIRED maker CI; coin-jackknife; IC
  3  RESOLVE reb=2 maker: phase-AVERAGED reb2, α=1 vs 0.90
  4  RICHER causal filters: two-pole cascade, per-coin AR(1)-tuned gain — beat single α=0.9 OOS?

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_steelman_combine
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
PREPERIOD_MAX = 202602


def dense_ema(SIG, alpha):
    """Strictly-causal per-column level-EMA blending every observed hour (carry belief across gaps). α=1 -> passthrough."""
    if alpha >= 1.0:
        return SIG
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), alpha * obs + (1.0 - alpha) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


def dense_ema_cascade(SIG, alpha, poles=2):
    """Two-pole (or n-pole) causal EMA: apply dense_ema `poles` times. Sharper noise roll-off, more lag."""
    out = SIG
    for _ in range(poles):
        out = dense_ema(out, alpha)
    return out


def dense_ema_percoin(SIG, alphas):
    """Per-column EMA with a per-coin gain vector alphas[a]."""
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    a = np.asarray(alphas, dtype=float)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), a * obs + (1.0 - a) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


def load():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); disp = d["disp"]
    N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    SIG = np.full((N, n_alt), np.nan)
    obs = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
    base_hours = np.array(sorted(obs), dtype=np.int64)
    # frozen mid-dispersion band (pre-period tertiles), applied forward
    uniqR = np.unique(R)
    pre = np.array([t for t in uniqR if panel_month[t] <= PREPERIOD_MAX])
    dpre = disp[pre]; dpre = dpre[np.isfinite(dpre)]
    dlo, dhi = np.nanpercentile(dpre, [33.3, 66.6])
    mid_hours = set(int(t) for t in uniqR if np.isfinite(disp[t]) and dlo < disp[t] <= dhi)
    folds = sorted(int(x) for x in d["folds"])
    return dict(SIG=SIG, base_hours=base_hours, resid_alt=resid_alt, halfspread=halfspread,
                hs_default=hs_default, n_alt=n_alt, hours=hours, panel_month=panel_month,
                mid_hours=mid_hours, folds=folds)


_FV_CACHE = {}
def fv_for(D, reb):
    if reb not in _FV_CACHE:
        _FV_CACHE[reb] = S0.fwd_sum(D["resid_alt"], reb)
    return _FV_CACHE[reb]


def eval_config(D, m, reb, offset=0, q1=0.10, q2=0.15, regime="all", fold_filter=None, ret_series=False):
    """Evaluate one filtered signal `m` (already smoothed) at a given reb/phase/hold-band/regime. Returns FOCUS scenarios."""
    reb_grid = D["base_hours"][offset::reb]
    FVr = fv_for(D, reb)
    full = set(range(D["n_alt"]))
    mid = D["mid_hours"]
    xs, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t)
        if fold_filter is not None and int(D["panel_month"][ti]) not in fold_filter:
            continue
        if regime == "mid" and ti not in mid:
            continue
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8:
        return None
    sim = CB.simulate_raw(keys, xs, fvb, D["halfspread"], D["hs_default"], 1, q1, q2, elig)
    hrs = sim["hr"].astype(np.int64)
    shm = np.array([int(D["panel_month"][int(t)]) for t in hrs])
    out = {"gross": float((sim["gross"] / reb).mean()), "turn": float(sim["turn"].mean()),
           "n": len(hrs), "sc": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS:
            continue
        netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, D["hs_default"])
        ci = CB._dayblock_ci(netph, hrs, D["hours"])
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        rec = {"net": float(netph.mean()), "ci": ci,
               "fp": int(sum(1 for v in pf.values() if v > 0)), "nf": len(pf), "pf": pf}
        if ret_series:
            rec["series"] = (hrs, netph)
        out["sc"][lab] = rec
    return out


def _cell(sc):
    lo, hi = sc["ci"]; star = "*" if lo > 0 else ("-" if hi < 0 else " ")
    return f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['fp']}/{sc['nf']}{star}"


def _hdr():
    return f"{'gross':>6} {'turn':>5}  " + "  ".join(
        f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>19}" for l in FOCUS)


def _row(e):
    return f"{e['gross']:>+6.2f} {e['turn']:>5.2f}  " + "  ".join(f"{_cell(e['sc'][l]):>19}" for l in FOCUS)


def paired_diff_ci(D, mA, mB, reb, q1, q2, regime, fold_filter=None, n=2000, seed=11):
    """Paired day-block CI of the per-step net DIFFERENCE (mB - mA) for each FOCUS leg. Steps align by hour."""
    eA = eval_config(D, mA, reb, 0, q1, q2, regime, fold_filter, ret_series=True)
    eB = eval_config(D, mB, reb, 0, q1, q2, regime, fold_filter, ret_series=True)
    res = {}
    for lab in FOCUS:
        hA, nA = eA["sc"][lab]["series"]; hB, nB = eB["sc"][lab]["series"]
        dA = {int(h): v for h, v in zip(hA, nA)}
        common = np.array([h for h in hB if int(h) in dA], dtype=np.int64)
        diff = np.array([dB - dA[int(h)] for h, dB in zip(hB, nB) if int(h) in dA])
        days = (D["hours"][common] // 86_400_000).astype(np.int64); ud = np.unique(days)
        loc = {dd: np.nonzero(days == dd)[0] for dd in ud}; rng = np.random.default_rng(seed); st = []
        for _ in range(n):
            pick = rng.integers(0, len(ud), size=len(ud))
            st.append(diff[np.concatenate([loc[ud[p]] for p in pick])].mean())
        s = np.array(st)
        res[lab] = {"mean_diff": float(diff.mean()), "ci": (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))}
    return res


def xsec_ic(D, m, reb):
    """Mean per-hour Spearman IC between filtered signal and forward-sum residual at reb-grid hours (pooled)."""
    FVr = fv_for(D, reb); ics = []
    for t in D["base_hours"][::reb]:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        y = FVr[ti, nm]; ok = np.isfinite(y)
        if ok.sum() < 4:
            continue
        sr = np.argsort(np.argsort(row[nm][ok])); yr = np.argsort(np.argsort(y[ok]))
        if sr.std() == 0 or yr.std() == 0:
            continue
        ics.append(np.corrcoef(sr, yr)[0, 1])
    return float(np.mean(ics)), len(ics)


def main():
    D = load()
    folds = D["folds"]
    early, late = set(folds[:4]), set(folds[4:])
    print(f"folds {folds} | EARLY {sorted(early)} LATE {sorted(late)}")
    m1 = dense_ema(D["SIG"], 1.0)
    m9 = dense_ema(D["SIG"], 0.90)

    # ---- Section 0: baseline gate ----
    print("\n===== 0. BASELINE GATE (pooled all-folds, reb4, q2=0.15) =====")
    print(f"{'cfg':>14} {_hdr()}")
    b1 = eval_config(D, m1, 4, 0, 0.10, 0.15, "all")
    b9 = eval_config(D, m9, 4, 0, 0.10, 0.15, "all")
    print(f"{'a1.0 reb4':>14} {_row(b1)}")
    print(f"{'a0.9 reb4':>14} {_row(b9)}")
    print(f"  GATE: a1 maker_a30={b1['sc']['maker_earn_a30']['net']:+.2f} (exp +4.35), "
          f"taker_smallclip={b1['sc']['taker_top_smallclip']['net']:+.2f} (exp +1.42)")

    # ---- Section 1: COMBINE levers ----
    print("\n===== 1. COMBINE LEVERS: denoise x hold-band(q2) x reb x regime — can TAKER clear zero robustly? =====")
    for regime in ("all", "mid"):
        print(f"\n  --- regime={regime} ---")
        print(f"{'reb':>3} {'q2':>4} {'a':>4}  {_hdr()}")
        for reb in (2, 3, 4):
            for q2 in (0.15, 0.20, 0.25, 0.30, 0.35):
                for alpha, m in ((1.0, m1), (0.90, m9)):
                    e = eval_config(D, m, reb, 0, 0.10, q2, regime)
                    if e is None:
                        continue
                    print(f"{reb:>3} {q2:>4.2f} {alpha:>4.2f}  {_row(e)}")

    # ---- Section 2: DENOISE deployability ----
    print("\n===== 2. DENOISE DEPLOYABILITY =====")
    print("\n  2a. Phase-offset robustness of the α EFFECT (Δ = a0.9 − a1) at reb4, pooled, per grid phase:")
    print(f"{'reb':>3} {'phase':>5}  " + "  ".join(f"{'d '+l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>12}" for l in FOCUS))
    for reb in (3, 4, 6):
        for off in range(reb):
            e1 = eval_config(D, m1, reb, off, 0.10, 0.15, "all")
            e9 = eval_config(D, m9, reb, off, 0.10, 0.15, "all")
            if e1 is None or e9 is None:
                continue
            cols = [f"{e9['sc'][l]['net']-e1['sc'][l]['net']:+12.2f}" for l in FOCUS]
            gd = e9['gross'] - e1['gross']
            print(f"{reb:>3} {off:>5}  " + "  ".join(cols) + f"   dgross {gd:+.2f}")

    print("\n  2b. Both regimes, reb4 pooled: α=1 vs α=0.9 side by side:")
    print(f"{'regime':>7} {'a':>4}  {_hdr()}")
    for regime in ("all", "mid"):
        for alpha, m in ((1.0, m1), (0.90, m9)):
            e = eval_config(D, m, 4, 0, 0.10, 0.15, regime)
            if e: print(f"{regime:>7} {alpha:>4.2f}  {_row(e)}")

    print("\n  2c. PAIRED day-block CI of the maker/taker LIFT (a0.9 − a1), reb4 pooled q2=0.15:")
    pd = paired_diff_ci(D, m1, m9, 4, 0.10, 0.15, "all")
    for lab in FOCUS:
        r = pd[lab]; lo, hi = r["ci"]; star = "*" if lo > 0 else ("-" if hi < 0 else " ")
        print(f"    {lab:22s} lift {r['mean_diff']:+.3f} CI[{lo:+.3f},{hi:+.3f}] {star}")

    print("\n  2d. Coin-jackknife on the DENOISE gross delta (drop each coin, recompute Δgross a0.9−a1), reb4 pooled:")
    base_dg = b9["gross"] - b1["gross"]
    dgs = []
    for a in range(D["n_alt"]):
        keep = np.ones(D["n_alt"], bool); keep[a] = False
        s1 = m1.copy(); s9 = m9.copy(); s1[:, a] = np.nan; s9[:, a] = np.nan
        e1 = eval_config(D, s1, 4, 0, 0.10, 0.15, "all"); e9 = eval_config(D, s9, 4, 0, 0.10, 0.15, "all")
        if e1 and e9:
            dgs.append(e9["gross"] - e1["gross"])
    dgs = np.array(dgs)
    print(f"    full Δgross={base_dg:+.3f}; jackknife-drop-1: min {dgs.min():+.3f} med {np.median(dgs):+.3f} "
          f"max {dgs.max():+.3f} ; n_negative_drops {int((dgs<0).sum())}/{len(dgs)}")

    print("\n  2e. Cross-sectional IC, a1 vs a0.9 (reb4 pooled) — denoise should lift IC modestly:")
    ic1, n1 = xsec_ic(D, m1, 4); ic9, n9 = xsec_ic(D, m9, 4)
    print(f"    IC a1.0 = {ic1:+.4f} (n={n1})   IC a0.9 = {ic9:+.4f} (n={n9})   ΔIC {ic9-ic1:+.4f}")

    # ---- Section 3: reb=2 maker phase-averaged ----
    print("\n===== 3. RESOLVE reb=2 MAKER (phase-AVERAGED over both grid offsets) =====")
    print(f"{'phase/avg':>10} {'a':>4}  {_hdr()}")
    for alpha, m in ((1.0, m1), (0.90, m9)):
        legs = {l: [] for l in FOCUS}; gs = []; ts = []
        for off in range(2):
            e = eval_config(D, m, 2, off, 0.10, 0.15, "all")
            if e is None:
                continue
            print(f"{('reb2 ph'+str(off)):>10} {alpha:>4.2f}  {_row(e)}")
            gs.append(e["gross"]); ts.append(e["turn"])
            for l in FOCUS:
                legs[l].append(e["sc"][l]["net"])
        avg = {l: float(np.mean(legs[l])) for l in FOCUS}
        print(f"{'AVG':>10} {alpha:>4.2f}  {np.mean(gs):>+6.2f} {np.mean(ts):>5.2f}  " +
              "  ".join(f"{avg[l]:>+19.2f}" for l in FOCUS))

    # ---- Section 4: richer causal filters ----
    print("\n===== 4. RICHER CAUSAL FILTERS (OOS: train on EARLY, judge on LATE, maker_a30 target) =====")
    # candidates: single-pole a in grid, two-pole cascade, per-coin AR(1)-tuned
    def ar1_alpha_percoin():
        """MSE-optimal EMA gain per coin from lag-1 autocorr of the observed signal: a* = 1 - rho (bounded)."""
        SIG = D["SIG"]; a = np.full(D["n_alt"], 0.90)
        for c in range(D["n_alt"]):
            col = SIG[:, c]; ok = np.isfinite(col)
            x = col[ok]
            if len(x) < 30:
                continue
            x0, x1 = x[:-1], x[1:]
            if x0.std() == 0 or x1.std() == 0:
                continue
            rho = np.corrcoef(x0, x1)[0, 1]
            a[c] = float(np.clip(1.0 - max(0.0, rho), 0.05, 1.0))
        return a
    apc = ar1_alpha_percoin()
    print(f"    per-coin AR(1) gain: median a*={np.median(apc):.3f} range[{apc.min():.3f},{apc.max():.3f}]")
    filters = {
        "a=1.0 (base)":     m1,
        "a=0.90 1-pole":    m9,
        "a=0.87 1-pole":    dense_ema(D["SIG"], 0.87),
        "a=0.90 2-pole":    dense_ema_cascade(D["SIG"], 0.90, 2),
        "a=0.95 2-pole":    dense_ema_cascade(D["SIG"], 0.95, 2),
        "per-coin AR(1)":   dense_ema_percoin(D["SIG"], apc),
    }
    print(f"{'filter':>16} {'EARLY mk_a30':>13} {'LATE mk_a30':>12} {'LATE tk_small':>14} {'LATE gross':>11}  OOS")
    base_late = None
    for name, m in filters.items():
        ee = eval_config(D, m, 4, 0, 0.10, 0.15, "all", early)
        el = eval_config(D, m, 4, 0, 0.10, 0.15, "all", late)
        if ee is None or el is None:
            continue
        if name == "a=1.0 (base)":
            base_late = el["sc"]["maker_earn_a30"]["net"]
        v = "WIN" if base_late is not None and el["sc"]["maker_earn_a30"]["net"] > base_late else ""
        print(f"{name:>16} {ee['sc']['maker_earn_a30']['net']:>+13.3f} {el['sc']['maker_earn_a30']['net']:>+12.3f} "
              f"{el['sc']['taker_top_smallclip']['net']:>+14.3f} {el['gross']:>+11.3f}  {v}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
