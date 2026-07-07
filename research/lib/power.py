"""Power / MDE and the positive-control helper — the over-nulling gate's requirement #2.

A null is only earned if the pipeline is SHOWN able to recover an injected edge of the size we care about
(MDE ≤ care-about). If MDE ≫ realistic edge, the test is blind by construction → inconclusive, full stop.
These functions make that check one line.

Pure numpy + stdlib.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import ceil, sqrt
from typing import Callable, Sequence
import numpy as np

from .stats import inv_norm, _rng, Array


def mde_mean(sigma: float, n: int, alpha: float = 0.05, power: float = 0.80,
             two_sided: bool = True) -> float:
    """Minimum detectable effect for a one-sample mean at the given n, in the units of `sigma`.

    MDE = (z_{1-alpha/2} + z_{power}) * sigma / sqrt(n). Compare to the effect size you care about:
    MDE ≤ care-about ⇒ a null is informative; MDE ≫ care-about ⇒ blind by construction.
    """
    z_a = inv_norm(1 - alpha / 2) if two_sided else inv_norm(1 - alpha)
    z_b = inv_norm(power)
    return (z_a + z_b) * sigma / sqrt(n)


def min_n_for_mde(sigma: float, mde: float, alpha: float = 0.05, power: float = 0.80,
                  two_sided: bool = True) -> int:
    """Smallest n whose MDE ≤ the target effect size. Tells you how much data a powered design needs."""
    z_a = inv_norm(1 - alpha / 2) if two_sided else inv_norm(1 - alpha)
    z_b = inv_norm(power)
    return ceil(((z_a + z_b) * sigma / mde) ** 2)


@dataclass
class PowerReport:
    n: int
    sigma: float
    mde: float
    care_about: float
    powered: bool          # True iff mde <= care_about  → a null here is informative


def power_check(values: Sequence[float], care_about: float, alpha: float = 0.05,
                power: float = 0.80) -> PowerReport:
    """Convenience: estimate sigma from `values`, compute MDE, and flag whether the test is powered to
    resolve an effect of size `care_about`. Print this beside any null verdict.
    """
    x = np.asarray(values, dtype=float)
    sigma = float(x.std(ddof=1))
    mde = mde_mean(sigma, x.size, alpha, power)
    return PowerReport(x.size, sigma, mde, care_about, mde <= care_about)


def inject_positive_control(values: Array, edge: float,
                            direction: Array | None = None) -> Array:
    """Add a known synthetic edge of size `edge` to `values` (per-observation, signed by `direction`
    if given) — then re-run the pipeline and confirm it recovers `edge`. This is the positive control
    that proves the instrument isn't blind before you trust a null from it.
    """
    v = np.asarray(values, dtype=float).copy()
    if direction is None:
        return v + edge
    return v + edge * np.sign(np.asarray(direction, dtype=float))
