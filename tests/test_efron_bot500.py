from __future__ import annotations

import numpy as np

from research.studies.copy_cohort.dynamic_t_quality import FOLDS
from research.studies.copy_cohort.efron_bot500 import (
    HOLD_MS,
    atomic_json,
    bound_entry_meta,
    capacity_book_global,
    efron_roster,
    entry_cache_valid,
    grouped_scores,
    rate_gates,
)


def test_grouped_scores_matches_ordinary_t() -> None:
    wallet = np.array(["a"] * 15 + ["b"] * 15)
    x = np.r_[np.arange(1.0, 16.0), np.arange(-5.0, 10.0)]
    fpd = np.r_[np.full(15, 100.0), np.full(15, 600.0)]
    wallets, nd, _sd, score, group_fpd = grouped_scores(wallet, x, fpd)
    assert wallets.tolist() == ["a", "b"]
    assert nd.tolist() == [15.0, 15.0]
    assert np.isclose(score[0], x[:15].mean() / (x[:15].std(ddof=1) / np.sqrt(15)))
    assert group_fpd.tolist() == [100.0, 600.0]


def test_bot_screen_is_applied_before_efron_fit() -> None:
    wallets = np.array([f"w{i:02d}" for i in range(40)])
    nd = np.full(40, 20.0)
    score = np.linspace(1.0, 4.0, 40)
    mask = np.arange(40) < 35
    seen: list[int] = []

    def fake_fit(z: np.ndarray) -> dict:
        seen.append(z.size)
        return {
            "p_informed": np.linspace(0.0, 1.0, z.size),
            "mu0": 0.0,
            "sigma0": 1.0,
            "pi0": 0.9,
        }

    roster, diag = efron_roster(wallets, nd, score, mask, fit_fn=fake_fit)
    assert seen == [35]
    assert diag["n_fit"] == 35
    assert len(roster) == 30
    assert set(roster) <= set(wallets[mask])


def test_missing_rate_gates_require_every_fold() -> None:
    per_fold_good = {str(f): {"rate": 0.01} for f in FOLDS}
    per_fold_bad = {str(f): {"rate": 0.01} for f in FOLDS}
    per_fold_bad[str(FOLDS[-1])] = {"rate": 0.03}
    good = {
        "rate": 0.005,
        "per_fold": per_fold_good,
    }
    bad = {
        "rate": 0.005,
        "per_fold": per_fold_bad,
    }
    assert rate_gates(good, good)
    assert not rate_gates(good, bad)


def test_capacity_carries_across_fold_boundary() -> None:
    entries = {
        "wallet": np.array(["w", "w"]),
        "coin": np.array(["BTC", "BTC"]),
        "ts": np.array([0, HOLD_MS // 2]),
        "dir_sign": np.ones(2),
        "notional": np.full(2, 1_000.0),
        "gross_bp": np.array([10.0, 20.0]),
        "fold": np.array(FOLDS[:2]),
        "signal_ts": np.array([0, HOLD_MS // 2]),
    }
    rosters = {str(f): ["w"] for f in FOLDS}
    book, funnels = capacity_book_global(entries, rosters)
    assert book["ts"].tolist() == [0]
    assert funnels[str(FOLDS[1])]["n_skip_wallet_coin"] == 1


def test_entry_sidecar_binds_final_parquet_bytes(tmp_path) -> None:
    entry = tmp_path / "entries.parquet"
    meta = tmp_path / "entries.meta.json"
    entry.write_bytes(b"frozen-entry-bytes")
    spec = {"fold": 202511, "schema": "unit-test"}
    atomic_json(meta, bound_entry_meta(entry, spec))
    assert entry_cache_valid(entry, meta, spec)

    entry.write_bytes(b"mutated-entry-bytes")
    assert not entry_cache_valid(entry, meta, spec)
