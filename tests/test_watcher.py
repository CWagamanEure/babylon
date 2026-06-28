import asyncio

from babylon.follow.watcher import WalletWatcher

W = "0xwallet"


def _fill(t, coin, side, sz, startpos, tid):
    return {"time": t, "coin": coin, "side": side, "sz": sz,
            "startPosition": startpos, "tid": tid}


class FakeSource:
    """Serves fills in [start, end] (inclusive start) and a clearinghouse snapshot."""

    def __init__(self, fills=None, chs=None):
        self.fills = fills or []
        self.chs = chs or {"assetPositions": []}

    async def user_fills_by_time(self, address, start_ms, end_ms):
        out = [f for f in self.fills if start_ms <= f["time"] <= end_ms]
        return sorted(out, key=lambda f: f["time"])[:2000]

    async def clearinghouse_state(self, address):
        return self.chs


def _run(coro):
    return asyncio.run(coro)


def test_start_position_anchoring():
    # latest fill's startPosition ± sz IS the net (absolute, not a running sum)
    src = FakeSource([
        _fill(1000, "BTC", "B", 5.0, 0.0, 1),    # open long 5
        _fill(2000, "BTC", "B", 3.0, 5.0, 2),    # add → net 8
        _fill(3000, "BTC", "A", 2.0, 8.0, 3),    # trim → net 6
    ])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    n = _run(w.poll_wallet(W, 9999))
    assert n == 3 and w.position(W, "BTC") == 6.0


def test_close_flattens():
    src = FakeSource([
        _fill(1000, "ETH", "B", 4.0, 0.0, 1),
        _fill(2000, "ETH", "A", 4.0, 4.0, 2),  # close → flat
    ])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 9999))
    assert w.position(W, "ETH") == 0.0 and "ETH" not in w.positions(W)


def test_cursor_dedup_no_double_count_across_polls():
    src = FakeSource([_fill(1000, "SOL", "B", 2.0, 0.0, 1)])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 5000))
    assert w.position(W, "SOL") == 2.0
    # second poll: inclusive `since` re-serves tid=1, but it's deduped → no change
    n2 = _run(w.poll_wallet(W, 6000))
    assert n2 == 0 and w.position(W, "SOL") == 2.0


def test_same_ms_boundary_not_dropped():
    # two fills share a ms; the boundary-tid set must not drop the second next poll
    src = FakeSource([
        _fill(1000, "BTC", "B", 1.0, 0.0, 1),
        _fill(1000, "ETH", "B", 1.0, 0.0, 2),  # same ms, different tid
    ])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    n = _run(w.poll_wallet(W, 5000))
    assert n == 2 and w.position(W, "BTC") == 1.0 and w.position(W, "ETH") == 1.0


def test_burst_pagination_over_2000():
    fills = [_fill(1000 + i, "DOGE", "B", 1.0, float(i), i + 1) for i in range(2500)]
    # net after all = startPosition of last (2499) + 1 = 2500
    src = FakeSource(fills)
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    n = _run(w.poll_wallet(W, 10_000_000))
    assert n == 2500 and w.position(W, "DOGE") == 2500.0


def test_truth_up_kills_phantom():
    # watcher thinks BTC long (a missed close); exchange says flat → force-flat
    src = FakeSource(chs={"assetPositions": [
        {"position": {"coin": "ETH", "szi": "3.0"}},
    ]})
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    w._pos[W] = {"BTC": 5.0, "ETH": 3.0}  # BTC is the phantom
    _run(w.truth_up(W))
    assert w.position(W, "BTC") == 0.0 and w.position(W, "ETH") == 3.0


def test_self_heal_after_missed_fill():
    # the watcher never saw the open (missed), but the next fill re-anchors via startPosition
    src = FakeSource([_fill(3000, "SOL", "A", 2.0, 10.0, 7)])  # startPos 10 we never recorded
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 9999))
    assert w.position(W, "SOL") == 8.0  # 10 + (-2) — absolute, self-corrected


def test_consensus_sign_edge_weighted():
    src = FakeSource()
    w = WalletWatcher(src, ["a", "b", "c"], min_interval_s=0.0)
    w._pos = {"a": {"BTC": 5.0}, "b": {"BTC": -1.0}, "c": {"BTC": 2.0}}
    weights = {"a": 0.5, "b": 0.3, "c": 0.2}
    assert abs(w.consensus_sign("BTC", weights) - (0.5 - 0.3 + 0.2)) < 1e-12


def test_boundary_union_no_stale_regression():
    # A: a same-ms fill surfacing after a poll cut must not drop the prior boundary
    # tids (else the next poll re-applies the stale opens and the net regresses).
    src = FakeSource([_fill(1000, "BTC", "B", 1.0, 0.0, 1), _fill(1000, "ETH", "B", 1.0, 0.0, 2)])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 5000))
    src.fills.append(_fill(1000, "BTC", "B", 4.0, 1.0, 3))  # new same-ms BTC scale → net 5
    assert _run(w.poll_wallet(W, 6000)) == 1 and w.position(W, "BTC") == 5.0
    # third poll re-serves all three @1000; all deduped → no regression to 1.0
    assert _run(w.poll_wallet(W, 7000)) == 0 and w.position(W, "BTC") == 5.0


def test_same_ms_tiebreak_by_tid():
    # B: same-ms fills returned out of execution order → the higher-tid (later) anchor wins
    src = FakeSource([
        _fill(1000, "BTC", "B", 10.0, 110.0, 2),  # executed 2nd (tid 2): net 120
        _fill(1000, "BTC", "B", 10.0, 100.0, 1),  # executed 1st (tid 1), returned LAST
    ])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 5000))
    assert w.position(W, "BTC") == 120.0  # not 110 (list-order would pick the last)


def test_relative_flat_tolerance_no_signflip():
    # C: float dust on a huge position is flat, not a sign-flipped full-strength vote
    src = FakeSource([_fill(1000, "PEPE", "A", 999_999_999.5, 1_000_000_000.0, 1)])  # net 0.5
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 5000))
    assert w.position(W, "PEPE") == 0.0 and w.consensus_sign("PEPE", {W: 1.0}) == 0.0


def test_truth_up_staleness_gate():
    # #2: a snapshot OLDER than our last applied fill must not clobber it into a phantom
    src = FakeSource([_fill(1000, "BTC", "B", 10.0, 0.0, 1)])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 5000))  # BTC=10, cursor=1000
    src.chs = {"time": 500, "assetPositions": []}  # stale snapshot (before the fill)
    _run(w.truth_up(W))
    assert w.position(W, "BTC") == 10.0  # not clobbered
    src.chs = {"time": 2000, "assetPositions": []}  # fresh snapshot says flat
    _run(w.truth_up(W))
    assert w.position(W, "BTC") == 0.0  # now legitimately flattened


def test_state_roundtrip():
    src = FakeSource([_fill(1000, "BTC", "B", 5.0, 0.0, 1)])
    w = WalletWatcher(src, [W], min_interval_s=0.0)
    _run(w.poll_wallet(W, 5000))
    st = w.to_state()
    w2 = WalletWatcher(FakeSource(), [W], min_interval_s=0.0)
    w2.from_state(st)
    assert w2.position(W, "BTC") == 5.0 and w2._cursor[W] == 1000
