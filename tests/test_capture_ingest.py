from babylon.follow.capture.ingest import Fill, FillIngest
from babylon.follow.capture.stepper import Close, Open


class _FakeSched:
    def __init__(self): self.opens = []; self.closes = []
    def on_open(self, w, ev): self.opens.append(ev)
    def on_close(self, w, ev): self.closes.append(ev)


def _f(coin, t, side, sz, tid, px=100.0):
    return Fill(coin=coin, time=t, px=px, sz=sz, side=side, crossed=True, tid=tid, hsh="0xr")


def test_in_order_fills_produce_one_roundtrip():
    s = _FakeSched()
    ing = FillIngest(s, lateness_ms=2000)  # type: ignore[arg-type]
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))   # open long
    ing.on_fill("w", _f("ZEC", 5000, "A", 1.0, 11))   # close
    ing.flush()
    assert len(s.opens) == 1 and len(s.closes) == 1
    assert isinstance(s.opens[0], Open) and isinstance(s.closes[0], Close)
    assert s.closes[0].entry_t == 1000 and s.closes[0].exit_t == 5000


def test_dedup_drops_replayed_tid():
    s = _FakeSched()
    ing = FillIngest(s, lateness_ms=2000)  # type: ignore[arg-type]
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))   # replayed on resubscribe → ignored
    ing.on_fill("w", _f("ZEC", 5000, "A", 1.0, 11))
    ing.flush()
    assert ing.dropped_dup == 1 and len(s.opens) == 1  # not double-applied (no phantom add)


def test_reorder_fixes_out_of_order_arrival():
    # the close ARRIVES before the open; the reorder buffer must feed the stepper open-then-close,
    # NOT close-first (which would make a negative-hold phantom)
    s = _FakeSched()
    ing = FillIngest(s, lateness_ms=2000)  # type: ignore[arg-type]
    ing.on_fill("w", _f("ZEC", 5000, "A", 1.0, 11))   # close arrives FIRST
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))   # open arrives second (within lateness)
    ing.flush()
    assert len(s.opens) == 1 and len(s.closes) == 1
    assert s.closes[0].entry_t == 1000 and s.closes[0].exit_t == 5000  # ordered correctly
    assert s.closes[0].exit_t > s.closes[0].entry_t                    # no negative hold


def test_too_late_fill_dropped():
    s = _FakeSched()
    ing = FillIngest(s, lateness_ms=500)  # type: ignore[arg-type]
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))
    ing.on_fill("w", _f("ZEC", 5000, "A", 1.0, 11))   # watermark 5000 → releases open@1000
    assert s.opens                                     # open released (last_released=1000)
    ing.on_fill("w", _f("ZEC", 500, "B", 1.0, 12))    # arrives older than last released → drop
    assert ing.dropped_late == 1


def test_flush_releases_buffered_tail():
    s = _FakeSched()
    ing = FillIngest(s, lateness_ms=10_000)  # type: ignore[arg-type]
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))   # buffered (no later watermark to settle it)
    assert not s.opens                                 # still held by lateness window
    ing.flush()
    assert len(s.opens) == 1                           # flush releases it


def test_distinct_coins_isolated():
    s = _FakeSched()
    ing = FillIngest(s, lateness_ms=2000)  # type: ignore[arg-type]
    ing.on_fill("w", _f("ZEC", 1000, "B", 1.0, 10))
    ing.on_fill("w", _f("SOL", 1100, "B", 2.0, 11))
    ing.on_fill("w", _f("ZEC", 5000, "A", 1.0, 12))
    ing.on_fill("w", _f("SOL", 5100, "A", 2.0, 13))
    ing.flush()
    assert len(s.opens) == 2 and len(s.closes) == 2    # two independent round-trips, no cross-coin
    assert {c.coin for c in s.closes} == {"ZEC", "SOL"}
