from babylon.follow.capture.markout import BookCache, FinalRoundtrip, MarkoutScheduler
from babylon.follow.capture.scorer import CaptureScorer
from babylon.follow.capture.stepper import Open
from babylon.follow.capture.store import RoundtripStore

DAY = 86_400_000


def _closed(wallet, coin, rid, exit_t, ret):
    return FinalRoundtrip(wallet, coin, rid, 1, exit_t - 1000, exit_t, 100.0, 100.0, ret,
                          True, True, "live")


def test_returns_is_closed_window_when_no_open(tmp_path):
    store = RoundtripStore(tmp_path / "db")
    t0 = 100 * DAY
    lo = t0 - 30 * DAY
    store.add(_closed("w", "ZEC", 0, lo + 1000, 100.0))
    store.add(_closed("w", "ZEC", 1, lo + 2000, 50.0))
    store.add(_closed("w", "ZEC", 2, t0 + 5000, 999.0))         # AFTER t0 → excluded by seam
    sc = CaptureScorer(store, MarkoutScheduler(lag_ms=0), BookCache(), train_days=30)
    r = sc.returns_fn("w", t0)
    assert sorted(r.tolist()) == [50.0, 100.0]                  # only in-window closed
    store.close()


def test_mtm_open_loser_lowers_score_disposition_fix(tmp_path):
    store = RoundtripStore(tmp_path / "db")
    t0 = 100 * DAY
    lo = t0 - 30 * DAY
    store.add(_closed("w", "ZEC", 0, lo + 1000, 100.0))         # two closed WINNERS
    store.add(_closed("w", "SOL", 1, lo + 2000, 100.0))
    sch = MarkoutScheduler(lag_ms=0)
    bk = BookCache()
    # an open long, still held, now deeply underwater (the loser disposition wallets sit on)
    sch.on_open("w", Open(rid=5, coin="APT", direction=1, entry_t=lo + 5000,
                          taker_open=True, conviction=True))
    bk.update("APT", bid=99.0, ask=101.0, ts=lo + 5000)
    sch.process_due(lo + 5000, bk)                              # entry marked at ask 101
    bk.update("APT", bid=80.0, ask=82.0, ts=t0)                # APT crashed
    sc = CaptureScorer(store, sch, bk, train_days=30)
    r = sc.returns_fn("w", t0)
    closed_only = store.returns("w", lo, t0)
    assert len(closed_only) == 2 and len(r) == 3                # the open loser is INCLUDED
    assert r[2] < 0                                             # MTM of the underwater long
    assert r.mean() < closed_only.mean()                       # disposition fix pulls the score down
    store.close()


def test_active_candidates(tmp_path):
    store = RoundtripStore(tmp_path / "db")
    t0 = 100 * DAY
    lo = t0 - 30 * DAY
    for i in range(3):
        store.add(_closed("active", "ZEC", i, lo + i, 10.0))
    store.add(_closed("thin", "SOL", 0, lo + 1, 10.0))
    sc = CaptureScorer(store, MarkoutScheduler(lag_ms=0), BookCache(), train_days=30)
    assert sc.active_candidates(t0, min_positions=3) == ["active"]
    store.close()
