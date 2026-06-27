"""Tail-aware performance metrics.

Returns are fat-tailed with sometimes-undefined variance, so the north star is
**log-growth** (the Kelly objective) and the **max-drawdown family** — both
meaningful without finite variance — not Sharpe. Sharpe/Sortino are reported but
flagged unreliable when the Hill tail index α < 4 (kurtosis undefined). See
``docs/ARCHITECTURE.md`` (Measurement & statistics).

All functions are pure and operate on an **equity curve** (array of equity values
over time) or its per-period simple returns. Money is float here (the stats/numpy
domain); the execution path stays Decimal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]


def simple_returns(equity: Array) -> Array:
    """Per-period simple returns r_t = e_t/e_{t-1} − 1 (needs ≥2 points, e>0)."""
    if equity.size < 2:
        return np.empty(0, dtype=np.float64)
    return equity[1:] / equity[:-1] - 1.0


def log_growth_total(equity: Array) -> float:
    """Total realized log-growth log(e_end / e_start)."""
    if equity.size < 2 or equity[0] <= 0 or equity[-1] <= 0:
        return 0.0
    return float(np.log(equity[-1] / equity[0]))


def log_growth_rate(equity: Array) -> float:
    """Mean per-period log-growth — the realized growth rate (Kelly objective)."""
    r = simple_returns(equity)
    g = 1.0 + r
    if r.size == 0 or np.any(g <= 0):
        return 0.0
    return float(np.mean(np.log(g)))


def drawdown_series(equity: Array) -> Array:
    """Fractional drawdown from the running peak at each point (0..1)."""
    if equity.size == 0:
        return np.empty(0, dtype=np.float64)
    peak = np.maximum.accumulate(equity)
    return np.where(peak > 0, (peak - equity) / peak, 0.0)


def max_drawdown(equity: Array) -> float:
    dd = drawdown_series(equity)
    return float(dd.max()) if dd.size else 0.0


def current_drawdown(equity: Array) -> float:
    dd = drawdown_series(equity)
    return float(dd[-1]) if dd.size else 0.0


def drawdown_duration(equity: Array) -> int:
    """Longest run (in periods) spent below a prior peak."""
    dd = drawdown_series(equity)
    longest = run = 0
    for x in dd:
        run = run + 1 if x > 0 else 0
        longest = max(longest, run)
    return longest


def calmar(equity: Array) -> float:
    """Total return ÷ max drawdown (∞-guarded). Higher is better."""
    mdd = max_drawdown(equity)
    if mdd <= 0:
        return 0.0
    total_return = float(equity[-1] / equity[0] - 1.0) if equity[0] > 0 else 0.0
    return total_return / mdd


def ulcer_index(equity: Array) -> float:
    """RMS drawdown (in %), penalising depth AND duration of underwater periods."""
    dd = drawdown_series(equity)
    return float(np.sqrt(np.mean((dd * 100.0) ** 2))) if dd.size else 0.0


def cvar(returns: Array, level: float = 0.05) -> float:
    """Expected shortfall: mean of the worst ``level`` fraction of returns,
    returned as a POSITIVE loss magnitude (0 if no data)."""
    if returns.size == 0:
        return 0.0
    k = max(1, int(math.ceil(level * returns.size)))
    worst = np.sort(returns)[:k]
    return float(-worst.mean())


def omega(returns: Array, threshold: float = 0.0) -> float:
    """Probability-weighted gains/losses ratio about ``threshold`` (distribution-
    free). > 1 means gains outweigh losses; ∞ if no losses."""
    if returns.size == 0:
        return 0.0
    excess = returns - threshold
    gains = excess[excess > 0].sum()
    losses = -excess[excess < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 1.0
    return float(gains / losses)


def median_return(returns: Array) -> float:
    return float(np.median(returns)) if returns.size else 0.0


def mad(returns: Array) -> float:
    """Median absolute deviation — robust scale (exists even when variance doesn't)."""
    if returns.size == 0:
        return 0.0
    return float(np.median(np.abs(returns - np.median(returns))))


def hill_alpha(returns: Array, tail_frac: float = 0.1) -> float:
    """Hill estimate of the (left/loss) tail index α. Smaller α = fatter tail;
    α ≤ 2 ⇒ infinite variance. Noisy on small samples — treat as a regime hint.
    Returns 0 if too little tail data."""
    losses = -returns[returns < 0]
    losses = losses[losses > 0]
    if losses.size < 10:
        return 0.0
    k = max(2, int(tail_frac * losses.size))
    top = np.sort(losses)[-k:]  # k largest losses
    thresh = top[0]
    if thresh <= 0:
        return 0.0
    logs = np.log(top / thresh)
    m = float(logs[1:].mean()) if logs.size > 1 else 0.0
    return 1.0 / m if m > 0 else 0.0


def hit_rate(returns: Array, prior_a: float = 1.0, prior_b: float = 1.0) -> tuple[float, float]:
    """Beta-Binomial directional edge from the SIGN of returns (immune to tail
    size). Returns (posterior mean win-rate, P(win-rate > 0.5))."""
    if returns.size == 0:
        return 0.5, 0.5
    wins = int(np.sum(returns > 0))
    losses = int(np.sum(returns < 0))
    a, b = prior_a + wins, prior_b + losses
    mean = a / (a + b)
    return mean, _prob_beta_gt_half(a, b)


def sharpe(returns: Array) -> float:
    if returns.size < 2:
        return 0.0
    sd = float(np.std(returns, ddof=1))
    return float(np.mean(returns)) / sd if sd > 0 else 0.0


def sortino(returns: Array) -> float:
    if returns.size < 2:
        return 0.0
    downside = returns[returns < 0]
    dd = float(np.sqrt(np.mean(downside**2))) if downside.size else 0.0
    return float(np.mean(returns)) / dd if dd > 0 else 0.0


def _prob_beta_gt_half(a: float, b: float) -> float:
    """P(p > 0.5) for p ~ Beta(a, b), via stable grid integration (no scipy)."""
    p = np.linspace(1e-6, 1.0 - 1e-6, 2001)
    logpdf = (a - 1.0) * np.log(p) + (b - 1.0) * np.log1p(-p)
    logpdf -= logpdf.max()
    pdf = np.exp(logpdf)
    pdf /= pdf.sum()
    return float(pdf[p > 0.5].sum())


@dataclass(frozen=True, slots=True)
class Metrics:
    n: int
    log_growth_total: float
    log_growth_rate: float
    max_drawdown: float
    current_drawdown: float
    drawdown_duration: int
    calmar: float
    ulcer: float
    cvar5: float
    omega: float
    median: float
    mad: float
    hill_alpha: float
    hit_rate: float
    hit_prob_positive: float
    sharpe: float
    sortino: float

    @property
    def variance_reliable(self) -> bool:
        """Sharpe/Sortino trustworthy only when the tail index supports finite
        kurtosis (α > 4). When False, prefer log-growth / Calmar / CVaR."""
        return self.hill_alpha == 0.0 or self.hill_alpha > 4.0


def compute_metrics(equity: Array) -> Metrics:
    r = simple_returns(equity)
    hr, hp = hit_rate(r)
    return Metrics(
        n=int(equity.size),
        log_growth_total=log_growth_total(equity),
        log_growth_rate=log_growth_rate(equity),
        max_drawdown=max_drawdown(equity),
        current_drawdown=current_drawdown(equity),
        drawdown_duration=drawdown_duration(equity),
        calmar=calmar(equity),
        ulcer=ulcer_index(equity),
        cvar5=cvar(r, 0.05),
        omega=omega(r),
        median=median_return(r),
        mad=mad(r),
        hill_alpha=hill_alpha(r),
        hit_rate=hr,
        hit_prob_positive=hp,
        sharpe=sharpe(r),
        sortino=sortino(r),
    )
