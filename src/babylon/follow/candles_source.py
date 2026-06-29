"""Live candle-lookup refresh for the rolling selection (followable pricing).

`load_price_lookups` reads a STATIC parquet snapshot; over a multi-month live run those
candles go stale, so each roll must fetch fresh hourly candles covering its train window.
Output matches `load_price_lookups`: coin → (open_times, closes).
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import numpy as np

from babylon.logging import get_logger

log = get_logger("follow.candles")


class _CandleInfo(Protocol):
    async def candle_snapshot(
        self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[Any]: ...


async def fetch_lookups(
    info: _CandleInfo, universe: list[str], start_ms: int, end_ms: int, *,
    interval: str = "1h", gap_s: float = 1.1,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """coin → (open_times, closes) over [start_ms, end_ms), paced to the HL weight limit.
    A coin that errors or returns nothing is skipped (it just won't price in selection)."""
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for coin in universe:
        if gap_s:
            await asyncio.sleep(gap_s)
        try:
            candles = await info.candle_snapshot(coin, interval, start_ms, end_ms)
        except Exception as exc:  # noqa: BLE001 — one bad coin must not abort the roll
            log.warning("candles.fetch_failed", coin=coin, error=str(exc))
            continue
        if not candles:
            continue
        candles = sorted(candles, key=lambda c: c.open_time)
        out[coin] = (np.array([c.open_time for c in candles], dtype=np.int64),
                     np.array([float(c.close) for c in candles], dtype=np.float64))
    return out
