"""Wire a :class:`WebSocketFeed` to a :class:`ParquetStore`.

The recorder subscribes to trades / L2 book / BBO for a set of coins, parses each
message into typed models, and persists a flat row per event. This is the data
capture layer the backtester and research stack will read from.

Parquet writes are offloaded with ``asyncio.to_thread`` so the (occasionally
blocking) disk flush never stalls the read loop or heartbeat. Handlers are
invoked serially by the feed's dispatcher, so the store is never touched
concurrently.
"""

from __future__ import annotations

import asyncio
from typing import Any

from babylon.data.models import Bbo, L2Book, Trade
from babylon.data.store import ParquetStore
from babylon.exchange.websocket import Subscription, WebSocketFeed
from babylon.logging import get_logger

log = get_logger("recorder")

# Warn if consecutive L2 snapshots for a coin are further apart than this — a
# likely capture gap (reconnect, server hiccup) that breaks contiguity. The live
# WS l2Book feed is naturally coarse (multi-second cadence), so this is set well
# above normal spacing to flag only disconnect-sized holes.
GAP_WARN_MS = 30_000


class Recorder:
    def __init__(self, feed: WebSocketFeed, store: ParquetStore) -> None:
        self._feed = feed
        self._store = store
        self._last_book_time: dict[str, int] = {}
        feed.on("trades", self._on_trades)
        feed.on("l2Book", self._on_book)
        feed.on("bbo", self._on_bbo)

    def record_coin(self, coin: str, *, book: bool = True, bbo: bool = False) -> None:
        self._feed.subscribe(Subscription(type="trades", coin=coin))
        if book:
            self._feed.subscribe(Subscription(type="l2Book", coin=coin))
        if bbo:
            self._feed.subscribe(Subscription(type="bbo", coin=coin))

    async def _write(self, kind: str, coin: str, row: dict[str, Any]) -> None:
        await asyncio.to_thread(self._store.write, kind, coin, row)

    async def _on_trades(self, data: list[dict[str, Any]]) -> None:
        for raw in data:
            t = Trade.from_ws(raw)
            await self._write("trades", t.coin, t.to_row())

    async def _on_book(self, data: dict[str, Any]) -> None:
        book = L2Book.from_ws(data)
        if not book.is_valid():
            log.warning("recorder.invalid_book", coin=book.coin, time=book.time)
            return
        last = self._last_book_time.get(book.coin)
        if last is not None:
            if book.time == last:
                return  # duplicate snapshot (e.g. resubscribe) — skip
            if book.time - last > GAP_WARN_MS:
                log.warning("recorder.book_gap", coin=book.coin, gap_ms=book.time - last)
        self._last_book_time[book.coin] = book.time
        await self._write("l2Book", book.coin, book.to_row())

    async def _on_bbo(self, data: dict[str, Any]) -> None:
        b = Bbo.from_ws(data)
        await self._write("bbo", b.coin, b.to_row())
