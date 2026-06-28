"""The backtest driver.

Pumps a replayed L2 stream through the **real** ``engine._tick()`` pipeline — no
trading logic is re-implemented. The only thing replaced is the wall-clock
``run()`` loop, here a deterministic event-time driver.

Scheduling (per ``docs/BACKTEST.md`` §4 + §8b, from the audit):
- **Peek-based**: a tick at ``next_tick`` fires only when the next event's time is
  strictly greater, so the tick sees exactly the events with ``time ≤ next_tick``
  (resolves the same-millisecond off-by-one).
- **Gap-aware**: an inter-event gap beyond ``max_gap_ms`` SUPPRESSES catch-up ticks
  (jump ``next_tick`` past the gap) — never replay an empty grid on a frozen book.
- **Staleness guard**: a coin with no fresh book within ``max_staleness_ms`` is
  evicted from ``MarketView`` and the executor (looks ABSENT, doesn't trade stale).
- **Warmup**: after ``warmup`` ticks the measurement layer is reset, so warmup ticks
  (strategies still filling their windows) don't pollute the equity curve.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from babylon.backtest.config import BacktestConfig
from babylon.data.replay import L2Replay
from babylon.engine.clock import SimClock
from babylon.engine.engine import Engine
from babylon.execution.backtest import BacktestExecutor
from babylon.execution.fill_model import FILL_MODEL_VERSION
from babylon.logging import get_logger
from babylon.stats.gate import GateResult, log_growth_gate
from babylon.stats.metrics import Metrics
from babylon.stats.monitor import ACCOUNT

log = get_logger("backtest")

HONESTY_FLAGS = (
    "L2-only archive: no trade prints, no funding modeled, no oracle/mark.",
    "Taker-only fills at the decision-time book (zero-latency) — optimistic.",
    "Edge series is mid-based + half-spread on turnover; not a maker/passive model.",
    "No liquidation/margin model — ruinous paths are not terminated.",
    "A backtest SEEDS A WEAK PRIOR / SANITY-CHECKS; it is NOT validation.",
    "Fast iteration risks overfitting — treat one run as one of many trials; the "
    "gate applies NO multiple-testing correction across a sweep.",
    "The 'edge real?' gate is ADVISORY: trust it only when n is well above ~30, and "
    "it understates risk on strongly autocorrelated returns (a pass can still be a "
    "false positive). A no-trade run reports nothing, not a verdict.",
)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    coins: list[str]
    start: str
    end: str
    interval_ms: int
    warmup: int
    n_events: int
    n_ticks: int
    skipped_books: int
    gaps: int
    fills: int
    no_fills: int
    avg_depth_fraction: float
    max_depth_fraction: float
    no_fill_reasons: dict[str, int]
    net_exposure_notional_hours: float
    account: Metrics | None
    per_strategy: dict[str, Metrics]
    gates: dict[str, GateResult]
    traded: bool  # any fills at all — a no-trade run has no metrics, not a broken report
    aborted: bool = False  # invariant break mid-run (results are not trustworthy)
    warmup_incomplete: bool = False  # warmup >= total ticks → no measured window
    no_fill_rate: float = 0.0  # fraction of order attempts that couldn't fill
    fill_model_version: int = FILL_MODEL_VERSION
    honesty: tuple[str, ...] = HONESTY_FLAGS


class Backtester:
    def __init__(
        self,
        engine: Engine,
        executor: BacktestExecutor,
        replay: L2Replay,
        clock: SimClock,
        config: BacktestConfig,
    ) -> None:
        self._engine = engine
        self._executor = executor
        self._replay = replay
        self._clock = clock
        self._cfg = config

    def run(self) -> BacktestResult:
        eng = self._engine
        cfg = self._cfg
        eng.start()
        # "warmed" once the warmup window is dropped; warmup=0 means measure everything.
        self._warmed = cfg.warmup == 0

        next_tick: int | None = None
        last_event_t: int | None = None
        last_update: dict[str, int] = {}
        n_events = n_ticks = gaps = 0
        exposure_nh = 0.0
        aborted = False

        for ev in self._replay.events():
            t = ev.time
            # Gap → suppress the empty catch-up grid (don't tick a frozen book), AND
            # invalidate the engine's per-coin price baseline so the first post-gap
            # tick doesn't book the whole gap's move as one period return (a giant
            # outlier into the EdgeModel + equity curve).
            if last_event_t is not None and t - last_event_t > cfg.max_gap_ms:
                next_tick = t + cfg.interval_ms
                eng._prev_mid.clear()
                gaps += 1
            if next_tick is None:
                next_tick = t + cfg.interval_ms
            # Fire every tick strictly before this event (book = events with time ≤ tick).
            while next_tick < t:
                exposure_nh += self._tick(next_tick, last_update, n_ticks)
                n_ticks += 1
                next_tick += cfg.interval_ms
                # The engine sets _stop on a ledger≠executor invariant break. The
                # paper loop watches _stop; this driver must too, or a desync would
                # silently corrupt every subsequent tick. Abort loudly.
                if eng._stop.is_set():
                    log.error("backtest.aborted_invariant_break", tick=n_ticks)
                    aborted = True
                    break
            if aborted:
                break
            # Apply this event into the market + the executor's depth book (atomically).
            eng._market.update(ev.coin, Decimal(str(ev.book.best_bid)),
                               Decimal(str(ev.book.best_ask)))
            self._executor.set_book(ev.coin, ev.book)
            last_update[ev.coin] = t
            last_event_t = t
            n_events += 1

        return self._result(n_events, n_ticks, gaps, exposure_nh, aborted)

    def _tick(self, now: int, last_update: dict[str, int], n_ticks: int) -> float:
        eng = self._engine
        cfg = self._cfg
        # Staleness guard: evict coins with no fresh book (look absent, don't trade
        # stale). Also drop the price baseline so a returning coin doesn't book the
        # whole stale window as one period. A HELD position is still marked to its
        # last-known price (engine._last_mark), so its PnL doesn't flicker out.
        for coin in list(eng._coins):
            seen = last_update.get(coin)
            if seen is None or now - seen > cfg.max_staleness_ms:
                eng._market.evict(coin)
                eng._prev_mid.pop(coin, None)
        self._clock.advance_to(now)
        eng._tick()
        if eng._kill is not None and eng._tick_id % eng._snapshot_every == 0:
            eng._evaluate_kills(now)
        # Warmup boundary: drop warmup ticks from the measured curve. Also clear the
        # engine's last-sample cache, else a flat post-warmup equity equal to the
        # stale pre-reset value would be deduped away (→ 0 samples → None metrics).
        if n_ticks + 1 == cfg.warmup:
            eng._perf.reset()
            eng._last_perf_sample = {}
            eng._net_risk.rebaseline()  # measure account DD from the post-warmup peak too
            self._warmed = True
        # Net-exposure integral (bounds the unmodeled funding).
        notional = 0.0
        for coin, pos in self._executor.net_positions().items():
            mark = eng._market.mark(coin)
            if mark is not None:
                notional += abs(float(pos) * float(mark))
        return notional * (cfg.interval_ms / 3_600_000.0)

    def _result(
        self, n_events: int, n_ticks: int, gaps: int, exposure_nh: float, aborted: bool
    ) -> BacktestResult:
        eng = self._engine
        rng = np.random.default_rng(self._cfg.seed)
        per_strategy: dict[str, Metrics] = {}
        gates: dict[str, GateResult] = {}
        # If warmup never completed (warmup >= total ticks) the measured window is
        # entirely warmup ticks — report no metrics rather than warmup-polluted ones.
        if self._warmed:
            for s in eng._strategies:
                m = eng._perf.metrics(s.name)
                if m is not None:
                    per_strategy[s.name] = m
                gates[s.name] = log_growth_gate(eng._perf.unit_returns(s.name), rng)
        account = eng._perf.metrics(ACCOUNT) if self._warmed else None
        fracs = self._executor.depth_fractions
        attempts = self._executor.fills + self._executor.no_fills
        return BacktestResult(
            coins=list(eng._coins), start=self._cfg.start, end=self._cfg.end,
            interval_ms=self._cfg.interval_ms, warmup=self._cfg.warmup,
            n_events=n_events, n_ticks=n_ticks, skipped_books=self._replay.skipped, gaps=gaps,
            fills=self._executor.fills, no_fills=self._executor.no_fills,
            avg_depth_fraction=float(np.mean(fracs)) if fracs else 0.0,
            max_depth_fraction=float(np.max(fracs)) if fracs else 0.0,
            no_fill_reasons=dict(self._executor.no_fill_reasons),
            net_exposure_notional_hours=exposure_nh,
            account=account, per_strategy=per_strategy, gates=gates,
            traded=self._executor.fills > 0, aborted=aborted,
            warmup_incomplete=not self._warmed,
            no_fill_rate=(self._executor.no_fills / attempts) if attempts else 0.0,
        )
