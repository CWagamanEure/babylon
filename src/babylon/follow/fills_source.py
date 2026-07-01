"""FillsProvider implementations for the SelectionAdapter.

The RollScheduler is synchronous, but fetching a candidate's train-window fills is async
(REST). So the live provider PREFETCHES all candidates' fills for the upcoming roll (async,
paginated, throttled by the caller) into an in-memory store, and the SelectionAdapter then
reads them SYNCHRONOUSLY during the roll. A parquet variant reads a local snapshot for
backtests / offline wiring tests (the existing data/follow/fills schema).

HL `userFillsByTime` returns ascending by time, capped at 2000/call; paginate by advancing
to the last fill's time and de-duping by tid (advancing to last_t+1 would drop fills that
share that millisecond).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

import polars as pl

_PAGE_CAP = 2000
_SCHEMA = {
    "time": pl.Int64, "coin": pl.Utf8, "px": pl.Float64, "sz": pl.Float64, "side": pl.Utf8,
    "crossed": pl.Boolean, "startPosition": pl.Float64, "hash": pl.Utf8, "tid": pl.Int64,
}


class _Info(Protocol):
    async def user_fills_by_time(
        self, address: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]: ...


def fills_to_frame(raw: list[dict[str, Any]]) -> pl.DataFrame:
    """Normalize raw HL fill dicts into the schema `_positions_for` expects, de-duped by
    tid and sorted by time."""
    if not raw:
        return pl.DataFrame(schema=_SCHEMA)
    seen: set[int] = set()
    rows = []
    for f in raw:
        tid = int(f["tid"])
        if tid in seen:
            continue
        seen.add(tid)
        rows.append({
            "time": int(f["time"]), "coin": str(f["coin"]), "px": float(f["px"]),
            "sz": float(f["sz"]), "side": str(f["side"]),
            "crossed": bool(f.get("crossed", True)),
            "startPosition": float(f.get("startPosition", 0.0)),
            "hash": str(f.get("hash", "")), "tid": tid,
        })
    return pl.DataFrame(rows, schema=_SCHEMA).sort("time")


async def page_fills(info: _Info, wallet: str, start_ms: int, end_ms: int, *,
                     gap_s: float = 0.0) -> list[dict[str, Any]]:
    """Fetch all of a wallet's fills in [start_ms, end_ms), paging past the 2000 cap.
    `gap_s` paces each call to stay under the HL info weight limit (~1 req/s for fills)."""
    out: list[dict[str, Any]] = []
    cur = start_ms
    while cur < end_ms:
        if gap_s:
            await asyncio.sleep(gap_s)
        batch = await info.user_fills_by_time(wallet, cur, end_ms)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < _PAGE_CAP:
            break
        last_t = int(batch[-1]["time"])
        cur = last_t + 1 if last_t <= cur else last_t   # re-fetch from last_t (dedup handles it)
    return out


class RestFillsProvider:
    """Async-prefetch + sync-read. Call `await prefetch(...)` before each roll, then the
    SelectionAdapter reads synchronously during `RollScheduler.roll`."""

    def __init__(self, info: _Info, *, min_interval_s: float = 1.1) -> None:
        self._info = info
        self._store: dict[str, pl.DataFrame] = {}
        self._gap = min_interval_s   # ~1 req/s keeps the bulk prefetch under the HL limit

    async def prefetch(self, wallets: list[str], start_ms: int, end_ms: int) -> None:
        for w in wallets:
            self._store[w] = fills_to_frame(
                await page_fills(self._info, w, start_ms, end_ms, gap_s=self._gap))

    def __call__(self, wallet: str, start_ms: int, end_ms: int) -> pl.DataFrame:
        df = self._store.get(wallet)
        if df is None or df.height == 0:
            return pl.DataFrame(schema=_SCHEMA)
        return df.filter((pl.col("time") >= start_ms) & (pl.col("time") < end_ms))

    def clear(self) -> None:
        self._store.clear()


class ParquetFillsProvider:
    """Reads a local per-wallet parquet snapshot (data/follow/fills/{wallet}.parquet) — for
    backtests / offline wiring, NOT the live rolling re-rank (which needs fresh REST fills)."""

    def __init__(self, fills_dir: Path) -> None:
        self._dir = Path(fills_dir)

    def __call__(self, wallet: str, start_ms: int, end_ms: int) -> pl.DataFrame:
        p = self._dir / f"{wallet}.parquet"
        if not p.exists():
            return pl.DataFrame(schema=_SCHEMA)
        # LAZY scan + predicate pushdown: read ONLY the windowed rows, not the whole file. Some
        # whale wallets have 100-500MB of full history; read_parquet(whole).filter decompressed
        # the lot (~3GB peak) before filtering — scan_parquet pushes the time predicate into the
        # reader so a 30-day slice costs ~a tenth of that (fits a 1GB box).
        return pl.scan_parquet(p).filter(
            (pl.col("time") >= start_ms) & (pl.col("time") < end_ms)).collect()
