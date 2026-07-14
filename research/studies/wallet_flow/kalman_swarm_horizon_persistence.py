"""
kalman_swarm_horizon_persistence — SIGNAL-DYNAMICS & HORIZON-INTERACTION agent (Result-11 attack).

Result 11 fixed reb=4 and concluded "the signal is fast, harvest it fresh" but NEVER (a) measured the signal's
persistence rigorously, nor (b) JOINTLY re-optimized harvest horizon with smoothing. This script does both.

Sections:
  A. Reproduce the reb=4 no-smooth baseline (must give taker_smallclip ~+1.42, maker_a30 ~+4.35 pooled). Harness gate.
  B. Persistence characterization:
       B1  hour-to-hour autocorrelation (ACF) of s_inf per alt, pooled → signal-LEVEL half-life
       B2  rank/decile MEMBERSHIP persistence: fraction of top-decile still top-decile after 1/2/4/8/... h → membership half-life
       B3  a name's signal DECAY: mean forward rank of a top-decile name vs lag
  C. ALPHA (forward-predictive) half-life: marginal cross-sectional IC(tau) between s_inf[t] and the single future
       hour return at t+tau, plus the long-short spread(tau). Compare ALPHA half-life vs MEMBERSHIP half-life:
       if membership churns FASTER than alpha decays -> room for a longer hold; if alpha decays first -> fast, harvest fresh.
  D. JOINT sweep: smoothing half-life HL (EMA) x harvest horizon reb in {2,3,4,6,8,12}. Find joint net-per-hr optimum,
       compare to no-smooth baseline at each reb. Reports FOCUS scenarios point est + day-block CI + per-fold sign.
  E. MATCHED-horizon test: EMA half-life == harvest horizon (self-consistent) vs the mismatched cells.

Strictly causal: EMA uses only s_inf at hours <= t. Rebalance grid frozen to sorted(observed hours)[::reb] per reb.
Everything tuned here is an in-sample search -> candidates, reported across a RANGE, both gates applied.

    .venv/bin/python -m research.studies.wallet_flow.kalman_swarm_horizon_persistence
"""
from __future__ import annotations
import time, json, math
from pathlib import Path
import numpy as np

from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

CACHE = Path("data/derived/xsec_kalman/panel_cache.npz")
OUT = Path("data/derived/xsec_kalman_horizon")
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")
REBS = (2, 3, 4, 6, 8, 12)
# smoothing parametrized by EMA half-life HL (hours): alpha = 1 - 0.5**(1/HL); HL=0 == no smoothing (alpha=1)
HLS = (0, 1, 2, 3, 4, 6, 8, 12)


def alpha_of_hl(hl):
    return 1.0 if hl <= 0 else 1.0 - 0.5 ** (1.0 / hl)


def ema_smooth(SIG, alpha, stale=48):
    """Strictly-causal per-column EMA with carry-forward + staleness drop (verbatim logic from xsec_kalman)."""
    if alpha >= 1.0 and stale <= 0:
        return SIG
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    last = np.full(Acol, -1_000_000, dtype=np.int64)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        fresh = has & (~np.isfinite(prev) | ((t - last) > stale))
        blend = has & ~fresh
        prev = np.where(fresh, obs, prev)
        prev = np.where(blend, alpha * obs + (1.0 - alpha) * prev, prev)
        last = np.where(has, t, last)
        alive = np.isfinite(prev) & ((t - last) <= stale)
        prev = np.where(alive, prev, np.nan)
        m[t] = np.where(alive, prev, np.nan)
    return m


def _spearman(a, b):
    """Spearman corr on paired finite values."""
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 3: return np.nan
    ra = np.argsort(np.argsort(a[m])).astype(float)
    rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    d = math.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else np.nan


# ============================================================ load cache
d = np.load(CACHE, allow_pickle=False)
R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
folds = d["folds"]

SIG = np.full((N, n_alt), np.nan)
obs_hours_set = set()
for i in range(len(R)):
    if np.isfinite(s_inf[i]):
        SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs_hours_set.add(int(R[i]))
base_hours = np.array(sorted(obs_hours_set), dtype=np.int64)
_log(f"loaded cache: {len(R):,} cells, {n_alt} alts, {len(base_hours)} observed hours "
     f"[{base_hours[0]}..{base_hours[-1]}]")


# ============================================================ book evaluation on a (signal matrix, reb)
def eval_book(m, reb, regime="all", mid_ok=None):
    """Build xs_arr/fvb/elig on the frozen reb grid from smoothed matrix m; run CB.simulate_raw + scenarios."""
    reb_grid = base_hours[::reb]
    FVr = S0.fwd_sum(resid_alt, reb)                       # [N,n_alt] forward reb-hour resid return (frac)
    full_set = set(range(n_alt))
    xs_arr, fvb, elig = {}, {}, {}
    hour_month = {}
    for t in reb_grid:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4: continue
        xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
        fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
        elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
        hour_month[ti] = int(panel_month[ti])
    keys = np.array(sorted(xs_arr), dtype=np.int64)
    if len(keys) < 8: return None
    sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
    if len(sim["hr"]) < 8: return None
    hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
    out = {"reb": reb, "regime": regime, "n_steps": int(len(hrs)),
           "gross_bp_per_hr": float((sim["gross"] / reb).mean()), "mean_turnover": float(sim["turn"].mean()),
           "scenarios": {}}
    for lab, mult, fee, mode in CB.SCENARIOS:
        netph, _ = CB.scenario_net_series(sim, reb, fee, mode, mult, hs_default)
        ci95 = CB._dayblock_ci(netph, hrs, hours)
        pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
        out["scenarios"][lab] = {"net": float(netph.mean()), "ci95": list(ci95),
                                 "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                 "n_folds": len(pf), "sign_p": ADJ.sign_test(list(pf.values()))["p"]}
    return out


def _fmt(cell, labs=FOCUS):
    if cell is None: return "(thin)"
    cols = []
    for lab in labs:
        sc = cell["scenarios"][lab]; lo, hi = sc["ci95"]
        star = "*" if lo > 0 else ("-" if hi < 0 else " ")
        cols.append(f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['folds_pos']}/{sc['n_folds']}{star}")
    return f"g{cell['gross_bp_per_hr']:+6.2f} turn{cell['mean_turnover']:4.2f}  " + "  ".join(cols)


results = {"config": {"rebs": list(REBS), "hls": list(HLS), "n_alt": n_alt,
                      "focus": list(FOCUS), "hs_default": hs_default}}


# ============================================================ A. baseline gate
print("\n================= A. BASELINE REPRODUCTION (reb=4, no smoothing, pooled) =================")
print(f"{'':17s}" + "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>21}" for l in FOCUS))
base4 = eval_book(SIG, 4, "all")
print(f"{'reb4 a1(base)':17s} " + _fmt(base4))
results["baseline_reb4"] = base4
b_tk = base4["scenarios"]["taker_top_smallclip"]["net"]; b_mk = base4["scenarios"]["maker_earn_a30"]["net"]
b_mk50 = base4["scenarios"]["maker_earn_a50"]["net"]
gate_ok = abs(b_tk - 1.42) < 0.15 and abs(b_mk - 4.35) < 0.15
print(f"  GATE: taker_smallclip {b_tk:+.2f} (want +1.42), maker_a30 {b_mk:+.2f} (want +4.35), "
      f"maker_a50 {b_mk50:+.2f} (want +3.60)  -> {'PASS' if gate_ok else 'FAIL'}")
assert gate_ok, "baseline reproduction FAILED — harness mismatch, abort."


# ============================================================ B. persistence characterization
print("\n================= B. SIGNAL PERSISTENCE =================")

# B1 pooled hour-to-hour ACF of s_inf (per alt, then pooled across alts). Demean each column over time.
Xc = SIG.copy()
colmean = np.nanmean(Xc, axis=0)
Xd = Xc - colmean                                          # per-name time-demean
def acf_pooled(lag):
    a = Xd[:-lag] if lag > 0 else Xd
    b = Xd[lag:] if lag > 0 else Xd
    m = np.isfinite(a) & np.isfinite(b)
    av, bv = a[m], b[m]
    if len(av) < 100: return np.nan, 0
    av = av - av.mean(); bv = bv - bv.mean()
    den = math.sqrt((av * av).sum() * (bv * bv).sum())
    return (float((av * bv).sum() / den) if den > 0 else np.nan), len(av)
acf_lags = [1, 2, 3, 4, 6, 8, 12, 16, 24]
acf = {L: acf_pooled(L) for L in acf_lags}
print("B1 signal-LEVEL ACF (pooled, per-name time-demeaned, Pearson):")
for L in acf_lags:
    r, npr = acf[L]; print(f"     lag {L:2d}h  rho={r:+.3f}  (n={npr:,})")
# level half-life: lag where ACF crosses 0.5 (interp between lags)
def cross_half(lags, vals, target=0.5, base=1.0):
    prev_l, prev_v = 0, base
    for L in lags:
        v = vals[L]
        if v <= target:
            if prev_v == v: return float(L)
            return prev_l + (prev_v - target) / (prev_v - v) * (L - prev_l)
        prev_l, prev_v = L, v
    return float("inf")
level_hl = cross_half(acf_lags, {L: acf[L][0] for L in acf_lags}, 0.5, base=1.0)
print(f"     -> signal-LEVEL half-life (ACF->0.5): {level_hl:.2f} h")
results["acf"] = {str(L): {"rho": acf[L][0], "n": acf[L][1]} for L in acf_lags}
results["level_half_life_h"] = level_hl

# B2 decile MEMBERSHIP persistence: top-decile retention vs lag. base rate = decile fraction ~0.10.
mem_lags = [1, 2, 3, 4, 6, 8, 12, 16, 24]
top_at = {}                                                # hour -> set of top-decile alt idx
frac_top = 0.10
for t in base_hours:
    row = SIG[t]; nm = np.nonzero(np.isfinite(row))[0]
    if len(nm) < 8: continue
    k = max(1, int(round(frac_top * len(nm))))
    order = np.argsort(row[nm])
    top_at[int(t)] = set(nm[order[-k:]].tolist())
def retention(lag):
    num = den = 0
    for t, tops in top_at.items():
        t2 = t + lag
        if t2 not in top_at: continue
        # only count names still present (finite) at t2
        present = [a for a in tops if np.isfinite(SIG[t2, a])]
        if not present: continue
        num += sum(1 for a in present if a in top_at[t2]); den += len(present)
    return (num / den) if den else np.nan, den
mem = {L: retention(L) for L in mem_lags}
# baseline chance retention = mean decile fraction
chance = np.mean([len(v) / max(1, np.isfinite(SIG[t]).sum()) for t, v in top_at.items()])
print(f"\nB2 top-decile MEMBERSHIP retention (chance≈{chance:.3f}):")
for L in mem_lags:
    r, den = mem[L]; excess = (r - chance) / (1 - chance)
    print(f"     lag {L:2d}h  retention={r:.3f}  excess-over-chance={excess:+.3f}  (pairs={den:,})")
# membership half-life: retention excess over chance crosses 0.5
mem_excess = {L: (mem[L][0] - chance) / (1 - chance) for L in mem_lags}
mem_hl = cross_half(mem_lags, mem_excess, 0.5, base=1.0)
print(f"     -> MEMBERSHIP half-life (excess-over-chance->0.5): {mem_hl:.2f} h")
results["membership"] = {str(L): {"retention": mem[L][0], "excess": mem_excess[L], "pairs": mem[L][1]}
                         for L in mem_lags}
results["membership_half_life_h"] = mem_hl; results["decile_chance"] = float(chance)

# B3 a top-decile name's mean forward cross-sectional RANK vs lag (0=bottom,1=top). Fresh top starts ~ (1-k/2n)~0.95.
def mean_fwd_rank(lag):
    vals = []
    for t, tops in top_at.items():
        t2 = t + lag
        if t2 >= N: continue
        row = SIG[t2]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 8: continue
        rk = np.argsort(np.argsort(row[nm])).astype(float) / (len(nm) - 1)   # 0..1
        pos = {int(a): rk[j] for j, a in enumerate(nm)}
        for a in tops:
            if a in pos: vals.append(pos[a])
    return (float(np.mean(vals)) if vals else np.nan)
print("\nB3 forward mean cross-sectional rank of a name that WAS top-decile (1=top,0.5=median):")
r0 = mean_fwd_rank(0)
for L in [0, 1, 2, 3, 4, 6, 8, 12]:
    print(f"     lag {L:2d}h  mean_rank={mean_fwd_rank(L):.3f}")


# ============================================================ C. ALPHA (forward-predictive) half-life
print("\n================= C. ALPHA (forward-predictive) half-life =================")
# marginal cross-sectional IC(tau): Spearman(s_inf[t,:], resid_alt[t+tau,:]) per hour, averaged.
def marginal_ic(tau):
    ics = []
    for t in base_hours:
        t2 = t + tau
        if t2 >= N: continue
        s = SIG[t]; f = resid_alt[t2]
        m = np.isfinite(s) & np.isfinite(f)
        if m.sum() < 8: continue
        ic = _spearman(s[m], f[m])
        if np.isfinite(ic): ics.append(ic)
    return (float(np.mean(ics)) if ics else np.nan), len(ics)
# long-short spread(tau): top-decile minus bottom-decile single-hour forward resid return (bp) at lag tau
def ls_spread(tau):
    sp = []
    for t in base_hours:
        t2 = t + tau
        if t2 >= N: continue
        s = SIG[t]; f = resid_alt[t2]; nm = np.nonzero(np.isfinite(s) & np.isfinite(f))[0]
        if len(nm) < 10: continue
        k = max(1, int(round(0.10 * len(nm)))); order = np.argsort(s[nm])
        sp.append((f[nm[order[-k:]]].mean() - f[nm[order[:k]]].mean()) * 1e4)
    return (float(np.mean(sp)) if sp else np.nan), len(sp)
tau_lags = [1, 2, 3, 4, 6, 8, 12, 16, 24]
ic_by = {t: marginal_ic(t) for t in tau_lags}
sp_by = {t: ls_spread(t) for t in tau_lags}
print("  tau    marginal_IC   LS_spread(bp/hr)")
for t in tau_lags:
    print(f"   {t:2d}h   {ic_by[t][0]:+.4f}       {sp_by[t][0]:+6.3f}   (n={ic_by[t][1]:,})")
ic1 = ic_by[1][0]; sp1 = sp_by[1][0]
alpha_hl_ic = cross_half(tau_lags, {t: ic_by[t][0] for t in tau_lags}, 0.5 * ic1, base=ic1)
alpha_hl_sp = cross_half(tau_lags, {t: sp_by[t][0] for t in tau_lags}, 0.5 * sp1, base=sp1)
print(f"  -> ALPHA half-life (marginal IC -> 0.5*IC(1)):   {alpha_hl_ic:.2f} h")
print(f"  -> ALPHA half-life (LS spread  -> 0.5*spread(1)): {alpha_hl_sp:.2f} h")
results["marginal_ic"] = {str(t): {"ic": ic_by[t][0], "spread_bp": sp_by[t][0], "n": ic_by[t][1]} for t in tau_lags}
results["alpha_half_life_ic_h"] = alpha_hl_ic; results["alpha_half_life_spread_h"] = alpha_hl_sp

print(f"\n  COMPARISON: membership_HL={mem_hl:.2f}h  vs  alpha_HL(IC)={alpha_hl_ic:.2f}h  alpha_HL(spread)={alpha_hl_sp:.2f}h")
verdict_room = mem_hl < min(alpha_hl_ic, alpha_hl_sp)
print(f"  membership churns {'FASTER' if verdict_room else 'SLOWER'} than alpha decays "
      f"-> {'ROOM for longer hold/smoothing' if verdict_room else 'signal is fast, harvest fresh (no room)'}")


# ============================================================ D. JOINT sweep HL x reb (pooled)
print("\n================= D. JOINT SWEEP  smoothing-HL x harvest-reb  (pooled) =================")
print("  each cell: [taker_smallclip / taker_impact / maker_a30 / maker_a50]  net[CIlo,CIhi]folds  *=CI>0 -=CI<0")
smoothed = {}
for hl in HLS:
    smoothed[hl] = SIG if hl == 0 else ema_smooth(SIG, alpha_of_hl(hl), stale=48)
joint = {}
best = None  # (net, hl, reb, label) tracked for maker_a30 and taker_smallclip separately
best_mk = None; best_tk = None
for hl in HLS:
    a = alpha_of_hl(hl)
    print(f"\n  --- smoothing HL={hl}h (alpha={a:.3f}) ---")
    for reb in REBS:
        cell = eval_book(smoothed[hl], reb, "all")
        joint[f"hl{hl}_reb{reb}"] = cell
        print(f"    reb{reb:2d}  " + _fmt(cell))
        if cell is None: continue
        mk = cell["scenarios"]["maker_earn_a30"]["net"]; tk = cell["scenarios"]["taker_top_smallclip"]["net"]
        if best_mk is None or mk > best_mk[0]: best_mk = (mk, hl, reb)
        if best_tk is None or tk > best_tk[0]: best_tk = (tk, hl, reb)
results["joint"] = joint
print(f"\n  JOINT optimum maker_a30: net={best_mk[0]:+.2f}/hr at HL={best_mk[1]} reb={best_mk[2]}  "
      f"(baseline reb4 no-smooth {b_mk:+.2f})")
print(f"  JOINT optimum taker_smallclip: net={best_tk[0]:+.2f}/hr at HL={best_tk[1]} reb={best_tk[2]}  "
      f"(baseline reb4 no-smooth {b_tk:+.2f})")
results["joint_best"] = {"maker_a30": {"net": best_mk[0], "hl": best_mk[1], "reb": best_mk[2]},
                         "taker_smallclip": {"net": best_tk[0], "hl": best_tk[1], "reb": best_tk[2]}}

# also: no-smooth across reb (does a longer/shorter FRESH hold beat reb4?)
print("\n  NO-SMOOTH horizon curve (HL=0) — is reb4 the fresh-signal optimum?")
for reb in REBS:
    print(f"    reb{reb:2d}  " + _fmt(joint[f"hl0_reb{reb}"]))


# ============================================================ E. MATCHED-horizon test
print("\n================= E. MATCHED-HORIZON (EMA half-life == harvest reb) vs mismatched =================")
matched = {}
for reb in REBS:
    hl = reb
    a = alpha_of_hl(hl)
    m = ema_smooth(SIG, a, stale=48)
    cell = eval_book(m, reb, "all")
    matched[f"reb{reb}"] = cell
    base_cell = joint[f"hl0_reb{reb}"]
    dmk = cell["scenarios"]["maker_earn_a30"]["net"] - base_cell["scenarios"]["maker_earn_a30"]["net"]
    print(f"  reb{reb:2d} matched(HL={reb},a={a:.3f})  " + _fmt(cell) + f"   dMaker_a30_vs_freshSameReb {dmk:+.2f}")
results["matched"] = matched

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
_log(f"wrote {OUT/'results.json'}")
print("\nDONE.")
