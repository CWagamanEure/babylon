"""Paper executor — simulates fills against the live book.

Taker model: marketable orders cross the spread (buy at ask, sell at bid). This
is faithful for **aggressive** strategies only; passive/maker fills need queue
modeling and are not represented (see the paper-fidelity ceiling in
``docs/ARCHITECTURE.md``). No signing, no real orders — zero financial risk.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Literal

from babylon.core import Fill, Order
from babylon.execution.base import Quote
from babylon.execution.fill_model import Book, FillReport, fill as _depth_fill

Mode = Literal["retail", "validator"]


class PaperExecutor:
    def __init__(
        self, *, taker_fee_bps: float = 0.0, mode: Mode = "retail",
        impact_bps: float = 0.0, max_depth_frac: float = 0.25, maker_cost_bps: float = 2.0,
    ) -> None:
        # taker_fee_bps folds the fee INTO the fill price so the equity curve actually
        # pays it (else equity is fee-blind — the live-follow audit's finding). Default
        # 0 preserves the original fill-at-touch behaviour for existing paper runs.
        self._fee = Decimal(str(taker_fee_bps)) / Decimal(10_000)
        # Cost is SINGLE-SOURCED in the fill price (fee+spread+impact); the round-trip
        # measure must subtract nothing further (§v4.6). submit_book is the faithful path.
        self._fee_bps = float(taker_fee_bps)
        self._mode = mode
        self._impact_bps = float(impact_bps)        # entry-impact slippage (retail arm)
        self._max_depth_frac = float(max_depth_frac)
        self._maker_bps = float(maker_cost_bps)      # validator-arm cost at the wallet price
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

    def submit_book(
        self, order: Order, book: Book, now: int, *, wallet_px: Decimal | None = None,
    ) -> tuple[Fill | None, FillReport]:
        """Faithful follow-system fill — parity with the backtest's depth-walking
        fill_model so the live equity curve == the backtested prior. Cost (fee + spread
        + impact) is folded into the returned price; nothing else subtracts it.

        - retail: walk the real L2 book (VWAP), charge taker fee + entry-impact slippage,
          depth-cap at max_depth_frac (full-fill-or-none — over-cap returns no fill).
        - validator: same/next-block co-execution ≈ the wallet's fill price, charged a
          small maker-ish cost (requires wallet_px); full fill, no book walk.
        """
        if order.size == 0:
            return None, FillReport(False, 0.0, "zero size")
        if self._mode == "validator":
            if wallet_px is None or wallet_px <= 0:
                return None, FillReport(False, 0.0, "validator mode needs wallet_px")
            worsen = Decimal(str(self._maker_bps)) / Decimal(10_000)
            price = wallet_px * (Decimal(1) + worsen) if order.is_buy else wallet_px * (Decimal(1) - worsen)
            self._net[order.coin] += order.size
            return Fill(coin=order.coin, size=order.size, price=price, time=now,
                        cloid=order.cloid), FillReport(True, 0.0)
        f, rep = _depth_fill(order, book, now=now, slippage_bps=self._impact_bps,
                             fee_bps=self._fee_bps, max_depth_fraction=self._max_depth_frac)
        if f is not None:
            self._net[order.coin] += order.size
        return f, rep
