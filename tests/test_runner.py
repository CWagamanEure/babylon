from decimal import Decimal

from babylon.execution.fill_model import Book
from babylon.execution.paper import PaperExecutor
from babylon.follow.runner import FollowRunner
from babylon.follow.watcher import WalletWatcher
from babylon.sizing.sizer import FixedFractionSizer


class _Src:
    async def user_fills_by_time(self, a, s, e): return []
    async def clearinghouse_state(self, a): return {"assetPositions": []}


def _book(mid=100.0, sz=100.0):
    return Book(bid_px=(mid - 0.05,), bid_sz=(sz,), ask_px=(mid + 0.05,), ask_sz=(sz,))


def _runner(weights, *, per_coin=0.05, max_coin=0.08):
    w = WalletWatcher(_Src(), list(weights), min_interval_s=0.0)
    sizer = FixedFractionSizer(per_coin_fraction=per_coin)
    ex = PaperExecutor(taker_fee_bps=4.5, mode="retail", impact_bps=6.0, max_depth_frac=0.25)
    r = FollowRunner(w, weights, ["ZEC"], sizer, ex, budget_usd=1000.0,
                     max_coin_frac=max_coin, staleness_ms=30_000, min_rebalance_usd=5.0)
    return r, w, ex


def test_consensus_opens_position():
    r, w, ex = _runner({"a": 0.6, "b": 0.4})
    w._pos = {"a": {"ZEC": 5.0}, "b": {"ZEC": 2.0}}    # both long → consensus +1
    r.on_book("ZEC", _book(100.0), ts=1000)
    rep = r.tick(now=1000)
    assert len(rep.fills) == 1
    # target = 0.05 * 1.0 * 1000/100 = 0.5 units, long
    assert ex.net_position("ZEC") == Decimal("0.5")


def test_stale_book_skipped():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=0)
    rep = r.tick(now=40_000)                            # > staleness_ms → skip
    assert rep.stale_skipped == ("ZEC",) and not rep.fills and ex.net_position("ZEC") == Decimal(0)


def test_reconcile_reverses_on_flip():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}                        # long
    r.on_book("ZEC", _book(100.0), ts=1)
    r.tick(now=1)
    assert ex.net_position("ZEC") == Decimal("0.5")
    w._pos = {"a": {"ZEC": -5.0}}                       # flips short
    r.on_book("ZEC", _book(100.0), ts=2)
    r.tick(now=2)
    assert ex.net_position("ZEC") == Decimal("-0.5")   # reversed to the short target


def test_per_coin_cap_binds():
    r, w, ex = _runner({"a": 1.0}, per_coin=0.20, max_coin=0.08)  # fraction > cap
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0, sz=1000.0), ts=1)    # deep book so depth cap won't bind
    r.tick(now=1)
    # raw target 0.20*1000/100=2.0 capped to 0.08*1000/100=0.8 units
    assert ex.net_position("ZEC") == Decimal("0.8")


def test_deadband_no_rechurn():
    r, w, ex = _runner({"a": 1.0})
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0), ts=1)
    r.tick(now=1)
    r.on_book("ZEC", _book(100.0), ts=2)
    rep = r.tick(now=2)                                 # same target → delta 0 → no order
    assert not rep.fills


def test_thin_book_no_fill_reported():
    r, w, ex = _runner({"a": 1.0}, per_coin=0.20, max_coin=0.50)
    w._pos = {"a": {"ZEC": 5.0}}
    r.on_book("ZEC", _book(100.0, sz=1.0), ts=1)       # target ~2 units vs 1 visible → >25% cap
    rep = r.tick(now=1)
    assert "ZEC" in rep.no_fills and ex.net_position("ZEC") == Decimal(0)
