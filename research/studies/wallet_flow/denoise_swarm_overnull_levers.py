"""
denoise_swarm_overnull_levers — OVER-NULL RECOGNITION pass on the denoise swarm's 2 open candidates
(CLAIM B) + a scan for any OTHER implicitly-nulled lever. Applies the 4-pillar over-null gate to each:
  (1) point estimate + day-block CI  (2) positive-control MDE  (3) cross-fold sign test
  (4) construction-conservatism (phase de-confound / walk-forward / combine-with-denoise).

Everything rebuilt from data/derived/xsec_kalman/panel_cache.npz on the FROZEN observed-hours grid; only the
book rule / signal / grid-phase differs. Costs via CB.scenario_net_series (identical accounting). Strictly
causal (dense_ema + hysteresis use signal <= t only). No cache/frozen-file writes.

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_overnull_levers
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
OUT = Path("data/derived/xsec_kalman")
Z975, Z80 = 1.959964, 0.841621           # MDE = (z_.975 + z_.80) * SE  (two-sided a=0.05, 80% power)


# ------------------------------------------------------------------ signal filter (EXACT decisive construction)
def dense_ema(SIG, alpha):
    if alpha >= 1.0:
        return SIG
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        newv = np.where(np.isfinite(prev), alpha * obs + (1.0 - alpha) * prev, obs)
        prev = np.where(has, newv, prev)
        m[t] = np.where(has, prev, np.nan)
    return m


# ------------------------------------------------------------------ generic held book on an explicit grid
def simulate_grid(grid_hours, m, FVr, halfspread, hs_default, n_alt, q1, q2, mid_ok, regime,
                  weight="equal", coin_vol=None):
    """Held long-short decile book on an explicit rebalance grid (any phase). Cost accounting matches
    CB.simulate_raw for weight='equal'. weight in {'equal','conviction','volscale'} changes name weights
    (and turnover = sum|dw| for the non-equal modes). Returns per-step arrays keyed to rebalance hour."""
    full = set(range(n_alt))
    held_long, held_short = set(), set()
    wL_prev, wS_prev = {}, {}
    out = {"hr": [], "gross": [], "ntrade": [], "hs": [], "turn": []}
    for t in grid_hours:
        ti = int(t)
        if regime == "mid" and not mid_ok[ti]:
            continue
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        sc = row[nm]
        names = nm.astype(int); order = np.argsort(sc)
        n = len(names)
        k1 = max(1, int(round(q1 * n))); k2 = max(k1, int(round(q2 * n)))
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        score = {int(names[j]): float(sc[j]) for j in range(n)}
        new_long = {nm2 for nm2 in held_long if nm2 in top_hold}
        for a in names[order[::-1]]:
            if len(new_long) >= k1: break
            if a in top_entry and a not in new_long: new_long.add(int(a))
        new_short = {nm2 for nm2 in held_short if nm2 in bot_hold}
        for a in names[order]:
            if len(new_short) >= k1: break
            if a in bot_entry and a not in new_short: new_short.add(int(a))
        K = max(1, min(len(new_long), len(new_short)))
        fvL = {a: FVr[ti, a] * 1e4 for a in new_long if np.isfinite(FVr[ti, a])}
        fvS = {a: FVr[ti, a] * 1e4 for a in new_short if np.isfinite(FVr[ti, a])}
        if not fvL or not fvS:
            held_long, held_short = new_long, new_short; wL_prev, wS_prev = {}, {}; continue

        def weights(side_set, want_high):
            members = [a for a in side_set if a in (fvL if want_high else fvS)]
            if not members: return {}
            if weight == "equal":
                w = {a: 1.0 / len(members) for a in members}
            elif weight == "conviction":
                mag = np.array([abs(score[a]) for a in members]); mag = np.where(mag > 0, mag, 1e-9)
                w = {a: float(v) for a, v in zip(members, mag / mag.sum())}
            elif weight == "volscale":
                iv = np.array([1.0 / max(coin_vol[a], 1e-9) for a in members]); w = {a: float(v) for a, v in zip(members, iv / iv.sum())}
            else:
                raise ValueError(weight)
            return w
        wL = weights(new_long, True); wS = weights(new_short, False)
        gross = float(sum(wL[a] * fvL[a] for a in wL) - sum(wS[a] * fvS[a] for a in wS))

        if weight == "equal":
            traded = (new_long ^ held_long) | (new_short ^ held_short)
            n_tr = len(traded); hs_sum = sum(halfspread.get(a, hs_default) for a in traded)
            out["ntrade"].append(n_tr / K); out["hs"].append(hs_sum / K); out["turn"].append(n_tr / (2 * K))
        else:
            dw = 0.0; hs_sum = 0.0
            for a in set(wL) | set(wL_prev):
                d = abs(wL.get(a, 0.0) - wL_prev.get(a, 0.0)); dw += d; hs_sum += d * halfspread.get(a, hs_default)
            for a in set(wS) | set(wS_prev):
                d = abs(wS.get(a, 0.0) - wS_prev.get(a, 0.0)); dw += d; hs_sum += d * halfspread.get(a, hs_default)
            out["ntrade"].append(dw); out["hs"].append(hs_sum); out["turn"].append(dw / 2)
        out["hr"].append(ti); out["gross"].append(gross)
        held_long, held_short = new_long, new_short; wL_prev, wS_prev = wL, wS
    return {k: np.array(v, dtype=float) for k, v in out.items()}


# ------------------------------------------------------------------ stats: net series -> point/CI/MDE/sign per fold
def dayblock_boot(vals, hrs, hours, panel_month, n=2000, seed=7):
    """Day-block bootstrap: return (mean, ci_lo, ci_hi, SE, MDE, folds_pos, n_folds, sign_p)."""
    if len(vals) < 8:
        return dict(net=float("nan"), ci=(float("nan"),) * 2, se=float("nan"), mde=float("nan"),
                    fp=0, nf=0, sign_p=None)
    days = (hours[hrs.astype(np.int64)] // 86400000).astype(np.int64); ud = np.unique(days)
    loc = {d: np.nonzero(days == d)[0] for d in ud}; rng = np.random.default_rng(seed); st = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        st.append(vals[np.concatenate([loc[ud[p]] for p in pick])].mean())
    s = np.array(st); se = float(s.std(ddof=1))
    shm = np.array([int(panel_month[int(h)]) for h in hrs])
    pf = {int(mm): float(vals[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
    stt = ADJ.sign_test(list(pf.values()))
    return dict(net=float(vals.mean()), ci=(float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))),
                se=se, mde=float((Z975 + Z80) * se), fp=int(sum(1 for v in pf.values() if v > 0)),
                nf=len(pf), sign_p=stt["p"], per_fold=pf)


def scen_stats(sim, reb, hours, panel_month, labs=FOCUS):
    hrs = sim["hr"].astype(np.int64)
    res = {"gross": float((sim["gross"] / reb).mean()), "turn": float(sim["turn"].mean()), "n": len(hrs)}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in labs: continue
        netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, hs_default=HS_DEF)
        res[lab] = dayblock_boot(netph, hrs, hours, panel_month)
    return res


def fmt(s):
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    return (f"{s['net']:+5.2f}[{s['ci'][0]:+4.1f},{s['ci'][1]:+4.1f}]{star} "
            f"MDE{s['mde']:4.1f} {s['fp']}/{s['nf']} p{s['sign_p'] if s['sign_p'] is not None else float('nan'):.3f}")


def pooled_phase_stats(sims, reb, hours, panel_month, labs=FOCUS):
    """Concatenate per-step net across ALL grid-phase offsets (phase-averaged), then CI/MDE/sign."""
    res = {"n_phase": len(sims)}
    grs = np.concatenate([s["gross"] / reb for s in sims]); turns = np.concatenate([s["turn"] for s in sims])
    res["gross"] = float(grs.mean()); res["turn"] = float(turns.mean())
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in labs: continue
        allnet = []; allhrs = []
        for s in sims:
            netph, _ = CB.scenario_net_series(s, reb, fee, mode, mult, hs_default=HS_DEF)
            allnet.append(netph); allhrs.append(s["hr"].astype(np.int64))
        netph = np.concatenate(allnet); hrs = np.concatenate(allhrs)
        res[lab] = dayblock_boot(netph, hrs, hours, panel_month)
    return res


# ================================================================== load
d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; HS_DEF = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
coin_vol = np.nanstd(resid_alt, axis=0)

SIG = np.full((N, n_alt), np.nan); obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
dlo, dhi = np.nanpercentile(disp[np.isfinite(disp)], [33.3, 66.6])
mid_ok = {int(t): bool(np.isfinite(disp[int(t)]) and dlo < disp[int(t)] <= dhi) for t in base_hours}
folds = sorted(int(x) for x in d["folds"])
DENOISE = dense_ema(SIG, 0.90)
RESULTS = {}
_log(f"loaded: {len(base_hours)} obs hours, {n_alt} alts, folds {folds}")


def fv_of(reb):
    return S0.fwd_sum(resid_alt, reb)


# ================================================================== 0. BASELINE GATE
print("\n============ 0. BASELINE GATE (reb4, phase0, no smoothing) ============")
sim = simulate_grid(base_hours[::4], SIG, fv_of(4), halfspread, HS_DEF, n_alt, 0.10, 0.15, mid_ok, "all")
b = scen_stats(sim, 4, hours, panel_month)
for lab in FOCUS:
    print(f"  {lab:22s} {fmt(b[lab])}")
gate = abs(b["taker_top_smallclip"]["net"] - 1.42) < 0.15 and abs(b["maker_earn_a30"]["net"] - 4.35) < 0.15
print(f"  GATE taker_smallclip {b['taker_top_smallclip']['net']:+.2f}(want+1.42) "
      f"maker_a30 {b['maker_earn_a30']['net']:+.2f}(want+4.35) -> {'PASS' if gate else 'FAIL'}")
assert gate, "baseline mismatch"
RESULTS["baseline_reb4"] = {l: b[l] for l in FOCUS}


# ================================================================== 1. HYSTERESIS TAKER (CLAIM B-1)
print("\n============ 1. HYSTERESIS q2 -> TAKER leg  (4-pillar over-null) ============")
print("   leg: net[CIlo,CIhi] MDE folds+ sign_p   (grid=phase0 reb4, FRESH signal a=1)")
RESULTS["hyst_taker"] = {}
for regime in ("all", "mid"):
    print(f"  --- regime={regime} ---")
    for q2 in (0.15, 0.30, 0.35):
        sim = simulate_grid(base_hours[::4], SIG, fv_of(4), halfspread, HS_DEF, n_alt, 0.10, q2, mid_ok, regime)
        st = scen_stats(sim, 4, hours, panel_month)
        tag = "base" if q2 == 0.15 else f"q2={q2}"
        RESULTS["hyst_taker"][f"{regime}_{tag}"] = {l: st[l] for l in FOCUS}
        print(f"    {tag:7s} turn{st['turn']:.2f} | tk_sc {fmt(st['taker_top_smallclip'])} | "
              f"tk_imp {fmt(st['taker_top_impact'])} | mk_a30 {fmt(st['maker_earn_a30'])}")

# --- powered version A: combine denoise (a=0.90) WITH wider hold-band, mid regime ---
print("\n  --- powered: DENOISE(a=0.90) + hysteresis, mid regime (does denoise lift & tighten the taker leg?) ---")
RESULTS["hyst_taker_denoise"] = {}
for q2 in (0.15, 0.30, 0.35):
    sim = simulate_grid(base_hours[::4], DENOISE, fv_of(4), halfspread, HS_DEF, n_alt, 0.10, q2, mid_ok, "mid")
    st = scen_stats(sim, 4, hours, panel_month)
    RESULTS["hyst_taker_denoise"][f"q2={q2}"] = {l: st[l] for l in FOCUS}
    print(f"    denoise q2={q2} turn{st['turn']:.2f} | tk_sc {fmt(st['taker_top_smallclip'])} | "
          f"tk_imp {fmt(st['taker_top_impact'])} | mk_a30 {fmt(st['maker_earn_a30'])}")

# --- powered version B: frozen-threshold walk-forward (freeze q2 on EARLY, apply LATE) ---
print("\n  --- walk-forward: pick q2* = argmax taker_smallclip on EARLY 4 folds, apply to LATE 3 (mid) ---")
early, late = set(folds[:4]), set(folds[4:])
q2s = [0.15, 0.20, 0.25, 0.30, 0.35]
def taker_net_on(foldset, q2, sig=SIG):
    sim = simulate_grid(base_hours[::4], sig, fv_of(4), halfspread, HS_DEF, n_alt, 0.10, q2, mid_ok, "mid")
    hrs = sim["hr"].astype(np.int64); shm = np.array([int(panel_month[int(h)]) for h in hrs])
    lab = "taker_top_smallclip"; mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
    netph, _ = CB.scenario_net_series(sim, 4, fee, mode, mult, HS_DEF)
    keep = np.array([m in foldset for m in shm])
    return float(netph[keep].mean()) if keep.sum() else float("nan")
q2star = max(q2s, key=lambda q: taker_net_on(early, q))
wf = {"q2star": q2star, "EARLY_base": taker_net_on(early, 0.15), "EARLY_q2star": taker_net_on(early, q2star),
      "LATE_base": taker_net_on(late, 0.15), "LATE_q2star": taker_net_on(late, q2star)}
print(f"    q2*={q2star} (argmax EARLY taker_sc) | EARLY base {wf['EARLY_base']:+.2f} q2* {wf['EARLY_q2star']:+.2f}"
      f" | LATE base {wf['LATE_base']:+.2f} q2* {wf['LATE_q2star']:+.2f}"
      f"  -> {'WF holds' if wf['LATE_q2star'] > wf['LATE_base'] else 'WF fails'}")
RESULTS["hyst_taker_walkforward"] = wf


# ================================================================== 2. PHASE-AVERAGED REB (CLAIM B-2)
print("\n============ 2. PHASE-AVERAGED harvest reb  (grid-phase de-confound) ============")
print("   per reb: run ALL offsets base_hours[o::reb], pool per-step net (phase-avg) -> CI/MDE/sign")
RESULTS["phase_reb"] = {}
for reb in (2, 3, 4, 6):
    print(f"  --- reb={reb} ({reb} phase offsets) ---")
    perphase = {}
    sims = []
    for o in range(reb):
        grid = base_hours[o::reb]
        sim = simulate_grid(grid, SIG, fv_of(reb), halfspread, HS_DEF, n_alt, 0.10, 0.15, mid_ok, "all")
        if len(sim["hr"]) >= 8:
            sims.append(sim)
            st = scen_stats(sim, reb, hours, panel_month, labs=("maker_earn_a30", "taker_top_smallclip"))
            perphase[o] = {"maker": st["maker_earn_a30"]["net"], "taker": st["taker_top_smallclip"]["net"]}
    pavg = pooled_phase_stats(sims, reb, hours, panel_month)
    RESULTS["phase_reb"][f"reb{reb}"] = {"per_phase": perphase, "phase_avg": {l: pavg[l] for l in FOCUS},
                                         "gross": pavg["gross"], "turn": pavg["turn"]}
    mk = [f"{perphase[o]['maker']:+.2f}" for o in sorted(perphase)]
    print(f"    per-phase maker_a30: [{', '.join(mk)}]  (offset0 is the [::reb] grid)")
    print(f"    PHASE-AVG turn{pavg['turn']:.2f} | mk_a30 {fmt(pavg['maker_earn_a30'])} | "
          f"mk_a50 {fmt(pavg['maker_earn_a50'])} | tk_sc {fmt(pavg['taker_top_smallclip'])}")


# ================================================================== 3. OTHER LEVERS
print("\n============ 3. OTHER LEVERS (implicitly-nulled?) ============")
RESULTS["other"] = {}

# 3a. denoise + longer harvest matched to alpha half-life (~3.6h). reb in {4,5,6}, denoise a=0.90, phase-averaged.
print("  --- 3a. DENOISE(a=0.90) x harvest reb, PHASE-AVERAGED (alpha HL~3.6h => is reb>4 better?) ---")
for reb in (4, 5, 6):
    sims = [simulate_grid(base_hours[o::reb], DENOISE, fv_of(reb), halfspread, HS_DEF, n_alt, 0.10, 0.15, mid_ok, "all")
            for o in range(reb)]
    sims = [s for s in sims if len(s["hr"]) >= 8]
    pavg = pooled_phase_stats(sims, reb, hours, panel_month)
    RESULTS["other"][f"denoise_reb{reb}_phaseavg"] = {l: pavg[l] for l in FOCUS}
    print(f"    denoise reb{reb} turn{pavg['turn']:.2f} | mk_a30 {fmt(pavg['maker_earn_a30'])} | "
          f"tk_sc {fmt(pavg['taker_top_smallclip'])}")

# 3b. conviction-weight vs vol-scale vs equal (GROSS-first scan; reb4 phase0, mid+all)
print("  --- 3b. WEIGHTING lever: conviction / vol-scale vs equal (net; reb4 phase0) ---")
for regime in ("all", "mid"):
    print(f"    regime={regime}:")
    for wmode in ("equal", "conviction", "volscale"):
        sim = simulate_grid(base_hours[::4], SIG, fv_of(4), halfspread, HS_DEF, n_alt, 0.10, 0.15, mid_ok, regime,
                            weight=wmode, coin_vol=coin_vol)
        st = scen_stats(sim, 4, hours, panel_month)
        RESULTS["other"][f"weight_{wmode}_{regime}"] = {l: st[l] for l in FOCUS}
        print(f"      {wmode:11s} g{st['gross']:+5.2f} turn{st['turn']:.2f} | mk_a30 {fmt(st['maker_earn_a30'])} | "
              f"tk_sc {fmt(st['taker_top_smallclip'])}")

# 3c. denoise + conviction combined, mid
print("  --- 3c. DENOISE(a=0.90) + conviction-weight, mid ---")
sim = simulate_grid(base_hours[::4], DENOISE, fv_of(4), halfspread, HS_DEF, n_alt, 0.10, 0.15, mid_ok, "mid",
                    weight="conviction", coin_vol=coin_vol)
st = scen_stats(sim, 4, hours, panel_month)
RESULTS["other"]["denoise_conviction_mid"] = {l: st[l] for l in FOCUS}
print(f"      denoise+conv g{st['gross']:+5.2f} turn{st['turn']:.2f} | mk_a30 {fmt(st['maker_earn_a30'])} | "
      f"tk_sc {fmt(st['taker_top_smallclip'])}")


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "denoise_swarm_overnull.json").write_text(json.dumps(RESULTS, indent=2, default=float))
_log("wrote denoise_swarm_overnull.json")
print("\nLegend: net[CIlo,CIhi] MDE folds+ sign_p.  '*'=CI>0 '-'=CI<0.  MDE=(1.96+0.84)*SE (80% power).")
