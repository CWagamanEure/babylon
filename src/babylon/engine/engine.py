"""The orchestrating engine.

Drives the within-tick phase order from ``docs/ARCHITECTURE.md`` on a timer
cadence over the live feed:

  1. (market data is applied to MarketView by the feed handler, between ticks)
  2. update each EdgeModel with the realized **unit return** of last tick's signal
  3. strategies emit directions → Sizer → per-strategy Risk → targets
  4. net targets per coin → Net Risk Manager
  5. Reconciler diffs vs actual → orders
  6. Executor fills → attribute pro-rata back to strategy ledgers

Heavy stats run inline here at the (slow) tick cadence; moving them fully
off-loop is the planned hardening.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import numpy as np

from babylon.core import Fill
from babylon.data.models import L2Book
from babylon.engine.clock import Clock
from babylon.engine.context import Context, MarketView
from babylon.exchange.websocket import Subscription, WebSocketFeed
from babylon.execution.base import Executor
from babylon.logging import get_logger
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.edge import EdgeModel
from babylon.sizing.sizer import Sizer
from babylon.strategy.base import Strategy

log = get_logger("engine")


class Engine:
    def __init__(
        self,
        *,
        feed: WebSocketFeed,
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
    ) -> None:
        self._feed = feed
        self._market = market
        self._strategies = strategies
        self._sizer = sizer
        self._risk = risk
        self._net_risk = net_risk
        self._reconciler = reconciler
        self._executor = executor
        self._ledger = ledger
        self._clock = clock
        self._budgets = budgets
        self._interval = interval_s
        self._stop = asyncio.Event()
        self._fills = 0

        self._coins = sorted({c for s in strategies for c in s.universe})
        self._edges: dict[tuple[str, str], EdgeModel] = {
            (s.name, c): s.make_edge_model(c, rng) for s in strategies for c in s.universe
        }
        self._last_dir: dict[tuple[str, str], float] = {}
        self._prev_mid: dict[str, float] = {}

        feed.on("l2Book", self._on_book)
        for c in self._coins:
            feed.subscribe(Subscription(type="l2Book", coin=c))

    def stop(self) -> None:
        self._stop.set()

    @property
    def fills(self) -> int:
        return self._fills

    async def _on_book(self, data: dict[str, Any]) -> None:
        book = L2Book.from_ws(data)
        if book.best_bid is not None and book.best_ask is not None:
            self._market.update(book.coin, book.best_bid, book.best_ask)

    async def run(self) -> None:
        feed_task = asyncio.create_task(self._feed.run())
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self._interval)
                try:
                    self._tick()
                except Exception:  # noqa: BLE001 — one bad tick must not kill the loop
                    log.exception("engine.tick_error")
        finally:
            self._stop.set()
            self._feed.stop()
            await asyncio.gather(feed_task, return_exceptions=True)

    def _tick(self) -> None:
        now = self._clock.now()
        marks = self._market.marks(self._coins)
        if not marks:
            return  # no prices yet

        self._update_edges(marks)
        equity = self._ledger.equity(marks)

        # Phase 3: strategies → signals → sizing → per-strategy risk → targets.
        targets: dict[tuple[str, str], Decimal] = {}
        for strat in self._strategies:
            budget_equity = equity * Decimal(str(self._budgets.get(strat.name, 0.0)))
            positions = {c: self._ledger.position(strat.name, c) for c in strat.universe}
            ctx = Context(
                strategy=strat.name,
                clock=self._clock,
                market=self._market,
                positions=positions,
                equity=equity,
            )
            strat.on_bar(ctx)
            signals = ctx.collected()
            for coin in strat.universe:
                # default: hold current virtual position if no fresh signal.
                if coin not in signals or coin not in marks:
                    targets[(strat.name, coin)] = positions[coin]
                    continue
                direction = signals[coin]
                self._last_dir[(strat.name, coin)] = direction
                edge = self._edges[(strat.name, coin)].estimate()
                raw = self._sizer.target_size(
                    edge=edge,
                    direction=direction,
                    budget_equity=budget_equity,
                    mark_price=marks[coin],
                )
                targets[(strat.name, coin)] = self._risk.clamp_target(
                    raw, mark=marks[coin], budget_equity=budget_equity
                )

        # Phase 4: net per coin → Net Risk Manager.
        net_targets: dict[str, Decimal] = {}
        for (_s, coin), size in targets.items():
            net_targets[coin] = net_targets.get(coin, Decimal(0)) + size
        review = self._net_risk.review(net_targets=net_targets, marks=marks, equity=equity)

        # Phase 5+6: reconcile vs actual → orders → fills → attribute.
        actual = {c: self._executor.net_position(c) for c in self._coins}
        orders = self._reconciler.diff(
            net_targets=review.net_targets, actual=actual, marks=marks, now=now
        )
        for order in orders:
            quote = self._market.quote(order.coin)
            if quote is None:
                continue
            fill = self._executor.submit(order, quote, now)
            if fill is not None:
                self._attribute(fill, targets)
                self._fills += 1

        log.info(
            "engine.tick",
            equity=float(equity),
            net=self._executor.net_positions(),
            dd=round(review.drawdown, 4),
            halted=review.halted,
            fills=self._fills,
        )

    def _update_edges(self, marks: dict[str, Decimal]) -> None:
        """Feed each strategy's EdgeModel the realized unit return of its last
        direction over the interval — size-independent, so sizing can't
        contaminate the edge estimate."""
        for coin, mark in marks.items():
            prev = self._prev_mid.get(coin)
            cur = float(mark)
            if prev is not None and prev > 0:
                period_ret = cur / prev - 1.0
                for strat in self._strategies:
                    if coin not in strat.universe:
                        continue
                    direction = self._last_dir.get((strat.name, coin), 0.0)
                    if direction != 0.0:
                        unit = (1.0 if direction > 0 else -1.0) * period_ret
                        self._edges[(strat.name, coin)].update(unit)
            self._prev_mid[coin] = cur

    def _attribute(self, fill: Fill, targets: dict[tuple[str, str], Decimal]) -> None:
        """Distribute a netted fill back to strategies pro-rata by their requested
        delta, settling each at the fill price."""
        coin = fill.coin
        deltas: dict[str, Decimal] = {}
        for (strat, c), tgt in targets.items():
            if c != coin:
                continue
            deltas[strat] = tgt - self._ledger.position(strat, coin)
        total = sum(deltas.values(), Decimal(0))
        if total == 0:
            return
        for strat, d in deltas.items():
            if d == 0:
                continue
            share = fill.size * (d / total)
            self._ledger.apply_fill(strat, coin, share, fill.price)
