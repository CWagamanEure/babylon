"""Reconciler — diff desired net position vs actual, emit orders.

Target-position paradigm: self-healing across missed fills and restarts. A
**deadband** (min trade notional) prevents thrash — without it, every tiny Kelly
re-size would fire a fee-bleeding order.

Each emitted order gets a **unique** cloid (a per-reconciler monotonic counter).
An earlier design keyed the cloid to ``(coin, quantized target)`` for
"idempotency", but a mean-reverting book revisits the same target repeatedly, so
different orders collided on one cloid → the exchange rejects the re-entry as a
duplicate. Crash-time idempotency belongs to the durable journal (it stores each
order's cloid and reconciles it against the exchange on boot), not to a
deterministic-but-colliding key. Coins are iterated in sorted order so the
counter assignment is deterministic for a given tick (backtest reproducibility).
"""

from __future__ import annotations

from decimal import Decimal

from babylon.core import Order, TimeInForce
from babylon.logging import get_logger

log = get_logger("reconcile")


class Reconciler:
    def __init__(self, *, min_trade_notional: Decimal = Decimal(10)) -> None:
        self._min_notional = min_trade_notional
        self._counter = 0

    def diff(
        self,
        *,
        net_targets: dict[str, Decimal],
        actual: dict[str, Decimal],
        marks: dict[str, Decimal],
    ) -> list[Order]:
        orders: list[Order] = []
        for coin in sorted(set(net_targets) | set(actual)):
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
            self._counter += 1
            orders.append(
                Order(
                    coin=coin,
                    size=delta,
                    price=None,
                    reduce_only=reduce_only,
                    tif=TimeInForce.IOC,
                    cloid=f"{coin}:{self._counter}",  # unique per order
                )
            )
        return orders
