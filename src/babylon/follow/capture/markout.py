"""BookCache + MarkoutScheduler — shadow-mark each round-trip at the live book at +lag.

The follower markout: a round-trip opened at entry_t and closed at exit_t is marked at the
book `lag` ms after each, at the AGGRESSING touch (a long follower buys the ask on entry,
sells the bid on exit — and vice-versa for a short), so the spread cost a real follower pays
is baked into ret_bps (audit fidelity #1/#5a — mid-to-mid overstated by the round-trip
spread). Markouts are keyed on (wallet, coin, rid) — never entry_t (same-ms flips collide).

A markout is the price at a specific instant: if the book for that coin is stale/crossed/
missing at the due moment, the round-trip is DROPPED (never fabricated) — with the
liquidity-bias caveat the audit flagged. On restart, in-flight markouts whose due-time
passed during downtime are dropped (no `late_markout` at a stale price, no mid-log).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from babylon.follow.capture.stepper import Close, Open


@dataclass(frozen=True, slots=True)
class BookSnap:
    bid: float
    ask: float
    ts: int                 # exchange wall-clock ms of this book

    @property
    def valid(self) -> bool:
        return self.ask > self.bid > 0


class BookCache:
    """Latest L2 top-of-book per coin (fed by the l2Book WS feed). `snap` enforces the
    freshness + validity contract so a stale/crossed book never produces a markout."""

    def __init__(self) -> None:
        self._books: dict[str, BookSnap] = {}

    def update(self, coin: str, bid: float, ask: float, ts: int) -> None:
        self._books[coin] = BookSnap(bid, ask, ts)

    def snap(self, coin: str, now: int, staleness_ms: int) -> BookSnap | None:
        b = self._books.get(coin)
        if b is None or not b.valid or now - b.ts > staleness_ms:
            return None
        return b


@dataclass(slots=True)
class _RTState:
    direction: int
    entry_t: int
    exit_t: int | None = None
    entry_mk: float | None = None
    exit_mk: float | None = None
    taker: bool = False
    conv: bool = False


@dataclass(frozen=True, slots=True)
class FinalRoundtrip:
    wallet: str
    coin: str
    rid: int
    direction: int
    entry_t: int
    exit_t: int
    entry_mk: float         # aggressing-touch markouts (cost folded in)
    exit_mk: float
    ret_bps: float          # direction · (exit_mk/entry_mk − 1) · 1e4
    taker_open: bool
    conviction: bool
    source: str = "live"


class MarkoutScheduler:
    def __init__(self, *, lag_ms: int, staleness_ms: int = 30_000) -> None:
        self._lag = lag_ms
        self._staleness = staleness_ms
        self._heap: list[tuple[int, int, str, str, int, str]] = []   # (due, seq, wallet, coin, rid, kind)
        self._rt: dict[tuple[str, str, int], _RTState] = {}          # (wallet,coin,rid) -> state
        self._seq = 0

    def _push(self, due: int, wallet: str, coin: str, rid: int, kind: str) -> None:
        heapq.heappush(self._heap, (due, self._seq, wallet, coin, rid, kind))
        self._seq += 1

    def on_open(self, wallet: str, ev: Open) -> None:
        key = (wallet, ev.coin, ev.rid)
        self._rt[key] = _RTState(direction=ev.direction, entry_t=ev.entry_t,
                                 taker=ev.taker_open, conv=ev.conviction)
        self._push(ev.entry_t + self._lag, wallet, ev.coin, ev.rid, "entry")

    def on_close(self, wallet: str, ev: Close) -> None:
        if not ev.valid:                       # pre-observed open (rid −1) → never scorable
            return
        rt = self._rt.get((wallet, ev.coin, ev.rid))
        if rt is None:                         # entry markout already dropped (stale book) → skip
            return
        rt.exit_t = ev.exit_t
        self._push(ev.exit_t + self._lag, wallet, ev.coin, ev.rid, "exit")

    def process_due(self, now: int, book: BookCache) -> list[FinalRoundtrip]:
        """Take all markouts due by `now` against the current book; finalize round-trips whose
        both legs are marked. Call frequently so `now ≈ due` (book read ≈ the due instant)."""
        out: list[FinalRoundtrip] = []
        while self._heap and self._heap[0][0] <= now:
            _due, _seq, wallet, coin, rid, kind = heapq.heappop(self._heap)
            key = (wallet, coin, rid)
            rt = self._rt.get(key)
            if rt is None:
                continue
            snap = book.snap(coin, now, self._staleness)
            if snap is None:                   # stale/crossed/missing book → drop the round-trip
                self._rt.pop(key, None)
                continue
            d = rt.direction
            if kind == "entry":
                rt.entry_mk = snap.ask if d > 0 else snap.bid       # follower aggresses to open
            else:
                rt.exit_mk = snap.bid if d > 0 else snap.ask        # ...and to close
            if rt.entry_mk is not None and rt.exit_mk is not None and rt.exit_t is not None:
                ret = d * (rt.exit_mk / rt.entry_mk - 1.0) * 1e4
                out.append(FinalRoundtrip(
                    wallet, coin, rid, d, rt.entry_t, rt.exit_t,
                    rt.entry_mk, rt.exit_mk, ret, rt.taker, rt.conv))
                self._rt.pop(key, None)
        return out

    def drop_due_before(self, cutoff: int) -> int:
        """Restart hygiene: drop any pending markout whose due-time already passed (we have no
        book at that past instant — never mark at a stale price). Returns the count dropped."""
        kept: list[tuple[int, int, str, str, int, str]] = []
        dropped = 0
        for item in self._heap:
            if item[0] < cutoff:
                self._rt.pop((item[2], item[3], item[4]), None)
                dropped += 1
            else:
                kept.append(item)
        heapq.heapify(kept)
        self._heap = kept
        return dropped

    @property
    def pending(self) -> int:
        return len(self._heap)
