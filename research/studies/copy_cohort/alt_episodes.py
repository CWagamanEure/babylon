"""Alt opening-taker episodes + forward 8h markout for the frozen copy_cohort alt validation.

Consumes `data/raw/alt_fills/` (the wallet-filtered Reservoir per-fill lake) and the `asset_ctx` per-minute
price lattice. Produces one row per ALT opening-taker fill of a frozen wallet, with a dir-signed 8h markout —
the SAME basis as the majors study (dir_sign·(p_h−p0)/p0·1e4), so the alt book is directly comparable.

Processed PER MONTH (bounds the ASOF-join working set to one month of ctx — the disk here is tight, a single
whole-window ASOF spills). Each entry's +8h endpoint can cross into the next month, so each month's ctx scan
includes a 2-day tail into the following month.

Definitions (frozen in ALT_VALIDATION_PREREG.md):
  opening-taker : direction IN ('Open Long','Open Short') AND crossed=TRUE.
  dir_sign      : +1 Long, −1 Short.
  price basis   : asset_ctx mid_px, backward-ASOF at entry ts (p0) and at entry+8h (p8), staleness ≤90s each.
  universe      : ALT coins only (coin NOT IN BTC/ETH/SOL/HYPE — majors already tested on node_fills).

    python -m research.studies.copy_cohort.alt_episodes            # all months present in alt_fills
    python -m research.studies.copy_cohort.alt_episodes 202511     # one month
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import duckdb

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS, as_of_cutoff_ms

ALT_FILLS_DIR = REPO_ROOT / "data" / "raw" / "alt_fills"
CTX = str(REPO_ROOT / "data" / "raw" / "asset_ctx" / "month=*" / "day=*" / "ctx.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_episodes"
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
H8_MS = 28_800_000
STALE_MS = 90_000
DAY_MS = 86_400_000
DUCK_MEM = "10GB"


def _months_present() -> list[int]:
    ms = sorted({int(Path(p).parts[-1].split("=")[1])
                 for p in glob.glob(str(ALT_FILLS_DIR / "month=*"))})
    return ms


def _fold_of(month: int) -> int:
    """Test-month label if this calendar month is a fold (MONTHS[3:]), else -1."""
    folds = MONTHS[3:]
    return month if month in folds else -1


def build_month(month: int) -> int:
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{DUCK_MEM}'; SET threads=2")
    majors = ",".join(f"'{m}'" for m in MAJORS)
    fills_glob = str(ALT_FILLS_DIR / f"month={month}" / "day=*" / "fills.parquet")
    if not glob.glob(fills_glob):
        return 0
    # ctx scan window: this month's ctx + a 2-day tail (for entries whose +8h crosses the month boundary)
    y, mm = divmod(month, 100)
    nxt = (y + 1) * 100 + 1 if mm == 12 else month + 1
    ctx_glob_this = str(REPO_ROOT / "data" / "raw" / "asset_ctx" / f"month={month}" / "day=*" / "ctx.parquet")
    ctx_glob_next = str(REPO_ROOT / "data" / "raw" / "asset_ctx" / f"month={nxt}" / "day=0*" / "ctx.parquet")
    ctx_parts = glob.glob(ctx_glob_this) + [p for p in glob.glob(ctx_glob_next)
                                            if int(Path(p).parts[-2].split("=")[1]) <= nxt * 100 + 3]
    if not ctx_parts:
        print(f"  {month}: no ctx parts, skip", flush=True)
        return 0
    ctx_list = ",".join(f"'{p}'" for p in ctx_parts)
    fold = _fold_of(month)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    part = OUT_DIR / f"month={month}" / "part.parquet"
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(part) + ".tmp"
    con.execute(f"""
      COPY (
        WITH ent AS (
          SELECT wallet, coin,
                 CASE WHEN direction='Open Long' THEN 1 WHEN direction='Open Short' THEN -1 END AS dir_sign,
                 ts, abs(sz) AS abs_sz
          FROM read_parquet('{fills_glob}')
          WHERE crossed = TRUE AND direction IN ('Open Long','Open Short') AND coin NOT IN ({majors})
            AND start_position = 0   -- TRUE position open (flat before), matching majors start_position opener
        ),
        ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL),
        p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS px0_ts
               FROM ent e ASOF LEFT JOIN ctx c ON e.coin=c.coin AND e.ts >= c.ts),
        p8 AS (SELECT p0.*, c.mid_px AS px8, c.ts AS px8_ts
               FROM p0 ASOF LEFT JOIN ctx c ON p0.coin=c.coin AND (p0.ts + {H8_MS}) >= c.ts)
        SELECT wallet, coin, ts, dir_sign, abs_sz, px0, px8, (abs_sz*px0) AS notl,
               CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0>0
                      AND (ts-px0_ts)<={STALE_MS} AND ((ts+{H8_MS})-px8_ts)<={STALE_MS}
                    THEN dir_sign*(px8-px0)/px0*1e4 END AS raw_markout_8h,
               (ts-px0_ts) AS p0_lag_ms, ((ts+{H8_MS})-px8_ts) AS p8_lag_ms,
               {fold} AS fold_month
        FROM p8 WHERE dir_sign IS NOT NULL
      ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    con.close()
    os.replace(tmp, part)
    print(f"  {month} (fold={fold}): {n:,} opening-taker alt entries -> {part}", flush=True)
    return n


def build(months: list[int] | None = None) -> None:
    ms = months or _months_present()
    print(f"alt_episodes: building {len(ms)} months {ms}", flush=True)
    tot = 0
    for m in ms:
        tot += build_month(m)
    # summary over all parts
    con = duckdb.connect()
    g = str(OUT_DIR / "month=*" / "part.parquet")
    if glob.glob(g):
        d = con.execute(f"""SELECT count(*) n, count(DISTINCT wallet) w, count(DISTINCT coin) c,
            count(raw_markout_8h) ev FROM read_parquet('{g}')""").fetchone()
        t = con.execute(f"""SELECT count(*) n, count(raw_markout_8h) ev
            FROM read_parquet('{g}') WHERE fold_month>0""").fetchone()
        print(f"\nalt_episodes TOTAL: {d[0]:,} entries | {d[1]} wallets | {d[2]} coins | {d[3]:,} w/8h markout")
        print(f"  in-test (folds 202511-202606): {t[0]:,} entries, {t[1]:,} evaluable")


if __name__ == "__main__":
    build([int(a) for a in sys.argv[1:]] or None)
