from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path

import duckdb
import numpy as np

from research.studies.copy_cohort.adaptive_rq_filter import (
    CARE_BP,
    K60,
    KSLOW,
    PROFILE_ID,
    Q60,
    QSLOW,
    ContrastRows,
    FoldScores,
    _arm_coin_weights,
    average_tie_percentile,
    cache_identity_payload,
    compare_factor,
    context_rv_catalog,
    exact_hhi,
    factor_bootstrap,
    kalman_state_score,
    robust_observations,
    top5_wallet_abs_contribution_share,
    validate_profile,
)
from research.studies.copy_cohort.dynamic_t_quality import normalized_x
from research.studies.copy_cohort.filtered_quality import _sha256_json


def test_random_walk_stationary_gain_is_literal_k60():
    predicted = K60 + Q60
    assert math.isclose(predicted / (predicted + 1.0), K60, abs_tol=1e-15)
    predicted_slow = KSLOW + QSLOW
    assert math.isclose(predicted_slow / (predicted_slow + 1.0), KSLOW, abs_tol=1e-15)
    assert KSLOW < K60


def test_qslow_and_r4_have_identical_theta_gain_and_ranking_scale():
    ordinal = np.array([10, 11, 20, 40], np.int64)
    y = np.array([1.0, -0.5, 2.0, 0.25])
    slow = kalman_state_score(
        ordinal,
        y,
        np.ones(4),
        start_ordinal=10,
        end_ordinal=50,
        q=QSLOW,
        p0=KSLOW,
    )
    r4 = kalman_state_score(
        ordinal,
        y,
        np.full(4, 4.0),
        start_ordinal=10,
        end_ordinal=50,
        q=Q60,
        p0=4.0 * KSLOW,
    )
    assert math.isclose(slow[1], r4[1], rel_tol=0, abs_tol=1e-13)
    assert math.isclose(r4[2], 4.0 * slow[2], rel_tol=0, abs_tol=1e-13)
    assert math.isclose(r4[0], 0.5 * slow[0], rel_tol=0, abs_tol=1e-13)


def test_larger_r_reduces_applied_innovation():
    ordinal = np.array([100], np.int64)
    low = kalman_state_score(
        ordinal,
        np.array([2.0]),
        np.array([1.0]),
        start_ordinal=100,
        end_ordinal=100,
        q=Q60,
        p0=K60,
    )
    high = kalman_state_score(
        ordinal,
        np.array([2.0]),
        np.array([4.0]),
        start_ordinal=100,
        end_ordinal=100,
        q=Q60,
        p0=K60,
    )
    assert 0 < high[1] < low[1]


def test_shock_reset_occurs_before_same_day_update():
    ordinal = np.array([10, 11], np.int64)
    y = np.array([5.0, -5.0])
    ordinary = kalman_state_score(
        ordinal,
        y,
        np.ones(2),
        start_ordinal=10,
        end_ordinal=11,
        q=Q60,
        p0=K60,
    )
    reset = kalman_state_score(
        ordinal,
        y,
        np.ones(2),
        start_ordinal=10,
        end_ordinal=11,
        q=Q60,
        p0=K60,
        shock=np.array([False, True]),
    )
    assert reset[1] < ordinary[1]
    assert reset[2] > ordinary[2]


def test_robust_observation_preserves_positive_location():
    y, scale = robust_observations(np.array([9.0, 10.0, 11.0]))
    assert scale > 0
    assert np.all(y > 0)


def test_average_tie_percentile():
    got = average_tie_percentile(np.array([1.0, 2.0, 2.0, 4.0]))
    assert np.allclose(got, [0.125, 0.5, 0.5, 0.875])


def _scores_for_weight_test() -> FoldScores:
    wallets = np.array([f"w{i:03d}" for i in range(40)])
    eligible = {
        arm: np.ones(40, bool)
        for arm in (
            "KF60_BASE",
            "KF60_R_BREADTH",
            "KF60_R_VOL",
            "KF60_Q_SLOW",
            "KF60_BLOWUP",
            "KF60_ALL",
            "EW60",
            "TSTAT_COMMON",
        )
    }
    raw = {arm: np.linspace(-0.975, 0.975, 40) for arm in eligible}
    score = {arm: v.copy() for arm, v in raw.items()}
    return FoldScores(wallets, score, raw, eligible, np.zeros(40, bool), {})


def test_quarantined_wallet_is_removed_before_centering_and_exactly_zero():
    scores = _scores_for_weight_test()
    active = set(scores.wallets)
    excluded = {"w000", "w039"}
    weights = _arm_coin_weights(scores, "KF60_ALL", active, excluded)
    assert weights is not None
    assert excluded.isdisjoint(weights)
    assert math.isclose(sum(weights.values()), 0.0, abs_tol=1e-12)
    assert math.isclose(sum(abs(v) for v in weights.values()), 0.25, abs_tol=1e-12)


def _write_ctx(path: Path, *, missing_target: bool = False) -> None:
    path.parent.mkdir(parents=True)
    con = duckdb.connect()
    day_start = 1_735_689_600_000  # 2025-01-01 UTC
    where = "WHERE NOT (coin='ETH' AND i=100)" if missing_target else ""
    con.execute(f"""COPY (
      SELECT coin,{day_start}+i*300000 AS ts,
             100.0+0.01*i+CASE coin WHEN 'BTC' THEN 0 WHEN 'ETH' THEN 1
               WHEN 'SOL' THEN 2 ELSE 3 END AS mid_px
      FROM UNNEST(['BTC','ETH','SOL','HYPE']) t(coin),range(288) r(i)
      {where}
    ) TO '{path.as_posix()}' (FORMAT PARQUET)""")
    con.close()


def test_exact_context_rv_lattice_accepts_complete_day(tmp_path):
    path = tmp_path / "day=20250101" / "ctx.parquet"
    _write_ctx(path)
    rv, invalid = context_rv_catalog([path])
    assert 20250101 in rv and rv[20250101] > 0
    assert invalid == {}


def test_exact_context_rv_lattice_rejects_missing_target(tmp_path):
    path = tmp_path / "day=20250101" / "ctx.parquet"
    _write_ctx(path, missing_target=True)
    rv, invalid = context_rv_catalog([path])
    assert rv == {}
    assert 20250101 in invalid


def test_factor_bootstrap_is_daily_sum_not_row_mean_and_fixed_injection_varies():
    wallets = np.array([f"w{i}" for i in range(12) for _ in range(12)])
    days = np.tile(np.array([20250101 + i for i in range(12)]), 12)
    z = np.ones(wallets.size)
    d2 = np.linspace(0.01, 1.0, wallets.size)
    rows = ContrastRows(
        wallets,
        np.full(wallets.size, "BTC"),
        days,
        np.full(wallets.size, 202501),
        z,
        d2,
        np.array([20250101 + i for i in range(13)]),
        np.full(13, 202501),
        np.append(np.unique(wallets), "w_zero"),
    )
    unique_days = np.unique(rows.lattice_day).size
    c0 = CARE_BP * unique_days / d2.sum()
    original, injected, invalid = factor_bootstrap(rows, c0, 1234, "crossed", n_boot=200)
    assert invalid == {"original": 0.0, "fixed_injection": 0.0}
    # Daily sums remain on their natural scale, not the contribution-row mean of one.
    assert float(original.mean()) > 5.0
    shift = injected - original
    assert abs(c0 * d2.sum() / unique_days - CARE_BP) < 1e-12
    # Fixed data are bootstrapped; unlike a tautological draw-specific c, shifts vary.
    assert np.std(shift) > 0

    result = compare_factor(
        rows,
        {"202501": {"coverage": 1.0}},
        {"KF60_ALL": set(rows.universe_wallet), "EW60": set(rows.universe_wallet)},
        ("KF60_ALL", "EW60"),
        1234,
        n_boot=200,
    )
    assert math.isclose(result["point_bp_day"], 144.0 / 13.0)
    assert result["fixed_injection"]["zero_contrast_days"] == 1
    assert result["support"]["global_wallets"] == 13
    assert result["support"]["nonzero_difference_wallets"] == 12


def test_generic_profile_validation_fails_closed():
    validate_profile(PROFILE_ID)
    try:
        validate_profile("wrong-profile")
    except RuntimeError as exc:
        assert PROFILE_ID in str(exc)
    else:
        raise AssertionError("wrong profile must fail")


def test_cache_identity_is_profile_bound():
    frozen = cache_identity_payload(PROFILE_ID)
    changed = cache_identity_payload("different-profile")
    assert frozen["profile_id"] == PROFILE_ID
    assert _sha256_json(frozen) != _sha256_json(changed)


def test_wallet_concentration_aggregates_before_absolute_value():
    rows = ContrastRows(
        np.array(["a", "a", "b", "c", "d", "e", "f"]),
        np.array(["BTC"] * 7),
        np.array([20250101] * 7),
        np.array([202501] * 7),
        np.array([10.0, -10.0, 5.0, 4.0, 3.0, 2.0, 1.0]),
        np.ones(7),
        np.array([20250101]),
        np.array([202501]),
        np.array(["a", "b", "c", "d", "e", "f"]),
    )
    # Wallet a cancels to zero; top five then comprise every nonzero wallet.
    assert top5_wallet_abs_contribution_share(rows) == 1.0


def test_wallet_day_cache_keeps_v1_exact_decimal_normalization_and_hhi():
    notionals = [
        Decimal("33333.333333333333"),
        Decimal("22222.222222222222"),
        Decimal("11111.111111111111"),
        Decimal("5555.555555555555"),
    ]
    total = sum(notionals, Decimal(0))
    pnl = Decimal("123.456789012345")
    old_shares = np.asarray([float(v / total) for v in notionals], float)
    assert exact_hhi(notionals, total) == float(old_shares @ old_shares)
    assert normalized_x(pnl, total) == float(pnl * min(Decimal(1), Decimal(100000) / total))
