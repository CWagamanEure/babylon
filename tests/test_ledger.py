from decimal import Decimal

from babylon.portfolio.ledger import Ledger


def test_open_and_average_entry():
    led = Ledger(Decimal(1000))
    led.apply_fill("s", "BTC", Decimal(1), Decimal(100))
    led.apply_fill("s", "BTC", Decimal(1), Decimal(120))
    assert led.position("s", "BTC") == Decimal(2)
    # avg entry = 110, unrealized at 130 = 2*(130-110)=40
    assert led.unrealized_pnl({"BTC": Decimal(130)}) == Decimal(40)


def test_realize_on_close():
    led = Ledger(Decimal(1000))
    led.apply_fill("s", "BTC", Decimal(2), Decimal(100))
    led.apply_fill("s", "BTC", Decimal(-2), Decimal(110))  # close at +10/unit
    assert led.position("s", "BTC") == 0
    assert led.realized_pnl() == Decimal(20)


def test_flip_through_zero():
    led = Ledger(Decimal(1000))
    led.apply_fill("s", "BTC", Decimal(1), Decimal(100))
    led.apply_fill("s", "BTC", Decimal(-3), Decimal(110))  # close +10, open -2 @110
    assert led.position("s", "BTC") == Decimal(-2)
    assert led.realized_pnl() == Decimal(10)
    # new short entry is 110; at 100 unrealized = (100-110)*-2 = 20
    assert led.unrealized_pnl({"BTC": Decimal(100)}) == Decimal(20)


def test_net_position_across_strategies():
    led = Ledger(Decimal(1000))
    led.apply_fill("a", "BTC", Decimal(1), Decimal(100))
    led.apply_fill("b", "BTC", Decimal("-0.5"), Decimal(100))
    assert led.net_position("BTC") == Decimal("0.5")


def test_equity_includes_realized_and_unrealized():
    led = Ledger(Decimal(1000))
    led.apply_fill("s", "BTC", Decimal(1), Decimal(100))
    led.apply_fill("s", "BTC", Decimal(-1), Decimal(110))  # realized +10
    led.apply_fill("s", "ETH", Decimal(2), Decimal(50))  # open, unrealized
    eq = led.equity({"ETH": Decimal(55)})
    assert eq == Decimal(1000) + Decimal(10) + Decimal(10)
