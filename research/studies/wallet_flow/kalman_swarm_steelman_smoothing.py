"""
kalman_swarm_steelman_smoothing — STEELMAN attack on Result 11's negative.

Result 11 tested ONE crude filter: fixed-alpha EMA on the residualized signal LEVEL, coarse grid
alpha in {1,.6,.35,.2}, then re-rank. It found net monotonically worse (gross decayed faster than
turnover savings) and called it a method-scoped negative. This script attacks the CONSTRUCTION:

  1. SMOOTHING SPACE: smooth the cross-sectional RANK, or the cross-sectional Z-score (scale-free)
     each hour, then re-rank -- not the raw level whose cross-sectional scale drifts hour to hour.
  2. FINE ALPHA: interior optimum just below 1? sweep alpha in 0.75..0.98 (finer than coarse grid).
  3. MEMBERSHIP HYSTERESIS (the RIGHT turnover lever, not staling the signal): rank the FRESH signal
     but widen the hold-band q2 so a held name is retained until it falls out of a wider band --
     directly cuts boundary churn while entries use the freshest rank.  (uses CB.simulate_raw q1,q2.)
  4. MIN-HOLDING-PERIOD: custom held-book (validated == simulate_raw at min_hold=1) that force-keeps a
     name for >=H rebalances -- a pure turnover cut on a FRESH signal.
  5. JOINT smoothing x harvest horizon: smoothing lags ~1/alpha hours; sweep reb in {2,3,4,6,8} x alpha.
  6. Risk-adjusted: report net Sharpe (mean/std of per-step net) and day-block CI, not just the mean.

ALL filters strictly causal (signal at hours <= t only). Rebalance grid FROZEN to the baseline
observed-hour grid (base_hours[::reb]); every variant compared on identical timestamps. Any tuned
parameter is an in-sample search -> reported as a CANDIDATE, robustness required across a RANGE.

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_steelman_smoothing
"""
from __future__ import annotations
import time
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow.xsec_kalman import ema_smooth, CACHE

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")

# ------------------------------------------------------------------ load cache -------------------
d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
full_set = set(range(n_alt))

# dense fresh-signal matrix + frozen observed-hour grid
SIG = np.full((N, n_alt), np.nan)
obs_hours = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs_hours.add(int(R[i]))
base_hours = np.array(sorted(obs_hours), dtype=np.int64)

# regime split (mid-dispersion), thresholds from all observed hours (matches xsec_kalman)
dlo, dhi = np.nanpercentile(disp[np.isfinite(disp)], [33.3, 66.6])

FVr_cache = {}
def fvr(reb):
    if reb not in FVr_cache:
        FVr_cache[reb] = S0.fwd_sum(resid_alt, reb)
    return FVr_cache[reb]


# ------------------------------------------------------------------ scale-free signal transforms -
def to_rank(SIGm):
    """per-hour cross-sectional rank in [-0.5,0.5] among observed names; NaN where unobserved."""
    out = np.full_like(SIGm, np.nan)
    for t in range(SIGm.shape[0]):
        row = SIGm[t]; fin = np.isfinite(row); n = int(fin.sum())
        if n < 2: continue
        vals = row[fin]
        rk = np.argsort(np.argsort(vals)).astype(float)
        out[t, np.nonzero(fin)[0]] = rk / (n - 1) - 0.5
    return out

def to_z(SIGm):
    """per-hour cross-sectional z-score among observed names; NaN where unobserved."""
    out = np.full_like(SIGm, np.nan)
    for t in range(SIGm.shape[0]):
        row = SIGm[t]; fin = np.isfinite(row); n = int(fin.sum())
        if n < 2: continue
        vals = row[fin]; mu = vals.mean(); sd = vals.std()
        if sd <= 0: continue
        out[t, np.nonzero(fin)[0]] = (vals - mu) / sd
    return out


# ------------------------------------------------------------------ min-hold custom book ----------
def simulate_minhold(hours_list, xs_arr, fv_by_hour, halfspread, hs_default, reb, q1, q2,
                     elig_by_hour, min_hold):
    """Replicates CB.simulate_raw EXACTLY at min_hold<=1; for min_hold>1 a held name is force-kept for
    at least min_hold rebalances (turnover cut on a FRESH signal). Same cost accounting as simulate_raw."""
    reb_hours = hours_list[::reb]
    held_long, held_short = set(), set()
    age_l, age_s = {}, {}                       # rebalances since entry
    out = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    for t in reb_hours:
        names, sc = xs_arr[t]
        if elig_by_hour is not None:
            k = np.array([nm in elig_by_hour[t] for nm in names])
            names, sc = names[k], sc[k]
        n = len(names)
        if n < 4:
            continue
        present = set(names.tolist())
        order = np.argsort(sc)
        k1 = max(1, int(round(q1 * n))); k2 = max(k1, int(round(q2 * n)))
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        # keep = in hold-band OR still under min_hold lock (and still present in universe)
        def keep(nm, band, age):
            return nm in present and (nm in band or age.get(nm, 10**9) < min_hold)
        new_long = {nm for nm in held_long if keep(nm, top_hold, age_l)}
        for nm in names[order[::-1]]:
            if len(new_long) >= k1: break
            if nm in top_entry and nm not in new_long: new_long.add(nm)
        new_short = {nm for nm in held_short if keep(nm, bot_hold, age_s)}
        for nm in names[order]:
            if len(new_short) >= k1: break
            if nm in bot_entry and nm not in new_short: new_short.add(nm)
        K = max(1, min(len(new_long), len(new_short)))
        traded = (new_long ^ held_long) | (new_short ^ held_short)
        lf = [fv_by_hour[t].get(nm, np.nan) for nm in new_long]
        sf = [fv_by_hour[t].get(nm, np.nan) for nm in new_short]
        lf = [x for x in lf if np.isfinite(x)]; sf = [x for x in sf if np.isfinite(x)]
        # advance ages
        na = {}; na2 = {}
        for nm in new_long: na[nm] = (age_l.get(nm, 0) + 1) if nm in held_long else 1
        for nm in new_short: na2[nm] = (age_s.get(nm, 0) + 1) if nm in held_short else 1
        age_l, age_s = na, na2
        if not lf or not sf:
            held_long, held_short = new_long, new_short; continue
        gross = float(np.mean(lf) - np.mean(sf))
        n_tr = len(traded); hs_sum = sum(halfspread.get(nm, hs_default) for nm in traded)
        out["hr"].append(int(t)); out["gross"].append(gross)
        out["ntrade"].append(n_tr / K); out["hs"].append(hs_sum / K); out["turn"].append(n_tr / (2 * K))
        held_long, held_short = new_long, new_short
    return {k: np.array(v, dtype=float) for k, v in out.items()}


# ------------------------------------------------------------------ evaluate one book -------------
def eval_book(m, reb, q1=0.10, q2=0.15, regime="all", min_hold=1):
    """m = dense signal matrix [N,n_alt]. Returns per-FOCUS-scenario stats + gross/turnover."""
    base_h = base_hours[::reb]
    FVr = fvr(reb)
    hour_month = {int(t): int(panel_month[int(t)]) for t in base_h}
    mid_ok = {int(t): (dlo < disp[int(t)] <= dhi) for t in base_h}
    xs_arr, fvb, elig = {}, {}, {}
    for t in base_h:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4: continue
        xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
    keys = np.array(sorted(xs_arr), dtype=np.int64)
    if len(keys) < 8: return None
    if min_hold > 1:
        sim = simulate_minhold(keys, xs_arr, fvb, halfspread, hs_default, 1, q1, q2, elig, min_hold)
    else:
        sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, q1, q2, elig)
    if len(sim["hr"]) < 8: return None
    hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
    res = {"n_steps": int(len(hrs)), "gross_bp_per_hr": float((sim["gross"] / reb).mean()),
           "mean_turnover": float(sim["turn"].mean()), "scenarios": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS: continue
        netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, hs_default)
        ci95 = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        st = ADJ.sign_test(list(pf.values()))
        sharpe = float(netph.mean() / netph.std()) if netph.std() > 0 else float("nan")
        res["scenarios"][lab] = {"net": float(netph.mean()), "ci95": ci95,
                                 "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                 "n_folds": len(pf), "sign_p": st["p"], "sharpe": sharpe,
                                 "per_fold": pf}
    return res


def fmt(res, tag=""):
    if res is None: return f"   (thin) {tag}"
    cols = []
    for lab in FOCUS:
        sc = res["scenarios"][lab]; lo, hi = sc["ci95"]
        star = "*" if lo > 0 else ("-" if hi < 0 else " ")
        cols.append(f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['folds_pos']}/{sc['n_folds']}{star}sh{sc['sharpe']:+.2f}")
    return f"g{res['gross_bp_per_hr']:>+6.2f} t{res['mean_turnover']:>4.2f}  " + "  ".join(cols) + f"  {tag}"


HDR = f"{'':38}" + "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>34}" for l in FOCUS)


def main():
    print("FOCUS scenarios:", "  ".join(FOCUS))
    print("legend: net[CIlo,CIhi]folds+  *=CI>0  -=CI<0  sh=step-Sharpe\n")

    # ---------- 0. baseline reproduction ----------
    print("="*60, "\n0. BASELINE REPRODUCTION (fresh signal, reb4, q .10/.15)\n", "="*60)
    print(HDR)
    base = eval_book(SIG, 4)
    print("baseline reb4          ", fmt(base))
    print("  -> must match: maker_a30 ~+4.35, taker_smallclip ~+1.42\n")

    # ---------- 1. smoothing SPACE: level vs rank vs z, fine alpha ----------
    print("="*60, "\n1. SMOOTHING SPACE x FINE ALPHA (reb4)\n", "="*60)
    print(HDR)
    RANK = to_rank(SIG); Z = to_z(SIG)
    for alpha in (0.98, 0.95, 0.90, 0.85, 0.75, 0.60):
        for space, base_mat in (("level", SIG), ("rank", RANK), ("zscore", Z)):
            m = ema_smooth(base_mat, alpha, 24)
            print(f"{space:>6} a{alpha:<5}          ", fmt(eval_book(m, 4)))
        print()

    # ---------- 2. membership HYSTERESIS: fresh signal, wider hold-band q2 ----------
    print("="*60, "\n2. HYSTERESIS via hold-band q2 (FRESH signal, reb4, entry q1=.10)\n", "="*60)
    print(HDR)
    for q2 in (0.15, 0.18, 0.20, 0.25, 0.30, 0.40):
        print(f"q1=.10 q2={q2:<5}        ", fmt(eval_book(SIG, 4, q1=0.10, q2=q2)), f"(q2={q2})")
    print()

    # ---------- 3. MIN-HOLDING-PERIOD (validate == baseline at 1) ----------
    print("="*60, "\n3. MIN-HOLDING-PERIOD (FRESH signal, reb4)\n", "="*60)
    print(HDR)
    for mh in (1, 2, 3, 4, 6):
        r = eval_book(SIG, 4, min_hold=mh)
        tag = " <VALIDATE==baseline" if mh == 1 else ""
        print(f"min_hold={mh}            ", fmt(r), tag)
    print()

    # ---------- 4. JOINT smoothing x harvest horizon ----------
    print("="*60, "\n4. JOINT: rank-EMA alpha x rebalance horizon reb\n", "="*60)
    print(HDR)
    for reb in (2, 3, 4, 6, 8):
        # fresh (no smoothing) at this reb, then rank-EMA at a couple alphas
        print(f"reb{reb} fresh            ", fmt(eval_book(SIG, reb)))
        for alpha in (0.90, 0.75):
            m = ema_smooth(RANK, alpha, 24)
            print(f"reb{reb} rankEMA a{alpha}    ", fmt(eval_book(m, reb)))
        print()

    # ---------- 5. best turnover-cutter head-to-head, MID regime ----------
    print("="*60, "\n5. MID-DISPERSION regime (hysteresis + min-hold, reb4)\n", "="*60)
    print(HDR)
    print("mid fresh baseline     ", fmt(eval_book(SIG, 4, regime="mid")))
    for q2 in (0.20, 0.30):
        print(f"mid q2={q2}            ", fmt(eval_book(SIG, 4, q2=q2, regime="mid")))
    for mh in (2, 3):
        print(f"mid min_hold={mh}        ", fmt(eval_book(SIG, 4, min_hold=mh, regime="mid")))
    print()

    _log("done")


if __name__ == "__main__":
    main()
