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
    def __init__(self, *, taker_fee_bps: float = 0.0) -> None:
        # taker_fee_bps folds the fee INTO the fill price so the equity curve actually
        # pays it (else equity is fee-blind — the live-follow audit's finding). Default
        # 0 preserves the original fill-at-touch behaviour for existing paper runs.
        self._fee = Decimal(str(taker_fee_bps)) / Decimal(10_000)
        self._net: dict[str, Decimal] = defaultdict(lambda: Decimal(0))

    def net_position(self, coin: str) -> Decimal:
        return self._net[coin]

    def net_positions(self) -> dict[str, Decimal]:
        return {c: s for c, s in self._net.items() if s != 0}

    def set_position(self, coin: str, size: Decimal) -> None:
        self._net[coin] = size

    def submit(self, order: Order, quote: Quote, now: int) -> Fill | None:
        if order.size == 0:
            return None
        # Taker: pay the spread, and the taker fee folded into the price (a buy pays
        # more, a sell receives less) so realized PnL/equity reflect the fee.
        if order.is_buy:
            price = quote.ask * (Decimal(1) + self._fee)
        else:
            price = quote.bid * (Decimal(1) - self._fee)
        self._net[order.coin] += order.size
        return Fill(
            coin=order.coin,
            size=order.size,
            price=price,
            time=now,
            cloid=order.cloid,
        )
