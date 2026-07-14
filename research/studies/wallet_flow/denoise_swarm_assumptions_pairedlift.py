"""
ASSUMPTIONS agent — PAIRED test of the denoise LIFT (a.90 - a1) itself.

The caveat: maker a.90=+5.06 sits INSIDE baseline CI [+2.9,+5.7] -> overlapping CIs cannot tell if the LIFT is real.
The right test pairs the two net series on the SAME day-blocks and bootstraps the DIFFERENCE. Does the lift exclude 0?
Run at the win config (reb4 phase0) AND phase-averaged across all reb4 offsets (grid-phase-robust).

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_assumptions_pairedlift
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow.denoise_swarm_assumptions_sensitivity import build_cache, dense_ema

CACHE = "data/derived/xsec_kalman/panel_cache.npz"


def net_series(B, alpha, reb, phase, lab, mult, fee, mode, q1=0.10, q2=0.15):
    """Return dict hour->net_per_hr for one scenario, plus the hour->month map."""
    m = dense_ema(B["SIG"], alpha)
    reb_grid = B["base_hours"][phase::reb]
    FVr = S0.fwd_sum(B["resid_alt"], reb)
    full = set(range(B["n_alt"]))
    xs, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t)
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8:
        return {}
    sim = CB.simulate_raw(keys, xs, fvb, B["halfspread"], B["hs_default"], 1, q1, q2, elig)
    netph, hrs = CB.scenario_net_series(sim, reb, fee, mode, mult, B["hs_default"])
    return {int(h): float(v) for h, v in zip(hrs, netph)}


def paired_boot(B, reb, phases, lab, mult, fee, mode, n=2000, seed=7):
    """Paired day-block bootstrap of (a.90 - a1) net-per-hr, pooled over the given phase offsets."""
    diffs = []; days = []
    for ph in phases:
        s1 = net_series(B, 1.0, reb, ph, lab, mult, fee, mode)
        s9 = net_series(B, 0.90, reb, ph, lab, mult, fee, mode)
        common = sorted(set(s1) & set(s9))
        for h in common:
            diffs.append(s9[h] - s1[h])
            days.append(B["hours"][h] // 86_400_000)
    diffs = np.array(diffs); days = np.array(days, dtype=np.int64)
    if len(diffs) < 8:
        return None
    ud = np.unique(days); loc = {d: np.nonzero(days == d)[0] for d in ud}
    rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(diffs[np.concatenate([loc[ud[p]] for p in pick])].mean())
    s = np.array(st)
    return dict(mean=float(diffs.mean()), lo=float(np.percentile(s, 2.5)), hi=float(np.percentile(s, 97.5)),
                p_ge0=float((s <= 0).mean()), nsteps=len(diffs))


def main():
    d = np.load(CACHE, allow_pickle=False)
    B = build_cache(d)
    scen = {"maker_earn_a30": (0.70, 1.0, "earn"), "maker_earn_a50": (0.50, 1.0, "earn"),
            "taker_top_smallclip": (1.00, 2.4, "small"), "taker_top_impact": (1.00, 2.4, "impact")}
    print("PAIRED day-block bootstrap of the DENOISE LIFT (a.90 - a1), same hours. '*' = lift CI excludes 0.\n")
    for tag, reb, phases in [("WIN CONFIG   reb4 phase0", 4, [0]),
                             ("PHASE-AVG    reb4 all 4 phases", 4, [0, 1, 2, 3]),
                             ("PHASE-AVG    reb3 all 3 phases", 3, [0, 1, 2])]:
        print(f"--- {tag} ---")
        for lab, (mult, fee, mode) in scen.items():
            r = paired_boot(B, reb, phases, lab, mult, fee, mode)
            if r is None:
                print(f"  {lab:22s} thin"); continue
            star = "*" if r["lo"] > 0 else ("-" if r["hi"] < 0 else " ")
            print(f"  {lab:22s} lift {r['mean']:+.3f} CI[{r['lo']:+.3f},{r['hi']:+.3f}] "
                  f"p(lift<=0)={r['p_ge0']:.3f} n={r['nsteps']} {star}")
        print()


if __name__ == "__main__":
    main()
