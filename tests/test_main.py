import asyncio

import numpy as np
import polars as pl
import pytest

from babylon.config import Network
from babylon.follow.experiment import ExperimentConfig
from babylon.follow.fills_source import ParquetFillsProvider
from babylon.follow.main import (
    analysis_hash, load_candidates, load_universe, locked_config, run_live, universe_hash,
)

H = 3_600_000
LOOK = {"TESTC": (np.array([0, H, 2 * H, 3 * H, 4 * H, 5 * H]),
                  np.array([90.0, 95.0, 100.0, 105.0, 110.0, 115.0]))}


def test_universe_hash_deterministic_and_order_invariant():
    assert universe_hash(["BTC", "ETH"]) == universe_hash(["ETH", "BTC"])
    assert universe_hash(["BTC"]) != universe_hash(["BTC", "ETH"])


def test_analysis_hash_stable():
    assert analysis_hash() == analysis_hash() and len(analysis_hash()) == 16


def test_locked_config_validates_and_binds_universe():
    c = locked_config(["BTC", "ETH"])
    c.validate()
    assert c.universe_hash == universe_hash(["BTC", "ETH"]) and c.execution == "retail"
    assert c.train_days == 30 and c.mar_bps == 8.0 and c.max_wallet_frac == 0.05


def test_load_candidates_full_and_top_quintile(tmp_path):
    p = tmp_path / "w.csv"
    pl.DataFrame({"w": ["0xa", "0xb", "0xc"], "top_quintile": [True, False, True]}).write_csv(p)
    assert load_candidates(p) == ["0xa", "0xb", "0xc"]
    assert load_candidates(p, top_quintile_only=True) == ["0xa", "0xc"]


def test_load_universe(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("# a comment\nBTC\nETH\n\n SOL \n# another\n")
    assert load_universe(p) == ["BTC", "ETH", "SOL"]   # comments + blanks skipped


# --- dry-run orchestration (no network, no loop) ---

def _cfg(**over):
    base = dict(
        execution="retail", universe_hash="u", eligible_pool="p", train_days=1, follow_days=14,
        roll_cadence_days=14, min_hold_ms=0, min_positions=1, beta=1.0, gross_target=1.0,
        max_coin_frac=0.08, max_wallet_frac=0.05, also_run_uncapped=True, lag_bucket_ms=0,
        fee_bps=4.5, impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=1000.0,
        primary_control="pool_mean", secondary_controls=("random",), min_n_nominal=1500,
        min_effective_n=120, horizon_cap_days=300, mar_bps=8.0, maxdd_bound=-0.25,
        max_single_contrib_frac=0.20, cost_floor_bps=15.0)
    base.update(over)
    return ExperimentConfig(**base)


def _roundtrips(exit_px, tid0):
    # TWO sequential round-trips on TESTC (kelly needs ≥2 obs/wallet for a variance)
    return pl.DataFrame({
        "time": [2 * H, 3 * H, 4 * H, 5 * H], "coin": ["TESTC"] * 4,
        "px": [100.0, 105.0, 105.0, exit_px], "sz": [1.0] * 4,
        "side": ["B", "A", "B", "A"], "crossed": [True] * 4,
        "startPosition": [0.0, 1.0, 0.0, 1.0],
        "hash": ["0xr"] * 4, "tid": [tid0, tid0 + 1, tid0 + 2, tid0 + 3]})


class _FakeInfo:
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def user_fills_by_time(self, addr, s, e): return []
    async def clearinghouse_state(self, a): return {"assetPositions": []}


class _FakeFeed:
    def subscribe(self, sub): ...
    def on(self, ch, h): ...
    def stop(self): ...
    async def run(self): ...


def test_dry_run_builds_and_rolls(tmp_path):
    fills_dir = tmp_path / "fills"
    fills_dir.mkdir()
    cands = [f"w{i}" for i in range(10)]
    for i, w in enumerate(cands):              # each wallet two positive round-trips
        _roundtrips(108.0 + i, tid0=10 * i).write_parquet(fills_dir / f"{w}.parquet")
    system = asyncio.run(run_live(
        candidates=cands, universe=["TESTC"], registry_path=tmp_path / "reg.jsonl",
        checkpoint_path=tmp_path / "ckpt.json", config=_cfg(), lookups=LOOK, t0_ms=6 * H,
        info=_FakeInfo(), feed=_FakeFeed(), provider=ParquetFillsProvider(fills_dir),
        dry_run=True))
    assert system.run_id.startswith("run_")
    assert system.registry.committed(6 * H) is not None     # initial manifest registered
    assert system.runner._weights                            # a roster was selected
    assert system.config.train_days == 1


def test_resume_skips_reroll_and_prefetch(tmp_path):
    fills_dir = tmp_path / "fills"; fills_dir.mkdir()
    cands = [f"w{i}" for i in range(10)]
    for i, w in enumerate(cands):
        _roundtrips(108.0 + i, tid0=10 * i).write_parquet(fills_dir / f"{w}.parquet")
    calls = {"n": 0}
    async def pf(wallets, s, e): calls["n"] += 1
    kw = dict(candidates=cands, universe=["TESTC"], registry_path=tmp_path / "reg.jsonl",
              checkpoint_path=tmp_path / "ckpt.json", config=_cfg(), lookups=LOOK,
              info=_FakeInfo(), feed=_FakeFeed(), provider=ParquetFillsProvider(fills_dir),
              prefetch=pf, dry_run=True)
    s1 = asyncio.run(run_live(t0_ms=6 * H, **kw))             # first: rolls + prefetches
    assert calls["n"] == 1
    s2 = asyncio.run(run_live(t0_ms=999 * H, **kw))           # restart: resume, no prefetch/re-roll
    assert calls["n"] == 1 and s2.run_id == s1.run_id and s2.t0_ms == 6 * H


def test_dry_run_empty_pool_raises(tmp_path):
    (tmp_path / "fills").mkdir()
    with pytest.raises(ValueError, match="empty roster"):
        asyncio.run(run_live(
            candidates=["nobody"], universe=["TESTC"], registry_path=tmp_path / "reg.jsonl",
            checkpoint_path=tmp_path / "ckpt.json", config=_cfg(), lookups=LOOK, t0_ms=6 * H,
            info=_FakeInfo(), feed=_FakeFeed(),
            provider=ParquetFillsProvider(tmp_path / "fills"), dry_run=True))
