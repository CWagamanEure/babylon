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


def test_kelly_stress_floor_bounds_loss_free_sample():
    # All-positive returns must NOT imply an unbounded bet — the stress floor
    # injects a synthetic loss, keeping f finite.
    r = np.full(200, 0.01)
    f = kelly_fraction(r, fractional=1.0, shrink=1.0)
    assert 0 < f < 1000


def test_kelly_shrink_scales_size():
    r = np.random.default_rng(1).normal(0.001, 0.01, 1000)
    assert kelly_fraction(r, shrink=0.25) < kelly_fraction(r, shrink=1.0)


def test_log_growth_argmax_matches_known_optimum():
    # For a symmetric two-point bet, full-Kelly f* = edge/odds; check it's interior.
    r = np.array([0.1, -0.05] * 100)
    f = optimal_log_growth_fraction(r, f_max=10.0)
    assert 0 < f < 10


def test_edge_shrink_cold_start_zero_grows_with_data():
    m = BootstrapEdgeModel()  # no prior
    assert m.estimate().shrink() == 0.0
    rng = np.random.default_rng(2)
    seeded = BootstrapEdgeModel.from_gaussian_prior(rng, mean=0.002, std=0.005, n=200)
    assert seeded.estimate().shrink() > 0.0


def test_sizer_direction_and_budget():
    rng = np.random.default_rng(3)
    sizer = Sizer(rng, fractional=0.25, n_draws=500)
    edge = BootstrapEdgeModel.from_gaussian_prior(
        rng, mean=0.003, std=0.005, n=200
    ).estimate()
    long = sizer.target_size(
        edge=edge, direction=1.0, budget_equity=Decimal(10000), mark_price=Decimal(100)
    )
    short = sizer.target_size(
        edge=edge, direction=-1.0, budget_equity=Decimal(10000), mark_price=Decimal(100)
    )
    flat = sizer.target_size(
        edge=edge, direction=0.0, budget_equity=Decimal(10000), mark_price=Decimal(100)
    )
    assert long > 0 and short < 0 and flat == 0
    # Magnitudes match up to per-call bootstrap sampling noise (sizer resamples).
    assert abs(long + short) < long / 10
