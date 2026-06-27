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


def _engine(rng, market, clock, executor, ledger, *, journal=None, run_id="", seed=0):
    strat = MACrossover(COIN, fast=2, slow=3, prior_mean=0.002, prior_std=0.004, prior_strength=200)
    return Engine(
        feed=WebSocketFeed(url="wss://example/ws"), market=market, strategies=[strat],
        sizer=Sizer(fractional=0.25), risk=RiskManager(per_asset_cap=0.5),
        net_risk=NetRiskManager(max_leverage=1.0, gross_cap=10.0, max_drawdown=0.9),
        reconciler=Reconciler(min_trade_notional=Decimal(1), run_id=run_id), executor=executor,
        ledger=ledger, clock=clock, budgets={strat.name: 1.0}, rng=rng, interval_s=0.0,
        journal=journal, run_id=run_id, seed=seed,
    )


def test_crash_replay_recovers_to_last_fill(tmp_path):
    # Live-journal fills, snapshot partway, journal MORE fills, then "crash" with
    # no final snapshot. Recovery must reach the LAST fill (replay), not the snapshot.
    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1, network="t", seed=3, roster=[STRAT])
    mkt, clk, ex, led = MarketView(), SimClock(), PaperExecutor(), Ledger(Decimal(100_000))
    a = _engine(np.random.default_rng(3), mkt, clk, ex, led, journal=j, run_id="r1", seed=3)

    def step(prices, t0):
        for i, p in enumerate(prices):
            clk.advance_to(t0 + (i + 1) * 1000)
            px = Decimal(str(p))
            mkt.update(COIN, px - Decimal("0.5"), px + Decimal("0.5"))
            a._tick()
        return t0 + len(prices) * 1000

    t = step([100, 101, 102, 103], 0)   # warmup + fills
    a.record_snapshot(j, now=clk.now())  # snapshot at this cut
    step([104, 105, 106], t)             # MORE fills, only in the event log
    pos_before_crash = led.net_position(COIN)
    j.close()  # release the writer lock (simulate process death; no final snapshot)

    # --- restart: fresh engine recovers from the same journal
    j2 = Journal(tmp_path / "j.db")
    ex_b, led_b = PaperExecutor(), Ledger(Decimal(100_000))
    b = _engine(np.random.default_rng(3), MarketView(), SimClock(), ex_b, led_b,
                journal=j2, run_id="r2", seed=3)
    j2.connect()
    b._recover()
    # restore_state replaces the ledger object → read it from the engine.
    assert b._ledger.net_position(COIN) == pos_before_crash  # replayed past the snapshot
    assert ex_b.net_position(COIN) == pos_before_crash       # executor net derived from ledger
    j2.close()


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
    _seq, _rid, parts = got
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


def test_recover_aborts_on_fingerprint_mismatch(tmp_path):
    import pytest

    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1, network="t", seed=3, roster=[STRAT])
    a = _engine(np.random.default_rng(3), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)), journal=j, run_id="r1", seed=3)
    a.record_snapshot(j, now=1)
    j.close()
    # A different seed must ABORT the boot, never silently trade from flat while
    # the journal holds positions from another configuration.
    j2 = Journal(tmp_path / "j.db")
    b = _engine(np.random.default_rng(99), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)), journal=j2, run_id="r2", seed=99)
    j2.connect()
    with pytest.raises(RuntimeError, match="fingerprint"):
        b._recover()
    j2.close()


def test_quarantine_latch_replayed_on_recovery(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1, network="t", seed=3, roster=[STRAT])
    a = _engine(np.random.default_rng(3), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)), journal=j, run_id="r1", seed=3)
    a.record_snapshot(j, now=1)  # snapshot at seq 0
    # A quarantine that latched AFTER the snapshot must survive recovery.
    j.record_event("QUARANTINE", {"strategy": STRAT}, run_id="r1", tick=2, now=2, wall=2)
    j.close()
    j2 = Journal(tmp_path / "j.db")
    b = _engine(np.random.default_rng(3), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)), journal=j2, run_id="r2", seed=3)
    j2.connect()
    b._recover()
    assert STRAT in b._quarantined  # latch re-armed from the replayed event
    j2.close()


def test_engine_records_per_strategy_positions(tmp_path):
    a = _engine(np.random.default_rng(3), MarketView(), SimClock(),
                PaperExecutor(), Ledger(Decimal(100_000)))
    a._run_id = "r1"
    _drive(a, a._market, a._clock, [100, 101, 102, 103, 104, 105, 106])

    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1, network="testnet", seed=3, roster=[STRAT])
    a.record_snapshot(j, now=9999)

    # The strategy is registered with its allocation, and its current position is
    # queryable and matches the ledger.
    strats = {s["strategy"]: s for s in j.strategies()}
    assert STRAT in strats and strats[STRAT]["budget"] == "1.0"
    pos = j.current_positions(STRAT)
    assert len(pos) == 1 and pos[0]["coin"] == COIN
    assert pos[0]["size"] == a._ledger.net_position(COIN)
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
