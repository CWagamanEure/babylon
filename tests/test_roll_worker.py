"""RAM-bounded chunked roll selection: the chunked/subprocess path must be bit-identical to the
in-process SelectionAdapter loop (only memory behaviour differs)."""
import numpy as np
import polars as pl

from babylon.follow.experiment import ExperimentConfig
from babylon.follow.roll_worker import chunked_batch_returns, compute_returns_chunk
from babylon.follow.selection import SelectionAdapter

H = 3_600_000
DAY = 86_400_000


def _cfg(**over):
    base = dict(
        execution="retail", universe_hash="u0", eligible_pool="p", train_days=30, follow_days=14,
        roll_cadence_days=14, min_hold_ms=3_600_000, min_positions=1, beta=1.0, gross_target=1.0,
        max_coin_frac=0.08, max_wallet_frac=0.05, also_run_uncapped=True, lag_bucket_ms=0,
        fee_bps=4.5, impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=1000.0,
        primary_control="pool_mean", secondary_controls=("random",), min_n_nominal=20,
        min_effective_n=2, horizon_cap_days=300, mar_bps=8.0, maxdd_bound=-0.25,
        max_single_contrib_frac=0.20, cost_floor_bps=15.0, selection_signal="markout",
        markout_horizon_ms=H, selection_rank="trimmed_mean")
    base.update(over)
    return ExperimentConfig(**base)


def _lookup(t0):
    times = t0 + np.arange(-20, 3) * H
    return {"RISE": (times, 100.0 * 1.02 ** np.arange(times.size))}


def _write_fills(fills_dir, wallet, entries):
    n = len(entries)
    pl.DataFrame({"time": list(entries), "coin": ["RISE"] * n, "px": [100.0] * n, "sz": [1.0] * n,
                 "side": ["B"] * n, "crossed": [True] * n, "startPosition": [0.0] * n,
                 "hash": [f"0x{i}" for i in range(n)], "tid": list(range(1, n + 1))}
                ).write_parquet(fills_dir / f"{wallet}.parquet")


def _world(tmp_path):
    t0 = 300 * H
    fills_dir = tmp_path / "fills"
    fills_dir.mkdir()
    wallets = ["a", "b", "c"]
    for i, w in enumerate(wallets):        # each: opens on RISE in the train window (before t0)
        _write_fills(fills_dir, w, [t0 - (14 - i) * H, t0 - (9 - i) * H])
    return t0, fills_dir, wallets


def _adapter_loop(wallets, t0, cfg, fills_dir, look):
    from babylon.follow.fills_source import ParquetFillsProvider
    ad = SelectionAdapter(ParquetFillsProvider(fills_dir), universe=set(), lookups=look,
                          config=cfg, basket=None)
    return {w: {"returns": ad.returns_fn(w, t0).tolist(), "cutoff": ad.cutoff_fn(w, t0),
                "activity": ad.activity_fn(w, t0)} for w in wallets}


def test_compute_returns_chunk_matches_adapter(tmp_path):
    t0, fills_dir, wallets = _world(tmp_path)
    cfg, look = _cfg(), _lookup(300 * H)
    chunk = compute_returns_chunk(wallets, t0, config=cfg, fills_dir=fills_dir, lookups=look,
                                  basket=None, universe=set())
    assert chunk == _adapter_loop(wallets, t0, cfg, fills_dir, look)


def test_chunked_batch_returns_subprocess_matches_inprocess(tmp_path):
    t0, fills_dir, wallets = _world(tmp_path)
    cfg, look = _cfg(), _lookup(300 * H)
    # chunk_size=2 → real subprocesses (config/lookups pickled + reloaded); pool splits 2 + 1
    returns, cutoffs, activity = chunked_batch_returns(
        wallets, t0, config=cfg, fills_dir=fills_dir, lookups=look, basket=None,
        universe=set(), chunk_size=2)
    ref = _adapter_loop(wallets, t0, cfg, fills_dir, look)
    assert set(returns) == set(wallets)
    for w in wallets:
        assert returns[w].tolist() == ref[w]["returns"]
        assert cutoffs[w] == ref[w]["cutoff"] and activity[w] == ref[w]["activity"]
    assert any(r.size for r in returns.values())     # the RISE opens actually produced markouts
