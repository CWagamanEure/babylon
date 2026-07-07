"""Null models, multiplicity control, and clustered/blocked bootstrap CIs.

These are the false-positive AND false-negative controls the over-nulling gate needs. Every function
returns a POINT ESTIMATE alongside any p-value / CI — never a bare p-value, by design (see `CLAUDE.md`:
"a p > 0.05 is NOT evidence of absence"). Pass an explicit `seed` for reproducibility.

Pure numpy + stdlib. All bootstrap/permutation functions take a `seed` (or an `np.random.Generator`).
"""
from __future__ import annotations
from dataclasses import dataclass
from math import comb, erf, sqrt
from typing import Callable, Sequence
import warnings
import numpy as np

Array = np.ndarray

# Reproducibility: a reported CI/p-value must be recomputable from code+commit (see CLAUDE.md). If a
# caller passes no seed, fall back to this fixed constant (so the result IS reproducible) and warn ONCE
# that they should pass their study's own seed for independent draws.
DEFAULT_SEED = 0
_warned_unseeded = False


# ---------------------------------------------------------------------------
# small helpers (scipy-free)
# ---------------------------------------------------------------------------
def _rng(seed) -> np.random.Generator:
    global _warned_unseeded
    if isinstance(seed, np.random.Generator):
        return seed
    if seed is None:
        if not _warned_unseeded:
            warnings.warn(
                "research.lib.stats: no seed passed -> using DEFAULT_SEED for a reproducible result; "
                "pass your study seed for independent draws.", stacklevel=3)
            _warned_unseeded = True
        seed = DEFAULT_SEED
    return np.random.default_rng(seed)


def norm_cdf(z: float) -> float:
    """Standard-normal CDF via erf (no scipy)."""
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def inv_norm(p: float) -> float:
    """Standard-normal quantile (Acklam's rational approximation; abs err < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = sqrt(-2 * np.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = sqrt(-2 * np.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ---------------------------------------------------------------------------
# multiplicity control
# ---------------------------------------------------------------------------
def bh_fdr(pvals: Sequence[float], alpha: float = 0.05):
    """Benjamini-Hochberg. Returns (rejected: bool array, qvalues: array) in the input order.

    `qvalues[i]` is the smallest FDR level at which test i is rejected (monotone-adjusted p).
    """
    p = np.asarray(pvals, dtype=float)
    n = p.size
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]      # enforce monotonicity
    q = np.clip(q, 0, 1)
    qvals = np.empty(n)
    qvals[order] = q
    return qvals <= alpha, qvals


# ---------------------------------------------------------------------------
# cross-unit sign test (the over-null gate's requirement #3)
# ---------------------------------------------------------------------------
@dataclass
class SignTest:
    n_pos: int
    n_effective: int          # excludes exact zeros
    p_value: float            # two-sided, exact binomial at 0.5
    frac_pos: float


def sign_test(unit_stats: Sequence[float]) -> SignTest:
    """Two-sided exact binomial sign test: are N/N independent units leaning the same way?

    This is the combination test the over-nulling gate mandates BEFORE declaring a null — individual
    cells are underpowered, but many units leaning one direction is significant.
    """
    x = np.asarray(unit_stats, dtype=float)
    x = x[x != 0.0]
    n = x.size
    k = int((x > 0).sum())
    if n == 0:
        return SignTest(0, 0, 1.0, float("nan"))
    # two-sided exact p = P(|Bin(n,0.5) - n/2| >= |k - n/2|)
    d = abs(k - n / 2)
    lo, hi = int(np.ceil(n / 2 - d)), int(np.floor(n / 2 + d))
    tail = sum(comb(n, i) for i in range(0, lo + 1)) + sum(comb(n, i) for i in range(hi, n + 1))
    p = min(1.0, tail / (2 ** n))
    return SignTest(k, n, p, k / n)


# ---------------------------------------------------------------------------
# permutation / sign-flip null
# ---------------------------------------------------------------------------
def sign_flip_pvalue(x: Sequence[float], stat: Callable[[Array], float] = np.mean,
                     n_perm: int = 10_000, seed=None):
    """One-sample symmetric-null test (H0: distribution symmetric about 0) via random sign flips.

    Good for per-unit signed markout / signed returns. Returns (point, p_two_sided, null_samples).
    """
    x = np.asarray(x, dtype=float)
    obs = float(stat(x))
    rng = _rng(seed)
    # draw signs per-iteration — a dense (n_perm x len(x)) matrix OOMs on large per-observation inputs
    null = np.empty(n_perm)
    for b in range(n_perm):
        null[b] = stat(x * rng.choice([-1.0, 1.0], size=x.size))
    p = (np.sum(np.abs(null) >= abs(obs)) + 1) / (n_perm + 1)
    return obs, float(p), null


def label_permutation_pvalue(values: Sequence[float], group: Sequence[int],
                             n_perm: int = 10_000, seed=None):
    """Two-group difference-in-means permutation test. group is 0/1. Returns (diff, p, null)."""
    v = np.asarray(values, dtype=float)
    g = np.asarray(group).astype(bool)
    obs = v[g].mean() - v[~g].mean()
    rng = _rng(seed)
    null = np.empty(n_perm)
    for b in range(n_perm):
        gp = rng.permutation(g)
        null[b] = v[gp].mean() - v[~gp].mean()
    p = (np.sum(np.abs(null) >= abs(obs)) + 1) / (n_perm + 1)
    return float(obs), float(p), null


# ---------------------------------------------------------------------------
# clustered / blocked bootstrap CIs (correlated observations)
# ---------------------------------------------------------------------------
@dataclass
class BootCI:
    point: float
    lo: float
    hi: float
    level: float


def cluster_bootstrap_ci(cluster_id: Sequence, values: Sequence[float],
                         statfn: Callable[[Array], float] = np.mean,
                         n_boot: int = 5_000, level: float = 0.95, seed=None) -> BootCI:
    """Resample whole CLUSTERS with replacement (e.g. wallets, coins, weeks) — the right CI when rows
    within a cluster are correlated. `statfn` is applied to the pooled resampled values.
    """
    cid = np.asarray(cluster_id)
    val = np.asarray(values, dtype=float)
    clusters = np.unique(cid)
    idx_by_cluster = {c: np.where(cid == c)[0] for c in clusters}
    rng = _rng(seed)
    point = float(statfn(val))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(clusters, size=clusters.size, replace=True)
        rows = np.concatenate([idx_by_cluster[c] for c in pick])
        boots[b] = statfn(val[rows])
    a = (1 - level) / 2
    return BootCI(point, float(np.quantile(boots, a)), float(np.quantile(boots, 1 - a)), level)


def moving_block_bootstrap_ci(series: Sequence[float], statfn: Callable[[Array], float] = np.mean,
                              block_len: int | None = None, n_boot: int = 5_000,
                              level: float = 0.95, seed=None) -> BootCI:
    """Moving-block bootstrap for a time-ordered 1D series (preserves short-range dependence).
    Default block_len ~ n**(1/3). Use for autocorrelated equity-curve / daily-PnL statistics.
    """
    x = np.asarray(series, dtype=float)
    n = x.size
    L = block_len or max(1, int(round(n ** (1 / 3))))
    L = max(1, min(L, n))                                     # clamp: a block can't exceed the series
    n_blocks = int(np.ceil(n / L))
    starts_hi = n - L + 1
    rng = _rng(seed)
    point = float(statfn(x))
    boots = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, starts_hi, size=n_blocks)
        sample = np.concatenate([x[s:s + L] for s in starts])[:n]
        boots[b] = statfn(sample)
    a = (1 - level) / 2
    return BootCI(point, float(np.quantile(boots, a)), float(np.quantile(boots, 1 - a)), level)
