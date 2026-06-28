"""Replay archived L2 snapshots back as an event-time stream for backtesting.

Reads the same Parquet the recorder/backfill write (``{dir}/l2Book/{coin}/{day}/
*.parquet``) and yields ``ReplayEvent``s in **global event-time order** across
coins. Design constraints (per ``docs/BACKTEST.md`` §8b, from the data audit):

- **Day-chunked** per coin → avoids a single range-wide sort that would OOM. Note
  the k-way merge holds one materialized coin-day per coin concurrently (memory ~
  N_coins × one coin-day, not constant), and each coin-day is fully read into Python
  lists before yielding — fine for a handful of coins, not a streaming guarantee.
- **Union-sort + dedup across files.** Filenames carry the WALL clock but partitions
  are by EVENT day, and backfill (unlike the recorder) doesn't dedup — so we sort
  the union of a coin-day's files by ``time`` and drop duplicate ``(time, ver_num)``
  (re-backfill / live+backfill overlap). Never trust file order.
- **Deterministic total order**: per-coin stream sorted by ``(time, ver_num, idx)``
  (``ver_num`` is null for live captures → the stable concat index breaks ties), then
  a k-way merge across coins keyed by ``(time, coin_index)``.
- **Slim float book** (no pydantic/Decimal) for speed over millions of snapshots.
- Skips null / crossed / empty archive books (they exist — backfill writes unvalidated).
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from babylon.execution.fill_model import Book
from babylon.logging import get_logger

log = get_logger("replay")


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    time: int  # event time, epoch ms
    coin: str
    coin_index: int
    book: Book


def _days(start: str, end: str) -> list[str]:
    """Inclusive YYYYMMDD..YYYYMMDD → ['YYYY-MM-DD', ...] (gmt, matches partitions)."""
    d0 = datetime.strptime(start, "%Y%m%d").replace(tzinfo=UTC)
    d1 = datetime.strptime(end, "%Y%m%d").replace(tzinfo=UTC)
    out, d = [], d0
    while d <= d1:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


class L2Replay:
    def __init__(self, data_dir: Path, coins: list[str], start: str, end: str) -> None:
        self._root = Path(data_dir)
        self._coins = coins
        self._days = _days(start, end)
        self.skipped = 0  # invalid books dropped (null/crossed/empty/NaN/non-positive)
        self.bad_files = 0  # unreadable/corrupt parquet skipped
        self.out_of_order = 0  # events dropped for violating monotonic time
        self.deduped = 0  # identical-content duplicate rows collapsed

    def _coin_events(self, coin: str, coin_index: int) -> Iterator[ReplayEvent]:
        for day in self._days:
            part = self._root / "l2Book" / coin / day
            files = sorted(part.glob("*.parquet")) if part.is_dir() else []
            frames = []
            for f in files:
                try:
                    frames.append(pl.read_parquet(f))
                except Exception:  # noqa: BLE001 — one corrupt/partial flush must not kill the run
                    self.bad_files += 1
                    log.warning("replay.bad_parquet", file=str(f))
            if not frames:
                continue
            df = pl.concat(frames).with_row_index("_idx")
            df = df.sort(["time", "ver_num", "_idx"], nulls_last=True)
            # Drop duplicate rows but ONLY when they're genuinely identical: same
            # (time, ver_num) AND same top-of-book. Including best_bid/ask in the key
            # means a ver_num COLLISION between two DISTINCT snapshots (ver reset/wrap/
            # 0 sentinel) is kept, not silently deleted. Null-ver_num live rows are
            # never deduped. Drops are counted (observable, not silent).
            n0 = df.height
            dup = pl.col("ver_num").is_not_null() & (
                pl.int_range(pl.len()).over(["time", "ver_num", "best_bid", "best_ask"]) > 0
            )
            df = df.filter(~dup)
            self.deduped += n0 - df.height
            yield from self._rows_to_events(df, coin, coin_index)

    def _rows_to_events(
        self, df: pl.DataFrame, coin: str, coin_index: int
    ) -> Iterator[ReplayEvent]:
        times = df["time"].to_list()
        bpx, bsz = df["bid_px"].to_list(), df["bid_sz"].to_list()
        apx, asz = df["ask_px"].to_list(), df["ask_sz"].to_list()
        for i in range(len(times)):
            # Validate the LIST columns the Book is actually built from (not the
            # scalar best_bid/ask, which can disagree on an unvalidated archive row).
            book = _clean_book(bpx[i], bsz[i], apx[i], asz[i])
            if book is None:
                self.skipped += 1
                continue
            yield ReplayEvent(time=int(times[i]), coin=coin, coin_index=coin_index, book=book)

    def events(self) -> Iterator[ReplayEvent]:
        """Yield every coin's events merged into one global event-time stream.
        A final monotonic guard drops any out-of-order event (e.g. a mis-binned
        partition row) so downstream code can rely on non-decreasing time."""
        iters = [self._coin_events(c, i) for i, c in enumerate(self._coins)]
        last = -(1 << 63)
        for ev in heapq.merge(*iters, key=lambda e: (e.time, e.coin_index)):
            if ev.time < last:
                self.out_of_order += 1
                continue
            last = ev.time
            yield ev


def _clean_side(px: list[float] | None, sz: list[float] | None) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Zip price/size to equal length (fixes a mismatched archive row that would
    otherwise let the depth cap be bypassed), dropping non-finite / non-positive levels."""
    out_px: list[float] = []
    out_sz: list[float] = []
    for p, s in zip(px or (), sz or (), strict=False):
        if p is None or s is None or not math.isfinite(p) or not math.isfinite(s):
            continue
        if p <= 0 or s <= 0:
            continue
        out_px.append(float(p))
        out_sz.append(float(s))
    return tuple(out_px), tuple(out_sz)


def _clean_book(
    bpx: list[float] | None, bsz: list[float] | None,
    apx: list[float] | None, asz: list[float] | None,
) -> Book | None:
    """Build a validated Book or None (one-sided / empty / crossed top-of-book)."""
    bp, bs = _clean_side(bpx, bsz)
    ap, as_ = _clean_side(apx, asz)
    if not bp or not ap or bp[0] >= ap[0]:
        return None
    return Book(bid_px=bp, bid_sz=bs, ask_px=ap, ask_sz=as_)
