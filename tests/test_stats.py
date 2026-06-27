import numpy as np

from babylon.stats.metrics import (
    calmar,
    compute_metrics,
    cvar,
    drawdown_duration,
    hill_alpha,
    hit_rate,
    log_growth_total,
    max_drawdown,
    omega,
)
from babylon.stats.monitor import ACCOUNT, PerformanceMonitor


def test_log_growth_total_is_log_ratio():
    eq = np.array([100.0, 110.0])
    assert abs(log_growth_total(eq) - np.log(1.1)) < 1e-12


def test_max_drawdown_and_duration():
    eq = np.array([100.0, 120.0, 90.0, 95.0, 130.0])  # peak 120 → trough 90 = 25%
    assert abs(max_drawdown(eq) - 0.25) < 1e-12
    assert drawdown_duration(eq) == 2  # two periods below the 120 peak (90, 95)


def test_current_vs_max_drawdown():
    m = compute_metrics(np.array([100.0, 120.0, 90.0, 130.0]))
    assert m.current_drawdown == 0.0  # ended at a new peak
    assert abs(m.max_drawdown - 0.25) < 1e-12


def test_cvar_is_positive_loss():
    r = np.array([0.01, 0.02, -0.05, 0.01, -0.10, 0.03])
    assert abs(cvar(r, level=0.30) - 0.075) < 1e-9  # worst 2 of 6: mean(-.05,-.10)=.075


def test_omega_above_one_for_positive_edge():
    assert omega(np.array([0.02, 0.02, -0.01])) > 1.0
    assert omega(np.array([0.01, -0.02, -0.02])) < 1.0


def test_hit_rate_beta_binomial():
    mean, prob = hit_rate(np.array([1.0] * 8 + [-1.0] * 2))
    assert mean == 0.75 and prob > 0.9
    mean2, prob2 = hit_rate(np.array([1.0] * 2 + [-1.0] * 8))
    assert mean2 == 0.25 and prob2 < 0.1


def test_calmar_zero_when_no_drawdown():
    assert calmar(np.array([100.0, 101.0, 102.0])) == 0.0  # monotone → no DD


def test_hill_alpha_distinguishes_tail_fatness():
    rng = np.random.default_rng(0)
    thin = -np.abs(rng.normal(0, 0.01, 2000))          # ~gaussian losses
    fat = -np.abs(rng.standard_t(1.5, 2000)) * 0.01     # heavy power-law losses
    a_thin, a_fat = hill_alpha(thin), hill_alpha(fat)
    assert a_thin > a_fat > 0  # fatter tail → smaller alpha


def test_variance_reliable_flag():
    rng = np.random.default_rng(1)
    eq = 100 * np.cumprod(1 + rng.standard_t(1.2, 500) * 0.01)  # infinite-variance
    m = compute_metrics(eq)
    assert m.hill_alpha > 0 and not m.variance_reliable  # α < 4 → Sharpe untrusted


def test_nonfinite_equity_sanitized():
    # A bad/inf/nan mark must NOT poison risk fields into NaN (NaN > limit is False
    # → silently defeats a kill-switch).
    m = compute_metrics(np.array([100.0, np.inf, 110.0, np.nan, 120.0]))
    assert np.isfinite(m.max_drawdown) and np.isfinite(m.median) and m.n == 3


def test_ruin_is_negative_infinity_not_zero():
    from babylon.stats.metrics import log_growth_rate, log_growth_total

    assert log_growth_rate(np.array([100.0, 110.0, 0.0])) == float("-inf")
    assert log_growth_total(np.array([100.0, 50.0, 0.0])) == float("-inf")


def test_beta_prob_unbiased_at_large_counts():
    from babylon.stats.metrics import _prob_beta_gt_half

    assert abs(_prob_beta_gt_half(25000, 25000) - 0.5) < 0.01  # symmetric → 0.5
    assert abs(_prob_beta_gt_half(6, 6) - 0.5) < 0.01


def test_variance_reliable_fails_closed_on_unknown_tail():
    m = compute_metrics(np.array([100.0, 101.0, 102.0]))  # too little tail data → α=0
    assert m.hill_alpha == 0.0 and not m.variance_reliable  # unknown ⇒ distrust Sharpe


def test_monitor_drawdown_survives_window_eviction():
    mon = PerformanceMonitor(maxlen=3)  # tiny window; the 200 peak scrolls out
    for v in [100, 200, 150, 155, 160, 165]:
        mon.sample({"x": float(v)})
    # All-time max-DD (200→150 = 25%) must persist even though it left the window.
    assert abs(mon.metrics("x").max_drawdown - 0.25) < 1e-9


def test_monitor_tracks_per_key():
    mon = PerformanceMonitor()
    for e_a, e_acc in zip([100, 101, 102, 103], [100, 100.5, 101, 101.5], strict=True):
        mon.sample({"alpha": float(e_a), ACCOUNT: float(e_acc)})
    assert mon.metrics("alpha") is not None
    assert mon.metrics(ACCOUNT) is not None
    assert mon.metrics("alpha").log_growth_total > 0
    assert mon.metrics("missing") is None
    assert set(mon.all_metrics()) == {"alpha", ACCOUNT}
