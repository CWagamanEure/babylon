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

from decimal import ROUND_HALF_EVEN, Decimal

from babylon.core import Order, TimeInForce
from babylon.logging import get_logger

log = get_logger("reconcile")


class Reconciler:
    def __init__(
        self,
        *,
        min_trade_notional: Decimal = Decimal(10),
        lot: Decimal = Decimal("1e-8"),
        run_id: str = "",
    ) -> None:
        self._min_notional = min_trade_notional
        self._lot = lot  # quantize order sizes → all booked state is exact at this step
        self._run_id = run_id  # cloid prefix; makes cloids unique across runs/processes
        self._counter = 0

    @property
    def lot(self) -> Decimal:
        return self._lot

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
            # Quantize the delta to the lot step so every booked size is exact at
            # ≤8 dp (lossless for the journal's scaled-int money; required by real
            # exchanges). cur is already lot-quantized from prior fills.
            delta = (target - cur).quantize(self._lot, rounding=ROUND_HALF_EVEN)
            if delta == 0:
                continue
            if abs(delta) * marks[coin] < self._min_notional:
                continue  # inside the deadband — don't thrash
            reduce_only = (target == 0 and cur != 0) or (
                (target > 0) == (cur > 0) and abs(target) < abs(cur)
            )
            self._counter += 1
            prefix = f"{self._run_id}:" if self._run_id else ""
            orders.append(
                Order(
                    coin=coin,
                    size=delta,
                    price=None,
                    reduce_only=reduce_only,
                    tif=TimeInForce.IOC,
                    cloid=f"{prefix}{coin}:{self._counter}",  # unique per order, run-scoped
                )
            )
        return orders
