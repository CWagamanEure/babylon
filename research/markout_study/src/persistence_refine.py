"""
OOS-persistence REFINEMENT (PERSISTENCE_REFINE_ARCHITECTURE.md v2) — EXPLORATORY.

Dual ew/vw scoring x top-N (K) x {expanding, rolling1} train x 12 horizons x 7 metrics, reported
DESCRIPTIVELY (no per-cell significance). Plus the ONE honest inferential exit: a deterministic
graduation RULE (max over configs of mean_folds(S) - std_folds(S), primary family = non-censored
horizon, K<=50) whose winner is tested by a CONFIG-SELECTION-CORRECTED global permutation null (the
same rule re-applied to each permuted grid) — the only p that corrects the ~8k-cell selection.

Reuses audited machinery: base.priced_close_ms/rank_desc, sweep.wallet_agg_ext/pool_metrics.
ew is active-only and SYMMETRIC with vw (never the silent-as-0 ew0). Rolling uses FIRST_TEST=1 and
the identical single-seam purge. Leak-audited: nothing test-window enters ranking.

Outputs: refine_grid.parquet (descriptive), refine_graduation.parquet (rule winners + corrected p).
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import H_LABELS, H_MS, MAJORS, COST_BPS, winsor_cap, apply_winsor, _load_bars, T0
import oos_persistence as base
import persistence_sweep as sw

OUT = Path(__file__).resolve().parents[1] / "out"
HORIZONS = list(H_LABELS)
METRICS = sw.METRICS + ["median_edge", "trim10_edge"]   # 7 + 2 outlier-robust rankers
FLOOR = 30
KS = [10, 25, 50, 100, 200]
K_MIN = min(KS)
K_GRAD_MAX = 50                            # graduation primary family: K<=50
TRAINS = ["expanding", "rolling1"]
CENSOR = sw.CENSOR_HORIZONS               # {"72h","168h"}
SCORABLE_MIN = sw.SCORABLE_MIN
BUCKET_MS = base.BUCKET_MS
R_GRAD = 500
SEED = 12345
EPS = 1e-9


def robust_metrics(inv_a, r_a, W, trim=0.1):
    """Vectorized per-wallet MEDIAN and TRIMMED MEAN (bps) — fully outlier-immune rankers (one lucky
    trade cannot move a median). lexsort by (wallet, value) then prefix sums; no per-wallet loop."""
    med = np.full(W, np.nan); trm = np.full(W, np.nan)
    fin = np.isfinite(r_a)
    inv_a = inv_a[fin]; r_a = r_a[fin]
    if inv_a.size == 0:
        return med, trm
    order = np.lexsort((r_a, inv_a))                 # by wallet, ascending value within wallet
    iv = inv_a[order]; rv = r_a[order]
    uniq, start = np.unique(iv, return_index=True)
    counts = np.diff(np.append(start, iv.size))
    mid = start + (counts - 1) // 2
    mid2 = np.minimum(mid + 1, iv.size - 1)
    even = counts % 2 == 0
    med[uniq] = np.where(even, 0.5 * (rv[mid] + rv[mid2]), rv[mid]) * 1e4
    pref = np.concatenate([[0.0], np.cumsum(rv)])
    lo = (trim * counts).astype(np.int64)
    tstart = start + lo; tend = start + counts - lo; tcnt = tend - tstart
    tsum = pref[tend] - pref[tstart]; full = pref[start + counts] - pref[start]
    trm[uniq] = np.where(tcnt > 0, tsum / np.maximum(tcnt, 1), full / counts) * 1e4
    return med, trm


def refine_tables(ctx, floor, train_mode):
    """Per (horizon, fold): purge, aggregate, eligibility(>=K_MIN), 7 metrics, test contribs.
    train_mode: 'expanding' (train=all buckets <t) or 'rolling1' (train=bucket t-1). FIRST_TEST=1
    for rolling, 4 for expanding."""
    W, inv, notl, b_ts, bucket = ctx["W"], ctx["inv"], ctx["notl"], ctx["b_ts"], ctx["bucket"]
    first = 1 if train_mode == "rolling1" else base.FIRST_TEST
    tab = {}
    for hi, hl in enumerate(HORIZONS):
        h_ms = int(H_MS[hi]); cap_te = ctx["cap_full"][hi]
        pexit = base.priced_close_ms(b_ts + h_ms)
        col = ctx["ret_raw"][:, hi]; fin = np.isfinite(col)
        per_t = {}
        for t in range(first, ctx["n_buckets"]):
            test_start = T0 + t * BUCKET_MS
            train_mask = (b_ts < test_start) if train_mode == "expanding" else (bucket == t - 1)
            adm = fin & train_mask & (pexit <= test_start)          # identical single-seam purge
            if not adm.any():
                continue
            cap_tr = winsor_cap(col[adm])                            # recomputed per fold (rolling too)
            r_w_tr = apply_winsor(col, cap_tr)
            tr = sw.wallet_agg_ext(inv[adm], W, r_w_tr[adm], col[adm], notl[adm])
            elig = np.nonzero(tr["cnt"] >= floor)[0]
            if elig.size < K_MIN:                                    # gate on min(K), not 50
                continue
            field_std = float(np.std(col[adm], ddof=1) * 1e4) if adm.sum() > 1 else EPS
            tstat, eb, degen = sw.pool_metrics(tr, elig, field_std)
            med, trm = robust_metrics(inv[adm], r_w_tr[adm], W)
            metrics = {m: tr[m] for m in sw.BASE_METRICS}
            metrics["tstat"] = tstat; metrics["eb_edge"] = eb
            metrics["median_edge"] = med; metrics["trim10_edge"] = trm
            tmask = fin & (bucket == t)
            r_w_te = apply_winsor(col, cap_te)
            te = sw.wallet_agg_ext(inv[tmask], W, r_w_te[tmask], col[tmask], notl[tmask])
            nwin = int((bucket == t).sum())
            per_t[t] = dict(elig=elig, metrics=metrics, te_mkusd=te["sum_mkusd"],
                            te_notl=te["sum_notl"], te_cnt=te["cnt"], te_sumw=te["sum_w"],
                            scorable=(float(tmask.sum()) / nwin if nwin else 0.0),
                            degenerate=degen)
        tab[hi] = per_t
    return tab


def _pick_perfold(tab_h, codes, order_by, K):
    """For each fold with pool>=K, rank by `order_by` (metric-name -> use metrics; None -> use the
    provided score array), take top-K, return per-fold (S_vw, S_ew, num_vw, den_vw, num_ew, nact)."""
    rows = []
    for s in tab_h.values():
        vals = s["metrics"][order_by] if isinstance(order_by, str) else order_by
        order = base.rank_desc(vals, codes, np.isin(codes, s["elig"])) if isinstance(order_by, str) \
            else s["elig"][np.lexsort((s["elig"], -order_by[s["elig"]]))]
        if order.size < K:                                          # per-K skip+flag
            continue
        pick = order[:K]
        act = s["te_cnt"][pick] > 0
        num_vw = float(s["te_mkusd"][pick].sum()); den_vw = float(s["te_notl"][pick].sum())
        perw = np.where(act, s["te_sumw"][pick] / np.maximum(s["te_cnt"][pick], 1), 0.0)
        num_ew = float(perw[act].sum()); nact = int(act.sum())
        s_vw = num_vw / den_vw * 1e4 if den_vw > 0 else np.nan
        s_ew = num_ew / nact * 1e4 if nact > 0 else np.nan
        rows.append((s_vw, s_ew, num_vw, den_vw, num_ew, nact))
    return rows


def grid_rows(ctx, tabs):
    """Descriptive rows for one coin across metric x horizon x K x train x eval."""
    coin, codes = ctx["coin"], ctx["codes"]
    out = []
    for train_mode, tab in tabs.items():
        for hi, hl in enumerate(HORIZONS):
            tab_h = tab[hi]
            if not tab_h:
                continue
            stratum = "censoring" if (hl in CENSOR or
                       np.mean([s["scorable"] for s in tab_h.values()]) < SCORABLE_MIN) else "primary_family"
            for metric in METRICS:
                for K in KS:
                    pf = _pick_perfold(tab_h, codes, metric, K)
                    if not pf:
                        continue
                    a = np.array(pf, dtype=float)   # cols: s_vw,s_ew,num_vw,den_vw,num_ew,nact
                    pooled_vw = a[:, 2].sum() / a[:, 3].sum() * 1e4 if a[:, 3].sum() > 0 else np.nan
                    pooled_ew = a[:, 4].sum() / a[:, 5].sum() * 1e4 if a[:, 5].sum() > 0 else np.nan
                    for eval_, col, pooled in [("vw", 0, pooled_vw), ("ew", 1, pooled_ew)]:
                        sf = a[:, col][np.isfinite(a[:, col])]
                        out.append(dict(
                            coin=coin, metric=metric, horizon=hl, floor=FLOOR, K=K,
                            train=train_mode, eval=eval_, stratum=stratum,
                            pooled_S=None if not np.isfinite(pooled) else float(pooled),
                            mean_fold_S=float(sf.mean()) if sf.size else None,
                            std_fold_S=float(sf.std(ddof=1)) if sf.size > 1 else None,
                            n_folds=int(sf.size), folds_pos=int((sf > 0).sum()),
                            n_active_tot=int(a[:, 5].sum()),
                            perfold_S=[float(x) for x in a[:, col]]))
    return out


# ---- graduation rule (deterministic) + config-selection-corrected null ----
def _config_stat(perfold_by_coin):
    """mean - std over the pooled (coin,fold) S sample for a config."""
    vals = np.concatenate([v for v in perfold_by_coin if len(v)]) if perfold_by_coin else np.array([])
    vals = vals[np.isfinite(vals)]
    if vals.size < 2:
        return -np.inf
    return float(vals.mean() - vals.std(ddof=1))


def graduation(grid_df, target):
    """Deterministic winner: max over primary-family, non-censored, K<=50 configs of mean-std, for
    eval==target. Config key = (metric,horizon,K,train). Returns (key, stat)."""
    d = grid_df.filter((pl.col("eval") == target) & (pl.col("stratum") == "primary_family") &
                       (pl.col("K") <= K_GRAD_MAX))
    best = None
    for (metric, horizon, K, train), g in d.group_by(["metric", "horizon", "K", "train"]):
        stat = _config_stat([np.array(x) for x in g["perfold_S"].to_list()])
        # deterministic tie-break: higher stat, lowest horizon, smallest K, then metric/train name
        key = (stat, -HORIZONS.index(horizon), -K, metric, train)
        if best is None or key > best[0]:               # full-key compare (replayable) [code-audit M1]
            best = (key, (metric, horizon, K, train), stat)
    return (best[1], best[2]) if best else (None, -np.inf)


def config_null(ctxs, tabs_by_coin, target, real_stat, R=R_GRAD, seed=SEED):
    """Config-selection-corrected null. The null must mirror graduation's FULL config space —
    INCLUDING the 7-metric axis [code-audit BLOCKER B1]. So we keep the REAL metric rankings (all 7
    rank as they truly do) and break the ranking->outcome link by permuting TEST identities per coin
    (te[pi[pick]]) — a label-shuffle. Max over the same (metric,horizon,K<=50,train) space; the max
    over 7 CORRELATED real rankings calibrates the metric selection. p = P(null winner >= real)."""
    rng = np.random.default_rng(seed + 999)
    col = 0 if target == "vw" else 1
    grad_hs = [(hi, hl) for hi, hl in enumerate(HORIZONS) if hl not in CENSOR]
    grad_Ks = [k for k in KS if k <= K_GRAD_MAX]
    # precompute real picks per config (mirrors `graduation` exactly, metric axis included)
    cache = {}
    for train_mode in TRAINS:
        for hi, hl in grad_hs:
            for metric in METRICS:
                for K in grad_Ks:
                    per_coin = []
                    for c in ctxs:
                        tab_h = tabs_by_coin[c["coin"]][train_mode][hi]
                        if not tab_h or np.mean([s["scorable"] for s in tab_h.values()]) < SCORABLE_MIN:
                            continue
                        folds = []
                        for t, s in tab_h.items():
                            order = base.rank_desc(s["metrics"][metric], c["codes"], np.isin(c["codes"], s["elig"]))
                            if order.size >= K:
                                folds.append((t, order[:K]))
                        if folds:
                            per_coin.append((c["coin"], train_mode, hi, folds))
                    if per_coin:
                        cache[(metric, hi, K, train_mode)] = per_coin
    ge = 0
    for r in range(R):
        pis = {c["coin"]: rng.permutation(c["W"]) for c in ctxs}
        best = -np.inf
        for per_coin in cache.values():
            vals = []
            for (coin, train_mode, hi, folds) in per_coin:
                pi = pis[coin]; tabh = tabs_by_coin[coin][train_mode][hi]
                for (t, pick) in folds:
                    s = tabh[t]; pp = pi[pick]                 # permuted test identities
                    if col == 0:
                        den = s["te_notl"][pp].sum()
                        vals.append(s["te_mkusd"][pp].sum() / den * 1e4 if den > 0 else np.nan)
                    else:
                        cn = s["te_cnt"][pp]; act = cn > 0; nact = int(act.sum())
                        perw = np.where(act, s["te_sumw"][pp] / np.maximum(cn, 1), 0.0)
                        vals.append(perw[act].sum() / nact * 1e4 if nact > 0 else np.nan)
            v = np.array(vals); v = v[np.isfinite(v)]
            stat = (v.mean() - v.std(ddof=1)) if v.size > 1 else -np.inf
            if stat > best:
                best = stat
        if best >= real_stat:
            ge += 1
    return (1 + ge) / (1 + R)


def main(smoke=False):
    lk = _load_bars()
    coins = ["BTC", "ETH"] if smoke else MAJORS
    ctxs = []; tabs_by_coin = {}; grid = []
    for coin in coins:
        if lk.get(coin) is None:
            continue
        ctx = sw.build_coin_all(coin, lk[coin])
        if ctx is None:
            continue
        assert (ctx["notl"] > 0).all(), "notl>0 invariant (ew/vw active-set symmetry) [code-audit M3]"
        tabs = {tm: refine_tables(ctx, FLOOR, tm) for tm in TRAINS}
        tabs_by_coin[coin] = tabs; ctxs.append(ctx)
        grid += grid_rows(ctx, tabs)
        print(f"{coin}: grid rows so far {len(grid)}", flush=True)
    gdf = pl.DataFrame(grid)
    gdf.write_parquet(OUT / "refine_grid.parquet")
    # graduation + corrected null, per target
    grad_rows = []
    for target in ["vw", "ew"]:
        key, stat = graduation(gdf, target)
        p = config_null(ctxs, tabs_by_coin, target, stat) if key else None
        grad_rows.append(dict(target=target, metric=key[0], horizon=key[1], K=key[2], train=key[3],
                              winner_stat=float(stat), config_selection_p=p,
                              note="mean-std fold lower-bound; p corrects the ~8k-cell selection"))
        print(f"GRADUATION[{target}]: {key} stat={stat:.1f} corrected_p={p}", flush=True)
    pl.DataFrame(grad_rows).write_parquet(OUT / "refine_graduation.parquet")
    print(f"DONE -> refine_grid ({gdf.height} rows) / refine_graduation in {OUT}", flush=True)


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
