"""Sizer — maps (signal direction, EdgeModel, budget, price) → target position.

The strategy decides *direction*; the Sizer decides *size* via the Kelly kernel,
so sizing is uniform across strategies. Crosses the float (stats) ↔ Decimal
(execution) boundary here: edge math is float, the emitted target is Decimal.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from babylon.sizing.edge import EdgeEstimate
from babylon.sizing.kelly import kelly_fraction


class Sizer:
    def __init__(
        self, rng: np.random.Generator, *, fractional: float = 0.25, n_draws: int = 2000
    ) -> None:
        self._rng = rng
        self._fractional = fractional
        self._n_draws = n_draws

    def kelly_f(self, edge: EdgeEstimate) -> float:
        """Unsigned Kelly fraction of budget equity for this edge."""
        draws = edge.sample(self._rng, self._n_draws)
        return kelly_fraction(draws, fractional=self._fractional, shrink=edge.shrink())

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
        if f <= 0.0:
            return Decimal(0)
        notional = budget_equity * Decimal(str(f))
        size = notional / mark_price
        return size if direction > 0 else -size
