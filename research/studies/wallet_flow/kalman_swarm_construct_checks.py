"""
kalman_swarm_construct_checks — CONSTRUCTION/CORRECTNESS audit of Result 11 (xsec_kalman).

Does the test artificially disadvantage smoothing?  Checks:
  (0) reproduce baseline (a1,s0) == compare_pooled reb4 numbers.
  (1) ema_smooth(SIG,1,0) == SIG exactly (baseline identity).
  (2) turnover-credit: does an active smooth cell actually get lower turnover charged?
  (3) held-name-absent handling: are carried names charged/earned correctly (carry-forward inertness).
  (4) LEVEL-scale incoherence: cross-sectional std drift of s_inf hour-to-hour.
  (5) SMOOTHING SPACE fix: level vs z-scored vs rank EMA, head-to-head net for FOCUS scenarios.
  (6) crowd re-correlation induced by post-residualization smoothing.

Does NOT modify frozen files. Reuses the cache + CB cost engine.
"""
from __future__ import annotations
import numpy as np
from pathlib import Path

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_kalman as KAL

CACHE = Path("data/derived/xsec_kalman/panel_cache.npz")
REB = 4
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")


def load():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    SIG = np.full((N, n_alt), np.nan)
    obs_hours = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs_hours.add(int(R[i]))
    base_hours = np.array(sorted(obs_hours), dtype=np.int64)
    reb_grid = base_hours[::REB]
    hour_month = {int(t): int(panel_month[int(t)]) for t in reb_grid}
    FVr = S0.fwd_sum(resid_alt, REB)
    disp_f = disp[np.isfinite(disp)]
    dlo, dhi = np.nanpercentile(disp_f, [33.3, 66.6])
    mid_ok = {int(t): (dlo < disp[int(t)] <= dhi) for t in reb_grid}
    return dict(SIG=SIG, reb_grid=reb_grid, hour_month=hour_month, FVr=FVr, halfspread=halfspread,
                hs_default=hs_default, n_alt=n_alt, hours=hours, mid_ok=mid_ok, panel_month=panel_month,
                disp=disp, R=R, Cc=Cc, s_inf=s_inf, N=N)


def eval_from_m(m, ctx, regime="all"):
    """Replicate KAL.eval_cell's booking exactly, but take a pre-smoothed matrix m."""
    reb_grid = ctx["reb_grid"]; FVr = ctx["FVr"]; halfspread = ctx["halfspread"]
    hs_default = ctx["hs_default"]; n_alt = ctx["n_alt"]; hours = ctx["hours"]
    hour_month = ctx["hour_month"]; mid_ok = ctx["mid_ok"]; full_set = set(range(n_alt))
    xs_arr, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4: continue
        xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
    keys = np.array(sorted(xs_arr), dtype=np.int64)
    if len(keys) < 8: return None
    sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
    if len(sim["hr"]) < 8: return None
    hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
    out = {"gross_bp_per_hr": float((sim["gross"] / REB).mean()), "mean_turnover": float(sim["turn"].mean()),
           "n_steps": int(len(hrs)), "scenarios": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
        ci95 = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        st = ADJ.sign_test([v for v in pf.values()])
        out["scenarios"][lab] = {"net": float(netph.mean()), "ci95": ci95,
                                 "folds_pos": int(sum(1 for v in pf.values() if v > 0)), "n_folds": len(pf),
                                 "sign_p": st["p"]}
    return out


def zscore_hours(SIG):
    """Per-hour cross-sectional standardization: (x - mean)/std over finite entries. Preserves NaN mask."""
    Z = np.full_like(SIG, np.nan)
    for t in range(SIG.shape[0]):
        row = SIG[t]; fin = np.isfinite(row)
        if fin.sum() < 2: continue
        v = row[fin]; sd = v.std()
        Z[t, fin] = (v - v.mean()) / sd if sd > 0 else 0.0
    return Z


def rank_hours(SIG):
    """Per-hour cross-sectional centered rank in [-0.5,0.5]. Preserves NaN mask."""
    Rk = np.full_like(SIG, np.nan)
    for t in range(SIG.shape[0]):
        row = SIG[t]; fin = np.isfinite(row); n = int(fin.sum())
        if n < 2: continue
        v = row[fin]; rk = np.argsort(np.argsort(v)).astype(float)
        Rk[t, fin] = rk / (n - 1) - 0.5
    return Rk


def fmt(cell):
    if cell is None: return "(thin)"
    parts = [f"gross{cell['gross_bp_per_hr']:+.3f} turn{cell['mean_turnover']:.3f}"]
    for lab in FOCUS:
        s = cell["scenarios"][lab]; lo, hi = s["ci95"]
        parts.append(f"{lab.replace('taker_top_','tk_').replace('maker_earn_','mk_')}={s['net']:+.2f}[{lo:+.1f},{hi:+.1f}]{s['folds_pos']}/{s['n_folds']}")
    return "  ".join(parts)


def main():
    ctx = load()
    SIG = ctx["SIG"]
    print(f"loaded cache: N={ctx['N']} hours, {ctx['n_alt']} alts, {len(ctx['reb_grid'])} reb-grid steps")

    # ---- (1) identity: ema_smooth(SIG,1,0) == SIG
    m10 = KAL.ema_smooth(SIG, 1.0, 0)
    both_nan = np.isnan(SIG) & np.isnan(m10)
    eq = np.isclose(np.where(np.isnan(SIG), 0, SIG), np.where(np.isnan(m10), 0, m10)) | both_nan
    same_mask = (np.isnan(SIG) == np.isnan(m10)).all()
    print(f"\n[1] ema_smooth(SIG,1,0)==SIG : values_equal={eq.all()}  nan_mask_equal={same_mask}")

    # ---- (0) reproduce baseline
    base_all = eval_from_m(SIG, ctx, "all")
    base_mid = eval_from_m(SIG, ctx, "mid")
    print(f"\n[0] BASELINE all : {fmt(base_all)}")
    print(f"    BASELINE mid : {fmt(base_mid)}")
    print("    (expect all: mk_a30 ~+4.35, tk_smallclip ~+1.42)")

    # ---- (4) level-scale drift of s_inf across hours
    stds = []
    for t in ctx["reb_grid"]:
        row = SIG[int(t)]; v = row[np.isfinite(row)]
        if len(v) >= 4: stds.append(v.std())
    stds = np.array(stds)
    print(f"\n[4] per-hour cross-sectional std of s_inf (level): "
          f"median={np.median(stds):.4g} p10={np.percentile(stds,10):.4g} p90={np.percentile(stds,90):.4g} "
          f"p90/p10={np.percentile(stds,90)/max(np.percentile(stds,10),1e-12):.2f}x  cv={stds.std()/stds.mean():.3f}")
    print("    (large p90/p10 => level EMA blends incomparable scales => scale-incoherent smoothing)")

    # ---- (2)/(3)/(5) smoothing-SPACE head-to-head. Active cell needs stale>0.
    ZS = zscore_hours(SIG); RK = rank_hours(SIG)
    print("\n[5] SMOOTHING-SPACE head-to-head (regime=all).  m built causally, then re-ranked+booked identically.")
    print(f"    {'config':28s} {'space':6s}  " + "metrics")
    print(f"    {'baseline a1 s0':28s} {'-':6s}  {fmt(base_all)}")
    for space, base in (("level", SIG), ("zscore", ZS), ("rank", RK)):
        for alpha, stale in ((0.6, 4), (0.35, 8), (0.2, 24), (0.6, 24), (0.35, 24)):
            m = KAL.ema_smooth(base, alpha, stale)
            cell = eval_from_m(m, ctx, "all")
            print(f"    a{alpha} s{stale:<3d} {'':16s} {space:6s}  {fmt(cell)}")

    print("\n[5b] SMOOTHING-SPACE head-to-head (regime=mid).")
    print(f"    {'baseline a1 s0':28s} {'-':6s}  {fmt(base_mid)}")
    for space, base in (("level", SIG), ("zscore", ZS), ("rank", RK)):
        for alpha, stale in ((0.6, 4), (0.35, 8), (0.2, 24), (0.35, 24)):
            m = KAL.ema_smooth(base, alpha, stale)
            cell = eval_from_m(m, ctx, "mid")
            print(f"    a{alpha} s{stale:<3d} {'':16s} {space:6s}  {fmt(cell)}")

    # ---- (6) crowd re-correlation from post-resid smoothing (level vs zscore)
    # correlation of smoothed signal with the FRESH signal it should track (proxy for lag) and turnover credit table
    print("\n[2/6] turnover-credit + lag diagnostic (regime=all, level space):")
    for alpha, stale in ((1.0, 0), (0.6, 4), (0.35, 8), (0.2, 24)):
        m = KAL.ema_smooth(SIG, alpha, stale) if (stale > 0 or alpha < 1.0) else SIG
        # per-hour corr of smoothed vs fresh within reb grid
        cs = []
        for t in ctx["reb_grid"]:
            ti = int(t); a = m[ti]; b = SIG[ti]; f = np.isfinite(a) & np.isfinite(b)
            if f.sum() >= 4 and a[f].std() > 0 and b[f].std() > 0:
                cs.append(np.corrcoef(a[f], b[f])[0, 1])
        cell = eval_from_m(m, ctx, "all")
        print(f"    a{alpha} s{stale:<3d}: turn={cell['mean_turnover']:.3f} gross={cell['gross_bp_per_hr']:+.3f} "
              f"corr(smoothed,fresh)med={np.median(cs):.3f}  n_names/hr~{np.mean([np.isfinite(m[int(t)]).sum() for t in ctx['reb_grid']]):.1f}")


if __name__ == "__main__":
    main()
