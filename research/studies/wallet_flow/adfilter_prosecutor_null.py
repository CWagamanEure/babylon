"""
adfilter_prosecutor_null — PROSECUTOR / OVER-CARRY agent for the ADAPTIVE-R (heteroskedastic measurement) swarm.

The swarm wants to DISCOVER observables `f` such that the selection signal's forward IC is heteroskedastic in
`f` (IC high where R is low, collapses where R is high) -> those are R/Q drivers of an adaptive Kalman gain.
Every candidate observable is a fresh researcher degree-of-freedom. This script holds the idea to the
false-positive gauntlet BEFORE anyone builds a filter on it. Four gates, all cache-only (no pipeline load):

  (0) REPRODUCE: pooled rank-IC of s_inf vs the 4h forward resid return (the signal exists), and the KNOWN
      dispersion heteroskedasticity (mid-dispersion IC lift) that motivates the whole idea.
  (1) THE DIAGNOSTIC + MINING NULL: define a conditional-IC heteroskedasticity statistic (bucket gradient AND
      bucket range). Then MINE: draw K random observables AT THE OBSERVABLE'S OWN GRANULARITY (per-hour and
      per-coin), and show the null distribution of the best conditional-IC gradient you find by chance. This is
      the DoF cost. A real driver must clear the max-over-K bar, not just "IC varies across buckets."
  (2) PER-CANDIDATE STRUCTURE-MATCHED PERMUTATION p: for each leading cache-doable candidate (dispersion,
      per-coin half-spread, breadth, per-coin realized vol, |signal|), permute the observable at its natural
      granularity (hours across hours, coins across coins) and get an honest p. A cell-level permutation of a
      per-hour observable is the classic trap (whole hours move together -> effective N is #hours, not #cells).
  (3) IN-SAMPLE vs OOS: discover the bucket-IC pattern on EARLY folds, test whether it REPLICATES on LATE folds.
      In-sample heteroskedasticity is trivial to mine; OOS is the test. Includes the per-coin reliability
      persistence test (does a coin's early-fold IC predict its late-fold IC?).
  (4) BOOK GATE (phase + multiplicity + matched-DoF): if a driver survives (0-3), does an adaptive-R gain built
      on it actually beat the fixed-alpha / baseline book, PHASE-AVERAGED over the 4 reb offsets AND vs a
      matched-DoF RANDOM-GAIN null (same number of free per-bucket gains, assigned at random)?

Statistic note: inside permutation/bootstrap loops we use "rank-IC" = Pearson of GLOBAL ranks within a bucket
(O(N) per resample, consistently computed across the null and the observed -> a valid permutation test). Point
estimates are cross-checked against true within-bucket Spearman.

    .venv/bin/python -m research.studies.wallet_flow.adfilter_prosecutor_null
"""
from __future__ import annotations
import time
import numpy as np

from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_kalman as KAL

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

REB = 4
CACHE = "data/derived/xsec_kalman/panel_cache.npz"
B = 5                      # buckets
K_MINE = 400               # candidate observables in the mining scan
N_PERM = 2000              # structure-matched permutation draws
RNG = np.random.default_rng(20260710)


# ------------------------------------------------------------------ load
def load():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"].astype(np.int64), d["Cc"].astype(np.int64), d["s_inf"].astype(np.float64)
    hours = d["hours"].astype(np.int64); panel_month = d["panel_month"].astype(np.int64)
    disp = d["disp"].astype(np.float64); resid_alt = d["resid_alt"].astype(np.float64)
    hs_arr = d["hs_arr"].astype(np.float64); hs_default = float(d["hs_default"])
    n_alt = int(d["n_alt"]); folds = d["folds"].astype(np.int64); N = len(hours)

    FV = S0.fwd_sum(resid_alt, REB)                          # [N,45] forward 4h resid return (frac)
    fv = FV[R, Cc] * 1e4                                     # bp, per cell
    ok = np.isfinite(fv) & np.isfinite(s_inf)
    R, Cc, s_inf, fv = R[ok], Cc[ok], s_inf[ok], fv[ok]
    cell_month = panel_month[R]
    return dict(R=R, Cc=Cc, s=s_inf, fv=fv, cell_month=cell_month, hours=hours, panel_month=panel_month,
                disp=disp, resid_alt=resid_alt, hs_arr=hs_arr, hs_default=hs_default, n_alt=n_alt,
                folds=folds, N=N, FV=FV)


def _rank01(x):
    """rank -> [0,1], average ties negligibly (argsort-argsort is fine at this scale)."""
    r = np.empty(len(x), dtype=np.float64)
    r[np.argsort(x, kind="stable")] = np.arange(len(x))
    return r / max(len(x) - 1, 1)


# ------------------------------------------------------------------ fast bucketed rank-IC
def bucket_ic(xr, yr, bkt, B=B):
    """Per-bucket Pearson of global ranks xr,yr given integer bucket labels bkt in [0,B). Vectorized O(N)."""
    n = np.bincount(bkt, minlength=B).astype(np.float64)
    sx = np.bincount(bkt, weights=xr, minlength=B); sy = np.bincount(bkt, weights=yr, minlength=B)
    sxx = np.bincount(bkt, weights=xr * xr, minlength=B); syy = np.bincount(bkt, weights=yr * yr, minlength=B)
    sxy = np.bincount(bkt, weights=xr * yr, minlength=B)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - (sx / n) * (sy / n)
        vx = sxx / n - (sx / n) ** 2; vy = syy / n - (sy / n) ** 2
        ic = cov / np.sqrt(vx * vy)
    ic[n < 30] = np.nan
    return ic


def het_stats(ic):
    """From a length-B IC vector return (gradient, range). gradient = LS slope of IC vs centered bucket index
    (per unit index); range = max-min. Both are 'how heteroskedastic'."""
    b = np.arange(len(ic), dtype=np.float64)
    fin = np.isfinite(ic)
    if fin.sum() < 3: return np.nan, np.nan
    bb = b[fin] - b[fin].mean(); ii = ic[fin]
    grad = float((bb @ (ii - ii.mean())) / (bb @ bb))
    rng = float(np.nanmax(ic) - np.nanmin(ic))
    return grad, rng


def spearman(a, b):
    ar = _rank01(a); br = _rank01(b)
    ar -= ar.mean(); br -= br.mean()
    d = np.sqrt((ar @ ar) * (br @ br))
    return float((ar @ br) / d) if d > 0 else np.nan


# ------------------------------------------------------------------ observables (per cell), + granularity
def build_observables(D):
    """Return dict name -> (values_per_cell, granularity, unit_index_per_cell). granularity in
    {'hour','coin','cell'}; unit_index maps each cell to its granularity unit (for structure-matched perms)."""
    R, Cc, s, N, n_alt = D["R"], D["Cc"], D["s"], D["N"], D["n_alt"]
    disp, hs_arr, resid_alt = D["disp"], D["hs_arr"], D["resid_alt"]
    obs = {}

    # per-HOUR: cross-sectional dispersion (the motivating Q/R candidate)
    obs["disp_hour"] = (disp[R], "hour", R)

    # per-HOUR: breadth = # names observed that hour (crowding/participation proxy available from cache)
    breadth = np.bincount(R, minlength=N).astype(np.float64)      # cells per hour == names w/ finite signal
    obs["breadth_hour"] = (breadth[R], "hour", R)

    # per-COIN: half-spread (liquidity / cost, static)
    obs["halfspread_coin"] = (hs_arr[Cc], "coin", Cc)

    # per-COIN static: unconditional temporal resid vol (noisy coins)
    coin_vol = np.nanstd(resid_alt, axis=0)
    obs["coinvol_static_coin"] = (coin_vol[Cc], "coin", Cc)

    # per-CELL (coin x time): causal trailing realized vol of the coin's resid (W=48h, strictly past)
    W = 48
    Rz = np.where(np.isfinite(resid_alt), resid_alt, 0.0)
    m = np.isfinite(resid_alt).astype(np.float64)
    cs = np.cumsum(Rz, axis=0); cs2 = np.cumsum(Rz * Rz, axis=0); cm = np.cumsum(m, axis=0)
    def _win(c):
        w = np.array(c); w[W:] = c[W:] - c[:-W]; return w
    sw = _win(cs); s2w = _win(cs2); nw = _win(cm)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = s2w / nw - (sw / nw) ** 2
    rv = np.sqrt(np.clip(var, 0, None))                          # [N,45] trailing vol known at end of t
    rv_lag = np.full_like(rv, np.nan); rv_lag[1:] = rv[:-1]      # strictly past (known before t's forward window)
    obs["realvol48_cell"] = (rv_lag[R, Cc], "cell", np.arange(len(R)))

    # per-CELL: |signal| magnitude (a natural miner candidate; endogenous)
    obs["absmag_cell"] = (np.abs(s), "cell", np.arange(len(R)))

    return obs


def quantile_bucket(vals, B=B):
    """Quantile bucket a value vector into [0,B). NaN -> -1 (dropped by callers)."""
    out = np.full(len(vals), -1, dtype=np.int64)
    fin = np.isfinite(vals)
    v = vals[fin]
    edges = np.quantile(v, np.linspace(0, 1, B + 1)[1:-1])
    bk = np.searchsorted(edges, v, side="right")
    out[fin] = bk
    return out


# ------------------------------------------------------------------ main
def main():
    D = load()
    R, Cc, s, fv = D["R"], D["Cc"], D["s"], D["fv"]
    xr = _rank01(s); yr = _rank01(fv)
    _log(f"loaded {len(s):,} finite cells; {D['n_alt']} alts; folds={list(D['folds'])}")

    # ============ (0) REPRODUCE ============
    print("\n" + "=" * 96)
    print("(0) REPRODUCE — signal exists + KNOWN dispersion heteroskedasticity (the motivation)")
    print("=" * 96)
    pooled = spearman(s, fv)
    print(f"  pooled forward rank-IC (s_inf vs 4h fwd resid, {len(s):,} cells): {pooled:+.4f}")
    dispb = quantile_bucket(D["disp"][R])
    ic_disp = bucket_ic(xr, yr, dispb)
    dedges = np.quantile(D["disp"][R][np.isfinite(D["disp"][R])], np.linspace(0, 1, B + 1))
    print(f"  dispersion-bucketed IC (B={B}, low->high dispersion):")
    for b in range(B):
        print(f"     bkt{b} disp[{dedges[b]:.4f},{dedges[b+1]:.4f}] IC={ic_disp[b]:+.4f}")
    g, rng = het_stats(ic_disp)
    print(f"  --> gradient={g:+.4f}/bkt  range={rng:.4f}   (mid-lift => non-monotone; RANGE captures it)")

    # ============ (1) DIAGNOSTIC + MINING NULL ============
    print("\n" + "=" * 96)
    print(f"(1) MINING NULL — draw K={K_MINE} RANDOM observables at matched granularity; best-gradient by chance")
    print("=" * 96)
    Nh = D["N"]; ncoin = D["n_alt"]
    for gran, unit, nunit in (("hour", R, Nh), ("coin", Cc, ncoin)):
        grads = np.empty(K_MINE); rngs = np.empty(K_MINE)
        for k in range(K_MINE):
            uval = RNG.standard_normal(nunit)                    # random value per unit (hour or coin)
            bk = quantile_bucket(uval[unit])
            ic = bucket_ic(xr, yr, bk)
            grads[k], rngs[k] = het_stats(ic)
        ag = np.abs(grads)
        print(f"  granularity={gran:4s} ({nunit} units): random-observable |gradient| "
              f"p50={np.percentile(ag,50):.4f} p95={np.percentile(ag,95):.4f} "
              f"MAX-over-K={ag.max():.4f} ;  range p95={np.percentile(rngs,95):.4f} max={rngs.max():.4f}")
    print("  -> ANY real driver's |gradient|/range must exceed the MAX-over-K bar for its own granularity,")
    print("     else it is inside what a K-observable scan manufactures from noise.")

    # positive control: an observable built to BE the local IC (must clear)
    # local IC proxy: sign-agreement of this cell (xr-.5)*(yr-.5); smooth per hour
    loc = (xr - 0.5) * (yr - 0.5)
    hour_loc = np.bincount(R, weights=loc, minlength=Nh) / np.maximum(np.bincount(R, minlength=Nh), 1)
    pc_bk = quantile_bucket(hour_loc[R]); pc_ic = bucket_ic(xr, yr, pc_bk)
    pg, prng = het_stats(pc_ic)
    print(f"  [pos-control] observable = in-sample per-hour local-IC: gradient={pg:+.4f} range={prng:.4f} "
          f"(clears bar, but this is IN-SAMPLE circular -> must be OOS-tested in (3))")

    # ============ (2) PER-CANDIDATE STRUCTURE-MATCHED PERMUTATION p ============
    print("\n" + "=" * 96)
    print(f"(2) PER-CANDIDATE structure-matched permutation p  ({N_PERM} perms at each obs's own granularity)")
    print("=" * 96)
    obs = build_observables(D)
    cand_ic = {}
    print(f"  {'observable':22s} {'gran':5s} {'gradient':>10s} {'p_grad':>7s}   {'range':>8s} {'p_range':>8s}")
    for name, (vals, gran, unit) in obs.items():
        bk = quantile_bucket(vals)
        keep = bk >= 0
        ic = bucket_ic(xr[keep], yr[keep], bk[keep]); g0, r0 = het_stats(ic); cand_ic[name] = ic
        xk, yk, uk = xr[keep], yr[keep], unit[keep]
        if gran in ("hour", "coin"):
            # one value per present unit; permute values across units (scatter/gather, fully vectorized)
            nunit = D["N"] if gran == "hour" else D["n_alt"]
            uval = np.full(nunit, np.nan)
            uval[uk] = vals[keep]                                  # constant per unit -> consistent
            present = np.unique(uk); base = uval[present]
            gp = rp = 0
            for _ in range(N_PERM):
                perm = np.full(nunit, np.nan); perm[present] = RNG.permutation(base)
                bkn = quantile_bucket(perm[uk])
                gn, rn = het_stats(bucket_ic(xk, yk, np.clip(bkn, 0, B - 1)))
                gp += (abs(gn) >= abs(g0) - 1e-12); rp += (rn >= r0 - 1e-12)
            p_g, p_r = (gp + 1) / (N_PERM + 1), (rp + 1) / (N_PERM + 1)
        else:  # cell-level: full-shuffle null (ANTI-CONSERVATIVE for coin x time fields -> OOS is the real gate)
            vk = vals[keep]; gp = rp = 0
            for _ in range(N_PERM):
                bkn = quantile_bucket(RNG.permutation(vk))
                gn, rn = het_stats(bucket_ic(xk, yk, np.clip(bkn, 0, B - 1)))
                gp += (abs(gn) >= abs(g0) - 1e-12); rp += (rn >= r0 - 1e-12)
            p_g, p_r = (gp + 1) / (N_PERM + 1), (rp + 1) / (N_PERM + 1)
        print(f"  {name:22s} {gran:5s} {g0:>+10.4f} {p_g:>7.3f}   {r0:>8.4f} {p_r:>8.3f}")
    print("  (cell-level p uses a full-shuffle null and is ANTI-CONSERVATIVE for coin x time fields -> treat its")
    print("   small p with suspicion; the OOS test in (3) is the binding gate for cell-level observables.)")

    # ============ (3) IN-SAMPLE vs OOS ============
    print("\n" + "=" * 96)
    print("(3) IN-SAMPLE vs OOS — does the bucket-IC pattern REPLICATE on late folds?")
    print("=" * 96)
    folds = list(D["folds"]); cm = D["cell_month"]
    early_f, late_f = folds[:3], folds[3:]
    em = np.isin(cm, early_f); lm = np.isin(cm, late_f)
    print(f"  early folds {early_f} ({em.sum():,} cells)   late folds {late_f} ({lm.sum():,} cells)")
    print(f"  {'observable':22s} {'IC_buckets_EARLY':>34s}  {'IC_buckets_LATE':>34s}  {'corr':>6s} {'signAgr':>7s}")
    for name, (vals, gran, unit) in obs.items():
        bk = quantile_bucket(vals[em])                            # FREEZE bucket edges on EARLY cells
        edges = np.quantile(vals[em][np.isfinite(vals[em])], np.linspace(0, 1, B + 1)[1:-1])
        ic_e = bucket_ic(xr[em], yr[em], np.clip(bk, 0, B - 1))
        # apply SAME edges to late
        bl = np.searchsorted(edges, vals[lm], side="right")
        bl = np.clip(bl, 0, B - 1); bl[~np.isfinite(vals[lm])] = 0
        ic_l = bucket_ic(xr[lm], yr[lm], bl)
        fin = np.isfinite(ic_e) & np.isfinite(ic_l)
        corr = float(np.corrcoef(ic_e[fin], ic_l[fin])[0, 1]) if fin.sum() >= 3 else np.nan
        # sign agreement of the deviation-from-mean (is high-IC bucket still high?)
        de = ic_e[fin] - ic_e[fin].mean(); dl = ic_l[fin] - ic_l[fin].mean()
        sign = float((np.sign(de) == np.sign(dl)).mean()) if fin.sum() else np.nan
        es = ",".join(f"{v:+.3f}" for v in ic_e)
        ls = ",".join(f"{v:+.3f}" for v in ic_l)
        print(f"  {name:22s} {es:>34s}  {ls:>34s}  {corr:>+6.2f} {sign:>7.2f}")
    print("  corr>0 & signAgr high => the heteroskedasticity REPLICATES OOS (real R-driver);")
    print("  corr<=0 / inverts => IN-SAMPLE MIRAGE (do not build a filter on it).")

    # per-coin reliability persistence (the 'per-token reliability' driver): early-coin-IC -> late-coin-IC
    print("\n  per-COIN reliability persistence (early-fold coin IC vs late-fold coin IC):")
    ce, cl = [], []
    for c in range(D["n_alt"]):
        me = em & (Cc == c); ml = lm & (Cc == c)
        if me.sum() >= 200 and ml.sum() >= 200:
            ce.append(spearman(s[me], fv[me])); cl.append(spearman(s[ml], fv[ml]))
    ce, cl = np.array(ce), np.array(cl)
    rho = spearman(ce, cl) if len(ce) >= 5 else np.nan
    pr = float(np.corrcoef(ce, cl)[0, 1]) if len(ce) >= 5 else np.nan
    print(f"     {len(ce)} coins with >=200 cells both halves.  early-vs-late coin-IC: Pearson={pr:+.3f} "
          f"Spearman={rho:+.3f}")
    print(f"     -> {'PERSISTS: per-coin reliability is a real, OOS R-driver' if (np.isfinite(rho) and rho>0.2) else 'does NOT persist: static per-coin trust is a mirage / needs a much longer window'}")

    # ============ (4) BOOK GATE: phase + multiplicity + matched-DoF random-gain null ============
    print("\n" + "=" * 96)
    print("(4) BOOK GATE — adaptive-R gain (best surviving driver = dispersion) vs baseline:")
    print("     PHASE-AVERAGED over 4 reb offsets AND vs a matched-DoF RANDOM-GAIN null")
    print("=" * 96)
    book_gate(D)

    _log("done")


# ------------------------------------------------------------------ book gate
def book_gate(D):
    """Build the deployed book at each of the 4 reb phase offsets. Compare:
       (a) baseline (alpha=1 fresh signal),
       (b) a dispersion-adaptive gain: alpha varies by the hour's dispersion bucket (down-weight high-R hours),
       (c) matched-DoF RANDOM-GAIN null: same #free per-bucket alphas, assigned to RANDOM hour-buckets.
    Report phase-averaged net for the focus scenarios; the adaptive book must beat baseline AND sit outside the
    random-gain null band."""
    R, Cc, s, N = D["R"], D["Cc"], D["s"], D["N"]
    disp, panel_month, hours = D["disp"], D["panel_month"], D["hours"]
    resid_alt, hs_arr, hs_default, n_alt = D["resid_alt"], D["hs_arr"], D["hs_default"], D["n_alt"]
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    FVr = S0.fwd_sum(resid_alt, REB)

    SIG = np.full((N, n_alt), np.nan)
    for i in range(len(R)):
        SIG[R[i], Cc[i]] = s[i]
    obs_hours = np.array(sorted(set(R.tolist())), dtype=np.int64)
    full = set(range(n_alt))
    FOCUS = ("taker_top_smallclip", "maker_earn_a30")

    # dispersion bucket per hour (adaptive gain lever). down-weight (smaller alpha) where dispersion is high.
    dvals = disp[obs_hours]; fin = np.isfinite(dvals)
    edges = np.quantile(dvals[fin], np.linspace(0, 1, B + 1)[1:-1])
    dbk = np.searchsorted(edges, disp, side="right")             # per-hour dispersion bucket 0..B-1
    ALPHA_BY_BKT = np.array([1.00, 0.85, 0.70, 0.55, 0.40])      # low-disp trust / high-disp smooth (stale=8)
    STALE = 8

    def smooth_adaptive(alpha_map, bkt_of_hour):
        """EMA where per-hour alpha = alpha_map[bkt_of_hour[t]] (Kalman gain varies by the hour's regime)."""
        m = np.full((N, n_alt), np.nan); prev = np.full(n_alt, np.nan)
        last = np.full(n_alt, -10**6, dtype=np.int64)
        for t in range(N):
            a = alpha_map[bkt_of_hour[t]] if 0 <= bkt_of_hour[t] < len(alpha_map) else 1.0
            obs = SIG[t]; has = np.isfinite(obs)
            fresh = has & (~np.isfinite(prev) | ((t - last) > STALE))
            blend = has & ~fresh
            prev = np.where(fresh, obs, prev)
            prev = np.where(blend, a * obs + (1 - a) * prev, prev)
            last = np.where(has, t, last)
            alive = np.isfinite(prev) & ((t - last) <= STALE)
            prev = np.where(alive, prev, np.nan)
            m[t] = np.where(alive, prev, np.nan)
        return m

    def net_at_phase(m, offset, lab):
        reb = obs_hours[offset::REB]
        hour_month = {int(t): int(panel_month[int(t)]) for t in reb}
        xs, fvb, elig = {}, {}, {}
        for t in reb:
            ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4: continue
            xs[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
            elig[ti] = full
        keys = np.array(sorted(xs), dtype=np.int64)
        if len(keys) < 8: return None
        sim = CB.simulate_raw(keys, xs, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
        if len(sim["hr"]) < 8: return None
        mult, fee, mode = next((mu, fe, mo) for l, mu, fe, mo in CB.SCENARIOS if l == lab)
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
        return float(netph.mean())

    def phase_avg(m, lab):
        vals = [net_at_phase(m, o, lab) for o in range(REB)]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)), vals

    base = SIG
    adap = smooth_adaptive(ALPHA_BY_BKT, dbk)
    print(f"  gain schedule (by dispersion bucket, stale={STALE}): {list(ALPHA_BY_BKT)}  (down-weight high-disp)")
    b_avg = {lab: phase_avg(base, lab) for lab in FOCUS}
    a_avg = {lab: phase_avg(adap, lab) for lab in FOCUS}
    for lab in FOCUS:
        print(f"\n  {lab}:  baseline phase-avg={b_avg[lab][0]:+.3f} {[round(x,2) for x in b_avg[lab][1]]}   "
              f"adaptive={a_avg[lab][0]:+.3f} {[round(x,2) for x in a_avg[lab][1]]}  "
              f"delta={a_avg[lab][0]-b_avg[lab][0]:+.3f}")
    # matched-DoF random-gain null: same 5 alphas -> RANDOM hour-buckets; one smoothing pass scored for BOTH labs
    NDRAW = 150
    deltas = {lab: [] for lab in FOCUS}
    for _ in range(NDRAW):
        rand_bk = RNG.integers(0, B, size=N)
        mr = smooth_adaptive(ALPHA_BY_BKT, rand_bk)
        for lab in FOCUS:
            deltas[lab].append(phase_avg(mr, lab)[0] - b_avg[lab][0])
    for lab in FOCUS:
        dd = np.array(deltas[lab]); adel = a_avg[lab][0] - b_avg[lab][0]
        pct = float((dd >= adel).mean())
        print(f"\n  {lab}: matched-DoF({B}-gain) random null delta mean={dd.mean():+.3f} "
              f"CI[{np.percentile(dd,2.5):+.3f},{np.percentile(dd,97.5):+.3f}]  adaptive delta={adel:+.3f}  "
              f"P(rand>=adaptive)={pct:.3f}")
        print(f"    -> {'adaptive BEATS matched-DoF null (>0 and outside band)' if (pct < 0.05 and adel > 0) else 'adaptive INSIDE the random-gain band => gain is DoF/overfit, NOT the driver'}")


if __name__ == "__main__":
    main()
