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
from typing import Any


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

    def position_detail(self, strategy: str, coin: str) -> tuple[Decimal, Decimal, Decimal]:
        """(size, entry_px, realized) for one (strategy, coin) — zeros if absent."""
        p = self._pos.get((strategy, coin))
        if p is None:
            return (Decimal(0), Decimal(0), Decimal(0))
        return (p.size, p.entry_px, p.realized)

    def positions(self) -> list[tuple[str, str, Decimal, Decimal, Decimal]]:
        """Every (strategy, coin, size, entry_px, realized) the ledger knows about —
        including closed positions that still carry realized PnL."""
        return [
            (s, c, p.size, p.entry_px, p.realized)
            for (s, c), p in self._pos.items()
            if p.size != 0 or p.realized != 0
        ]

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

    # --- durable state (exact Decimal; see docs/JOURNAL.md) -------------------

    def to_state(self) -> dict[str, Any]:
        return {
            "start": str(self._start),
            "pos": [
                [s, c, str(p.size), str(p.entry_px), str(p.realized)]
                for (s, c), p in self._pos.items()
            ],
        }

    @classmethod
    def from_state(cls, st: dict[str, Any]) -> Ledger:
        led = cls(Decimal(st["start"]))
        for s, c, size, entry, realized in st["pos"]:
            led._pos[(s, c)] = Position(Decimal(size), Decimal(entry), Decimal(realized))
        return led
