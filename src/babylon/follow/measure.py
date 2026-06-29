"""Measurement harness for the forward experiment (docs/LIVE_FOLLOW.md §v4.2-4.3).

Turns the realized per-round-trip returns of the deployed (TOP) arm and the falsification
CONTROL arms into the pre-committed `Results`, then hands them to the immutable `decide()`.
The gated quantity is the DIRECTIONAL top−pool-mean return (NOT the neutralized series and
NOT portfolio Sharpe), with:
- a circular BLOCK bootstrap CI (round-trips are autocorrelated — the i.i.d. CI lies),
- power judged on EFFECTIVE n (integrated-autocorrelation), not nominal n,
- a maxDD bound, a depth-cap-survival flag, and a single-contributor concentration cap.

`RollingEdgeMonitor` is OBSERVE-ONLY: a live diagnostic of the rolling edge that never
feeds the gate (the gate is read once, post-min-n, by decide()).
"""

from __future__ import annotations

import numpy as np

from babylon.follow.experiment import Results


def max_drawdown(equity: np.ndarray) -> float:
    """Worst peak-to-trough fractional drawdown of an equity curve (≤ 0)."""
    e = np.asarray(equity, dtype=np.float64)
    if e.size == 0:
        return 0.0
    peak = np.maximum.accumulate(e)
    dd = (e - peak) / np.where(peak == 0, 1.0, peak)
    return float(dd.min())


def block_bootstrap_ci(
    diffs: np.ndarray, *, block: int, n_boot: int = 2000, alpha: float = 0.05, seed: int = 0,
) -> tuple[float, float]:
    """Circular block-bootstrap CI for the MEAN of a (serially correlated) per-round-trip
    series. Resampling whole blocks preserves the autocorrelation the i.i.d. CI ignores."""
    x = np.asarray(diffs, dtype=np.float64)
    n = x.size
    if n == 0:
        return (0.0, 0.0)
    block = max(1, min(block, n))
    nb = int(np.ceil(n / block))
    offs = np.arange(block)
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        starts = rng.integers(0, n, nb)
        sample = x[(starts[:, None] + offs) % n].ravel()[:n]
        means[b] = sample.mean()
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return (float(lo), float(hi))


def effective_n(x: np.ndarray, *, max_lag: int | None = None) -> int:
    """Effective sample size = n / τ, τ = integrated autocorrelation time (1 + 2Σρ_k over
    the initial positive sequence). Autocorrelated round-trips ⇒ effective n < nominal n."""
    a = np.asarray(x, dtype=np.float64)
    n = a.size
    if n < 2:
        return n
    a = a - a.mean()
    var = float(a @ a) / n
    if var <= 0:
        return n
    tau = 1.0
    for k in range(1, (max_lag or n // 4) + 1):
        if k >= n:
            break
        rho = float(a[:-k] @ a[k:]) / (n * var)
        if rho <= 0:               # stop at the first non-positive lag (initial-sequence)
            break
        tau += 2.0 * rho
    return max(1, int(n / tau))


def single_contrib_frac(contrib: dict[str, float]) -> float:
    """Max share of the aggregate (absolute) top−control spread from any one wallet/coin —
    the concentration gate (a 'spread' carried by a single name is not a strategy)."""
    tot = sum(abs(v) for v in contrib.values())
    if tot <= 0:
        return 0.0
    return max(abs(v) for v in contrib.values()) / tot


def measure(
    top: np.ndarray, control: np.ndarray, equity: np.ndarray, contrib: dict[str, float], *,
    block: int = 10, depth_capped_survives: bool, n_boot: int = 2000, seed: int = 0,
) -> Results:
    """Assemble the pre-committed Results from the realized arms. `top`/`control` are paired
    per-round-trip net returns (bps) of the deployed arm and the pool-mean control."""
    t = np.asarray(top, dtype=np.float64)
    c = np.asarray(control, dtype=np.float64)
    n = int(min(t.size, c.size))
    diffs = t[:n] - c[:n]                              # paired top − pool-mean
    lo, hi = block_bootstrap_ci(diffs, block=block, n_boot=n_boot, seed=seed)
    r = Results(
        n_effective=effective_n(diffs),
        n_nominal=n,
        top_minus_control_ci_low=lo,
        top_minus_control_ci_high=hi,
        top_vs_poolmean_significant=lo > 0.0,         # CI excludes 0 ⇒ ranking beats the pool
        maxdd=max_drawdown(equity),
        depth_capped_survives=depth_capped_survives,
        max_single_contrib_frac=single_contrib_frac(contrib),
    )
    r.validate()
    return r


class RollingEdgeMonitor:
    """OBSERVE-ONLY live diagnostic. Accumulates per-round-trip top−control diffs and
    reports a rolling mean + block-bootstrap CI. NEVER feeds the gate (decide() reads the
    frozen Results once, post-min-n) — this is just so a human can watch the edge evolve."""

    def __init__(self, block: int = 10) -> None:
        self._diffs: list[float] = []
        self._block = block

    def observe(self, top_ret: float, control_ret: float) -> None:
        self._diffs.append(top_ret - control_ret)

    def estimate(self, seed: int = 0) -> dict[str, object]:
        x = np.asarray(self._diffs, dtype=np.float64)
        if x.size < 2:
            return {"n": int(x.size), "mean": float(x.mean()) if x.size else 0.0,
                    "ci": (0.0, 0.0), "n_eff": int(x.size)}
        lo, hi = block_bootstrap_ci(x, block=self._block, seed=seed)
        return {"n": int(x.size), "mean": float(x.mean()), "ci": (lo, hi),
                "n_eff": effective_n(x)}
