"""Per-coin bid-ask spread from REAL top-of-book quotes (HL l2Book).

The copy cost is dominated by the alt-dependent spread, and a flat assumption is
wrong in both directions. We can't recover the true spread from OHLC candles —
on intraday bars the high-low range is volatility, not the spread (Corwin-Schultz
overstates a liquid coin's spread by ~20x). So we sample the live book per coin and
take the median spread over a few snapshots. The follow window ends ~now, so the
current book is period-appropriate; spreads are structural (a coin's liquidity tier
persists), so this is a sound per-coin cost proxy. Per-side copy cost = half-spread
+ HL taker fee.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import polars as pl

from babylon.data.wallet_fills import _Throttle
from babylon.exchange.rest import InfoClient
from babylon.logging import get_logger

log = get_logger("spread")

TAKER_FEE_BPS = 4.5  # HL perp taker (base tier); maker ~1.5 — copy-trades are taker


async def fetch_spreads(
    rest_url: str, coins: list[str], *, samples: int = 3, min_interval_s: float = 0.4,
) -> dict[str, float]:
    """Median full-spread (bps) per coin over ``samples`` live book snapshots."""
    throttle = _Throttle(min_interval_s)
    readings: dict[str, list[float]] = {c: [] for c in coins}
    async with InfoClient(rest_url, timeout=20.0) as info:
        for _ in range(samples):
            for coin in coins:
                await throttle.wait()
                try:
                    b = await info.l2_book(coin)
                except Exception as exc:  # noqa: BLE001 — skip a momentarily bad book
                    log.warning("spread.error", coin=coin, error=str(exc))
                    continue
                if b.best_bid and b.best_ask and b.mid and b.mid > 0:
                    readings[coin].append(float((b.best_ask - b.best_bid) / b.mid) * 1e4)
    out: dict[str, float] = {}
    for coin, vals in readings.items():
        if vals:
            out[coin] = float(statistics.median(vals))
    return out


def per_side_cost_map(
    spreads_bps: dict[str, float], *, taker_fee_bps: float = TAKER_FEE_BPS,
    floor_bps: float = 0.5, cap_bps: float = 120.0,
) -> dict[str, float]:
    """Per-coin per-side copy cost (bps) = half-spread + taker fee, clipped."""
    out: dict[str, float] = {}
    for coin, full in spreads_bps.items():
        half = min(max(full / 2.0, floor_bps), cap_bps)
        out[coin] = half + taker_fee_bps
    return out


def save_spreads(spreads_bps: dict[str, float], path: Path) -> None:
    pl.DataFrame(
        {"coin": list(spreads_bps), "spread_bps": list(spreads_bps.values())}
    ).write_parquet(path)


def load_spreads(path: Path) -> dict[str, float]:
    df = pl.read_parquet(path)
    return dict(zip(df["coin"].to_list(), df["spread_bps"].to_list(), strict=True))
