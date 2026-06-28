"""The orchestrating engine.

Within-tick phase order (see ``docs/ARCHITECTURE.md``), on a timer cadence over
the live feed:

  1. (market data applied to MarketView by the feed handler, between ticks)
  2. update each EdgeModel with last interval's realized **net-of-fee unit return**
     (direction taken from the actual virtual position, so a quiet strategy can't
     keep accruing a stale signal's returns)
  3. strategies emit directions → Sizer → per-strategy Risk → raw targets
     (each strategy isolated; a thrower is quarantined, never poisons the tick)
  4. Net Risk Manager returns ONE uniform scale; apply it to every target so the
     virtual ledgers stay reconciled to the real net
  5. Reconciler diffs scaled net vs actual → orders
  6. Executor fills → attribute (exact residual) back to ledgers → on_fill, then
     assert ledger net == executor net

Heavy stats run inline at the (slow) tick cadence; moving them off-loop is the
planned hardening.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import numpy as np

from babylon.core import Fill
from babylon.data.models import L2Book
from babylon.engine.clock import Clock
from babylon.engine.context import Context, MarketView
from babylon.exchange.feed import Feed
from babylon.exchange.websocket import Subscription
from babylon.execution.base import Executor
from babylon.execution.fill_model import TAKER_FEE  # taker fee, single source of truth
from babylon.logging import get_logger
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.exposure import BookExposure, ExposureMonitor
from babylon.risk.killswitch import KillSwitch
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.edge import EdgeModel
from babylon.sizing.sizer import Sizer
from babylon.stats.decay import EdgeTracker
from babylon.stats.monitor import ACCOUNT, PerformanceMonitor
from babylon.strategy.base import Strategy

log = get_logger("engine")

QUARANTINE_AFTER = 3  # consecutive strategy failures before it's benched


class Engine:
    def __init__(
        self,
        *,
        feed: Feed,
        market: MarketView,
        strategies: Sequence[Strategy],
        sizer: Sizer,
        risk: RiskManager,
        net_risk: NetRiskManager,
        reconciler: Reconciler,
        executor: Executor,
        ledger: Ledger,
        clock: Clock,
        budgets: dict[str, float],
        rng: np.random.Generator,
        interval_s: float = 2.0,
        exposure: ExposureMonitor | None = None,
        run_id: str = "",
        journal: Any = None,
        seed: int = 0,
        snapshot_every: int = 10,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self._feed = feed
        self._run_id = run_id
        self._journal = journal
        self._seed = seed
        self._snapshot_every = snapshot_every
        self._tick_id = 0
        self._market = market
        self._strategies = strategies
        self._by_name = {s.name: s for s in strategies}
        self._sizer = sizer
        self._risk = risk
        self._net_risk = net_risk
        self._reconciler = reconciler
        self._executor = executor
        self._ledger = ledger
        self._clock = clock
        self._budgets = budgets
        # Per-strategy equity curves only cross-foot to the account when budgets
        # sum to 1 (Σ base = start). Enforce it — else per-strategy kill thresholds
        # are computed against a wrong notional base. (Model a cash reserve as an
        # explicit budget bucket if you want Σ<1.)
        total_budget = sum(budgets.get(s.name, 0.0) for s in strategies)
        if abs(total_budget - 1.0) > 1e-6:
            raise ValueError(
                f"strategy budgets must sum to 1.0 (got {total_budget}); "
                "every strategy must be present in `budgets`"
            )
        self._interval = interval_s
        self._exposure_mon = exposure or ExposureMonitor()
        self._exposure: BookExposure | None = None
        self._perf = PerformanceMonitor()
        self._last_perf_sample: dict[str, float] = {}
        self._last_mark: dict[str, Decimal] = {}  # last-known price per coin, for MTM
        self._kill = kill_switch
        self._trackers: dict[str, EdgeTracker] = {s.name: EdgeTracker() for s in strategies}
        self._stop = asyncio.Event()
        self._fills = 0

        self._coins = sorted({c for s in strategies for c in s.universe})
        # Independent child RNG per strategy, keyed to the SORTED strategy name so
        # the prior draws are invariant to --coin/strategy ORDER (reproducibility).
        ordered = sorted(strategies, key=lambda s: s.name)
        children = dict(zip([s.name for s in ordered], rng.spawn(len(ordered)), strict=True))
        self._edges: dict[tuple[str, str], EdgeModel] = {
            (s.name, c): s.make_edge_model(c, children[s.name])
            for s in strategies
            for c in s.universe
        }
        self._prev_mid: dict[str, float] = {}
        self._edge_dir: dict[tuple[str, str], int] = {}  # last edge direction, for fee-on-turnover
        self._fail_count: dict[str, int] = {}
        self._quarantined: set[str] = set()
        self._last_applied_seq = 0  # journal offset of the last applied event
        self._halted_prev = False  # net-risk halt edge-detect (journal on transition)

    def stop(self) -> None:
        self._stop.set()

    @property
    def fills(self) -> int:
        return self._fills

    @property
    def exposure(self) -> BookExposure | None:
        """Latest book exposure snapshot (net directional, concentration, neutrality)."""
        return self._exposure

    @property
    def performance(self) -> PerformanceMonitor:
        """Per-strategy + account equity curves and their tail-aware metrics."""
        return self._perf

    def _strategy_equities(self, marks: dict[str, Decimal], equity: Decimal) -> dict[str, float]:
        """Mark-to-market equity per strategy (budget base + realized + unrealized)
        plus the account total — the curves the measurement layer judges."""
        pnl: dict[str, Decimal] = {}
        for s, c, size, entry, realized in self._ledger.positions():
            pnl[s] = pnl.get(s, Decimal(0)) + realized
            if c in marks:
                pnl[s] += (marks[c] - entry) * size
        start = self._ledger.starting_equity
        out: dict[str, float] = {ACCOUNT: float(equity)}
        for strat in self._strategies:
            base = Decimal(str(self._budgets.get(strat.name, 0.0))) * start
            out[strat.name] = float(base + pnl.get(strat.name, Decimal(0)))
        return out

    # --- durable state (snapshot / restore) ----------------------------------

    def capture_state(self) -> dict[str, Any]:
        """Full recoverable state at the current `last_applied_seq` cut. Exact
        Decimal for money (the recovery-critical path)."""
        return {
            "last_applied_seq": self._last_applied_seq,
            "ledger": self._ledger.to_state(),
            "edges": {f"{s}\t{c}": m.to_state() for (s, c), m in self._edges.items()},
            "netrisk": self._net_risk.to_state(),
            "quarantined": sorted(self._quarantined),
            "edge_dir": [[s, c, d] for (s, c), d in self._edge_dir.items()],
            "prev_mid": dict(self._prev_mid),
        }

    def record_snapshot(self, journal: Any, now: int) -> None:
        """Register the strategies + persist the state snapshot + refresh the
        per-strategy positions cache, all to the journal. Records which positions
        currently belong to which strategy (history lives in the fills table)."""
        for strat in self._strategies:
            journal.register_strategy(
                strat.name,
                universe=strat.universe,
                budget=Decimal(str(self._budgets.get(strat.name, 0.0))),
                status="quarantined" if strat.name in self._quarantined else "paper",
                now=now,
            )
        state = self.capture_state()
        blob = json.dumps(state).encode()
        journal.snapshot(
            run_id=self._run_id, applied_seq=state["last_applied_seq"], ts_ms=now,
            parts={("engine", ""): blob},
        )
        journal.write_positions(
            applied_seq=state["last_applied_seq"], ts_ms=now, rows=self._ledger.positions()
        )

    def restore_state(self, state: dict[str, Any]) -> None:
        """Rebuild in-memory state from a snapshot. For paper, the executor net is
        derived from the restored ledger (single rounding → invariant holds)."""
        self._last_applied_seq = int(state["last_applied_seq"])
        self._ledger = Ledger.from_state(state["ledger"])
        for key, est in state["edges"].items():
            s, c = key.split("\t", 1)
            model = self._edges.get((s, c))
            if model is not None:
                model.from_state(est)
        self._net_risk.from_state(state["netrisk"])
        self._quarantined = set(state["quarantined"])
        self._edge_dir = {(s, c): int(d) for s, c, d in state["edge_dir"]}
        self._prev_mid = dict(state.get("prev_mid", {}))
        for coin in self._coins:
            self._executor.set_position(coin, self._ledger.net_position(coin))

    async def _on_book(self, data: dict[str, Any]) -> None:
        book = L2Book.from_ws(data)
        if book.best_bid is not None and book.best_ask is not None:
            self._market.update(book.coin, book.best_bid, book.best_ask)

    def start(self) -> None:
        """Bootstrap sequence shared by run() and the backtest driver: journal
        connect → recover → begin_run (ordering matters — recover validates the
        fingerprint and rebuilds the ledger before on_start reflects it), then the
        strategy on_start fan-out. Backtest passes journal=None → reduces to on_start."""
        if self._journal is not None:
            # Journal lives on this (the event-loop) thread; the brief FULL-fsync
            # per order/fill is acceptable at paper cadence. Off-loop single-writer
            # thread is the documented live optimisation.
            self._journal.connect()
            self._recover()
            self._journal.begin_run(
                self._run_id, started_ms=self._clock.now(), network="",
                seed=self._seed, roster=[s.name for s in self._strategies],
            )
        for s in self._strategies:
            s.on_start(self._context(s, {}, self._ledger_equity({})))

    async def run(self) -> None:
        self._feed.on("l2Book", self._on_book)
        for c in self._coins:
            self._feed.subscribe(Subscription(type="l2Book", coin=c))
        self.start()
        feed_task = asyncio.create_task(self._feed.run())
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self._interval)
                try:
                    self._tick()
                    if self._tick_id % self._snapshot_every == 0:
                        if self._kill is not None:
                            self._evaluate_kills(self._clock.now())
                        if self._journal is not None:
                            self.record_snapshot(self._journal, self._clock.now())
                except Exception:  # noqa: BLE001 — last-resort guard; per-strategy isolation is inside
                    log.exception("engine.tick_error")
        finally:
            self._stop.set()
            self._feed.stop()
            for s in self._strategies:
                s.on_stop(self._context(s, {}, self._ledger_equity({})))
            if self._journal is not None:
                self.record_snapshot(self._journal, self._clock.now())
                self._journal.close()
            await asyncio.gather(feed_task, return_exceptions=True)

    def _recover(self) -> None:
        """Restore the latest snapshot + replay events since, on boot. Paper: the
        executor net is derived from the restored ledger."""
        snap = self._journal.latest_snapshot()
        if snap is None:
            return
        applied_seq, snap_run_id, parts = snap
        blob = parts.get(("engine", ""))
        if blob is None:
            return
        # Validate the fingerprint of the run that OWNS this snapshot (not merely
        # the newest run). On mismatch, ABORT the boot — never trade from flat
        # while the journal holds real positions (that would shadow them).
        owner = self._journal.run_meta(snap_run_id)
        if owner is not None and (
            owner["seed"] != self._seed
            or owner["roster"] != sorted(s.name for s in self._strategies)
        ):
            raise RuntimeError(
                "journal fingerprint mismatch (seed/roster) — refusing to start; "
                "the journal holds positions from a different configuration"
            )
        self.restore_state(json.loads(blob))
        # Replay events after the snapshot cut: FILLs advance the ledger; the
        # latch transitions (QUARANTINE/HALT) re-arm — both lost otherwise.
        for seq, kind, payload in self._journal.replay_events(applied_seq):
            if kind == "FILL":
                p = json.loads(payload)
                price = Decimal(p["price"])
                for strat, size in p["shares"].items():
                    self._ledger.apply_fill(strat, p["coin"], Decimal(size), price)
            elif kind == "QUARANTINE":
                self._quarantined.add(json.loads(payload)["strategy"])
            elif kind == "HALT":
                self._net_risk.mark_halted()
            elif kind == "RESET":
                self._net_risk.reset()
                self._quarantined.clear()
            self._last_applied_seq = seq
        # Reconcile edge direction to the REPLAYED positions (a post-snapshot fill
        # may have flipped a coin) so the next tick doesn't mis-charge a turnover.
        for (strat, coin) in self._edge_dir:
            pos = self._ledger.position(strat, coin)
            self._edge_dir[(strat, coin)] = 1 if pos > 0 else -1 if pos < 0 else 0
        for coin in self._coins:
            self._executor.set_position(coin, self._ledger.net_position(coin))
        log.info("engine.recovered", applied_seq=self._last_applied_seq,
                 halted=self._net_risk_halted())

    def _net_risk_halted(self) -> bool:
        return bool(self._net_risk.to_state().get("halted"))

    def _evaluate_kills(self, now: int) -> None:
        """Consult the kill switch on the measurement layer (slow cadence): demote
        (→ quarantine) breached/decayed strategies; halt the account on DD/CVaR."""
        if self._kill is None:
            return
        strat_metrics = {}
        decayed = {}
        for strat in self._strategies:
            m = self._perf.metrics(strat.name)
            if m is not None:
                strat_metrics[strat.name] = m
            decayed[strat.name] = self._trackers[strat.name].decayed()
        decision = self._kill.evaluate(
            strat_metrics=strat_metrics,
            account_metrics=self._perf.metrics(ACCOUNT),
            edge_decayed=decayed,
        )
        for name in decision.demote:
            if name not in self._quarantined:
                self._quarantined.add(name)
                log.warning("kill.demote", strategy=name, reason=decision.reasons.get(name))
                if self._journal is not None:
                    self._journal.record_event(
                        "QUARANTINE", {"strategy": name, "reason": decision.reasons.get(name)},
                        run_id=self._run_id, tick=self._tick_id, now=now, wall=now, strategy=name)
        if decision.halt and not self._net_risk_halted():
            self._net_risk.mark_halted()
            log.warning("kill.halt", reason=decision.reasons.get(ACCOUNT))
            if self._journal is not None:
                self._journal.record_event(
                    "HALT", {"reason": decision.reasons.get(ACCOUNT)}, run_id=self._run_id,
                    tick=self._tick_id, now=now, wall=now)
        self._halted_prev = self._net_risk_halted()

    def _ledger_equity(self, marks: dict[str, Decimal]) -> Decimal:
        return self._ledger.equity(marks)

    def _context(self, strat: Strategy, marks: dict[str, Decimal], equity: Decimal) -> Context:
        positions = {c: self._ledger.position(strat.name, c) for c in strat.universe}
        return Context(
            strategy=strat.name,
            clock=self._clock,
            market=self._market,
            positions=positions,
            equity=equity,
        )

    def _tick(self) -> None:
        self._tick_id += 1
        now = self._clock.now()
        marks = self._market.marks(self._coins)
        if not marks:
            return
        # Trading uses only FRESH marks. For mark-to-market (equity/measurement),
        # carry the last-known price of any coin without a fresh quote so a held
        # position's PnL doesn't vanish from the curve while its feed is quiet/stale.
        self._last_mark.update(marks)
        mtm = dict(marks)
        for coin in self._coins:
            if coin not in mtm and coin in self._last_mark:
                mtm[coin] = self._last_mark[coin]

        self._update_edges(marks)
        equity = self._ledger.equity(mtm)

        # Phase 3: per-strategy directions → sizing → per-asset risk → raw targets.
        # Each strategy is isolated; a thrower holds its position and is benched.
        targets: dict[tuple[str, str], Decimal] = {}
        for strat in self._strategies:
            held = {c: self._ledger.position(strat.name, c) for c in strat.universe}
            if strat.name in self._quarantined:
                targets.update({(strat.name, c): held[c] for c in strat.universe})
                continue
            try:
                budget_equity = equity * Decimal(str(self._budgets.get(strat.name, 0.0)))
                ctx = self._context(strat, marks, equity)
                strat.on_bar(ctx)
                signals = ctx.collected()
                for coin in strat.universe:
                    if coin not in signals or coin not in marks:
                        targets[(strat.name, coin)] = held[coin]
                        continue
                    edge = self._edges[(strat.name, coin)].estimate()
                    raw = self._sizer.target_size(
                        edge=edge,
                        direction=signals[coin],
                        budget_equity=budget_equity,
                        mark_price=marks[coin],
                    )
                    targets[(strat.name, coin)] = self._risk.clamp_target(
                        raw, mark=marks[coin], budget_equity=budget_equity
                    )
                self._fail_count[strat.name] = 0
            except Exception:  # noqa: BLE001 — isolate one bad strategy from the rest
                self._fail_count[strat.name] = self._fail_count.get(strat.name, 0) + 1
                log.exception("engine.strategy_error", strategy=strat.name)
                for coin in strat.universe:
                    targets.setdefault((strat.name, coin), held[coin])
                if (self._fail_count[strat.name] >= QUARANTINE_AFTER
                        and strat.name not in self._quarantined):
                    self._quarantined.add(strat.name)
                    log.error("engine.quarantine", strategy=strat.name)
                    if self._journal is not None:  # durable latch (replayed on recovery)
                        self._journal.record_event(
                            "QUARANTINE", {"strategy": strat.name}, run_id=self._run_id,
                            tick=self._tick_id, now=now, wall=now, strategy=strat.name)

        # Phase 4: ONE uniform Net-Risk scale, applied to every strategy's target,
        # so per-strategy virtual positions stay reconciled to the real net.
        net_notional = Decimal(0)
        for coin in self._coins:
            if coin not in marks:
                continue
            net = sum((sz for (_s, c), sz in targets.items() if c == coin), Decimal(0))
            net_notional += abs(net) * marks[coin]
        gross_notional = sum(
            (abs(sz) * marks[c] for (_s, c), sz in targets.items() if c in marks),
            Decimal(0),
        )
        review = self._net_risk.review(
            net_notional=net_notional, gross_notional=gross_notional, equity=equity
        )
        if review.halted and not self._halted_prev and self._journal is not None:
            self._journal.record_event(  # durable halt latch (replayed on recovery)
                "HALT", {"drawdown": review.drawdown}, run_id=self._run_id,
                tick=self._tick_id, now=now, wall=now)
        self._halted_prev = review.halted
        scale = Decimal(str(review.scale))
        scaled = {k: sz * scale for k, sz in targets.items()}

        # Phase 5+6: reconcile scaled net vs actual → orders → fills → attribute.
        net_targets: dict[str, Decimal] = {}
        for (_s, coin), sz in scaled.items():
            net_targets[coin] = net_targets.get(coin, Decimal(0)) + sz
        actual = {c: self._executor.net_position(c) for c in self._coins}
        orders = self._reconciler.diff(
            net_targets=net_targets, actual=actual, marks=marks
        )
        for order in orders:
            quote = self._market.quote(order.coin)
            if quote is None:
                continue  # drop quote-less orders BEFORE journaling (no PENDING orphan)
            # The share split is independent of fill price, so compute it from the
            # order; journal the order + its intended vector BEFORE the send.
            provisional = Fill(coin=order.coin, size=order.size, price=quote.mid,
                               time=now, cloid=order.cloid)
            shares = self._compute_shares(provisional, scaled)
            order_id = 0
            if self._journal is not None:
                order_id = self._journal.record_order(
                    order, dict(shares), run_id=self._run_id, tick=self._tick_id, now=now, wall=now)
            try:
                fill = self._executor.submit(order, quote, now)
            except Exception:  # noqa: BLE001 — an executor failure must not desync state
                log.exception("engine.submit_error", coin=order.coin)
                continue
            if fill is None:
                continue
            self._apply_shares(fill, shares)
            self._fills += 1
            # Validate BEFORE persisting (don't journal a known-bad fill).
            if self._ledger.net_position(order.coin) != self._executor.net_position(order.coin):
                log.error(
                    "engine.invariant_break", coin=order.coin,
                    ledger=str(self._ledger.net_position(order.coin)),
                    executor=str(self._executor.net_position(order.coin)),
                )
                self._stop.set()
                continue
            if self._journal is not None:
                self._last_applied_seq = self._journal.record_fill(
                    order_id=order_id, cloid=fill.cloid, coin=fill.coin, price=fill.price,
                    shares=shares, run_id=self._run_id, tick=self._tick_id, now=now, wall=now)
                # Keep the positions cache LIVE (per fill, not just at snapshot).
                self._journal.write_positions(
                    applied_seq=self._last_applied_seq, ts_ms=now,
                    rows=[(s, order.coin, *self._ledger.position_detail(s, order.coin))
                          for s, _ in shares],
                )

        # Measure the actual book we now hold (tracks; does not enforce).
        self._exposure = self._exposure_mon.assess(
            self._executor.net_positions(), mtm, equity
        )
        # Sample per-strategy + account equity for the measurement layer — but only
        # when something actually changed (a stale tick with no new mark/fill would
        # inject a spurious 0-return period, diluting log-growth).
        eqs = self._strategy_equities(mtm, equity)
        if eqs != self._last_perf_sample:
            self._perf.sample(eqs)
            self._last_perf_sample = eqs

        log.info(
            "engine.tick",
            equity=float(equity),
            net=self._executor.net_positions(),
            dd=round(review.drawdown, 4),
            halted=review.halted,
            fills=self._fills,
            leverage=round(self._exposure.net_leverage, 3),
            bias=round(self._exposure.directional_bias, 3),
            neutrality=round(self._exposure.neutrality, 3),
            top=f"{self._exposure.top_coin}:{round(self._exposure.top_concentration, 3)}",
        )

    def _update_edges(self, marks: dict[str, Decimal]) -> None:
        """Feed each EdgeModel last interval's net-of-fee unit return. Direction is
        the sign of the actual virtual position (auto-resets when flat); a turnover
        (direction change) is charged the round-trip taker fee."""
        per_strat: dict[str, list[float]] = {}
        for coin, mark in marks.items():
            prev = self._prev_mid.get(coin)
            cur = float(mark)
            if prev is not None and prev > 0:
                period_ret = cur / prev - 1.0
                for strat in self._strategies:
                    if coin not in strat.universe:
                        continue
                    pos = self._ledger.position(strat.name, coin)
                    direction = 1 if pos > 0 else -1 if pos < 0 else 0
                    key = (strat.name, coin)
                    prev_dir = self._edge_dir.get(key, 0)
                    if direction != 0:
                        unit = direction * period_ret
                        if direction != prev_dir:  # turnover this interval → cost drag
                            sides = 2 if prev_dir != 0 else 1
                            # Fee AND the half-spread crossed per side — else the edge
                            # series is mid-based/spread-blind and the prior optimistic.
                            unit -= sides * (TAKER_FEE + self._half_spread_ret(coin))
                        self._edges[key].update(unit)
                        per_strat.setdefault(strat.name, []).append(unit)
                    self._edge_dir[key] = direction
            self._prev_mid[coin] = cur
        # Per-strategy unit return = mean across its held coins (size-independent),
        # logged separately for the edge gate, and fed to the decay tracker.
        if per_strat:
            units = {s: sum(v) / len(v) for s, v in per_strat.items()}
            self._perf.record_unit_returns(units)
            for s, r in units.items():
                self._trackers[s].update(r)

    def _half_spread_ret(self, coin: str) -> float:
        """Half-spread as a fraction of mid (the per-side cost of crossing)."""
        q = self._market.quote(coin)
        if q is None or q.mid <= 0:
            return 0.0
        return float((q.ask - q.bid) / 2 / q.mid)

    def _compute_shares(
        self, fill: Fill, scaled: dict[tuple[str, str], Decimal]
    ) -> list[tuple[str, Decimal]]:
        """Pure: the per-strategy share vector for a fill — no mutation. This is the
        single source of attribution, so the journal can persist the exact vector
        and recovery reproduces identical booking.

        Shares are pro-rata by each strategy's scaled requested delta, each QUANTIZED
        to the lot grid; the last (largest |delta|, name tiebreak — deterministic, NOT
        dict order) takes the exact residual. Quantizing every share keeps each
        strategy's position an exact lot multiple, so the ledger's per-strategy
        re-summation (Ledger.net_position) is lossless and stays bit-equal to the
        executor's running net — otherwise 28-digit pro-rata Decimals re-summed by
        strategy drift apart and trip the invariant on multi-strategy-on-one-coin.
        Pure pro-rata is correct for FULL fills (paper); partial fills need the
        same-sign-fills-first rule — a [LIVE] TODO.
        """
        coin = fill.coin
        lot = self._reconciler.lot
        deltas = [
            (s, scaled[(s, c)] - self._ledger.position(s, coin))
            for (s, c) in scaled
            if c == coin
        ]
        total = sum((d for _s, d in deltas), Decimal(0))
        if total == 0:
            return []
        movers = sorted(
            ((s, d) for s, d in deltas if d != 0), key=lambda sd: (abs(sd[1]), sd[0])
        )
        shares: list[tuple[str, Decimal]] = []
        allocated = Decimal(0)
        for i, (strat, d) in enumerate(movers):
            if i == len(movers) - 1:
                share = fill.size - allocated  # exact residual (also lot-aligned)
            else:
                share = (fill.size * d / total).quantize(lot, rounding=ROUND_HALF_EVEN)
                allocated += share
            shares.append((strat, share))
        return shares

    def _apply_shares(self, fill: Fill, shares: list[tuple[str, Decimal]]) -> None:
        """Apply a computed share vector to the ledgers and notify strategies."""
        for strat, share in shares:
            self._ledger.apply_fill(strat, fill.coin, share, fill.price)
            s = self._by_name.get(strat)
            if s is not None:
                s.on_fill(
                    Fill(
                        coin=fill.coin,
                        size=share,
                        price=fill.price,
                        time=fill.time,
                        cloid=fill.cloid,
                        strategy=strat,
                    )
                )

    def _attribute(self, fill: Fill, scaled: dict[tuple[str, str], Decimal]) -> None:
        """Compute + apply (used by the non-journal path / tests)."""
        self._apply_shares(fill, self._compute_shares(fill, scaled))
