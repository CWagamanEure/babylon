"""Continuous edge-decay tracking.

Alpha erosion is usually a gradual ramp, not a sharp regime break, so an
EWMA/state-space tracker is the PRIMARY detector (BOCPD, for genuine abrupt
breaks, is a deferred secondary). The tracker maintains an exponentially-weighted
estimate of a strategy's net-of-cost unit-return edge; ``decayed`` fires when that
edge falls below a threshold (the edge has gone away).
"""

from __future__ import annotations


class EdgeTracker:
    def __init__(self, *, halflife: float = 50.0) -> None:
        # EWMA smoothing: weight on the newest observation for the given half-life.
        self._alpha = 1.0 - 0.5 ** (1.0 / halflife)
        self._ewma: float | None = None
        self._n = 0

    def update(self, unit_return: float) -> None:
        if self._ewma is None:
            self._ewma = unit_return
        else:
            self._ewma += self._alpha * (unit_return - self._ewma)
        self._n += 1

    @property
    def edge(self) -> float:
        """Current EWMA edge estimate (0 before any observation)."""
        return self._ewma if self._ewma is not None else 0.0

    @property
    def n(self) -> int:
        return self._n

    def decayed(self, *, threshold: float = 0.0, min_n: int = 30) -> bool:
        """True when enough data has accrued and the tracked edge has fallen below
        ``threshold`` (default 0 — the edge has turned non-positive)."""
        return self._n >= min_n and self.edge < threshold
