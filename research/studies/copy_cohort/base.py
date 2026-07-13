"""One-time base table: markout ⋈ episodes for the non-inherited episode universe (majors).

Rationale: the markout lake is partitioned by coin only (no time pruning), so filtering it by a
per-fold window re-reads all ~33M rows every fold — 65 min/fold in the naive selector. This
materializes the join ONCE (per coin, memory-bounded), carrying every field the selector/arms/
follower-lag need, so each fold reads a local ~4M-row slice + a tiny μ join. Everything downstream
is a pure function of this base + a code commit.

markout is 1:1 with non-inherited episodes (markout.py excludes inherited_basis, keeps ALL opener
types incl. maker), so `markout ⋈ episodes(NOT inherited_basis)` on the collision-free key
(wallet, coin, opener_block, opener_event_index) IS the complete non-inherited episode set with both
markout and episode fields — exactly the population F1–F8 + both arms consume.

    python -m research.studies.copy_cohort.base all
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

from research.data.markout import (_connect, EP_GLOB, REPO_ROOT, COINS,
                                   MARKOUT_SCHEMA_VERSION)

MK_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes_markout" / "coin=*/part-b*.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "base"
BASE_SCHEMA_VERSION = "copy_cohort_base_v1_2026-07-12"
START_MS = 1754006400000                       # 2025-08-01T00:00Z

# markout horizons kept in the base (primary 4h + secondaries + follower-lag prices)
MK_COLS = ["raw_markout_1h", "raw_markout_2h", "raw_markout_4h", "raw_markout_8h",
           "ph_5m", "ph_4h"]
# episode fields the selector/arms/F-filters need
EP_COLS = ["close_ts", "initial_notional_usd", "total_added_notional_usd", "hold_minutes",
           "realized_pnl_usd", "opener_flagged", "is_liquidation_close", "crossed_open"]


def build_coin(con, coin: str) -> int:
    cdir = OUT_DIR / f"coin={coin}"
    cdir.mkdir(parents=True, exist_ok=True)
    out = cdir / "part.parquet"
    tmp = out.with_suffix(".parquet.tmp")
    mk_sel = ", ".join(f"mk.{c}" for c in MK_COLS)
    ep_sel = ", ".join(f"ep.{c}" for c in EP_COLS)
    con.execute(f"""COPY (
      WITH mk AS (
        SELECT wallet, coin, open_ts, entry_bar_ts, dir_sign, opener_block, opener_event_index,
               entry_lag_s, entry_after_close, {', '.join(MK_COLS)}
        FROM read_parquet('{MK_GLOB}', hive_partitioning=false)
        WHERE coin = '{coin}' AND open_ts >= {START_MS}
      ),
      ep AS (
        SELECT wallet, coin, opener_block, opener_event_index, {', '.join(EP_COLS)}
        FROM read_parquet('{EP_GLOB}', hive_partitioning=true)
        WHERE coin = '{coin}' AND NOT inherited_basis
      )
      SELECT mk.wallet, mk.coin, mk.open_ts, mk.entry_bar_ts, mk.dir_sign,
             mk.opener_block, mk.opener_event_index, mk.entry_lag_s, mk.entry_after_close,
             strftime(make_timestamp(mk.entry_bar_ts*1000), '%G%V') AS iso_week_entry,
             strftime(make_timestamp(mk.open_ts*1000), '%G%V')      AS iso_week_open,
             {mk_sel}, {ep_sel}
      FROM mk JOIN ep USING (wallet, coin, opener_block, opener_event_index)
      ORDER BY mk.wallet, mk.open_ts, mk.opener_block, mk.opener_event_index
    ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    os.replace(tmp, out)
    return con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]


def build_all() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = _connect()
    con.execute("PRAGMA threads=2")
    con.execute("PRAGMA memory_limit='6GB'")
    t0 = time.time()
    total = 0
    for c in COINS:
        tm = time.time()
        n = build_coin(con, c)
        total += n
        print(f"  base {c}: {n:,} episodes  {time.time()-tm:.0f}s", flush=True)
    (OUT_DIR / "_BASE_META.json").write_text(json.dumps({
        "base_schema_version": BASE_SCHEMA_VERSION,
        "source_markout_schema": MARKOUT_SCHEMA_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_rows": total}, indent=2))
    print(f"=== base done {time.time()-t0:.0f}s -> {OUT_DIR} ({total:,} rows) ===", flush=True)


if __name__ == "__main__":
    build_all()
