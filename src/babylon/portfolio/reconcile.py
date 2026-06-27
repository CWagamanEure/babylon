"""Reconciler — diff desired net position vs actual, emit orders.

Target-position paradigm: idempotent and self-healing across missed fills and
restarts. A **deadband** (min trade notional) prevents thrash — without it, every
tiny Kelly re-size would fire a fee-bleeding order.
"""

from __future__ import annotations

from decimal import Decimal

from babylon.core import Order, TimeInForce
from babylon.logging import get_logger

log = get_logger("reconcile")


class Reconciler:
    def __init__(self, *, min_trade_notional: Decimal = Decimal(10)) -> None:
        self._min_notional = min_trade_notional

    def diff(
        self,
        *,
        net_targets: dict[str, Decimal],
        actual: dict[str, Decimal],
        marks: dict[str, Decimal],
    ) -> list[Order]:
        orders: list[Order] = []
        for coin in set(net_targets) | set(actual):
            if coin not in marks:
                continue
            target = net_targets.get(coin, Decimal(0))
            cur = actual.get(coin, Decimal(0))
            delta = target - cur
            if delta == 0:
                continue
            if abs(delta) * marks[coin] < self._min_notional:
                continue  # inside the deadband — don't thrash
            reduce_only = (target == 0 and cur != 0) or (
                (target > 0) == (cur > 0) and abs(target) < abs(cur)
            )
            # Deterministic cloid keyed to (coin, quantized target) — NO wall-clock,
            # so a retry/restart for the same target reuses the id and the exchange
            # can dedupe it (idempotent reconciliation).
            cloid = f"{coin}:{int(target * Decimal(10**8))}"
            orders.append(
                Order(
                    coin=coin,
                    size=delta,
                    price=None,
                    reduce_only=reduce_only,
                    tif=TimeInForce.IOC,
                    cloid=cloid,
                )
            )
        return orders
