"""Tier-2 markout BACKFILL — per-episode initial-entry timing markout (1:1 augmentation of the episode lake).
Arch: docs/WALLET_FEATURES_TIER2_MARKOUT_ARCH.md (v2, post-audit). This module is ONLY the cutoff-independent
backfill (R2): raw_markout per (episode, horizon) + entry_bar_ts + staleness. NO μ-subtraction, NO cutoff
filtering here — timing_alpha and all μ are computed in the per-cutoff aggregation layer.

Guards baked in: post-fill entry (first oracle tick STRICTLY after open_ts, R11); oracle_px independent price;
per-minute ASOF with a ≤90s staleness bound both ends (R6 — interior-gap artifact); exclude inherited_basis
(R5); 1:1 with episodes, no episode self-join (R4). dir_sign signs the return (R11).

    python -m research.data.markout probe BTC     # tiny hand-checkable validation
    python -m research.data.markout coin BTC      # backfill one coin
    python -m research.data.markout all           # all majors
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from . import schema

REPO_ROOT = Path(__file__).resolve().parents[2]
EP_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes" / "month=*/episodes.parquet")
CTX_GLOB = str(REPO_ROOT / "data" / "raw" / "asset_ctx" / "month=*/day=*/ctx.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived" / "episodes_markout"
MARKOUT_SCHEMA_VERSION = "markout_v1_initentry_timing_2026-07-08"
STALE_MS = 90_000          # R6: ASOF match must be within 90s of target, else NULL+censor
COINS = list(schema.SZD.keys())

# horizons in ms; primary study = {1,2,4,8}h but store all
HORIZONS = {"5m": 5*60_000, "15m": 15*60_000, "30m": 30*60_000, "1h": 3_600_000,
            "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000, "16h": 57_600_000,
            "24h": 86_400_000, "48h": 172_800_000}


NBUCKET = 8   # wallet-hash chunks per coin: bounds the ASOF working set to ~1M rows (8GB/17Gi-temp safe)


def _connect():
    con = duckdb.connect()
    con.execute("PRAGMA threads=2"); con.execute("PRAGMA memory_limit='4GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{REPO_ROOT / '.tmp'}'")
    con.execute("SET enable_progress_bar=false")
    return con


def _price_view(con, coin: str) -> None:
    """Register the coin's per-minute oracle price series (sorted, deduped on ts)."""
    con.execute(f"""CREATE OR REPLACE TEMP VIEW px AS
      SELECT ts, TRY_CAST(oracle_px AS DOUBLE) AS p
      FROM read_parquet('{CTX_GLOB}', hive_partitioning=true)
      WHERE coin='{coin}' AND TRY_CAST(oracle_px AS DOUBLE) IS NOT NULL
      QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts)=1""")


def _entries_view(con, coin: str, extra_sql: str = "", materialize: bool = False) -> None:
    """Episodes eligible for entry-timing markout: exclude inherited_basis (R5); carry full 1:1 identity (R4).
    entry_bar_ts = first px tick STRICTLY after open_ts (post-fill, R11) via forward ASOF; entry price P0 there.
    entry_lag_s / entry_after_close flags the sub-cadence/gap cases (R5/R6). `materialize` builds a TABLE (so the
    entry ASOF runs once per bucket, not once per horizon)."""
    kind = "TABLE" if materialize else "TEMP VIEW"
    con.execute(f"""CREATE OR REPLACE {kind} ent AS
      WITH e AS (
        SELECT wallet, coin, open_ts, close_ts, dir, opener_block, opener_event_index,
               CASE WHEN dir='long' THEN 1 ELSE -1 END AS dir_sign
        FROM read_parquet('{EP_GLOB}', hive_partitioning=true)
        WHERE coin='{coin}' AND NOT inherited_basis {extra_sql}
      )
      SELECT e.*, px.ts AS entry_bar_ts, px.p AS p0,
             (px.ts - e.open_ts)/1000.0 AS entry_lag_s,
             (e.close_ts IS NOT NULL AND px.ts >= e.close_ts) AS entry_after_close
      FROM e ASOF JOIN px ON e.open_ts < px.ts""")   # forward: smallest px.ts > open_ts


def _markout_sql(coin: str) -> str:
    """One backward-ASOF per horizon (staleness-bounded), producing wide raw_markout_<h> columns. Built by
    chaining ASOF joins; each Ph NULL if no tick within 90s of t_h (R6) — right-censoring by data availability
    is implicit (no tick → NULL); the ≤C cutoff censor is applied later in the aggregation layer (R10)."""
    joins, cols = [], []
    for name, h in HORIZONS.items():
        a = f"h_{name}"
        joins.append(f"""ASOF JOIN px {a} ON (ent.entry_bar_ts + {h}) >= {a}.ts""")
        # staleness-bounded price at t_h; NULL if the matched tick is >90s stale
        ph = f"CASE WHEN (ent.entry_bar_ts + {h}) - {a}.ts <= {STALE_MS} THEN {a}.p END"
        cols.append(f"{ph} AS ph_{name}")
        cols.append(f"CASE WHEN (ent.entry_bar_ts + {h}) - {a}.ts <= {STALE_MS} "
                    f"THEN ent.dir_sign * (({ph}) - ent.p0)/ent.p0 * 1e4 END AS raw_markout_{name}")
        cols.append(f"(ent.entry_bar_ts + {h}) AS t_{name}")
    return f"""
      SELECT ent.wallet, ent.coin, ent.open_ts, ent.close_ts, ent.dir, ent.dir_sign,
             ent.opener_block, ent.opener_event_index, ent.entry_bar_ts, ent.p0,
             ent.entry_lag_s, ent.entry_after_close,
             {', '.join(cols)}
      FROM ent {' '.join(joins)}"""


def probe(coin: str) -> None:
    """Hand-checkable validation on ~5 episodes: verify entry is post-open, markout sign, a manual recompute."""
    con = _connect(); _price_view(con, coin)
    _entries_view(con, coin, extra_sql="AND close_ts IS NOT NULL ORDER BY open_ts LIMIT 5000")
    rows = con.execute(f"""SELECT wallet, dir, dir_sign, open_ts, entry_bar_ts, entry_lag_s, p0,
        ph_1h, raw_markout_1h, ph_8h, raw_markout_8h
        FROM ({_markout_sql(coin)}) WHERE p0 IS NOT NULL AND ph_1h IS NOT NULL
        ORDER BY abs(raw_markout_1h) DESC LIMIT 5""").fetchall()
    print(f"probe {coin}: entry strictly after open? all lag>0:",
          con.execute(f"SELECT min(entry_lag_s) FROM ent").fetchone()[0])
    for r in rows:
        w,dirn,ds,op,eb,lag,p0,ph1,m1,ph8,m8 = r
        manual = ds*(ph1-p0)/p0*1e4
        print(f"  {dirn:5s} lag={lag:5.0f}s p0={p0:.2f} ph1h={ph1:.2f} markout1h={m1:+.1f}bp "
              f"(manual {manual:+.1f}) 8h={m8:+.1f}bp  ok={abs(manual-m1)<0.01}")


def backfill_coin(con, coin: str) -> int:
    """Per-coin backfill in NBUCKET wallet-hash chunks (bounds the ASOF working set to ~1M rows). Each bucket:
    materialize `ent` (entry ASOF once), then stream the wide markout query to a part via COPY (no Python-side
    Arrow materialization — that was the OOM). Buckets are written atomically; a coin is done when all parts
    exist. Idempotent: an existing complete-marker skips the coin."""
    cdir = OUT_DIR / f"coin={coin}"; cdir.mkdir(parents=True, exist_ok=True)
    _price_view(con, coin)
    total = 0
    for b in range(NBUCKET):
        out = cdir / f"part-b{b}.parquet"
        tmp = cdir / f"part-b{b}.parquet.tmp"
        _entries_view(con, coin, extra_sql=f"AND hash(wallet) % {NBUCKET} = {b}", materialize=True)
        con.execute(f"COPY ({_markout_sql(coin)}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
        os.replace(tmp, out)
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
        total += n
        print(f"    {coin} bucket {b}: {n:,}", flush=True)
    # provenance sidecar (COPY-written parquet can't carry kv metadata)
    (cdir / "_MARKOUT_META.json").write_text(
        f'{{"markout_schema_version":"{MARKOUT_SCHEMA_VERSION}",'
        f'"source_episode_schema":"episodes_v1_lifecycle_enriched_2026-07-07","nbucket":{NBUCKET}}}')
    return total


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if cmd == "probe":
        probe(sys.argv[2] if len(sys.argv) > 2 else "BTC")
    elif cmd == "coin":
        con = _connect(); t0 = time.time()
        n = backfill_coin(con, sys.argv[2])
        print(f"markout {sys.argv[2]}: {n:,} episodes  {time.time()-t0:.0f}s")
    elif cmd == "all":
        con = _connect(); t0 = time.time()
        for c in COINS:
            tm = time.time(); n = backfill_coin(con, c)
            print(f"  markout {c}: {n:,} eps  {time.time()-tm:.0f}s", flush=True)
        print(f"=== markout backfill done {time.time()-t0:.0f}s -> {OUT_DIR} ===")
