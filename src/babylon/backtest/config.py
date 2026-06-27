"""Backtest run configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    start: str  # YYYYMMDD inclusive
    end: str  # YYYYMMDD inclusive
    interval_ms: int = 2000  # strategy evaluation cadence in SIMULATED time
    seed: int = 0
    warmup: int = 50  # ticks dropped from the measured curve (strategy window fill)
    max_gap_ms: int = 30_000  # inter-event gap beyond which catch-up ticks are suppressed
    max_staleness_ms: int = 10_000  # a coin with no fresh book within this is treated absent
    slippage_bps: float = 0.0  # taker haircut on the fill price
    max_depth_fraction: float = 0.25  # max share of visible depth one fill may consume
