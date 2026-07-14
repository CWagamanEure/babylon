"""
denoise_swarm_averaging_decomp — AVERAGING-AWAY-SIGNAL lens on CLAIM A (the banked alpha~0.90 dense_ema denoise).

Cuts BOTH ways:
  (i)  Is the pooled +0.7bp maker gain (and +1.06 taker / +1.0 gross) a WASH of large +/- across folds/coins/regimes
       (a fake average), or a BROAD improvement? A real denoise should be broad; a fake one is concentrated.
  (ii) Does pooling HIDE a bigger conditional denoise win in a subset (regime/coin-tier) that the pooled alpha=0.90
       undershoots?

Lenses (all on the panel_cache, the exact CB engine, dense_ema; reb=4 frozen grid, ONLY the signal differs):
  L1  PER-FOLD heterogeneity   — paired (a0.90 - a1.0) per-step net + gross, per fold; day-block CI per fold, sign.
  L2  PER-COIN attribution     — decompose the decile-book gross into per-coin signed contributions; map the
                                 gross change baseline->a0.90 for each of 45 coins. Broad or a few tail names?
  L3  REGIME                   — dispersion tertiles (calm/mid/noisy) AND turnover tertiles (lo/mid/hi):
                                 paired diff net+gross per cell. A denoiser MUST help the NOISY regime.
  L4  BURIED-BIGGER-WIN        — sweep alpha WITHIN each regime cell; is the optimal alpha meaningfully different
                                 and the gain much larger than the pooled alpha=0.90 delta?
  L5  TAKER-specifically       — is the taker denoise gain uniform across folds/coins, or driven by the same lucky
                                 subset (cross-check vs prosecutor)?

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_averaging_decomp
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
REB = 4
BASE_A, WIN_A = 1.0, 0.90
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
ALPHAS_SWEEP = [1.0, 0.95, 0.90, 0.85, 0.80, 0.70, 0.60, 0.40]
OUT = Path("data/derived/xsec_kalman")


def dense_ema(SIG, alpha):
    """Exact copy of kalman_swarm_decisive.dense_ema — causal per-column EMA blending across the rare gap."""
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


def build(d):
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; resid_alt = d["resid_alt"]; disp = d["disp"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    SIG = np.full((N, n_alt), np.nan); obs = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
    base_hours = np.array(sorted(obs), dtype=np.int64)
    reb_grid = base_hours[::REB]
    FVr = S0.fwd_sum(resid_alt, REB)
    return dict(SIG=SIG, reb_grid=reb_grid, FVr=FVr, halfspread=halfspread, hs_default=hs_default,
                n_alt=n_alt, hours=hours, panel_month=panel_month, disp=disp, resid_alt=resid_alt, hs_arr=hs_arr)


def make_xs(B, alpha, hours_iter=None):
    """Build (xs, fvb, elig) for the frozen reb_grid on the alpha-smoothed signal. Same universe as baseline."""
    m = dense_ema(B["SIG"], alpha)
    full = set(range(B["n_alt"]))
    xs, fvb, elig = {}, {}, {}
    grid = B["reb_grid"] if hours_iter is None else hours_iter
    for t in grid:
        ti = int(t); row = m[ti]
        nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(B["FVr"][ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    return xs, fvb, elig


def run_sim(B, alpha):
    xs, fvb, elig = make_xs(B, alpha)
    keys = np.array(sorted(xs), dtype=np.int64)
    sim = CB.simulate_raw(keys, xs, fvb, B["halfspread"], B["hs_default"], 1, 0.10, 0.15, elig)
    return sim


def net_map(B, sim, lab):
    """Per-step net-per-hour map {hr: net} for a scenario label."""
    mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
    netph, hrs = CB.scenario_net_series(sim, REB, fee, mode, mult, B["hs_default"])
    return {int(h): float(v) for h, v in zip(hrs, netph)}


def gross_map(sim):
    return {int(h): float(g) / REB for h, g in zip(sim["hr"], sim["gross"])}


def turn_map(sim):
    return {int(h): float(t) for h, t in zip(sim["hr"], sim["turn"])}


def summ(B, vmap, hset=None):
    hrs = np.array([h for h in sorted(vmap) if (hset is None or h in hset)], dtype=np.int64)
    if len(hrs) < 8: return None
    vals = np.array([vmap[int(h)] for h in hrs])
    ci = CB._dayblock_ci(vals, hrs, B["hours"])
    shm = np.array([int(B["panel_month"][int(h)]) for h in hrs])
    pf = {int(mm): float(vals[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
    st = ADJ.sign_test([v for v in pf.values()])
    return {"mean": float(vals.mean()), "ci": ci, "fp": int(sum(1 for v in pf.values() if v > 0)),
            "nf": len(pf), "n": int(len(hrs)), "sign_p": float(st["p"]), "per_fold": pf}


def paired(B, a_map, b_map, hset=None):
    """PAIRED (a_map - b_map) per-step diff on common timestamps; day-block CI + per-fold sign."""
    common = sorted(set(a_map) & set(b_map))
    if hset is not None:
        common = [h for h in common if h in hset]
    if len(common) < 8: return None
    hrs = np.array(common, dtype=np.int64)
    diff = np.array([a_map[h] - b_map[h] for h in common])
    ci = CB._dayblock_ci(diff, hrs, B["hours"])
    shm = np.array([int(B["panel_month"][int(h)]) for h in hrs])
    pf = {int(mm): float(diff[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
    st = ADJ.sign_test([v for v in pf.values()])
    return {"diff": float(diff.mean()), "ci": ci, "fp": int(sum(1 for v in pf.values() if v > 0)),
            "nf": len(pf), "n": int(len(hrs)), "sign_p": float(st["p"]), "per_fold": pf}


def fmt(s):
    if s is None: return "   (thin)"
    k = "diff" if "diff" in s else "mean"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    return f"{s[k]:+6.3f}[{s['ci'][0]:+5.2f},{s['ci'][1]:+5.2f}]{s['fp']}/{s['nf']}{star} n={s['n']}"


# ---------- per-coin attribution: replicate simulate_raw's held-book selection, track per-coin signed contribution
def coin_contrib(B, alpha):
    """Return arr[n_alt] = total per-hour gross contribution of each coin over all reb steps (sum matches book gross).
    Also returns n_steps. Mirrors CB.simulate_raw selection EXACTLY (q1=0.10 entry, q2=0.15 hold band)."""
    xs, fvb, _ = make_xs(B, alpha)
    keys = sorted(xs)
    q1, q2 = 0.10, 0.15
    held_long, held_short = set(), set()
    contrib = np.zeros(B["n_alt"]); nstep = 0
    for t in keys:
        names, sc = xs[t]
        n = len(names)
        if n < 4:
            continue
        order = np.argsort(sc)
        k1 = max(1, int(round(q1 * n))); k2 = max(k1, int(round(q2 * n)))
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        new_long = {nm for nm in held_long if nm in top_hold}
        for nm in names[order[::-1]]:
            if len(new_long) >= k1: break
            if nm in top_entry and nm not in new_long: new_long.add(nm)
        new_short = {nm for nm in held_short if nm in bot_hold}
        for nm in names[order]:
            if len(new_short) >= k1: break
            if nm in bot_entry and nm not in new_short: new_short.add(nm)
        lf = [(nm, fvb[t].get(nm, np.nan)) for nm in new_long]
        sf = [(nm, fvb[t].get(nm, np.nan)) for nm in new_short]
        lf = [(nm, x) for nm, x in lf if np.isfinite(x)]; sf = [(nm, x) for nm, x in sf if np.isfinite(x)]
        if not lf or not sf:
            held_long, held_short = new_long, new_short; continue
        nl, ns = len(lf), len(sf)
        for nm, x in lf:
            contrib[nm] += (x / nl) / REB      # per-hour contribution
        for nm, x in sf:
            contrib[nm] += (-x / ns) / REB
        nstep += 1
        held_long, held_short = new_long, new_short
    return contrib, nstep


def main():
    d = np.load(CACHE, allow_pickle=False)
    B = build(d)
    folds = sorted(int(x) for x in d["folds"])
    _log(f"folds {folds}")

    # ---- baseline + win sims (frozen grid, identical timestamps) ----
    base_sim = run_sim(B, BASE_A)
    win_sim = run_sim(B, WIN_A)
    b_gross = gross_map(base_sim); w_gross = gross_map(win_sim)
    b_turn = turn_map(base_sim); w_turn = turn_map(win_sim)
    b_net = {lab: net_map(B, base_sim, lab) for lab in FOCUS}
    w_net = {lab: net_map(B, win_sim, lab) for lab in FOCUS}
    common_hrs = sorted(set(b_gross) & set(w_gross))
    _log(f"base steps {len(b_gross)}  win steps {len(w_gross)}  common {len(common_hrs)} "
         f"(pairing {'CLEAN' if len(common_hrs)==len(b_gross)==len(w_gross) else 'MISMATCH'})")

    RES = {"gate": {}, "L1_fold": {}, "L2_coin": {}, "L3_regime": {}, "L4_buried": {}, "L5_taker": {}}

    # ---- GATE: pooled baseline vs win ----
    print("\n============ GATE: pooled reb4  (baseline a=1.0  ->  win a=0.90) ============")
    print(f"  {'metric':22s} {'baseline':>26s} {'win a0.90':>26s}   paired diff (win-base)")
    for lab, bm, wm in [("gross", b_gross, w_gross)] + [(l, b_net[l], w_net[l]) for l in FOCUS]:
        bs, ws, pd = summ(B, bm), summ(B, wm), paired(B, wm, bm)
        RES["gate"][lab] = {"base": bs, "win": ws, "diff": pd}
        print(f"  {lab:22s} {fmt(bs):>26s} {fmt(ws):>26s}   {fmt(pd)}")
    tb = summ(B, b_turn); tw = summ(B, w_turn)
    print(f"  {'turnover':22s} {tb['mean']:+.3f}{'':18s} {tw['mean']:+.3f}")

    # ---- L1 PER-FOLD heterogeneity ----
    print("\n============ L1  PER-FOLD heterogeneity of the denoise gain (paired win-base within each fold) ============")
    for lab in (["gross"] + list(FOCUS)):
        bm = b_gross if lab == "gross" else b_net[lab]
        wm = w_gross if lab == "gross" else w_net[lab]
        print(f"  -- {lab} --")
        RES["L1_fold"][lab] = {}
        row = []
        for f in folds:
            hset = set(h for h in common_hrs if int(B["panel_month"][int(h)]) == f)
            pd = paired(B, wm, bm, hset)
            RES["L1_fold"][lab][f] = pd
            row.append(f"{f}:{pd['diff']:+.2f}{'*' if pd['ci'][0]>0 else ('-' if pd['ci'][1]<0 else '')}" if pd else f"{f}:thin")
        npos = sum(1 for f in folds if RES["L1_fold"][lab][f] and RES["L1_fold"][lab][f]["diff"] > 0)
        print(f"     folds win>base: {npos}/{len(folds)}   [{'  '.join(row)}]")

    # ---- L2 PER-COIN attribution ----
    print("\n============ L2  PER-COIN attribution: gross contribution baseline -> a0.90 (per-hr bp) ============")
    cb_base, ns_b = coin_contrib(B, BASE_A)
    cb_win, ns_w = coin_contrib(B, WIN_A)
    # normalize to per-step (contrib already per-hour summed over steps) -> per reb-step average
    cb_base_ph = cb_base / max(1, ns_b); cb_win_ph = cb_win / max(1, ns_w)
    dc = cb_win_ph - cb_base_ph
    print(f"  book gross reconstructed: base sum={cb_base_ph.sum():+.3f}/hr  win sum={cb_win_ph.sum():+.3f}/hr "
          f"(engine base {summ(B,b_gross)['mean']:+.3f}, win {summ(B,w_gross)['mean']:+.3f})")
    n_improve = int((dc > 0).sum()); n_worse = int((dc < 0).sum())
    hs_arr = B["hs_arr"]; coin_vol = np.nanstd(B["resid_alt"], axis=0)
    order = np.argsort(-np.abs(dc))
    print(f"  coins improved by denoise: {n_improve}/45   worsened: {n_worse}/45")
    top_sum = float(np.sort(dc)[-5:].sum()); bot_sum = float(np.sort(dc)[:5].sum())
    print(f"  total gross delta {dc.sum():+.3f}/hr ; top-5 gainers contribute {top_sum:+.3f}, bottom-5 {bot_sum:+.3f}")
    print(f"  {'coin#':>5s} {'base':>8s} {'win':>8s} {'delta':>8s} {'|d|rank':>7s} {'hs_bp':>6s} {'vol':>7s}")
    for c in order[:12]:
        print(f"  {c:>5d} {cb_base_ph[c]:>+8.3f} {cb_win_ph[c]:>+8.3f} {dc[c]:>+8.3f} "
              f"{'':>7s} {hs_arr[c]:>6.2f} {coin_vol[c]:>7.4f}")
    # concentration: fraction of positive delta explained by top-k coins
    pos = np.sort(dc[dc > 0])[::-1]
    frac_top5 = float(pos[:5].sum() / pos.sum()) if pos.sum() > 0 else float('nan')
    RES["L2_coin"] = {"base_ph": cb_base_ph.tolist(), "win_ph": cb_win_ph.tolist(), "delta": dc.tolist(),
                      "n_improve": n_improve, "n_worse": n_worse, "gross_delta_sum": float(dc.sum()),
                      "top5_gainers_sum": top_sum, "bot5_sum": bot_sum,
                      "frac_pos_delta_from_top5": frac_top5, "hs_arr": hs_arr.tolist(),
                      "coin_vol": [float(x) for x in coin_vol]}
    print(f"  concentration: top-5 gainers explain {frac_top5*100:.0f}% of the total POSITIVE per-coin delta")

    # ---- L3 REGIME: dispersion + turnover tertiles ----
    print("\n============ L3  REGIME decomposition (paired win-base within regime cells) ============")
    disp = B["disp"]
    dvals = np.array([disp[int(h)] for h in common_hrs])
    dlo, dhi = np.nanpercentile(dvals, [33.3, 66.6])
    disp_cells = {"calm": set(h for h in common_hrs if disp[int(h)] <= dlo),
                  "mid":  set(h for h in common_hrs if dlo < disp[int(h)] <= dhi),
                  "noisy": set(h for h in common_hrs if disp[int(h)] > dhi)}
    tvals = np.array([b_turn[int(h)] for h in common_hrs])
    tlo, thi = np.percentile(tvals, [33.3, 66.6])
    turn_cells = {"lo_turn": set(h for h in common_hrs if b_turn[int(h)] <= tlo),
                  "mid_turn": set(h for h in common_hrs if tlo < b_turn[int(h)] <= thi),
                  "hi_turn": set(h for h in common_hrs if b_turn[int(h)] > thi)}
    RES["L3_regime"] = {"disp_bounds": [float(dlo), float(dhi)], "turn_bounds": [float(tlo), float(thi)],
                        "disp": {}, "turn": {}}
    for grpname, cells in (("disp", disp_cells), ("turn", turn_cells)):
        print(f"  -- {grpname} tertiles  (n: " + ", ".join(f"{k}={len(v)}" for k, v in cells.items()) + ") --")
        for lab in (["gross", "maker_earn_a30", "taker_top_smallclip"]):
            bm = b_gross if lab == "gross" else b_net[lab]
            wm = w_gross if lab == "gross" else w_net[lab]
            print(f"     {lab}:")
            RES["L3_regime"][grpname][lab] = {}
            for cn, hset in cells.items():
                pd = paired(B, wm, bm, hset)
                RES["L3_regime"][grpname][lab][cn] = pd
                print(f"        {cn:9s} diff {fmt(pd)}")

    # ---- L4 BURIED-BIGGER-WIN: sweep alpha within each regime cell (net maker_a30 & gross) ----
    print("\n============ L4  BURIED-BIGGER-WIN: optimal alpha WITHIN each regime cell ============")
    # precompute net/gross maps for each alpha once (pooled), then subset
    alpha_maps = {}
    for a in ALPHAS_SWEEP:
        sim_a = base_sim if a == BASE_A else run_sim(B, a)
        alpha_maps[a] = {"gross": gross_map(sim_a),
                         "maker_earn_a30": net_map(B, sim_a, "maker_earn_a30"),
                         "taker_top_smallclip": net_map(B, sim_a, "taker_top_smallclip")}
    RES["L4_buried"] = {}
    for grpname, cells in (("disp", disp_cells), ("turn", turn_cells)):
        for cn, hset in cells.items():
            RES["L4_buried"][f"{grpname}:{cn}"] = {}
            for lab in ("gross", "maker_earn_a30", "taker_top_smallclip"):
                curve = {}
                for a in ALPHAS_SWEEP:
                    s = summ(B, alpha_maps[a][lab], hset)
                    curve[a] = None if s is None else s["mean"]
                base_v = curve[BASE_A]
                astar = max([a for a in ALPHAS_SWEEP if curve[a] is not None], key=lambda a: curve[a])
                gain_at_090 = (curve[WIN_A] - base_v) if (curve[WIN_A] is not None and base_v is not None) else None
                gain_at_star = (curve[astar] - base_v) if base_v is not None else None
                RES["L4_buried"][f"{grpname}:{cn}"][lab] = {"curve": curve, "astar": astar,
                                                            "gain_090": gain_at_090, "gain_star": gain_at_star}
                if lab == "maker_earn_a30":
                    print(f"  {grpname}:{cn:9s} maker_a30: base {base_v:+.2f}  a0.90 {curve[WIN_A]:+.2f} "
                          f"(gain {gain_at_090:+.2f})  argmax a={astar:.2f} {curve[astar]:+.2f} (gain {gain_at_star:+.2f})")

    # ---- L5 TAKER specifically: per-fold + per-coin uniformity ----
    print("\n============ L5  TAKER denoise: uniform or lucky subset? ============")
    RES["L5_taker"] = {}
    for lab in ("taker_top_smallclip", "taker_top_impact"):
        bm, wm = b_net[lab], w_net[lab]
        pf_diffs = {}
        for f in folds:
            hset = set(h for h in common_hrs if int(B["panel_month"][int(h)]) == f)
            pd = paired(B, wm, bm, hset)
            pf_diffs[f] = None if pd is None else pd["diff"]
        vals = [v for v in pf_diffs.values() if v is not None]
        npos = sum(1 for v in vals if v > 0)
        rng = (max(vals) - min(vals)) if vals else float('nan')
        pooled = summ(B, wm)["mean"] - summ(B, bm)["mean"]
        RES["L5_taker"][lab] = {"per_fold_diff": pf_diffs, "npos": npos, "pooled_diff": pooled, "spread": rng}
        print(f"  {lab:22s} pooled diff {pooled:+.3f}  folds+ {npos}/{len(folds)}  "
              f"per-fold [{'  '.join(f'{f}:{pf_diffs[f]:+.2f}' if pf_diffs[f] is not None else f'{f}:thin' for f in folds)}]")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "denoise_averaging_decomp.json").write_text(json.dumps(RES, indent=2, default=float))
    _log("wrote denoise_averaging_decomp.json")
    print("\nLegend: diff/mean [CI_lo,CI_hi] folds+/nfolds  '*'=CI>0  '-'=CI<0.  diff = win(a0.90) - baseline(a1.0).")


if __name__ == "__main__":
    main()
