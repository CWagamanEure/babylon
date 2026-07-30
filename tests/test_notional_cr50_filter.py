from __future__ import annotations

import math
from decimal import Decimal

import duckdb
import numpy as np

from research.studies.copy_cohort import notional_cr50_filter as cr
from research.studies.copy_cohort import wallet_coin_t30 as wc


def _candidates(notional: list[float]) -> dict[str, np.ndarray]:
    n = len(notional)
    return {
        "wallet": np.asarray([f"w{i}" for i in range(n)]),
        "coin": np.asarray(["BTC"] * n),
        "ts": cr.sc.START_MS + np.arange(n, dtype=np.int64),
        "dir_sign": np.ones(n),
        "notional": np.asarray(notional, dtype=float),
        "source_id": np.asarray([f"f#{i}" for i in range(n)]),
        "gross_bp": np.arange(n, dtype=float),
        "fold": np.full(n, 202511, dtype=np.int64),
    }


def _scales(values: list[str | None]) -> list[dict[str, object]]:
    return [
        {"fold": 202511, "wallet": f"w{i}", "typical_decimal": value}
        for i, value in enumerate(values)
    ]


def test_exact_continuous_median_preserves_half_tick() -> None:
    values = [Decimal("250.0000000001"), Decimal("250.0000000002")]
    median = cr.continuous_median(values)
    assert median == Decimal("250.00000000015")
    assert cr.canonical_decimal(median) == "250.00000000015"


def test_duckdb_widened_decimal_median_matches_python() -> None:
    con = duckdb.connect()
    got = con.execute(
        "SELECT CAST(median(CAST(x AS DECIMAL(38,11))) AS VARCHAR) "
        "FROM (VALUES (CAST('250.0000000001' AS DECIMAL(38,10))), "
        "(CAST('250.0000000002' AS DECIMAL(38,10)))) t(x)"
    ).fetchone()[0]
    con.close()
    assert cr.canonical_decimal(Decimal(got)) == "250.00000000015"


def test_cr50_exact_boundary_passes_and_one_ulp_above_fails() -> None:
    candidates = _candidates([5_000.0, np.nextafter(5_000.0, np.inf)])
    annotated, keep = cr.attach_cr(candidates, _scales(["100", "100"]))
    assert keep.tolist() == [True, False]
    assert annotated["cr"][0] == 50.0
    assert annotated["cr"][1] > 50.0


def test_undefined_scale_passes_through() -> None:
    candidates = _candidates([1e12])
    annotated, keep = cr.attach_cr(candidates, _scales([None]))
    assert keep.tolist() == [True]
    assert not annotated["has_scale"][0]
    assert np.isnan(annotated["cr"][0])


def test_filter_runs_before_capacity_and_frees_slot(monkeypatch) -> None:
    monkeypatch.setattr(wc, "COIN_CAP_USD", 5_000.0)
    candidates = _candidates([5_001.0, 1_000.0])
    annotated, keep = cr.attach_cr(candidates, _scales(["100", "100"]))
    baseline, _ = cr.sc.replay(candidates, one_side=False)
    policy, _ = cr.filtered_replay(annotated, keep)
    assert baseline["source_id"].tolist() == ["f#0"]
    assert policy["source_id"].tolist() == ["f#1"]


def test_filter_decision_is_outcome_blind() -> None:
    candidates = _candidates([5_001.0, 1_000.0])
    original, keep = cr.attach_cr(candidates, _scales(["100", "100"]))
    changed = {key: value.copy() for key, value in candidates.items()}
    changed["gross_bp"] = np.asarray([np.nan, 1e12])
    shadow, shadow_keep = cr.attach_cr(changed, _scales(["100", "100"]))
    assert np.array_equal(keep, shadow_keep)
    assert np.array_equal(original["cr"], shadow["cr"])


def test_missing_gates_use_cr50_arm_labels() -> None:
    per_fold = {str(fold): {"accepted": 100, "missing": 0, "rate": 0.0} for fold in wc.FOLDS}
    by_arm = {
        cr.BASELINE: {"rate": 0.0, "per_fold": per_fold},
        cr.POLICY: {"rate": 0.0, "per_fold": per_fold},
    }
    assert cr.missing_gates(by_arm)["pass"]


def test_missing_bounds_relabels_inherited_policy_arm(monkeypatch) -> None:
    inherited = {
        "absolute_arm_stress": {
            cr.sc.POLICY: {"net_usd_low": -1.0},
            cr.sc.BASELINE: {"net_usd_low": -2.0},
        }
    }
    monkeypatch.setattr(
        cr.sc,
        "missing_bounds",
        lambda policy, baseline, daily: (inherited, daily - 1, daily + 1),
    )
    bounds, _, _ = cr.missing_bounds({}, {}, np.zeros(cr.sc.N_DAYS))
    assert set(bounds["absolute_arm_stress"]) == {cr.POLICY, cr.BASELINE}
    assert bounds["absolute_arm_stress"][cr.POLICY]["net_usd_low"] == -1.0


def test_wallet_contributions_are_additive_and_deterministically_ranked() -> None:
    def cap(wallets: list[str], bp: list[float]) -> dict[str, np.ndarray]:
        return {
            "wallet": np.asarray(wallets),
            "supported": np.ones(len(wallets), dtype=bool),
            "net_bp": np.asarray(bp, dtype=float),
        }

    baseline = cap(["b", "a", "c"], [10, 20, 5])
    policy = cap(["a", "b", "c"], [10, 20, 5])
    # a contributes -$5, b +$5, c zero; abs tie breaks wallet ascending.
    out = cr.wallet_concentration(policy, baseline, 0.0)
    assert [row["wallet"] for row in out["contributions"][:2]] == ["a", "b"]
    assert math.isclose(out["sum_contributions_usd"], 0.0)
    assert out["cumulative_leave_top_k_delta_usd"]["1"] == 5.0


def test_concentration_blocks_only_narrow_adverse_claim() -> None:
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

    observed = inf(-4_000, -5_000, -3_000)
    adverse = inf(-5_000, -6_000, -4_000)
    favorable = inf(-3_500, -4_000, -3_000)
    concentrated = {"adverse_breadth_gate_le_0_50": False}
    out = cr.classify_with_concentration(observed, adverse, favorable, True, concentrated)
    assert out["claim"] == "UNRESOLVED"
    assert not out["narrow_policy_adverse_predicate"]
