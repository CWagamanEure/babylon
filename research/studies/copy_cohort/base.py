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

from research.data.markout import (_connect, _git_commit, EP_GLOB, REPO_ROOT,
                                   COINS, MARKOUT_SCHEMA_VERSION, CLOSE_SCHEMA_VERSION)

MK_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes_markout" / "coin=*/part-b*.parquet")
MK_CLOSE_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes_markout_close" / "coin=*/part-b*.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "base"
# v2 (2026-07-14): +raw_markout_24h/48h; +own-exit sidecar cols (CAPDAY_BOOK_ARCH §7, audit A5/A10/A14).
BASE_SCHEMA_VERSION = "copy_cohort_base_v2_ownexit_2026-07-14"
START_MS = 1754006400000                       # 2025-08-01T00:00Z

# markout horizons kept in the base (primary 4h/8h + secondaries + follower-lag prices + long horizons)
MK_COLS = ["raw_markout_1h", "raw_markout_2h", "raw_markout_4h", "raw_markout_8h",
           "raw_markout_24h", "raw_markout_48h", "ph_5m", "ph_4h"]
# NOTE: own-exit sidecar columns are NOT baked into base — the book joins the sidecar for its small
# cohort∪random wallet subset (audit A13: keeps close-time cols out of the selection/sizing base; also
# avoids a 3-table 14M-row ORDER-BY spill on a near-full disk). Sidecar glob is MK_CLOSE_GLOB above.
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
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    # A10 per-coin done-marker (version + commit) so an interrupted rebuild can't leave a mixed-schema lake.
    (cdir / "_DONE.json").write_text(json.dumps({
        "base_schema_version": BASE_SCHEMA_VERSION, "source_markout_schema": MARKOUT_SCHEMA_VERSION,
        "code_commit": _git_commit(), "n_rows": n}))
    return n


def open_base(con) -> str:
    """A5: the ONE sanctioned entry to the base parquet. Asserts the on-disk provenance matches the code
    (schema versions + code_commit + per-coin done-markers) before any query — no silent stale-cache reads.
    Returns the glob to read. Every base consumer should route through this."""
    meta_path = OUT_DIR / "_BASE_META.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"base not built (no {meta_path}) — run `base all`")
    meta = json.loads(meta_path.read_text())
    if meta.get("base_schema_version") != BASE_SCHEMA_VERSION:
        raise RuntimeError(f"stale base: on-disk {meta.get('base_schema_version')} != code "
                           f"{BASE_SCHEMA_VERSION} — rebuild with `base all`")
    if meta.get("source_markout_schema") != MARKOUT_SCHEMA_VERSION:
        raise RuntimeError("stale base: source markout schema mismatch — rebuild with `base all`")
    for c in COINS:
        dm = OUT_DIR / f"coin={c}" / "_DONE.json"
        if not dm.exists() or json.loads(dm.read_text()).get("base_schema_version") != BASE_SCHEMA_VERSION:
            raise RuntimeError(f"base coin={c} missing/stale done-marker — rebuild with `base all`")
    return str(OUT_DIR / "coin=*/part.parquet")


def open_close_sidecar() -> str:
    """Guarded entry to the own-exit sidecar: assert every coin's `_MARKOUT_CLOSE_META.json` matches the
    code's CLOSE_SCHEMA_VERSION before use (audit firewall-F2 — the raw glob had no provenance check).
    Returns MK_CLOSE_GLOB."""
    from research.data.markout import CLOSE_OUT_DIR
    for c in COINS:
        mp = CLOSE_OUT_DIR / f"coin={c}" / "_MARKOUT_CLOSE_META.json"
        if not mp.exists():
            raise FileNotFoundError(f"own-exit sidecar not built for {c} — run `markout close_all`")
        if json.loads(mp.read_text()).get("markout_close_schema_version") != CLOSE_SCHEMA_VERSION:
            raise RuntimeError(f"stale own-exit sidecar coin={c} — rebuild with `markout close_all`")
    return MK_CLOSE_GLOB


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
        "code_commit": _git_commit(),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_rows": total}, indent=2))
    print(f"=== base done {time.time()-t0:.0f}s -> {OUT_DIR} ({total:,} rows) ===", flush=True)


if __name__ == "__main__":
    build_all()
