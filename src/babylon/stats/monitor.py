"""PerformanceMonitor — maintains per-strategy + account equity curves and
computes their tail-aware metrics on demand.

Fed one mark-to-market equity sample per key per tick. Metrics are computed
lazily (the sample path is O(1); the metric fold is O(n) only when read).
"""

from __future__ import annotations

from collections import defaultdict, deque

import numpy as np

from babylon.stats.metrics import Metrics, compute_metrics

ACCOUNT = "__account__"  # reserved key for the whole-book equity curve


class PerformanceMonitor:
    def __init__(self, maxlen: int = 50_000) -> None:
        self._series: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))

    def sample(self, equities: dict[str, float]) -> None:
        """Append one equity value per key (strategy names + ``ACCOUNT``)."""
        for key, value in equities.items():
            self._series[key].append(value)

    def metrics(self, key: str) -> Metrics | None:
        s = self._series.get(key)
        if s is None or len(s) < 2:
            return None
        return compute_metrics(np.asarray(s, dtype=np.float64))

    def all_metrics(self) -> dict[str, Metrics]:
        return {k: m for k in self._series if (m := self.metrics(k)) is not None}

    def equity_curve(self, key: str) -> list[float]:
        return list(self._series.get(key, ()))
