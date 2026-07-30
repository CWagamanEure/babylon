from __future__ import annotations

import numpy as np

from research.studies.copy_cohort.nested_t_filter import (
    kalman_score,
    lagged_r_vol,
    q_ratio,
    topk,
)


def test_q0_is_ordinary_t_with_gaps_and_terminal_gap() -> None:
    x = np.array([2.0, -1.0, 4.0, 3.0, 0.5])
    day = np.array([10, 11, 15, 20, 22])
    expected = x.mean() / (x.std(ddof=1) / np.sqrt(x.size))
    got = kalman_score(x, day, 40, np.ones(x.size), half_life=None)
    assert np.isclose(got, expected, atol=1e-12, rtol=1e-12)


def test_terminal_prediction_penalizes_stale_state() -> None:
    x = np.array([1.0, 1.5, 2.0, 2.5])
    day = np.array([1, 2, 3, 4])
    fresh = kalman_score(x, day, 4, np.ones(4), half_life=60)
    stale = kalman_score(x, day, 40, np.ones(4), half_life=60)
    assert stale < fresh


def test_half_life_120_has_less_process_noise() -> None:
    assert 0 < q_ratio(120) < q_ratio(60)


def test_first_r_multiplier_does_not_change_frozen_initial_state() -> None:
    x = np.array([1.0, 2.0, 3.0])
    day = np.array([1, 2, 3])
    a = kalman_score(x, day, 3, np.array([1.0, 2.0, 2.0]), half_life=60)
    b = kalman_score(x, day, 3, np.array([4.0, 2.0, 2.0]), half_life=60)
    assert a == b


def test_first_extreme_shock_uses_minimum_not_fixed_reset() -> None:
    x = np.r_[-1_000.0, np.zeros(19)]
    day = np.arange(1, 21)
    shock = np.zeros(20, bool)
    shock[0] = True
    shocked = kalman_score(x, day, 20, np.ones(20), half_life=60, shock=shock)
    ordinary = kalman_score(x, day, 20, np.ones(20), half_life=60)
    assert shocked != ordinary


def test_first_liquidation_resets_then_consumes_positive_observation() -> None:
    x = np.array([10.0, -1.0])
    day = np.array([1, 2])
    shock = np.array([True, False])
    r = float(np.var(x, ddof=1))
    q = r * q_ratio(60)
    theta, p = min(x[0], -3 * np.sqrt(r)), r
    gain = p / (p + r)
    theta, p = theta + gain * (x[0] - theta), p * (1 - gain)
    p += q
    gain = p / (p + r)
    theta, p = theta + gain * (x[1] - theta), p * (1 - gain)
    expected = theta / np.sqrt(p)
    got = kalman_score(x, day, 2, np.ones(2), half_life=60, shock=shock)
    assert np.isclose(got, expected)


def test_lagged_r_vol_never_uses_current_day() -> None:
    months = [202601]
    rv = {
        20260101: 1.0,
        20260102: 1.0,
        20260103: 1.0,
        20260104: 1.0,
        20260105: 1.0,
        20260106: 4.0,
    }
    out = lagged_r_vol(months, rv)
    assert out[20260106] == 1.0
    assert out[20260107] == 4.0


def test_topk_deterministic_wallet_tie_break() -> None:
    wallets = np.array([f"w{i:02d}" for i in range(35)])
    score = np.ones(35)
    assert topk(wallets, score) == wallets[:30].tolist()
