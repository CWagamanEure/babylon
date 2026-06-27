from decimal import Decimal

from babylon.core import Order, TimeInForce
from babylon.execution.fill_model import Book, fill


def _order(size: float) -> Order:
    return Order(coin="BTC", size=Decimal(str(size)), price=None, reduce_only=False,
                 tif=TimeInForce.IOC, cloid="x")


def _book() -> Book:
    # asks: 100@2, 101@3, 102@5 ; bids: 99@2, 98@4  (visible 10 per side)
    return Book(bid_px=(99.0, 98.0), bid_sz=(2.0, 4.0),
                ask_px=(100.0, 101.0, 102.0), ask_sz=(2.0, 3.0, 5.0))


def test_buy_fills_at_touch_within_top_level():
    f, r = fill(_order(1), _book(), now=1)
    assert f is not None and f.price == Decimal("100.0") and r.filled
    assert abs(r.depth_fraction - 0.1) < 1e-9


def test_sell_hits_the_bid():
    f, _ = fill(_order(-1), _book(), now=1)
    assert f is not None and f.price == Decimal("99.0")


def test_walk_the_book_vwap():
    # buy 2.5 → 2@100 + 0.5@101 = 250.5 / 2.5 = 100.2
    f, _ = fill(_order(2.5), _book(), now=1)
    assert f is not None and f.price == Decimal("100.2")


def test_depth_cap_blocks_oversized_order_no_partial():
    # buy 4 of visible 10 = 0.4 > default cap 0.25 → NO fill (never a partial)
    f, r = fill(_order(4), _book(), now=1)
    assert f is None and not r.filled and r.no_fill_reason == "exceeds max_depth_fraction"


def test_exhausting_visible_depth_is_no_fill():
    f, r = fill(_order(100), _book(), now=1, max_depth_fraction=99.0)
    assert f is None and r.no_fill_reason == "insufficient depth"


def test_slippage_haircut_worsens_price():
    fb, _ = fill(_order(1), _book(), now=1, slippage_bps=10)
    fs, _ = fill(_order(-1), _book(), now=1, slippage_bps=10)
    assert fb is not None and fb.price == Decimal("100.1")  # buy pays more
    assert fs is not None and fs.price == Decimal("98.901")  # sell receives less (99*0.999)


def test_empty_side_is_no_fill():
    one_sided = Book(bid_px=(), bid_sz=(), ask_px=(100.0,), ask_sz=(5.0,))
    f, r = fill(_order(-1), one_sided, now=1)  # sell, but no bids
    assert f is None and r.no_fill_reason == "no liquidity this side"


def test_crossed_book_detected():
    assert Book((101.0,), (1.0,), (100.0,), (1.0,)).crossed
    assert not _book().crossed
