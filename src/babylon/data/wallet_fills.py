"""Fetch follow-wallet fill histories from the Hyperliquid REST API.

For copy-trade backtesting we need each target wallet's executions — coin, side,
price, size, time, realized PnL, and the position trajectory. ``userFillsByTime``
gives exactly that (incl. ``closedPnl`` for per-position skill), capped at 2000
fills/call, so we paginate by time. Each wallet is written to its own Parquet
file (resumable: an already-fetched wallet is skipped).

This is the 2026 source — the S3 ``node_trades`` archive ends mid-2025, so the
REST API is the only way to reach the period these wallets were selected from.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import aiohttp
import polars as pl

from babylon.exchange.rest import InfoClient
from babylon.logging import get_logger

log = get_logger("wallet_fills")

_PAGE = 2000  # HL userFillsByTime cap


class _Throttle:
    """Global minimum-interval rate limiter shared across all wallet fetches —
    HL's info rate limit is IP-wide, so per-wallet sleeps don't bound it."""

    def __init__(self, min_interval_s: float) -> None:
        self._mi = min_interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            dt = time.monotonic() - self._last
            if dt < self._mi:
                await asyncio.sleep(self._mi - dt)
            self._last = time.monotonic()


async def _fills_page(
    info: InfoClient, throttle: _Throttle, wallet: str, start_ms: int, end_ms: int,
    *, retries: int = 6,
) -> list[dict[str, Any]]:
    """One throttled page, retrying on HTTP 429 with exponential backoff."""
    for attempt in range(retries):
        await throttle.wait()
        try:
            return await info.user_fills_by_time(wallet, start_ms, end_ms)
        except aiohttp.ClientResponseError as exc:
            if exc.status == 429 and attempt < retries - 1:
                await asyncio.sleep(2.0 * (2**attempt))  # 2,4,8,16,32s
                continue
            raise
    return []


# Columns we keep (the rest of the payload is dropped); schema keeps Parquet stable.
# `hash` (zero hash = TWAP slice / liquidation, not conviction) and `twapId` let the
# skill measure exclude mechanical fills (~12% of the stream).
_SCHEMA: dict[str, type[pl.DataType] | pl.DataType] = {
    "time": pl.Int64, "coin": pl.Utf8, "side": pl.Utf8, "px": pl.Float64,
    "sz": pl.Float64, "closedPnl": pl.Float64, "dir": pl.Utf8,
    "startPosition": pl.Float64, "fee": pl.Float64, "oid": pl.Int64,
    "tid": pl.Int64, "crossed": pl.Boolean, "hash": pl.Utf8, "twapId": pl.Int64,
}


async def fetch_wallet(
    info: InfoClient, throttle: _Throttle, wallet: str, start_ms: int, end_ms: int
) -> list[dict[str, Any]]:
    """Paginate a wallet's fills over [start_ms, end_ms]. Dedups by ``tid`` across
    page boundaries; advances by the max time seen so either sort order is safe."""
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    cursor = start_ms
    while True:
        batch = await _fills_page(info, throttle, wallet, cursor, end_ms)
        fresh = [f for f in batch if int(f["tid"]) not in seen]
        if not fresh:
            break
        out.extend(fresh)
        seen.update(int(f["tid"]) for f in fresh)
        if len(batch) < _PAGE:
            break
        nxt = max(int(f["time"]) for f in batch)
        cursor = nxt + 1 if nxt <= cursor else nxt  # guarantee progress
    return out


def _to_frame(fills: list[dict[str, Any]]) -> pl.DataFrame:
    rows = [
        {
            "time": int(f["time"]), "coin": str(f["coin"]), "side": str(f["side"]),
            "px": float(f["px"]), "sz": float(f["sz"]), "closedPnl": float(f["closedPnl"]),
            "dir": str(f["dir"]), "startPosition": float(f["startPosition"]),
            "fee": float(f["fee"]), "oid": int(f["oid"]), "tid": int(f["tid"]),
            "crossed": bool(f["crossed"]), "hash": str(f["hash"]),
            "twapId": int(f["twapId"]) if f.get("twapId") is not None else None,
        }
        for f in fills
    ]
    return pl.DataFrame(rows, schema=_SCHEMA).sort("time")


async def fetch_all(
    rest_url: str, wallets: list[str], start_ms: int, end_ms: int, out_dir: Path,
    *, concurrency: int = 2, min_interval_s: float = 0.9,
) -> dict[str, int]:
    """Fetch every wallet's fills → ``{out_dir}/{wallet}.parquet`` (resumable).
    Returns {wallet: n_fills}. Bounded concurrency + a shared (IP-wide) throttle."""
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    throttle = _Throttle(min_interval_s)
    counts: dict[str, int] = {}

    async with InfoClient(rest_url, timeout=30.0) as info:
        async def one(w: str) -> None:
            dest = out_dir / f"{w}.parquet"
            existing = await asyncio.to_thread(_existing_count, dest)
            if existing is not None:
                counts[w] = existing
                return
            async with sem:
                try:
                    fills = await fetch_wallet(info, throttle, w, start_ms, end_ms)
                except Exception as exc:  # noqa: BLE001 — one bad wallet must not kill the batch
                    log.warning("wallet_fills.error", wallet=w, error=str(exc))
                    counts[w] = -1
                    return
            await asyncio.to_thread(lambda: _to_frame(fills).write_parquet(dest))
            counts[w] = len(fills)
            log.info("wallet_fills.fetched", wallet=w, n=len(fills))

        await asyncio.gather(*(one(w) for w in wallets))
    return counts


def _existing_count(dest: Path) -> int | None:
    """Row count of an already-fetched wallet file, or None if not yet fetched."""
    return pl.read_parquet(dest).height if dest.exists() else None


def load_wallets(csv_path: Path) -> list[str]:
    """Wallet addresses from the follow CSV (column ``w``)."""
    return pl.read_csv(csv_path)["w"].to_list()
