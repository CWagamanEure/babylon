"""
Distributional analysis (PERSISTENCE_REFINE_ARCHITECTURE.md v2 §5) — is the vw_edge 24h lean a
central shift or a fat-tail artifact?

For the train-selected top-K vw_edge cohort (expanding), per (coin, horizon), pool the cohort's
TRAIN vs TEST markout entries (SINGLE frozen cap on BOTH windows) and compare location (mean, median)
+ shape (std, skew, p5/p95, tail-loss fraction, win rate), against the field and a random-cohort
reference band. DESCRIPTIVE — size-blind, no significance; a persistent median is NOT deployable
edge. Turnover-weighted (vw) test location reported beside the median. >=72h flagged censoring.

Output: refine_dist.parquet
"""
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import H_LABELS, H_MS, MAJORS, apply_winsor, _load_bars, T0
import oos_persistence as base
import persistence_sweep as sw
import persistence_refine as rf

OUT = Path(__file__).resolve().parents[1] / "out"
HORIZONS = list(H_LABELS)
KS_DIST = [10, 50]
CENSOR = sw.CENSOR_HORIZONS
LOSS_THRESH = 0.01           # tail-loss = fraction of markouts below -100 bp
N_RAND = 300                 # random-cohort reference draws (pooled across folds, [S1 fix])


def _skew(r):
    m = r.mean(); s = r.std()
    return float(np.mean(((r - m) / s) ** 3)) if s > 0 else 0.0


def _stats(r, prefix):
    r = r[np.isfinite(r)]
    if r.size < 20:
        return {f"{prefix}_{k}": None for k in ["n", "mean", "median", "std", "skew", "p5", "p95", "tailloss", "win"]}
    return {f"{prefix}_n": int(r.size), f"{prefix}_mean": float(r.mean() * 1e4),
            f"{prefix}_median": float(np.median(r) * 1e4), f"{prefix}_std": float(r.std() * 1e4),
            f"{prefix}_skew": _skew(r), f"{prefix}_p5": float(np.percentile(r, 5) * 1e4),
            f"{prefix}_p95": float(np.percentile(r, 95) * 1e4),
            f"{prefix}_tailloss": float((r < -LOSS_THRESH).mean()), f"{prefix}_win": float((r > 0).mean())}


def dist_rows(ctx, rng):
    coin, codes, inv = ctx["coin"], ctx["codes"], ctx["inv"]
    b_ts, bucket, notl = ctx["b_ts"], ctx["bucket"], ctx["notl"]
    tab = rf.refine_tables(ctx, rf.FLOOR, "expanding")
    rows = []
    for hi, hl in enumerate(HORIZONS):
        tab_h = tab[hi]
        if not tab_h:
            continue
        cap = ctx["cap_full"][hi]; col = ctx["ret_raw"][:, hi]; fin = np.isfinite(col)
        w = apply_winsor(col, cap)                                  # single frozen cap, BOTH windows
        pexit = base.priced_close_ms(b_ts + int(H_MS[hi]))
        stratum = "censoring" if hl in CENSOR else "primary"
        for K in KS_DIST:
            tr_all, te_all, te_notl_all, fold_pools = [], [], [], []
            for t, s in tab_h.items():
                order = base.rank_desc(s["metrics"]["vw_edge"], codes, np.isin(codes, s["elig"]))
                if order.size < K:
                    continue
                test_start = T0 + t * rf.BUCKET_MS
                trm = fin & (b_ts < test_start) & (pexit <= test_start)
                tem = fin & (bucket == t)
                cmask = np.isin(inv, order[:K])
                tr_all.append(w[cmask & trm]); te_all.append(w[cmask & tem]); te_notl_all.append(notl[cmask & tem])
                fold_pools.append((s["elig"], inv[tem], w[tem], notl[tem]))   # [S1 fix] cache for pooled draws
            if not te_all or not np.concatenate(te_all).size:
                continue
            # random-cohort band [S1 fix]: each draw picks a random K PER FOLD then POOLS across folds —
            # matching the real statistic's cross-fold pooling (the per-fold band was ~3.5x too wide).
            # Two nulls: unweighted median (for te_median) AND turnover-weighted mean (for the deployable vw_te).
            rand_medians, rand_vw = [], []
            for _ in range(N_RAND):
                sub = [(w_te[m], n_te[m]) for (el, inv_te, w_te, n_te) in fold_pools
                       for m in [np.isin(inv_te, rng.choice(el, size=min(K, el.size), replace=False))]]
                rr = np.concatenate([a for a, _ in sub]); nn = np.concatenate([b for _, b in sub])
                ok = np.isfinite(rr)
                if ok.sum() >= 20:
                    rand_medians.append(float(np.median(rr[ok]) * 1e4))
                    if nn[ok].sum() > 0:
                        rand_vw.append(float((rr[ok] * nn[ok]).sum() / nn[ok].sum() * 1e4))
            tr = np.concatenate(tr_all); te = np.concatenate(te_all); ten = np.concatenate(te_notl_all)
            fld = w[fin & (bucket >= base.FIRST_TEST)]
            vw_te = float((te[np.isfinite(te)] * ten[np.isfinite(te)]).sum() / ten[np.isfinite(te)].sum() * 1e4) \
                if np.isfinite(te).any() and ten[np.isfinite(te)].sum() > 0 else None
            rm = np.array(rand_medians); rv = np.array(rand_vw)
            te_fin = te[np.isfinite(te)]
            te_med_bps = float(np.median(te_fin) * 1e4) if te_fin.size else None
            med_hi = float(np.percentile(rm, 95)) if rm.size else None
            vw_hi = float(np.percentile(rv, 95)) if rv.size else None
            row = dict(coin=coin, horizon=hl, K=K, stratum=stratum, vw_te_median_bps=vw_te,
                       rand_med_lo=float(np.percentile(rm, 5)) if rm.size else None, rand_med_hi=med_hi,
                       rand_vw_lo=float(np.percentile(rv, 5)) if rv.size else None, rand_vw_hi=vw_hi,
                       # one-sided: does the real cohort exceed the fair pooled p95 null? (unweighted / deployable)
                       te_med_gt_band=bool(te_med_bps is not None and med_hi is not None and te_med_bps > med_hi),
                       vw_te_gt_band=bool(vw_te is not None and vw_hi is not None and vw_te > vw_hi))
            row.update(_stats(tr, "tr")); row.update(_stats(te, "te")); row.update(_stats(fld, "field"))
            rows.append(row)
    return rows


def main(smoke=False):
    lk = _load_bars()
    coins = ["BTC"] if smoke else MAJORS
    rng = np.random.default_rng(rf.SEED + 55)
    rows = []
    for coin in coins:
        if lk.get(coin) is None:
            continue
        ctx = sw.build_coin_all(coin, lk[coin])
        if ctx is None:
            continue
        rows += dist_rows(ctx, rng)
        print(f"{coin}: dist rows {len(rows)}", flush=True)
    pl.DataFrame(rows).write_parquet(OUT / "refine_dist.parquet")
    print(f"DONE -> refine_dist ({len(rows)}) in {OUT}", flush=True)


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
