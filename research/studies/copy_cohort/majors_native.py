"""MAJORS-NATIVE SELECTION x HORIZON — registered candidate-ranking grid
(CONSTRUCTION_PREREG.md §MAJORS-NATIVE SELECTION × HORIZON). Burned folds 202511-202606.

Selection per fold: MAJORS-only capped daily PnL t-stat from lake wallet_coin_day
(coins BTC/ETH/SOL/HYPE; day_pnl = Σ(pnl−fee), cap min(1, 100k/day_notional), nd>=15,
sd>0), frozen-133 excluded, top-K by t (K in {30,100}, nested prefixes, wallet-asc ties).
Entries: test-month MAJORS flat taker opens (lake open_entries), notl >= $250.
Markout: {1h,4h,8h,24h,48h} gross dir-signed vs local asset_ctx mid (backward ASOF <=90s
both ends). Robust spec: winsor p95 within cell, wf>=3, wallet-fold-equal; wallet-cluster
boot 4000, per-cell rng default_rng(20260716 + 1000*k_idx + horizon_idx).

    python -m research.studies.copy_cohort.majors_native
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from .alt_fresh_validate import _ctx_parts, _np, MAJORS, STALE_MS
from .ksweep import _top100 as _blind_top100

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
FROZEN = DERIVED / "frozen_alt_universe.json"
COHORTS = DERIVED / "alt_universe_cohorts.json"
CACHE = DERIVED / "majors_native"
OUT = DERIVED / "majors_native_report.json"

FOLDS = MONTHS[3:]                       # 202511..202606 (burned)
KS = (30, 100)
HOURS = (1, 4, 8, 24, 48)
CAP = 100_000.0
ND_MIN = 15
NOTL_MIN = 250.0
N_BOOT = 4000
SEED = 20260716
CAL_DAYS = 242


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


def _select_top100(con, fold: int, frozen: set[str]) -> list[str]:
    """MAJORS-only capped-daily-PnL t-stat top-100 (frozen-133 pre-excluded)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    selp = CACHE / f"sel_{fold}.parquet"
    if not selp.exists():
        globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in _formation_months(fold))
        majors = ",".join(f"'{m}'" for m in MAJORS)
        con.execute(f"""COPY (
            WITH wd AS (
              SELECT wallet, day,
                     SUM(CAST(pnl AS DOUBLE)) - SUM(CAST(fee AS DOUBLE)) AS day_pnl,
                     SUM(CAST(notional AS DOUBLE))                       AS day_notional
              FROM read_parquet([{globs}])
              WHERE coin IN ({majors})
              GROUP BY wallet, day
            ),
            capd AS (
              SELECT wallet,
                     day_pnl * LEAST(1.0, {CAP} / GREATEST(day_notional, 1e-12)) AS cap_pnl
              FROM wd
            )
            SELECT wallet, count(*) AS nd, avg(cap_pnl) AS mu, stddev_samp(cap_pnl) AS sd,
                   avg(cap_pnl) / (stddev_samp(cap_pnl) / sqrt(count(*))) AS t_stat
            FROM capd GROUP BY wallet
            HAVING count(*) >= {ND_MIN} AND stddev_samp(cap_pnl) > 0
        ) TO '{selp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: selection pool cached", flush=True)
    lc = duckdb.connect()
    d = lc.execute(f"SELECT wallet, t_stat FROM read_parquet('{selp.as_posix()}') "
                   "WHERE t_stat IS NOT NULL").fetchnumpy()
    lc.close()
    w = d["wallet"].astype(str)
    t = np.asarray(d["t_stat"], float)
    keep = np.array([x not in frozen for x in w])
    w, t = w[keep], t[keep]
    order = np.lexsort((w, -t))          # t desc, wallet asc tie-break (deterministic)
    return w[order[:100]].tolist()


def _fold_entries(con, fold: int, wallets: list[str]):
    """Cache test-month MAJORS flat taker opens of top-100 with all 5 horizon markouts."""
    entp = CACHE / f"entries_{fold}.parquet"
    if not entp.exists():
        ctx_list = ",".join(f"'{p}'" for p in _ctx_parts(fold))
        majors = ",".join(f"'{m}'" for m in MAJORS)
        con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT UNNEST(?) AS wallet, "
                    "UNNEST(?) AS rk", [wallets, list(range(len(wallets)))])
        joins, cols = [], []
        prev = "p0"
        for h in HOURS:
            ms = h * 3_600_000
            joins.append(
                f"p{h} AS (SELECT {prev}.*, c.mid_px AS px{h}, c.ts AS px{h}_ts "
                f"FROM {prev} ASOF LEFT JOIN ctx c ON {prev}.coin = c.coin "
                f"AND ({prev}.ts + {ms}) >= c.ts)")
            cols.append(
                f"CASE WHEN px0 IS NOT NULL AND px{h} IS NOT NULL AND px0 > 0 "
                f"AND (ts - px0_ts) <= {STALE_MS} AND ((ts + {ms}) - px{h}_ts) <= {STALE_MS} "
                f"THEN dir_sign * (px{h} - px0) / px0 * 1e4 END AS mk{h}")
            prev = f"p{h}"
        con.execute(f"""COPY (
            WITH ent AS (
              SELECT o.wallet, cw.rk, o.coin, o.ts, o.dir_sign, CAST(o.notl AS DOUBLE) AS notl
              FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
              WHERE o.coin IN ({majors}) AND CAST(o.notl AS DOUBLE) >= {NOTL_MIN}
            ),
            ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL),
            p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS px0_ts
                   FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts),
            {",".join(joins)}
            SELECT wallet, rk, coin, ts, notl, {",".join(cols)}
            FROM {prev}
        ) TO '{entp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: entries cached", flush=True)
    lc = duckdb.connect()
    d = lc.execute(f"SELECT * FROM read_parquet('{entp.as_posix()}')").fetchnumpy()
    lc.close()
    return d


def _cell_inference(mk, wallet, fold, rng):
    """Registered robust spec on one cell (identical to ksweep._cell_inference)."""
    n_eval = int(mk.size)
    out = {"n_entries": n_eval, "n_wallets_covered": int(np.unique(wallet).size) if n_eval else 0}
    if n_eval == 0:
        return out
    wf_key = np.char.add(np.char.add(wallet, "|"), fold.astype(str))
    out["n_wf_covered"] = int(np.unique(wf_key).size)
    uk, inv = np.unique(wf_key, return_inverse=True)
    out["raw_point_bp"] = float((np.bincount(inv, weights=mk) / np.bincount(inv)).mean())
    lim = float(np.percentile(np.abs(mk), 95))
    mk_w = np.clip(mk, -lim, lim)
    cnt = np.bincount(inv)
    keep = cnt[inv] >= 3
    if not keep.any():
        out["robust"] = None
        return out
    uk2, inv2 = np.unique(wf_key[keep], return_inverse=True)
    wf_mean = np.bincount(inv2, weights=mk_w[keep]) / np.bincount(inv2)
    wf_wal = np.array([k.split("|")[0] for k in uk2])
    wf_fold = np.array([int(k.split("|")[1]) for k in uk2])
    out["n_robust_entries"] = int(keep.sum())
    out["n_robust_wf"] = int(uk2.size)
    out["robust_point_bp"] = float(wf_mean.mean())
    uw, winv = np.unique(wf_wal, return_inverse=True)
    s = np.bincount(winv, weights=wf_mean)
    c = np.bincount(winv).astype(float)
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        m = np.bincount(rng.integers(0, uw.size, uw.size), minlength=uw.size)
        stats[b] = (m @ s) / (m @ c)
    stats = stats[np.isfinite(stats)]
    out["ci"] = [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))]
    out["p_gt0"] = float((stats > 0).mean())
    pf = {}
    for f in FOLDS:
        m = wf_fold == f
        pf[str(f)] = (float(wf_mean[m].mean()) if m.any() else None)
    out["per_fold_mean_bp"] = pf
    signs = [v for v in pf.values() if v is not None]
    out["per_fold_signs"] = f"{sum(1 for v in signs if v > 0)}/{len(signs)} folds > 0"
    out["entries_per_day"] = round(n_eval / CAL_DAYS, 2)
    return out


def run():
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    cohorts = json.loads(COHORTS.read_text())
    con = lake.connect()

    rows = {k: [] for k in ("wallet", "fold", "rk")} | {f"mk{h}": [] for h in HOURS}
    overlap = {}
    for f in FOLDS:
        top = _select_top100(con, f, frozen)
        # registered overlap descriptives
        armT = set(cohorts["folds"][str(f)]["arms"]["T"]["members"])
        blind = set(_blind_top100(f, frozen))
        overlap[str(f)] = {
            "top30_x_armT30": len(set(top[:30]) & armT),
            "top100_x_armT30": len(set(top) & armT),
            "top100_x_blind_top100": len(set(top) & blind),
        }
        d = _fold_entries(con, f, top)
        n = d["wallet"].size
        rows["wallet"].append(d["wallet"].astype(str))
        rows["fold"].append(np.full(n, f))
        rows["rk"].append(_np(d["rk"], int))
        for h in HOURS:
            rows[f"mk{h}"].append(_np(d[f"mk{h}"]))   # masked->NaN guard (audit 2026-07-17)
        print(f"  fold {f}: {n:,} majors entries pulled; overlap {overlap[str(f)]}", flush=True)
    e = {k: np.concatenate(v) for k, v in rows.items()}

    rep = {"config": {"prereg": "CONSTRUCTION_PREREG.md §MAJORS-NATIVE SELECTION × HORIZON",
                      "stamp": "CANDIDATE-RANKING, burned folds 202511-202606",
                      "selection": "MAJORS-only capped daily PnL t-stat, nd>=15, sd>0, "
                                   "frozen-133 excluded, top-K nested by t desc/wallet asc",
                      "majors": list(MAJORS), "ks": list(KS),
                      "horizons_h": list(HOURS), "notl_min": NOTL_MIN, "cap": CAP,
                      "basis": "asset_ctx mid (gross); ~1-1.6bp follower lag haircut per "
                               "lag_haircut_report.json + taker fees before any net read",
                      "robust_spec": "winsor p95 in cell, wf>=3, wallet-fold-equal",
                      "n_boot": N_BOOT, "seed": SEED, "cal_days": CAL_DAYS,
                      "code_commit": lake.git_describe(),
                      "audit_2026_07_17": "masked->NaN markout guard (weighted cluster boot "
                                          "here was already multiplicity-correct)"},
           "overlap_per_fold": overlap, "cells": {}}

    for ki, K in enumerate(KS):
        in_k = e["rk"] < K
        for hi, h in enumerate(HOURS):
            mk = e[f"mk{h}"]
            m = in_k & np.isfinite(mk)
            rng = np.random.default_rng(SEED + 1000 * ki + hi)
            cell = _cell_inference(mk[m], e["wallet"][m], e["fold"][m], rng)
            cell["n_selected_wf"] = 8 * K
            rep["cells"][f"K{K}/{h}h"] = cell
            b = cell.get("robust_point_bp")
            ci = cell.get("ci", [None, None])
            if b is not None:
                print(f"K={K:>3} h={h:>2}h n={cell['n_entries']:>6,} "
                      f"wal={cell.get('n_wallets_covered', 0):>3} robust={b:+.1f}bp "
                      f"CI[{ci[0]:+.1f},{ci[1]:+.1f}] P(>0)={cell.get('p_gt0', float('nan')):.3f} "
                      f"{cell.get('per_fold_signs', '')} e/d={cell.get('entries_per_day')}",
                      flush=True)
            else:
                print(f"K={K:>3} h={h:>2}h n={cell['n_entries']} (no robust wf)", flush=True)

    # overlap summary
    rep["overlap_summary"] = {
        k: float(np.mean([overlap[str(f)][k] for f in FOLDS]))
        for k in ("top30_x_armT30", "top100_x_armT30", "top100_x_blind_top100")}
    print("overlap (mean/fold):", rep["overlap_summary"], flush=True)

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
