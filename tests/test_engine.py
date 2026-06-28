from decimal import Decimal

import numpy as np

from babylon.engine.clock import SimClock
from babylon.engine.context import Context, MarketView
from babylon.engine.engine import Engine
from babylon.execution.paper import PaperExecutor
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.edge import BootstrapEdgeModel
from babylon.sizing.sizer import Sizer
from babylon.strategy.base import Strategy
from babylon.strategy.examples.ma_crossover import MACrossover


def _engine(strat, market, clock, executor, ledger, rng, *, net_risk=None):
    from babylon.exchange.websocket import WebSocketFeed

    return Engine(
        feed=WebSocketFeed(url="wss://example/ws"),
        market=market,
        strategies=[strat],
        sizer=Sizer(fractional=0.25),
        risk=RiskManager(per_asset_cap=0.5),
        net_risk=net_risk or NetRiskManager(max_leverage=1.0, gross_cap=10.0, max_drawdown=0.9),
        reconciler=Reconciler(min_trade_notional=Decimal(1)),
        executor=executor,
        ledger=ledger,
        clock=clock,
        budgets={strat.name: 1.0},
        rng=rng,
        interval_s=0.0,
    )


def _drive(engine, market, clock, coin, prices):
    for i, p in enumerate(prices):
        clock.advance_to((i + 1) * 1000)
        px = Decimal(str(p))
        market.update(coin, px - Decimal("0.5"), px + Decimal("0.5"))
        engine._tick()


def test_pipeline_goes_long_in_uptrend_and_stays_in_sync():
    rng = np.random.default_rng(7)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    strat = MACrossover(
        "BTC", fast=2, slow=3, prior_mean=0.001, prior_std=0.005, prior_strength=200
    )
    engine = _engine(strat, market, clock, executor, ledger, rng)
    _drive(engine, market, clock, "BTC", [100, 101, 102, 103, 104, 105, 106, 107])
    assert ledger.net_position("BTC") > 0
    assert ledger.net_position("BTC") == executor.net_position("BTC")
    assert engine.fills > 0


def test_pipeline_goes_short_in_downtrend():
    rng = np.random.default_rng(7)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    strat = MACrossover(
        "BTC", fast=2, slow=3, prior_mean=0.001, prior_std=0.005, prior_strength=200
    )
    engine = _engine(strat, market, clock, executor, ledger, rng)
    _drive(engine, market, clock, "BTC", [110, 109, 108, 107, 106, 105, 104, 103])
    assert ledger.net_position("BTC") < 0
    assert ledger.net_position("BTC") == executor.net_position("BTC")


class _HoldAfter(Strategy):
    """Signals long for the first 3 ticks, then holds silently — the case that
    used to break attribution when Net Risk acted on a held position."""

    def __init__(self) -> None:
        super().__init__("hold", ["BTC"])
        self.n = 0

    def make_edge_model(self, coin, rng):
        return BootstrapEdgeModel.from_gaussian_prior(rng, mean=0.01, std=0.003, strength=300)

    def on_bar(self, ctx: Context) -> None:
        self.n += 1
        if self.n <= 3:
            ctx.signal("BTC", 1.0)


def test_attribution_invariant_holds_under_deleverage_of_held_position():
    # Regression for the CRITICAL bug: a held position (no fresh signal) that Net
    # Risk deleverages must keep ledger net == executor net (and book the change).
    rng = np.random.default_rng(0)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    strat = _HoldAfter()
    engine = _engine(
        strat, market, clock, executor, ledger, rng,
        net_risk=NetRiskManager(max_leverage=1.0, gross_cap=10.0, max_drawdown=0.9),
    )
    _drive(engine, market, clock, "BTC", [100, 100, 100])  # build position
    assert ledger.net_position("BTC") == executor.net_position("BTC")
    assert ledger.net_position("BTC") != 0
    # Now force a hard deleverage while the strategy holds (silent).
    engine._net_risk = NetRiskManager(max_leverage=0.1, gross_cap=10.0, max_drawdown=0.9)
    clock.advance_to(9000)
    market.update("BTC", Decimal("99.5"), Decimal("100.5"))
    engine._tick()
    assert ledger.net_position("BTC") == executor.net_position("BTC")  # INVARIANT


def _two_strategy_run(seed):
    rng = np.random.default_rng(seed)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    s1 = MACrossover("BTC", fast=2, slow=3, prior_mean=0.002, prior_std=0.004, prior_strength=200)
    s2 = MACrossover("BTC", fast=2, slow=4, prior_mean=0.002, prior_std=0.004, prior_strength=200)
    from babylon.exchange.websocket import WebSocketFeed

    engine = Engine(
        feed=WebSocketFeed(url="wss://example/ws"), market=market, strategies=[s1, s2],
        sizer=Sizer(fractional=0.25), risk=RiskManager(per_asset_cap=0.5),
        net_risk=NetRiskManager(max_leverage=1.0, gross_cap=10.0, max_drawdown=0.9),
        reconciler=Reconciler(min_trade_notional=Decimal(1)), executor=executor,
        ledger=ledger, clock=clock, budgets={s1.name: 0.5, s2.name: 0.5},
        rng=rng, interval_s=0.0,
    )
    _drive(engine, market, clock, "BTC", [100, 101, 102, 103, 104, 105])
    return ledger, executor, s1, s2


def test_multi_strategy_attribution_in_sync_and_deterministic():
    ledger, executor, s1, s2 = _two_strategy_run(11)
    # Invariant holds across the multi-mover residual path.
    assert ledger.net_position("BTC") == executor.net_position("BTC")
    # Both strategies are attributed a share (net is sum of the two virtuals).
    combined = ledger.position(s1.name, "BTC") + ledger.position(s2.name, "BTC")
    assert combined == ledger.net_position("BTC")
    # Reproducible: same seed → identical per-strategy attribution (deterministic residual).
    led2, _ex2, _a, _b = _two_strategy_run(11)
    assert ledger.position(s1.name, "BTC") == led2.position(s1.name, "BTC")


def test_child_rng_is_roster_invariant():
    from babylon.engine.engine import _child_rng

    # A (strategy, coin) edge RNG depends only on (base, name, coin) — so adding or
    # removing other strategies never shifts its draws (order- AND insert-invariant).
    base = 999
    a = _child_rng(base, "mom_SOL_20", "SOL").random(5)
    b = _child_rng(base, "mom_SOL_20", "SOL").random(5)
    assert np.array_equal(a, b)
    # distinct (name, coin) → independent streams
    assert not np.array_equal(a, _child_rng(base, "mom_BTC_20", "BTC").random(5))
    assert not np.array_equal(a, _child_rng(base, "mom_SOL_20", "ETH").random(5))


def test_budgets_must_sum_to_one():
    import pytest

    rng = np.random.default_rng(0)
    strat = MACrossover("BTC", fast=2, slow=3)
    from babylon.exchange.websocket import WebSocketFeed

    def build(budget):
        return Engine(
            feed=WebSocketFeed(url="wss://x/ws"), market=MarketView(), strategies=[strat],
            sizer=Sizer(), risk=RiskManager(), net_risk=NetRiskManager(),
            reconciler=Reconciler(), executor=PaperExecutor(), ledger=Ledger(Decimal(1000)),
            clock=SimClock(), budgets={strat.name: budget}, rng=rng, interval_s=0.0,
        )

    with pytest.raises(ValueError, match="sum to 1.0"):
        build(0.6)
    build(1.0)  # ok


def test_no_leverage_respected_on_net():
    rng = np.random.default_rng(7)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    strat = MACrossover(
        "BTC", fast=2, slow=3, prior_mean=0.005, prior_std=0.004, prior_strength=300
    )
    engine = _engine(strat, market, clock, executor, ledger, rng)
    _drive(engine, market, clock, "BTC", [100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    marks = {"BTC": Decimal("109")}
    notional = abs(ledger.net_position("BTC")) * marks["BTC"]
    assert notional <= ledger.equity(marks) + Decimal(1)
