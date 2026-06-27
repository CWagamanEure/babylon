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
from babylon.risk.exposure import BookExposure, ExposureMonitor
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.edge import EdgeModel
from babylon.sizing.sizer import Sizer
from babylon.strategy.base import Strategy

log = get_logger("engine")

# Approx Hyperliquid taker fee per side; round-trip charged to the edge on turnover.
TAKER_FEE = 0.00045
QUARANTINE_AFTER = 3  # consecutive strategy failures before it's benched


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
        exposure: ExposureMonitor | None = None,
    ) -> None:
        self._feed = feed
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
        self._interval = interval_s
        self._exposure_mon = exposure or ExposureMonitor()
        self._exposure: BookExposure | None = None
        self._stop = asyncio.Event()
        self._fills = 0

        self._coins = sorted({c for s in strategies for c in s.universe})
        # Independent child RNG per strategy → adding/removing one doesn't shift
        # another's prior draws (reproducibility).
        children = rng.spawn(len(strategies))
        self._edges: dict[tuple[str, str], EdgeModel] = {
            (s.name, c): s.make_edge_model(c, child)
            for s, child in zip(strategies, children, strict=True)
            for c in s.universe
        }
        self._prev_mid: dict[str, float] = {}
        self._edge_dir: dict[tuple[str, str], int] = {}  # last edge direction, for fee-on-turnover
        self._fail_count: dict[str, int] = {}
        self._quarantined: set[str] = set()

    def stop(self) -> None:
        self._stop.set()

    @property
    def fills(self) -> int:
        return self._fills

    @property
    def exposure(self) -> BookExposure | None:
        """Latest book exposure snapshot (net directional, concentration, neutrality)."""
        return self._exposure

    async def _on_book(self, data: dict[str, Any]) -> None:
        book = L2Book.from_ws(data)
        if book.best_bid is not None and book.best_ask is not None:
            self._market.update(book.coin, book.best_bid, book.best_ask)

    async def run(self) -> None:
        self._feed.on("l2Book", self._on_book)
        for c in self._coins:
            self._feed.subscribe(Subscription(type="l2Book", coin=c))
        for s in self._strategies:
            s.on_start(self._context(s, {}, self._ledger_equity({})))
        feed_task = asyncio.create_task(self._feed.run())
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self._interval)
                try:
                    self._tick()
                except Exception:  # noqa: BLE001 — last-resort guard; per-strategy isolation is inside
                    log.exception("engine.tick_error")
        finally:
            self._stop.set()
            self._feed.stop()
            for s in self._strategies:
                s.on_stop(self._context(s, {}, self._ledger_equity({})))
            await asyncio.gather(feed_task, return_exceptions=True)

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
        now = self._clock.now()
        marks = self._market.marks(self._coins)
        if not marks:
            return

        self._update_edges(marks)
        equity = self._ledger.equity(marks)

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
                if self._fail_count[strat.name] >= QUARANTINE_AFTER:
                    self._quarantined.add(strat.name)
                    log.error("engine.quarantine", strategy=strat.name)

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
                continue
            try:
                fill = self._executor.submit(order, quote, now)
            except Exception:  # noqa: BLE001 — an executor failure must not desync state
                log.exception("engine.submit_error", coin=order.coin)
                continue
            if fill is not None:
                self._attribute(fill, scaled)
                self._fills += 1
                if self._ledger.net_position(order.coin) != self._executor.net_position(order.coin):
                    log.error(
                        "engine.invariant_break",
                        coin=order.coin,
                        ledger=str(self._ledger.net_position(order.coin)),
                        executor=str(self._executor.net_position(order.coin)),
                    )
                    self._stop.set()

        # Measure the actual book we now hold (tracks; does not enforce).
        self._exposure = self._exposure_mon.assess(
            self._executor.net_positions(), marks, equity
        )

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
                        if direction != prev_dir:  # turnover this interval → fee drag
                            sides = 2 if prev_dir != 0 else 1
                            unit -= sides * TAKER_FEE
                        self._edges[key].update(unit)
                    self._edge_dir[key] = direction
            self._prev_mid[coin] = cur

    def _compute_shares(
        self, fill: Fill, scaled: dict[tuple[str, str], Decimal]
    ) -> list[tuple[str, Decimal]]:
        """Pure: the per-strategy share vector for a fill — no mutation. This is the
        single source of attribution, so the journal can persist the exact vector
        and recovery reproduces identical booking.

        Shares are pro-rata by each strategy's scaled requested delta; the last
        (largest |delta|, name tiebreak — deterministic, NOT dict order) takes the
        exact residual so the vector sums to fill.size precisely (keeps ledger net
        == executor net). Pure pro-rata is correct for FULL fills (paper); partial
        fills need the same-sign-fills-first rule — a [LIVE] TODO.
        """
        coin = fill.coin
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
            share = fill.size - allocated if i == len(movers) - 1 else fill.size * d / total
            if i != len(movers) - 1:
                allocated += share
            shares.append((strat, share))
        return shares

    def _attribute(self, fill: Fill, scaled: dict[tuple[str, str], Decimal]) -> None:
        """Apply the computed share vector to the ledgers and notify strategies."""
        for strat, share in self._compute_shares(fill, scaled):
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
