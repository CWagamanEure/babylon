"""
adfilter_regime_Q_diag — REGIME / PROCESS-NOISE (Q) lens on the xsec selection filter.

R-drivers say "the MEASUREMENT is noisy -> smooth MORE (low Kalman gain / low alpha)."
Q-drivers are the opposite: "the true STATE is DRIFTING fast -> trust new obs MORE -> smooth LESS (high gain / high alpha)."

alpha in the EMA is the observation weight == the Kalman gain:  alpha=1.0 -> no smoothing (all obs);
alpha<1 -> smooth (weight the prior).  High-R regime wants LOW alpha; high-Q regime wants HIGH alpha.

THE R-vs-Q TEST (the whole point):  within a regime bucket, does a FIXED denoise (alpha=0.9) HELP or HURT?
  - HELPS (IC up, gross up)  => measurement noise; the regime is an R-DRIVER (smooth more here).
  - HURTS (IC down, gross down) => the true state moved; the regime is a Q-DRIVER (smooth less / harvest fresh here).
  (A NET-only gain with FLAT/DOWN gross+IC is a pure turnover/cost effect, NOT a state-estimation R-driver -> flagged.)

Sections:
  1. DISPERSION decomposed into R-part vs Q-part: within each disp tertile, IC-delta + gross/net-delta of smoothing.
  2. CANDIDATE Q-DRIVERS (all CAUSAL, <=t): dispersion CHANGE (not level), realized-vol regime, |disp| accel.
     For each: conditional forward IC in each regime bucket + smoothing-helps(R)/hurts(Q) via IC-delta and gross-delta.
  3. OOS: discover on EARLY folds (202512-202602), confirm the sign on LATE folds (202604-202606).
  All magnitudes PHASE-AVERAGED over the 4 reb-4 phases.  IC uses all observed hours (phase-free).

    .venv/bin/python -m research.studies.wallet_flow.adfilter_regime_Q_diag
"""
from __future__ import annotations
import json, time, math
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
OUT = Path("data/derived/xsec_kalman"); OUT.mkdir(parents=True, exist_ok=True)
REB = 4
DENOISE_A = 0.90                    # the banked fixed denoise (dense_ema alpha)
FOCUS = ("taker_top_smallclip", "maker_earn_a30")

# ------------------------------------------------------------------ load cache
d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
folds = list(int(x) for x in d["folds"])
halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}

SIG = np.full((N, n_alt), np.nan)
obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
FVr = S0.fwd_sum(resid_alt, REB)                       # [N,n_alt] forward reb-hour resid return (frac)
hour_month_all = {int(t): int(panel_month[int(t)]) for t in base_hours}
EARLY = set(folds[:3]); LATE = set(folds[-3:])         # 202512-202602 vs 202604-202606
_log(f"cache: {len(base_hours)} obs hours, {n_alt} alts, folds={folds}  early={sorted(EARLY)} late={sorted(LATE)}")


def dense_ema(M, alpha):
    """Causal per-column EMA, blends across gaps (== banked denoise). alpha=1 -> passthrough."""
    if alpha >= 1.0:
        return M
    N, A = M.shape
    out = np.full((N, A), np.nan); prev = np.full(A, np.nan)
    for t in range(N):
        obs_t = M[t]; has = np.isfinite(obs_t)
        newv = np.where(np.isfinite(prev), alpha * obs_t + (1.0 - alpha) * prev, obs_t)
        prev = np.where(has, newv, prev)
        out[t] = np.where(has, prev, np.nan)
    return out


SIG_SM = dense_ema(SIG, DENOISE_A)


# ------------------------------------------------------------------ per-hour cross-sectional Spearman IC
def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 8: return np.nan
    ra = np.argsort(np.argsort(a[m])).astype(float); rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = math.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / den) if den > 0 else np.nan


def hour_ics(M, hrs):
    """per-hour cross-sectional IC of matrix M vs forward reb-return, for a set of hours. returns {hour: ic}."""
    out = {}
    for t in hrs:
        ic = _spear(M[t], FVr[t])
        if np.isfinite(ic): out[int(t)] = ic
    return out


def ic_summary(icmap, hrs_subset=None):
    hs = [h for h in icmap if (hrs_subset is None or h in hrs_subset)]
    if len(hs) < 20: return None
    vals = np.array([icmap[h] for h in hs])
    pf = {}
    for h in hs:
        pf.setdefault(hour_month_all[h], []).append(icmap[h])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}
    st = ADJ.sign_test(list(pfm.values()))
    return {"ic": float(vals.mean()), "n_hours": len(hs), "per_fold": pfm,
            "folds_pos": st["n_pos"], "n_folds": st["n"], "sign_p": st["p"]}


def paired_ic_delta(icmap_sm, icmap_raw, hrs_subset=None):
    """PAIRED per-hour IC(smoothed) - IC(raw). sign of mean => smoothing helps(+,R) / hurts(-,Q)."""
    common = [h for h in icmap_sm if h in icmap_raw and (hrs_subset is None or h in hrs_subset)]
    if len(common) < 20: return None
    diff = np.array([icmap_sm[h] - icmap_raw[h] for h in common])
    pf = {}
    for h in common:
        pf.setdefault(hour_month_all[h], []).append(icmap_sm[h] - icmap_raw[h])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}
    st = ADJ.sign_test(list(pfm.values()))
    return {"mean_dIC": float(diff.mean()), "n_hours": len(common), "per_fold": pfm,
            "folds_pos": st["n_pos"], "n_folds": st["n"], "sign_p": st["p"]}


# ------------------------------------------------------------------ phase-averaged booking
def book_netmaps(M, uni=None):
    """Book matrix M over ALL 4 reb-4 phases; return {label: {hour: net_per_hr}}, {hour: turnover}, {hour: gross_per_hr}."""
    uni = set(range(n_alt)) if uni is None else set(uni)
    net = {lab: {} for lab in FOCUS}; turn = {}; gross = {}
    for ph in range(REB):
        grid = base_hours[ph::REB]
        xs_arr, fvb, elig = {}, {}, {}
        for t in grid:
            ti = int(t); row = M[ti]
            nm = np.array([a for a in np.nonzero(np.isfinite(row))[0] if a in uni], dtype=int)
            if len(nm) < 4: continue
            xs_arr[ti] = (nm, row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
            elig[ti] = uni
        keys = np.array(sorted(xs_arr), dtype=np.int64)
        if len(keys) < 8: continue
        sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
        if len(sim["hr"]) < 8: continue
        for h, t_, g in zip(sim["hr"], sim["turn"], sim["gross"]):
            turn[int(h)] = float(t_); gross[int(h)] = float(g) / REB
        for lab in FOCUS:
            mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
            netph, hrs = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
            for h, v in zip(hrs, netph):
                net[lab][int(h)] = float(v)
    return net, turn, gross


def book_summary(vmap, hrs_subset=None):
    hs = np.array([h for h in sorted(vmap) if (hrs_subset is None or h in hrs_subset)], dtype=np.int64)
    if len(hs) < 12: return None
    vals = np.array([vmap[int(h)] for h in hs])
    ci = CB._dayblock_ci(vals, hs, hours)
    pf = {}
    for h in hs:
        pf.setdefault(hour_month_all[int(h)], []).append(vmap[int(h)])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}
    st = ADJ.sign_test(list(pfm.values()))
    return {"mean": float(vals.mean()), "ci": list(ci), "n": int(len(hs)),
            "folds_pos": st["n_pos"], "n_folds": st["n"], "sign_p": st["p"]}


def book_paired(vmap_sm, vmap_raw, hrs_subset=None):
    common = sorted(set(vmap_sm) & set(vmap_raw) & (set(hrs_subset) if hrs_subset is not None else set(vmap_sm)))
    if len(common) < 12: return None
    hs = np.array(common, dtype=np.int64)
    diff = np.array([vmap_sm[h] - vmap_raw[h] for h in common])
    ci = CB._dayblock_ci(diff, hs, hours)
    pf = {}
    for h in common:
        pf.setdefault(hour_month_all[int(h)], []).append(vmap_sm[h] - vmap_raw[h])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}
    st = ADJ.sign_test(list(pfm.values()))
    return {"mean_diff": float(diff.mean()), "ci": list(ci), "n": int(len(hs)),
            "folds_pos": st["n_pos"], "n_folds": st["n"], "sign_p": st["p"]}


def _f_ic(s):
    if s is None: return "   (thin)"
    return f"IC={s['ic']:+.4f} {s['folds_pos']}/{s['n_folds']} n={s['n_hours']}"

def _f_dic(s):
    if s is None: return "   (thin)"
    tag = "R(helps)" if s["mean_dIC"] > 0 else "Q(hurts)"
    return f"dIC={s['mean_dIC']:+.4f} {s['folds_pos']}/{s['n_folds']} p={s['sign_p']} {tag}"

def _f_book(s):
    if s is None: return "(thin)"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    return f"{s['mean']:+.2f}[{s['ci'][0]:+.1f},{s['ci'][1]:+.1f}]{s['folds_pos']}/{s['n_folds']}{star}"

def _f_bpair(s):
    if s is None: return "(thin)"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    tag = "sm>base" if s["mean_diff"] > 0 else "sm<base"
    return f"{s['mean_diff']:+.3f}[{s['ci'][0]:+.2f},{s['ci'][1]:+.2f}]{s['folds_pos']}/{s['n_folds']}{star} {tag}"


# ================================================================== precompute IC maps + book maps once
_log("computing raw + smoothed per-hour IC maps ...")
IC_RAW = hour_ics(SIG, base_hours)
IC_SM = hour_ics(SIG_SM, base_hours)
_log("booking baseline + smoothed (phase-averaged) ...")
NET_B, TURN_B, GROSS_B = book_netmaps(SIG)
NET_S, TURN_S, GROSS_S = book_netmaps(SIG_SM)
_log("book maps done")

RESULTS = {"config": {"denoise_alpha": DENOISE_A, "reb": REB, "folds": folds,
                      "early": sorted(EARLY), "late": sorted(LATE)}}


def tertile_labels(vals_by_hour, hrs):
    v = np.array([vals_by_hour[h] for h in hrs])
    lo, hi = np.nanpercentile(v[np.isfinite(v)], [33.3, 66.6])
    lab = {}
    for h in hrs:
        x = vals_by_hour[h]
        lab[h] = "lo" if x <= lo else ("hi" if x > hi else "mid")
    return lab, float(lo), float(hi)


def run_regime(name, valmap, note=""):
    """Full R/Q diagnostic for a causal regime observable valmap:{hour:value}."""
    print(f"\n================= REGIME: {name} =================  {note}")
    hrs = [h for h in base_hours if h in valmap and np.isfinite(valmap[h])]
    lab, lo, hi = tertile_labels(valmap, hrs)
    print(f"  tertile thresholds: lo<= {lo:.5f}  hi> {hi:.5f}   (n={len(hrs)})")
    res = {"thresholds": [lo, hi], "note": note, "tertiles": {}}
    for tert in ("lo", "mid", "hi"):
        hset = set(h for h in hrs if lab[h] == tert)
        # signal quality (raw IC), and R/Q test (IC-delta from smoothing), full + OOS split
        ic_raw = ic_summary(IC_RAW, hset)
        dic_all = paired_ic_delta(IC_SM, IC_RAW, hset)
        dic_early = paired_ic_delta(IC_SM, IC_RAW, hset & set(h for h in hrs if hour_month_all[h] in EARLY))
        dic_late = paired_ic_delta(IC_SM, IC_RAW, hset & set(h for h in hrs if hour_month_all[h] in LATE))
        # deployable: gross-delta (signal realized) + net-delta (incl cost) from smoothing, phase-avg
        g_pair = book_paired(GROSS_S, GROSS_B, hset)
        net_pairs = {lab_: book_paired(NET_S[lab_], NET_B[lab_], hset) for lab_ in FOCUS}
        base_net = {lab_: book_summary(NET_B[lab_], hset) for lab_ in FOCUS}
        res["tertiles"][tert] = {"n_hours": len(hset), "ic_raw": ic_raw, "dIC_all": dic_all,
                                 "dIC_early": dic_early, "dIC_late": dic_late, "gross_diff": g_pair,
                                 "net_diff": {k: v for k, v in net_pairs.items()},
                                 "base_net": {k: v for k, v in base_net.items()}}
        print(f"  --- {tert.upper()} (n={len(hset)}) ---")
        print(f"      raw signal quality : {_f_ic(ic_raw)}")
        print(f"      R/Q (smooth dIC)   : ALL {_f_dic(dic_all)}")
        print(f"                           early {_f_dic(dic_early)}   late {_f_dic(dic_late)}")
        print(f"      gross delta (a0.9-base): {_f_bpair(g_pair)}")
        for lab_ in FOCUS:
            print(f"      {lab_:22s} base {_f_book(base_net[lab_])}  Δsmooth {_f_bpair(net_pairs[lab_])}")
    return res


# ================================================================== 1. DISPERSION LEVEL (R vs Q per tertile)
disp_map = {int(h): float(disp[int(h)]) for h in base_hours if np.isfinite(disp[int(h)])}
RESULTS["disp_level"] = run_regime("DISPERSION LEVEL", disp_map,
                                   note="reconcile: signal 2x in MID; denoise helps most in NOISY(hi)")

# ================================================================== 2. Q-DRIVER CANDIDATES (causal)
# 2a. dispersion CHANGE (fast): disp[t] - trailing mean(disp[t-K..t-1])
def build_change(K):
    dm = {}
    for h in base_hours:
        window = [disp[int(hh)] for hh in range(int(h) - K, int(h)) if 0 <= hh < N and np.isfinite(disp[int(hh)])]
        if len(window) >= max(4, K // 2) and np.isfinite(disp[int(h)]):
            dm[int(h)] = float(disp[int(h)] - np.mean(window))
    return dm
RESULTS["disp_change_24"] = run_regime("DISP CHANGE (level - trailing24)", build_change(24),
                                       note="fast rise in dispersion = state churning? Q-candidate")
RESULTS["disp_absaccel_24"] = run_regime("DISP |CHANGE| (magnitude of move)",
                                         {h: abs(v) for h, v in build_change(24).items()},
                                         note="large |Δdisp| either sign = regime transition, Q-candidate")

# 2b. realized-vol regime (temporal): market vol = mean_a trailing-std(resid_alt) over K hours, causal
def build_rvol(K):
    # per-coin trailing std of resid over the K hours strictly before t, averaged across coins present
    rm = {}
    for h in base_hours:
        t = int(h); lo = max(0, t - K)
        if t - lo < max(6, K // 2): continue
        block = resid_alt[lo:t]                 # strictly < t
        with np.errstate(invalid="ignore"):
            per_coin = np.nanstd(block, axis=0)
        v = np.nanmean(per_coin)
        if np.isfinite(v): rm[t] = float(v)
    return rm
RESULTS["rvol_24"] = run_regime("REALIZED VOL regime (trailing24 resid vol)", build_rvol(24),
                                note="high market vol: state drifts faster (Q) or noisier measure (R)?")
RESULTS["rvol_6"] = run_regime("REALIZED VOL regime (trailing6 fast)", build_rvol(6),
                               note="fast vol regime")

(OUT / "adfilter_regime_Q_diag.json").write_text(json.dumps(RESULTS, indent=2, default=float))
_log("wrote adfilter_regime_Q_diag.json")
print("\nLEGEND: dIC>0 & gross_diff>0 => R-driver (smooth MORE here).  dIC<0 & gross_diff<0 => Q-driver (smooth LESS/harvest fresh).")
print("        NET-up with gross flat/down = pure turnover/cost effect (not a state-estimation R-driver).")
