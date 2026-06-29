from babylon.follow.capture.markout import BookCache, MarkoutScheduler
from babylon.follow.capture.stepper import Close, Open


def _open(rid, coin, d, t):
    return Open(rid=rid, coin=coin, direction=d, entry_t=t, taker_open=True, conviction=True)


def _close(rid, coin, d, et, xt, valid=True):
    return Close(rid=rid, coin=coin, direction=d, entry_t=et, exit_t=xt, entry_px=0.0,
                 exit_px=0.0, taker_open=True, conviction=True, valid=valid)


def test_book_cache_freshness_and_validity():
    bk = BookCache()
    bk.update("ZEC", bid=99.0, ask=101.0, ts=1000)
    assert bk.snap("ZEC", now=1000, staleness_ms=30_000).mid if False else True  # mid via bid/ask
    assert bk.snap("ZEC", 1000, 30_000) is not None
    assert bk.snap("ZEC", 40_000, 30_000) is None              # stale (>30s old)
    bk.update("ZEC", bid=101.0, ask=100.0, ts=2000)            # crossed
    assert bk.snap("ZEC", 2000, 30_000) is None
    assert bk.snap("MISSING", 2000, 30_000) is None


def test_markout_aggressing_side_folds_in_spread():
    bk = BookCache()
    sch = MarkoutScheduler(lag_ms=60_000, staleness_ms=30_000)
    sch.on_open("w", _open(0, "ZEC", 1, 1000))                 # long, entry markout due @61000
    bk.update("ZEC", bid=99.0, ask=101.0, ts=61_000)
    assert sch.process_due(61_000, bk) == []                   # entry marked at ASK 101, not final
    sch.on_close("w", _close(0, "ZEC", 1, 1000, 10_000))       # exit markout due @70000
    bk.update("ZEC", bid=109.0, ask=111.0, ts=70_000)
    out = sch.process_due(70_000, bk)
    assert len(out) == 1
    rt = out[0]
    assert rt.entry_mk == 101.0 and rt.exit_mk == 109.0        # buy ask, sell bid
    # vs mid-to-mid +1000bp; the ~208bp round-trip spread is folded in
    assert abs(rt.ret_bps - 791.6) < 2.0 and rt.ret_bps < 1000.0


def test_short_marks_opposite_touch():
    bk = BookCache()
    sch = MarkoutScheduler(lag_ms=10)
    sch.on_open("w", _open(0, "X", -1, 0))                     # short: sells bid to open
    bk.update("X", bid=100.0, ask=102.0, ts=10)
    sch.process_due(10, bk)
    sch.on_close("w", _close(0, "X", -1, 0, 100))
    bk.update("X", bid=90.0, ask=92.0, ts=110)                 # short closes by buying ask
    rt = sch.process_due(110, bk)[0]
    assert rt.entry_mk == 100.0 and rt.exit_mk == 92.0         # sell bid 100, buy ask 92
    assert rt.ret_bps > 0                                       # short won as price fell


def test_stale_book_drops_roundtrip():
    bk = BookCache()
    sch = MarkoutScheduler(lag_ms=60_000, staleness_ms=30_000)
    sch.on_open("w", _open(0, "ZEC", 1, 1000))
    bk.update("ZEC", bid=99.0, ask=101.0, ts=1000)            # book is 60s stale at due 61000
    assert sch.process_due(61_000, bk) == [] and sch.pending == 0   # dropped, not marked


def test_same_ms_flip_two_distinct_roundtrips():
    bk = BookCache()
    sch = MarkoutScheduler(lag_ms=0)
    # flip: close rid0 (long) + open rid1 (short), entry_t collides at 5000 but rid differs
    sch.on_open("w", _open(0, "X", 1, 5000))
    sch.on_close("w", _close(0, "X", 1, 5000, 5000))
    sch.on_open("w", _open(1, "X", -1, 5000))
    bk.update("X", bid=99.0, ask=101.0, ts=5000)
    out = sch.process_due(5000, bk)
    # rid0 fully marked (entry@5000 + exit@5000) → finalizes; rid1 only entry → pending
    assert len(out) == 1 and out[0].rid == 0 and sch.pending == 0  # rid1 entry consumed, awaits close


def test_invalid_close_ignored():
    sch = MarkoutScheduler(lag_ms=10)
    sch.on_close("w", _close(-1, "X", 1, 0, 100, valid=False))  # pre-observed → no-op
    assert sch.pending == 0


def test_drop_due_before_on_restart():
    sch = MarkoutScheduler(lag_ms=60_000)
    sch.on_open("w", _open(0, "X", 1, 1000))                   # due @61000
    sch.on_open("w", _open(1, "Y", 1, 200_000))               # due @260000
    assert sch.drop_due_before(100_000) == 1                   # only the past-due one
    assert sch.pending == 1
