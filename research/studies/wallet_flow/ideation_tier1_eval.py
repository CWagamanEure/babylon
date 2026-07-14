"""
ideation_tier1_eval — proper OOS test of the 3 cache-cheap, probed IDEATION winners (audit/xsec_ideation_swarm/SYNTHESIS.md):
  A. COVARIANCE-AWARE book (equal vs inverse-vol vs Ledoit-Wolf min-variance char-portfolio) — convergence ×2, both probed.
  B. CONVICTION-CONCENTRATION (extremity sweep) — the "taker-rescue": per-crossing gross + median + hourly hit + net (STATIC hs;
     the point-in-time-spread hinge is flagged as the asset_ctx follow-up).
  C. FADE-vs-CHASE gate (informed flow vs trailing move) — the ~10× IC split; cache version on s_inf + the residualization-artifact
     caveat noted (raw-S recheck = pipeline follow-up).

All from the fast cache (data/derived/xsec_kalman/panel_cache.npz — post-aggregation cells; s_inf = V-trail ⊥[crowd,mom]).
Faithful to the frozen engine: PHASE-AVERAGED over all reb offsets, t+1 entry (S0.fwd_sum), per-fold (month) sign test,
day-block bootstrap CI, turnover-aware taker+maker cost scenarios. Honest over-carry framing (concentration = argmax-extremity).

    .venv/bin/python -m research.studies.wallet_flow.ideation_tier1_eval
"""
from __future__ import annotations
import time, json
from pathlib import Path
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)
CACHE = Path("data/derived/xsec_kalman/panel_cache.npz")
OUT = Path("data/derived/xsec_ideation_tier1")
TAKER_FEE, MAKER_FEE = 2.4, 1.0
# (label, gross_mult, fee/side, spread_mode)  earn = maker earns half-spread; small = taker small-clip; impact = taker full
SCEN = [("taker_small", 1.0, TAKER_FEE, "small"), ("taker_impact", 1.0, TAKER_FEE, "impact"),
        ("maker_a30", 0.7, MAKER_FEE, "earn"), ("maker_a50", 0.5, MAKER_FEE, "earn")]
COVWIN = 480          # trailing hours (~20d) for vol/cov estimation (causal)
COVMIN = 120          # min trailing obs to estimate vol/cov, else fall back to equal


def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 8: return np.nan
    ra = np.argsort(np.argsort(a[m])).astype(float); rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else np.nan


def _dayblock_ci(vals, hrs, hours, n=1000, seed=7):
    vals = np.asarray(vals, float)
    if len(vals) < 8: return (float("nan"), float("nan"))
    days = (hours[np.asarray(hrs, np.int64)] // 86_400_000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(vals[np.concatenate([loc[ud[p]] for p in pick])].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


def _sign_test(per_fold_vals):
    v = [x for x in per_fold_vals if np.isfinite(x)]; n = len(v); k = sum(1 for x in v if x > 0)
    if n == 0: return {"pos": 0, "n": 0, "p": float("nan")}
    from math import comb
    p = sum(comb(n, i) for i in range(k, n + 1)) / (2 ** n)          # one-sided sign test vs 0.5
    return {"pos": k, "n": n, "p": float(min(1.0, 2 * p))}           # two-sided


def _ledoit_diag(X):
    """Ledoit-Wolf shrink of sample cov toward its diagonal. X = obs x names (finite)."""
    T, Nn = X.shape
    Xc = X - X.mean(0)
    S = (Xc.T @ Xc) / T
    d = np.diag(np.diag(S))
    # shrinkage intensity toward diagonal (off-diagonal only)
    off = S - d
    phi = ((Xc ** 2).T @ (Xc ** 2)) / T - S ** 2       # var of entries
    np.fill_diagonal(phi, 0.0)
    num = phi.sum(); den = (off ** 2).sum()
    lam = 0.0 if den <= 0 else min(1.0, max(0.0, num / den / T))
    return (1 - lam) * S + lam * d


# ---------------------------------------------------------------- book cores -----------------------------------
def _select(row_idx, sc, q1, q2, held_long, held_short):
    """CB hold-band selection → (new_long, new_short) as sets of alt-indices. row_idx/sc aligned present names."""
    n = len(row_idx); order = np.argsort(sc)
    k1 = max(1, int(round(q1 * n))); k2 = max(k1, int(round(q2 * n)))
    idx = np.asarray(row_idx)
    top_e, top_h = set(idx[order[-k1:]]), set(idx[order[-k2:]])
    bot_e, bot_h = set(idx[order[:k1]]), set(idx[order[:k2]])
    new_long = {c for c in held_long if c in top_h}
    for c in idx[order[::-1]]:
        if len(new_long) >= k1: break
        if c in top_e: new_long.add(c)
    new_short = {c for c in held_short if c in bot_h}
    for c in idx[order]:
        if len(new_short) >= k1: break
        if c in bot_e: new_short.add(c)
    return new_long, new_short


def book(SIG, RA, FV, hs, hs_def, reb, weight="equal", q1=0.10, q2=0.15, phase=0):
    """Phase-`phase` held decile long-short book with a weighting scheme. RA = per-hour resid (for vol/cov). FV = fwd
    resid over the hold (bp). Returns per-step components. weight ∈ {equal, invvol, minvar}."""
    N, na = SIG.shape
    held_long, held_short = set(), set()
    out = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    grid = range(phase, N - reb, reb)
    for t in grid:
        row = SIG[t]; present = np.nonzero(np.isfinite(row))[0]
        present = np.array([c for c in present if np.isfinite(FV[t, c])])
        if len(present) < 4:
            continue
        sc = row[present]
        nl, ns = _select(present, sc, q1, q2, held_long, held_short)
        nl = [c for c in nl if np.isfinite(FV[t, c])]; ns = [c for c in ns if np.isfinite(FV[t, c])]
        if not nl or not ns:
            held_long, held_short = set(nl), set(ns); continue
        nl = np.array(sorted(nl)); ns = np.array(sorted(ns))
        # weights within each leg
        if weight == "equal":
            wl = np.ones(len(nl)) / len(nl); wsh = np.ones(len(ns)) / len(ns)
        elif weight == "magnitude":                          # soft weight ∝ |signal| within leg (diversifies the hard cut)
            al = np.abs(row[nl]); ash = np.abs(row[ns])
            wl = al / al.sum() if al.sum() > 0 else np.ones(len(nl)) / len(nl)
            wsh = ash / ash.sum() if ash.sum() > 0 else np.ones(len(ns)) / len(ns)
        else:
            lo = max(0, t - COVWIN)
            win = RA[lo:t]                                    # causal trailing window
            names = np.concatenate([nl, ns])
            sub = win[:, names]
            good = np.isfinite(sub).all(1)
            if good.sum() < COVMIN:
                wl = np.ones(len(nl)) / len(nl); wsh = np.ones(len(ns)) / len(ns)
            elif weight == "invvol":
                vol = np.nanstd(win, axis=0)
                vl = np.where(np.isfinite(vol[nl]) & (vol[nl] > 0), 1.0 / vol[nl], 0.0)
                vs = np.where(np.isfinite(vol[ns]) & (vol[ns] > 0), 1.0 / vol[ns], 0.0)
                wl = vl / vl.sum() if vl.sum() > 0 else np.ones(len(nl)) / len(nl)
                wsh = vs / vs.sum() if vs.sum() > 0 else np.ones(len(ns)) / len(ns)
            else:  # minvar char-portfolio: w ∝ Σ⁻¹ μ, μ = signed cross-sec rank, LW-shrunk Σ, then dollar-neutralize
                X = sub[good]
                Sig = _ledoit_diag(X)
                mu = np.zeros(len(names))
                # signed target: longs positive by rank, shorts negative
                rk = np.argsort(np.argsort(row[names])).astype(float); rk = rk / (len(rk) - 1) - 0.5
                sgn = np.array([1.0] * len(nl) + [-1.0] * len(ns))
                mu = np.abs(rk) * sgn                          # magnitude of extremity, signed by leg
                try:
                    w = np.linalg.solve(Sig + 1e-9 * np.eye(len(names)), mu)
                except np.linalg.LinAlgError:
                    w = mu.copy()
                w = w - w.mean()                               # dollar-neutral
                if np.abs(w).sum() > 0: w = w / np.abs(w).sum() * 2.0   # L1 = 2 (1 per side nominal)
                wl = np.maximum(w[:len(nl)], 0.0); wsh = np.maximum(-w[len(nl):], 0.0)
                if wl.sum() > 0: wl = wl / wl.sum()
                else: wl = np.ones(len(nl)) / len(nl)
                if wsh.sum() > 0: wsh = wsh / wsh.sum()
                else: wsh = np.ones(len(ns)) / len(ns)
        gl = float(np.sum(wl * FV[t, nl])); gs = float(np.sum(wsh * FV[t, ns]))
        gross = gl - gs
        nlset, nsset = set(nl.tolist()), set(ns.tolist())
        K = max(1, min(len(nlset), len(nsset)))
        traded = (nlset ^ held_long) | (nsset ^ held_short)
        out["hr"].append(int(t)); out["gross"].append(gross)
        out["ntrade"].append(len(traded) / K)
        out["hs"].append(sum(hs.get(int(c), hs_def) for c in traded) / K)
        out["turn"].append(len(traded) / (2 * K))
        held_long, held_short = nlset, nsset
    return {k: np.array(v, float) for k, v in out.items()}


def net_series(sim, reb, fee, mode):
    if len(sim["hr"]) == 0: return np.array([]), np.array([])
    if mode == "small":
        cost = sim["ntrade"] * fee + np.minimum(sim["hs"], sim["ntrade"] * 1.0)
    elif mode == "impact":
        cost = sim["ntrade"] * fee + sim["hs"]
    else:
        cost = sim["ntrade"] * fee - sim["hs"]
    return (sim["gross"] - cost) / reb, sim["hr"].astype(np.int64)   # per-HOUR net (gross is reb-hour hold)


def phase_avg(SIG, RA, FV_by_reb, hs, hs_def, reb, panel_month, hours, weight="equal", q1=0.10, q2=0.15):
    """Pool per-step series over all reb phases; report gross/hr, turnover, and per-scenario net/hr + CI + per-fold sign."""
    pool = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    for ph in range(reb):
        s = book(SIG, RA, FV_by_reb[reb], hs, hs_def, reb, weight, q1, q2, phase=ph)
        for k in pool: pool[k].extend(s[k].tolist())
    P = {k: np.array(v, float) for k, v in pool.items()}
    if len(P["hr"]) < 8: return None
    hrs = P["hr"].astype(np.int64); shm = np.array([int(panel_month[t]) for t in hrs])
    res = {"reb": reb, "weight": weight, "q1": q1, "n_steps": int(len(hrs)),
           "gross_bp_hr": float((P["gross"] / reb).mean()), "gross_per_cross": float(P["gross"].mean()),
           "turn": float(P["turn"].mean()), "sc": {}}
    for lab, mult, fee, mode in SCEN:
        if mode == "earn":                                     # maker: adverse-selection haircut on gross, earn spread
            cost = P["ntrade"] * fee - P["hs"]; netph = (P["gross"] * mult - cost) / reb
        elif mode == "small":
            cost = P["ntrade"] * fee + np.minimum(P["hs"], P["ntrade"] * 1.0); netph = (P["gross"] - cost) / reb
        else:
            cost = P["ntrade"] * fee + P["hs"]; netph = (P["gross"] - cost) / reb
        lo, hi = _dayblock_ci(netph, hrs, hours)
        pf = {int(m): float(netph[shm == m].mean()) for m in sorted(set(shm.tolist()))}
        st = _sign_test(list(pf.values()))
        per_cross = netph * reb                                # net over each reb-hour hold
        sharpe = float(per_cross.mean() / per_cross.std() * np.sqrt(8760.0 / reb)) if per_cross.std() > 0 else float("nan")
        res["sc"][lab] = {"net_bp_hr": float(netph.mean()), "ci95": [lo, hi], "per_fold": pf, "sharpe": sharpe,
                          "folds_pos": st["pos"], "n_folds": st["n"], "sign_p": st["p"]}
    return res


# ---------------------------------------------------------------- experiments ----------------------------------
def run():
    OUT.mkdir(parents=True, exist_ok=True)
    d = np.load(CACHE, allow_pickle=True)
    R, Cc, s_inf = d["R"].astype(np.int64), d["Cc"].astype(np.int64), d["s_inf"].astype(np.float64)
    hours = d["hours"].astype(np.int64); panel_month = d["panel_month"].astype(np.int64)
    resid_alt = d["resid_alt"].astype(np.float64); hs_arr = d["hs_arr"].astype(np.float64)
    hs_def = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    hs = {i: float(hs_arr[i]) for i in range(n_alt)}
    fin = np.isfinite(s_inf)
    SIG = np.full((N, n_alt), np.nan); SIG[R[fin], Cc[fin]] = s_inf[fin]
    RA = resid_alt                                             # per-hour resid for vol/cov
    _log(f"cache: N={N} n_alt={n_alt} cells={fin.sum():,} folds={list(d['folds'])}")
    FV = {r: S0.fwd_sum(resid_alt, r) * 1e4 for r in (2, 4)}   # bp, t+1 entry (fwd_sum is strictly future)
    results = {}

    # ---- EXP A: covariance-aware book (equal vs invvol vs minvar), reb2 + reb4 ----
    print("\n================ EXP A — COVARIANCE-AWARE BOOK (phase-avg, OOS) ================")
    print("  (maker_a30 is the deployable leg; SR = annualized Sharpe — the covariance agents' claim was an IR lift, not a mean lift)")
    print(f"{'cfg':>26} {'gross/hr':>8} {'turn':>5}   {'maker_a30 net/hr':>18} {'maker SR':>9}")
    for reb in (4, 2):
        for weight in ("equal", "invvol", "minvar"):
            e = phase_avg(SIG, RA, FV, hs, hs_def, reb, panel_month, hours, weight=weight)
            results[f"A/reb{reb}/{weight}"] = e
            if e is None: print(f"  reb{reb}/{weight}: thin"); continue
            mk = e["sc"]["maker_a30"]; lo, hi = mk["ci95"]
            print(f"{f'reb{reb} {weight}':>26} {e['gross_bp_hr']:>+8.2f} {e['turn']:>5.2f}   "
                  f"{mk['net_bp_hr']:+6.2f}[{lo:+.1f},{hi:+.1f}] {mk['sharpe']:>9.2f}  {mk['folds_pos']}/{mk['n_folds']}")

    # ---- EXP B: conviction-concentration extremity sweep (reb4 + reb2), STATIC hs; per-crossing gross+median+hit ----
    print("\n================ EXP B — CONVICTION-CONCENTRATION (extremity sweep, STATIC hs) ================")
    print("  (per-crossing gross; median+hit test the over-carry; PIT-spread is the asset_ctx follow-up if this survives)")
    for reb in (4, 2):
        for q1 in (0.30, 0.20, 0.10, 0.05):
            pool = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
            nns = []
            for ph in range(reb):
                s = book(SIG, RA, FV[reb], hs, hs_def, reb, "equal", q1=q1, q2=min(0.5, q1 * 1.5), phase=ph)
                for k in pool: pool[k].extend(s[k].tolist())
            P = {k: np.array(v, float) for k, v in pool.items()}
            if len(P["hr"]) < 8:
                print(f"  reb{reb} q{q1}: thin"); continue
            hrs = P["hr"].astype(np.int64); shm = np.array([int(panel_month[t]) for t in hrs])
            g = P["gross"]                                     # per-crossing gross (reb-hour hold)
            approx_names = int(round(q1 * 45))
            row = {"reb": reb, "q1": q1, "approx_names_side": approx_names, "n_steps": int(len(g)),
                   "gross_per_cross_mean": float(g.mean()), "gross_per_cross_median": float(np.median(g)),
                   "hourly_hit": float((g > 0).mean()), "sc": {}}
            for lab, mult, fee, mode in SCEN:
                if mode == "earn":
                    cost = P["ntrade"] * fee - P["hs"]; net = (g * mult - cost)          # per-crossing net
                elif mode == "small":
                    cost = P["ntrade"] * fee + np.minimum(P["hs"], P["ntrade"] * 1.0); net = g - cost
                else:
                    cost = P["ntrade"] * fee + P["hs"]; net = g - cost
                pf = {int(m): float(net[shm == m].mean()) for m in sorted(set(shm.tolist()))}
                st = _sign_test(list(pf.values()))
                row["sc"][lab] = {"net_per_cross": float(net.mean()), "net_median": float(np.median(net)),
                                  "folds_pos": st["pos"], "n_folds": st["n"], "sign_p": st["p"]}
            results[f"B/reb{reb}/q{q1}"] = row
            row["turn"] = float(P["turn"].mean()); row["ntrade_per_K"] = float(P["ntrade"].mean())
            tk = row["sc"]["taker_small"]; mk = row["sc"]["maker_a30"]
            print(f"  reb{reb} q{q1:<4} (~{approx_names}/side, turn {row['turn']:.2f})  gross/cross {g.mean():+6.2f} "
                  f"(={g.mean()/reb:+.2f}/hr)  | taker_small {tk['net_per_cross']:+6.2f}/cross med {tk['net_median']:+6.2f} "
                  f"{tk['folds_pos']}/{tk['n_folds']}  | maker_a30 {mk['net_per_cross']:+6.2f}/cross (={mk['net_per_cross']/reb:+.2f}/hr) {mk['folds_pos']}/{mk['n_folds']}")

    # ---- EXP C: fade-vs-chase gate on s_inf (cache); IC split + gated book. Caveat: s_inf already ⊥mom → raw-S recheck pending ----
    print("\n================ EXP C — FADE vs CHASE (informed flow vs trailing move) ================")
    LAG = S0.trailing_resid_mom(resid_alt)                     # trailing-24h residual move per (hour, alt)
    agree = np.sign(SIG) * np.sign(LAG)                        # +1 chase (flow agrees w/ recent move), -1 fade
    # IC split at several horizons
    print("  IC(s_inf, fwd-rank) by cell class:")
    ic_out = {}
    for h in (2, 4, 8):
        U = S0.xsec_rank(S0.fwd_sum(resid_alt, h), list(range(n_alt)))
        sflat = SIG.flatten(); uflat = U.flatten(); aflat = agree.flatten()
        ic_all = _spear(sflat, uflat)
        ic_chase = _spear(np.where(aflat > 0, sflat, np.nan), uflat)
        ic_fade = _spear(np.where(aflat < 0, sflat, np.nan), uflat)
        ic_out[f"h{h}"] = {"all": ic_all, "chase": ic_chase, "fade": ic_fade}
        print(f"    h={h:<2}  all {ic_all:+.4f}   chase {ic_chase:+.4f}   fade {ic_fade:+.4f}")
    # per-fold fade>chase sign test at h=8 (the agent's headline horizon)
    U8 = S0.xsec_rank(S0.fwd_sum(resid_alt, 8), list(range(n_alt)))
    pf_delta = {}
    for m in sorted(set(panel_month.tolist())):
        hm = np.nonzero(panel_month == m)[0]
        sf = SIG[hm].flatten(); uf = U8[hm].flatten(); af = agree[hm].flatten()
        icc = _spear(np.where(af > 0, sf, np.nan), uf); icf = _spear(np.where(af < 0, sf, np.nan), uf)
        if np.isfinite(icc) and np.isfinite(icf): pf_delta[int(m)] = icf - icc
    stD = _sign_test(list(pf_delta.values()))
    print(f"    fade−chase per-fold (h=8): {stD['pos']}/{stD['n']} folds fade>chase, sign p={stD['p']:.3f}")
    # fade-GATED book: keep only fade cells (zero chase), reb2+reb4 maker
    SIG_fade = np.where(agree < 0, SIG, np.nan)                # trade only fade cells
    print("  Fade-GATED book (chase cells dropped) vs baseline, phase-avg OOS:")
    for reb in (4, 2):
        base = phase_avg(SIG, RA, FV, hs, hs_def, reb, panel_month, hours, weight="equal")
        fade = phase_avg(SIG_fade, RA, FV, hs, hs_def, reb, panel_month, hours, weight="equal")
        results[f"C/reb{reb}/base"] = base; results[f"C/reb{reb}/fade"] = fade
        for tag, e in (("base", base), ("fade", fade)):
            if e is None: print(f"    reb{reb} {tag}: thin"); continue
            mk = e["sc"]["maker_a30"]; lo, hi = mk["ci95"]
            print(f"    reb{reb} {tag:5s}  gross {e['gross_bp_hr']:+.2f}/hr  maker_a30 {mk['net_bp_hr']:+.2f}/hr "
                  f"CI[{lo:+.2f},{hi:+.2f}] {mk['folds_pos']}/{mk['n_folds']} p{mk['sign_p']:.2f}")
    results["C/ic_split"] = ic_out; results["C/fade_minus_chase_signtest_h8"] = stD

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    print("\nNOTE: all OOS/phase-avg. Over-carry guards — EXP B concentration is an argmax-over-extremity (watch multiplicity + the")
    print("netting trap at q0.05≈2 names/side); EXP C s_inf is already ⊥mom so the fade split needs the RAW-S recheck (pipeline).")


if __name__ == "__main__":
    run()
