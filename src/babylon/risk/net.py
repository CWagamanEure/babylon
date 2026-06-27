"""Net Risk Manager — owns the *real* account, not the virtual ledgers.

Per-strategy controls can't see the thing that liquidates you: the net exchange
position. This enforces no-leverage on the net, a **gross-virtual cap** (so the
book can't run large offsetting gross under a flat-looking net), and an
account-level **max-drawdown kill that latches** (a kill that auto-un-kills on
mark jitter is not a survival constraint). It returns a single uniform scale
factor; the engine applies it to every strategy's target so virtual ledgers stay
reconciled to the real net.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from babylon.logging import get_logger

log = get_logger("netrisk")


@dataclass(frozen=True, slots=True)
class NetRiskReview:
    scale: float  # uniform factor to apply to every strategy's target (0 = flat)
    halted: bool
    drawdown: float


class NetRiskManager:
    def __init__(
        self,
        *,
        max_leverage: float = 1.0,
        gross_cap: float = 2.0,
        max_drawdown: float = 0.25,
    ) -> None:
        self._max_leverage = max_leverage
        self._gross_cap = gross_cap
        self._max_drawdown = max_drawdown
        self._high_water: Decimal | None = None  # TODO(durable-state): persist this
        self._halted = False

    def reset(self) -> None:
        """Clear a latched halt (operator action)."""
        self._halted = False

    def review(
        self,
        *,
        net_notional: Decimal,
        gross_notional: Decimal,
        equity: Decimal,
    ) -> NetRiskReview:
        """``net_notional`` = |Σ net position|·mark summed over coins;
        ``gross_notional`` = Σ|per-strategy position|·mark. Returns the uniform
        scale to apply to every target."""
        if self._high_water is None or equity > self._high_water:
            self._high_water = equity
        drawdown = 0.0
        if self._high_water > 0:
            drawdown = float((self._high_water - equity) / self._high_water)

        # Latched max-DD kill: once tripped, stays flat until reset().
        if drawdown >= self._max_drawdown:
            self._halted = True
        if self._halted:
            log.warning("netrisk.halt", drawdown=round(drawdown, 4))
            return NetRiskReview(scale=0.0, halted=True, drawdown=drawdown)

        # Scale to satisfy BOTH no-leverage on net and the gross-virtual cap.
        scale = 1.0
        if net_notional > 0:
            net_cap = equity * Decimal(str(self._max_leverage))
            if net_notional > net_cap:
                scale = min(scale, float(net_cap / net_notional))
        if gross_notional > 0:
            gross_cap = equity * Decimal(str(self._gross_cap))
            if gross_notional > gross_cap:
                scale = min(scale, float(gross_cap / gross_notional))
        if scale < 1.0:
            log.info("netrisk.scale", factor=round(scale, 4))
        return NetRiskReview(scale=scale, halted=False, drawdown=drawdown)
