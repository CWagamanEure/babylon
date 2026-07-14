"""
adfilter_regime_Q_adaptive — build + OOS-test a REGIME-ADAPTIVE Kalman gain and reconcile the horizon finding.

From adfilter_regime_Q_diag: the DOMINANT axis is R (a fixed denoise alpha<1 lifts IC almost everywhere), but
realized-VOL carries a Q-flavor: the booked GROSS benefit of smoothing is strong in CALM hours (rvol6-lo gross
+0.74 [+0.22,+1.25] 7/7*) and EVAPORATES / reverses in high-vol hours (rvol24-hi gross -0.07). Q-driver reading:
high vol => the tail state drifts => smooth LESS (gain -> 1, harvest fresh); calm => smooth MORE (low gain).

This script:
  A. ADAPTIVE GAIN: alpha_t = A_CALM in low-vol hours, A_VOL(>=A_CALM) in high-vol hours (causal rvol regime).
     TUNE (A_CALM, A_VOL, vol-threshold) on EARLY folds; report the tuned config OOS on LATE folds. Compare to
     the best FIXED alpha (also tuned early) and to no-smooth. Phase-averaged over all 4 reb-4 phases.
  B. HORIZON x REGIME: is "harvest faster" (reb2>reb4) a Q-response? Book reb2 vs reb4 within vol tertiles;
     if reb2's edge over reb4 is concentrated in HIGH-vol hours, that IS the same Q-response as less smoothing.

    .venv/bin/python -m research.studies.wallet_flow.adfilter_regime_Q_adaptive
"""
from __future__ import annotations
import json, time, itertools
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
OUT = Path("data/derived/xsec_kalman"); OUT.mkdir(parents=True, exist_ok=True)
FOCUS = ("taker_top_smallclip", "maker_earn_a30")

d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
folds = list(int(x) for x in d["folds"]); halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
SIG = np.full((N, n_alt), np.nan); obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
hour_month_all = {int(t): int(panel_month[int(t)]) for t in base_hours}
EARLY = set(folds[:3]); LATE = set(folds[-3:])
_log(f"cache: {len(base_hours)} obs hours; early={sorted(EARLY)} late={sorted(LATE)}")


# ------------------------------------------------------------------ causal realized-vol regime
def build_rvol(K):
    rm = np.full(N, np.nan)
    for h in base_hours:
        t = int(h); lo = max(0, t - K)
        if t - lo < max(6, K // 2): continue
        with np.errstate(invalid="ignore"):
            per_coin = np.nanstd(resid_alt[lo:t], axis=0)
        v = np.nanmean(per_coin)
        if np.isfinite(v): rm[t] = v
    return rm

RVOL = build_rvol(24)
# CAUSAL threshold: use the EARLY-fold quantile only (no look-ahead into late folds)
rvol_early = np.array([RVOL[int(h)] for h in base_hours if hour_month_all[int(h)] in EARLY and np.isfinite(RVOL[int(h)])])


# ------------------------------------------------------------------ EMA with a per-timestep (time-varying) gain
def dense_ema_vec(M, alpha_t):
    """Causal per-column EMA; alpha_t[t] is the observation weight (Kalman gain) applied at hour t."""
    out = np.full((N, n_alt), np.nan); prev = np.full(n_alt, np.nan)
    for t in range(N):
        a = alpha_t[t]; obs_t = M[t]; has = np.isfinite(obs_t)
        newv = np.where(np.isfinite(prev), a * obs_t + (1.0 - a) * prev, obs_t)
        prev = np.where(has, newv, prev)
        out[t] = np.where(has, prev, np.nan)
    return out

def const_alpha(a):
    return np.full(N, a)

def adaptive_alpha(a_calm, a_vol, thr):
    """low-vol hour -> a_calm (smooth more); high-vol hour -> a_vol (smooth less). NaN vol -> a_calm (default)."""
    at = np.full(N, a_calm)
    hi = np.isfinite(RVOL) & (RVOL > thr)
    at[hi] = a_vol
    return at


# ------------------------------------------------------------------ phase-averaged booking -> per-hour net maps
def book_netmaps(M, reb=4):
    net = {lab: {} for lab in FOCUS}
    for ph in range(reb):
        grid = base_hours[ph::reb]
        FVr = S0.fwd_sum(resid_alt, reb)
        xs_arr, fvb, elig = {}, {}, {}
        for t in grid:
            ti = int(t); row = M[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4: continue
            xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
            elig[ti] = set(range(n_alt))
        keys = np.array(sorted(xs_arr), dtype=np.int64)
        if len(keys) < 8: continue
        sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
        if len(sim["hr"]) < 8: continue
        for lab in FOCUS:
            mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
            netph, hrs = CB.scenario_net_series(sim, reb, fee, mode, mult, hs_default)
            for h, v in zip(hrs, netph):
                net[lab][int(h)] = float(v)
    return net

def summ(vmap, foldset):
    hs = np.array([h for h in sorted(vmap) if hour_month_all[int(h)] in foldset], dtype=np.int64)
    if len(hs) < 12: return None
    vals = np.array([vmap[int(h)] for h in hs]); ci = CB._dayblock_ci(vals, hs, hours)
    pf = {}
    for h in hs: pf.setdefault(hour_month_all[int(h)], []).append(vmap[int(h)])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}; st = ADJ.sign_test(list(pfm.values()))
    return {"mean": float(vals.mean()), "ci": list(ci), "n": int(len(hs)),
            "folds_pos": st["n_pos"], "n_folds": st["n"], "sign_p": st["p"]}

def paired(vmap, vbase, foldset):
    common = sorted(h for h in set(vmap) & set(vbase) if hour_month_all[int(h)] in foldset)
    if len(common) < 12: return None
    hs = np.array(common, dtype=np.int64); diff = np.array([vmap[h] - vbase[h] for h in common])
    ci = CB._dayblock_ci(diff, hs, hours)
    pf = {}
    for h in common: pf.setdefault(hour_month_all[int(h)], []).append(vmap[h] - vbase[h])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}; st = ADJ.sign_test(list(pfm.values()))
    return {"mean_diff": float(diff.mean()), "ci": list(ci), "n": int(len(hs)),
            "folds_pos": st["n_pos"], "n_folds": st["n"], "sign_p": st["p"]}

def fb(s):
    if s is None: return "(thin)"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    return f"{s['mean']:+.3f}[{s['ci'][0]:+.2f},{s['ci'][1]:+.2f}]{s['folds_pos']}/{s['n_folds']}{star}"

def fp(s):
    if s is None: return "(thin)"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    return f"Δ{s['mean_diff']:+.3f}[{s['ci'][0]:+.2f},{s['ci'][1]:+.2f}]{s['folds_pos']}/{s['n_folds']}{star}"


RESULTS = {"config": {"folds": folds, "early": sorted(EARLY), "late": sorted(LATE)}}

# ================================================================== A. ADAPTIVE GAIN
print("\n================= A. REGIME-ADAPTIVE GAIN (tune EARLY, test LATE, phase-averaged) =================")
NO_SMOOTH = book_netmaps(SIG)
FIXED = {a: book_netmaps(dense_ema_vec(SIG, const_alpha(a))) for a in (0.95, 0.90, 0.85, 0.80, 0.70, 0.60)}
_log("fixed-alpha books done")

# candidate adaptive configs: smooth harder when calm (a_calm), lighter/off when volatile (a_vol >= a_calm)
THR_Q = (40, 55, 70)                       # early-fold rvol percentile for the "high-vol" cut
A_CALMS = (0.60, 0.70, 0.80)
A_VOLS = (0.90, 1.00)
adaptive_books = {}
for thrq, ac, av in itertools.product(THR_Q, A_CALMS, A_VOLS):
    if av < ac: continue
    thr = float(np.percentile(rvol_early, thrq))
    key = (thrq, ac, av)
    adaptive_books[key] = book_netmaps(dense_ema_vec(SIG, adaptive_alpha(ac, av, thr)))
_log(f"{len(adaptive_books)} adaptive books done")

RESULTS["A_adaptive"] = {"fixed": {}, "adaptive": {}, "no_smooth": {}}
for lab in FOCUS:
    print(f"\n  ---- {lab} ----")
    ns_e = summ(NO_SMOOTH[lab], EARLY); ns_l = summ(NO_SMOOTH[lab], LATE)
    print(f"    no-smooth          early {fb(ns_e)}   LATE {fb(ns_l)}")
    RESULTS["A_adaptive"]["no_smooth"][lab] = {"early": ns_e, "late": ns_l}
    # best fixed alpha by EARLY mean
    best_fa = max(FIXED, key=lambda a: (summ(FIXED[a][lab], EARLY) or {"mean": -9})["mean"])
    fe = summ(FIXED[best_fa][lab], EARLY); fl = summ(FIXED[best_fa][lab], LATE)
    fl_d = paired(FIXED[best_fa][lab], NO_SMOOTH[lab], LATE)
    print(f"    best FIXED a={best_fa:.2f}   early {fb(fe)}   LATE {fb(fl)}   LATE vs no-smooth {fp(fl_d)}")
    RESULTS["A_adaptive"]["fixed"][lab] = {"best_alpha": best_fa, "early": fe, "late": fl, "late_vs_nosmooth": fl_d}
    # best adaptive by EARLY mean
    best_ad = max(adaptive_books, key=lambda k: (summ(adaptive_books[k][lab], EARLY) or {"mean": -9})["mean"])
    ae = summ(adaptive_books[best_ad][lab], EARLY); al = summ(adaptive_books[best_ad][lab], LATE)
    al_vs_fixed = paired(adaptive_books[best_ad][lab], FIXED[best_fa][lab], LATE)
    al_vs_ns = paired(adaptive_books[best_ad][lab], NO_SMOOTH[lab], LATE)
    print(f"    best ADAPTIVE {best_ad}  early {fb(ae)}   LATE {fb(al)}")
    print(f"        LATE adaptive vs best-fixed {fp(al_vs_fixed)}    vs no-smooth {fp(al_vs_ns)}")
    RESULTS["A_adaptive"]["adaptive"][lab] = {"best_cfg": list(best_ad), "early": ae, "late": al,
                                              "late_vs_fixed": al_vs_fixed, "late_vs_nosmooth": al_vs_ns}

# ================================================================== B. HORIZON x REGIME (is harvest-faster a Q-response?)
print("\n================= B. HORIZON x VOL-REGIME  (reb2 vs reb4 within vol tertiles) =================")
NS2 = book_netmaps(SIG, reb=2); NS4 = book_netmaps(SIG, reb=4)
# vol tertiles over all obs hours (descriptive here; regime split, not a tuned param)
rv = np.array([RVOL[int(h)] for h in base_hours if np.isfinite(RVOL[int(h)])])
qlo, qhi = np.nanpercentile(rv, [33.3, 66.6])
def volset(which):
    return set(int(h) for h in base_hours if np.isfinite(RVOL[int(h)]) and
               (RVOL[int(h)] <= qlo if which == "calm" else RVOL[int(h)] > qhi if which == "vol" else qlo < RVOL[int(h)] <= qhi))
RESULTS["B_horizon"] = {}
for lab in FOCUS:
    print(f"\n  ---- {lab}: reb2 - reb4 net-per-hr, by vol regime ----")
    RESULTS["B_horizon"][lab] = {}
    for reg in ("calm", "mid", "vol"):
        hs = volset(reg)
        # align reb2/reb4 on the hours each actually rebalances within the regime; paired where common
        s2 = summ(NS2[lab], set(folds)) if False else None
        common = sorted(h for h in set(NS2[lab]) & set(NS4[lab]) if h in hs)
        if len(common) < 12:
            print(f"    {reg:4s}: thin"); continue
        harr = np.array(common, dtype=np.int64)
        d2 = np.array([NS2[lab][h] for h in common]); d4 = np.array([NS4[lab][h] for h in common])
        diff = d2 - d4; ci = CB._dayblock_ci(diff, harr, hours)
        pf = {}
        for h in common: pf.setdefault(hour_month_all[int(h)], []).append(NS2[lab][h] - NS4[lab][h])
        pfm = {m: float(np.mean(v)) for m, v in pf.items()}; st = ADJ.sign_test(list(pfm.values()))
        star = "*" if ci[0] > 0 else ("-" if ci[1] < 0 else " ")
        print(f"    {reg:4s}: reb2 {d2.mean():+.2f}  reb4 {d4.mean():+.2f}  Δ(reb2-reb4) {diff.mean():+.3f}"
              f"[{ci[0]:+.2f},{ci[1]:+.2f}]{st['n_pos']}/{st['n']}{star} n={len(common)}")
        RESULTS["B_horizon"][lab][reg] = {"reb2": float(d2.mean()), "reb4": float(d4.mean()),
                                          "diff": float(diff.mean()), "ci": list(ci),
                                          "folds_pos": st["n_pos"], "n_folds": st["n"], "n": len(common)}

(OUT / "adfilter_regime_Q_adaptive.json").write_text(json.dumps(RESULTS, indent=2, default=float))
_log("wrote adfilter_regime_Q_adaptive.json")
print("\nIf Δ(reb2-reb4) is POSITIVE and larger in VOL than CALM => harvest-faster IS a Q-response to state drift.")
