from decimal import Decimal

from babylon.data.models import AllMids, Bbo, Candle, L2Book, Trade, TradeSide


def _book(bids, asks, coin="ETH", time=1700000000000, ver_num=None):
    return L2Book.from_ws(
        {
            "coin": coin,
            "time": time,
            "levels": [
                [{"px": str(p), "sz": str(s), "n": n} for p, s, n in bids],
                [{"px": str(p), "sz": str(s), "n": n} for p, s, n in asks],
            ],
        },
        ver_num=ver_num,
    )


def test_trade_side_is_taker_aggressor():
    # Hyperliquid trade side is the TAKER direction: "B" = market buy.
    buy = Trade.from_ws(
        {"coin": "BTC", "side": "B", "px": "65000", "sz": "0.1", "time": 1, "tid": 7}
    )
    sell = Trade.from_ws({"coin": "BTC", "side": "A", "px": "65000", "sz": "0.1", "time": 1})
    assert buy.side is TradeSide.BUY and buy.side.sign == 1
    assert sell.side is TradeSide.SELL and sell.side.sign == -1
    assert buy.to_row()["side"] == "B"


def test_l2book_mid_and_best():
    book = _book([(3000, 1, 2)], [(3002, 1, 1)])
    assert book.best_bid == Decimal("3000")
    assert book.best_ask == Decimal("3002")
    assert book.mid == Decimal("3001")


def test_empty_book_mid_is_none():
    book = _book([], [])
    assert book.mid is None
    assert book.is_valid()  # empty is not malformed


def test_book_validation_catches_crossed_and_misordered():
    assert _book([(3000, 1, 1)], [(3002, 1, 1)]).is_valid()
    # crossed: best bid >= best ask
    assert not _book([(3003, 1, 1)], [(3002, 1, 1)]).is_valid()
    # bids not descending
    assert not _book([(3000, 1, 1), (3001, 1, 1)], [(3002, 1, 1)]).is_valid()
    # asks not ascending
    assert not _book([(3000, 1, 1)], [(3002, 1, 1), (3001, 1, 1)]).is_valid()


def test_l2book_to_row_preserves_depth_and_n_and_vernum():
    book = _book([(100, 1, 3), (99, 2, 1)], [(102, 1, 5)], ver_num=42)
    row = book.to_row()
    assert row["bid_px"] == [100.0, 99.0]
    assert row["bid_n"] == [3, 1]
    assert row["ask_n"] == [5]
    assert row["ver_num"] == 42
    assert row["best_bid"] == 100.0 and row["best_ask"] == 102.0


def test_candle_alias_parsing():
    c = Candle.from_ws(
        {"s": "BTC", "i": "1h", "t": 1, "T": 2,
         "o": "1", "c": "2", "h": "3", "l": "0.5", "v": "10", "n": 4}
    )
    assert c.coin == "BTC" and c.interval == "1h"
    assert c.high == Decimal("3") and c.trades == 4


def test_bbo_to_row_floats_and_missing_side():
    b = Bbo.from_ws({"coin": "BTC", "time": 1, "bbo": [{"px": "100", "sz": "1", "n": 2}, None]})
    row = b.to_row()
    assert row["bid_px"] == 100.0 and row["bid_n"] == 2
    assert row["ask_px"] is None and row["ask_sz"] is None


def test_all_mids():
    m = AllMids.from_ws({"mids": {"BTC": "65000", "ETH": "3000"}})
    assert m.mids["BTC"] == Decimal("65000")
