"""
adfilter_token_reliability — PER-TOKEN RELIABILITY (R-driver) lens for the adaptive-R xsec filter swarm.

Hypothesis: some COINS carry a persistently noisier selection signal (higher observation-noise R). The filter
should distrust the signal on those coins (shrink toward the cross-sectional mean / raise effective R) before it
ranks the cross-section for the decile long-short book.

This script (cache-only: data/derived/xsec_kalman/panel_cache.npz) answers:
  1. CAUSAL rolling per-coin forward IC = Spearman(s_inf, forward-resid) within each coin over a trailing window.
     This is the per-coin inverse-R (high IC => low R => trust).
  2. Is per-coin reliability PERSISTENT? early-fold IC vs late-fold IC cross-coin, per-fold IC autocorrelation.
  3. Structural R-drivers: realized vol, impact half-spread, activity/liquidity proxy -> does higher vol / wider
     spread predict LOWER signal IC (higher R)? (funding/ADV flagged as an asset_ctx follow-up.)
  4. Adaptive per-coin gain: shrink / drop low-reliability coins BEFORE the cross-sectional rank. Discover the
     reliability ranking on EARLY folds (frozen) and on a trailing CAUSAL window; apply to LATE folds. Does the
     PHASE-AVERAGED decile book beat the uniform (all-coins, gain=1) baseline OOS?

GUARDRAILS: causal-only rolling stats; phase-average every booked magnitude (4 offsets of the reb-4 grid);
OOS split (discover early -> confirm late); report the # of coins / features / gain variants scanned (multiplicity).

    .venv/bin/python -m research.studies.wallet_flow.adfilter_token_reliability
"""
from __future__ import annotations
import json, time
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

CACHE = "data/derived/xsec_kalman/panel_cache.npz"
OUT = Path("data/derived/xsec_kalman")
REB = 4
H_IC = 4                       # horizon for the per-coin forward IC (matches H_TRAIN / REB)
FOCUS = ("taker_top_smallclip", "maker_earn_a30")   # the two deployable cost scenarios


# ----------------------------------------------------------------------------- rank / Spearman helpers
def rankdata(a):
    a = np.asarray(a, float)
    sorter = np.argsort(a, kind="mergesort")
    inv = np.empty(len(a), dtype=int); inv[sorter] = np.arange(len(a))
    a_srt = a[sorter]
    obs = np.r_[True, a_srt[1:] != a_srt[:-1]]
    dense = obs.cumsum()[inv]
    count = np.r_[np.nonzero(obs)[0], len(a)]
    return 0.5 * (count[dense] + count[dense - 1] + 1)

def spearman(x, y, nmin=8):
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < nmin: return np.nan, int(m.sum())
    rx, ry = rankdata(x[m]), rankdata(y[m])
    if rx.std() == 0 or ry.std() == 0: return np.nan, int(m.sum())
    return float(np.corrcoef(rx, ry)[0, 1]), int(m.sum())


# ----------------------------------------------------------------------------- load cache
d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
folds = sorted(int(x) for x in d["folds"])
EARLY = set(folds[:4]); LATE = set(folds[4:])
halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}

SIG = np.full((N, n_alt), np.nan); obs = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs.add(int(R[i]))
base_hours = np.array(sorted(obs), dtype=np.int64)
FVr = S0.fwd_sum(resid_alt, H_IC)            # 4h forward residual return
FVbp = FVr * 1e4
month_of = {int(t): int(panel_month[int(t)]) for t in base_hours}
_log(f"cache: {n_alt} coins, {len(base_hours)} obs hours, folds early={sorted(EARLY)} late={sorted(LATE)}")


# ============================================================================= 1. PER-COIN FORWARD IC
# For each coin: non-overlapping (::REB, per phase-0) obs hours where signal AND 4h-fwd return both finite.
def coin_obs(c, hset=None, stride=REB, phase=0):
    col_sig = SIG[base_hours, c]; col_fwd = FVbp[base_hours, c]
    ok = np.isfinite(col_sig) & np.isfinite(col_fwd)
    if hset is not None:
        ok &= np.array([month_of[int(t)] in hset for t in base_hours])
    idx = np.nonzero(ok)[0][phase::stride]                 # non-overlapping to avoid fwd-window autocorr
    return col_sig[idx], col_fwd[idx], base_hours[idx]

RESULTS = {"config": {"reb": REB, "h_ic": H_IC, "n_coins": n_alt,
                      "early_folds": sorted(EARLY), "late_folds": sorted(LATE)}}

print("\n============ 1. PER-COIN FORWARD IC (full-sample, non-overlapping 4h) ============")
coin_ic = {}
for c in range(n_alt):
    sg, fw, _ = coin_obs(c)
    ic, n = spearman(sg, fw)
    coin_ic[c] = (ic, n)
ic_full = np.array([coin_ic[c][0] for c in range(n_alt)])
order = np.argsort(ic_full)
print(f"  pooled cross-coin IC mean={np.nanmean(ic_full):+.4f}  median={np.nanmedian(ic_full):+.4f}  "
      f"sd={np.nanstd(ic_full):.4f}  (coins w/ IC>0: {int(np.nansum(ic_full>0))}/{n_alt})")
print("  weakest 6 coins:", [(int(c), round(float(ic_full[c]), 3)) for c in order[:6]])
print("  strongest 6 coins:", [(int(c), round(float(ic_full[c]), 3)) for c in order[-6:]])
RESULTS["per_coin_ic_full"] = {int(c): {"ic": float(coin_ic[c][0]), "n": coin_ic[c][1]} for c in range(n_alt)}


# ============================================================================= 2. PERSISTENCE
print("\n============ 2. PERSISTENCE OF PER-COIN RELIABILITY ============")
ic_early = np.array([spearman(*coin_obs(c, EARLY)[:2])[0] for c in range(n_alt)])
ic_late = np.array([spearman(*coin_obs(c, LATE)[:2])[0] for c in range(n_alt)])
rho_el, n_el = spearman(ic_early, ic_late, nmin=10)
# sign persistence: of coins with early IC in the low tertile, how many stay below-median late?
val = np.isfinite(ic_early) & np.isfinite(ic_late)
ie, il = ic_early[val], ic_late[val]
lo_thr = np.percentile(ie, 33.3); hi_thr = np.percentile(ie, 66.6)
lo_mask = ie <= lo_thr; hi_mask = ie >= hi_thr
late_med = np.median(il)
lo_stay = float(np.mean(il[lo_mask] < late_med)) if lo_mask.sum() else np.nan
hi_stay = float(np.mean(il[hi_mask] > late_med)) if hi_mask.sum() else np.nan
# quintile spread: late IC of bottom-early-tertile vs top-early-tertile coins
print(f"  cross-coin Spearman(IC_early, IC_late) = {rho_el:+.3f}  (n={n_el} coins)")
print(f"  bottom-early-tertile coins staying below-median late: {lo_stay:.2f}   "
      f"top-early-tertile staying above-median late: {hi_stay:.2f}")
print(f"  mean LATE IC | bottom-early-tertile = {il[lo_mask].mean():+.4f}   top-early-tertile = {il[hi_mask].mean():+.4f}")

# per-fold IC matrix (coin x fold) + within-coin lag-1 autocorrelation across the 7 folds
per_fold_ic = np.full((n_alt, len(folds)), np.nan)
for fi, f in enumerate(folds):
    for c in range(n_alt):
        per_fold_ic[c, fi] = spearman(*coin_obs(c, {f})[:2], nmin=20)[0]
# within-coin demeaned lag-1 autocorr, pooled
ar_x, ar_y = [], []
for c in range(n_alt):
    v = per_fold_ic[c]; fin = np.isfinite(v)
    if fin.sum() >= 4:
        vv = v.copy(); vv[fin] = vv[fin] - vv[fin].mean()
        for k in range(len(folds) - 1):
            if np.isfinite(vv[k]) and np.isfinite(vv[k + 1]):
                ar_x.append(vv[k]); ar_y.append(vv[k + 1])
ar_rho, ar_n = spearman(ar_x, ar_y, nmin=20)
print(f"  within-coin lag-1 IC autocorr (per-fold, demeaned, pooled): rho={ar_rho:+.3f} (n={ar_n} pairs)")
RESULTS["persistence"] = {"rho_early_late": rho_el, "n_coins": n_el, "lo_tertile_stay_low": lo_stay,
                          "hi_tertile_stay_high": hi_stay, "late_ic_bottom_tertile": float(il[lo_mask].mean()),
                          "late_ic_top_tertile": float(il[hi_mask].mean()), "lag1_autocorr": ar_rho, "lag1_n": ar_n}


# ============================================================================= 3. STRUCTURAL FEATURES
print("\n============ 3. STRUCTURAL R-DRIVERS (coin features vs full-sample IC) ============")
feat = {
    "realized_vol": np.nanstd(resid_alt, axis=0),                    # temporal resid vol per coin
    "half_spread": np.array([hs_arr[c] for c in range(n_alt)]),      # impact half-spread (illiquidity)
    "activity": np.array([coin_ic[c][1] for c in range(n_alt)]),     # # non-overlap obs (liquidity/uptime proxy)
    "mean_abs_signal": np.array([np.nanmean(np.abs(SIG[base_hours, c])) for c in range(n_alt)]),
    "signal_vol": np.array([np.nanstd(SIG[base_hours, c]) for c in range(n_alt)]),
}
RESULTS["feature_vs_ic"] = {}
for name, fv in feat.items():
    rho, nn = spearman(fv, ic_full, nmin=10)
    print(f"  Spearman(IC, {name:16s}) = {rho:+.3f}  (n={nn})   "
          f"[+ => higher {name} => higher IC/lower R]")
    RESULTS["feature_vs_ic"][name] = {"rho": rho, "n": nn}
print(f"  (multiplicity: {len(feat)} structural features scanned)")


# ============================================================================= 4. ADAPTIVE PER-COIN GAIN BOOK
print("\n============ 4. ADAPTIVE PER-COIN GAIN vs UNIFORM (phase-averaged decile book) ============")

def eval_phase_book(sig_mat, fold_set, elig_coins=None):
    """Run the decile L/S book over the 4 reb-4 phase offsets, restricted to fold_set; phase-average the stats.
    sig_mat = (possibly gain-adjusted) signal matrix. elig_coins=None -> all 45; else restrict universe to that set.
    Returns per-scenario {phase_avg net, per-phase means, per-fold phase-avg means} + gross."""
    uni = set(range(n_alt)) if elig_coins is None else set(int(x) for x in elig_coins)
    per_phase_gross = []; per_scn = {lab: {"phase_means": [], "per_fold_phase": []} for lab, *_ in CB.SCENARIOS}
    for ph in range(REB):
        grid = base_hours[ph::REB]
        grid = np.array([t for t in grid if month_of[int(t)] in fold_set], dtype=np.int64)
        xs, fvb, elig = {}, {}, {}
        for t in grid:
            ti = int(t); row = sig_mat[ti]
            nm = np.array([a for a in np.nonzero(np.isfinite(row))[0] if a in uni], dtype=int)
            if len(nm) < 4: continue
            xs[ti] = (nm, row[nm].astype(float))
            fvb[ti] = {int(a): float(FVbp[ti, a]) for a in nm}
            elig[ti] = uni
        keys = np.array(sorted(xs), dtype=np.int64)
        if len(keys) < 8:
            per_phase_gross.append(np.nan)
            for lab in per_scn: per_scn[lab]["phase_means"].append(np.nan); per_scn[lab]["per_fold_phase"].append({})
            continue
        sim = CB.simulate_raw(keys, xs, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
        hrs = sim["hr"].astype(np.int64); shm = np.array([month_of[int(t)] for t in hrs])
        per_phase_gross.append(float((sim["gross"] / REB).mean()))
        for lab, mult, fee, mode in CB.SCENARIOS:
            netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
            per_scn[lab]["phase_means"].append(float(netph.mean()))
            per_scn[lab]["per_fold_phase"].append({int(m): float(netph[shm == m].mean()) for m in sorted(set(shm.tolist()))})
    out = {"gross_phase_avg": float(np.nanmean(per_phase_gross)), "gross_phases": per_phase_gross, "scn": {}}
    for lab in per_scn:
        pm = np.array(per_scn[lab]["phase_means"])
        # per-fold phase-average
        pf = {}
        for f in fold_set:
            vals = [d.get(f, np.nan) for d in per_scn[lab]["per_fold_phase"]]
            vals = [v for v in vals if np.isfinite(v)]
            if vals: pf[int(f)] = float(np.mean(vals))
        st = ADJ.sign_test(list(pf.values())) if pf else {"p": np.nan}
        out["scn"][lab] = {"net_phase_avg": float(np.nanmean(pm)), "phase_means": pm.tolist(),
                           "phase_min": float(np.nanmin(pm)), "phase_max": float(np.nanmax(pm)),
                           "per_fold": pf, "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                           "n_folds": len(pf), "sign_p": float(st["p"])}
    return out

# reliability ranking DISCOVERED on EARLY folds (frozen), applied to LATE folds
ic_early_rank = np.argsort(np.where(np.isfinite(ic_early), ic_early, -9))   # ascending: worst first
# gain schemes (frozen, from early folds):
def shrink_matrix(g_lo, tertile_mask):
    g = np.ones(n_alt); g[tertile_mask] = g_lo
    return SIG * g[None, :]

# bottom-tertile (worst reliability) coins from EARLY folds
lo_ct = int(round(n_alt / 3))
worst_early = set(int(c) for c in ic_early_rank[:lo_ct])
best_early = set(int(c) for c in ic_early_rank[-lo_ct:])
worst_mask = np.zeros(n_alt, bool); worst_mask[list(worst_early)] = True

VARIANTS = {}   # name -> (signal_matrix, elig_coins)
VARIANTS["uniform"]        = (SIG, None)
VARIANTS["shrink_lo0.50"]  = (shrink_matrix(0.50, worst_mask), None)
VARIANTS["shrink_lo0.00"]  = (shrink_matrix(0.00, worst_mask), None)
VARIANTS["drop_worst5"]    = (SIG, set(range(n_alt)) - set(int(c) for c in ic_early_rank[:5]))
VARIANTS["drop_worst10"]   = (SIG, set(range(n_alt)) - set(int(c) for c in ic_early_rank[:10]))
n_gain_variants = len(VARIANTS) - 1

print(f"  reliability discovered on EARLY folds; worst-tertile coins (frozen) = {sorted(worst_early)}")
print(f"  gain variants scanned: {n_gain_variants}  (2 shrink levels x bottom-tertile, 2 hard-drop levels)")
RESULTS["adaptive"] = {"worst_early_tertile": sorted(worst_early), "n_gain_variants": n_gain_variants,
                       "early": {}, "late": {}, "paired_late": {}}

def paired_fold_delta(adap, unif):
    """Phase-averaged per-fold (adaptive - uniform) net delta on the FOCUS scenarios; sign test across folds."""
    res = {}
    for lab in FOCUS:
        a = adap["scn"][lab]["per_fold"]; u = unif["scn"][lab]["per_fold"]
        common = sorted(set(a) & set(u))
        deltas = [a[f] - u[f] for f in common]
        st = ADJ.sign_test(deltas) if deltas else {"p": np.nan}
        res[lab] = {"mean_delta": float(np.mean(deltas)) if deltas else np.nan,
                    "folds_up": int(sum(1 for x in deltas if x > 0)), "n_folds": len(deltas),
                    "sign_p": float(st["p"]), "per_fold_delta": {int(f): float(v) for f, v in zip(common, deltas)}}
    return res

for split_name, fold_set in (("early", EARLY), ("late", LATE)):
    print(f"\n  --- {split_name.upper()} folds ({sorted(fold_set)}) ---")
    books = {}
    for vname, (mat, elig) in VARIANTS.items():
        books[vname] = eval_phase_book(mat, fold_set, elig)
    RESULTS["adaptive"][split_name] = {v: books[v] for v in VARIANTS}
    for vname in VARIANTS:
        b = books[vname]; g = b["gross_phase_avg"]
        cols = []
        for lab in FOCUS:
            s = b["scn"][lab]
            cols.append(f"{lab.replace('taker_top_','tk_').replace('maker_earn_','mk_')}={s['net_phase_avg']:+.3f}"
                        f"[{s['phase_min']:+.2f},{s['phase_max']:+.2f}]{s['folds_pos']}/{s['n_folds']}")
        print(f"    {vname:14s} gross={g:+.3f}  " + "  ".join(cols))
    if split_name == "late":
        print("    -- PAIRED (adaptive - uniform) per-fold delta, LATE folds (the OOS exploitability test) --")
        for vname in VARIANTS:
            if vname == "uniform": continue
            pd_ = paired_fold_delta(books[vname], books["uniform"])
            RESULTS["adaptive"]["paired_late"][vname] = pd_
            cols = [f"{lab.replace('taker_top_','tk_').replace('maker_earn_','mk_')} d={pd_[lab]['mean_delta']:+.3f} "
                    f"{pd_[lab]['folds_up']}/{pd_[lab]['n_folds']}up p={pd_[lab]['sign_p']:.2f}" for lab in FOCUS]
            print(f"      {vname:14s} " + "  ".join(cols))


# ============================================================================= ROLLING CAUSAL GAIN (all folds)
print("\n============ 4b. ROLLING CAUSAL per-coin gain (trailing-window IC), all folds ============")
WIN = 200          # trailing non-overlapping obs per coin (~200*4h ~= 33 days of that coin's history)
gain_roll = np.ones((N, n_alt))
for c in range(n_alt):
    col_sig = SIG[base_hours, c]; col_fwd = FVbp[base_hours, c]
    ok = np.isfinite(col_sig) & np.isfinite(col_fwd)
    idx = np.nonzero(ok)[0]
    # causal: at obs j, use the prior WIN obs whose 4h fwd window has CLOSED (<= current hour - REB)
    sgv = col_sig[idx]; fwv = col_fwd[idx]; hidx = idx  # positions in base_hours
    running_ic = np.full(len(idx), np.nan)
    for j in range(len(idx)):
        # prior obs with closed forward window: base_hours position <= hidx[j]-REB
        prior = np.nonzero(idx <= hidx[j] - REB)[0]
        if len(prior) >= 40:
            w = prior[-WIN:]
            running_ic[j], _ = spearman(sgv[w], fwv[w], nmin=40)
    # map IC -> gain in [0,1]: reliable(IC>=0.03)->1 ; unreliable(IC<=-0.02)->0.25 ; linear between
    g = np.clip((running_ic - (-0.02)) / (0.03 - (-0.02)), 0.25, 1.0)
    g[~np.isfinite(running_ic)] = 1.0                     # no history yet -> trust (uniform)
    for j, pos in enumerate(idx):
        gain_roll[base_hours[pos], c] = g[j]
SIG_roll = SIG * gain_roll
print(f"  rolling window={WIN} obs; gain in [0.25,1.0] by trailing causal IC (thr -0.02..0.03)")
for split_name, fold_set in (("early", EARLY), ("late", LATE)):
    bu = eval_phase_book(SIG, fold_set); br = eval_phase_book(SIG_roll, fold_set)
    pd_ = paired_fold_delta(br, bu)
    RESULTS["adaptive"].setdefault("rolling", {})[split_name] = {
        "uniform": bu, "rolling": br, "paired": pd_}
    cols = [f"{lab.replace('taker_top_','tk_').replace('maker_earn_','mk_')}: unif {bu['scn'][lab]['net_phase_avg']:+.3f}"
            f" -> roll {br['scn'][lab]['net_phase_avg']:+.3f}  d={pd_[lab]['mean_delta']:+.3f}"
            f" {pd_[lab]['folds_up']}/{pd_[lab]['n_folds']}up" for lab in FOCUS]
    print(f"  {split_name.upper()}: gross unif {bu['gross_phase_avg']:+.3f} -> roll {br['gross_phase_avg']:+.3f}")
    for c in cols: print(f"      {c}")

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "adfilter_token_reliability.json").write_text(json.dumps(RESULTS, indent=2, default=float))
_log("wrote adfilter_token_reliability.json")
print("\nLegend: net phase-avg [phase_min,phase_max] folds_pos/n_folds ; paired delta = adaptive - uniform.")
