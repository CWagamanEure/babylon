import numpy as np

from babylon.risk.killswitch import KillConfig, KillSwitch
from babylon.stats.decay import EdgeTracker
from babylon.stats.gate import log_growth_gate
from babylon.stats.metrics import compute_metrics
from babylon.stats.monitor import ACCOUNT

# --- gate ----------------------------------------------------------------------

def test_gate_real_on_clear_positive_edge():
    rng = np.random.default_rng(0)
    r = rng.normal(0.003, 0.004, 400)  # strong, consistent positive edge
    res = log_growth_gate(r, np.random.default_rng(1), n_boot=400)
    assert res.is_real and res.log_growth_lower > 0


def test_gate_not_real_on_no_edge():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0, 0.01, 400)  # zero-mean → not real
    res = log_growth_gate(r, np.random.default_rng(1), n_boot=400)
    assert not res.is_real


def test_gate_not_real_below_min_n():
    r = np.full(10, 0.01)
    res = log_growth_gate(r, np.random.default_rng(0), min_n=30)
    assert not res.is_real and res.n == 10


# --- decay tracker -------------------------------------------------------------

def test_edge_tracker_decays_when_edge_turns_negative():
    t = EdgeTracker(halflife=10.0)
    for _ in range(60):
        t.update(0.01)  # positive edge
    assert t.edge > 0 and not t.decayed()
    for _ in range(60):
        t.update(-0.01)  # edge dies
    assert t.edge < 0 and t.decayed()


def test_edge_tracker_needs_min_n():
    t = EdgeTracker()
    for _ in range(5):
        t.update(-0.01)
    assert not t.decayed(min_n=30)  # not enough data yet


# --- kill switch ---------------------------------------------------------------

def _metrics(equity):
    return compute_metrics(np.asarray(equity, dtype=np.float64))


def test_killswitch_demotes_on_strategy_drawdown():
    ks = KillSwitch(KillConfig(strat_max_drawdown=0.2))
    # alpha drops 30% (>20%); beta steady
    m_alpha = _metrics([100, 100, 70, 75])
    m_beta = _metrics([100, 101, 102, 103])
    d = ks.evaluate(strat_metrics={"alpha": m_alpha, "beta": m_beta},
                    account_metrics=None, edge_decayed={})
    assert d.demote == {"alpha"} and not d.halt


def test_killswitch_demotes_on_edge_decay():
    ks = KillSwitch(KillConfig(strat_max_drawdown=0.9))  # DD won't trip
    m = _metrics([100, 101, 102])
    d = ks.evaluate(strat_metrics={"alpha": m}, account_metrics=None,
                    edge_decayed={"alpha": True})
    assert d.demote == {"alpha"}


def test_killswitch_halts_account_on_drawdown():
    ks = KillSwitch(KillConfig(account_max_drawdown=0.2))
    acct = _metrics([100, 120, 90])  # 25% DD
    d = ks.evaluate(strat_metrics={}, account_metrics=acct, edge_decayed={})
    assert d.halt and ACCOUNT in d.reasons


def test_engine_kill_wiring_demotes_and_halts():
    # End-to-end: a seeded per-strategy drawdown → _evaluate_kills quarantines it
    # and the account drawdown halts net-risk.
    from decimal import Decimal

    from babylon.engine.clock import SimClock
    from babylon.engine.context import MarketView
    from babylon.engine.engine import Engine
    from babylon.exchange.websocket import WebSocketFeed
    from babylon.execution.paper import PaperExecutor
    from babylon.portfolio.ledger import Ledger
    from babylon.portfolio.reconcile import Reconciler
    from babylon.risk.manager import RiskManager
    from babylon.risk.net import NetRiskManager
    from babylon.sizing.sizer import Sizer
    from babylon.strategy.examples.ma_crossover import MACrossover

    strat = MACrossover("BTC", fast=2, slow=3)
    eng = Engine(
        feed=WebSocketFeed(url="wss://x/ws"), market=MarketView(), strategies=[strat],
        sizer=Sizer(), risk=RiskManager(), net_risk=NetRiskManager(),
        reconciler=Reconciler(), executor=PaperExecutor(), ledger=Ledger(Decimal(100_000)),
        clock=SimClock(), budgets={strat.name: 1.0}, rng=np.random.default_rng(0),
        kill_switch=KillSwitch(KillConfig(strat_max_drawdown=0.2, account_max_drawdown=0.2)),
    )
    # Seed a 30% drawdown into both the strategy and account equity curves.
    for v in [100_000, 100_000, 70_000, 72_000]:
        eng._perf.sample({strat.name: float(v), ACCOUNT: float(v)})
    eng._evaluate_kills(now=1)
    assert strat.name in eng._quarantined  # demoted on per-strategy DD
    assert eng._net_risk_halted()          # account halted on DD
