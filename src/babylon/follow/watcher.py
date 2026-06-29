"""WalletWatcher — live per-wallet net position from polled fills + a truth-up.

Per the live-follow audit (docs/LIVE_FOLLOW.md §9b):
- POLL ``userFillsByTime`` (WS user-fills is hard-capped at 10 users/IP — infeasible
  at our scale). Weight-budgeted throttle; in-poll pagination on the 2000-fill cap.
- Live position is **startPosition-anchored**: each fill carries the wallet's
  position in that coin BEFORE it, so ``startPosition ± sz`` is an ABSOLUTE,
  self-correcting read of the current net — a missed/duplicated fill can't permanently
  corrupt it (the next fill in that coin re-anchors). NOT a running sum, NOT
  ``reconstruct`` (which only emits closed round-trips).
- The one residual hole — a missed FINAL close in a coin never traded again — is a
  phantom that fill-streaming can't heal, so a periodic ``clearinghouseState``
  truth-up (the exchange's authoritative positions) force-flats it.

Cursor = inclusive ``since`` + a persisted tid set at the boundary ms (advancing by
time alone would drop fills that share a millisecond). State is serializable so the
engine can checkpoint the watcher at its snapshot cut and restore both consistently.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from babylon.data.wallet_fills import _Throttle
from babylon.logging import get_logger

log = get_logger("watcher")

_FLAT_EPS = 1e-12
_REL_TOL = 1e-9  # flat when |net| < _REL_TOL·|startPosition| (meme-coin / float-ULP safe)
_PAGE = 2000


class FillSource(Protocol):
    async def user_fills_by_time(
        self, address: str, start_ms: int, end_ms: int
    ) -> list[dict[str, Any]]: ...

    async def clearinghouse_state(self, address: str) -> dict[str, Any]: ...


class WalletWatcher:
    def __init__(
        self, source: FillSource, wallets: list[str], *, min_interval_s: float = 1.05
    ) -> None:
        self._src = source
        self._wallets = list(wallets)
        self._throttle = _Throttle(min_interval_s)
        # Current signed net position per (wallet, coin); absent = flat.
        self._pos: dict[str, dict[str, float]] = {w: {} for w in wallets}
        self._cursor: dict[str, int] = {w: 0 for w in wallets}
        self._boundary_tids: dict[str, set[int]] = {w: set() for w in wallets}
        self._last_detect: dict[str, int] = {}  # poll-return time per wallet (latency)
        # Per-wallet lock so a poll and a truth-up can't interleave at their awaits
        # and corrupt _pos (the "same loop ⇒ atomic" assumption is false across awaits).
        self._lock: dict[str, asyncio.Lock] = {w: asyncio.Lock() for w in wallets}

    # --- reads -------------------------------------------------------------

    def position(self, wallet: str, coin: str) -> float:
        return self._pos.get(wallet, {}).get(coin, 0.0)

    def positions(self, wallet: str) -> dict[str, float]:
        return dict(self._pos.get(wallet, {}))

    def consensus_sign(self, coin: str, weights: dict[str, float]) -> float:
        """Edge-weighted Σ of followed wallets' position signs in a coin (the
        aggregate copy signal). ``weights`` maps wallet → edge weight (Σ = 1)."""
        s = 0.0
        for w, wt in weights.items():
            p = self._pos.get(w, {}).get(coin, 0.0)
            s += wt * (1.0 if p > 0 else -1.0 if p < 0 else 0.0)
        return s

    def active_coins(self, weights: dict[str, float]) -> set[str]:
        return {c for w in weights for c in self._pos.get(w, {})}

    # --- updates -----------------------------------------------------------

    async def poll_wallet(self, wallet: str, now_ms: int) -> int:
        """Fetch fills since the cursor (paginating a burst), update positions from
        the latest fill per coin. Returns the count of fresh fills applied."""
        async with self._lock[wallet]:  # serialize vs truth_up (no interleave at awaits)
            cursor = self._cursor[wallet]
            boundary = self._boundary_tids[wallet]
            since = cursor
            fresh: list[dict[str, Any]] = []
            seen: set[int] = set()
            while True:
                await self._throttle.wait()
                batch = await self._src.user_fills_by_time(wallet, since, now_ms)
                new = [f for f in batch
                       if int(f["tid"]) not in seen
                       and not (int(f["time"]) == cursor and int(f["tid"]) in boundary)]
                if not new:
                    break
                for f in new:
                    seen.add(int(f["tid"]))
                fresh.extend(new)
                if len(batch) < _PAGE:
                    break
                nxt = max(int(f["time"]) for f in batch)
                if min(int(f["time"]) for f in batch) == nxt:
                    since = nxt + 1  # a FULL page at one ms can't paginate within it →
                    # force progress (a >2000-same-ms event is unrepresentable; truth-up reconciles)
                else:
                    since = nxt if nxt > since else nxt + 1  # overlap to catch a straddling group
            self._last_detect[wallet] = now_ms
            if not fresh:
                return 0
            self._apply(wallet, fresh)
            return len(fresh)

    def _apply(self, wallet: str, fills: list[dict[str, Any]]) -> None:
        # startPosition-anchored: the (time, tid)-latest fill per coin is the absolute
        # net — tie-break on tid because same-ms fill order is undefined by the API.
        latest: dict[str, dict[str, Any]] = {}
        for f in fills:
            c = str(f["coin"])
            key = (int(f["time"]), int(f["tid"]))
            if c not in latest or key >= (int(latest[c]["time"]), int(latest[c]["tid"])):
                latest[c] = f
        book = self._pos[wallet]
        for c, f in latest.items():
            sp = float(f["startPosition"])
            signed = float(f["sz"]) if str(f["side"]) == "B" else -float(f["sz"])
            net = sp + signed
            tol = max(_FLAT_EPS, _REL_TOL * abs(sp))  # relative — float residue ≠ a position
            if abs(net) < tol:
                book.pop(c, None)
            else:
                book[c] = net
        top = max(int(f["time"]) for f in fills)
        top_tids = {int(f["tid"]) for f in fills if int(f["time"]) == top}
        # Union the prior boundary when the top ms is unchanged — else previously-seen
        # tids at that ms drop out and get re-applied (a stale regression) next poll.
        self._boundary_tids[wallet] = (
            self._boundary_tids[wallet] | top_tids if top == self._cursor[wallet] else top_tids)
        self._cursor[wallet] = top

    async def truth_up(self, wallet: str) -> None:
        """Overwrite from the exchange's authoritative positions — force-flat any coin
        the wallet no longer holds (kills the missed-close phantom). Also the cold-start
        seed. Skips the overwrite if the snapshot is OLDER than our last applied fill
        (a stale snapshot would clobber a fresh fill into a sticky phantom flat)."""
        async with self._lock[wallet]:
            await self._throttle.wait()
            st = await self._src.clearinghouse_state(wallet)
            snap_time = int(st.get("time", 0))
            truth: dict[str, float] = {}
            for ap in st.get("assetPositions", []):
                p = ap.get("position", {})
                coin = p.get("coin")
                if coin is None:
                    continue
                szi = float(p.get("szi", 0.0))
                if abs(szi) >= _FLAT_EPS:
                    truth[str(coin)] = szi
            if snap_time == 0 or snap_time >= self._cursor.get(wallet, 0):
                self._pos[wallet] = truth  # snapshot is at least as new as our fills

    async def truth_up_all(self) -> None:
        for w in self._wallets:
            await self.truth_up(w)

    async def cold_start(self, since_ms: int) -> None:
        """Seed positions from the exchange and stream fills forward only."""
        await self.truth_up_all()
        for w in self._wallets:
            self._cursor[w] = since_ms
            self._boundary_tids[w] = set()

    def update_roster(self, wallets: list[str], *, since_ms: int = 0) -> None:
        """Adopt a re-ranked roster mid-run (§v4.4 roll seam). NEW wallets start flat
        (cursor=since_ms) until a poll/truth-up loads their real position — so the
        consensus under-counts a new name briefly rather than trading it blind; CONTINUING
        wallets keep their tracked state; DROPPED wallets are purged."""
        keep = set(wallets)
        for w in wallets:
            if w not in self._pos:
                self._pos[w] = {}
                self._cursor[w] = since_ms
                self._boundary_tids[w] = set()
                self._lock[w] = asyncio.Lock()
        for w in [w for w in self._pos if w not in keep]:
            for d in (self._pos, self._cursor, self._boundary_tids, self._lock,
                      self._last_detect):
                d.pop(w, None)
        self._wallets = list(wallets)

    # --- durability --------------------------------------------------------

    def to_state(self) -> dict[str, Any]:
        return {
            "pos": {w: dict(b) for w, b in self._pos.items()},
            "cursor": dict(self._cursor),
            "boundary": {w: sorted(t) for w, t in self._boundary_tids.items()},
        }

    def from_state(self, st: dict[str, Any]) -> None:
        self._pos = {w: dict(b) for w, b in st["pos"].items()}
        self._cursor = dict(st["cursor"])
        self._boundary_tids = {w: set(t) for w, t in st["boundary"].items()}
