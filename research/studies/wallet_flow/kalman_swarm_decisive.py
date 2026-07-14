"""
DECISIVE test of the steelman's claim: does mild EMA (alpha~0.9) RAISE gross (denoising) and beat baseline OOS?
Every other swarm agent used a coarse alpha grid (first smoothing point ~0.5-0.6) and found monotone-worse. Only the
steelman finely sampled alpha in [0.85,0.91]. This resolves it: (1) fine gross(alpha) curve — is there a real peak
above baseline, or is it monotone? (2) OOS overfit-killer — freeze alpha* = argmax on EARLY folds, apply to LATE folds.

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_decisive
"""
from __future__ import annotations
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
REB = 4
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
ALPHAS = [1.0, 0.98, 0.95, 0.93, 0.91, 0.90, 0.89, 0.87, 0.85, 0.80, 0.70, 0.60, 0.40]


def dense_ema(SIG, alpha):
    """Per-column causal EMA that BLENDS every observed hour (carry belief across the rare gap). alpha=1 -> passthrough.
    Matches the steelman construction (stale large => belief always alive => real blend), leak-free."""
    if alpha >= 1.0:
        return SIG
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), alpha * obs + (1.0 - alpha) * prev, obs)
        prev = np.where(has, newv, prev)          # update belief only on observed hours; carry forward otherwise
        m[t] = np.where(has, prev, np.nan)        # emit only where observed THIS hour (same universe as baseline)
    return m


def build(d):
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    SIG = np.full((N, n_alt), np.nan)
    obs = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
    base_hours = np.array(sorted(obs), dtype=np.int64)
    reb_grid = base_hours[::REB]
    FVr = S0.fwd_sum(resid_alt, REB)
    return dict(SIG=SIG, reb_grid=reb_grid, FVr=FVr, halfspread=halfspread, hs_default=hs_default,
                n_alt=n_alt, hours=hours, panel_month=panel_month)


def eval_alpha(B, alpha, fold_filter=None):
    m = dense_ema(B["SIG"], alpha)
    full = set(range(B["n_alt"]))
    xs, fvb, elig = {}, {}, {}
    for t in B["reb_grid"]:
        ti = int(t)
        if fold_filter is not None and int(B["panel_month"][ti]) not in fold_filter:
            continue
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(B["FVr"][ti, a]) * 1e4 for a in nm}
        elig[ti] = full
    keys = np.array(sorted(xs), dtype=np.int64)
    if len(keys) < 8:
        return None
    sim = CB.simulate_raw(keys, xs, fvb, B["halfspread"], B["hs_default"], 1, 0.10, 0.15, elig)
    hrs = sim["hr"].astype(np.int64); shm = np.array([int(B["panel_month"][int(t)]) for t in hrs])
    out = {"gross": float((sim["gross"] / REB).mean()), "turn": float(sim["turn"].mean()), "n": len(hrs), "sc": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS:
            continue
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, B["hs_default"])
        ci = CB._dayblock_ci(netph, hrs, B["hours"])
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        out["sc"][lab] = {"net": float(netph.mean()), "ci": ci,
                          "fp": int(sum(1 for v in pf.values() if v > 0)), "nf": len(pf), "pf": pf}
    return out


def main():
    d = np.load(CACHE, allow_pickle=False)
    B = build(d)
    folds = sorted(int(x) for x in d["folds"])
    early, late = set(folds[:4]), set(folds[4:])
    print(f"folds {folds}  | EARLY(train alpha) {sorted(early)}  LATE(OOS) {sorted(late)}\n")

    print("=== FINE gross(alpha) & net(alpha), pooled all-7-folds reb4 ===")
    print(f"{'alpha':>6} {'gross':>7} {'turn':>6}  " + "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>20}" for l in FOCUS))
    curve = {}
    for a in ALPHAS:
        e = eval_alpha(B, a); curve[a] = e
        cols = []
        for l in FOCUS:
            sc = e["sc"][l]; lo, hi = sc["ci"]; star = "*" if lo > 0 else ("-" if hi < 0 else " ")
            cols.append(f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['fp']}/{sc['nf']}{star}")
        tag = "  <=BASE" if a == 1.0 else ""
        print(f"{a:>6.2f} {e['gross']:>+7.2f} {e['turn']:>6.2f}  " + "  ".join(f"{c:>20}" for c in cols) + tag)

    base_g = curve[1.0]["gross"]
    peak_a = max(curve, key=lambda a: curve[a]["gross"])
    print(f"\ngross: baseline(a1.0)={base_g:+.3f}  peak at a={peak_a:.2f} gross={curve[peak_a]['gross']:+.3f} "
          f"(delta {curve[peak_a]['gross']-base_g:+.3f})  -> {'NON-MONOTONE peak above baseline' if curve[peak_a]['gross']>base_g+0.05 and peak_a<1.0 else 'baseline is max / monotone'}")

    print("\n=== OVERFIT-KILLER: freeze alpha* = argmax maker_a30 net on EARLY folds, test OOS on LATE folds ===")
    early_curve = {a: eval_alpha(B, a, early) for a in ALPHAS}
    astar = max([a for a in ALPHAS if a < 1.0 and early_curve[a]],
                key=lambda a: early_curve[a]["sc"]["maker_earn_a30"]["net"])
    print(f"alpha* (trained on EARLY, argmax maker_a30) = {astar:.2f}")
    print(f"{'leg':>22} {'EARLY a=1':>12} {'EARLY a*':>12} {'LATE a=1':>12} {'LATE a*':>12}   OOS_verdict")
    late1 = eval_alpha(B, 1.0, late); lateS = eval_alpha(B, astar, late)
    e1 = eval_alpha(B, 1.0, early); eS = early_curve[astar]
    for l in FOCUS:
        v = "SMOOTH WINS OOS" if lateS["sc"][l]["net"] > late1["sc"][l]["net"] else "baseline wins OOS"
        print(f"{l:>22} {e1['sc'][l]['net']:>+12.3f} {eS['sc'][l]['net']:>+12.3f} "
              f"{late1['sc'][l]['net']:>+12.3f} {lateS['sc'][l]['net']:>+12.3f}   {v}")
    print(f"\nEARLY gross a1={e1['gross']:+.3f} a*={eS['gross']:+.3f} | LATE gross a1={late1['gross']:+.3f} a*={lateS['gross']:+.3f}")
    dl = lateS['gross'] - late1['gross']
    print(f"OOS gross delta (a* - a1) on LATE folds = {dl:+.3f}  -> {'denoising REPLICATES OOS' if dl>0.05 else 'denoising does NOT replicate OOS (in-sample overfit)'}")


if __name__ == "__main__":
    main()
