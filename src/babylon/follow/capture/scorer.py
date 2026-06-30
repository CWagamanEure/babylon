"""CaptureScorer — the live-captured ReturnsFn/CutoffFn for the RollScheduler.

A drop-in for SelectionAdapter that ranks wallets on live shadow-markouts instead of the
candle proxy. CRUCIALLY it carries the audit's #2 disposition fix: the per-wallet return
series is the closed round-trips in the train window PLUS a mark-to-market of every still-OPEN
position at the cutoff (aggressing exit), so the open losers a disposition-prone wallet is
sitting on enter the score — without this, closed-only inflates the score by up to +122bp in
the warm-up (9× the true edge). RollScheduler then ranks by Sortino (same as the candle path).

SHADOW: built + tested, NOT yet wired into the live roll. The candle path stays the backbone
until this is validated against realized fills.
"""

from __future__ import annotations

import numpy as np

from babylon.follow.capture.markout import BookCache, MarkoutScheduler
from babylon.follow.capture.store import RoundtripStore

_DAY_MS = 86_400_000


class CaptureScorer:
    def __init__(self, store: RoundtripStore, scheduler: MarkoutScheduler, book: BookCache, *,
                 train_days: int, staleness_ms: int = 30_000) -> None:
        self._store = store
        self._sched = scheduler
        self._book = book
        self._train_ms = train_days * _DAY_MS
        self._staleness = staleness_ms

    def returns_fn(self, wallet: str, t0_ms: int) -> np.ndarray:
        """Closed round-trips in [t0−train, t0) + MTM of open positions at t0 (disposition fix)."""
        lo = t0_ms - self._train_ms
        closed = self._store.returns(wallet, lo, t0_ms)
        mtm: list[float] = []
        for coin, d, entry_mk in self._sched.open_marked(wallet):   # ALL open positions (incl. long-held)
            snap = self._book.snap(coin, t0_ms, self._staleness)
            if snap is None or entry_mk <= 0:
                continue
            exit_mk = snap.bid if d > 0 else snap.ask     # aggressing exit, same footing as closed
            mtm.append(d * (exit_mk / entry_mk - 1.0) * 1e4)
        if not mtm:
            return closed
        return np.concatenate([closed, np.asarray(mtm, dtype=np.float64)])

    def cutoff_fn(self, wallet: str, t0_ms: int) -> int:
        """Seam = round-trips CLOSED before t0 (the store windows on exit_t < t0)."""
        return t0_ms

    def active_candidates(self, t0_ms: int, min_positions: int) -> list[str]:
        """Discovery: wallets with ≥ min_positions round-trips in the train window."""
        return self._store.active_wallets(t0_ms - self._train_ms, t0_ms, min_positions)
