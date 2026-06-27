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
    max_fraction: float = 1.0,
) -> float:
    """Survival-safe Kelly fraction (unsigned magnitude, fraction of budget).

    ``returns`` are unit returns to following the signal at unit size. Two guards
    keep it from over-betting an under-sampled tail (a prior audit found the old
    floor let leverage scale as 1/worst-observed-loss):

    - the stress loss is **regime-anchored** to ``max(worst, 3σ)`` rather than the
      noisy minimum order statistic, so a placid sample can't imply a huge
      ``f_max``. It's injected as a single point (negligible mean shift), so it
      bounds the bet without destroying a genuine edge;
    - a **hard ``max_fraction`` cap** is the real backstop — it's what actually
      stops the blow-up, independent of the downstream per-asset / no-leverage
      clamps.
    """
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.0

    worst = -min(float(r.min()), 0.0)  # magnitude of the worst observed loss
    std = float(r.std())
    stress_mag = max(worst, 3.0 * std, 1e-3) * stress_mult
    r = np.append(r, -stress_mag)

    # Keep 1 + f·stress > 0 so log-growth stays finite.
    f_max = 0.999 / stress_mag
    f_star = optimal_log_growth_fraction(r, f_max)
    f = min(fractional * shrink * f_star, max_fraction)
    return f if f > 1e-9 else 0.0  # floor sub-nano Kelly to a clean zero
