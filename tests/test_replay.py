from datetime import UTC, datetime

from babylon.data.replay import L2Replay, _days
from babylon.data.store import ParquetStore

BASE = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp() * 1000)


def _rec(t, bb, ba, ver=None):
    return dict(
        time=t, ver_num=ver, best_bid=bb, best_ask=ba,
        mid=(bb + ba) / 2 if bb and ba else None,
        bid_px=[bb, bb - 1.0] if bb else [], bid_sz=[2.0, 4.0] if bb else [],
        bid_n=[1, 1] if bb else [],
        ask_px=[ba, ba + 1.0] if ba else [], ask_sz=[2.0, 3.0] if ba else [],
        ask_n=[1, 1] if ba else [],
    )


def _store(tmp_path):
    s = ParquetStore(tmp_path)
    s.write("l2Book", "BTC", _rec(BASE + 1000, 100.0, 101.0, ver=1))
    s.write("l2Book", "BTC", _rec(BASE + 1000, 100.0, 101.0, ver=1))  # dup (time,ver)
    s.write("l2Book", "BTC", _rec(BASE + 3000, 102.0, 103.0, ver=2))
    s.write("l2Book", "ETH", _rec(BASE + 2000, 50.0, 51.0, ver=1))
    s.write("l2Book", "BTC", _rec(BASE + 2500, 105.0, 104.0, ver=3))  # crossed
    s.write("l2Book", "ETH", _rec(BASE + 4000, None, None, ver=2))  # null
    s.flush()
    return s


def test_days_inclusive():
    assert _days("20260601", "20260603") == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert _days("20260601", "20260601") == ["2026-06-01"]


def test_replay_global_time_order_dedup_and_skip(tmp_path):
    _store(tmp_path)
    r = L2Replay(tmp_path, ["BTC", "ETH"], "20260601", "20260601")
    evs = list(r.events())
    # Global event-time order across coins; dup collapsed; crossed+null skipped.
    assert [(e.time - BASE, e.coin) for e in evs] == [(1000, "BTC"), (2000, "ETH"), (3000, "BTC")]
    assert r.skipped == 2
    assert evs[0].book.best_bid == 100.0 and len(evs[0].book.ask_px) == 2


def test_replay_deterministic(tmp_path):
    _store(tmp_path)

    def run():
        r = L2Replay(tmp_path, ["BTC", "ETH"], "20260601", "20260601")
        return [(e.time, e.coin) for e in r.events()]

    assert run() == run()


def test_clean_book_validates_list_columns():
    from babylon.data.replay import _clean_book

    assert _clean_book([100.0, 99.0], [2.0, 4.0], [101.0], [3.0]) is not None
    # NaN level dropped, valid level remains
    b = _clean_book([float("nan"), 99.0], [2.0, 4.0], [101.0], [3.0])
    assert b is not None and b.bid_px == (99.0,)
    # px/sz length mismatch → truncated to equal length (depth-cap bypass fix)
    b = _clean_book([100.0, 99.0, 98.0], [2.0, 4.0], [101.0], [3.0])
    assert b is not None and len(b.bid_px) == len(b.bid_sz) == 2
    # negative size → side empties → None; crossed top-of-book → None; one-sided → None
    assert _clean_book([100.0], [-5.0], [101.0], [3.0]) is None
    assert _clean_book([101.0], [2.0], [100.0], [3.0]) is None
    assert _clean_book([100.0], [2.0], [], []) is None


def test_replay_skips_malformed_archive_books(tmp_path):
    s = ParquetStore(tmp_path)
    s.write("l2Book", "BTC", _rec(BASE + 1000, 100.0, 101.0, ver=1))  # valid
    # list-crossed but scalar-uncrossed: scalars say 100/101, lists say bid 200 > ask 100
    s.write("l2Book", "BTC", dict(
        time=BASE + 2000, ver_num=2, best_bid=100.0, best_ask=101.0, mid=100.5,
        bid_px=[200.0], bid_sz=[2.0], bid_n=[1], ask_px=[100.0], ask_sz=[2.0], ask_n=[1]))
    s.flush()
    r = L2Replay(tmp_path, ["BTC"], "20260601", "20260601")
    evs = list(r.events())
    assert len(evs) == 1 and r.skipped == 1  # the list-crossed book is dropped


def test_replay_missing_days_graceful(tmp_path):
    _store(tmp_path)
    # Range spanning empty days on both sides — no crash, same 3 events.
    r = L2Replay(tmp_path, ["BTC", "ETH"], "20260530", "20260603")
    assert len(list(r.events())) == 3
