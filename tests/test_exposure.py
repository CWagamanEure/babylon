from decimal import Decimal

from babylon.risk.exposure import ExposureMonitor, compute_exposure

MARKS = {"BTC": Decimal(100), "ETH": Decimal(100)}
EQUITY = Decimal(1000)


def test_all_long_is_fully_directional():
    exp = compute_exposure({"BTC": Decimal(5), "ETH": Decimal(3)}, MARKS, EQUITY)
    assert exp.gross_long == 800.0 and exp.gross_short == 0.0
    assert exp.net_directional == 800.0
    assert exp.directional_bias == 1.0
    assert exp.neutrality == 0.0  # entirely one-directional
    assert exp.net_leverage == 0.8


def test_balanced_book_is_market_neutral_proxy():
    exp = compute_exposure({"BTC": Decimal(5), "ETH": Decimal(-5)}, MARKS, EQUITY)
    assert exp.gross_long == 500.0 and exp.gross_short == 500.0
    assert exp.net_directional == 0.0
    assert exp.directional_bias == 0.0
    assert exp.neutrality == 1.0  # balanced long/short $
    assert exp.net_leverage == 1.0  # gross still 1000


def test_partial_tilt():
    exp = compute_exposure({"BTC": Decimal(6), "ETH": Decimal(-2)}, MARKS, EQUITY)
    # long 600, short 200 → net +400 on gross 800 → bias +0.5
    assert exp.directional_bias == 0.5
    assert round(exp.neutrality, 3) == 0.5


def test_concentration_tracks_top_coin():
    exp = compute_exposure({"BTC": Decimal(7), "ETH": Decimal(1)}, MARKS, EQUITY)
    assert exp.top_coin == "BTC"
    assert exp.top_concentration == 0.7  # 700 / 1000
    assert exp.concentration["ETH"] == 0.1


def test_empty_book_is_flat():
    exp = compute_exposure({}, MARKS, EQUITY)
    assert exp.gross == 0.0 and exp.directional_bias == 0.0 and exp.neutrality == 1.0


def test_monitor_returns_exposure_and_does_not_enforce():
    mon = ExposureMonitor(max_directional_frac=0.1, max_concentration_frac=0.2)
    exp = mon.assess({"BTC": Decimal(9)}, MARKS, EQUITY)  # breaches both (warns only)
    assert exp.top_concentration == 0.9  # returned unchanged — tracking, not capping
