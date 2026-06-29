"""Incremental per-coin position state machine — the ONE shared round-trip reconstructor.

The audit's #1 correctness rule: live capture and batch backtests must reconstruct
round-trips with the SAME state machine, or their scores silently diverge. `skill.reconstruct`
is batch + closed-only (emits nothing on open). This `CoinStepper` is the incremental form:
`step(fill) -> [Open|Close]` events, firing an Open the instant a position goes flat→nonzero
(so the capture layer can schedule the entry markout) and a Close on return-to-flat. It
mirrors `reconstruct` line-for-line (entry-averaging en/es, flip leftover, exact-zero reset,
the `valid` flag for positions opened before observation) — and `reconstruct_via_stepper`
proves they agree, so the batch path can delegate here instead of forking the logic.

Markout note: Open/Close carry the wallet's own avg prices for diagnostics only — the
FOLLOWER markout is taken from the book at entry_t+lag / exit_t+lag, never these.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from babylon.follow.skill import _REL_TOL, ZERO_HASH, Position


@dataclass(frozen=True, slots=True)
class Open:
    coin: str
    direction: int          # +1 long / -1 short
    entry_t: int            # ms — schedule the entry markout at entry_t + lag
    taker_open: bool
    conviction: bool        # opening fill has a real hash (not TWAP/liquidation)


@dataclass(frozen=True, slots=True)
class Close:
    coin: str
    direction: int
    entry_t: int            # links to the Open's markout
    exit_t: int             # schedule the exit markout at exit_t + lag
    entry_px: float         # wallet's size-weighted avg (diagnostics only)
    exit_px: float
    taker_open: bool
    conviction: bool
    valid: bool             # False ⇒ opened before we observed it → unmarkable, drop


class CoinStepper:
    """One coin's signed-position machine for one wallet. Feed fills in (time, tid) order."""

    def __init__(self, coin: str, startpos: float = 0.0) -> None:
        self.coin = coin
        self.pos = float(startpos)
        # a position seeded mid-window (nonzero startpos) has an unobserved open → not valid
        self._maxabs = abs(self.pos)
        self.valid = abs(self.pos) < self._tol()
        self.en = self.es = self.xn = self.xs = 0.0   # open position's entry/exit notional+size
        self.et = 0
        self.topen = self.conv = False

    def _tol(self) -> float:
        return max(_REL_TOL * self._maxabs, 1e-15)

    def step(self, time: int, px: float, sz: float, side: str, crossed: bool,
             hsh: str | None = None) -> list[Open | Close]:
        ev: list[Open | Close] = []
        d = float(sz) if side == "B" else -float(sz)
        conv_i = hsh is None or str(hsh) != ZERO_HASH
        self._maxabs = max(self._maxabs, abs(self.pos + d))
        tol = self._tol()
        if self.pos == 0.0 or (d > 0) == (self.pos > 0):          # opening (flat or same-side add)
            if self.pos == 0.0:
                self.et, self.topen, self.conv = int(time), bool(crossed), conv_i
                self.en = self.es = 0.0
                self.valid = True
                ev.append(Open(self.coin, 1 if d > 0 else -1, self.et, self.topen, self.conv))
            self.en += abs(d) * float(px)
            self.es += abs(d)
            self.pos += d
        else:                                                      # opposite sign → closing / flip
            held = 1 if self.pos > 0 else -1
            close = min(abs(d), abs(self.pos))
            self.xn += close * float(px)
            self.xs += close
            self.pos += close if self.pos < 0 else -close
            if abs(self.pos) < tol:                                # position closed
                if self.es > 0 and self.xs > 0:
                    ev.append(Close(self.coin, held, self.et, int(time),
                                    self.en / self.es, self.xn / self.xs,
                                    self.topen, self.conv, self.valid))
                self.en = self.es = self.xn = self.xs = 0.0
                self.pos = 0.0                                     # exact flat (no float residual)
                leftover = abs(d) - close
                if leftover > tol:                                # flip → open the opposite side
                    self.et, self.topen, self.conv = int(time), bool(crossed), conv_i
                    self.valid = True
                    ev.append(Open(self.coin, 1 if d > 0 else -1, self.et, self.topen, self.conv))
                    self.en, self.es = leftover * float(px), leftover
                    self.pos = leftover if d > 0 else -leftover
        return ev


def reconstruct_via_stepper(
    times: np.ndarray, px: np.ndarray, sz: np.ndarray, side: np.ndarray,
    crossed: np.ndarray, startpos: np.ndarray | None = None,
    hashes: np.ndarray | None = None,
) -> list[Position]:
    """Run the incremental stepper over a fill array and return the SAME closed `Position`
    list `skill.reconstruct` produces — the equivalence proof (and the path by which the
    batch reconstructor can delegate to the one shared state machine)."""
    sp = float(startpos[0]) if startpos is not None and startpos.size else 0.0
    st = CoinStepper("X", startpos=sp)
    out: list[Position] = []
    for i in range(times.size):
        for e in st.step(int(times[i]), float(px[i]), float(sz[i]), str(side[i]),
                         bool(crossed[i]), str(hashes[i]) if hashes is not None else None):
            if isinstance(e, Close) and e.valid:
                out.append(Position(e.direction, e.entry_px, e.exit_px, e.entry_t,
                                    e.exit_t, e.taker_open, e.conviction))
    return out
