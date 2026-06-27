from decimal import Decimal

import numpy as np

from babylon.sizing.edge import BootstrapEdgeModel
from babylon.sizing.kelly import kelly_fraction, optimal_log_growth_fraction
from babylon.sizing.sizer import Sizer


def test_kelly_positive_edge_sizes_negative_edge_zero():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 1000)
    assert kelly_fraction(r, shrink=1.0) > 0
    assert kelly_fraction(-r, shrink=1.0) == 0.0


def test_kelly_empty_is_zero():
    assert kelly_fraction(np.array([]), shrink=1.0) == 0.0


def test_kelly_hard_cap_bounds_the_cliff():
    # Regression: a placid sample (tiny worst loss) used to imply astronomical
    # leverage (f ∝ 1/worst-loss). The hard cap must bound it.
    r = np.concatenate([np.full(999, 0.001), [-1e-4]])
    assert kelly_fraction(r, fractional=1.0, shrink=1.0, max_fraction=2.0) <= 2.0
    assert kelly_fraction(r, fractional=1.0, shrink=1.0, max_fraction=0.5) <= 0.5


def test_kelly_stress_floor_bounds_loss_free_sample():
    r = np.full(200, 0.01)  # never lost
    f = kelly_fraction(r, fractional=1.0, shrink=1.0, max_fraction=1.0)
    assert 0 < f <= 1.0


def test_kelly_shrink_scales_size():
    # Lift the cap so the linear shrink term is observable (not pinned at max).
    r = np.random.default_rng(1).normal(0.004, 0.01, 2000)
    big = kelly_fraction(r, shrink=1.0, max_fraction=100.0)
    small = kelly_fraction(r, shrink=0.2, max_fraction=100.0)
    assert 0 < small < big


def test_log_growth_argmax_is_interior():
    r = np.array([0.1, -0.05] * 100)
    f = optimal_log_growth_fraction(r, f_max=10.0)
    assert 0 < f < 10


def test_edge_cold_start_zero_informative_prior_nonzero():
    assert BootstrapEdgeModel().estimate().shrink() == 0.0  # no prior, no data
    rng = np.random.default_rng(2)
    seeded = BootstrapEdgeModel.from_gaussian_prior(
        rng, mean=0.003, std=0.005, strength=40
    )
    assert seeded.estimate().shrink() > 0.0


def test_weak_prior_strength_zero_stays_cold():
    # A prior with strength=0 shapes the distribution but adds NO confidence.
    rng = np.random.default_rng(3)
    weak = BootstrapEdgeModel(list(rng.normal(0.01, 0.05, 200)), prior_strength=0)
    assert weak.estimate().shrink() == 0.0


def test_sizer_is_deterministic_and_symmetric():
    rng = np.random.default_rng(3)
    sizer = Sizer(fractional=0.25)
    edge = BootstrapEdgeModel.from_gaussian_prior(
        rng, mean=0.003, std=0.005, strength=40
    ).estimate()
    kw = dict(edge=edge, budget_equity=Decimal(10000), mark_price=Decimal(100))
    long1 = sizer.target_size(direction=1.0, **kw)
    long2 = sizer.target_size(direction=1.0, **kw)
    short = sizer.target_size(direction=-1.0, **kw)
    flat = sizer.target_size(direction=0.0, **kw)
    assert long1 == long2  # deterministic — no per-call resampling
    assert long1 > 0 and short == -long1 and flat == 0
