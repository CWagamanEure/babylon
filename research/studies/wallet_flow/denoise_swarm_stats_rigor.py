"""
STATS-RIGOR agent (xsec_denoise_swarm) — hold CLAIM A (alpha~=0.90 denoise) and CLAIM B candidates to proper
inference: multiplicity across the WHOLE arc, honest CIs under multiple resampling schemes, effective independent N,
and the cross-unit sign test.

The load-bearing quantity is NOT the LEVEL at alpha=0.9 (whose marginal CI overlaps baseline's by construction) but
the PAIRED IMPROVEMENT delta = leg(alpha=0.9) - leg(alpha=1.0) on the SAME rebalance hours / SAME name universe
(dense_ema emits only observed hours, so the hour grid + per-hour name set are IDENTICAL across alpha; only the
signal VALUES are smoothed). That makes a clean paired test with variance FAR below the marginal level CIs.

Reuses: kalman_swarm_decisive.{dense_ema,build}, xsec_concentrated_book as CB. No cache mutation, no DuckDB.
    .venv/bin/python -m research.studies.wallet_flow.denoise_swarm_stats_rigor
"""
from __future__ import annotations
import math
import numpy as np
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_concentrated_book as CB
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow.kalman_swarm_decisive import dense_ema, build, CACHE, REB, FOCUS

ALPHA_STAR = 0.90
BOOT = 5000
RNG = np.random.default_rng(11)


# ----------------------------------------------------------------------------- per-alpha aligned series
def eval_series(B, alpha):
    """Return, aligned by rebalance hour: per-leg net-per-hr step series, gross series, per-hour cross-sec IC,
    and the hour index. Keys/universe are alpha-invariant so different alphas align 1:1."""
    m = dense_ema(B["SIG"], alpha)
    full = set(range(B["n_alt"]))
    xs, fvb, elig, ic = {}, {}, {}, {}
    for t in B["reb_grid"]:
        ti = int(t)
        row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
        if len(nm) < 4:
            continue
        sig = row[nm].astype(float)
        fwd = np.array([float(B["FVr"][ti, a]) * 1e4 for a in nm])
        xs[ti] = (nm.astype(int), sig)
        fvb[ti] = {int(a): float(B["FVr"][ti, a]) * 1e4 for a in nm}
        elig[ti] = full
        ic[ti] = A._spear(sig, fwd)          # per-hour cross-sectional Spearman IC (signal vs fwd return)
    keys = np.array(sorted(xs), dtype=np.int64)
    sim = CB.simulate_raw(keys, xs, fvb, B["halfspread"], B["hs_default"], 1, 0.10, 0.15, elig)
    hrs = sim["hr"].astype(np.int64)
    legs = {}
    for lab, mult, fee, mode in CB.SCENARIOS:
        if lab not in FOCUS:
            continue
        netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, B["hs_default"])
        legs[lab] = netph
    ic_series = np.array([ic[int(t)] for t in hrs])
    return dict(hrs=hrs, legs=legs, gross=sim["gross"] / REB, turn=sim["turn"], ic=ic_series)


# ----------------------------------------------------------------------------- resampling schemes on a paired delta
def _blocks(hrs, hours, scheme, panel_month):
    """Return an integer block-id per step for a block-bootstrap scheme."""
    if scheme == "day":
        return (hours[hrs] // 86400000).astype(np.int64)
    if scheme == "week":
        return (hours[hrs] // (7 * 86400000)).astype(np.int64)
    if scheme == "month":
        return np.array([int(panel_month[int(t)]) for t in hrs], dtype=np.int64)
    raise ValueError(scheme)


def block_ci(delta, block_id, boot=BOOT, rng=RNG):
    """Block bootstrap: resample WHOLE blocks with replacement, concatenate, take the mean of delta."""
    ub = np.unique(block_id)
    loc = {b: np.nonzero(block_id == b)[0] for b in ub}
    G = len(ub)
    st = np.empty(boot)
    for i in range(boot):
        pick = ub[rng.integers(0, G, size=G)]
        idx = np.concatenate([loc[b] for b in pick])
        st[i] = delta[idx].mean()
    lo, hi = np.percentile(st, [2.5, 97.5])
    p_two = 2.0 * min((st <= 0).mean(), (st >= 0).mean())   # bootstrap two-sided p that mean=0
    return float(lo), float(hi), float(min(1.0, p_two)), G


def moving_block_ci(delta, L, boot=BOOT, rng=RNG):
    """Circular moving-block bootstrap, block length L, time-ordered series."""
    n = len(delta)
    nb = int(math.ceil(n / L))
    st = np.empty(boot)
    for i in range(boot):
        starts = rng.integers(0, n, size=nb)
        idx = (starts[:, None] + np.arange(L)[None, :]).ravel() % n
        st[i] = delta[idx[:n]].mean()
    lo, hi = np.percentile(st, [2.5, 97.5])
    p_two = 2.0 * min((st <= 0).mean(), (st >= 0).mean())
    return float(lo), float(hi), float(min(1.0, p_two))


def iid_ci(delta, boot=BOOT, rng=RNG):
    n = len(delta)
    st = delta[rng.integers(0, n, size=(boot, n))].mean(axis=1)
    lo, hi = np.percentile(st, [2.5, 97.5])
    p_two = 2.0 * min((st <= 0).mean(), (st >= 0).mean())
    return float(lo), float(hi), float(min(1.0, p_two))


def cluster_t(delta, block_id):
    """Cluster-robust t on mean(delta)=0. var = (1/n^2) sum_g (sum_i in g resid_i)^2 ; two-sided p via normal."""
    n = len(delta); mu = delta.mean(); resid = delta - mu
    ub = np.unique(block_id); G = len(ub)
    v = 0.0
    for b in ub:
        s = resid[block_id == b].sum(); v += s * s
    # finite-cluster correction
    var = (G / max(1, G - 1)) * v / (n * n)
    se = math.sqrt(var) if var > 0 else float("nan")
    t = mu / se if se > 0 else float("nan")
    p = math.erfc(abs(t) / math.sqrt(2)) if np.isfinite(t) else float("nan")
    return mu, se, t, p, G


def sign_test_p(vals):
    vals = [v for v in vals if np.isfinite(v)]
    n = len(vals); k = sum(1 for v in vals if v > 0); kk = max(k, n - k)
    p = min(1.0, 2.0 * sum(math.comb(n, i) for i in range(kk, n + 1)) * 0.5 ** n)
    return n, k, p


def main():
    d = np.load(CACHE, allow_pickle=False)
    B = build(d)
    hours = B["hours"]; panel_month = B["panel_month"]
    s1 = eval_series(B, 1.0)
    s9 = eval_series(B, ALPHA_STAR)
    assert np.array_equal(s1["hrs"], s9["hrs"]), "hour grids diverged — paired test invalid"
    hrs = s1["hrs"]
    shm = np.array([int(panel_month[int(t)]) for t in hrs])
    n = len(hrs)
    print(f"paired steps n={n}  months={sorted(set(shm.tolist()))}\n")

    # ---- 0. levels (reproduce) ----
    print("=== LEVELS (reproduce baseline) : alpha=1 vs alpha=0.90 ===")
    print(f"{'leg':>22} {'a=1 net':>9} {'a=.9 net':>9} {'improve':>9}")
    for lab in FOCUS:
        print(f"{lab:>22} {s1['legs'][lab].mean():>+9.3f} {s9['legs'][lab].mean():>+9.3f} "
              f"{(s9['legs'][lab].mean()-s1['legs'][lab].mean()):>+9.3f}")
    print(f"{'gross/hr':>22} {s1['gross'].mean():>+9.3f} {s9['gross'].mean():>+9.3f} "
          f"{s9['gross'].mean()-s1['gross'].mean():>+9.3f}")
    ic1, ic9 = np.nanmean(s1['ic']), np.nanmean(s9['ic'])
    print(f"{'mean per-hr IC':>22} {ic1:>+9.4f} {ic9:>+9.4f} {ic9-ic1:>+9.4f}  "
          f"(IC +{100*(ic9-ic1)/ic1:.0f}% vs gross +{100*(s9['gross'].mean()-s1['gross'].mean())/s1['gross'].mean():.0f}%)")

    # ---- 1. PAIRED IMPROVEMENT under multiple resampling schemes ----
    print("\n=== PAIRED IMPROVEMENT delta = leg(a=.9) - leg(a=1), multi-scheme CI + cluster-t ===")
    day_b = _blocks(hrs, hours, "day", panel_month)
    week_b = _blocks(hrs, hours, "week", panel_month)
    month_b = _blocks(hrs, hours, "month", panel_month)
    L = max(2, int(round(n ** (1 / 3))))
    schemes_out = {}
    for lab in FOCUS + ("__gross__", "__ic__"):
        if lab == "__gross__":
            delta = s9["gross"] - s1["gross"]; disp = "gross/hr improve"
        elif lab == "__ic__":
            delta = s9["ic"] - s1["ic"]; delta = np.where(np.isfinite(delta), delta, 0.0); disp = "per-hr IC improve"
        else:
            delta = s9["legs"][lab] - s1["legs"][lab]; disp = lab
        r = {}
        r["day"] = block_ci(delta, day_b)
        r["week"] = block_ci(delta, week_b)
        r["month"] = block_ci(delta, month_b)
        r["movblk"] = moving_block_ci(delta, L)
        r["iid"] = iid_ci(delta)
        mu, se, t, pt, G = cluster_t(delta, week_b)      # week-clustered t as the headline
        mu_m, se_m, t_m, pt_m, Gm = cluster_t(delta, month_b)
        schemes_out[lab] = (r, (mu, t, pt, G), (mu_m, t_m, pt_m, Gm))
        print(f"\n  {disp}   mean_delta={delta.mean():+.4f}")
        for sc in ("day", "week", "month", "movblk", "iid"):
            if sc == "movblk":
                lo, hi, p = r[sc]; g = f"L={L}"
            elif sc == "iid":
                lo, hi, p = r[sc]; g = "iid"
            else:
                lo, hi, p, gg = r[sc]; g = f"{gg}blk"
            star = "*" if lo > 0 else ("-" if hi < 0 else " ")
            print(f"      {sc:>7} CI[{lo:+.3f},{hi:+.3f}] p={p:.4f} {g:>8} {star}")
        print(f"      week-cluster t={t:+.2f} (G={G} weeks) p={pt:.4g}   month-cluster t={t_m:+.2f} (G={Gm}) p={pt_m:.4g}")

    # ---- 2. SIGN TEST on per-fold paired improvement ----
    print("\n=== SIGN TEST: per-fold paired improvement (cross-independent-unit gate) ===")
    print(f"{'leg':>22}   per-fold delta (a=.9 - a=1)                          folds+  p2sided")
    for lab in FOCUS + ("__gross__",):
        if lab == "__gross__":
            d9, d1 = s9["gross"], s1["gross"]
        else:
            d9, d1 = s9["legs"][lab], s1["legs"][lab]
        perf = []
        for mm in sorted(set(shm.tolist())):
            msk = shm == mm
            perf.append(d9[msk].mean() - d1[msk].mean())
        nn, k, p = sign_test_p(perf)
        cells = " ".join(f"{v:+.2f}" for v in perf)
        print(f"{lab:>22}   {cells}   {k}/{nn}  p={p:.4f}")

    # fold-delta autocorrelation (independence of the 7 folds)
    print("\n  --- fold independence: lag-1 autocorr of the maker_earn_a30 paired-delta fold series ---")
    d9, d1 = s9["legs"]["maker_earn_a30"], s1["legs"]["maker_earn_a30"]
    perf = np.array([ (d9[shm == mm].mean() - d1[shm == mm].mean()) for mm in sorted(set(shm.tolist())) ])
    pc = perf - perf.mean()
    ac1 = float((pc[:-1] @ pc[1:]) / (pc @ pc)) if (pc @ pc) > 0 else float("nan")
    print(f"      fold deltas = {['%+.3f'%v for v in perf]}  lag-1 autocorr={ac1:+.3f}")

    # ---- 3. TAKER LEVEL 'CI clears 0' under multiplicity ----
    print("\n=== TAKER LEVEL 'CI clears 0' at a=0.90 : own p, then multiplicity correction ===")
    for lab in ("taker_top_smallclip", "taker_top_impact"):
        v = s9["legs"][lab]
        lo, hi, p_lvl, G = block_ci(v, day_b)     # day-block, matches the frozen engine's _dayblock_ci scheme
        print(f"  {lab:>22} level net={v.mean():+.3f}  day-block CI[{lo:+.3f},{hi:+.3f}]  raw two-sided p={p_lvl:.4f}")
        for fam, name in [(13, "alpha-grid only"),
                          (13 * 2, "alpha x regime"),
                          (13 * 2 * 3, "alpha x regime x reb-ish"),
                          (13 * 2 * 3 * 3, "x space(level/rank/z)"),
                          (13 * 2 * 3 * 3 * 4, "x 4 focus legs (full arc)")]:
            bonf = min(1.0, p_lvl * fam)
            print(f"        Bonferroni x{fam:>4} ({name:26s}) -> p={bonf:.3f} {'SURVIVES' if bonf<0.05 else 'DIES'}")

    # ---- 3b. OOS (LATE-fold-only) paired improvement — multiplicity-IMMUNE confirmation ----
    print("\n=== OOS paired improvement on LATE folds only {202604,202605,202606} (alpha* frozen on EARLY) ===")
    late = {202604, 202605, 202606}
    lmsk = np.array([m in late for m in shm.tolist()])
    day_bl = day_b[lmsk]
    for lab in ("maker_earn_a30", "taker_top_smallclip", "__gross__"):
        if lab == "__gross__":
            delta = (s9["gross"] - s1["gross"])[lmsk]; disp = "gross/hr"
        else:
            delta = (s9["legs"][lab] - s1["legs"][lab])[lmsk]; disp = lab
        lo, hi, p, G = block_ci(delta, day_bl)
        star = "*" if lo > 0 else ("-" if hi < 0 else " ")
        print(f"  {disp:>22} LATE-only mean_delta={delta.mean():+.3f} day-block CI[{lo:+.3f},{hi:+.3f}] p={p:.4f} n={lmsk.sum()} {star}")

    # ---- 4. EFFECTIVE N : coin x week clusters (for the IC/gross estimate) ----
    print("\n=== EFFECTIVE INDEPENDENT N ===")
    n_days = len(np.unique(day_b)); n_weeks = len(np.unique(week_b)); n_months = len(np.unique(month_b))
    print(f"  rebalance steps (reb{REB}) = {n}")
    print(f"  time-block units: days={n_days}  weeks={n_weeks}  months(folds)={n_months}")
    # coin x week clusters actually populated in the signal panel
    R = d["R"].astype(np.int64); Cc = d["Cc"].astype(np.int64); sinf = d["s_inf"]
    fin = np.isfinite(sinf)
    wk = (hours[R[fin]] // (7 * 86400000)).astype(np.int64)
    coin = Cc[fin]
    cw = set(zip(coin.tolist(), wk.tolist()))
    print(f"  populated coin-week clusters in signal panel = {len(cw)}  "
          f"(n_alt={int(d['n_alt'])} coins x {len(np.unique(wk))} weeks)")
    # per-hour IC t-stat with week clustering (is the IC improvement real given the tail-amplified gross?)
    ic_d = s9["ic"] - s1["ic"]; ic_d = np.where(np.isfinite(ic_d), ic_d, 0.0)
    mu, se, t, p, G = cluster_t(ic_d, week_b)
    gr_d = s9["gross"] - s1["gross"]
    mug, seg, tg, pg, Gg = cluster_t(gr_d, week_b)
    print(f"  IC improvement:    mean={mu:+.4f} week-cluster t={t:+.2f} p={p:.4g}")
    print(f"  gross improvement: mean={mug:+.4f} week-cluster t={tg:+.2f} p={pg:.4g}")
    print("  -> if gross-t >> IC-t, the decile-spread gain is partly tail-amplification beyond the broad-ranking IC gain")


if __name__ == "__main__":
    main()
