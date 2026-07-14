"""
STEELMAN addendum — the HONEST (phase-luck-removed) significance of the α=0.90 denoise, and the reb2-horizon maker win.

The reb4[::4] deployed grid lands on a favorable phase (phase-0 dgross +1.03 vs phase-avg +0.27). To get the
deployable α effect free of phase selection, POOL the paired per-step lift (a0.9 − a1) across ALL grid phases and
day-block-bootstrap it. Also: paired reb2-vs-reb4 maker lift (is the horizon win significant?).

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_steelman_phaserobust
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow.denoise_swarm_steelman_combine import load, dense_ema, eval_config, fv_for, FOCUS


def _dayblock_ci_diff(diff, hours_of_step, hours, n=2000, seed=13):
    days = (hours[hours_of_step] // 86_400_000).astype(np.int64); ud = np.unique(days)
    loc = {dd: np.nonzero(days == dd)[0] for dd in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(diff[np.concatenate([loc[ud[p]] for p in pick])].mean())
    s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))


def phase_pooled_lift(D, mA, mB, reb, q1=0.10, q2=0.15, regime="all"):
    """Pool the paired per-step net diff (mB−mA) across ALL grid phase offsets, then day-block CI. Phase-luck-removed."""
    res = {l: {"h": [], "d": []} for l in FOCUS}
    for off in range(reb):
        eA = eval_config(D, mA, reb, off, q1, q2, regime, ret_series=True)
        eB = eval_config(D, mB, reb, off, q1, q2, regime, ret_series=True)
        if eA is None or eB is None:
            continue
        for l in FOCUS:
            hA, nA = eA["sc"][l]["series"]; hB, nB = eB["sc"][l]["series"]
            dA = {int(h): v for h, v in zip(hA, nA)}
            for h, dB in zip(hB, nB):
                if int(h) in dA:
                    res[l]["h"].append(int(h)); res[l]["d"].append(dB - dA[int(h)])
    out = {}
    for l in FOCUS:
        d = np.array(res[l]["d"]); h = np.array(res[l]["h"], dtype=np.int64)
        lo, hi = _dayblock_ci_diff(d, h, D["hours"])
        out[l] = {"lift": float(d.mean()), "ci": (lo, hi), "n": len(d)}
    return out


def phase_pooled_horizon_lift(D, m, rebB, rebA, q1=0.10, q2=0.15, regime="all"):
    """Paired maker lift of horizon rebB vs rebA, pooled across rebB's phases matched to rebA phase0 by nearest hour.
    Simpler: report phase-pooled net for each reb (unpaired) since the step universes differ across reb."""
    def pooled_net(reb):
        acc = {l: [] for l in FOCUS}; gs = []
        for off in range(reb):
            e = eval_config(D, m, reb, off, q1, q2, regime)
            if e is None:
                continue
            gs.append(e["gross"])
            for l in FOCUS:
                acc[l].append(e["sc"][l]["net"])
        return {l: float(np.mean(acc[l])) for l in FOCUS}, float(np.mean(gs))
    nB, gB = pooled_net(rebB); nA, gA = pooled_net(rebA)
    return nA, gA, nB, gB


def main():
    D = load()
    m1 = dense_ema(D["SIG"], 1.0); m9 = dense_ema(D["SIG"], 0.90)

    print("===== PHASE-POOLED paired α-lift (a0.9 − a1), phase-luck REMOVED — the honest deployable denoise effect =====")
    for reb in (4, 2, 3, 6):
        r = phase_pooled_lift(D, m1, m9, reb, 0.10, 0.15, "all")
        print(f"\n  reb{reb} (pooled over {reb} phases, all-regime):")
        for l in FOCUS:
            lo, hi = r[l]["ci"]; star = "*" if lo > 0 else ("-" if hi < 0 else " ")
            print(f"    {l:22s} phase-avg lift {r[l]['lift']:+.3f} CI[{lo:+.3f},{hi:+.3f}] {star}  (n={r[l]['n']})")

    print("\n===== HORIZON maker win: phase-averaged reb2 vs reb4 (α=1 and α=0.9), pooled all-regime =====")
    for alpha, m, tag in ((1.0, m1, "a1.0"), (0.90, m9, "a0.9")):
        nA, gA, nB, gB = phase_pooled_horizon_lift(D, m, 2, 4)
        print(f"  {tag}: reb4 gross {gA:+.2f} maker_a30 {nA['maker_earn_a30']:+.2f} | "
              f"reb2 gross {gB:+.2f} maker_a30 {nB['maker_earn_a30']:+.2f}  "
              f"-> reb2 horizon lift {nB['maker_earn_a30']-nA['maker_earn_a30']:+.2f}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
