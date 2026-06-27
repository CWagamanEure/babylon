"""EdgeModel — a per-strategy estimated return distribution, decoupled from
signal logic.

Hands the Sizer a **sampler** (bootstrap draws of unit returns), not `(μ, σ)`,
so the tail-aware Kelly kernel has the full distribution. A weak prior gives the
cold-start ≈ 0 sizing; observed live returns accumulate and take over. (v1 uses
an IID bootstrap of the pooled prior+observed returns; a block bootstrap that
preserves serial dependence is the planned upgrade.)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class EdgeEstimate:
    """A resamplable return distribution + how much real data backs it.

    ``n_effective`` counts *real* observations (informative prior + live), so an
    informative backtest prior yields sizeable confidence from day one while a
    weak prior or cold start stays near zero.
    """

    draws: NDArray[np.float64]  # pooled prior + observed unit returns
    n_effective: int

    def sample(self, rng: np.random.Generator, k: int) -> NDArray[np.float64]:
        return rng.choice(self.draws, size=k, replace=True)

    def shrink(self) -> float:
        """SNR-based shrinkage in [0, 1): how much to trust the edge for sizing.

        SNR = n · mean² / var (signal-to-noise of the mean estimate); shrink =
        SNR/(1+SNR) → 0 at cold start, → 1 as the posterior concentrates.
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


class BootstrapEdgeModel:
    """Weak-prior bootstrap edge. ``prior_returns`` seed the distribution (e.g.
    from a backtest, deliberately weak); live unit returns are appended."""

    def __init__(
        self, prior_returns: list[float] | None = None, *, max_observed: int = 5000
    ) -> None:
        self._prior = np.asarray(prior_returns or [], dtype=np.float64)
        self._observed: deque[float] = deque(maxlen=max_observed)

    @classmethod
    def from_gaussian_prior(
        cls, rng: np.random.Generator, *, mean: float, std: float, n: int
    ) -> BootstrapEdgeModel:
        """Seed a (deliberately weak when n is small) prior from backtest-like
        summary stats. ``n`` controls how informative — i.e. confidence."""
        return cls(list(rng.normal(mean, std, size=n)))

    def update(self, unit_return: float) -> None:
        self._observed.append(float(unit_return))

    def estimate(self) -> EdgeEstimate:
        obs = np.asarray(self._observed, dtype=np.float64)
        draws = np.concatenate([self._prior, obs]) if self._prior.size else obs
        n_effective = self._prior.size + len(self._observed)
        if draws.size == 0:
            draws = np.zeros(1, dtype=np.float64)
        return EdgeEstimate(draws=draws, n_effective=n_effective)
