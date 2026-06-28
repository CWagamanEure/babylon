"""Sizer — maps (signal direction, EdgeModel, budget, price) → target position.

The strategy decides *direction*; the Sizer decides *size* via the Kelly kernel.
It computes Kelly over the EdgeModel's **full empirical draws** (deterministic
given edge state — no per-call bootstrap resampling, which a prior audit found
injected tick-to-tick sizing jitter and reconciler churn). Crosses the float
(stats) ↔ Decimal (execution) boundary here.
"""

from __future__ import annotations

import math
from decimal import Decimal

from babylon.sizing.edge import EdgeEstimate
from babylon.sizing.kelly import kelly_fraction


class Sizer:
    def __init__(self, *, fractional: float = 0.25, max_fraction: float = 1.0) -> None:
        self._fractional = fractional
        self._max_fraction = max_fraction

    def kelly_f(self, edge: EdgeEstimate) -> float:
        """Unsigned Kelly fraction of budget equity for this edge (deterministic)."""
        return kelly_fraction(
            edge.draws,
            fractional=self._fractional,
            shrink=edge.shrink(),
            max_fraction=self._max_fraction,
        )

    def target_size(
        self,
        *,
        edge: EdgeEstimate,
        direction: float,
        budget_equity: Decimal,
        mark_price: Decimal,
    ) -> Decimal:
        """Signed target position in coin units. 0 if no direction or no edge."""
        if direction == 0.0 or mark_price <= 0:
            return Decimal(0)
        f = self.kelly_f(edge)
        if not math.isfinite(f) or f <= 0.0:
            return Decimal(0)
        notional = budget_equity * Decimal(str(f))
        size = notional / mark_price
        return size if direction > 0 else -size


class FixedFractionSizer(Sizer):
    """Sizes by a FIXED fraction of budget equity per signalled coin, ignoring the
    EdgeModel's Kelly — for copy-following. Per the live-follow audit, per-tick Kelly
    cannot size a per-round-trip, multi-hour copy edge (it floors to $0 or pins at
    100%). Here each followed coin gets ``per_coin_fraction`` × |direction| of budget;
    the NetRiskManager caps total gross/net, so a wide book scales down uniformly
    rather than levering up. ``direction``'s sign sets long/short, its magnitude
    (the consensus strength, ≤1) scales the clip."""

    def __init__(self, *, per_coin_fraction: float = 0.1, max_fraction: float = 1.0) -> None:
        super().__init__(fractional=per_coin_fraction, max_fraction=max_fraction)
        self._per_coin = per_coin_fraction

    def target_size(
        self, *, edge: EdgeEstimate, direction: float,
        budget_equity: Decimal, mark_price: Decimal,
    ) -> Decimal:
        if direction == 0.0 or mark_price <= 0:
            return Decimal(0)
        f = min(abs(direction), 1.0) * self._per_coin
        notional = budget_equity * Decimal(str(f))
        size = notional / mark_price
        return size if direction > 0 else -size
