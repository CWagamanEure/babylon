"""Paper executor — simulates fills against the live book.

Taker model: marketable orders cross the spread (buy at ask, sell at bid). This
is faithful for **aggressive** strategies only; passive/maker fills need queue
modeling and are not represented (see the paper-fidelity ceiling in
``docs/ARCHITECTURE.md``). No signing, no real orders — zero financial risk.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from babylon.core import Fill, Order
from babylon.execution.base import Quote


class PaperExecutor:
    def __init__(self) -> None:
        self._net: dict[str, Decimal] = defaultdict(lambda: Decimal(0))

    def net_position(self, coin: str) -> Decimal:
        return self._net[coin]

    def net_positions(self) -> dict[str, Decimal]:
        return {c: s for c, s in self._net.items() if s != 0}

    def submit(self, order: Order, quote: Quote, now: int) -> Fill | None:
        if order.size == 0:
            return None
        # Taker: pay the spread.
        price = quote.ask if order.is_buy else quote.bid
        self._net[order.coin] += order.size
        return Fill(
            coin=order.coin,
            size=order.size,
            price=price,
            time=now,
            cloid=order.cloid,
        )
