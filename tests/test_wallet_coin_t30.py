from __future__ import annotations

import numpy as np

from research.studies.copy_cohort import wallet_coin_t30 as wc


def _all_fold_rosters(value):
    return {str(fold): (value if fold == 202511 else []) for fold in wc.FOLDS}


def test_group_scores_and_pair_ranking_allow_multiple_seats_per_wallet(monkeypatch) -> None:
    monkeypatch.setattr(wc, "TOP_K", 2)
    keys = np.asarray(["a\x1fBTC"] * 15 + ["a\x1fETH"] * 15 + ["b\x1fSOL"] * 15)
    x = np.concatenate([np.arange(1, 16), np.arange(2, 17), np.linspace(-1, 1, 15)]).astype(float)
    unique, nd, _mean, _sd, t = wc._group_scores(keys, x)
    assert np.array_equal(nd, np.full(3, 15.0))
    ranked = wc._top_pairs(unique, t)
    assert ranked[:2] == [("a", "ETH"), ("a", "BTC")]


def test_pair_mask_is_exact_coin_restricted_and_wallet_mask_is_not() -> None:
    entries = {
        "wallet": np.asarray(["a", "a", "b"]),
        "coin": np.asarray(["BTC", "ETH", "BTC"]),
        "fold": np.asarray([202511, 202511, 202511]),
    }
    pair = _all_fold_rosters([{"wallet": "a", "coin": "BTC"}])
    wallet = _all_fold_rosters(["a"])
    assert wc._arm_mask(entries, pair, "PAIR_T30").tolist() == [True, False, False]
    assert wc._arm_mask(entries, wallet, "WALLET_T30").tolist() == [True, True, False]


def test_capacity_same_timestamp_coin_collision_uses_registered_total_order() -> None:
    wallets = np.asarray([f"w{i:02d}" for i in range(11)])
    n = wallets.size
    entries = {
        "wallet": wallets,
        "coin": np.asarray(["BTC"] * n),
        "ts": np.full(n, 1_700_000_000_000, np.int64),
        "dir_sign": np.ones(n),
        "notional": np.full(n, 500.0),
        "source_id": np.asarray([f"f#{i}" for i in range(n)]),
        "gross_bp": np.arange(n, dtype=float),
        "fold": np.full(n, 202511, np.int64),
    }
    rosters = _all_fold_rosters(wallets.tolist())
    cap, funnels = wc.capacity_book(entries, rosters, "WALLET_T30")
    assert cap["wallet"].tolist() == wallets[:10].tolist()
    assert funnels["202511"]["n_skip_coin_cap"] == 1
    assert funnels["202511"]["n_accepted_capacity"] == 10


def test_dual_compare_binds_by_envelope_not_width(monkeypatch) -> None:
    def fake_compare(a, _b, *_args, **_kwargs):
        is_pair = "|" in str(a["wallet"][0])
        ci = [-0.1, 6.0] if is_pair else [0.2, 8.0]
        return {
            "delta_bp": 2.0,
            "crossed_ci95": ci,
            "crossed_mde80_bp": 4.0 if is_pair else 3.0,
            "crossed_power_at_plus5": 0.7 if is_pair else 0.9,
            "crossed_p_two_sided": 0.2 if is_pair else 0.1,
            "p_null_plus5_one_sided": 0.4 if is_pair else 0.3,
        }

    monkeypatch.setattr(wc, "compare", fake_compare)
    book = {
        "wallet": np.asarray(["w"]),
        "coin": np.asarray(["BTC"]),
        "net_bp": np.asarray([1.0]),
    }
    out = wc._dual_compare(book, book, 1, 0, 1)
    assert out["binding"]["crossed_ci95_envelope"] == [-0.1, 8.0]
    assert out["binding"]["mde80_bp"] == 4.0
    assert out["binding"]["power_at_plus5"] == 0.7


def test_book_stats_reports_positive_evaluable_and_all_calendar_months() -> None:
    folds = np.asarray([202511, 202511, 202512, 202512])
    book = {
        "wallet": np.asarray(["a", "b", "a", "b"]),
        "coin": np.asarray(["BTC", "BTC", "ETH", "ETH"]),
        "ts": np.arange(4, dtype=np.int64),
        "dir_sign": np.ones(4),
        "source_id": np.asarray([f"f#{i}" for i in range(4)]),
        "fold": folds,
        "net_bp": np.asarray([10.0, 0.0, -4.0, -2.0]),
        "notional": np.full(4, 500.0),
    }
    out = wc._book_stats(book)
    assert out["positive_months"] == 1
    assert out["evaluable_months"] == 2
    assert out["calendar_months"] == 8
    assert out["positive_months_label"] == "1/2, 2/8 evaluable"
    assert out["net_median_bp_per_trade"] == -1.0


def test_secondary_pass_flags_require_holm_q() -> None:
    contrasts = {
        wc.PRIMARY: {},
        "a": {
            "positive_iut_p": 0.04,
            "null_iut_p": 0.04,
            "positive_sensitivity_pass": True,
            "null_sensitivity_pass": True,
        },
        "b": {
            "positive_iut_p": 0.04,
            "null_iut_p": 0.04,
            "positive_sensitivity_pass": True,
            "null_sensitivity_pass": True,
        },
        "c": {
            "positive_iut_p": 0.04,
            "null_iut_p": 0.04,
            "positive_sensitivity_pass": True,
            "null_sensitivity_pass": True,
        },
    }
    wc.apply_secondary_holm(contrasts)
    assert all(not contrasts[k]["positive_sensitivity_pass"] for k in ("a", "b", "c"))
    assert all(not contrasts[k]["null_sensitivity_pass"] for k in ("a", "b", "c"))


def test_secondary_holm_handles_non_estimable_contrast() -> None:
    contrasts = {
        wc.PRIMARY: {},
        "sparse": {
            "positive_iut_p": None,
            "null_iut_p": None,
            "positive_sensitivity_pass": False,
            "null_sensitivity_pass": False,
        },
    }
    wc.apply_secondary_holm(contrasts)
    assert contrasts["sparse"]["positive_iut_holm_q"] is None
    assert contrasts["sparse"]["null_iut_holm_q"] is None
    assert not contrasts["sparse"]["positive_sensitivity_pass"]
    assert not contrasts["sparse"]["null_sensitivity_pass"]


def test_parent_global_accepts_native_ts_without_eager_fallback() -> None:
    parts = [
        {"ts": np.asarray([1]), "wallet": np.asarray(["a"])},
        {"ts": np.asarray([2]), "wallet": np.asarray(["b"])},
    ]
    out = wc._parent_global(parts)
    assert out["ts"].tolist() == [1, 2]
    assert out["wallet"].tolist() == ["a", "b"]


def test_pair_seat_support_exposes_zero_forward_seats(monkeypatch) -> None:
    monkeypatch.setattr(wc, "TOP_K", 2)
    entries = {
        "wallet": np.asarray(["a"]),
        "coin": np.asarray(["BTC"]),
        "fold": np.asarray([202511]),
    }
    capacity = {
        "wallet": np.asarray(["a"]),
        "coin": np.asarray(["BTC"]),
        "fold": np.asarray([202511]),
        "supported": np.asarray([True]),
    }
    rosters = _all_fold_rosters([{"wallet": "a", "coin": "BTC"}, {"wallet": "b", "coin": "ETH"}])
    out = wc.pair_seat_support(entries, capacity, rosters, "PAIR_T30")
    assert out["per_fold"]["202511"]["zero_candidate_seats"] == 1
    assert out["per_fold"]["202511"]["zero_supported_seats"] == 1
