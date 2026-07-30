from __future__ import annotations

import math

import numpy as np

from research.studies.copy_cohort import same_coin_direction_policy as sc
from research.studies.copy_cohort import wallet_coin_t30 as wc


def _candidates(rows: list[tuple[str, str, int, int, float | None]]) -> dict[str, np.ndarray]:
    ordered = sorted(
        enumerate(rows),
        key=lambda x: (x[1][2], x[1][0], x[1][1], x[1][3], 500.0, f"f#{x[0]:03d}"),
    )
    return {
        "wallet": np.asarray([row[0] for _i, row in ordered]),
        "coin": np.asarray([row[1] for _i, row in ordered]),
        "ts": np.asarray([row[2] for _i, row in ordered], dtype=np.int64),
        "dir_sign": np.asarray([row[3] for _i, row in ordered], dtype=float),
        "notional": np.full(len(rows), 500.0),
        "source_id": np.asarray([f"f#{i:03d}" for i, _row in ordered]),
        "gross_bp": np.asarray(
            [np.nan if row[4] is None else row[4] for _i, row in ordered], dtype=float
        ),
        "fold": np.full(len(rows), 202511, dtype=np.int64),
    }


def test_one_side_suppresses_opposite_but_exits_before_equal_timestamp_entry() -> None:
    t = sc.START_MS + 1_000
    rows = _candidates(
        [
            ("a", "BTC", t, 1, 10.0),
            ("b", "BTC", t + 1, -1, 20.0),
            ("b", "BTC", t + wc.HOLD_MS, -1, 30.0),
        ]
    )
    baseline, bf = sc.replay(rows, one_side=False)
    policy, pf = sc.replay(rows, one_side=True)
    assert baseline["source_id"].tolist() == ["f#000", "f#001"]
    assert policy["source_id"].tolist() == ["f#000", "f#002"]
    assert bf["202511"]["n_skip_opposite_direction"] == 0
    assert pf["202511"]["n_skip_opposite_direction"] == 1


def test_gate_precedence_wallet_coin_before_opposite() -> None:
    t = sc.START_MS + 1_000
    rows = _candidates(
        [
            ("a", "BTC", t, 1, 10.0),
            ("a", "BTC", t + 1, -1, 20.0),
        ]
    )
    _cap, funnel = sc.replay(rows, one_side=True)
    assert funnel["202511"]["n_skip_wallet_coin"] == 1
    assert funnel["202511"]["n_skip_opposite_direction"] == 0


def test_canonical_tie_first_row_fixes_direction_and_tie_count_is_exact() -> None:
    t = sc.START_MS + 1_000
    rows = _candidates(
        [
            ("a", "BTC", t, -1, 10.0),
            ("b", "ETH", t, 1, 10.0),
            ("c", "BTC", t, 1, 10.0),
            ("d", "BTC", t, 1, 10.0),
        ]
    )
    checks = sc.validate_candidates(rows)
    cap, funnel = sc.replay(rows, one_side=True)
    assert checks["same_timestamp_coin_opposite_groups"] == 1
    assert checks["same_timestamp_coin_opposite_pairs"] == 2
    assert cap["source_id"].tolist() == ["f#000", "f#001"]
    assert funnel["202511"]["n_skip_opposite_direction"] == 2


def test_suppression_frees_capacity_for_a_later_same_side_candidate(monkeypatch) -> None:
    monkeypatch.setattr(wc, "COIN_CAP_USD", 10_000.0)
    t = sc.START_MS + 1_000
    rows = _candidates(
        [
            ("a", "BTC", t, 1, 10.0),
            ("b", "BTC", t + 1, -1, 10.0),
            ("c", "BTC", t + 2, 1, 10.0),
        ]
    )
    baseline, _ = sc.replay(rows, one_side=False)
    policy, _ = sc.replay(rows, one_side=True)
    assert baseline["source_id"].tolist() == ["f#000", "f#001"]
    assert policy["source_id"].tolist() == ["f#000", "f#002"]


def test_acceptance_is_outcome_blind() -> None:
    t = sc.START_MS + 1_000
    rows = _candidates([("a", "BTC", t, 1, 10.0), ("b", "BTC", t + 1, -1, None)])
    original, funnel = sc.replay(rows, one_side=True)
    altered = {k: v.copy() for k, v in rows.items()}
    altered["gross_bp"] = np.asarray([math.nan, 1e12])
    shadow, shadow_funnel = sc.replay(altered, one_side=True)
    assert sc._ids(original) == sc._ids(shadow)
    assert funnel == shadow_funnel


def test_exposure_reports_mixing_only_for_virtual_sleeves() -> None:
    t = sc.START_MS + DAY_OFFSET
    rows = _candidates([("a", "BTC", t, 1, 10.0), ("b", "BTC", t + 1, -1, 10.0)])
    baseline, _ = sc.replay(rows, one_side=False)
    policy, _ = sc.replay(rows, one_side=True)
    b = sc.exposure_stats(baseline)
    p = sc.exposure_stats(policy)
    assert b["mixed_active_coin_share"] > 0
    assert b["any_book_mixed_wall_time_share"] > 0
    assert p["mixed_active_coin_share"] == 0
    assert p["any_book_mixed_wall_time_share"] == 0


DAY_OFFSET = 3_600_000


def test_shared_missing_cancels_and_exclusive_rows_take_opposite_endpoints() -> None:
    t = sc.START_MS + DAY_OFFSET
    base_rows = _candidates(
        [
            ("a", "BTC", t, 1, None),
            ("b", "ETH", t, 1, None),
            ("c", "SOL", t, 1, 20.0),
        ]
    )
    policy_rows = {k: v[[0, 2]].copy() for k, v in base_rows.items()}
    for cap in (base_rows, policy_rows):
        cap["supported"] = np.isfinite(cap["gross_bp"])
        cap["net_bp"] = cap["gross_bp"] - wc.COST_BP
        cap["signal_ts"] = cap["ts"]
    observed = sc.daily_pnl(policy_rows) - sc.daily_pnl(base_rows)
    info, adverse, favorable = sc.missing_bounds(policy_rows, base_rows, observed)
    assert info["common_missing"] == 1
    assert info["policy_only_missing"] == 0
    assert info["baseline_only_missing"] == 1
    assert math.isclose(adverse.sum() - observed.sum(), -1_000.0)
    assert math.isclose(favorable.sum() - observed.sum(), 1_000.0)


def test_registered_bootstrap_and_two_tail_controls_are_deterministic() -> None:
    idx1, idx2 = sc.block_indices(), sc.block_indices()
    assert np.array_equal(idx1, idx2)
    d = np.zeros(sc.N_DAYS)
    d[::13] = 50.0
    out = sc.inference(d, idx1)
    assert math.isclose(out["point_usd"], d.sum())
    assert out["positive_injection"]["point_usd"] == 2_500.0
    assert out["negative_injection"]["point_usd"] == -2_500.0
    assert out["mde80_positive_usd"] >= 0
    assert out["mde80_negative_usd"] >= 0


def test_exact_sign_test_excludes_ties() -> None:
    out = sc.exact_sign_test({"a": 2.0, "b": -1.0, "c": 0.0, "d": 3.0})
    assert out["positive"] == 2
    assert out["negative"] == 1
    assert out["evaluable"] == 3
    assert out["tied"] == 1
    assert out["exact_two_sided_binomial_p"] == 1.0


def test_missing_imbalance_gate_is_overall_only() -> None:
    def arm(overall: float, first_fold: float) -> dict[str, object]:
        return {
            "rate": overall,
            "per_fold": {
                str(fold): {"rate": first_fold if fold == wc.FOLDS[0] else overall}
                for fold in wc.FOLDS
            },
        }

    # The first-fold arm gap is diagnostic; both fold rates pass 2%, while the
    # registered overall arm gap passes 0.5 percentage points.
    out = sc.missing_gates(
        {
            sc.POLICY: arm(0.009, 0.019),
            sc.BASELINE: arm(0.006, 0.010),
        }
    )
    assert out["pass"]
    assert math.isclose(out["imbalances"]["per_fold"][str(wc.FOLDS[0])], 0.009)
    assert out["per_fold_arm_imbalances_diagnostic_only"]


def test_claim_predicates_are_disjoint() -> None:
    def inf(point: float, lo: float, hi: float) -> dict[str, object]:
        return {
            "point_usd": point,
            "ci95_usd": [lo, hi],
            "mde80_positive_usd": 1_000.0,
            "mde80_negative_usd": 1_000.0,
            "power_at_positive_2500": 0.9,
            "power_at_negative_2500": 0.9,
            "positive_injection": {"pass": True},
            "negative_injection": {"pass": True},
        }

    equivalent = sc.classify(
        inf(-1_000, -1_500, -500), inf(-1_200, -2_000, -700), inf(-800, -1_000, -500), True
    )
    assert equivalent["claim"] == "NARROW_POLICY_NO_MATERIAL_EFFECT"
    adverse = sc.classify(
        inf(-4_000, -5_000, -3_000), inf(-5_000, -6_000, -4_000), inf(-3_500, -4_000, -3_000), True
    )
    assert adverse["claim"] == "NARROW_POLICY_ADVERSE"
