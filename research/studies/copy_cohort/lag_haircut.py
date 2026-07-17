"""Lag-haircut markout — follower entry = first tape print at trader-fill + lag (CONSTRUCTION_PREREG addendum).

Grid: lags {0, 3s, 10s, 30s} x horizons {1h, 4h}, E1 alt flat-opens of the arm-T cohorts.
Follower px from droplet-pulled per-lag first prints (data/derived/copy_cohort/lag_haircut/);
endpoint = local asset_ctx mid at entry_ts + h (backward ASOF, <=90s staleness). Robust spec:
winsor p95 |mk| within cell, wallet-folds >=3, wallet-equal, 4000-rep wallet-cluster boot.
Slippage decomposition: dir-signed bp from trader fill px to each lag's print px.

    python -m research.studies.copy_cohort.lag_haircut
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from .alt_fresh_validate import _ctx_parts

DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "lag_haircut"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "lag_haircut_report.json"
LAGS = (0, 3000, 10000, 30000)
HORIZONS = (("1h", 3_600_000), ("4h", 14_400_000))
STALE_MS = 90_000
SEED = 20260716
N_BOOT = 4000
FOLDS = (202511, 202512, 202601, 202602, 202603, 202604, 202605, 202606)


def _endpoint_px(con, fold: int):
    """rowid -> {h: end_px} for this fold's entries via ASOF against local ctx."""
    ctx_list = ",".join(f"'{p}'" for p in _ctx_parts(fold))
    rows = {}
    for hname, hms in HORIZONS:
        d = con.execute(f"""
            WITH ent AS (SELECT rowid, coin, ts FROM read_parquet('{(DIR / 'entries.parquet').as_posix()}')
                         WHERE fold = {fold}),
            ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL)
            SELECT e.rowid, c.mid_px, ((e.ts + {hms}) - c.ts) AS lag_ms
            FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND (e.ts + {hms}) >= c.ts
        """).fetchall()
        rows[hname] = {r[0]: r[1] for r in d if r[1] is not None and r[2] is not None and r[2] <= STALE_MS}
    return rows


def _wallet_equal(mk, wf_key):
    uk, inv = np.unique(wf_key, return_inverse=True)
    wf = np.bincount(inv, weights=mk) / np.bincount(inv)
    wal = np.array([k.split("|")[0] for k in uk], dtype=object)
    return wf, wal


def _cell(mk, wallet, fold, rng):
    """Robust spec: winsor p95 |mk|, wf>=3, wallet-equal + wallet-cluster boot."""
    lim = np.percentile(np.abs(mk), 95)
    mkw = np.clip(mk, -lim, lim)
    key = np.array([f"{w}|{f}" for w, f in zip(wallet, fold)])
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    keep = cnt[inv] >= 3
    mkw, key, wallet = mkw[keep], key[keep], wallet[keep]
    wf, wal = _wallet_equal(mkw, key)
    uw = np.unique(wal)
    idx = {x: np.flatnonzero(wal == x) for x in uw}
    boots = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = np.concatenate([idx[x] for x in rng.choice(uw, uw.size, replace=True)])
        boots[b] = wf[pick].mean()
    return {"robust_bp": float(wf.mean()), "ci": [float(np.quantile(boots, .025)), float(np.quantile(boots, .975))],
            "p_gt0": float((boots > 0).mean()), "n": int(mk.size), "n_wf": int(np.unique(key).size),
            "raw_bp": float(mk.mean())}


def run():
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'; SET threads=4")
    ent = con.execute(f"SELECT rowid, fold, wallet, coin, ts, dir_sign, trader_px FROM "
                      f"read_parquet('{(DIR / 'entries.parquet').as_posix()}')").fetchnumpy()
    prints = con.execute(f"SELECT rowid, lag, print_px FROM "
                         f"read_parquet('{(DIR / 'fold=*.parquet').as_posix()}')").fetchnumpy()
    n_ent = ent["rowid"].size
    px_by_lag = {}
    for lag in LAGS:
        m = prints["lag"] == lag
        px_by_lag[lag] = dict(zip(prints["rowid"][m].tolist(), prints["print_px"][m].tolist()))
    end_px = {h: {} for h, _ in HORIZONS}
    for f in FOLDS:
        e = _endpoint_px(con, f)
        for h, _ in HORIZONS:
            end_px[h].update(e[h])
        print(f"  ctx endpoints fold {f} done", flush=True)

    rid = ent["rowid"]; wal = ent["wallet"].astype(str); fold = ent["fold"]
    dirs = np.asarray(ent["dir_sign"], float); tpx = np.asarray(ent["trader_px"], float)
    rep = {"config": {"lags_ms": LAGS, "horizons": [h for h, _ in HORIZONS], "n_entries": int(n_ent),
                      "robust_spec": "winsor p95, wf>=3, wallet-equal, 4000 boot", "seed": SEED},
           "slippage_bp": {}, "cells": {}}
    for lag in LAGS:
        fpx = np.array([px_by_lag[lag].get(int(r), np.nan) for r in rid])
        have = np.isfinite(fpx)
        slip = dirs[have] * (fpx[have] - tpx[have]) / tpx[have] * 1e4
        rep["slippage_bp"][str(lag)] = {"mean": float(slip.mean()), "median": float(np.median(slip)),
                                        "p90": float(np.percentile(slip, 90)),
                                        "drop_rate": float(1 - have.mean())}
        for h, _ in HORIZONS:
            epx = np.array([end_px[h].get(int(r), np.nan) for r in rid])
            ok = have & np.isfinite(epx)
            mk = dirs[ok] * (epx[ok] - fpx[ok]) / fpx[ok] * 1e4
            rng = np.random.default_rng(SEED + lag + (7 if h == "4h" else 0))
            rep["cells"][f"lag{lag//1000}s/{h}"] = _cell(mk, wal[ok], fold[ok], rng)
    OUT.write_text(json.dumps(rep, indent=1))
    print("\nslippage (dir-signed bp, trader fill -> first print at lag):")
    for lag in LAGS:
        s = rep["slippage_bp"][str(lag)]
        print(f"  {lag//1000:>2}s: mean {s['mean']:+6.1f}  median {s['median']:+6.1f}  p90 {s['p90']:+7.1f}  drop {s['drop_rate']:.1%}")
    print("\ncells (robust bp [CI] P>0 | n, wf, raw):")
    for k, c in rep["cells"].items():
        print(f"  {k:>9}: {c['robust_bp']:+7.1f} [{c['ci'][0]:+7.1f},{c['ci'][1]:+7.1f}] P>0={c['p_gt0']:.2f} "
              f"| n={c['n']:,} wf={c['n_wf']} (raw {c['raw_bp']:+.1f})")
    print(f"-> {OUT}")


if __name__ == "__main__":
    run()
