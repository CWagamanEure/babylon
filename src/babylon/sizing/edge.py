"""EdgeModel — a per-strategy estimated return distribution, decoupled from
signal logic.

Hands the Sizer the **full empirical distribution** of unit returns (prior +
observed) so the tail-aware Kelly kernel sees the whole shape, plus a `shrink`
confidence.

Confidence is driven by a **pseudo-count** that is deliberately separate from the
number of bootstrap draws (a prior audit found that letting the prior's *draw
count* set confidence let callers fabricate day-one certainty). A weak prior sets
`prior_strength=0` → cold-start sizing ≈ 0; an informative backtest prior sets a
deliberate, bounded `prior_strength`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class EdgeEstimate:
    """The empirical return distribution + how much real confidence backs it."""

    draws: NDArray[np.float64]  # pooled prior + observed unit returns
    n_effective: int  # confidence pseudo-count (prior_strength + observed count)

    def shrink(self) -> float:
        """SNR-based shrinkage in [0, 1): how much to trust the edge for sizing.

        SNR = n · mean² / var; shrink = SNR/(1+SNR) → 0 at cold start, → 1 as the
        posterior concentrates.
        """
        if self.n_effective == 0:
            return 0.0
        var = float(np.var(self.draws))
        if var <= 0.0:
            return 0.0
        mean = float(np.mean(self.draws))
        snr = self.n_effective * mean * mean / var
        return snr / (1.0 + snr)


class EdgeModel(Protocol):
    def estimate(self) -> EdgeEstimate: ...
    def update(self, unit_return: float) -> None: ...
    def to_state(self) -> dict[str, Any]: ...
    def from_state(self, st: dict[str, Any]) -> None: ...


class BootstrapEdgeModel:
    """Empirical edge from pooled prior + observed unit returns.

    ``prior_returns`` shape the distribution; ``prior_strength`` (default 0) is the
    confidence pseudo-count the prior contributes — set it > 0 only for a prior
    you deliberately trust (e.g. a validated backtest)."""

    def __init__(
        self,
        prior_returns: list[float] | None = None,
        *,
        prior_strength: int = 0,
        max_observed: int = 5000,
    ) -> None:
        self._prior = np.asarray(prior_returns or [], dtype=np.float64)
        self._prior_strength = prior_strength
        self._observed: deque[float] = deque(maxlen=max_observed)

    @classmethod
    def from_gaussian_prior(
        cls,
        rng: np.random.Generator,
        *,
        mean: float,
        std: float,
        draws: int = 200,
        strength: int = 20,
    ) -> BootstrapEdgeModel:
        """Seed a prior from backtest-like summary stats. ``draws`` sets the
        distribution resolution; ``strength`` is the (deliberate, bounded) day-one
        confidence pseudo-count — NOT tied to ``draws``."""
        return cls(list(rng.normal(mean, std, size=draws)), prior_strength=strength)

    def update(self, unit_return: float) -> None:
        self._observed.append(float(unit_return))

    def estimate(self) -> EdgeEstimate:
        obs = np.asarray(self._observed, dtype=np.float64)
        draws = np.concatenate([self._prior, obs]) if self._prior.size else obs
        n_effective = self._prior_strength + len(self._observed)
        if draws.size == 0:
            draws = np.zeros(1, dtype=np.float64)
        return EdgeEstimate(draws=draws, n_effective=n_effective)

    # --- durable state ------------------------------------------------------
    # The prior draws are regenerated from the seed (NOT journaled); only the
    # observed returns + strength are durable. ``from_state`` restores them onto
    # an already-seeded model, rebuilding the deque with its maxlen.

    def to_state(self) -> dict[str, Any]:
        return {
            "prior_strength": self._prior_strength,
            "maxlen": self._observed.maxlen,
            "observed": list(self._observed),
        }

    def from_state(self, st: dict[str, Any]) -> None:
        self._prior_strength = int(st["prior_strength"])
        self._observed = deque(st["observed"], maxlen=st["maxlen"])


class FrozenEdge:
    """A FROZEN edge — a fixed prior distribution that NEVER updates from forward
    returns. For the live-follow OOS validator: sizing is frozen at T0 so the forward
    measurement can't be contaminated by online adaptation (docs/LIVE_FOLLOW.md §9b).
    Satisfies the EdgeModel Protocol; ``update`` is a deliberate no-op."""

    def __init__(self, draws: list[float], n_effective: int) -> None:
        self._draws = np.asarray(draws or [0.0], dtype=np.float64)
        self._n = int(n_effective)

    @classmethod
    def from_gaussian(
        cls, rng: np.random.Generator, *, mean: float, std: float,
        strength: int = 20, draws: int = 400,
    ) -> FrozenEdge:
        return cls(list(rng.normal(mean, std, size=draws)), strength)

    def estimate(self) -> EdgeEstimate:
        return EdgeEstimate(draws=self._draws, n_effective=self._n)

    def update(self, unit_return: float) -> None:
        return None  # frozen — forward returns never reshape sizing

    def to_state(self) -> dict[str, Any]:
        return {"draws": self._draws.tolist(), "n": self._n}

    def from_state(self, st: dict[str, Any]) -> None:
        self._draws = np.asarray(st["draws"], dtype=np.float64)
        self._n = int(st["n"])
