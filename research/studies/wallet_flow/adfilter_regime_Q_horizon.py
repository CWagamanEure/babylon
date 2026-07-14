"""
adfilter_regime_Q_horizon — pin the harvest-horizon (Q-axis) optimum and confirm the vol-scaling of the reb2>reb4 gap.

Part A of the swarm showed the SMOOTHING gain (R-axis) is a weak, non-adaptable lever; Part B showed reb2>>reb4
for maker and the gap GROWS with realized vol -> harvest-faster is the real Q-response. This nails the floor:
the reb ladder {1,2,3,4,6} pooled OOS (late folds), + the reb-k vs reb-4 gap by vol tertile across the ladder.

    .venv/bin/python -m research.studies.wallet_flow.adfilter_regime_Q_horizon
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)
CACHE = "data/derived/xsec_kalman/panel_cache.npz"; OUT = Path("data/derived/xsec_kalman")
FOCUS = ("taker_top_smallclip", "maker_earn_a30")
d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
folds = list(int(x) for x in d["folds"]); halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
SIG = np.full((N, n_alt), np.nan); obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]): SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
hm = {int(t): int(panel_month[int(t)]) for t in base_hours}
LATE = set(folds[-3:]); ALLF = set(folds)

def build_rvol(K):
    rm = np.full(N, np.nan)
    for h in base_hours:
        t = int(h); lo = max(0, t - K)
        if t - lo < max(6, K // 2): continue
        with np.errstate(invalid="ignore"): pc = np.nanstd(resid_alt[lo:t], axis=0)
        v = np.nanmean(pc)
        if np.isfinite(v): rm[t] = v
    return rm
RVOL = build_rvol(24)
rv = np.array([RVOL[int(h)] for h in base_hours if np.isfinite(RVOL[int(h)])])
qlo, qhi = np.nanpercentile(rv, [33.3, 66.6])

def book_netmaps(M, reb):
    net = {lab: {} for lab in FOCUS}; FVr = S0.fwd_sum(resid_alt, reb)
    for ph in range(reb):
        grid = base_hours[ph::reb]; xs_arr, fvb, elig = {}, {}, {}
        for t in grid:
            ti = int(t); row = M[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4: continue
            xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}; elig[ti] = set(range(n_alt))
        keys = np.array(sorted(xs_arr), dtype=np.int64)
        if len(keys) < 8: continue
        sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
        if len(sim["hr"]) < 8: continue
        for lab in FOCUS:
            mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
            netph, hrs = CB.scenario_net_series(sim, reb, fee, mode, mult, hs_default)
            for h, v in zip(hrs, netph): net[lab][int(h)] = float(v)
    return net

def summ(vmap, foldset, hs_subset=None):
    hs = np.array([h for h in sorted(vmap) if hm[int(h)] in foldset and (hs_subset is None or h in hs_subset)], dtype=np.int64)
    if len(hs) < 12: return None
    vals = np.array([vmap[int(h)] for h in hs]); ci = CB._dayblock_ci(vals, hs, hours)
    pf = {}
    for h in hs: pf.setdefault(hm[int(h)], []).append(vmap[int(h)])
    pfm = {m: float(np.mean(v)) for m, v in pf.items()}; st = ADJ.sign_test(list(pfm.values()))
    return {"mean": float(vals.mean()), "ci": list(ci), "n": int(len(hs)), "folds_pos": st["n_pos"], "n_folds": st["n"]}

def fb(s):
    if s is None: return "(thin)"
    star = "*" if s["ci"][0] > 0 else ("-" if s["ci"][1] < 0 else " ")
    return f"{s['mean']:+.2f}[{s['ci'][0]:+.1f},{s['ci'][1]:+.1f}]{s['folds_pos']}/{s['n_folds']}{star}"

REBS = (1, 2, 3, 4, 6)
BOOKS = {reb: book_netmaps(SIG, reb) for reb in REBS}
_log("reb ladder booked")
RESULTS = {"rebs": list(REBS)}

print("\n========== REB LADDER (no-smooth) — pooled ALL folds & LATE-fold OOS ==========")
RESULTS["ladder"] = {}
for lab in FOCUS:
    print(f"\n  ---- {lab} (net bp/hr) ----")
    RESULTS["ladder"][lab] = {}
    for reb in REBS:
        a = summ(BOOKS[reb][lab], ALLF); l = summ(BOOKS[reb][lab], LATE)
        print(f"    reb{reb}:  all {fb(a)}    LATE {fb(l)}")
        RESULTS["ladder"][lab][reb] = {"all": a, "late": l}

print("\n========== reb-k vs reb4 gap BY VOL TERTILE (all folds) — the Q-scaling ==========")
def volset(which):
    return set(int(h) for h in base_hours if np.isfinite(RVOL[int(h)]) and
               (RVOL[int(h)] <= qlo if which == "calm" else RVOL[int(h)] > qhi if which == "vol" else qlo < RVOL[int(h)] <= qhi))
RESULTS["gap_by_vol"] = {}
for lab in FOCUS:
    print(f"\n  ---- {lab}: (reb_k - reb4) net by vol regime ----")
    RESULTS["gap_by_vol"][lab] = {}
    for reb in (1, 2, 3):
        row = {}
        cells = []
        for reg in ("calm", "mid", "vol"):
            hs = volset(reg)
            common = sorted(h for h in set(BOOKS[reb][lab]) & set(BOOKS[4][lab]) if h in hs)
            if len(common) < 12: cells.append(f"{reg}:thin"); continue
            harr = np.array(common, dtype=np.int64)
            diff = np.array([BOOKS[reb][lab][h] - BOOKS[4][lab][h] for h in common])
            ci = CB._dayblock_ci(diff, harr, hours)
            pf = {}
            for h in common: pf.setdefault(hm[int(h)], []).append(BOOKS[reb][lab][h] - BOOKS[4][lab][h])
            st = ADJ.sign_test([float(np.mean(v)) for v in pf.values()])
            star = "*" if ci[0] > 0 else ("-" if ci[1] < 0 else " ")
            cells.append(f"{reg}:{diff.mean():+.2f}[{ci[0]:+.1f},{ci[1]:+.1f}]{st['n_pos']}/{st['n']}{star}")
            row[reg] = {"diff": float(diff.mean()), "ci": list(ci), "folds_pos": st["n_pos"], "n_folds": st["n"]}
        print(f"    reb{reb}-reb4:  " + "   ".join(cells))
        RESULTS["gap_by_vol"][lab][reb] = row

(OUT / "adfilter_regime_Q_horizon.json").write_text(json.dumps(RESULTS, indent=2, default=float))
_log("wrote adfilter_regime_Q_horizon.json")
