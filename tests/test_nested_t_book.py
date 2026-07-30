from __future__ import annotations

import numpy as np

from research.studies.copy_cohort.nested_t_book import (
    HOLD_MS,
    bounded,
    capacity_book,
    common_cutoff,
    concentration,
    historical_subset,
    holm,
    missing_stats,
    raw_stats,
)


def _entries() -> dict[str, np.ndarray]:
    return {
        "wallet": np.array(["w", "w", "x"]),
        "coin": np.array(["BTC", "BTC", "BTC"]),
        "ts": np.array([0, HOLD_MS // 2, HOLD_MS // 2]),
        "dir_sign": np.ones(3),
        "notional": np.full(3, 1_000.0),
        "gross_bp": np.array([np.nan, 100.0, 20.0]),
        "fold": np.full(3, 202511),
    }


def test_missing_outcome_reserves_wallet_coin_capacity() -> None:
    book, funnel = capacity_book(_entries(), ["w"])
    assert funnel["n_accepted_capacity"] == 1
    assert funnel["n_skip_wallet_coin"] == 1
    assert not book["supported"][0]


def test_missing_bound_only_replaces_unsupported() -> None:
    book, _ = capacity_book(_entries(), ["w", "x"])
    out = bounded(book, -2_000.0)
    assert out["net_bp"][~out["supported"]].tolist() == [-2_000.0]
    assert np.array_equal(out["net_bp"][out["supported"]], book["net_bp"][book["supported"]])


def test_wallet_contributions_sum_to_mean_difference() -> None:
    a = {"wallet": np.array(["a", "b"]), "net_bp": np.array([10.0, 20.0])}
    b = {"wallet": np.array(["a", "c"]), "net_bp": np.array([2.0, 4.0])}
    out = concentration(a, b)
    assert np.isclose(out["sum_contribution"], 12.0)


def test_common_cutoff_uses_least_mature_major() -> None:
    maxima = [("BTC", 100), ("ETH", 200), ("SOL", 300), ("HYPE", 400)]
    by_coin, cutoff = common_cutoff(maxima)
    assert by_coin["BTC"] == 100
    assert cutoff == 100 - HOLD_MS


def test_raw_robust_point_is_wallet_fold_equal_after_three_entry_gate() -> None:
    raw = {
        "wallet": np.array(["a", "a", "a", "b", "b"]),
        "fold": np.array([202511] * 5),
        "gross_bp": np.array([1.0, 2.0, 3.0, 100.0, 100.0]),
    }
    out = raw_stats(raw)["registered_robust"]
    assert out is not None
    assert out["n_wallet_folds"] == 1
    assert np.isclose(out["wallet_fold_equal_point_bp"], 2.0)


def test_missingness_is_reported_by_coin_and_wallet() -> None:
    cap, _ = capacity_book(_entries(), ["w", "x"])
    out = missing_stats(cap)
    assert out["by_coin"]["BTC"]["missing"] == 1
    assert out["by_wallet"]["w"]["missing"] == 1
    assert out["by_wallet"]["x"]["missing"] == 0


def test_holm_keeps_non_estimable_values_null() -> None:
    results = {"a": {"p": 0.01}, "b": {"p": None}, "c": {"p": 0.04}}
    holm(results, "p", "q")
    assert np.isclose(results["a"]["q"], 0.03)
    assert np.isclose(results["c"]["q"], 0.08)
    assert results["b"]["q"] is None


def test_historical_subset_returns_only_refreshed_additions() -> None:
    current = {
        "wallet": np.array(["a", "a", "b"]),
        "coin": np.array(["BTC", "BTC", "ETH"]),
        "ts": np.array([1, 2, 3]),
        "notional": np.array([250.0, 300.0, 400.0]),
        "mk": np.array([1.0, 2.0, 3.0]),
        "fold": np.array([202511, 202511, 202511]),
    }
    old = {k: v[[0, 2]] for k, v in current.items()}
    subset, extra = historical_subset(current, old)
    assert subset["ts"].tolist() == [1, 3]
    assert extra.tolist() == [1]
