"""Live wiring for the forward copy-trade paper experiment — the runnable entrypoint.

Composes the audited pieces into one system and LOCKS the contracts the audits demanded:
- the clock contract: wall-clock UNIX ms for book staleness (book ts are exchange ms) and
  a MONOTONIC source for the heartbeat — set here, never an arbitrary caller callable;
- the initial roll registers the sub-period's immutable manifest before any trade;
- on restart it resumes from the durable checkpoint (and forces a fresh poll first).

The data adapters (the HL info source for the watcher, the WS l2Book feed, and the
per-wallet train-return computation) are INJECTED so the wiring is testable without the
network — the live caller passes the real ones.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from babylon.exchange.websocket import WebSocketFeed
from babylon.execution.paper import PaperExecutor
from babylon.follow.experiment import ExperimentConfig, Registry
from babylon.follow.runner import FollowRunner, attach_l2_feed
from babylon.follow.scheduler import CutoffFn, ReturnsFn, RollScheduler
from babylon.follow.watcher import FillSource, WalletWatcher
from babylon.logging import get_logger
from babylon.sizing.sizer import FixedFractionSizer

log = get_logger("follow.live")

# t0_ms -> awaitable that readies all roll-time data (fresh candles + fills) for that T0
PrepareFn = Callable[[int], Awaitable[None]]


def wall_ms() -> int:
    """Book-staleness clock: wall-clock UNIX ms, matching the exchange book timestamps."""
    return int(time.time() * 1000)


def mono_ms() -> int:
    """Heartbeat/liveness clock: monotonic ms (immune to NTP steps)."""
    return int(time.monotonic() * 1000)


_DAY_MS = 86_400_000


@dataclass(slots=True)
class LiveFollowSystem:
    config: ExperimentConfig
    registry: Registry
    runner: FollowRunner
    feed: WebSocketFeed
    run_id: str
    checkpoint_path: Path
    scheduler: RollScheduler
    candidates: list[str]
    t0_ms: int
    prepare: PrepareFn | None = None   # ready roll-time data (fresh candles + fills) for a T0

    @classmethod
    def build(
        cls, *, config: ExperimentConfig, candidates: list[str], universe: list[str],
        source: FillSource, feed: WebSocketFeed, returns_fn: ReturnsFn, cutoff_fn: CutoffFn,
        t0_ms: int, budget_usd: float, registry_path: Path, checkpoint_path: Path,
        analysis_script_hash: str, poll_interval_s: float = 2.0,
        prepare: PrepareFn | None = None, max_roster_size: int | None = None,
    ) -> LiveFollowSystem:
        config.validate()
        registry = Registry(registry_path)
        scheduler = RollScheduler(candidates, returns_fn, cutoff_fn, config, registry,
                                  analysis_script_hash=analysis_script_hash,
                                  max_roster_size=max_roster_size)
        prior = registry.latest()
        if prior is not None:
            # RESUME the latest committed sub-period — do NOT re-roll (the registry is the
            # source of truth; re-ranking on a restart would conflict with the immutable
            # manifest and crash-loop). The checkpoint restores positions below.
            weights, run_id, t0_ms = prior.edge_weights, prior.run_id(), prior.t0_ms
            roster = list(weights)
            log.info("live.resume_roster", run_id=run_id, t0_ms=t0_ms, n=len(roster))
        else:
            roster, weights, run_id = scheduler.roll(t0_ms)    # first roll → immutable manifest
        watcher = WalletWatcher(source, roster, min_interval_s=poll_interval_s)
        sizer = FixedFractionSizer(per_coin_fraction=config.max_coin_frac)
        executor = PaperExecutor(taker_fee_bps=config.fee_bps, mode=config.execution,
                                 impact_bps=config.impact_bps, max_depth_frac=config.max_depth_frac)
        runner = FollowRunner(watcher, weights, universe, sizer, executor,
                              budget_usd=budget_usd, max_coin_frac=config.max_coin_frac,
                              min_rebalance_usd=2.0)  # diffuse consensus → small per-coin targets
        attach_l2_feed(runner, feed, universe)
        if checkpoint_path.exists():
            runner.from_state(json.loads(checkpoint_path.read_text()))
            log.info("live.resumed", run_id=run_id, checkpoint=str(checkpoint_path))
        return cls(config, registry, runner, feed, run_id, checkpoint_path, scheduler,
                   list(candidates), t0_ms, prepare)

    async def reroll(self, t0_ms: int) -> str:
        """Roll the next sub-period (§v4.4): ready the fresh train-window data (candles +
        fills), re-rank, register the new immutable manifest, and adopt the new roster into
        the running loop. Returns the new run_id."""
        if self.prepare is not None:
            await self.prepare(t0_ms)
        _roster, weights, run_id = self.scheduler.roll(t0_ms)
        self.runner.adopt_roster(weights, since_ms=t0_ms)
        self.run_id = run_id
        self.t0_ms = t0_ms
        return run_id

    async def run(self, *, stop: asyncio.Event | None = None, tick_s: float = 2.0,
                  checkpoint_every: int = 30, roll_check_s: float = 3600.0) -> None:
        """Run the WS feed, the trading loop, and the roll-cadence loop concurrently under
        one stop. The locked clocks are passed here; the feed is torn down when the runner
        exits."""
        stop = stop or asyncio.Event()

        async def _drive() -> None:
            try:
                await self.runner.run(
                    wall_ms, mono_ms, tick_s=tick_s, checkpoint_path=self.checkpoint_path,
                    checkpoint_every=checkpoint_every, stop=stop)
            finally:
                self.feed.stop()
                stop.set()

        await asyncio.gather(self.feed.run(), _drive(), self._roll_loop(stop, roll_check_s))

    async def _roll_loop(self, stop: asyncio.Event, check_s: float) -> None:
        cadence_ms = self.config.roll_cadence_days * _DAY_MS
        next_roll = self.t0_ms + cadence_ms
        try:
            while not stop.is_set():
                if wall_ms() >= next_roll:
                    try:
                        await self.reroll(next_roll)
                    except Exception as exc:  # noqa: BLE001 — a failed roll must not kill the run
                        log.error("reroll.failed", t0_ms=next_roll, error=str(exc))
                    next_roll += cadence_ms
                try:
                    await asyncio.wait_for(stop.wait(), timeout=check_s)
                except (TimeoutError, asyncio.TimeoutError):
                    pass
        finally:
            stop.set()
