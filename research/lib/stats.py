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
                     n_perm: int = 10_000, seed=None, cluster_id: Sequence | None = None):
    """One-sample symmetric-null test (H0: distribution symmetric about 0) via random sign flips.

    Good for per-unit signed markout / signed returns. Returns (point, p_two_sided, null_samples).

    `cluster_id`: optional — draw ONE sign per cluster and broadcast it to the cluster's rows.
    Whole-cluster flips preserve within-cluster dependence under the null; per-row flips on clustered
    data destroy it and make the null too well-behaved (a test can look calibrated when it isn't).
    """
    x = np.asarray(x, dtype=float)
    obs = float(stat(x))
    rng = _rng(seed)
    # draw signs per-iteration — a dense (n_perm x len(x)) matrix OOMs on large per-observation inputs
    null = np.empty(n_perm)
    if cluster_id is None:
        for b in range(n_perm):
            null[b] = stat(x * rng.choice([-1.0, 1.0], size=x.size))
    else:
        cid = np.asarray(cluster_id)
        if cid.shape[0] != x.size:
            raise ValueError("cluster_id must align 1:1 with x")
        _, inv = np.unique(cid, return_inverse=True)
        n_clusters = int(inv.max()) + 1
        for b in range(n_perm):
            s = rng.choice([-1.0, 1.0], size=n_clusters)
            null[b] = stat(x * s[inv])
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


def t_ppf(p: float, df: int) -> float:
    """Student-t quantile via the Cornish–Fisher expansion around the normal quantile (no scipy).
    Accuracy at p=0.975: ~3e-3 at df=5, <1e-3 for df ≥ 8. The expansion UNDER-shoots badly at very
    low df (df=1: 9.7 vs true 12.7 — anti-conservative), so df < 4 raises rather than silently
    narrowing a CI."""
    if df < 4:
        raise ValueError(f"t_ppf expansion is unreliable below df=4 (got df={df})")
    z = inv_norm(p)
    g1 = (z**3 + z) / 4.0
    g2 = (5*z**5 + 16*z**3 + 3*z) / 96.0
    g3 = (3*z**7 + 19*z**5 + 17*z**3 - 15*z) / 384.0
    return z + g1/df + g2/df**2 + g3/df**3


def _cluster_sandwich_var_of_mean(values: Array, cluster_id: Array) -> tuple[float, int]:
    """CR0 cluster-robust variance of the sample MEAN: V = Σ_c (Σ_{i∈c}(y_i − ȳ))² / n².
    Returns (variance, n_clusters). With each row its own cluster this is the iid sandwich."""
    y = np.asarray(values, dtype=float)
    d = y - y.mean()
    _, inv = np.unique(np.asarray(cluster_id), return_inverse=True)
    s = np.bincount(inv, weights=d)
    return float((s ** 2).sum() / y.size ** 2), int(s.size)


@dataclass
class TwoWayCI:
    point: float
    lo: float
    hi: float
    level: float
    se: float                 # the combined two-way SE actually used
    se_a: float
    se_b: float
    se_iid: float
    df: int                   # min(G_a, G_b) − 1
    floored: bool             # True if the CGM combination went non-positive and was floored


def twoway_cluster_ci(values: Sequence[float], cluster_a: Sequence, cluster_b: Sequence,
                      level: float = 0.95, method: str = "sandwich",
                      n_boot: int = 2_000, seed=None) -> TwoWayCI:
    """Two-way (Cameron–Gelbach–Miller) cluster-robust CI for the MEAN of `values`.

    SE² = SE_a² + SE_b² − SE_iid², critical value from t at min(G_a, G_b) − 1 df. This is the correct
    interval under simultaneous dependence in BOTH dimensions (e.g. wallet and week); the max of the
    two one-way CIs is NOT conservative there (probed ~80% coverage at nominal 95% — see
    audit/copy_cohort_arch/FINDINGS.md S1). Negative-variance guard: if the combination is ≤ 0,
    SE² is floored at max(SE_a², SE_b²) and `floored` is set.

    method="sandwich" (analytic CR0, default) or "bootstrap" (cluster-bootstrap variance per
    dimension, same combination).
    """
    y = np.asarray(values, dtype=float)
    point = float(y.mean())
    if method == "sandwich":
        va, ga = _cluster_sandwich_var_of_mean(y, np.asarray(cluster_a))
        vb, gb = _cluster_sandwich_var_of_mean(y, np.asarray(cluster_b))
        vi, _ = _cluster_sandwich_var_of_mean(y, np.arange(y.size))
    elif method == "bootstrap":
        rng = _rng(seed)
        def _boot_var(cid) -> tuple[float, int]:
            _, inv = np.unique(np.asarray(cid), return_inverse=True)
            clusters = np.arange(int(inv.max()) + 1)
            idx_by = [np.where(inv == c)[0] for c in clusters]
            boots = np.empty(n_boot)
            for b in range(n_boot):
                pick = rng.choice(clusters, size=clusters.size, replace=True)
                rows = np.concatenate([idx_by[c] for c in pick])
                boots[b] = y[rows].mean()
            return float(boots.var(ddof=1)), clusters.size
        va, ga = _boot_var(cluster_a)
        vb, gb = _boot_var(cluster_b)
        vi = float(y.var(ddof=1) / y.size)
    else:
        raise ValueError(f"unknown method {method!r} (sandwich|bootstrap)")
    v2 = va + vb - vi
    floored = v2 <= 0.0
    if floored:
        v2 = max(va, vb)
    df = max(1, min(ga, gb) - 1)
    tcrit = t_ppf(1 - (1 - level) / 2, df)
    se = sqrt(v2)
    return TwoWayCI(point, point - tcrit * se, point + tcrit * se, level,
                    se, sqrt(va), sqrt(vb), sqrt(vi), df, floored)


# ---------------------------------------------------------------------------
# empirical-Bayes shrinkage of per-unit means (selection statistic)
# ---------------------------------------------------------------------------
@dataclass
class EBShrink:
    unit: Array               # distinct unit ids, in np.unique order
    shrunk: Array             # B_w·ȳ_w + (1−B_w)·ȳ_pool  — the selection score
    raw_mean: Array           # ȳ_w = episode-equal-weight mean over the unit's rows
    n_eff: Array              # number of clusters per unit (NOT rows)
    tstat: Array              # ȳ_w / (σ_w/√n_eff) — the registered fallback ranking
    tau2: float               # MoM between-unit variance (after flooring)
    tau2_floored: bool        # True → τ̂²_MoM ≤ floor; ranking should fall back to `tstat`
    single_cluster: Array     # bool per unit: <2 clusters → B_w=0 (fully shrunk), tstat=nan


def eb_shrink(values: Sequence[float], unit_id: Sequence, cluster_id: Sequence,
              tau2_floor: float = 1e-12) -> EBShrink:
    """Empirical-Bayes shrunk per-unit (per-wallet) mean, dependence-aware.

    Spec (COPY_COHORT_ARCH §4, estimand frozen post-code-audit): ȳ_w = EQUAL-WEIGHT MEAN OVER THE
    UNIT'S ROWS (episodes) — identical to the forward-evaluation wallet statistic, so the selector
    optimizes the quantity the walk-forward measures. Its noise is the CR1-corrected CR0
    cluster-sandwich variance of that mean, v_w = [G_w/(G_w−1)]·Σ_c(S_c − n_c·ȳ_w)²/n_w² (clusters
    are where dependence re-enters — rows are not the information unit). B_w = τ²/(τ² + v_w);
    τ̂² by method-of-moments across units: Var_w(ȳ_w) − mean_w(v_w), floored at `tau2_floor` with a
    flag — when floored, the registered fallback ranking is `tstat`, not `shrunk` (which degenerates
    to the pool mean and makes top-K a tie-break artifact). Units with <2 clusters carry no variance
    information: B_w=0 (score = pool mean), tstat=nan, excluded from ȳ_pool and the MoM. A unit
    whose cluster residuals are exactly zero gets v_w=0 → B_w≈1 (fully trusted) — a measured-zero
    corner accepted as-is. NaNs in `values` are refused (they would silently poison every score).
    """
    y = np.asarray(values, dtype=float)
    if np.isnan(y).any():
        raise ValueError("eb_shrink: values contain NaN — filter before scoring")
    u = np.asarray(unit_id)
    units, u_inv = np.unique(u, return_inverse=True)
    # composite cluster key, integer-native (cluster ids need only be unique WITHIN a unit): pair the
    # per-unit code with a global cluster code arithmetically. Avoids np.char string ops, which sort
    # millions of 42-char wallet hashes and dominate runtime (~1h → seconds on real panels). Pass
    # INTEGER unit/cluster codes for the fast path; string inputs still work but pay the np.unique sort.
    cl_codes = np.unique(np.asarray(cluster_id), return_inverse=True)[1]
    pair = u_inv.astype(np.int64) * (int(cl_codes.max()) + 1) + cl_codes
    _, c_inv = np.unique(pair, return_inverse=True)
    c_sum = np.bincount(c_inv, weights=y)                   # cluster sums S_c
    c_cnt = np.bincount(c_inv).astype(float)                # cluster sizes n_c
    c_unit = np.full(c_sum.size, -1, dtype=int)
    c_unit[c_inv] = u_inv                                   # every row of a cluster shares the unit
    n_eff = np.bincount(c_unit, minlength=units.size).astype(float)      # clusters per unit
    n_rows = np.bincount(u_inv, minlength=units.size).astype(float)      # rows per unit
    raw = np.bincount(u_inv, weights=y, minlength=units.size) / n_rows   # episode-equal-weight mean
    resid2 = (c_sum - c_cnt * raw[c_unit]) ** 2
    ss = np.bincount(c_unit, weights=resid2, minlength=units.size)
    single = n_eff < 2
    with np.errstate(divide="ignore", invalid="ignore"):
        noise = np.where(single, np.nan,
                         ss / n_rows ** 2 * n_eff / np.maximum(n_eff - 1, 1))   # CR1·CR0 var of ȳ_w
    ok = ~single
    tau2_mom = float(raw[ok].var(ddof=1) - np.nanmean(noise[ok])) if ok.sum() > 1 else 0.0
    floored = tau2_mom <= tau2_floor
    tau2 = max(tau2_mom, tau2_floor)
    pool = float(raw[ok].mean()) if ok.any() else float("nan")
    b = np.where(ok, tau2 / (tau2 + np.where(ok, noise, np.inf)), 0.0)
    shrunk = b * raw + (1 - b) * pool
    with np.errstate(divide="ignore", invalid="ignore"):
        tstat = np.where(ok & (noise > 0), raw / np.sqrt(np.where(ok & (noise > 0), noise, np.nan)),
                         np.nan)
    return EBShrink(units, shrunk, raw, n_eff, tstat, tau2, floored, single)


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
