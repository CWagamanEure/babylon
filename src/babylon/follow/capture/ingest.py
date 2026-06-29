"""FillIngest — the guarantee the stepper relies on: ordered, de-duped fills.

The CoinStepper assumes fills arrive in (time, tid) order and has zero protection (an
out-of-order close produces a negative-hold phantom round-trip; a duplicate tid double-
applies). WS `userFills` violates both — it replays recent fills on every (re)subscribe and
can interleave on reconnect. So ingest, per (wallet, coin):
- DE-DUPs by tid with a BOUNDED LRU (the design's unbounded set would OOM in <1 day),
- REORDERs through a bounded-lateness buffer (release a fill only once it's settled —
  older than watermark − lateness — so a slightly-late fill still lands in order),
- DROPs a fill that arrives older than the last released time (too late to order; counted),
then drives one CoinStepper per (wallet, coin) and routes Open/Close to the MarkoutScheduler.
"""

from __future__ import annotations

import heapq
from collections import OrderedDict
from dataclasses import dataclass

from babylon.follow.capture.markout import MarkoutScheduler
from babylon.follow.capture.stepper import Close, CoinStepper, Open
from babylon.logging import get_logger

log = get_logger("follow.capture.ingest")


@dataclass(frozen=True, slots=True)
class Fill:
    coin: str
    time: int
    px: float
    sz: float
    side: str               # "B" / "A"
    crossed: bool
    tid: int
    hsh: str | None = None


class FillIngest:
    def __init__(self, scheduler: MarkoutScheduler, *, lateness_ms: int = 2_000,
                 dedup_window: int = 200_000) -> None:
        self._sched = scheduler
        self._lateness = lateness_ms
        self._dedup_window = dedup_window
        self._seen: OrderedDict[int, None] = OrderedDict()        # bounded LRU of tids
        self._steppers: dict[tuple[str, str], CoinStepper] = {}
        self._buf: dict[tuple[str, str], list[tuple[int, int, Fill]]] = {}   # min-heap (time,tid,fill)
        self._watermark: dict[tuple[str, str], int] = {}
        self._last_released: dict[tuple[str, str], int] = {}
        self.dropped_late = 0
        self.dropped_dup = 0

    def on_fill(self, wallet: str, f: Fill) -> None:
        if f.tid in self._seen:                                   # dedup (replay on resubscribe)
            self._seen.move_to_end(f.tid)
            self.dropped_dup += 1
            return
        self._seen[f.tid] = None
        if len(self._seen) > self._dedup_window:
            self._seen.popitem(last=False)
        key = (wallet, f.coin)
        if f.time < self._last_released.get(key, -1):             # already past this point → too late
            self.dropped_late += 1
            log.warning("ingest.late_fill_dropped", wallet=wallet, coin=f.coin, tid=f.tid)
            return
        heapq.heappush(self._buf.setdefault(key, []), (f.time, f.tid, f))
        self._watermark[key] = max(self._watermark.get(key, 0), f.time)
        self._release(wallet, key, self._watermark[key] - self._lateness)

    def _release(self, wallet: str, key: tuple[str, str], up_to: int) -> None:
        buf = self._buf.get(key)
        if not buf:
            return
        st = self._steppers.setdefault(key, CoinStepper(key[1]))
        while buf and buf[0][0] <= up_to:                         # settled → safe to emit in order
            _t, _tid, f = heapq.heappop(buf)
            self._last_released[key] = f.time
            for ev in st.step(f.time, f.px, f.sz, f.side, f.crossed, f.hsh):
                if isinstance(ev, Open):
                    self._sched.on_open(wallet, ev)
                elif isinstance(ev, Close):
                    self._sched.on_close(wallet, ev)
                # Add events are emitted but unused for now (whole-position markout model)

    def flush(self) -> None:
        """Release every buffered fill (e.g. before a scoring cutoff) — no more lateness wait."""
        for wallet_coin in list(self._buf):
            wallet, _coin = wallet_coin
            self._release(wallet, wallet_coin, 1 << 62)
