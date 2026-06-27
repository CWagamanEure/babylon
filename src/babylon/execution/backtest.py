"""Backtest executor — fills against the replayed depth book via the FillModel.

Implements the same ``Executor`` Protocol as paper/live; the engine submits orders
identically and never knows it's in backtest. The driver sets the current depth
book per coin (from the SAME replay event that updated ``MarketView``) before each
tick, so top-of-book pricing and depth-walk reference one consistent book state.

The passed ``Quote`` is ignored — we fill against our own held depth book — which
is safe because the engine's share attribution (``_compute_shares``) never reads
the fill price (verified in the backtest audit).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from babylon.core import Fill, Order
from babylon.execution.base import Quote
from babylon.execution.fill_model import Book, fill


class BacktestExecutor:
    def __init__(self, *, slippage_bps: float = 0.0, max_depth_fraction: float = 0.25) -> None:
        self._net: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
        self._book: dict[str, Book] = {}
        self._slippage_bps = slippage_bps
        self._max_depth_fraction = max_depth_fraction
        # Execution diagnostics for the report.
        self.fills = 0
        self.no_fills = 0
        self.depth_fractions: list[float] = []
        self.no_fill_reasons: Counter[str] = Counter()

    def set_book(self, coin: str, book: Book) -> None:
        self._book[coin] = book

    def net_position(self, coin: str) -> Decimal:
        return self._net[coin]

    def net_positions(self) -> dict[str, Decimal]:
        return {c: s for c, s in self._net.items() if s != 0}

    def set_position(self, coin: str, size: Decimal) -> None:
        self._net[coin] = size

    def submit(self, order: Order, quote: Quote, now: int) -> Fill | None:
        if order.size == 0:
            return None
        book = self._book.get(order.coin)
        if book is None:
            self.no_fills += 1
            self.no_fill_reasons["no book"] += 1
            return None
        f, report = fill(
            order, book, now=now,
            slippage_bps=self._slippage_bps, max_depth_fraction=self._max_depth_fraction,
        )
        if f is None:
            self.no_fills += 1
            self.no_fill_reasons[report.no_fill_reason or "unknown"] += 1
            return None
        self.fills += 1
        self.depth_fractions.append(report.depth_fraction)
        self._net[order.coin] += f.size
        return f
