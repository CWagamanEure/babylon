"""Recovery: engine state survives a restart through the journal."""

import json
from decimal import Decimal

import numpy as np

from babylon.engine.clock import SimClock
from babylon.engine.context import MarketView
from babylon.engine.engine import Engine
from babylon.exchange.websocket import WebSocketFeed
from babylon.execution.paper import PaperExecutor
from babylon.journal.journal import Journal
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.sizer import Sizer
from babylon.strategy.examples.ma_crossover import MACrossover

COIN = "BTC"
STRAT = "ma_BTC_2_3"


def _engine(rng, market, clock, executor, ledger):
    strat = MACrossover(COIN, fast=2, slow=3, prior_mean=0.002, prior_std=0.004, prior_strength=200)
    return Engine(
        feed=WebSocketFeed(url="wss://example/ws"), market=market, strategies=[strat],
        sizer=Sizer(fractional=0.25), risk=RiskManager(per_asset_cap=0.5),
        net_risk=NetRiskManager(max_leverage=1.0, gross_cap=10.0, max_drawdown=0.9),
        reconciler=Reconciler(min_trade_notional=Decimal(1)), executor=executor,
        ledger=ledger, clock=clock, budgets={strat.name: 1.0}, rng=rng, interval_s=0.0,
    )


def _drive(engine, market, clock, prices):
    for i, p in enumerate(prices):
        clock.advance_to((i + 1) * 1000)
        px = Decimal(str(p))
        market.update(COIN, px - Decimal("0.5"), px + Decimal("0.5"))
        engine._tick()


def test_state_survives_restart_via_journal(tmp_path):
    # --- run A: evolve ledger positions, edge observations, net-risk high-water
    a = _engine(np.random.default_rng(3), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)))
    _drive(a, a._market, a._clock, [100, 101, 102, 103, 104, 105, 106])
    assert a._ledger.net_position(COIN) != 0  # actually traded
    state_a = a.capture_state()

    # --- persist through the journal as a real snapshot blob
    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1, network="testnet", seed=3, roster=[STRAT])
    blob = json.dumps(state_a).encode()
    j.snapshot(run_id="r1", applied_seq=state_a["last_applied_seq"], ts_ms=1,
               parts={("engine", ""): blob})

    # --- "restart": fresh engine reads the snapshot back and restores
    got = j.latest_snapshot()
    assert got is not None
    _seq, parts = got
    state_b = json.loads(parts[("engine", "")])

    ex_b, led_b = PaperExecutor(), Ledger(Decimal(100_000))
    b = _engine(np.random.default_rng(3), MarketView(), SimClock(), ex_b, led_b)
    b.restore_state(state_b)

    # ledger positions + realized PnL restored exactly
    assert b._ledger.net_position(COIN) == a._ledger.net_position(COIN)
    assert b._ledger.realized_pnl() == a._ledger.realized_pnl()
    # paper executor net derived from the restored ledger (invariant holds)
    assert ex_b.net_position(COIN) == b._ledger.net_position(COIN)
    # edge learning restored (same shrink ⇒ same observed-return state)
    assert (b._edges[(STRAT, COIN)].estimate().shrink()
            == a._edges[(STRAT, COIN)].estimate().shrink())
    # net-risk latch (high-water) restored
    assert b._net_risk.to_state() == a._net_risk.to_state()
    j.close()


def test_restored_engine_continues_in_sync(tmp_path):
    a = _engine(np.random.default_rng(5), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)))
    _drive(a, a._market, a._clock, [100, 101, 102, 103, 104])
    state = json.loads(json.dumps(a.capture_state()))

    mkt_b, clk_b = MarketView(), SimClock()
    b = _engine(np.random.default_rng(5), mkt_b, clk_b, PaperExecutor(), Ledger(Decimal(100_000)))
    b.restore_state(state)
    # Keep trading after restore — the ledger==executor invariant must hold.
    _drive(b, mkt_b, clk_b, [105, 106, 107])
    assert b._ledger.net_position(COIN) == b._executor.net_position(COIN)
