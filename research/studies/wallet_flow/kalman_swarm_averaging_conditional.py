"""
kalman_swarm_averaging_conditional — AVERAGING-AWAY-SIGNAL lens on Result 11.

Result 11 judged smoothing on POOLED-across-everything net means and found it monotonically worse.
This script asks: does the pooled mean BURY a conditional benefit of smoothing in a subset?

Lenses:
  L1  TURNOVER regime  — split rebalance steps by baseline name-turnover; does smoothing help net on the
                         high-churn steps (where the spread taxes every entry/exit) even if it hurts overall?
  L2  DISPERSION regime — split by the `disp` array (noisy vs calm hours); a filter should matter most in
                         high-dispersion hours.
  L3  per-COIN          — rerun the book on the noisiest / highest-spread subuniverse; does smoothing help there?
  L4  per-FOLD          — is there ANY fold where smoothing clearly helps (pooled monotone-worse may mask het)?
  L5  per-WALLET sparsity — is the "carry-forward inert because 43.5/45 alts trade every hour" true PER WALLET?
                         (structural: quantify aggregate density, flag whether the wallet-level test needs a rebuild)

Method: rebalance grid FROZEN to baseline (sorted(observed hours)[::4]); every variant compared on identical
timestamps — only the smoothed signal differs. For every conditional win we report the PAIRED difference
(smoothed - baseline) per-step net, day-block CI on that difference, and per-fold sign — an honest over-carry gate.

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_averaging_conditional
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow.xsec_kalman import ema_smooth

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

REB = 4
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
# smoothing variants: (alpha, stale). alpha<1 = exponential blend; stale>0 = carry belief across quiet hours.
VARIANTS = [(0.60, 0), (0.35, 0), (0.20, 0), (0.60, 8), (0.35, 8), (0.35, 24), (0.20, 24)]
OUT = Path("data/derived/xsec_kalman")

d = np.load("data/derived/xsec_kalman/panel_cache.npz", allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}

SIG = np.full((N, n_alt), np.nan); obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
reb_grid = base_hours[::REB]
hour_month = {int(t): int(panel_month[int(t)]) for t in reb_grid}
FVr = S0.fwd_sum(resid_alt, REB)
full_set = set(range(n_alt))


def run_sim(m, universe=None, elig_hours=None):
    """Run the book on signal matrix m. universe=None -> all 45 names; else restrict names to that set.
    elig_hours=None -> all hours eligible; else only those hours. Returns sim + aligned metadata."""
    uni = full_set if universe is None else set(universe)
    xs_arr, fvb, elig = {}, {}, {}
    for t in reb_grid:
        ti = int(t); row = m[ti]
        nm = np.array([a for a in np.nonzero(np.isfinite(row))[0] if a in uni], dtype=int)
        if len(nm) < 4: continue
        xs_arr[ti] = (nm, row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = uni if (elig_hours is None or ti in elig_hours) else set()
    keys = np.array(sorted(xs_arr), dtype=np.int64)
    if len(keys) < 8: return None
    sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
    if len(sim["hr"]) < 8: return None
    return sim


def net_by_hour(sim, lab):
    """Per-step net-per-hour series indexed by rebalance hour, for one scenario label."""
    mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
    netph, hrs = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
    return {int(h): float(v) for h, v in zip(hrs, netph)}


def summarize(net_map, hrs_subset=None):
    """Pooled net + day-block CI + per-fold sign over an (optional) subset of hours."""
    hrs = np.array([h for h in sorted(net_map) if (hrs_subset is None or h in hrs_subset)], dtype=np.int64)
    if len(hrs) < 8: return None
    vals = np.array([net_map[int(h)] for h in hrs])
    ci = CB._dayblock_ci(vals, hrs, hours)
    shm = np.array([hour_month[int(h)] for h in hrs])
    pf = {int(mm): float(vals[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
    st = ADJ.sign_test([v for v in pf.values()])
    return {"net": float(vals.mean()), "ci": ci, "fp": int(sum(1 for v in pf.values() if v > 0)),
            "nf": len(pf), "n": int(len(hrs)), "sign_p": float(st["p"]), "per_fold": pf}


def paired_diff(net_a, net_b, hrs_subset=None):
    """PAIRED (smoothed - baseline) per-step net difference on the common timestamps; day-block CI + per-fold."""
    common = sorted(set(net_a) & set(net_b) & (set(hrs_subset) if hrs_subset is not None else set(net_a) | set(net_b)))
    if hrs_subset is not None:
        common = [h for h in common if h in hrs_subset]
    if len(common) < 8: return None
    hrs = np.array(common, dtype=np.int64)
    diff = np.array([net_a[h] - net_b[h] for h in common])   # net_a = smoothed, net_b = baseline
    ci = CB._dayblock_ci(diff, hrs, hours)
    shm = np.array([hour_month[int(h)] for h in hrs])
    pf = {int(mm): float(diff[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
    st = ADJ.sign_test([v for v in pf.values()])
    return {"mean_diff": float(diff.mean()), "ci": ci, "fp": int(sum(1 for v in pf.values() if v > 0)),
            "nf": len(pf), "n": int(len(hrs)), "sign_p": float(st["p"])}


def fmt(s):
    if s is None: return "   (thin)"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    key = "net" if "net" in s else "mean_diff"
    return f"{s[key]:+6.3f}[{s['ci'][0]:+5.2f},{s['ci'][1]:+5.2f}]{s['fp']}/{s['nf']}{star} n={s['n']}"


# ------------------------------------------------------------------ build baseline + variant net maps
_log("building baseline + variant net maps ...")
base_sim = run_sim(SIG)
base_turn = {int(h): float(t) for h, t in zip(base_sim["hr"], base_sim["turn"])}
base_net = {lab: net_by_hour(base_sim, lab) for lab in FOCUS}

variant_net = {}
for (alpha, stale) in VARIANTS:
    m = ema_smooth(SIG, alpha, stale)
    sim = run_sim(m)
    variant_net[(alpha, stale)] = {lab: net_by_hour(sim, lab) for lab in FOCUS}
_log("done net maps")

RESULTS = {"baseline_pooled": {lab: summarize(base_net[lab]) for lab in FOCUS}}
print("\n============ BASELINE pooled (must match +1.42 / +4.35) ============")
for lab in FOCUS:
    print(f"  {lab:22s} {fmt(RESULTS['baseline_pooled'][lab])}")


# ------------------------------------------------------------------ L1 TURNOVER regime
print("\n============ L1  TURNOVER regime (split reb-steps by BASELINE name-turnover) ============")
tvals = np.array([base_turn[int(h)] for h in reb_grid if int(h) in base_turn])
thi = np.percentile(tvals, 66.6); tlo = np.percentile(tvals, 33.3)
hi_turn = set(int(h) for h in base_turn if base_turn[int(h)] > thi)
lo_turn = set(int(h) for h in base_turn if base_turn[int(h)] <= tlo)
print(f"  turnover tertiles: low<= {tlo:.2f}, high> {thi:.2f}  (n_hi={len(hi_turn)}, n_lo={len(lo_turn)})")
RESULTS["L1_turnover"] = {}
for lab in FOCUS:
    print(f"  -- {lab} --")
    b_hi = summarize(base_net[lab], hi_turn)
    print(f"     baseline HIGH-turn : {fmt(b_hi)}")
    for v in VARIANTS:
        s = summarize(variant_net[v][lab], hi_turn)
        pd_ = paired_diff(variant_net[v][lab], base_net[lab], hi_turn)
        RESULTS["L1_turnover"][f"{lab}|a{v[0]}s{v[1]}|hi"] = {"net": s, "diff": pd_}
        print(f"       a{v[0]} s{v[1]:<2d} HI net {fmt(s)}   diff(sm-base) {fmt(pd_)}")


# ------------------------------------------------------------------ L2 DISPERSION regime
print("\n============ L2  DISPERSION regime (split reb-steps by disp array) ============")
dvals = np.array([disp[int(h)] for h in reb_grid])
dhi = np.percentile(dvals, 66.6); dlo = np.percentile(dvals, 33.3)
hi_disp = set(int(h) for h in reb_grid if disp[int(h)] > dhi)
lo_disp = set(int(h) for h in reb_grid if disp[int(h)] <= dlo)
print(f"  disp tertiles: calm<= {dlo:.4f}, noisy> {dhi:.4f}  (n_noisy={len(hi_disp)}, n_calm={len(lo_disp)})")
RESULTS["L2_dispersion"] = {}
for lab in FOCUS:
    print(f"  -- {lab} --")
    for regname, hset in (("noisy", hi_disp), ("calm", lo_disp)):
        b = summarize(base_net[lab], hset)
        print(f"     baseline {regname:5s}: {fmt(b)}")
        for v in VARIANTS:
            s = summarize(variant_net[v][lab], hset)
            pd_ = paired_diff(variant_net[v][lab], base_net[lab], hset)
            RESULTS["L2_dispersion"][f"{lab}|a{v[0]}s{v[1]}|{regname}"] = {"net": s, "diff": pd_}
            print(f"       a{v[0]} s{v[1]:<2d} {regname:5s} net {fmt(s)}   diff {fmt(pd_)}")


# ------------------------------------------------------------------ L3 per-COIN (noisy subuniverse)
print("\n============ L3  per-COIN: noisy/high-spread subuniverse rerun ============")
# per-coin temporal resid volatility (noise) and half-spread
coin_vol = np.nanstd(resid_alt, axis=0)
rank_spread = np.argsort(-hs_arr)          # highest spread first
rank_vol = np.argsort(-coin_vol)           # noisiest first
RESULTS["L3_coin"] = {}
for uni_name, order in (("hi_spread", rank_spread), ("hi_vol", rank_vol)):
    for ktop in (22, 15):
        uni = set(int(x) for x in order[:ktop])
        bsim = run_sim(SIG, universe=uni)
        if bsim is None:
            print(f"  {uni_name} top{ktop}: thin"); continue
        bnet = {lab: net_by_hour(bsim, lab) for lab in FOCUS}
        print(f"  -- universe={uni_name} top{ktop} names --")
        for lab in FOCUS:
            b = summarize(bnet[lab])
            print(f"     {lab:22s} baseline {fmt(b)}")
            for v in VARIANTS[:4]:
                m = ema_smooth(SIG, v[0], v[1]); vsim = run_sim(m, universe=uni)
                if vsim is None: continue
                vn = net_by_hour(vsim, lab)
                s = summarize(vn); pd_ = paired_diff(vn, bnet[lab])
                RESULTS["L3_coin"][f"{uni_name}{ktop}|{lab}|a{v[0]}s{v[1]}"] = {"net": s, "diff": pd_}
                print(f"        a{v[0]} s{v[1]:<2d} net {fmt(s)}  diff {fmt(pd_)}")


# ------------------------------------------------------------------ L4 per-FOLD
print("\n============ L4  per-FOLD: smoothed vs baseline net, each fold ============")
folds = sorted(set(hour_month.values()))
RESULTS["L4_fold"] = {}
for lab in FOCUS:
    print(f"  -- {lab} --  (per-fold net: baseline -> best-smoothed diff)")
    base_pf = summarize(base_net[lab])["per_fold"]
    for v in VARIANTS:
        vpf = summarize(variant_net[v][lab])["per_fold"]
        diffs = {f: vpf.get(f, float('nan')) - base_pf.get(f, float('nan')) for f in folds}
        nwin = sum(1 for x in diffs.values() if x > 0)
        RESULTS["L4_fold"][f"{lab}|a{v[0]}s{v[1]}"] = {"base_pf": base_pf, "var_pf": vpf, "diff": diffs}
        ds = "  ".join(f"{f}:{diffs[f]:+.2f}" for f in folds)
        print(f"     a{v[0]} s{v[1]:<2d}  folds_smoothed>base {nwin}/{len(folds)}   [{ds}]")


# ------------------------------------------------------------------ L5 per-WALLET sparsity (structural)
print("\n============ L5  per-WALLET sparsity (structural diagnostic) ============")
names_per_hour = np.array([np.isfinite(SIG[int(h)]).sum() for h in reb_grid])
sig_density = np.isfinite(SIG[reb_grid]).mean()
# how often is a name dormant hour-to-hour (aggregate)?
gaps = []
for a in range(n_alt):
    col = np.isfinite(SIG[base_hours, a])
    idx = np.nonzero(col)[0]
    if len(idx) > 1:
        gaps.append(np.diff(idx))
gaps = np.concatenate(gaps) if gaps else np.array([1])
RESULTS["L5_sparsity"] = {"mean_names_per_reb_hour": float(names_per_hour.mean()),
                          "median_names_per_reb_hour": float(np.median(names_per_hour)),
                          "min_names_per_reb_hour": int(names_per_hour.min()),
                          "aggregate_sig_density": float(sig_density),
                          "mean_gap_between_obs_hours": float(gaps.mean()),
                          "frac_consecutive_gap1": float((gaps == 1).mean())}
print(f"  aggregate names observed per reb-hour: mean {names_per_hour.mean():.1f}/45  median {np.median(names_per_hour):.0f}  min {names_per_hour.min()}")
print(f"  aggregate SIG density (reb-hours x names finite): {sig_density:.3f}")
print(f"  aggregate inter-observation gap for a name: mean {gaps.mean():.2f} h, frac gap==1: {(gaps==1).mean():.3f}")
print("  => at the AGGREGATE (cohort) level the panel is dense: carry-forward IS inert as Result 11 said.")
print("  => the PER-WALLET signal is far sparser (each wallet trades few names/hour); testing wallet-level")
print("     smoothing requires smoothing q_trail BEFORE cohort aggregation -> needs the full xsec_..._book.run")
print("     pipeline (DuckDB, ~130s). Flagged as a distinct follow-up; not resolvable from this cache alone.")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "averaging_conditional.json").write_text(json.dumps(RESULTS, indent=2, default=float))
_log("wrote averaging_conditional.json")
print("\nLegend: net/diff [CI_lo,CI_hi] folds+/nfolds  '*'=CI>0  '-'=CI<0  ' '=straddles.  diff = smoothed - baseline.")
