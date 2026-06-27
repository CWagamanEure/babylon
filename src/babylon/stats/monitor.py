"""PerformanceMonitor — maintains per-strategy + account equity curves and
computes their tail-aware metrics on demand.

Fed one mark-to-market equity sample per key per tick. Metrics are computed
lazily (the sample path is O(1); the metric fold is O(n) only when read).
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import replace

import numpy as np

from babylon.stats.metrics import Metrics, compute_metrics

ACCOUNT = "__account__"  # reserved key for the whole-book equity curve


class PerformanceMonitor:
    def __init__(self, maxlen: int = 50_000) -> None:
        self._series: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        # All-time running peak / max-drawdown, tracked incrementally OUTSIDE the
        # window — a sliding deque must not define a path-dependent risk stat (the
        # peak can scroll out, silently reading a real 25% DD as 0%).
        self._peak: dict[str, float] = {}
        self._max_dd: dict[str, float] = {}
        # Per-strategy net-of-cost UNIT returns (size-independent) — the EDGE series
        # the 'is-it-real' gate / decay tracker read. Kept SEPARATE from the sized
        # equity curves above, which are pro-cyclical and gate-contaminating.
        self._unit: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))

    def reset(self) -> None:
        """Clear all series + peaks (backtest uses this at the warmup boundary so
        warmup ticks don't pollute the measured equity curve / drawdown peak)."""
        self._series.clear()
        self._peak.clear()
        self._max_dd.clear()
        self._unit.clear()

    def sample(self, equities: dict[str, float]) -> None:
        """Append one equity value per key (strategy names + ``ACCOUNT``)."""
        for key, value in equities.items():
            if not math.isfinite(value):
                continue  # drop a bad/inf mark; never let it enter a risk stat
            self._series[key].append(value)
            peak = max(self._peak.get(key, value), value)
            self._peak[key] = peak
            dd = (peak - value) / peak if peak > 0 else 0.0
            self._max_dd[key] = max(self._max_dd.get(key, 0.0), min(max(dd, 0.0), 1.0))

    def metrics(self, key: str) -> Metrics | None:
        s = self._series.get(key)
        if s is None or len(s) < 2:
            return None
        m = compute_metrics(np.asarray(s, dtype=np.float64))
        # Override drawdown with the ALL-TIME values (the deque is windowed).
        peak, last = self._peak[key], s[-1]
        cur_dd = min(max((peak - last) / peak if peak > 0 else 0.0, 0.0), 1.0)
        return replace(m, max_drawdown=self._max_dd[key], current_drawdown=cur_dd)

    def all_metrics(self) -> dict[str, Metrics]:
        return {k: m for k in self._series if (m := self.metrics(k)) is not None}

    def equity_curve(self, key: str) -> list[float]:
        return list(self._series.get(key, ()))

    def record_unit_returns(self, unit_returns: dict[str, float]) -> None:
        """Append one net-of-cost unit return per strategy (the edge series)."""
        for strat, r in unit_returns.items():
            if math.isfinite(r):
                self._unit[strat].append(r)

    def unit_returns(self, strategy: str) -> np.ndarray:
        return np.asarray(self._unit.get(strategy, ()), dtype=np.float64)
