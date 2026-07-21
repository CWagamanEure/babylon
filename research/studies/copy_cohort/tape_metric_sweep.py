"""METRIC SWEEP — walk-forward monotonicity atlas of 29 wallet-ranking features (majors tape).

Per fold (202511-202606): compute each feature over the 3-month formation window for ALL eligible
wallets (nd>=15), bucket into quintiles, and measure the NEXT month's copy performance per bucket
(flat-open taker entries >=$250, 8h markout, net 2.6bp): wallet-fold-equal mean bp, equal-$1k book
Sharpe/Sortino. A feature "works" if bucket performance is monotone (Spearman across buckets,
top-bottom delta, per-fold sign agreement).

STAMP: EXPLORATORY / DESCRIPTIVE on burned folds, at the user's direction (2026-07-21) — a screening
atlas to rank hypotheses, not an evidence layer. Nothing here is a registered result.

Caches (month grain, resumable): wcd_<m>.parquet (wallet-coin-day), ent_<m>.parquet (all-wallet
entries with 8-horizon markouts + close-gap). Report: tape_metric_sweep_report.json.

    python -m research.studies.copy_cohort.tape_metric_sweep
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from research.data import schema
from .tape_capday_filter import (CACHE, CAP, DERIVED, FOLDS, MAJORS, ND_MIN, RT_COST_BP,
                                 _connect, _ctx_parts, _entries_sql, _formation_months, _git,
                                 _month_start_ms, _np)
from research.lib.cv import as_of_cutoff_ms

OUT = DERIVED / "tape_metric_sweep_report.json"
MONTHS_ALL = tuple(sorted({m for f in FOLDS for m in _formation_months(f)} | set(FOLDS)))
HOR_MS = {"5m": 300_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
          "4h": 14_400_000, "8h": 28_800_000, "12h": 43_200_000, "24h": 86_400_000}
NOTL_MIN_FWD = 250.0
N_BUCKETS = 5
MIN_ENTRIES_FEAT = 5          # wallet needs >=5 formation entries for entry-grain features
SWEEP_V = "v1"                # cache version for this module's caches


def _wcd_cache(con, month: int):
    p = CACHE / f"sweep_wcd_{month}_{SWEEP_V}.parquet"
    if p.exists():
        return p
    t0, t1 = _month_start_ms(month), as_of_cutoff_ms(month)
    majors = ",".join(f"'{m}'" for m in MAJORS)
    tmp = p.with_suffix(".tmp.parquet")
    con.execute(f"""COPY (
      SELECT wallet, coin, day,
             SUM(TRY_CAST(closed_pnl AS DOUBLE)) - SUM(TRY_CAST(fee AS DOUBLE)) AS pnl_net,
             SUM(TRY_CAST(px AS DOUBLE) * abs(TRY_CAST(sz AS DOUBLE))) AS notl,
             COUNT(*) AS n_fills,
             SUM(CASE WHEN crossed THEN 1 ELSE 0 END) AS n_taker
      FROM f
      WHERE month = {month} AND coin IN ({majors}) AND ts >= {t0} AND ts < {t1}
        AND NOT ({schema.VAULT_SQL})
      GROUP BY 1, 2, 3
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    tmp.rename(p)
    print(f"  wcd {month} cached", flush=True)
    return p


def _ent_cache(con, month: int):
    """All-wallet flat-open entries with 8-horizon markouts + close-gap proxy."""
    p = CACHE / f"sweep_ent_{month}_{SWEEP_V}.parquet"
    if p.exists():
        return p
    parts = _ctx_parts(month)
    assert parts, f"no ctx for {month}"
    t0, t1 = _month_start_ms(month), as_of_cutoff_ms(month)
    ctx_list = ",".join(f"'{x}'" for x in parts)
    joins, cols = [], []
    prev = "p0"
    for name, ms in HOR_MS.items():
        joins.append(f"p_{name} AS (SELECT {prev}.*, c.mid_px AS px_{name}, c.ts AS pts_{name} "
                     f"FROM {prev} ASOF LEFT JOIN ctx c ON {prev}.ts + {ms} >= c.ts)")
        cols.append(f"CASE WHEN px0 IS NOT NULL AND px_{name} IS NOT NULL AND px0 > 0 "
                    f"AND (ts - px0_ts) <= 90000 AND ((ts + {ms}) - pts_{name}) <= 90000 "
                    f"THEN dir_sign * (px_{name} - px0) / px0 * 1e4 END AS mk_{name}")
        prev = f"p_{name}"
    # per-coin passes: quarters ASOF sort memory (8GB box, ~1GB free disk — no spill headroom)
    coin_tmps = []
    for coin in MAJORS:
        ct = p.with_suffix(f".{coin}.tmp.parquet")
        coin_tmps.append(ct)
        if ct.exists():
            continue
        con.execute(f"""COPY (
          WITH ent0 AS ({_entries_sql([month], t0, t1)}),
          ent1 AS (SELECT * FROM ent0 WHERE coin = '{coin}'),
          closes AS (
            SELECT wallet, ts AS cts FROM f
            WHERE month = {month} AND coin = '{coin}' AND ts >= {t0} AND ts < {t1}
              AND dir IN ('Close Long', 'Close Short')
          ),
          entc AS (
            SELECT e.*, c.cts
            FROM ent1 e ASOF LEFT JOIN closes c ON e.wallet = c.wallet AND c.cts > e.ts
          ),
          ctx AS (SELECT ts, mid_px FROM read_parquet([{ctx_list}])
                  WHERE coin = '{coin}' AND mid_px IS NOT NULL AND mid_px > 0),
          p0 AS (SELECT entc.*, c.mid_px AS px0, c.ts AS px0_ts
                 FROM entc ASOF LEFT JOIN ctx c ON entc.ts >= c.ts),
          {",".join(joins)}
          SELECT wallet, coin, ts, dir_sign, notional,
                 (cts - ts) / 60000.0 AS close_gap_min, {",".join(cols)}
          FROM {prev}
        ) TO '{ct.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"    entries {month} {coin} done", flush=True)
    tmp = p.with_suffix(".tmp.parquet")
    files = ",".join(f"'{c.as_posix()}'" for c in coin_tmps)
    con.execute(f"COPY (SELECT * FROM read_parquet([{files}])) TO '{tmp.as_posix()}' "
                f"(FORMAT PARQUET, COMPRESSION zstd)")
    tmp.rename(p)
    for c in coin_tmps:
        c.unlink()
    print(f"  entries {month} cached", flush=True)
    return p


MK_COLS = ",".join(f"avg(mk_{h}) AS f_mk_{h}" for h in HOR_MS)


def _fold_features(con, fold: int):
    """Wallet-grain feature table for one fold (formation window), all in SQL."""
    p = CACHE / f"sweep_feat_{fold}_{SWEEP_V}.parquet"
    if p.exists():
        return p
    fm = _formation_months(fold)
    wcd = ",".join(f"'{(_wcd_cache(con, m)).as_posix()}'" for m in fm)
    ents = ",".join(f"'{(_ent_cache(con, m)).as_posix()}'" for m in fm)
    tmp = p.with_suffix(".tmp.parquet")
    con.execute(f"""COPY (
      WITH wcd AS (SELECT * FROM read_parquet([{wcd}])),
      wd AS (
        SELECT wallet, day, SUM(pnl_net) AS pnl, SUM(notl) AS notl,
               SUM(n_fills) AS n_fills, SUM(n_taker) AS n_taker
        FROM wcd GROUP BY 1, 2
      ),
      wda AS (SELECT * FROM wd WHERE notl > 0),
      capd AS (SELECT *, pnl * LEAST(1.0, {CAP} / notl) AS cap_pnl,
                      (day // 100) AS ym FROM wda),
      mrank AS (                             -- monthly percentile rank of capped pnl
        SELECT wallet, ym, percent_rank() OVER (PARTITION BY ym ORDER BY SUM(cap_pnl)) AS pr
        FROM capd GROUP BY wallet, ym
      ),
      f_day AS (
        SELECT wallet,
          COUNT(*) AS f_active_days,
          AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS f_pct_prof_days,
          AVG(pnl) AS f_mean_daily_pnl,
          median(pnl) AS f_median_daily_pnl,
          median(pnl) / NULLIF(mad(pnl), 0) AS f_consistency,
          quantile_cont(pnl, 0.10) AS f_worst_decile_pnl,
          SUM(n_fills) * 1.0 / COUNT(*) AS f_trades_per_day,
          1.0 - SUM(n_taker) * 1.0 / NULLIF(SUM(n_fills), 0) AS f_maker_share,
          SUM(notl) / COUNT(*) AS f_turnover,
          SUM(pnl) / NULLIF(SUM(notl), 0) * 1e4 AS f_pnl_per_dollar_bp,
          corr(pnl, lag_pnl) AS f_ret_autocorr
        FROM (SELECT *, LAG(pnl) OVER (PARTITION BY wallet ORDER BY day) AS lag_pnl FROM wda)
        GROUP BY wallet
      ),
      f_month AS (
        SELECT wallet,
          AVG(CASE WHEN mpnl > 0 THEN 1.0 ELSE 0.0 END) AS f_frac_months_prof
        FROM (SELECT wallet, (day // 100) AS ym, SUM(pnl) AS mpnl FROM wda GROUP BY 1, 2)
        GROUP BY wallet
      ),
      f_cap AS (
        SELECT wallet, COUNT(*) AS nd,
          SUM(cap_pnl) / COUNT(*) AS metric_cap,
          SUM(pnl) / COUNT(*) AS metric_uncap,
          SUM(cap_pnl) / NULLIF(SUM(pnl), 0) AS f_cap_sensitivity,
          SUM(pnl) - MAX(pnl) AS f_leave_best_day_pnl
        FROM capd GROUP BY wallet
      ),
      f_dd AS (
        SELECT wallet, MAX(peak - cum) AS f_max_dd_usd
        FROM (SELECT wallet, cum, MAX(cum) OVER (PARTITION BY wallet ORDER BY day) AS peak
              FROM (SELECT wallet, day,
                           SUM(SUM(pnl)) OVER (PARTITION BY wallet ORDER BY day) AS cum
                    FROM wda GROUP BY wallet, day))
        GROUP BY wallet
      ),
      f_coin AS (
        SELECT wallet,
          SUM(cn * cn) / NULLIF(SUM(cn) * SUM(cn), 0) AS f_coin_hhi,
          MAX(abs(cpnl)) / NULLIF(SUM(abs(cpnl)), 0) AS f_top_coin_pnl_share,
          SUM(cpnl) - arg_max(cpnl, cpnl) AS f_leave_best_coin_pnl
        FROM (SELECT wallet, coin, SUM(notl) AS cn, SUM(pnl_net) AS cpnl
              FROM wcd GROUP BY 1, 2)
        GROUP BY wallet
      ),
      f_rank AS (
        SELECT wallet, -stddev_samp(pr) AS f_rank_stability, COUNT(*) AS n_rank_months
        FROM mrank GROUP BY wallet
      ),
      ent AS (SELECT * FROM read_parquet([{ents}])),
      cons AS (
        SELECT coin, dir_sign, (ts // 3600000) AS hr, COUNT(DISTINCT wallet) AS nw
        FROM ent GROUP BY 1, 2, 3
      ),
      f_ent AS (
        SELECT e.wallet,
          COUNT(*) AS n_form_entries,
          median(e.notional) AS f_med_entry_notl,
          quantile_cont(e.notional, 0.9) / NULLIF(median(e.notional), 0) AS f_clip_lumpiness,
          median(e.close_gap_min) AS f_hold_proxy_min,
          {MK_COLS},
          AVG(CASE WHEN e.dir_sign > 0 THEN mk_8h END)
            - AVG(CASE WHEN e.dir_sign < 0 THEN mk_8h END) AS f_ls_gap_8h,
          AVG(c.nw - 1) AS f_entry_consensus,
          AVG(CASE WHEN c.nw = 1 THEN 1.0 ELSE 0.0 END) AS f_uniqueness
        FROM ent e JOIN cons c
          ON e.coin = c.coin AND e.dir_sign = c.dir_sign AND (e.ts // 3600000) = c.hr
        GROUP BY e.wallet
      )
      SELECT f_cap.wallet, f_cap.nd, f_cap.metric_cap,
             f_day.* EXCLUDE (wallet), f_month.* EXCLUDE (wallet),
             f_cap.f_cap_sensitivity, f_cap.f_leave_best_day_pnl,
             f_dd.f_max_dd_usd, f_coin.* EXCLUDE (wallet),
             f_rank.f_rank_stability, f_ent.* EXCLUDE (wallet)
      FROM f_cap
      LEFT JOIN f_day USING (wallet) LEFT JOIN f_month USING (wallet)
      LEFT JOIN f_dd USING (wallet) LEFT JOIN f_coin USING (wallet)
      LEFT JOIN f_rank USING (wallet) LEFT JOIN f_ent USING (wallet)
      WHERE f_cap.nd >= {ND_MIN}
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    tmp.rename(p)
    print(f"  fold {fold}: feature table cached", flush=True)
    return p


# feature registry: name -> (column, higher_is_better_hypothesis, note)
FEATURES = {
    "pct_prof_days": "f_pct_prof_days", "mean_daily_pnl": "f_mean_daily_pnl",
    "median_daily_pnl": "f_median_daily_pnl", "consistency_med_mad": "f_consistency",
    "worst_decile_pnl": "f_worst_decile_pnl", "max_dd_usd_NEG": "f_max_dd_usd",
    "coin_hhi": "f_coin_hhi", "top_coin_pnl_share": "f_top_coin_pnl_share",
    "active_days": "f_active_days", "trades_per_day": "f_trades_per_day",
    "med_entry_notl": "f_med_entry_notl", "clip_lumpiness": "f_clip_lumpiness",
    "hold_proxy_min": "f_hold_proxy_min", "maker_share": "f_maker_share",
    "turnover": "f_turnover", "pnl_per_dollar_bp": "f_pnl_per_dollar_bp",
    **{f"markout_{h}": f"f_mk_{h}" for h in HOR_MS},
    "markout_persistence": None,       # derived below
    "peak_markout_horizon": None, "post_peak_decay": None,
    "ls_gap_8h": "f_ls_gap_8h", "entry_consensus": "f_entry_consensus",
    "uniqueness": "f_uniqueness", "ret_autocorr": "f_ret_autocorr",
    "rank_stability": "f_rank_stability", "frac_months_prof": "f_frac_months_prof",
    "leave_best_day_pnl": "f_leave_best_day_pnl", "leave_best_coin_pnl": "f_leave_best_coin_pnl",
    "cap_sensitivity": "f_cap_sensitivity", "capday_metric_REF": "metric_cap",
}


def _derived_features(d):
    mks = np.column_stack([_np(d[f"f_mk_{h}"]) for h in HOR_MS])
    early = np.nanmean(mks[:, :2], axis=1)          # 5m/30m
    late = np.nanmean(mks[:, 4:6], axis=1)          # 4h/8h
    with np.errstate(invalid="ignore"):
        pers = late - early
        peak_idx = np.where(np.all(np.isnan(mks), axis=1), np.nan,
                            np.nanargmax(np.where(np.isnan(mks), -np.inf, mks), axis=1))
        peak_val = np.nanmax(np.where(np.isnan(mks), -np.inf, mks), axis=1)
        decay = (peak_val - mks[:, -1]) / np.abs(peak_val)
        decay[~np.isfinite(decay)] = np.nan
    return {"markout_persistence": pers, "peak_markout_horizon": peak_idx,
            "post_peak_decay": -decay}              # less decay = better hypothesis


def _fwd_book(ent, wallets_mask_idx):
    """Forward stats for a set of wallet indices: wallet-equal mk8, equal-$ Sharpe/Sortino."""
    m = wallets_mask_idx
    if not m.any():
        return None
    mk, wal, ts = ent["mk8"][m], ent["wallet"][m], ent["ts"][m]
    uw, inv = np.unique(wal, return_inverse=True)
    wmean = np.bincount(inv, weights=mk) / np.bincount(inv)
    net = mk - RT_COST_BP
    pnl = net / 1e4 * 1000.0
    ed = ((ts + HOR_MS["8h"]) // 86_400_000).astype(int)
    ud, dinv = np.unique(ed, return_inverse=True)
    daily = np.bincount(dinv, weights=pnl)
    span = int(ud.max() - ud.min() + 1)
    full = np.zeros(span)
    full[ud - ud.min()] = daily
    sd = full.std(ddof=1)
    dn = full[full < 0]
    dsd = np.sqrt((dn ** 2).sum() / max(full.size - 1, 1))
    return {"n_entries": int(m.sum()), "n_wallets": int(uw.size),
            "wallet_equal_bp": float(wmean.mean()), "net_bp": float(net.mean()),
            "sharpe": float(full.mean() / sd * np.sqrt(365)) if sd > 0 else None,
            "sortino": float(full.mean() / dsd * np.sqrt(365)) if dsd > 0 else None,
            "net_usd": float(pnl.sum())}


def run():
    con = _connect()
    # build caches
    for m in MONTHS_ALL:
        _wcd_cache(con, m)
        _ent_cache(con, m)
    featps = {f: _fold_features(con, f) for f in FOLDS}
    con.close()

    # load forward entries per fold (test month, >=$250, finite mk8) once
    fwd = {}
    for f in FOLDS:
        lc = duckdb.connect()
        d = lc.execute(f"""SELECT wallet, ts, mk_8h FROM
            read_parquet('{(CACHE / f"sweep_ent_{f}_{SWEEP_V}.parquet").as_posix()}')
            WHERE notional >= {NOTL_MIN_FWD} AND mk_8h IS NOT NULL""").fetchnumpy()
        lc.close()
        fwd[f] = {"wallet": d["wallet"].astype(str), "ts": _np(d["ts"]), "mk8": _np(d["mk_8h"])}
        print(f"fold {f}: {fwd[f]['mk8'].size:,} forward entries", flush=True)

    rep = {"config": {"stamp": "EXPLORATORY/DESCRIPTIVE burned folds (user-directed 2026-07-21); "
                               "screening atlas, not evidence",
                      "folds": list(FOLDS), "n_buckets": N_BUCKETS, "nd_min": ND_MIN,
                      "min_entries_feat": MIN_ENTRIES_FEAT, "fwd": "8h, >=$250, net 2.6bp",
                      "proxies": {"hold_proxy_min": "flat-open -> next Close fill gap",
                                  "leave_best_day": "day grain not trade grain",
                                  "max_dd_usd_NEG": "raw $ (scale-confounded, noted)"},
                      "code_commit": _git()},
           "features": {}}

    for feat, col in FEATURES.items():
        buckets = {b: {"mk8": [], "wal": [], "ts": [], "fold": []} for b in range(N_BUCKETS)}
        per_fold_delta = {}
        for f in FOLDS:
            lc = duckdb.connect()
            d = lc.execute(f"SELECT * FROM read_parquet('{featps[f].as_posix()}')").fetchnumpy()
            lc.close()
            w = d["wallet"].astype(str)
            if col is None:
                v = _derived_features(d)[feat]
            else:
                v = _np(d[col])
            if col in {"f_med_entry_notl", "f_clip_lumpiness", "f_hold_proxy_min",
                       "f_ls_gap_8h", "f_entry_consensus", "f_uniqueness"} or col is None \
                    or (col or "").startswith("f_mk_"):
                ne = _np(d.get("n_form_entries", np.zeros(w.size)))
                v = np.where(ne >= MIN_ENTRIES_FEAT, v, np.nan)
            ok = np.isfinite(v)
            if ok.sum() < 100:
                continue
            q = np.nanquantile(v[ok], np.linspace(0, 1, N_BUCKETS + 1)[1:-1])
            bidx = np.digitize(v, q)                 # 0..4, low->high
            wl, mk, ts = fwd[f]["wallet"], fwd[f]["mk8"], fwd[f]["ts"]
            w2b = dict(zip(w[ok], bidx[ok]))
            eb = np.array([w2b.get(x, -1) for x in wl])
            fold_bucket_mean = {}
            for b in range(N_BUCKETS):
                m = eb == b
                if m.any():
                    buckets[b]["mk8"].append(mk[m])
                    buckets[b]["wal"].append(wl[m])
                    buckets[b]["ts"].append(ts[m])
                    uw, inv = np.unique(wl[m], return_inverse=True)
                    fold_bucket_mean[b] = float((np.bincount(inv, weights=mk[m])
                                                 / np.bincount(inv)).mean())
            if 0 in fold_bucket_mean and (N_BUCKETS - 1) in fold_bucket_mean:
                per_fold_delta[str(f)] = round(
                    fold_bucket_mean[N_BUCKETS - 1] - fold_bucket_mean[0], 2)
        stats = {}
        for b in range(N_BUCKETS):
            if buckets[b]["mk8"]:
                ent = {k: np.concatenate(buckets[b][k]) for k in ("mk8", "wal", "ts")}
                ent["wallet"] = ent.pop("wal")
                stats[f"q{b + 1}"] = _fwd_book(ent, np.ones(ent["mk8"].size, bool))
        we = [stats.get(f"q{b + 1}", {}).get("wallet_equal_bp") for b in range(N_BUCKETS)]
        sh = [stats.get(f"q{b + 1}", {}).get("sharpe") for b in range(N_BUCKETS)]
        mono = None
        if all(x is not None for x in we):
            r = np.argsort(np.argsort(we)).astype(float)      # rank corr vs bucket order
            i = np.arange(N_BUCKETS, dtype=float)
            mono = float(np.corrcoef(i, r)[0, 1])
        deltas = list(per_fold_delta.values())
        rep["features"][feat] = {
            "bucket_wallet_equal_bp": [None if x is None else round(x, 2) for x in we],
            "bucket_sharpe": [None if x is None else round(x, 2) for x in sh],
            "spearman_monotonicity": mono,
            "q5_minus_q1_bp": round(float(np.mean(deltas)), 2) if deltas else None,
            "q5_minus_q1_folds_gt0": f"{sum(1 for x in deltas if x > 0)}/{len(deltas)}",
            "per_fold_delta": per_fold_delta,
            "buckets": stats,
        }
        print(f"{feat:>24}: q1..q5 we_bp="
              f"{['-' if x is None else round(x, 1) for x in we]} mono={mono} "
              f"d={rep['features'][feat]['q5_minus_q1_bp']} "
              f"{rep['features'][feat]['q5_minus_q1_folds_gt0']}", flush=True)

    ranked = sorted(((f, v) for f, v in rep["features"].items()
                     if v["spearman_monotonicity"] is not None),
                    key=lambda kv: -abs(kv[1]["spearman_monotonicity"]))
    rep["ranking_by_abs_monotonicity"] = [
        {"feature": f, "mono": v["spearman_monotonicity"], "delta": v["q5_minus_q1_bp"],
         "folds": v["q5_minus_q1_folds_gt0"]} for f, v in ranked]
    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
