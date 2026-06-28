from datetime import UTC, datetime
from decimal import Decimal

import numpy as np

from babylon.backtest.config import BacktestConfig
from babylon.backtest.runner import Backtester
from babylon.data.replay import L2Replay
from babylon.data.store import ParquetStore
from babylon.engine.clock import SimClock
from babylon.engine.context import MarketView
from babylon.engine.engine import Engine
from babylon.exchange.feed import NullFeed
from babylon.execution.backtest import BacktestExecutor
from babylon.portfolio.ledger import Ledger
from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager
from babylon.sizing.sizer import Sizer
from babylon.strategy.examples.momentum import Momentum

BASE = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp() * 1000)


def _write_trend(store, *, n=600, drift=0.0003, gap_at=None):
    rng = np.random.default_rng(1)
    px = 30_000.0
    for i in range(n):
        # Inject a 5-minute data gap to exercise gap suppression.
        t = BASE + i * 1000 + (300_000 if gap_at is not None and i >= gap_at else 0)
        px *= 1 + drift + rng.normal(0, 0.0005)
        bb, ba = px - 1, px + 1
        store.write("l2Book", "BTC", dict(
            time=t, ver_num=i, best_bid=bb, best_ask=ba, mid=px,
            bid_px=[bb, bb - 2], bid_sz=[5.0, 10.0], bid_n=[1, 1],
            ask_px=[ba, ba + 2], ask_sz=[5.0, 10.0], ask_n=[1, 1],
        ))
    store.flush()


def _run(tmp_path, *, seed=0):
    strat = Momentum("BTC", lookback=20)
    ex = BacktestExecutor(slippage_bps=1.0, max_depth_fraction=0.5)
    eng = Engine(
        feed=NullFeed(), market=MarketView(), strategies=[strat], sizer=Sizer(),
        risk=RiskManager(), net_risk=NetRiskManager(),
        reconciler=Reconciler(min_trade_notional=Decimal(10)), executor=ex,
        ledger=Ledger(Decimal(100_000)), clock=SimClock(), budgets={strat.name: 1.0},
        rng=np.random.default_rng(seed), interval_s=0.0,
    )
    cfg = BacktestConfig(start="20260601", end="20260601", interval_ms=2000, warmup=30, seed=seed)
    replay = L2Replay(tmp_path, ["BTC"], "20260601", "20260601")
    return Backtester(eng, ex, replay, eng._clock, cfg).run()


def test_backtest_end_to_end_produces_fills_and_metrics(tmp_path):
    _write_trend(ParquetStore(tmp_path))
    res = _run(tmp_path)
    assert res.n_events == 600 and res.n_ticks > 0
    assert res.fills > 0
    assert res.account is not None
    # Momentum on a clean uptrend should grow and the gate should see an edge.
    assert res.account.log_growth_total > 0
    assert res.gates["mom_BTC_20"].n > 0


def test_backtest_is_deterministic(tmp_path):
    _write_trend(ParquetStore(tmp_path))
    a, b = _run(tmp_path), _run(tmp_path)
    assert a.account.log_growth_total == b.account.log_growth_total
    assert a.fills == b.fills and a.n_ticks == b.n_ticks


def test_multi_strategy_on_one_coin_does_not_abort(tmp_path):
    # Several strategies netting on ONE coin used to trip ledger≠executor via
    # Decimal re-summation drift (~60% of runs). Lot-quantized shares fix it.
    _write_trend(ParquetStore(tmp_path))
    strats = [Momentum("BTC", lookback=lb) for lb in (5, 8, 13, 21)]
    ex = BacktestExecutor(slippage_bps=1.0, max_depth_fraction=0.5)
    eng = Engine(
        feed=NullFeed(), market=MarketView(), strategies=strats, sizer=Sizer(),
        risk=RiskManager(), net_risk=NetRiskManager(),
        reconciler=Reconciler(min_trade_notional=Decimal(10)), executor=ex,
        ledger=Ledger(Decimal(100_000)), clock=SimClock(),
        budgets={s.name: 0.25 for s in strats}, rng=np.random.default_rng(0), interval_s=0.0,
    )
    cfg = BacktestConfig(start="20260601", end="20260601", interval_ms=2000, warmup=20)
    res = Backtester(eng, ex, L2Replay(tmp_path, ["BTC"], "20260601", "20260601"),
                     eng._clock, cfg).run()
    assert not res.aborted
    for c in eng._coins:  # ledger re-sum stays bit-equal to the executor net
        assert eng._ledger.net_position(c) == eng._executor.net_position(c)


def test_no_trade_run_reports_gracefully(tmp_path):
    # Flat price → momentum sizes to zero → no fills. Must not crash, and must flag
    # traded=False (so the report says "no trades" instead of an empty table).
    store = ParquetStore(tmp_path)
    for i in range(400):
        store.write("l2Book", "BTC", dict(
            time=BASE + i * 1000, ver_num=i, best_bid=29_999.0, best_ask=30_001.0, mid=30_000.0,
            bid_px=[29_999.0, 29_998.0], bid_sz=[5.0, 10.0], bid_n=[1, 1],
            ask_px=[30_001.0, 30_002.0], ask_sz=[5.0, 10.0], ask_n=[1, 1],
        ))
    store.flush()
    res = _run(tmp_path)
    assert res.fills == 0 and not res.traded
    assert res.n_ticks > 0  # ran, just didn't trade


def test_driver_aborts_on_invariant_break(tmp_path):
    # The engine sets _stop on a ledger≠executor desync; the driver must abort, not
    # silently keep producing corrupt ticks.
    _write_trend(ParquetStore(tmp_path))
    strat = Momentum("BTC", lookback=20)
    ex = BacktestExecutor(slippage_bps=1.0, max_depth_fraction=0.5)
    eng = Engine(
        feed=NullFeed(), market=MarketView(), strategies=[strat], sizer=Sizer(),
        risk=RiskManager(), net_risk=NetRiskManager(),
        reconciler=Reconciler(min_trade_notional=Decimal(10)), executor=ex,
        ledger=Ledger(Decimal(100_000)), clock=SimClock(), budgets={strat.name: 1.0},
        rng=np.random.default_rng(0), interval_s=0.0,
    )
    real_tick, calls = eng._tick, {"n": 0}

    def trip(*a, **k):
        calls["n"] += 1
        real_tick(*a, **k)
        if calls["n"] == 5:
            eng._stop.set()  # simulate an invariant break

    eng._tick = trip  # type: ignore[method-assign]
    cfg = BacktestConfig(start="20260601", end="20260601", interval_ms=2000, warmup=0)
    replay = L2Replay(tmp_path, ["BTC"], "20260601", "20260601")
    res = Backtester(eng, ex, replay, eng._clock, cfg).run()
    assert res.aborted and res.n_ticks == 5  # stopped right at the break, not ~300


def test_backtest_suppresses_ticks_across_data_gap(tmp_path):
    # Without suppression a 5-min gap at interval 2s would inject ~150 phantom ticks.
    _write_trend(ParquetStore(tmp_path), gap_at=300)
    res = _run(tmp_path)
    assert res.gaps == 1
    # ~600s of real data at 2s ≈ ~300 ticks; the 300s gap must NOT add ~150 more.
    assert res.n_ticks < 320
