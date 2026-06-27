from decimal import Decimal

from babylon.portfolio.reconcile import Reconciler
from babylon.risk.manager import RiskManager
from babylon.risk.net import NetRiskManager


def test_reconciler_deadband_skips_small():
    rec = Reconciler(min_trade_notional=Decimal(100))
    orders = rec.diff(
        net_targets={"BTC": Decimal("0.001")},
        actual={"BTC": Decimal(0)},
        marks={"BTC": Decimal(50000)},  # 0.001*50000=50 < 100 deadband
        now=1,
    )
    assert orders == []


def test_reconciler_emits_delta_and_reduce_only():
    rec = Reconciler(min_trade_notional=Decimal(1))
    # currently long 1, target 0 → reduce-only sell of 1.
    orders = rec.diff(
        net_targets={"BTC": Decimal(0)}, actual={"BTC": Decimal(1)},
        marks={"BTC": Decimal(50000)}, now=1,
    )
    assert len(orders) == 1
    assert orders[0].size == Decimal(-1)
    assert orders[0].reduce_only is True


def test_reconciler_open_is_not_reduce_only():
    rec = Reconciler(min_trade_notional=Decimal(1))
    orders = rec.diff(
        net_targets={"BTC": Decimal(1)}, actual={"BTC": Decimal(0)},
        marks={"BTC": Decimal(50000)}, now=1,
    )
    assert orders[0].reduce_only is False


def test_risk_per_asset_cap():
    rm = RiskManager(per_asset_cap=0.5)
    # budget 1000, mark 100 → max size 5.
    def clamp(sz):
        return rm.clamp_target(Decimal(sz), mark=Decimal(100), budget_equity=Decimal(1000))

    assert clamp(20) == Decimal(5)
    assert clamp(-20) == Decimal(-5)
    assert clamp(3) == Decimal(3)


def test_net_risk_no_leverage_scaling():
    nr = NetRiskManager(max_leverage=1.0, max_drawdown=0.5)
    # gross notional = 2*1000=2000 > equity 1000 → scale by 0.5.
    review = nr.review(
        net_targets={"BTC": Decimal(2)}, marks={"BTC": Decimal(1000)}, equity=Decimal(1000)
    )
    assert review.scaled == 0.5
    assert review.net_targets["BTC"] == Decimal(1)
    assert not review.halted


def test_net_risk_drawdown_halt_flattens():
    nr = NetRiskManager(max_leverage=1.0, max_drawdown=0.2)
    nr.review(net_targets={}, marks={}, equity=Decimal(1000))  # high-water = 1000
    review = nr.review(
        net_targets={"BTC": Decimal(1)}, marks={"BTC": Decimal(100)}, equity=Decimal(700)
    )  # 30% DD > 20%
    assert review.halted
    assert review.net_targets["BTC"] == Decimal(0)
