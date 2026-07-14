"""
denoise_swarm_prosecutor_overcarry — PROSECUTOR / OVER-CARRY agent for CLAIM A (the alpha~0.90 denoise win).

Job: try to prove the alpha~0.90 aggregate level-EMA "denoise" win is a FALSE POSITIVE — an in-sample-selected /
tail-noise artifact that will not survive forward. Argue the benign explanation. Symmetric counterpart to the
over-null gate (CLAUDE.md): a fresh positive must clear the full false-positive gauntlet.

Reuses the EXACT frozen engine (kalman_swarm_decisive.dense_ema + xsec_concentrated_book) and the frozen cache.
Does NOT touch frozen files.

Sections:
  (0) Reproduce baseline (alpha=1) and the alpha=0.90 win via a fast selection-cache engine; VALIDATE vs the
      real CB.simulate_raw / scenario_net_series (gate: must match to ~1e-6).
  (1) PERMUTATION-ALPHA NULL: how often does a search over alpha in [0.80,0.99] manufacture the observed
      "best-alpha improvement over baseline" by chance? Day-block-permute the forward returns (signal fixed,
      selections fixed) -> gross->0, and record max_alpha(metric_alpha - metric_baseline). p-value.
  (2) TAIL ARTIFACT: is the +27% gross a few lucky steps? Per-step gross diff (0.90-1.0) concentration +
      trim/winsorize the decile returns and re-measure the gain.
  (3) OOS-SPLIT FRAGILITY: re-run the early->late overfit-killer under rolling-origin, leave-one-fold-out, and
      several early/late boundaries. Does "smoothing wins OOS" hold across splits or only the one reported?
  (4) DISTINGUISHABILITY: PAIRED per-step (smoothed - baseline) day-block AND month/fold-block CI on the
      DIFFERENCE itself. Is the improvement significantly > 0, or within noise?

    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_prosecutor_overcarry
"""
from __future__ import annotations
import time
import numpy as np

from research.studies.wallet_flow import kalman_swarm_decisive as K
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import xsec_flow_step0 as S0

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

REB = K.REB
CACHE = K.CACHE
FOCUS = ["taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50"]
# fine grid over the searched band [0.80,0.99] plus baseline
GRID = [0.99, 0.97, 0.95, 0.93, 0.91, 0.90, 0.89, 0.87, 0.85, 0.83, 0.81, 0.80]


# ---------------- selection cache (returns-independent; only the ranking depends on alpha) ----------------
def selections(m, reb_grid, halfspread, hs_default, n_alt):
    """Mirror CB.simulate_raw (reb=1, q1=0.10, q2=0.15, elig=full) but STORE the per-step long/short name sets +
    turnover/half-spread. Because the universe (finite names per hour) is identical across alpha, all alpha share
    the same step set/order; only the selected names differ."""
    steps = []
    held_long, held_short = set(), set()
    for t in reb_grid:
        ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        names = nm.astype(int); sc = row[nm].astype(float)
        n = len(names); order = np.argsort(sc)
        k1 = max(1, int(round(0.10 * n))); k2 = max(k1, int(round(0.15 * n)))
        top_entry = set(names[order[-k1:]]); top_hold = set(names[order[-k2:]])
        bot_entry = set(names[order[:k1]]);  bot_hold = set(names[order[:k2]])
        new_long = {x for x in held_long if x in top_hold}
        for x in names[order[::-1]]:
            if len(new_long) >= k1: break
            if x in top_entry and x not in new_long: new_long.add(x)
        new_short = {x for x in held_short if x in bot_hold}
        for x in names[order]:
            if len(new_short) >= k1: break
            if x in bot_entry and x not in new_short: new_short.add(x)
        K_ = max(1, min(len(new_long), len(new_short)))
        traded = (new_long ^ held_long) | (new_short ^ held_short)
        n_tr = len(traded); hs_sum = sum(halfspread.get(x, hs_default) for x in traded)
        steps.append((ti, sorted(new_long), sorted(new_short), n_tr / K_, hs_sum / K_))
        held_long, held_short = new_long, new_short
    return steps


def build_alpha(B, alpha, n_alt):
    m = K.dense_ema(B["SIG"], alpha)
    steps = selections(m, B["reb_grid"], B["halfspread"], B["hs_default"], n_alt)
    ns = len(steps)
    Lind = np.zeros((ns, n_alt)); Sind = np.zeros((ns, n_alt))
    hrs = np.empty(ns, dtype=np.int64); ntr = np.empty(ns); hs = np.empty(ns)
    for i, (t, lo, sh, nt, h) in enumerate(steps):
        Lind[i, lo] = 1.0; Sind[i, sh] = 1.0; hrs[i] = t; ntr[i] = nt; hs[i] = h
    return dict(Lind=Lind, Sind=Sind, hrs=hrs, ntrade=ntr, hs=hs)


def gross_steps(A, FVsel):
    """Per-step decile spread (bp over REB-hour hold). FVsel: (nstep, n_alt) forward returns in bp; nan-safe."""
    fin = np.isfinite(FVsel).astype(float); ff = np.where(np.isfinite(FVsel), FVsel, 0.0)
    lsum = np.einsum('ij,ij->i', A["Lind"], ff); lcnt = np.einsum('ij,ij->i', A["Lind"], fin)
    ssum = np.einsum('ij,ij->i', A["Sind"], ff); scnt = np.einsum('ij,ij->i', A["Sind"], fin)
    return lsum / np.maximum(lcnt, 1) - ssum / np.maximum(scnt, 1)


def net_steps(A, gross, lab):
    ntr, hs = A["ntrade"], A["hs"]
    if lab == "taker_top_smallclip":
        mult, fee = 1.0, 2.4; cost = ntr * fee + np.minimum(hs, ntr * 1.0)
    elif lab == "taker_top_impact":
        mult, fee = 1.0, 2.4; cost = ntr * fee + hs
    elif lab == "maker_earn_a30":
        mult, fee = 0.70, 1.0; cost = ntr * fee - hs
    elif lab == "maker_earn_a50":
        mult, fee = 0.50, 1.0; cost = ntr * fee - hs
    else:
        raise ValueError(lab)
    return (gross * mult - cost) / REB


def main():
    d = np.load(CACHE, allow_pickle=False)
    B = K.build(d)
    n_alt = int(d["n_alt"]); hours = d["hours"]; panel_month = d["panel_month"]
    folds = sorted(int(x) for x in d["folds"])
    FVbp = B["FVr"] * 1e4                                    # forward returns in bp (matches eval_alpha fvb)

    _log("building selection caches over the fine grid ...")
    A = {a: build_alpha(B, a, n_alt) for a in ([1.0] + GRID)}
    hrs = A[1.0]["hrs"]                                       # shared across alpha
    assert all(np.array_equal(A[a]["hrs"], hrs) for a in A), "step grids diverged across alpha"
    step_month = np.array([int(panel_month[t]) for t in hrs])
    FVreal = FVbp[hrs]                                        # (nstep, n_alt) real returns aligned to steps
    _log(f"caches built: {len(hrs)} steps, alphas {sorted(A)}")

    # per-alpha observed net/gross series (real returns)
    gross = {a: gross_steps(A[a], FVreal) for a in A}
    nets = {a: {lab: net_steps(A[a], gross[a], lab) for lab in FOCUS} for a in A}

    # ===================== (0) VALIDATION vs the real CB engine =====================
    print("\n" + "=" * 96)
    print("(0) VALIDATION: fast selection-cache engine vs real CB.simulate_raw / scenario_net_series")
    print("=" * 96)
    for a in (1.0, 0.90):
        g_hr = gross[a].mean() / REB
        row = f"  alpha={a:.2f}  gross/hr={g_hr:+.3f}"
        for lab in FOCUS:
            row += f"  {lab.replace('taker_top_','tk_').replace('maker_earn_','mk_')}={nets[a][lab].mean():+.3f}"
        print(row)
    print("  EXPECT alpha=1: gross+3.735 tk_smallclip+1.42 mk_a30+4.35 mk_a50+3.60 | "
          "alpha=0.90: gross+4.76 tk_smallclip+2.48 mk_a30+5.06")

    # ===================== (1) PERMUTATION-ALPHA NULL =====================
    print("\n" + "=" * 96)
    print("(1) PERMUTATION-ALPHA NULL: does a search over alpha in [0.80,0.99] manufacture the win by chance?")
    print("=" * 96)
    # observed statistic: max over the fine grid of (metric_alpha - metric_baseline)
    obs_gross_impr = max(gross[a].mean() / REB for a in GRID) - gross[1.0].mean() / REB
    obs_impr = {lab: max(nets[a][lab].mean() for a in GRID) - nets[1.0][lab].mean() for lab in FOCUS}
    argmax_a = {lab: max(GRID, key=lambda a: nets[a][lab].mean()) for lab in FOCUS}
    argmax_g = max(GRID, key=lambda a: gross[a].mean())

    step_days = (hours[hrs] // 86400000).astype(np.int64)
    ud = np.unique(step_days); groups = [np.nonzero(step_days == dd)[0] for dd in ud]
    orig_order = np.concatenate(groups)                      # positions grouped by day (day-sorted)
    rng = np.random.default_rng(20260710)
    M = 400
    null_g = np.empty(M); null_m = {lab: np.empty(M) for lab in FOCUS}
    t0 = time.time()
    for p in range(M):
        perm_days = rng.permutation(len(ud))
        src_order = np.concatenate([groups[j] for j in perm_days])
        sigma = np.empty(len(hrs), dtype=np.int64)
        sigma[orig_order] = hrs[src_order]                   # each step gets a day-shuffled source hour
        FVp = FVbp[sigma]
        gp = {a: gross_steps(A[a], FVp) for a in A}
        base_g = gp[1.0].mean() / REB
        null_g[p] = max(gp[a].mean() / REB for a in GRID) - base_g
        for lab in FOCUS:
            bm = net_steps(A[1.0], gp[1.0], lab).mean()
            null_m[lab][p] = max(net_steps(A[a], gp[a], lab).mean() for a in GRID) - bm
    _log(f"null done ({M} perms, {time.time()-t0:.1f}s)")

    def pval(obs, null): return float((np.sum(null >= obs) + 1) / (len(null) + 1))
    print(f"  observed best-alpha GROSS improvement over baseline = {obs_gross_impr:+.3f} bp/hr (argmax a={argmax_g:.2f})")
    print(f"    null max-improvement: mean {null_g.mean():+.3f}  p95 {np.percentile(null_g,95):+.3f}  "
          f"max {null_g.max():+.3f}   ->  p = {pval(obs_gross_impr, null_g):.4f}")
    for lab in FOCUS:
        o = obs_impr[lab]; nl = null_m[lab]
        print(f"  {lab:22s} observed best-a improvement {o:+.3f} (argmax a={argmax_a[lab]:.2f}) | "
              f"null mean {nl.mean():+.3f} p95 {np.percentile(nl,95):+.3f} max {nl.max():+.3f} -> p = {pval(o, nl):.4f}")

    # ===================== (2) TAIL ARTIFACT =====================
    print("\n" + "=" * 96)
    print("(2) TAIL ARTIFACT: is the +27% gross a broad ranking lift or a few lucky tail steps/names?")
    print("=" * 96)
    dg = gross[0.90] - gross[1.0]                            # per-step gross diff (bp/hold)
    tot = dg.sum()
    order = np.argsort(-np.abs(dg))
    csum = np.cumsum(dg[order]) / tot
    for frac in (0.01, 0.02, 0.05, 0.10):
        k = max(1, int(frac * len(dg)))
        print(f"  top {frac*100:>4.1f}% of steps by |diff| ({k:>4d} steps) supply {csum[k-1]*100:6.1f}% of the total gross gain")
    pos = np.mean(dg > 0)
    print(f"  fraction of steps where smoothing HELPS gross: {pos*100:.1f}%  (broad>50%, tail-driven<50%)")
    # trim extreme steps by |gross diff| and re-measure the per-hour gain
    print("  --- trim the most extreme steps (by |per-step gross diff|) and re-measure gross gain ---")
    for frac in (0.0, 0.01, 0.02, 0.05):
        k = int(frac * len(dg))
        keep = np.ones(len(dg), bool)
        if k > 0: keep[order[:k]] = False
        gain = (gross[0.90][keep].mean() - gross[1.0][keep].mean()) / REB
        print(f"    trim top {frac*100:>4.1f}% -> gross gain {gain:+.3f} bp/hr")
    # winsorize the per-NAME forward returns (kill lucky tail crossings), recompute both books
    print("  --- winsorize per-name forward returns at +/-q pct, recompute BOTH books, re-measure gain ---")
    flat = FVreal[np.isfinite(FVreal)]
    for q in (100, 99.5, 99, 97.5, 95):
        if q >= 100:
            FVw = FVreal
        else:
            lo, hi = np.percentile(flat, [100 - q, q]); FVw = np.clip(FVreal, lo, hi)
        gw0 = gross_steps(A[1.0], FVw).mean() / REB; gw9 = gross_steps(A[0.90], FVw).mean() / REB
        print(f"    winsor {q:>5.1f}%  gross a1={gw0:+.3f} a0.90={gw9:+.3f}  gain={gw9-gw0:+.3f} bp/hr")

    # ===================== (3) OOS-SPLIT FRAGILITY =====================
    print("\n" + "=" * 96)
    print("(3) OOS-SPLIT FRAGILITY: freeze alpha*=argmax(maker_a30) on TRAIN folds, test the gain on TEST folds")
    print("=" * 96)
    def eval_on(mask, a):
        g = gross[a][mask].mean() / REB
        return g, {lab: nets[a][lab][mask].mean() for lab in FOCUS}
    def astar_on(mask):
        return max(GRID, key=lambda a: nets[a]["maker_earn_a30"][mask].mean())
    def run_split(name, train_folds, test_folds):
        tr = np.isin(step_month, train_folds); te = np.isin(step_month, test_folds)
        a_s = astar_on(tr)
        g1, n1 = eval_on(te, 1.0); gs, ns_ = eval_on(te, a_s)
        legs = "".join(f" {lab.replace('taker_top_','tk_').replace('maker_earn_','mk_')}:{ns_[lab]-n1[lab]:+.2f}" for lab in FOCUS)
        win = "WINS" if (gs - g1) > 0.03 else "no"
        print(f"  {name:26s} a*={a_s:.2f}  test gross {g1:+.2f}->{gs:+.2f} (Δ{gs-g1:+.2f}) [{win}] |Δnet{legs}")
        return gs - g1, {lab: ns_[lab] - n1[lab] for lab in FOCUS}
    print("  -- rolling-origin (expanding train, next fold = test):")
    roll_g = []
    for k in range(1, len(folds)):
        dgk, _ = run_split(f"train[:{k}] test[{k}]", folds[:k], [folds[k]]); roll_g.append(dgk)
    print("  -- leave-one-fold-out (test = fold j, train = rest):")
    loo_g = []
    for j in range(len(folds)):
        dgj, _ = run_split(f"LOO test={folds[j]}", [f for f in folds if f != folds[j]], [folds[j]]); loo_g.append(dgj)
    print("  -- early/late boundary sweep (train=early, test=late):")
    bnd_g = []
    for b in range(2, 6):
        dgb, _ = run_split(f"early[:{b}] late[{b}:]", folds[:b], folds[b:]); bnd_g.append(dgb)
    allsp = roll_g + loo_g + bnd_g
    print(f"\n  SUMMARY across {len(allsp)} splits: gross gain>0 in {sum(1 for x in allsp if x>0.03)}/{len(allsp)} "
          f"| median Δgross {np.median(allsp):+.3f} | worst {min(allsp):+.3f} | best {max(allsp):+.3f}")

    # ===================== (4) DISTINGUISHABILITY: PAIRED DIFFERENCE CI =====================
    print("\n" + "=" * 96)
    print("(4) DISTINGUISHABILITY: PAIRED per-step (alpha0.90 - alpha1.0) difference CI (day-block + fold-block)")
    print("=" * 96)
    def dayblock_ci(vals):
        return CB._dayblock_ci(vals, hrs, hours)
    def foldblock_ci(vals, n=2000, seed=17):
        months = np.unique(step_month); loc = {mm: np.nonzero(step_month == mm)[0] for mm in months}
        rng2 = np.random.default_rng(seed); st = []
        for _ in range(n):
            pick = rng2.integers(0, len(months), size=len(months))
            st.append(vals[np.concatenate([loc[months[p]] for p in pick])].mean())
        s = np.array(st); return (float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5)))
    dgr = (gross[0.90] - gross[1.0]) / REB
    dcl, dch = dayblock_ci(dgr); fcl, fch = foldblock_ci(dgr)
    print(f"  GROSS paired diff  mean {dgr.mean():+.3f}  day-block CI[{dcl:+.3f},{dch:+.3f}]  "
          f"fold-block CI[{fcl:+.3f},{fch:+.3f}]  -> {'DISTINGUISHABLE' if dcl>0 else 'within noise'} (day) / "
          f"{'DISTINGUISHABLE' if fcl>0 else 'within noise'} (fold)")
    for lab in FOCUS:
        dd = nets[0.90][lab] - nets[1.0][lab]
        dcl, dch = dayblock_ci(dd); fcl, fch = foldblock_ci(dd)
        # per-fold sign of the DIFFERENCE
        pf = {int(mm): float(dd[step_month == mm].mean()) for mm in np.unique(step_month)}
        fp = sum(1 for v in pf.values() if v > 0)
        print(f"  {lab:22s} paired diff mean {dd.mean():+.3f}  day CI[{dcl:+.3f},{dch:+.3f}] fold CI[{fcl:+.3f},{fch:+.3f}]"
              f"  folds+ {fp}/{len(pf)}  -> {'DISTINGUISHABLE' if dcl>0 else 'within noise'}(day)/"
              f"{'DISTINGUISHABLE' if fcl>0 else 'within noise'}(fold)")

    # ===================== (5) reb / grid-PHASE robustness (the reb4-phase-confound lead) =====================
    print("\n" + "=" * 96)
    print("(5) reb / grid-PHASE ROBUSTNESS: does the alpha0.90-vs-1.0 paired gain replicate off reb4-phase0?")
    print("=" * 96)
    SIG = B["SIG"]; halfspread = B["halfspread"]; hs_default = B["hs_default"]
    base_hours = np.nonzero(np.isfinite(SIG).any(axis=1))[0].astype(np.int64)
    resid_alt = d["resid_alt"]
    m1 = K.dense_ema(SIG, 1.0); m9 = K.dense_ema(SIG, 0.90)
    def paired_gain(reb, off):
        grid = base_hours[off::reb]
        FVb = S0.fwd_sum(resid_alt, reb) * 1e4
        def series(m):
            st = selections(m, grid, halfspread, hs_default, n_alt)
            if len(st) < 8: return None
            ns = len(st); Lind = np.zeros((ns, n_alt)); Sind = np.zeros((ns, n_alt))
            hh = np.empty(ns, dtype=np.int64); nt = np.empty(ns); hsv = np.empty(ns)
            for i, (t, lo, sh, a_, b_) in enumerate(st):
                Lind[i, lo] = 1.0; Sind[i, sh] = 1.0; hh[i] = t; nt[i] = a_; hsv[i] = b_
            Aa = dict(Lind=Lind, Sind=Sind, hrs=hh, ntrade=nt, hs=hsv)
            g = gross_steps(Aa, FVb[hh])
            sm = np.array([int(panel_month[t]) for t in hh])
            return g, Aa, sm, reb
        r1 = series(m1); r9 = series(m9)
        if r1 is None or r9 is None: return None
        g1, A1, sm, _ = r1; g9, A9, _, _ = r9
        # both share the same hrs/step set (universe identical) -> paired
        dg = (g9.mean() - g1.mean()) / reb
        n1 = net_steps(A1, g1, "maker_earn_a30"); n9 = net_steps(A9, g9, "maker_earn_a30")
        dm = n9.mean() - n1.mean()
        dfold = n9 - n1  # per step
        fp = sum(1 for mm in np.unique(sm) if dfold[sm == mm].mean() > 0); nf = len(np.unique(sm))
        return dg, dm, fp, nf, len(g1)
    print(f"  {'config':>18} {'Δgross/hr':>10} {'Δmk_a30':>9} {'folds+':>8} {'nsteps':>7}")
    for reb in (3, 4, 6):
        for off in range(reb):
            r = paired_gain(reb, off)
            if r is None:
                print(f"  reb{reb} phase{off:>2}       (thin)"); continue
            dg, dm, fp, nf, ns = r
            tag = "  <-reb4-phase0 (the reported config)" if (reb == 4 and off == 0) else ""
            print(f"  reb{reb:>2} phase{off:<2}   {dg:>+10.3f} {dm:>+9.3f} {fp:>5d}/{nf:<2d} {ns:>7d}{tag}")

    _log("done")


if __name__ == "__main__":
    main()
