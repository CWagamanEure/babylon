"""Per-strategy virtual ledgers with average-cost PnL accounting.

Each ``(strategy, coin)`` keeps a signed position, an average entry price, and
realized PnL. Equity = starting capital + Σ realized + Σ unrealized (at marks).
The net exchange position per coin is the sum across strategies — that's what the
reconciler drives and what the Net Risk Manager limits.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Position:
    size: Decimal = Decimal(0)  # signed
    entry_px: Decimal = Decimal(0)  # avg cost of the open position
    realized: Decimal = Decimal(0)

    def unrealized(self, mark: Decimal) -> Decimal:
        return (mark - self.entry_px) * self.size


class Ledger:
    def __init__(self, starting_equity: Decimal) -> None:
        self._start = starting_equity
        self._pos: dict[tuple[str, str], Position] = defaultdict(Position)

    def position(self, strategy: str, coin: str) -> Decimal:
        pos = self._pos.get((strategy, coin))  # read without creating an entry
        return pos.size if pos else Decimal(0)

    def net_position(self, coin: str) -> Decimal:
        return sum(
            (p.size for (s, c), p in self._pos.items() if c == coin), Decimal(0)
        )

    def apply_fill(self, strategy: str, coin: str, size_delta: Decimal, price: Decimal) -> None:
        """Apply a signed fill to one strategy's virtual position (avg-cost)."""
        if size_delta == 0:
            return
        pos = self._pos[(strategy, coin)]
        old = pos.size
        new = old + size_delta

        if old == 0 or (old > 0) == (size_delta > 0):
            # opening or adding in the same direction → update average entry.
            total = abs(old) + abs(size_delta)
            pos.entry_px = (pos.entry_px * abs(old) + price * abs(size_delta)) / total
            pos.size = new
            return

        # reducing, closing, or flipping through zero.
        closed = min(abs(size_delta), abs(old))
        direction = Decimal(1) if old > 0 else Decimal(-1)
        pos.realized += closed * (price - pos.entry_px) * direction
        if abs(size_delta) <= abs(old):
            pos.size = new
            if pos.size == 0:
                pos.entry_px = Decimal(0)
        else:
            # flipped: remainder opens a fresh position at the fill price.
            pos.size = new
            pos.entry_px = price

    def realized_pnl(self) -> Decimal:
        return sum((p.realized for p in self._pos.values()), Decimal(0))

    def unrealized_pnl(self, marks: dict[str, Decimal]) -> Decimal:
        return sum(
            (p.unrealized(marks[c]) for (s, c), p in self._pos.items() if c in marks),
            Decimal(0),
        )

    def equity(self, marks: dict[str, Decimal]) -> Decimal:
        return self._start + self.realized_pnl() + self.unrealized_pnl(marks)
