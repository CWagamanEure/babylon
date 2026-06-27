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
