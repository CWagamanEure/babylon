"""
kalman_swarm_filter_lib — shared harness for the state-estimation attack on Result 11.

Loads the frozen panel cache, builds the dense observed-signal matrix + frozen baseline rebalance grid,
and books ANY causal per-alt filter through the IDENTICAL CB.simulate_raw / CB.scenario_net_series cost
engine used by the baseline. Reproduces the deployed book (no smoothing) as a self-check.

All filters here are strictly causal (use only signal at hours <= t) unless explicitly named a SMOOTHER
(non-causal diagnostic that CANNOT be deployed — used only to bound the achievable turnover rescue).
"""
from __future__ import annotations
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

REB = 4
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
CACHE = "data/derived/xsec_kalman/panel_cache.npz"


def load_panel():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"].astype(int), d["Cc"].astype(int), d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}

    SIG = np.full((N, n_alt), np.nan)
    obs_hours = set()
    fin = np.isfinite(s_inf)
    SIG[R[fin], Cc[fin]] = s_inf[fin]
    for t in R[fin]:
        obs_hours.add(int(t))
    base_hours = np.array(sorted(obs_hours), dtype=np.int64)
    reb_grid = base_hours[::REB]
    hour_month = {int(t): int(panel_month[int(t)]) for t in reb_grid}
    FVr = S0.fwd_sum(resid_alt, REB)                     # [N,n_alt] forward REB-hour resid return (frac)

    dfin = disp[np.isfinite(disp)]
    dlo, dhi = np.nanpercentile(dfin, [33.3, 66.6])
    mid_ok = {int(t): bool(dlo < disp[int(t)] <= dhi) for t in reb_grid}

    return dict(SIG=SIG, reb_grid=reb_grid, hour_month=hour_month, FVr=FVr, halfspread=halfspread,
                hs_default=hs_default, n_alt=n_alt, N=N, hours=hours, mid_ok=mid_ok,
                panel_month=panel_month, disp=disp, R=R, Cc=Cc, s_inf=s_inf)


def book_from_matrix(P, m, regime="all"):
    """Book a smoothed/observable matrix m[t,a] (NaN = name not live at t) through the frozen cost engine.
    Returns a cell dict with FOCUS-scenario stats. Rebalance timestamps are frozen to the baseline grid."""
    SIG_reb = P["reb_grid"]; FVr = P["FVr"]; n_alt = P["n_alt"]
    halfspread = P["halfspread"]; hs_default = P["hs_default"]; hours = P["hours"]
    hour_month = P["hour_month"]; mid_ok = P["mid_ok"]; full_set = set(range(n_alt))
    xs_arr, fvb, elig = {}, {}, {}
    for t in SIG_reb:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
    keys = np.array(sorted(xs_arr), dtype=np.int64)
    if len(keys) < 8:
        return None
    sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
    if len(sim["hr"]) < 8:
        return None
    hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
    cell = {"n_steps": int(len(hrs)), "gross_bp_per_hr": float((sim["gross"] / REB).mean()),
            "mean_turnover": float(sim["turn"].mean()), "scenarios": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
        ci95 = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        st = ADJ.sign_test([v for v in pf.values()])
        cell["scenarios"][lab] = {"net": float(netph.mean()), "ci95": list(ci95),
                                  "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                  "n_folds": len(pf), "sign_p": st["p"], "per_fold": pf,
                                  "net_sd": float(netph.std())}
    return cell


def fmt_focus(cell):
    if cell is None:
        return "(thin)"
    out = []
    for lab in FOCUS:
        sc = cell["scenarios"][lab]; lo, hi = sc["ci95"]
        star = "*" if lo > 0 else ("-" if hi < 0 else " ")
        short = lab.replace("taker_top_", "tk_").replace("maker_earn_", "mk_")
        out.append(f"{short}={sc['net']:+.2f}[{lo:+.1f},{hi:+.1f}]{sc['folds_pos']}/{sc['n_folds']}{star}")
    return f"gross{cell['gross_bp_per_hr']:+.2f} turn{cell['mean_turnover']:.2f} | " + "  ".join(out)
