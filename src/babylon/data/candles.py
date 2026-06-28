"""Fetch OHLC candles from the HL REST API — the marking price series for the
copy-trade backtest (we copy at a wallet's fill price; candles value the open
positions between fills). ``candleSnapshot`` returns up to 5000 candles/call, so
we paginate by open-time. One resumable Parquet per coin.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
import polars as pl

from babylon.data.wallet_fills import _Throttle
from babylon.exchange.rest import InfoClient
from babylon.logging import get_logger

log = get_logger("candles")

_PAGE = 5000
_SCHEMA: dict[str, type[pl.DataType] | pl.DataType] = {
    "time": pl.Int64, "open": pl.Float64, "high": pl.Float64,
    "low": pl.Float64, "close": pl.Float64, "volume": pl.Float64,
}


async def fetch_coin(
    info: InfoClient, throttle: _Throttle, coin: str, interval: str,
    start_ms: int, end_ms: int,
) -> list[dict[str, float]]:
    """Paginate one coin's candles over [start_ms, end_ms]; dedup by open-time.
    A 429 backs off and retries (capped) so a busy moment doesn't drop a coin."""
    out: list[dict[str, float]] = []
    seen: set[int] = set()
    cursor = start_ms
    backoffs = 0
    while True:
        await throttle.wait()
        try:
            batch = await info.candle_snapshot(coin, interval, cursor, end_ms)
        except aiohttp.ClientResponseError as exc:
            if exc.status == 429 and backoffs < 8:
                backoffs += 1
                await asyncio.sleep(2.0 * backoffs)
                continue
            raise
        fresh = [c for c in batch if c.open_time not in seen]
        if not fresh:
            break
        for c in fresh:
            seen.add(c.open_time)
            out.append({
                "time": c.open_time, "open": float(c.open), "high": float(c.high),
                "low": float(c.low), "close": float(c.close), "volume": float(c.volume),
            })
        if len(batch) < _PAGE:
            break
        cursor = max(c.open_time for c in batch) + 1
    return out


def _write(dest: Path, rows: list[dict[str, float]]) -> None:
    pl.DataFrame(rows, schema=_SCHEMA).sort("time").write_parquet(dest)


def _exists(dest: Path) -> bool:
    return dest.exists()


async def fetch_all_candles(
    rest_url: str, coins: list[str], interval: str, start_ms: int, end_ms: int,
    out_dir: Path, *, concurrency: int = 3, min_interval_s: float = 0.7,
) -> dict[str, int]:
    """Fetch every coin's candles → ``{out_dir}/{coin}.parquet`` (resumable)."""
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    throttle = _Throttle(min_interval_s)
    counts: dict[str, int] = {}

    async with InfoClient(rest_url, timeout=30.0) as info:
        async def one(coin: str) -> None:
            dest = out_dir / f"{coin}.parquet"
            if await asyncio.to_thread(_exists, dest):
                counts[coin] = -2  # already present
                return
            async with sem:
                try:
                    rows = await fetch_coin(info, throttle, coin, interval, start_ms, end_ms)
                except Exception as exc:  # noqa: BLE001 — one bad coin must not kill the batch
                    log.warning("candles.error", coin=coin, error=str(exc))
                    counts[coin] = -1
                    return
            await asyncio.to_thread(_write, dest, rows)
            counts[coin] = len(rows)

        await asyncio.gather(*(one(c) for c in coins))
    return counts


def load_universe(path: Path) -> list[str]:
    """Coins from alt_universe.txt (skip comment/blank lines)."""
    return [ln.strip() for ln in path.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
