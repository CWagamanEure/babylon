"""
OOS-persistence RELIABILITY SWEEP (PERSISTENCE_SWEEP_ARCHITECTURE.md v2).

Extends the audited base test (oos_persistence.py) with:
  - depth-aware ranking metrics: t-stat (=sqrt(n)*mean_w/std_eff, field-floored) and eb_edge
    (empirical-Bayes shrunk equal-weight edge, GLS mean, tau^2=0 -> skip);
  - ALL 12 horizons, per-horizon (rank-h == measure-h, no cross-horizon argmax);
  - raised activity-floor axis {30, 200};
  - GLOBAL permutation null (grid-wide "# cells beating own null") as the headline multiplicity
    control, BH-FDR secondary;
  - censoring-dominated horizons routed to a non-inferential stratum.

Reuses base machinery verbatim: priced_close_ms (purge), rank_desc, cohort_vw, joint_null, real_S,
_spearman, bh_fdr. Metrics change RANKING only; OOS outcome is still the active-only deployable vw
cohort edge + its joint null. Nothing reads test-window quantities into the ranking (leak-audited).

Outputs (out/):
  sweep_verdict.parquet   : per (coin, metric, horizon, floor) S, joint_p, stratum, degenerate
  sweep_global.parquet    : global permutation null — observed vs expected # cells beating null
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import (MAJORS, H_LABELS, H_MS, COST_BPS,
                      markout_ret, winsor_cap, apply_winsor, _load_bars, BAR_MS, T0)
import oos_persistence as base

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = sorted(glob(str(ROOT / "out/entries/part_*.parquet")))
OUT = ROOT / "out"

HORIZONS = list(H_LABELS)                          # all 12
BASE_METRICS = ["vw_edge", "avg_edge", "sharpe", "hit_rate", "cum_pnl"]
NEW_METRICS = ["tstat", "eb_edge"]
METRICS = BASE_METRICS + NEW_METRICS
FLOORS = [30, 200]
CENSOR_HORIZONS = {"72h", "168h"}                  # long-horizon censoring stratum
SCORABLE_MIN = 0.5                                 # cell scorable-fraction gate -> non-inferential
STD_FLOOR_K = 0.15                                 # t-stat denom floor (SORTINO_K precedent)
EPS = 1e-9
K = 50
R_PERM = 1000
R_GLOBAL = 1000
PRIMARY = ("vw_edge", "24h", 30)
LEAD_SECONDARY = ("eb_edge", "24h", 30)
SEED = 12345
BUCKET_MS = base.BUCKET_MS
FIRST_TEST = base.FIRST_TEST


def build_coin_all(coin, lk):
    """Like base.build_coin but keeps ALL 12 horizon columns."""
    df = (pl.scan_parquet(ENTRIES).filter(pl.col("coin") == coin)
          .select("wallet", "b_ts", "dir", "entry_px", "notl").collect())
    if df.height == 0:
        return None
    wallet = df["wallet"].to_numpy(); b_ts = df["b_ts"].to_numpy()
    d = df["dir"].to_numpy(); entry_px = df["entry_px"].to_numpy(); notl = df["notl"].to_numpy()
    uniq, inv = np.unique(wallet, return_inverse=True); inv = inv.astype(np.int64)
    ret_raw = markout_ret(lk, b_ts, d, entry_px)               # (n,12) raw, ONCE
    cap_full = [winsor_cap(ret_raw[:, j]) for j in range(len(HORIZONS))]
    bucket = ((b_ts - T0) // BUCKET_MS).astype(np.int64)
    return dict(coin=coin, uniq=uniq, inv=inv, W=uniq.size,
                codes=np.arange(uniq.size, dtype=np.int64),
                b_ts=b_ts, notl=notl, ret_raw=ret_raw, cap_full=cap_full,
                bucket=bucket, n_buckets=int(bucket.max()) + 1)


def wallet_agg_ext(inv, W, r_w, r_raw, notl):
    """base.wallet_agg + winsorized 2nd moment (sum_w2) + raw 2nd moment, for t-stat / eb."""
    cnt = np.bincount(inv, minlength=W)
    sum_notl = np.bincount(inv, weights=notl, minlength=W)
    sum_mkusd = np.bincount(inv, weights=r_w * notl, minlength=W)
    sum_w = np.bincount(inv, weights=r_w, minlength=W)
    sum_w2 = np.bincount(inv, weights=r_w * r_w, minlength=W)          # winsorized 2nd moment
    sum_r = np.bincount(inv, weights=r_raw, minlength=W)
    sum_r2 = np.bincount(inv, weights=r_raw * r_raw, minlength=W)
    hits = np.bincount(inv, weights=(r_raw > 0).astype(float), minlength=W)
    c = cnt.astype(np.float64); cpos = np.maximum(c, 1.0)
    mean_w = sum_w / cpos * 1e4                                        # winsor mean (bps)
    with np.errstate(invalid="ignore", divide="ignore"):
        vw = np.where(sum_notl > 0, sum_mkusd / np.where(sum_notl > 0, sum_notl, 1.0) * 1e4, np.nan)
        std_raw = np.sqrt(np.maximum(sum_r2 - sum_r ** 2 / cpos, 0.0) / np.maximum(c - 1, 1.0)) * 1e4
        sharpe = np.where((c > 0) & (std_raw > 0), mean_w / np.where(std_raw > 0, std_raw, 1.0), np.nan)
        hit = np.where(c > 0, hits / cpos, np.nan) * 1e4
        s_w2 = np.maximum(sum_w2 - sum_w ** 2 / cpos, 0.0) / np.maximum(c - 1, 1.0) * 1e8   # winsor var (bps^2)
    return dict(cnt=cnt, sum_notl=sum_notl, sum_mkusd=sum_mkusd, sum_w=sum_w,
                vw_edge=vw, avg_edge=mean_w, sharpe=sharpe, hit_rate=hit, cum_pnl=sum_mkusd,
                std_raw=std_raw, avg=mean_w, s_w2=s_w2)


def pool_metrics(agg, elig, field_std_bps):
    """Compute t-stat and eb_edge over the eligible pool. Returns (tstat[W], eb[W], degenerate:bool).
    All inputs are purged-train (no leak). eb shrinks the equal-weight avg (bps)."""
    W = agg["cnt"].size
    tstat = np.full(W, np.nan); eb = np.full(W, np.nan)
    n = agg["cnt"].astype(np.float64)
    # --- t-stat: sqrt(n) * mean_w / max(std_raw, K*field_std, EPS) ---
    std_eff = np.maximum.reduce([agg["std_raw"], np.full(W, STD_FLOOR_K * field_std_bps), np.full(W, EPS)])
    e = elig
    tstat[e] = np.sqrt(n[e]) * agg["avg"][e] / std_eff[e]
    # --- eb_edge over eligible pool ---
    avg = agg["avg"][e]                                   # bps
    ni = n[e]
    v = agg["s_w2"][e] / np.maximum(ni, 1.0)              # sampling var of the mean (bps^2)
    tau2 = max(float(np.var(avg, ddof=1)) - float(np.mean(v)), 0.0) if avg.size > 1 else 0.0
    degenerate = tau2 <= EPS
    if not degenerate:
        prec = 1.0 / (tau2 + v)                           # GLS weights
        mu = float((avg * prec).sum() / prec.sum())
        B = tau2 / (tau2 + v)
        eb[e] = mu + B * (avg - mu)
    return tstat, eb, degenerate


def sweep_tables(ctx, floor):
    """Per (horizon, split): purge, aggregate, eligibility at `floor`, all 7 metrics, test contribs.
    Returns tab[hi][t] compatible with base.real_S / base.joint_null, plus scorable & degenerate."""
    W, inv, notl, b_ts, bucket = ctx["W"], ctx["inv"], ctx["notl"], ctx["b_ts"], ctx["bucket"]
    tab = {}
    for hi, hl in enumerate(HORIZONS):
        h_ms = int(H_MS[hi]); cap_te = ctx["cap_full"][hi]
        pexit = base.priced_close_ms(b_ts + h_ms)
        col_raw = ctx["ret_raw"][:, hi]; fin = np.isfinite(col_raw)
        per_t = {}
        for t in range(FIRST_TEST, ctx["n_buckets"]):
            test_start = T0 + t * BUCKET_MS
            adm = fin & (b_ts < test_start) & (pexit <= test_start)      # PURGE (base §2)
            if not adm.any():
                continue
            cap_tr = winsor_cap(col_raw[adm])
            r_w_tr = apply_winsor(col_raw, cap_tr)
            tr = wallet_agg_ext(inv[adm], W, r_w_tr[adm], col_raw[adm], notl[adm])
            elig = np.nonzero(tr["cnt"] >= floor)[0]
            if elig.size < K:
                continue
            field_std_bps = float(np.std(col_raw[adm], ddof=1) * 1e4) if adm.sum() > 1 else EPS
            tstat, eb, degen = pool_metrics(tr, elig, field_std_bps)
            metrics = {m: tr[m] for m in BASE_METRICS}
            metrics["tstat"] = tstat; metrics["eb_edge"] = eb
            # TEST outcome (frozen full cap), + scorable fraction of test-window entries at this h
            tmask = fin & (bucket == t)
            r_w_te = apply_winsor(col_raw, cap_te)
            te = wallet_agg_ext(inv[tmask], W, r_w_te[tmask], col_raw[tmask], notl[tmask])
            n_test_window = int((bucket == t).sum())
            scorable = float(tmask.sum()) / n_test_window if n_test_window else 0.0
            per_t[t] = dict(elig=elig, metrics=metrics,
                            te_mkusd=te["sum_mkusd"], te_notl=te["sum_notl"],
                            te_cnt=te["cnt"], te_sumw=te["sum_w"],
                            scorable=scorable, degenerate=degen)
        tab[hi] = per_t
    return tab


def stratum_of(horizon, tab_h):
    """Censoring-dominated -> non-inferential stratum (kept OUT of the primary global-null family)."""
    if horizon in CENSOR_HORIZONS:
        return "censoring"
    if tab_h and np.mean([s["scorable"] for s in tab_h.values()]) < SCORABLE_MIN:
        return "censoring"
    return "primary_family"


def analyse_coin(ctx, floor):
    """Verdict rows for one coin at one floor; also returns per-(horizon) cached null + real-S-by-metric
    for the global null."""
    coin, codes, W = ctx["coin"], ctx["codes"], ctx["W"]
    tab = sweep_tables(ctx, floor)
    rows = []
    cache = {}   # hi -> dict(null=array, elig_splits=list, te per split) reused by global null
    for hi, hl in enumerate(HORIZONS):
        tab_h = tab[hi]
        if not tab_h:
            continue
        stratum = stratum_of(hl, tab_h)
        s_null = base.joint_null(tab_h, codes, W, seed=SEED + hi)
        s_null = s_null[np.isfinite(s_null)]
        cache[hi] = dict(null=s_null, splits=[(s["elig"], s["te_mkusd"], s["te_notl"]) for s in tab_h.values()],
                         stratum=stratum, degenerate=any(s["degenerate"] for s in tab_h.values()))
        for metric in METRICS:
            degen = (metric == "eb_edge") and any(s["degenerate"] for s in tab_h.values())
            S = np.nan if degen else base.real_S(tab_h, codes, metric)
            p = float((1 + (s_null >= S).sum()) / (1 + s_null.size)) if (np.isfinite(S) and s_null.size) else np.nan
            rows.append(dict(
                coin=coin, metric=metric, horizon=hl, floor=floor, stratum=stratum,
                degenerate=bool(degen), n_splits=len(tab_h),
                mean_scorable=float(np.mean([s["scorable"] for s in tab_h.values()])),
                S_bps=None if not np.isfinite(S) else float(S),
                null_p95_bps=float(np.percentile(s_null, 95)) if s_null.size else None,
                joint_p=None if np.isnan(p) else p,
                raw_sig=bool(np.isfinite(S) and S > 0 and (p is not None) and p < 0.05),
                is_primary=(metric, hl, floor) == PRIMARY,
                is_lead_secondary=(metric, hl, floor) == LEAD_SECONDARY))
    return rows, cache


def global_null(caches, R=R_GLOBAL, seed=SEED):
    """Grid-wide null of '# primary-family cells beating their own null' under ONE persistent random
    score per wallet per COIN, propagated through ALL (horizon, floor) cells of that coin
    simultaneously (captures the true cross-cell dependence: both floors AND the 7 metrics of a
    (coin,h,floor) share the single random ranking, so they clump). [code-audit MAJOR: score is now
    shared across floors, not redrawn per floor.]
    caches: list of (W, [cache_floor1, cache_floor2, ...]) — one entry per coin."""
    rng = np.random.default_rng(seed + 777)
    counts = np.zeros(R, dtype=np.int64)
    n_metrics = len(METRICS)
    for r in range(R):
        for (W, coin_caches) in caches:
            score = rng.random(W)                     # ONE score per coin, shared across floors
            for cache in coin_caches:
                for c in cache.values():
                    if c["stratum"] != "primary_family":
                        continue
                    num = den = 0.0
                    for elig, mk, no in c["splits"]:
                        order = elig[np.lexsort((elig, -score[elig]))]
                        pick = order[:K]
                        num += mk[pick].sum(); den += no[pick].sum()
                    S = (num / den * 1e4) if den > 0 else np.nan
                    nl = c["null"]
                    if np.isfinite(S) and nl.size and S > 0:
                        p = (1 + (nl >= S).sum()) / (1 + nl.size)
                        if p < 0.05:
                            counts[r] += n_metrics    # 7 metrics share this ranking -> clump
    return counts


def main(smoke=False):
    assert ENTRIES, "run build_entries.py first"
    lk = _load_bars()
    coins = ["BTC"] if smoke else MAJORS
    all_rows = []; gcaches = []
    for coin in coins:
        if lk.get(coin) is None:
            continue
        ctx = build_coin_all(coin, lk[coin])
        if ctx is None:
            continue
        coin_caches = []                              # share one random score across this coin's floors
        for floor in FLOORS:
            rows, cache = analyse_coin(ctx, floor)
            all_rows += rows
            coin_caches.append(cache)
            print(f"{coin} floor={floor}: {len(rows)} cells", flush=True)
        gcaches.append((ctx["W"], coin_caches))
    vdf = pl.DataFrame(all_rows)
    # observed # primary-family cells beating own null (raw_sig within primary_family)
    obs = int(vdf.filter((pl.col("stratum") == "primary_family") & pl.col("raw_sig"))["raw_sig"].sum())
    gcounts = global_null(gcaches)
    gp = float((1 + (gcounts >= obs).sum()) / (1 + gcounts.size))
    # BH-FDR (secondary) over primary-family non-degenerate cells with a p
    fam = vdf.filter((pl.col("stratum") == "primary_family") & pl.col("joint_p").is_not_null() & ~pl.col("degenerate"))
    if fam.height:
        rej = base.bh_fdr(fam["joint_p"].to_numpy())
        Sar = fam["S_bps"].fill_null(float("nan")).to_numpy()
        fdr_map = {(r["coin"], r["metric"], r["horizon"], r["floor"]): bool(x) and (s > 0)
                   for r, x, s in zip(fam.iter_rows(named=True), rej, Sar)}
    else:
        fdr_map = {}
    vdf = vdf.with_columns(pl.struct(["coin", "metric", "horizon", "floor"]).map_elements(
        lambda r: fdr_map.get((r["coin"], r["metric"], r["horizon"], r["floor"]), False),
        return_dtype=pl.Boolean).alias("persists_fdr"))
    gdf = pl.DataFrame([dict(observed_beats=obs, global_null_mean=float(gcounts.mean()),
                             global_null_p95=float(np.percentile(gcounts, 95)),
                             global_p=gp, n_primary_family_cells=fam.height,
                             note="observed vs grid-wide permutation null (# cells beating own null); "
                                  "dependence-respecting headline multiplicity control")])
    vdf.write_parquet(OUT / "sweep_verdict.parquet")
    gdf.write_parquet(OUT / "sweep_global.parquet")
    print(f"GLOBAL NULL: observed {obs} vs null mean {gcounts.mean():.1f} (p95 "
          f"{np.percentile(gcounts,95):.0f}), global p={gp:.3f}", flush=True)
    print(f"FDR survivors (primary family): {int(vdf['persists_fdr'].sum())}", flush=True)
    print(f"DONE -> sweep_verdict / sweep_global in {OUT}", flush=True)


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
