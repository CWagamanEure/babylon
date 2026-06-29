import asyncio
import json
from decimal import Decimal

import numpy as np

from babylon.follow.experiment import ExperimentConfig
from babylon.follow.live import LiveFollowSystem, mono_ms, wall_ms


def _cfg(**over):
    base = dict(
        execution="retail", universe_hash="u0", eligible_pool="longhold_taker_conviction",
        train_days=30, follow_days=14, roll_cadence_days=14, min_hold_ms=3_600_000,
        min_positions=6, beta=1.245, gross_target=1.0, max_coin_frac=0.08,
        max_wallet_frac=0.05, also_run_uncapped=True, lag_bucket_ms=60_000, fee_bps=4.5,
        impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=1_000.0,
        primary_control="pool_mean", secondary_controls=("random", "sign_shuffle"),
        min_n_nominal=1500, min_effective_n=120, horizon_cap_days=300, mar_bps=8.0,
        maxdd_bound=-0.25, max_single_contrib_frac=0.20, cost_floor_bps=15.0,
    )
    base.update(over)
    return ExperimentConfig(**base)


class _Src:
    async def user_fills_by_time(self, a, s, e): return []
    async def clearinghouse_state(self, a):
        return {"assetPositions": [{"position": {"coin": "ZEC", "szi": "5.0"}}]}


class _Feed:
    """Captures the l2Book handler and replays a few synthetic snapshots in run()."""
    def __init__(self): self._h = None; self._subs = []; self._stop = asyncio.Event()
    def subscribe(self, sub): self._subs.append(sub)
    def on(self, channel, handler): self._h = handler
    def stop(self): self._stop.set()
    async def run(self):
        for _ in range(5):
            if self._stop.is_set(): break
            await self._h({"coin": "ZEC", "time": wall_ms(),
                           "levels": [[{"px": "99.95", "sz": "100", "n": 1}],
                                      [{"px": "100.05", "sz": "100", "n": 1}]]})
            await asyncio.sleep(0.005)
        await self._stop.wait()


def _build(tmp_path, *, cfg=None, t0_ms=10_000, prefetch=None, reset=None, **over):
    # 120 candidates → top quintile ~24 wallets → weights sum to ~1 (realistic consensus)
    cands = [f"w{i}" for i in range(120)]
    rets = {w: np.random.default_rng(i).normal(300 - i, 20, 60) for i, w in enumerate(cands)}
    return LiveFollowSystem.build(
        config=cfg or _cfg(), candidates=cands, universe=["ZEC"], source=_Src(), feed=_Feed(),
        returns_fn=lambda w, t: rets[w], cutoff_fn=lambda w, t: 1000,
        t0_ms=t0_ms, budget_usd=1000.0, registry_path=tmp_path / "reg.jsonl",
        checkpoint_path=tmp_path / "ckpt.json", analysis_script_hash="ah",
        poll_interval_s=0.0, prefetch=prefetch, reset=reset, **over)


def test_build_rolls_and_registers(tmp_path):
    sys = _build(tmp_path)
    assert sys.run_id.startswith("run_")
    assert sys.registry.committed(10_000) is not None         # initial manifest registered
    assert sys.runner._weights                                 # roster weights wired in


def test_clock_contract_is_wallclock_and_monotonic():
    # book staleness must use wall-clock ms (book ts are exchange epoch ms)
    assert wall_ms() > 1_700_000_000_000                       # plausible 2024+ UNIX ms
    a, b = mono_ms(), mono_ms()
    assert b >= a                                              # monotonic never goes backward


def test_tick_trades_after_signal(tmp_path):
    sys = _build(tmp_path)
    r = sys.runner
    for wlt in list(r._weights):                              # seed the consensus
        r._watcher._pos[wlt] = {"ZEC": 5.0}
    r._last_poll_mono = 0
    r.on_book("ZEC", __import__("babylon.execution.fill_model", fromlist=["Book"]).Book(
        bid_px=(99.95,), bid_sz=(100.0,), ask_px=(100.05,), ask_sz=(100.0,)), ts=1)
    rep = r.tick(now_wall=1, now_mono=1)
    assert rep.fills and r._ex.net_position("ZEC") > 0


def test_checkpoint_and_resume(tmp_path):
    sys = _build(tmp_path)
    r = sys.runner
    for wlt in list(r._weights):
        r._watcher._pos[wlt] = {"ZEC": 5.0}
    r._last_poll_mono = 0
    r.on_book("ZEC", __import__("babylon.execution.fill_model", fromlist=["Book"]).Book(
        bid_px=(99.95,), bid_sz=(100.0,), ask_px=(100.05,), ask_sz=(100.0,)), ts=1)
    r.tick(1, 1)
    pos = r._ex.net_position("ZEC")
    r.checkpoint(sys.checkpoint_path)
    assert sys.checkpoint_path.exists()
    # rebuilding with the checkpoint present restores the net book
    sys2 = _build(tmp_path)
    assert sys2.runner._ex.net_position("ZEC") == pos
    assert sys2.runner._last_poll_mono is None                # resume forces a fresh poll


def test_reroll_registers_new_manifest_and_adopts(tmp_path):
    calls = {"prefetch": 0, "reset": 0}
    async def prefetch(wallets, s, e): calls["prefetch"] += 1
    sys = _build(tmp_path, prefetch=prefetch, reset=lambda: calls.__setitem__("reset", 1))
    rid1 = sys.run_id
    rid2 = asyncio.run(sys.reroll(t0_ms=20_000))               # next sub-period
    assert rid2 != rid1 and sys.t0_ms == 20_000
    assert sys.registry.committed(20_000) is not None          # new immutable manifest
    assert calls["prefetch"] == 1 and calls["reset"] == 1      # fresh train fetch + cache reset
    assert sys.runner._weights                                  # roster adopted into the runner


def test_roll_loop_fires_at_cadence(tmp_path):
    calls = {"n": 0}
    async def prefetch(wallets, s, e): calls["n"] += 1
    t0 = wall_ms() - int(1.5 * 86_400_000)                     # 1.5 days ago, 1-day cadence
    sys = _build(tmp_path, cfg=_cfg(roll_cadence_days=1), t0_ms=t0, prefetch=prefetch)
    for wlt in list(sys.runner._weights):
        sys.runner._watcher._pos[wlt] = {"ZEC": 5.0}
    async def drive():
        stop = asyncio.Event()
        task = asyncio.create_task(sys.run(stop=stop, tick_s=0.005, roll_check_s=0.005))
        await asyncio.sleep(0.08); stop.set()
        await asyncio.wait_for(task, timeout=2.0)
    asyncio.run(drive())
    assert calls["n"] >= 1                                      # the cadence loop rerolled


def test_async_run_smoke(tmp_path):
    sys = _build(tmp_path)
    for wlt in list(sys.runner._weights):
        sys.runner._watcher._pos[wlt] = {"ZEC": 5.0}
    async def drive():
        stop = asyncio.Event()
        task = asyncio.create_task(sys.run(stop=stop, tick_s=0.005, checkpoint_every=2))
        await asyncio.sleep(0.08)
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)            # feed torn down, clean exit
    asyncio.run(drive())
    assert sys.checkpoint_path.exists()                       # ran long enough to checkpoint
