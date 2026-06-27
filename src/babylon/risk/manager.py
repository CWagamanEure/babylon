"""Per-strategy risk limits (independent of strategy logic)."""

from __future__ import annotations

from decimal import Decimal


class RiskManager:
    def __init__(self, per_asset_cap: float = 0.5) -> None:
        # Max |notional| in one asset for one strategy, as a fraction of its budget.
        self._per_asset_cap = per_asset_cap

    def clamp_target(
        self, size: Decimal, *, mark: Decimal, budget_equity: Decimal
    ) -> Decimal:
        if mark <= 0:
            return Decimal(0)
        max_size = (budget_equity * Decimal(str(self._per_asset_cap))) / mark
        if size > max_size:
            return max_size
        if size < -max_size:
            return -max_size
        return size
