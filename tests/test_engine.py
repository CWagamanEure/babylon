from decimal import Decimal

import numpy as np

from babylon.engine.clock import SimClock
from babylon.engine.context import MarketView
from babylon.engine.engine import Engine
from babylon.execution.paper import PaperExecutor
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.sizer import Sizer
from babylon.strategy.examples.ma_crossover import MACrossover


def _engine(strat, market, clock, executor, ledger, rng):
    # A WebSocketFeed is constructed but never run; the test drives _tick directly.
    from babylon.exchange.websocket import WebSocketFeed

    return Engine(
        feed=WebSocketFeed(url="wss://example/ws"),
        market=market,
        strategies=[strat],
        sizer=Sizer(rng, fractional=0.25, n_draws=400),
        risk=RiskManager(per_asset_cap=0.5),
        net_risk=NetRiskManager(max_leverage=1.0, max_drawdown=0.9),
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
    strat = MACrossover("BTC", fast=2, slow=3, prior_mean=0.001, prior_std=0.005, prior_n=200)
    engine = _engine(strat, market, clock, executor, ledger, rng)

    _drive(engine, market, clock, "BTC", [100, 101, 102, 103, 104, 105, 106, 107])

    assert ledger.net_position("BTC") > 0  # uptrend → long
    # Invariant: ledger net == executor net (attribution distributes the full fill).
    assert ledger.net_position("BTC") == executor.net_position("BTC")
    assert engine.fills > 0


def test_pipeline_goes_short_in_downtrend():
    rng = np.random.default_rng(7)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    strat = MACrossover("BTC", fast=2, slow=3, prior_mean=0.001, prior_std=0.005, prior_n=200)
    engine = _engine(strat, market, clock, executor, ledger, rng)

    _drive(engine, market, clock, "BTC", [110, 109, 108, 107, 106, 105, 104, 103])

    assert ledger.net_position("BTC") < 0
    assert ledger.net_position("BTC") == executor.net_position("BTC")


def test_no_leverage_respected_on_net():
    rng = np.random.default_rng(7)
    market, clock = MarketView(), SimClock()
    executor, ledger = PaperExecutor(), Ledger(Decimal(100_000))
    strat = MACrossover("BTC", fast=2, slow=3, prior_mean=0.005, prior_std=0.004, prior_n=300)
    engine = _engine(strat, market, clock, executor, ledger, rng)

    _drive(engine, market, clock, "BTC", [100, 101, 102, 103, 104, 105, 106, 107, 108, 109])

    marks = {"BTC": ledger and Decimal("109")}
    notional = abs(ledger.net_position("BTC")) * marks["BTC"]
    assert notional <= ledger.equity(marks) + Decimal(1)  # ≤ equity (no leverage)
