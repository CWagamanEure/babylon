"""Tests for the harvest wiring: watcher open-detection, tail-aware sizing, HarvestRunner.step."""
import asyncio

import numpy as np

from babylon.execution.fill_model import Book
from babylon.execution.paper import PaperExecutor
from babylon.follow.harvest import HarvestLedger
from babylon.follow.harvest_runner import HarvestRunner
from babylon.follow.scheduler import _downside_dev, tail_aware_notionals
from babylon.follow.skill import OpenEvent
from babylon.follow.watcher import WalletWatcher

H = 3_600_000
SIX_H = 6 * H


def _book(mid=100.0, sz=1000.0):
    return Book(bid_px=(mid - 0.05,), bid_sz=(sz,), ask_px=(mid + 0.05,), ask_sz=(sz,))


def _ev(direction=1, taker=True, conv=True, t=0):
    return OpenEvent(entry_t=t, direction=direction, taker_open=taker, conviction=conv,
                     is_leading=False, notional=1000.0)


# ── watcher open detection (live ≡ open_events) ───────────────────────────────────────────
class _FakeSrc:
    def __init__(self, fills): self._fills = fills
    async def user_fills_by_time(self, addr, since, now):
        return [f for f in self._fills if since <= int(f["time"]) <= now]
    async def clearinghouse_state(self, addr): return {"assetPositions": []}


def _fill(t, side, sz, sp, coin="BTC", px=100.0, crossed=True, hsh="0xreal", tid=None):
    return {"time": t, "coin": coin, "side": side, "px": px, "sz": sz, "crossed": crossed,
            "startPosition": sp, "hash": hsh, "tid": tid if tid is not None else t}


def test_watcher_detects_one_open_per_position():
    # open (B, flat->+1), add (B, +1->+2, NO new open), close (A, +2->0)
    fills = [_fill(1, "B", 1.0, 0.0, tid=1), _fill(2, "B", 1.0, 1.0, tid=2),
             _fill(3, "A", 2.0, 2.0, tid=3)]
    seen = []
    w = WalletWatcher(_FakeSrc(fills), ["0xw"], min_interval_s=0.0,
                      on_opens=lambda wal, ops: seen.append((wal, ops)))
    asyncio.run(w.poll_wallet("0xw", now_ms=10))
    assert len(seen) == 1
    wal, ops = seen[0]
    assert wal == "0xw" and len(ops) == 1            # ONE open (the add did not emit)
    coin, ev = ops[0]
    assert coin == "BTC" and ev.direction == 1 and ev.taker_open and ev.conviction


def test_watcher_detects_flip_as_two_opens():
    # flat->long, then a big sell that closes AND flips short in one fill -> two opens total
    fills = [_fill(1, "B", 1.0, 0.0, tid=1), _fill(2, "A", 3.0, 1.0, tid=2)]  # +1, then -2 → flip
    seen = []
    w = WalletWatcher(_FakeSrc(fills), ["0xw"], min_interval_s=0.0,
                      on_opens=lambda wal, ops: seen.append(ops))
    asyncio.run(w.poll_wallet("0xw", now_ms=10))
    ops = seen[0]
    dirs = sorted(ev.direction for _, ev in ops)
    assert dirs == [-1, 1]                            # the long open + the flipped short open


def test_watcher_no_sink_no_emit():
    # default (mirror runner): no sink, poll still updates position, no crash
    w = WalletWatcher(_FakeSrc([_fill(1, "B", 1.0, 0.0)]), ["0xw"], min_interval_s=0.0)
    assert asyncio.run(w.poll_wallet("0xw", now_ms=10)) == 1
    assert w.position("0xw", "BTC") == 1.0


# ── tail-aware sizing ─────────────────────────────────────────────────────────────────────
def test_downside_dev_floored_and_basic():
    assert _downside_dev(np.array([-10.0, -10.0, -10.0])) >= 10.0 - 1e-6   # all negative
    # zero-downside sample is floored (not 0) so the ratio can't blow up
    assert _downside_dev(np.array([5.0, 5.0, 6.0])) > 0.0


def test_tail_aware_sizes_down_fatter_left_tail():
    # same edge (mean), but B has a fatter LEFT tail -> bigger downside_dev -> SMALLER notional
    a = np.array([20.0] * 10 + [10.0] * 10)               # mean 15, tiny downside
    b = np.array([120.0] * 10 + [-90.0] * 10)             # mean 15, big downside
    nz = tail_aware_notionals({"A": a, "B": b}, base_notional=1000.0, ratio_cap=100.0)
    assert nz["A"] > nz["B"] > 0.0                        # fatter left tail → bet less


def test_tail_aware_zero_for_nonpositive_edge():
    nz = tail_aware_notionals({"neg": np.array([-5.0, -6.0, -7.0, -8.0, -9.0])},
                              base_notional=1000.0)
    assert nz["neg"] == 0.0


def test_tail_aware_ratio_cap_and_max():
    # a thin low-downside wallet would size huge; ratio_cap + max_notional bound it
    r = np.array([50.0, 51.0, 49.0, 50.0, 50.0])         # high mean, ~no downside
    nz = tail_aware_notionals({"w": r}, base_notional=1000.0, kelly_frac=1.0,
                              ratio_cap=3.0, max_notional=2500.0)
    assert nz["w"] <= 2500.0 + 1e-9


# ── HarvestRunner end-to-end (real PaperExecutor) ─────────────────────────────────────────
def _runner(**led):
    ledger = HarvestLedger(entry_lag_ms=0, horizon_ms=SIX_H, **led)
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.25)
    r = HarvestRunner(ledger, {"w": 1000.0}, ex, universe={"BTC"})
    return r, ledger, ex


def test_runner_full_harvest_long():
    r, ledger, ex = _runner()
    assert r.ingest_opens("w", [("BTC", _ev(direction=1, t=0))]) == 1
    r.on_book("BTC", _book(mid=100.0), ts=0)
    tick = r.step(now_wall=0)
    assert tick.entries == 1 and ex.net_position("BTC") > 0          # long position opened
    # before expiry: nothing
    assert r.step(now_wall=SIX_H - 1).exits == 0
    # at expiry, with the price up to 110, the harvest realizes ~ +1000bp minus cost
    r.on_book("BTC", _book(mid=110.0), ts=SIX_H)
    tick = r.step(now_wall=SIX_H)
    assert tick.exits == 1 and len(tick.realized) == 1
    rt = tick.realized[0]
    assert 700.0 < rt.raw_bps < 1000.0                              # long 100->110, net of cost
    assert abs(float(ex.net_position("BTC"))) < 1e-9                # flat after harvest


def test_runner_filters_non_taker_and_non_universe():
    r, ledger, _ = _runner()
    assert r.ingest_opens("w", [("BTC", _ev(taker=False, t=1))]) == 0   # not taker
    assert r.ingest_opens("w", [("BTC", _ev(conv=False, t=2))]) == 0    # not conviction
    assert r.ingest_opens("w", [("ETH", _ev(t=3))]) == 0               # not in universe
    assert r.ingest_opens("w", [("BTC", _ev(t=4))]) == 1               # this one counts


def test_runner_stale_book_defers_entry():
    r, ledger, ex = _runner()
    r.ingest_opens("w", [("BTC", _ev(t=0))])
    r.on_book("BTC", _book(), ts=0)
    tick = r.step(now_wall=10 * H)            # book ts=0, now=10h ≫ staleness → no entry
    assert tick.entries == 0 and tick.no_fill.get("BTC") == "stale_book_entry"
    assert ex.net_position("BTC") == 0
    # fresh book → the still-PENDING tranche enters on the next step (not dropped)
    r.on_book("BTC", _book(), ts=10 * H)
    assert r.step(now_wall=10 * H).entries == 1


def test_runner_exit_retries_until_book_fresh():
    r, ledger, ex = _runner()
    r.ingest_opens("w", [("BTC", _ev(t=0))])
    r.on_book("BTC", _book(mid=100.0), ts=0)
    r.step(now_wall=0)                                   # entered
    # expiry reached but the book is stale → exit deferred, tranche stays OPEN
    tick = r.step(now_wall=SIX_H)
    assert tick.exits == 0 and tick.no_fill.get("BTC") == "stale_book_exit"
    assert len(ledger.open_tranches()) == 1
    # fresh book → exit completes
    r.on_book("BTC", _book(mid=100.0), ts=SIX_H + 60_000)
    assert r.step(now_wall=SIX_H + 60_000).exits == 1


def test_runner_idempotent_open_across_polls():
    r, ledger, _ = _runner()
    op = [("BTC", _ev(t=5))]
    assert r.ingest_opens("w", op) == 1
    assert r.ingest_opens("w", op) == 0                  # same open re-seen next poll → ignored


def test_watcher_sink_drives_ledger():
    # the live signal path: poll → watcher emits opens → runner.ingest_opens → ledger tranche
    ledger = HarvestLedger(entry_lag_ms=0, horizon_ms=SIX_H)
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.25)
    src = _FakeSrc([_fill(1, "B", 1.0, 0.0, tid=1)])     # one conviction taker open on BTC
    w = WalletWatcher(src, ["0xw"], min_interval_s=0.0)
    r = HarvestRunner(ledger, {"0xw": 1000.0}, ex, universe={"BTC"}, watcher=w, roster=["0xw"])
    w.set_opens_sink(r.ingest_opens)
    asyncio.run(w.poll_wallet("0xw", now_ms=10))
    assert [t.id for t in ledger.due_entries(10)] == ["0xw:BTC:1:1"]  # id = wallet:coin:entry_t:tid


def test_ledger_checkpoint_roundtrip_preserves_open():
    led = HarvestLedger(entry_lag_ms=0, horizon_ms=SIX_H)
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1, notional=1000.0,
                      open_event_ms=0)
    led.due_entries(0); led.on_entry_fill("e", 100.0, 0)        # noqa: E702 — OPEN, clock running
    led2 = HarvestLedger(entry_lag_ms=0, horizon_ms=SIX_H)
    led2.from_state(led.to_state())
    assert len(led2.open_tranches()) == 1
    rt = led2.on_exit_fill("e", 110.0, SIX_H)                   # resumes + harvests after restart
    assert abs(rt.raw_bps - 1000.0) < 1e-6 and rt.entry_lag_ms == 0


def test_runner_checkpoint_roundtrip(tmp_path):
    r, ledger, ex = _runner()
    r.ingest_opens("w", [("BTC", _ev(t=0))])
    r.on_book("BTC", _book(mid=100.0), ts=0)
    r.step(now_wall=0)                                          # opened a position
    ck = tmp_path / "harvest_ckpt.json"
    r.checkpoint(ck)
    # restore into a fresh runner/ledger/executor
    led2 = HarvestLedger(entry_lag_ms=0, horizon_ms=SIX_H)
    ex2 = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.25)
    r2 = HarvestRunner(led2, {"w": 1000.0}, ex2, universe={"BTC"})
    import json
    r2.from_state(json.loads(ck.read_text()))
    assert len(led2.open_tranches()) == 1 and ex2.net_position("BTC") > 0   # position restored
    r2.on_book("BTC", _book(mid=110.0), ts=SIX_H)
    assert r2.step(now_wall=SIX_H).exits == 1                   # harvests the resumed tranche
