from decimal import Decimal

from babylon.core import Order, TimeInForce
from babylon.execution.fill_model import Book
from babylon.execution.paper import PaperExecutor


def _order(size):
    return Order(coin="ZEC", size=Decimal(str(size)), price=None, reduce_only=False,
                 tif=TimeInForce.IOC, cloid="c1")


def _book():
    # ask side: 100@10, 101@10 ; bid side: 99@10, 98@10
    return Book(bid_px=(99.0, 98.0), bid_sz=(10.0, 10.0),
                ask_px=(100.0, 101.0), ask_sz=(10.0, 10.0))


def test_retail_depth_walk_with_fee_and_impact():
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.9)
    # buy 15 -> walks 10@100 + 5@101 = VWAP 100.333..., +10.5bp (fee+impact) folded in
    f, rep = ex.submit_book(_order(15), _book(), now=1)
    assert rep.filled and f is not None
    vwap = (10 * 100 + 5 * 101) / 15
    assert abs(float(f.price) - vwap * (1 + 10.5 / 1e4)) < 1e-6   # cost IN the price
    assert ex.net_position("ZEC") == Decimal("15")


def test_retail_depth_cap_no_fill():
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", max_depth_frac=0.25)
    # buy 15 of 20 visible ask = 75% > 25% cap -> no fill, net unchanged
    f, rep = ex.submit_book(_order(15), _book(), now=1)
    assert f is None and not rep.filled and ex.net_position("ZEC") == Decimal(0)


def test_validator_fills_at_wallet_price():
    ex = PaperExecutor(mode="validator", maker_cost_bps=2.0)
    f, rep = ex.submit_book(_order(15), _book(), now=1, wallet_px=Decimal("100"))
    assert rep.filled and f is not None
    assert abs(float(f.price) - 100 * (1 + 2.0 / 1e4)) < 1e-9   # wallet price + maker cost
    assert ex.net_position("ZEC") == Decimal("15")


def test_validator_requires_wallet_px():
    ex = PaperExecutor(mode="validator")
    f, rep = ex.submit_book(_order(15), _book(), now=1)  # no wallet_px
    assert f is None and not rep.filled


def test_sell_side_cost_direction():
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.9)
    f, _ = ex.submit_book(_order(-15), _book(), now=1)   # sell walks the bid
    vwap = (10 * 99 + 5 * 98) / 15
    assert f is not None and float(f.price) < vwap       # sell receives LESS (cost against)
    assert ex.net_position("ZEC") == Decimal("-15")
