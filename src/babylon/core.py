"""Shared trading vocabulary used across the engine.

These are internal engine types (not exchange-JSON parsing — that's
``data.models``), so they're lightweight frozen dataclasses. The Decimal/float
boundary (see ``docs/ARCHITECTURE.md``): execution-path quantities (`Order`/`Fill`
size & price) are **Decimal**; signal direction and anything feeding the
stats/numpy domain is **float**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class TimeInForce(StrEnum):
    ALO = "Alo"  # add-liquidity-only (post-only / maker)
    GTC = "Gtc"
    IOC = "Ioc"


@dataclass(frozen=True, slots=True)
class Order:
    """An order to move the *net* exchange position. ``cloid`` is deterministic
    (strategy-agnostic at the net level) for idempotent reconciliation."""

    coin: str
    size: Decimal  # signed: +buy / -sell
    price: Decimal | None  # None = marketable/taker at touch
    reduce_only: bool
    tif: TimeInForce
    cloid: str

    @property
    def is_buy(self) -> bool:
        return self.size > 0


@dataclass(frozen=True, slots=True)
class Fill:
    """A realized fill. Attributed to a strategy when applied to the ledger."""

    coin: str
    size: Decimal  # signed
    price: Decimal
    time: int  # epoch ms
    cloid: str
    strategy: str = field(default="")
