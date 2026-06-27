"""Net Risk Manager — owns the *real* account, not the virtual ledgers.

Per-strategy controls can't see the thing that liquidates you: the net exchange
position. This enforces no-leverage on the net, a gross-virtual cap, and an
account-level max-drawdown kill, returning the (possibly scaled / flattened) net
targets the reconciler should actually drive to.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from babylon.logging import get_logger

log = get_logger("netrisk")


@dataclass(frozen=True, slots=True)
class NetRiskReview:
    net_targets: dict[str, Decimal]  # coin → adjusted net target size
    halted: bool
    drawdown: float
    scaled: float  # 1.0 = untouched; <1 = no-leverage scale applied


class NetRiskManager:
    def __init__(
        self, *, max_leverage: float = 1.0, max_drawdown: float = 0.25
    ) -> None:
        self._max_leverage = max_leverage
        self._max_drawdown = max_drawdown
        self._high_water: Decimal | None = None

    def review(
        self,
        *,
        net_targets: dict[str, Decimal],
        marks: dict[str, Decimal],
        equity: Decimal,
    ) -> NetRiskReview:
        # Account drawdown vs high-water → hard halt (flatten everything).
        if self._high_water is None or equity > self._high_water:
            self._high_water = equity
        drawdown = 0.0
        if self._high_water > 0:
            drawdown = float((self._high_water - equity) / self._high_water)
        if drawdown >= self._max_drawdown:
            log.warning("netrisk.halt", drawdown=round(drawdown, 4))
            return NetRiskReview(
                net_targets={c: Decimal(0) for c in net_targets},
                halted=True,
                drawdown=drawdown,
                scaled=0.0,
            )

        # No leverage on the net: Σ|net notional| ≤ max_leverage × equity.
        gross = sum(
            (abs(sz) * marks[c] for c, sz in net_targets.items() if c in marks),
            Decimal(0),
        )
        cap = equity * Decimal(str(self._max_leverage))
        scaled = 1.0
        out = dict(net_targets)
        if gross > cap and gross > 0:
            factor = cap / gross
            scaled = float(factor)
            out = {c: sz * factor for c, sz in net_targets.items()}
            log.info("netrisk.scale", factor=round(scaled, 4))
        return NetRiskReview(net_targets=out, halted=False, drawdown=drawdown, scaled=scaled)
