"""Parquet persistence for captured market data.

Records are buffered in memory and flushed to **event-time** date-partitioned
Parquet files::

    {data_dir}/{kind}/{coin}/{YYYY-MM-DD}/{epoch_ms}_{seq}.parquet

Partitioning by the record's own ``time`` (not the wall clock) keeps backfilled
history and midnight-boundary live data in the right day. Each flush is written
with an **explicit schema** so a thin/empty-book batch can't make Polars infer a
``Null`` column and then crash — or write a ``Null``-typed file that poisons the
partition on read. The buffer is cleared only after a successful write, so a
failed flush never loses records.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import polars as pl

from babylon.logging import get_logger

log = get_logger("store")

# Explicit schemas keep every flush's Parquet file byte-compatible regardless of
# whether a batch happened to contain thin books / empty sides. Keys MUST stay in
# sync with the matching model's ``to_row`` (asserted in tests).
_PX = pl.Float64
# Values mix DataType classes (pl.Int64) and instances (pl.List(...)); polars
# accepts both, so the value type is intentionally broad.
_SCHEMAS: dict[str, dict[str, Any]] = {
    "trades": {
        "time": pl.Int64,
        "side": pl.Utf8,
        "px": _PX,
        "sz": _PX,
        "tid": pl.Int64,
    },
    "l2Book": {
        "time": pl.Int64,
        "ver_num": pl.Int64,
        "best_bid": _PX,
        "best_ask": _PX,
        "mid": _PX,
        "bid_px": pl.List(_PX),
        "bid_sz": pl.List(_PX),
        "bid_n": pl.List(pl.Int64),
        "ask_px": pl.List(_PX),
        "ask_sz": pl.List(_PX),
        "ask_n": pl.List(pl.Int64),
    },
    "bbo": {
        "time": pl.Int64,
        "bid_px": _PX,
        "bid_sz": _PX,
        "bid_n": pl.Int64,
        "ask_px": _PX,
        "ask_sz": _PX,
        "ask_n": pl.Int64,
    },
}


def _event_day(record: dict[str, Any]) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(record["time"] / 1000))


class ParquetStore:
    def __init__(self, data_dir: Path, *, flush_every: int = 5000) -> None:
        self._root = Path(data_dir)
        self._flush_every = flush_every
        self._buffers: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        self._seq = 0

    def write(self, kind: str, coin: str, record: dict[str, Any]) -> None:
        key = (kind, coin)
        buf = self._buffers[key]
        buf.append(record)
        if len(buf) >= self._flush_every:
            self._flush_key(key)

    def flush(self) -> None:
        for key in list(self._buffers):
            self._flush_key(key)

    def _flush_key(self, key: tuple[str, str]) -> None:
        kind, coin = key
        rows = self._buffers.get(key, [])
        if not rows:
            return
        schema = _SCHEMAS.get(kind)
        # Group by the record's own event day so partitions reflect when the data
        # actually happened, not when we happened to flush it.
        by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_day[_event_day(r)].append(r)

        # Write everything first; only drop the buffer if all writes succeed.
        for day, day_rows in by_day.items():
            df = (
                pl.DataFrame(day_rows, schema=schema)
                if schema is not None
                else pl.DataFrame(day_rows, infer_schema_length=None)
            )
            part = self._root / kind / coin / day
            part.mkdir(parents=True, exist_ok=True)
            self._seq += 1
            path = part / f"{int(time.time() * 1000)}_{self._seq}.parquet"
            df.write_parquet(path)
            log.debug("store.flush", kind=kind, coin=coin, day=day, rows=len(day_rows))
        self._buffers.pop(key, None)
