"""Copy-construction study — registered fixed grid per CONSTRUCTION_PREREG.md.

CANDIDATE-CONSTRUCTION-RANKING ONLY (burned folds 202511..202606, same reuse taint as
V2_BAKEOFF_PREREG). Fixed grid: horizons {1h,4h,8h,24h,48h} x entry sets
{E1 alt flat-opens, E2 +majors flat-opens, E3 +adds} on the frozen arm-T cohorts
(alt_universe_cohorts.json, 240 wallet-folds). Markout = gross dir-signed bp vs local
asset_ctx mid (backward ASOF, <=90s staleness both ends). Registered headline per cell:
winsor p95 |mk| within cell, wallet-folds >=3 entries, wallet-fold-equal mean;
wallet-cluster bootstrap 4000 reps, per-cell rng default_rng(20260716 + 1000*set + horizon).

Adds (E3) are pulled per fold month from lake perp_fills (cohort wallets only, projected
cols) and cached under data/derived/copy_cohort/construction/adds/.

    python -m research.studies.copy_cohort.construction_study
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from research.data.markout import REPO_ROOT
from . import lake
from .alt_fresh_validate import _ctx_parts

COHORTS = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_universe_cohorts.json"
DECAY = REPO_ROOT / "data" / "derived" / "copy_cohort" / "decay_anatomy_report.json"
ADDS_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "construction" / "adds"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "construction_report.json"
PF = f"s3://{lake.BUCKET}/source=hyperliquid_reservoir/dataset=perp_fills"
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
HORIZONS = (("1h", 3_600_000), ("4h", 14_400_000), ("8h", 28_800_000),
            ("24h", 86_400_000), ("48h", 172_800_000))
SETS = ("E1", "E2", "E3")
STALE_MS = 90_000
SEED = 20260716
N_BOOT = 4000


def _pull_adds(con, fold: int, wallets: list[str]) -> Path:
    """Cached per-fold perp_fills pull: cohort wallets' crossed Open* adds (start_position!=0)."""
    part = ADDS_DIR / f"fold={fold}" / "part.parquet"
    if part.exists():
        return part
    part.parent.mkdir(parents=True, exist_ok=True)
    wl = ",".join(f"'{w}'" for w in sorted(wallets))
    glob = f"{PF}/date={lake.month_dates(fold)}/*.parquet"
    tmp = str(part) + ".tmp"
    print(f"[construction] fold {fold}: pulling adds from lake perp_fills ...", flush=True)
    con.execute(f"""COPY (
        SELECT wallet, coin, ts,
               CASE WHEN direction = 'Open Long' THEN 1 ELSE -1 END AS dir_sign
        FROM read_parquet('{glob}')
        WHERE wallet IN ({wl}) AND crossed
          AND direction IN ('Open Long', 'Open Short') AND start_position <> 0
    ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
    Path(tmp).replace(part)
    return part


def _fold_entries(con, fold: int, wallets: list[str]):
    """All-set entries of the fold with the 5-horizon markout columns (numpy dict)."""
    ctx = _ctx_parts(fold)
    if not ctx:
        raise RuntimeError(f"no asset_ctx for fold {fold}")
    adds = _pull_adds(con, fold, wallets)
    lo, hi = con.execute(f"SELECT min(ts), max(ts) FROM read_parquet('{adds.as_posix()}')").fetchone()
    if lo is not None and not (1.4e12 < lo <= hi < 2.1e12):
        raise RuntimeError(f"fold {fold}: adds ts not epoch-ms: [{lo}, {hi}]")

    majors = ",".join(f"'{m}'" for m in MAJORS)
    con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets)])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ent AS
        SELECT o.wallet, o.coin, o.ts, o.dir_sign,
               o.coin IN ({majors}) AS is_major, FALSE AS is_add
        FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
        UNION ALL
        SELECT a.wallet, a.coin, a.ts, a.dir_sign,
               a.coin IN ({majors}) AS is_major, TRUE AS is_add
        FROM read_parquet('{adds.as_posix()}') a""")
    ctx_list = ",".join(f"'{p}'" for p in ctx)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ctx AS
        SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL""")

    ctes = ["p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS ts0 "
            "FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts)"]
    sel, prev = [], "p0"
    for i, (h, ms) in enumerate(HORIZONS):
        cur = f"h{i}"
        ctes.append(f"{cur} AS (SELECT {prev}.*, c.mid_px AS px_{h}, c.ts AS tse_{h} "
                    f"FROM {prev} ASOF LEFT JOIN ctx c "
                    f"ON {prev}.coin = c.coin AND ({prev}.ts + {ms}) >= c.ts)")
        sel.append(f"CASE WHEN px0 IS NOT NULL AND px0 > 0 AND (ts - ts0) <= {STALE_MS} "
                   f"AND px_{h} IS NOT NULL AND ((ts + {ms}) - tse_{h}) <= {STALE_MS} "
                   f"THEN dir_sign * (px_{h} - px0) / px0 * 1e4 END AS mk_{h}")
        prev = cur
    return con.execute(
        "WITH " + ",\n".join(ctes)
        + f" SELECT wallet, is_major, is_add, {', '.join(sel)} FROM {prev}").fetchnumpy()


def _np(a, dtype=float):
    a = np.ma.filled(a, np.nan) if np.ma.isMaskedArray(a) else a
    return np.asarray(a, dtype)


def _cell(mk, wallet, fold, rng):
    """One (entry-set, horizon) cell: coverage + raw + registered robust spec + wallet boot."""
    fin = np.isfinite(mk)
    mk, wallet, fold = mk[fin], wallet[fin], fold[fin]
    out = {"n_entries": int(mk.size), "n_wf": 0, "robust": None}
    if mk.size == 0:
        return out
    fold_s = fold.astype("U6")
    key = np.char.add(np.char.add(wallet, "|"), fold_s)
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    wf_wal = np.array([k.split("|")[0] for k in uk])
    wf_fld = np.array([k.split("|")[1] for k in uk])
    out["n_wf"] = int(uk.size)
    out["coverage_per_fold"] = {f: int((wf_fld == f).sum()) for f in sorted(set(fold_s))}
    out["raw_point_bp"] = float((np.bincount(inv, weights=mk) / cnt).mean())

    # registered robust spec: winsor p95 |mk| within cell, wallet-folds >= 3 entries
    lim = float(np.percentile(np.abs(mk), 95))
    mkw = np.clip(mk, -lim, lim)
    kept = cnt >= 3
    if not kept.any():
        return out
    wf_mean = (np.bincount(inv, weights=mkw) / cnt)[kept]
    kw, kf = wf_wal[kept], wf_fld[kept]
    per_fold = {f: {"n_wf": int((kf == f).sum()), "mean_bp": float(wf_mean[kf == f].mean())}
                for f in sorted(set(kf))}
    # wallet-cluster bootstrap (whole-wallet resampling leaves wf means intact -> boot on wf means)
    uwal = np.unique(kw)
    groups = [wf_mean[kw == x] for x in uwal]
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.integers(0, len(groups), len(groups))
        stats[b] = float(np.mean(np.concatenate([groups[i] for i in pick])))
    out["robust"] = {"point_bp": float(wf_mean.mean()),
                     "n_robust_entries": int(cnt[kept].sum()),
                     "n_wf_robust": int(kept.sum()), "n_wallets": int(uwal.size),
                     "winsor_lim_bp": lim,
                     "boot": {"ci": [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))],
                              "p_gt0": float((stats > 0).mean())},
                     "per_fold": per_fold,
                     "folds_pos": int(sum(v["mean_bp"] > 0 for v in per_fold.values()))}
    return out


def run():
    cohorts = json.loads(COHORTS.read_text())
    con = lake.connect()
    cols = {k: [] for k in ("wallet", "fold", "is_major", "is_add")}
    mks = {h: [] for h, _ in HORIZONS}
    for fold_s in sorted(cohorts["folds"]):
        fold = int(fold_s)
        members = cohorts["folds"][fold_s]["arms"]["T"]["members"]
        print(f"[construction] fold {fold}: entries + markouts ...", flush=True)
        d = _fold_entries(con, fold, sorted(members))
        n = d["wallet"].size
        cols["wallet"].append(d["wallet"].astype(str))
        cols["fold"].append(np.full(n, fold))
        cols["is_major"].append(_np(d["is_major"], bool))
        cols["is_add"].append(_np(d["is_add"], bool))
        for h, _ in HORIZONS:
            mks[h].append(_np(d[f"mk_{h}"]))
    wallet = np.concatenate(cols["wallet"])
    fold = np.concatenate(cols["fold"])
    is_major = np.concatenate(cols["is_major"])
    is_add = np.concatenate(cols["is_add"])
    mk = {h: np.concatenate(v) for h, v in mks.items()}

    set_mask = {"E1": ~is_add & ~is_major, "E2": ~is_add, "E3": np.ones(wallet.size, bool)}
    cells = {s: {} for s in SETS}
    for si, s in enumerate(SETS):
        m = set_mask[s]
        for hi, (h, _) in enumerate(HORIZONS):
            rng = np.random.default_rng(SEED + 1000 * si + hi)
            cells[s][h] = _cell(mk[h][m], wallet[m], fold[m], rng)
            print(f"  {s}/{h}: done", flush=True)

    # registered sanity anchor: E1/8h raw wf-equal must reproduce decay_anatomy
    anchor = json.loads(DECAY.read_text())["key_numbers"]["cohort_copy_mk_wf_equal_mean_bp"]
    got = cells["E1"]["8h"].get("raw_point_bp")
    sanity = {"e1_8h_raw_point_bp": got, "decay_anatomy_anchor_bp": anchor,
              "pass": got is not None and abs(got - anchor) <= 0.1}

    rep = {"label": "CANDIDATE-CONSTRUCTION-RANKING — burned folds 202511-202606; "
                    "descriptive 15-cell surface, no significance claims (CONSTRUCTION_PREREG.md)",
           "config": {"arm": "T", "n_wallet_folds": 240, "folds": sorted(cohorts["folds"]),
                      "horizons_ms": dict(HORIZONS), "sets": {
                          "E1": "alt flat taker opens (open_entries, coin NOT IN majors)",
                          "E2": "E1 + majors flat taker opens (open_entries, all coins)",
                          "E3": "E2 + adds (perp_fills: crossed Open* with start_position != 0, all coins)"},
                      "markout": "gross dir-signed bp vs asset_ctx mid, backward ASOF, <=90s both ends",
                      "robust_spec": "winsor p95 |mk| within cell, wf>=3, wallet-fold-equal",
                      "n_boot": N_BOOT, "seed": SEED,
                      "rng": "default_rng(SEED + 1000*set_index + horizon_index)"},
           "sanity": sanity,
           "coverage_wf_of_240": {s: {h: cells[s][h]["n_wf"] for h, _ in HORIZONS} for s in SETS},
           "cells": cells}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1, default=str))

    print(f"\nsanity E1/8h raw={got} vs anchor={anchor} pass={sanity['pass']}")
    print("\ncoverage (wallet-folds of 240 with >=1 evaluable entry):")
    for s in SETS:
        print(f"  {s}: " + " ".join(f"{h}={cells[s][h]['n_wf']}" for h, _ in HORIZONS))
    print("\ncell table: robust bp [CI] P(>0) | n_entries n_wf_robust folds+ (raw)")
    for s in SETS:
        for h, _ in HORIZONS:
            c = cells[s][h]
            r = c.get("robust")
            if r:
                print(f"  {s:>2}/{h:>3}: {r['point_bp']:+7.1f} [{r['boot']['ci'][0]:+6.1f},"
                      f"{r['boot']['ci'][1]:+6.1f}] P>{0}={r['boot']['p_gt0']:.2f} | "
                      f"n={c['n_entries']:>7,} wf={r['n_wf_robust']:>3} folds+={r['folds_pos']}/8 "
                      f"(raw {c.get('raw_point_bp', float('nan')):+.1f})")
            else:
                print(f"  {s:>2}/{h:>3}: n={c['n_entries']} (no robust wf)")
    print(f"-> {OUT}")
    if not sanity["pass"]:
        raise RuntimeError("SANITY FAIL: E1/8h raw does not reproduce decay_anatomy anchor")
    return rep


if __name__ == "__main__":
    run()
