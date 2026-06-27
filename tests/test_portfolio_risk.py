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
    )
    assert orders == []


def test_reconciler_reduce_only_and_unique_cloids():
    rec = Reconciler(min_trade_notional=Decimal(1))
    mk = {"BTC": Decimal(50000)}
    a = rec.diff(net_targets={"BTC": Decimal(0)}, actual={"BTC": Decimal(1)}, marks=mk)
    assert len(a) == 1 and a[0].size == Decimal(-1) and a[0].reduce_only is True
    # Different orders that happen to hit the same target get DISTINCT cloids
    # (a mean-reverting book revisits levels; a reused cloid would be rejected).
    b = rec.diff(net_targets={"BTC": Decimal("1.5")}, actual={"BTC": Decimal(0)}, marks=mk)
    c = rec.diff(net_targets={"BTC": Decimal("1.5")}, actual={"BTC": Decimal("1.2")}, marks=mk)
    assert b[0].cloid != c[0].cloid != a[0].cloid


def test_reconciler_open_is_not_reduce_only():
    rec = Reconciler(min_trade_notional=Decimal(1))
    orders = rec.diff(
        net_targets={"BTC": Decimal(1)}, actual={"BTC": Decimal(0)}, marks={"BTC": Decimal(50000)}
    )
    assert orders[0].reduce_only is False


def test_risk_per_asset_cap():
    rm = RiskManager(per_asset_cap=0.5)

    def clamp(sz):
        return rm.clamp_target(Decimal(sz), mark=Decimal(100), budget_equity=Decimal(1000))

    assert clamp(20) == Decimal(5)
    assert clamp(-20) == Decimal(-5)
    assert clamp(3) == Decimal(3)


def test_net_risk_no_leverage_scaling():
    nr = NetRiskManager(max_leverage=1.0, gross_cap=10.0, max_drawdown=0.5)
    r = nr.review(net_notional=Decimal(2000), gross_notional=Decimal(2000), equity=Decimal(1000))
    assert r.scale == 0.5 and not r.halted


def test_net_risk_gross_cap_catches_offsetting_book():
    # Net is flat-ish but gross is large (offsetting strategies) → gross cap bites.
    nr = NetRiskManager(max_leverage=1.0, gross_cap=2.0, max_drawdown=0.9)
    r = nr.review(net_notional=Decimal(100), gross_notional=Decimal(4000), equity=Decimal(1000))
    assert r.scale == 0.5  # 2000 cap / 4000 gross


def test_net_risk_drawdown_halt_latches():
    nr = NetRiskManager(max_leverage=1.0, max_drawdown=0.2)
    nr.review(net_notional=Decimal(0), gross_notional=Decimal(0), equity=Decimal(1000))  # hw=1000
    r = nr.review(net_notional=Decimal(0), gross_notional=Decimal(0), equity=Decimal(700))  # 30% DD
    assert r.halted and r.scale == 0.0
    # Latches: even after full recovery it stays halted until reset().
    r2 = nr.review(net_notional=Decimal(0), gross_notional=Decimal(0), equity=Decimal(1000))
    assert r2.halted
    nr.reset()
    r3 = nr.review(net_notional=Decimal(0), gross_notional=Decimal(0), equity=Decimal(1000))
    assert not r3.halted
