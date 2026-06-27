"""Executor interface — paper, backtest, and live all implement this.

The engine never knows which mode it's in; it just submits orders and applies the
returned fills. Live signing, paper fill-sim, and backtest replay all hide here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from babylon.core import Fill, Order


@dataclass(frozen=True, slots=True)
class Quote:
    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2


class Executor(Protocol):
    def net_position(self, coin: str) -> Decimal: ...

    def net_positions(self) -> dict[str, Decimal]: ...

    def set_position(self, coin: str, size: Decimal) -> None:
        """Restore a net position (paper recovery derives it from the ledger)."""
        ...

    def submit(self, order: Order, quote: Quote, now: int) -> Fill | None:
        """Execute an order; return the resulting fill (None if it didn't fill)."""
        ...
