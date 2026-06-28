"""The 'is-it-real' gate — a bootstrap confidence bound on realized log-growth.

Gates on the SAME statistic the engine optimizes (log-growth), computed on a
strategy's **net-of-cost unit returns** (size-independent — NOT the sized equity
curve, which is pro-cyclical and sizing-contaminated). This replaces the
Deflated/Probabilistic Sharpe gate, which assumed the finite moments the fat-tail
premise denies (see ``docs/ARCHITECTURE.md``).

A **moving-block** bootstrap preserves serial dependence (vol clustering /
autocorrelation), so the confidence band isn't understated. A strategy is "real"
only if the lower confidence bound of its log-growth rate is > 0.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class GateResult:
    is_real: bool
    log_growth_lower: float  # lower CI bound of the per-period log-growth rate
    log_growth_median: float
    n: int


def _block_bootstrap(
    r: NDArray[np.float64], block: int, rng: np.random.Generator
) -> NDArray[np.float64]:
    n = r.size
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=n_blocks)
    return np.concatenate([r[s : s + block] for s in starts])[:n]


def log_growth_gate(
    unit_returns: NDArray[np.float64],
    rng: np.random.Generator,
    *,
    confidence: float = 0.95,
    n_boot: int = 1000,
    min_n: int = 30,
    block: int | None = None,
) -> GateResult:
    """True iff the lower ``confidence`` bound of bootstrapped log-growth > 0.
    Returns not-real (with the bounds) until ``min_n`` observations accumulate."""
    r = np.asarray(unit_returns, dtype=np.float64)
    n = r.size
    if n < min_n:
        return GateResult(is_real=False, log_growth_lower=0.0, log_growth_median=0.0, n=n)
    # Block ~ sqrt(n), not n^(1/3): the smaller exponent left blocks far below the
    # serial-correlation length, so the band understated uncertainty and the
    # false-positive rate climbed badly on autocorrelated (crypto-like) series.
    # Even sqrt(n) is only a partial fix — the verdict stays ADVISORY, not a guarantee.
    blk = block or max(2, min(n // 2, int(round(n ** 0.5))))
    stats = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        g = 1.0 + _block_bootstrap(r, blk, rng)
        stats[i] = float("-inf") if np.any(g <= 0) else float(np.mean(np.log(g)))
    lower = float(np.percentile(stats, (1.0 - confidence) * 100.0))
    median = float(np.median(stats))
    return GateResult(is_real=lower > 0.0, log_growth_lower=lower, log_growth_median=median, n=n)
