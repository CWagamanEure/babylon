"""MarketView (latest prices) and the per-strategy Context.

Strategies see only the `Context`: a mode-agnostic read view of prices, their own
virtual position, and account equity, plus `signal()` to emit a desired direction.
They never touch the feed, the executor, or the clock directly — which is what
lets the same strategy run in paper, backtest, and live.
"""

from __future__ import annotations

from decimal import Decimal

from babylon.engine.clock import Clock
from babylon.execution.base import Quote


class MarketView:
    """Latest top-of-book per coin. ``mark`` is a placeholder using mid until the
    real mark/oracle feed lands (see docs/ARCHITECTURE.md pricing section)."""

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}

    def update(self, coin: str, bid: Decimal, ask: Decimal) -> None:
        if bid > 0 and ask > 0:
            self._quotes[coin] = Quote(bid=bid, ask=ask)

    def quote(self, coin: str) -> Quote | None:
        return self._quotes.get(coin)

    def mid(self, coin: str) -> Decimal | None:
        q = self._quotes.get(coin)
        return q.mid if q else None

    def mark(self, coin: str) -> Decimal | None:
        # TODO(mark/oracle feed): use HL mark price for PnL/margin/liquidation.
        return self.mid(coin)

    def marks(self, coins: list[str]) -> dict[str, Decimal]:
        return {c: m for c in coins if (m := self.mark(c)) is not None}


class Context:
    """Hands a strategy its read view + signal sink for one evaluation."""

    def __init__(
        self,
        *,
        strategy: str,
        clock: Clock,
        market: MarketView,
        positions: dict[str, Decimal],
        equity: Decimal,
    ) -> None:
        self._strategy = strategy
        self._clock = clock
        self._market = market
        self._positions = positions
        self._equity = equity
        self._signals: dict[str, float] = {}

    def now(self) -> int:
        return self._clock.now()

    def mid(self, coin: str) -> Decimal | None:
        return self._market.mid(coin)

    def mark(self, coin: str) -> Decimal | None:
        return self._market.mark(coin)

    def position(self, coin: str) -> Decimal:
        """This strategy's *virtual* position in the coin."""
        return self._positions.get(coin, Decimal(0))

    def equity(self) -> Decimal:
        """Total account equity (for context; sizing uses the strategy budget)."""
        return self._equity

    def signal(self, coin: str, direction: float) -> None:
        self._signals[coin] = direction

    def collected(self) -> dict[str, float]:
        return dict(self._signals)
