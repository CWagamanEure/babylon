import asyncio
from decimal import Decimal

import pytest

from babylon.execution.fill_model import Book
from babylon.execution.paper import PaperExecutor
from babylon.follow.runner import FollowRunner, book_from_l2
from babylon.follow.watcher import WalletWatcher
from babylon.sizing.sizer import FixedFractionSizer


class _Src:
    def __init__(self): self.fail = False; self.chs = []
    async def user_fills_by_time(self, a, s, e):
        if self.fail: raise RuntimeError("api down")
        return []
    async def clearinghouse_state(self, a): return {"assetPositions": self.chs}


def _book(mid=100.0, sz=100.0):
    return Book(bid_px=(mid - 0.05,), bid_sz=(sz,), ask_px=(mid + 0.05,), ask_sz=(sz,))


def _runner(weights, *, per_coin=0.05, max_coin=0.08, **kw):
    w = WalletWatcher(_Src(), list(weights), min_interval_s=0.0)
    sizer = FixedFractionSizer(per_coin_fraction=per_coin)
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.25)
    r = FollowRunner(w, weights, ["ZEC"], sizer, ex, budget_usd=1000.0, max_coin_frac=max_coin,
                     staleness_ms=30_000, exit_staleness_ms=300_000, min_rebalance_usd=5.0,
                     flip_cooldown_ms=300_000, **kw)
    r._last_poll_mono = 0          # fresh heartbeat (monotonic) for reconcile tests
    return r, w, ex


def test_consensus_opens_position():
    r, w, ex = _runner({"a": 0.6, "b": 0.4})
    w._pos = {"a": {"ZEC": 5.0}, "b": {"ZEC": 2.0}}
    r.on_book("ZEC", _book(100.0), ts=1000)
    rep = r.tick(now_wall=1000, now_mono=1000)
    assert len(rep.fills) == 1 and ex.net_position("ZEC") == Decimal("0.5")


def test_stale_book_skipped():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=0)
    rep = r.tick(now_wall=40_000, now_mono=40_000)     # book age 40s > 30s
    assert rep.stale_skipped == ("ZEC",) and not rep.fills and ex.net_position("ZEC") == Decimal(0)


def test_per_coin_cap_binds():
    r, w, ex = _runner({"a": 1.0}, per_coin=0.20, max_coin=0.08)
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0, sz=1000.0), ts=1)
    r.tick(now_wall=1, now_mono=1)
    assert ex.net_position("ZEC") == Decimal("0.8")


def test_deadband_no_rechurn():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=1); r.tick(1, 1)
    r.on_book("ZEC", _book(100.0), ts=2)
    assert not r.tick(2, 2).fills


def test_thin_book_no_fill_reported():
    r, w, ex = _runner({"a": 1.0}, per_coin=0.20, max_coin=0.50)
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0, sz=1.0), ts=1)
    rep = r.tick(1, 1)
    assert "ZEC" in rep.no_fills and ex.net_position("ZEC") == Decimal(0)


# --- the audit hardening ---

def test_validator_executor_fails_fast():
    w = WalletWatcher(_Src(), ["a"], min_interval_s=0.0)
    with pytest.raises(ValueError, match="validator"):
        FollowRunner(w, {"a": 1.0}, ["ZEC"], FixedFractionSizer(per_coin_fraction=0.05),
                     PaperExecutor(mode="validator"), budget_usd=1000.0)


def test_heartbeat_only_fresh_on_poll_success():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r._last_poll_mono = None                            # never polled
    r.on_book("ZEC", _book(100.0), ts=1)
    assert r.tick(1, 1).halted                          # halted: no fresh signal
    # a totally-failing poll must NOT refresh the heartbeat
    w._src.fail = True
    ok = asyncio.run(r.poll(now_wall=1, now_mono=1))
    assert ok == 0 and r._last_poll_mono is None and r.tick(2, 2).halted


def test_halt_flattens_open_position():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=1); r.tick(1, 1)
    assert ex.net_position("ZEC") == Decimal("0.5")
    r._last_poll_mono = None                            # signal dies → halt
    r.on_book("ZEC", _book(100.0), ts=2)               # but the book is fresh
    rep = r.tick(2, 5_000_000)                          # mono way past heartbeat
    assert rep.halted and ex.net_position("ZEC") == Decimal(0)  # reduce-only flatten


def test_stale_book_allows_exit_within_window():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=0); r.tick(0, 0)
    assert ex.net_position("ZEC") == Decimal("0.5")
    w._pos = {"a": {}}                                  # wallet flat → we want to exit
    # book now 60s stale: blocks entries, but exit allowed (< 300s exit window)
    rep = r.tick(now_wall=60_000, now_mono=60_000)
    assert ex.net_position("ZEC") == Decimal(0) and "ZEC" not in rep.frozen


def test_frozen_when_no_exit_possible():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=0); r.tick(0, 0)
    w._pos = {"a": {}}
    rep = r.tick(now_wall=400_000, now_mono=400_000)   # book 400s stale > 300s exit window
    assert "ZEC" in rep.frozen and ex.net_position("ZEC") == Decimal("0.5")  # can't flatten


def test_flip_hysteresis_gates_fast_reversal():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=1); r.tick(now_wall=1, now_mono=1)
    assert ex.net_position("ZEC") == Decimal("0.5")
    w._pos = {"a": {"ZEC": -5.0}}                       # flips short
    r.on_book("ZEC", _book(100.0), ts=2)
    r.tick(now_wall=2, now_mono=2)                      # within cooldown → gated
    assert ex.net_position("ZEC") == Decimal("0.5")
    r.on_book("ZEC", _book(100.0), ts=400_000)
    r.tick(now_wall=400_000, now_mono=400_000)          # past cooldown → reverses
    assert ex.net_position("ZEC") == Decimal("-0.5")


def test_mtm_equity_de_levers():
    eq = {"v": 1000.0}
    r, w, ex = _runner({"a": 1.0}, equity_fn=lambda: eq["v"])
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=1); r.tick(1, 1)
    full = ex.net_position("ZEC")
    eq["v"] = 500.0                                     # equity halves → target halves
    r.on_book("ZEC", _book(100.0), ts=2); r.tick(2, 2)
    assert ex.net_position("ZEC") == full / 2


def test_book_from_l2():
    from babylon.data.models import L2Book
    l2 = L2Book.from_ws({"coin": "ZEC", "time": 5,
                         "levels": [[{"px": "99", "sz": "10", "n": 1}],
                                    [{"px": "100", "sz": "10", "n": 1}]]})
    b = book_from_l2(l2)
    assert b.best_bid == 99.0 and b.best_ask == 100.0 and b.bid_sz == (10.0,)


def test_run_loop_ticks_and_stops():
    r, w, ex = _runner({"a": 1.0})
    w._src.chs = [{"position": {"coin": "ZEC", "szi": "5.0"}}]   # truth-up keeps the position
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=0)
    c = {"t": 0}
    def now(): c["t"] += 1; return c["t"]
    async def drive():
        stop = asyncio.Event()
        task = asyncio.create_task(
            r.run(now, now, tick_s=0.002, poll_pause_s=0.002, truthup_every=10**9, stop=stop))
        await asyncio.sleep(0.05); stop.set(); await task
    asyncio.run(drive())
    assert ex.net_position("ZEC") == Decimal("0.5")


def test_tick_isolation_survives_bad_tick():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}; r.on_book("ZEC", _book(100.0), ts=0)
    calls = {"n": 0}
    def boom(nw, nm):
        calls["n"] += 1; raise ValueError("bad tick")
    r.tick = boom  # type: ignore[method-assign]
    async def drive():
        stop = asyncio.Event()
        task = asyncio.create_task(
            r.run(lambda: 1, lambda: 1, tick_s=0.001, poll_pause_s=0.001, stop=stop))
        await asyncio.sleep(0.03); stop.set(); await task   # raising ticks are caught; stops clean
    asyncio.run(asyncio.wait_for(drive(), timeout=2.0))
    assert calls["n"] >= 2                                   # ran repeatedly without crashing
