"""
kalman_swarm_turnover_reducers — TURNOVER-MECHANISM & RISK-ADJUSTED audit of Result 11.

Result 11 conflated "smooth the signal" (which STALES it) with "cut turnover" (rank-churn at the decile
boundary). This script tests NON-smoothing turnover reducers on a FRESH (un-staled) signal:
  (A1) wider hysteresis hold-band  q2 ∈ {0.15,0.20,0.25,0.30,0.35}   (baseline q2=0.15)
  (A2) minimum-holding-period / rank-dwell  N ∈ {0,1,2,3,4}          (a name locked ≥N rebalances)
  (A3) turnover cap  M ∈ {inf,3,2,1} swaps/side/rebalance            (only trade top-M conviction changes)
and the risk-adjusted framing:
  (B) net Sharpe (annualized, per-step) + day-block CI for baseline vs EMA vs the (A) reducers.

Everything is rebuilt from data/derived/xsec_kalman/panel_cache.npz on the FROZEN baseline rebalance grid
(sorted observed hours[::REB]); only the book rule differs. Costs via CB.scenario_net_series. Strictly
causal (rules use only signal ≤ t). Any tuned knob is an in-sample candidate -> reported across a RANGE.

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_turnover_reducers
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_kalman as K

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

REB = 4
CACHE = Path("data/derived/xsec_kalman/panel_cache.npz")
OUT = Path("data/derived/xsec_kalman")
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
ANN = np.sqrt(8760.0 / REB)          # per-step (REB-hour) return -> annualized Sharpe factor


# ---------------------------------------------------------------------------------------------------
# General held long-short book with pluggable membership rule. Cost accounting IDENTICAL to
# CB.simulate_raw (gross, ntrade=n_traded/K, hs=Σ hs_traded/K, turn=n_traded/2K) so CB.scenario_net_series
# applies unchanged. rule ∈ {"hyst","dwell","cap"}.
# ---------------------------------------------------------------------------------------------------
def simulate_rule(hours_list, xs_arr, fv_by_hour, halfspread, hs_default, q1, q2, elig_by_hour,
                  rule="hyst", dwell_N=0, cap_M=10**9):
    reb_hours = hours_list
    held_long, held_short = set(), set()
    age_long, age_short = {}, {}          # rebalances a name has been continuously held
    out = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    for t in reb_hours:
        names, sc = xs_arr[t]
        if elig_by_hour is not None:
            k = np.array([nm in elig_by_hour[t] for nm in names])
            names, sc = names[k], sc[k]
        n = len(names)
        if n < 4:
            continue
        order = np.argsort(sc)                       # ascending score
        k1 = max(1, int(round(q1 * n))); k2 = max(k1, int(round(q2 * n)))
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        score = {int(names[j]): float(sc[j]) for j in range(n)}

        if rule in ("hyst", "dwell"):
            lock_long = {nm for nm in held_long if dwell_N > 0 and age_long.get(nm, 0) < dwell_N}
            lock_short = {nm for nm in held_short if dwell_N > 0 and age_short.get(nm, 0) < dwell_N}
            # retain: signal-hold (in hold band) OR dwell-locked; then top up with best fresh entries to k1
            new_long = {nm for nm in held_long if nm in top_hold} | (lock_long & set(map(int, names)))
            for nm in names[order[::-1]]:
                if len(new_long) >= k1: break
                if nm in top_entry and nm not in new_long: new_long.add(int(nm))
            new_short = {nm for nm in held_short if nm in bot_hold} | (lock_short & set(map(int, names)))
            for nm in names[order]:
                if len(new_short) >= k1: break
                if nm in bot_entry and nm not in new_short: new_short.add(int(nm))
        elif rule == "cap":
            # 1) baseline hysteresis desired book
            des_long = {nm for nm in held_long if nm in top_hold}
            for nm in names[order[::-1]]:
                if len(des_long) >= k1: break
                if nm in top_entry and nm not in des_long: des_long.add(int(nm))
            des_short = {nm for nm in held_short if nm in bot_hold}
            for nm in names[order]:
                if len(des_short) >= k1: break
                if nm in bot_entry and nm not in des_short: des_short.add(int(nm))
            # 2) limit to cap_M highest-conviction swaps per side (keep size = held size, ~k1)
            def cap_side(held, des, want_high):
                ent = des - held; exi = held - des
                if not ent or not exi: return set(held) if (des == held) else set(des) if (not held) else set(held)
                # highest-conviction entries: extreme score (high for long, low for short)
                ent_sorted = sorted(ent, key=lambda nm: score.get(nm, 0.0), reverse=want_high)
                # least-conviction exits: names furthest into the wrong zone (low score for long / high for short)
                exi_sorted = sorted(exi, key=lambda nm: score.get(nm, 0.0), reverse=not want_high)
                ns = min(cap_M, len(ent), len(exi))
                keep = set(held) - set(exi_sorted[:ns]) | set(ent_sorted[:ns])
                return keep
            new_long = cap_side(held_long, des_long, True) if held_long else set(des_long)
            new_short = cap_side(held_short, des_short, False) if held_short else set(des_short)
        else:
            raise ValueError(rule)

        K_ = max(1, min(len(new_long), len(new_short)))
        traded = (new_long ^ held_long) | (new_short ^ held_short)
        lf = [fv_by_hour[t].get(nm, np.nan) for nm in new_long]
        sf = [fv_by_hour[t].get(nm, np.nan) for nm in new_short]
        lf = [x for x in lf if np.isfinite(x)]; sf = [x for x in sf if np.isfinite(x)]
        if not lf or not sf:
            held_long, held_short = new_long, new_short; continue
        gross = float(np.mean(lf) - np.mean(sf))
        n_tr = len(traded); hs_sum = sum(halfspread.get(nm, hs_default) for nm in traded)
        out["hr"].append(int(t)); out["gross"].append(gross)
        out["ntrade"].append(n_tr / K_); out["hs"].append(hs_sum / K_); out["turn"].append(n_tr / (2 * K_))
        # age bookkeeping
        na = {};
        for nm in new_long: na[nm] = age_long.get(nm, 0) + 1 if nm in held_long else 1
        age_long = na
        na = {}
        for nm in new_short: na[nm] = age_short.get(nm, 0) + 1 if nm in held_short else 1
        age_short = na
        held_long, held_short = new_long, new_short
    return {k: np.array(v, dtype=float) for k, v in out.items()}


def sharpe(netph):
    if len(netph) < 8 or np.std(netph) == 0: return float("nan")
    return float(netph.mean() / netph.std(ddof=1) * ANN)


def main():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}

    SIG = np.full((N, n_alt), np.nan); obs_hours = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs_hours.add(int(R[i]))
    base_hours = np.array(sorted(obs_hours), dtype=np.int64)
    reb_grid = base_hours[::REB]
    hour_month = {int(t): int(panel_month[int(t)]) for t in reb_grid}
    FVr = S0.fwd_sum(resid_alt, REB)

    dlo, dhi = np.nanpercentile(disp[np.isfinite(disp)], [33.3, 66.6])
    mid_ok = {int(t): (dlo < disp[int(t)] <= dhi) for t in reb_grid}
    full_set = set(range(n_alt))

    def build_inputs(smoothed=None, regime="all"):
        m = smoothed if smoothed is not None else SIG
        xs_arr, fvb, elig, keys = {}, {}, {}, []
        for t in reb_grid:
            ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4: continue
            xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
            elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
            keys.append(ti)
        return np.array(sorted(keys), dtype=np.int64), xs_arr, fvb, elig

    def evaluate(sim):
        if len(sim["hr"]) < 8: return None
        hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
        out = {"n_steps": int(len(hrs)), "gross_bp_per_hr": float((sim["gross"] / REB).mean()),
               "mean_turnover": float(sim["turn"].mean()), "scenarios": {}}
        for lab, mult, fee, mode in CB.SCENARIOS:
            netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
            ci95 = CB._dayblock_ci(netph, hrs, hours)
            pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
            out["scenarios"][lab] = {"net": float(netph.mean()), "ci95": list(ci95),
                                     "sharpe": sharpe(netph),
                                     "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                     "n_folds": len(pf), "sign_p": ADJ.sign_test(list(pf.values()))["p"]}
        return out

    def line(tag, cell):
        if cell is None: print(f"{tag:26s} (thin)"); return
        cols = []
        for lab in FOCUS:
            sc = cell["scenarios"][lab]; lo, hi = sc["ci95"]
            star = "*" if lo > 0 else ("-" if hi < 0 else " ")
            cols.append(f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['folds_pos']}/{sc['n_folds']}{star}S{sc['sharpe']:+4.1f}")
        print(f"{tag:26s} g{cell['gross_bp_per_hr']:+6.3f} t{cell['mean_turnover']:5.2f}  " + "  ".join(cols))

    results = {"reb": REB, "regimes": {}}
    for regime in ("all", "mid"):
        print(f"\n================================ REGIME = {regime.upper()} ================================")
        print(f"{'config':26s} {'gross':>7} {'turn':>6}  " +
              "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>34}" for l in FOCUS))
        rr = {}
        keys, xs_arr, fvb, elig = build_inputs(None, regime)

        # ---- BASELINE (validate against CB) ----
        base = evaluate(simulate_rule(keys, xs_arr, fvb, halfspread, hs_default, 0.10, 0.15, elig, "hyst", 0))
        rr["baseline"] = base; line("baseline (q2=.15,N0)", base)

        # ---- A1: wider hysteresis hold-band ----
        for q2 in (0.20, 0.25, 0.30, 0.35):
            c = evaluate(simulate_rule(keys, xs_arr, fvb, halfspread, hs_default, 0.10, q2, elig, "hyst", 0))
            rr[f"hyst_q2_{q2}"] = c; line(f"A1 hyst q2={q2:.2f}", c)

        # ---- A2: min-holding-period / dwell ----
        for Ndw in (1, 2, 3, 4):
            c = evaluate(simulate_rule(keys, xs_arr, fvb, halfspread, hs_default, 0.10, 0.15, elig, "dwell", Ndw))
            rr[f"dwell_N{Ndw}"] = c; line(f"A2 dwell N={Ndw}", c)

        # ---- A3: turnover cap M swaps/side ----
        for M in (3, 2, 1):
            c = evaluate(simulate_rule(keys, xs_arr, fvb, halfspread, hs_default, 0.10, 0.15, elig, "cap", 0, M))
            rr[f"cap_M{M}"] = c; line(f"A3 cap M={M}", c)

        # ---- EMA (Result 11 smoothing) for head-to-head Sharpe. stale>=1 so the blend actually bites
        #      (with stale=0 every hour reinitializes since gap=1>0 -> no smoothing). ----
        for alpha in (0.60, 0.35):
            sm = K.ema_smooth(SIG, alpha, 8)
            k2, xs2, fv2, el2 = build_inputs(sm, regime)
            c = evaluate(simulate_rule(k2, xs2, fv2, halfspread, hs_default, 0.10, 0.15, el2, "hyst", 0))
            rr[f"ema_a{alpha}_s8"] = c; line(f"EMA a={alpha} s8 (smooth)", c)

        results["regimes"][regime] = rr

    # focused taker sign-test summary (the cross-independent-unit gate)
    print("\n---- TAKER cross-fold detail (net, CI, folds+, sign_p, Sharpe) ----")
    for regime in ("all", "mid"):
        print(f"  [{regime}]")
        for cfg in ("baseline", "hyst_q2_0.3", "hyst_q2_0.35", "cap_M2", "cap_M1", "dwell_N2", "ema_a0.6_s8"):
            c = results["regimes"][regime].get(cfg)
            if c is None: continue
            for lab in ("taker_top_smallclip", "taker_top_impact"):
                sc = c["scenarios"][lab]
                print(f"    {cfg:14s} {lab:20s} net{sc['net']:+5.2f} CI[{sc['ci95'][0]:+4.1f},{sc['ci95'][1]:+4.1f}] "
                      f"{sc['folds_pos']}/{sc['n_folds']}+ signp={sc['sign_p']:.3f} S{sc['sharpe']:+4.1f} turn{c['mean_turnover']:.2f}")

    (OUT / "turnover_reducers.json").write_text(json.dumps(results, indent=2, default=float))
    print("\nLegend: net[CI_lo,CI_hi]folds+  '*'=CI>0  '-'=CI<0  S=annualized net Sharpe.  g=gross/hr t=turnover.")
    print(f"Baseline must match Result 11: taker_smallclip +1.42, maker_a30 +4.35 (all-regime);"
          f" taker_smallclip +2.75, maker_a30 +5.39 (mid).")
    _log(f"wrote {OUT/'turnover_reducers.json'}")


if __name__ == "__main__":
    main()
