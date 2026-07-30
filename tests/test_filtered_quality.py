from __future__ import annotations

from datetime import date

import numpy as np

from research.studies.copy_cohort import alt_fresh_validate
from research.studies.copy_cohort.filtered_quality import (
    Panel,
    average_rank_normal,
    capacity_normalized,
    fit_kalman,
    kalman_gap,
    topk,
)
from research.studies.copy_cohort.filtered_quality_book import (
    accept_book,
    collapse_candidates,
    consensus_other_counts,
    time_boot_delta,
    wallet_boot_delta,
)


def test_capacity_normalized_scales_down_never_up():
    got = capacity_normalized(np.array([10.0, 100.0, -50.0]),
                              np.array([50_000.0, 200_000.0, 100_000.0]))
    assert np.allclose(got, [10.0, 50.0, -50.0])


def test_average_rank_normal_ties_and_direction():
    z = average_rank_normal(np.array([-5.0, 0.0, 0.0, 9.0]))
    assert z[0] < z[1] == z[2] < z[3]
    assert abs(z.mean()) < 1e-12


def test_kalman_gap_preserves_stationary_variance():
    phi, lam = 0.9, 0.35
    th, p = kalman_gap(np.array([2.0]), np.array([lam]), phi, lam, 30)
    assert np.allclose(th, [2.0 * phi**30])
    assert np.allclose(p, [lam])


def test_block_collapse_is_fill_split_invariant_and_drops_ambiguous():
    out = collapse_candidates(
        np.array(["w1", "w1", "w2", "w2"]),
        np.array(["BTC", "BTC", "ETH", "ETH"]),
        np.array([1, 1, 2, 2]),
        np.array([1, 1, 1, -1]),
        np.array([100.0, 200.0, 400.0, 500.0]),
    )
    assert out["wallet"].tolist() == ["w1"]
    assert out["notl"].tolist() == [300.0]


def test_acceptance_concurrency_and_coin_cap():
    # Same wallet/coin second entry is skipped; only 20 simultaneous BTC clips fit $50k.
    n = 23
    ent = {
        "wallet": np.array(["w0", "w0"] + [f"w{i}" for i in range(1, 22)]),
        "coin": np.array(["BTC"] * n),
        "ts": np.array([0, 1] + [2] * 21, np.int64),
        "dir": np.ones(n, np.int64),
    }
    keep = accept_book(ent)
    assert 1 not in keep
    assert keep.size == 20


def test_consensus_requires_distinct_other_wallet():
    entries = {"wallet": np.array(["a", "a"]), "coin": np.array(["BTC", "BTC"]),
               "ts": np.array([10, 20]), "dir": np.array([1, 1])}
    signals = {"wallet": np.array(["a", "b"]), "coin": np.array(["BTC", "BTC"]),
               "ts": np.array([5, 15]), "dir": np.array([1, 1])}
    got = consensus_other_counts(entries, signals, {"a", "b"})
    assert got.tolist() == [0, 1]


def test_synthetic_persistent_state_is_ranked_into_top30():
    rng = np.random.default_rng(7)
    n_wallets, n_days = 250, 70
    wallets = np.array([f"w{i:03d}" for i in range(n_wallets)])
    planted = set(wallets[:30])
    start = date(2026, 1, 1).toordinal()
    wal = np.tile(wallets, n_days)
    ordinal = np.repeat(np.arange(start, start + n_days), n_wallets)
    latent = np.array([1.5 if w in planted else 0.0 for w in wallets])
    z = np.tile(latent, n_days) + rng.normal(0, 0.7, n_wallets * n_days)
    x = z.copy()
    panel = Panel(wal, np.zeros(wal.size, np.int64), ordinal, x, x.copy(), z, wallets,
                  start, start + n_days - 1, ())
    phi, lam, score, _, fallback = fit_kalman(panel)
    assert not fallback and np.isfinite(phi) and np.isfinite(lam)
    selected = set(topk(wallets, score))
    assert len(selected & planted) >= 27


def test_plus5_inference_control_clears_both_component_intervals():
    rng = np.random.default_rng(42)
    n = 3_600
    wallets = np.array([f"w{i % 30:02d}" for i in range(n)])
    ts = np.arange(n, dtype=np.int64) * 86_400_000 // 12
    a = {"wallet": wallets, "ts": ts, "net_bp": rng.normal(5.0, 25.0, n)}
    b = {"wallet": wallets, "ts": ts, "net_bp": rng.normal(0.0, 25.0, n)}
    wb = wallet_boot_delta(a, b, np.random.default_rng(1), n_boot=500)
    tb = time_boot_delta(a, b, np.random.default_rng(2), n_boot=500)
    assert np.quantile(wb, .025) > 0
    assert np.quantile(tb, .025) > 0


def test_topk_fails_instead_of_silently_returning_short_roster():
    with np.testing.assert_raises(RuntimeError):
        topk(np.array(["a", "b"]), np.array([1.0, np.nan]), k=2)


def test_ctx_parts_includes_full_date_next_month_directories(monkeypatch):
    def fake_glob(pattern: str) -> list[str]:
        if "month=202601" in pattern:
            return ["/x/month=202601/day=20260131/ctx.parquet"]
        assert "month=202602" in pattern and "day=*" in pattern
        return ["/x/month=202602/day=20260201/ctx.parquet",
                "/x/month=202602/day=20260204/ctx.parquet"]

    monkeypatch.setattr(alt_fresh_validate.glob, "glob", fake_glob)
    got = alt_fresh_validate._ctx_parts(202601)
    assert "/x/month=202602/day=20260201/ctx.parquet" in got
    assert "/x/month=202602/day=20260204/ctx.parquet" not in got
