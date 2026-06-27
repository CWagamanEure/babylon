"""Clock abstraction so strategies are replayable.

Everything time-related in the engine goes through a `Clock`, never the wall
clock directly: `RealClock` for paper/live, `SimClock` (set by replayed data)
for backtest. This is what lets one strategy run unchanged in all three modes.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> int:
        """Current time in epoch milliseconds."""
        ...


class RealClock:
    def now(self) -> int:
        return int(time.time() * 1000)


class SimClock:
    """Backtest clock advanced explicitly by the event replayer."""

    def __init__(self, start_ms: int = 0) -> None:
        self._t = start_ms

    def now(self) -> int:
        return self._t

    def advance_to(self, t_ms: int) -> None:
        if t_ms < self._t:
            raise ValueError(f"clock cannot go backwards: {t_ms} < {self._t}")
        self._t = t_ms
