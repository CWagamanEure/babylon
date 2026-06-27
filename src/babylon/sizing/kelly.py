"""Tail- and dependence-aware Kelly kernel.

Sizes by maximizing empirical **log-growth** `E[log(1 + f·r)]` over a sample of
unit returns rather than the μ/σ² formula (fat tails / undefined variance make
that unreliable). Two guards make it survival-safe (see ``docs/ARCHITECTURE.md``):

- a **stress floor** — a synthetic worse-than-observed loss is injected before
  optimizing, because the catastrophic loss is the one the sample hasn't drawn
  yet (and a loss-free sample would otherwise imply an unbounded bet);
- the caller's **shrink** multiplier (SNR-based) plus a fixed fractional cap.

The sample should come from a block/stationary bootstrap (preserving serial
dependence); this module just consumes the draws.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def _log_growth(f: float, r: NDArray[np.float64]) -> float:
    g = 1.0 + f * r
    if np.any(g <= 0.0):
        return float("-inf")
    return float(np.mean(np.log(g)))


def optimal_log_growth_fraction(
    r: NDArray[np.float64], f_max: float, *, iters: int = 80
) -> float:
    """argmax_f in [0, f_max] of mean log(1+f·r). Concave in f → ternary search."""
    lo, hi = 0.0, f_max
    for _ in range(iters):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if _log_growth(m1, r) < _log_growth(m2, r):
            lo = m1
        else:
            hi = m2
    return (lo + hi) / 2.0


def kelly_fraction(
    returns: NDArray[np.float64],
    *,
    fractional: float = 0.25,
    shrink: float = 1.0,
    stress_mult: float = 1.5,
) -> float:
    """Survival-safe Kelly fraction (unsigned magnitude, fraction of budget).

    ``returns`` are unit returns to following the signal at unit size. The result
    is ``fractional × shrink × f*`` where ``f*`` maximizes stress-floored
    log-growth. Returns 0 when there's no positive log-growth edge.
    """
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.0

    # Stress floor: always assume a loss at least as bad as stress_mult × the
    # worst seen; if the sample never lost, assume one anyway (≈2σ) — a loss-free
    # history is the most dangerous case, not the safest.
    losses = r[r < 0.0]
    if losses.size:
        stress = float(losses.min()) * stress_mult
    else:
        stress = -max(2.0 * float(r.std()), 1e-3)
    r = np.append(r, stress)

    # Keep 1 + f·stress > 0 so log-growth stays finite.
    f_max = 0.999 / abs(stress)
    f_star = optimal_log_growth_fraction(r, f_max)
    f = fractional * shrink * f_star
    return f if f > 1e-9 else 0.0  # floor sub-nano Kelly to a clean zero
