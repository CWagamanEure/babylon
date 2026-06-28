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

from typing import Any, Protocol

from babylon.data.wallet_fills import _Throttle
from babylon.logging import get_logger

log = get_logger("watcher")

_FLAT_EPS = 1e-12
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
            since = nxt + 1 if nxt <= since else nxt  # progress; tid-dedup covers overlap
        self._last_detect[wallet] = now_ms
        if not fresh:
            return 0
        self._apply(wallet, fresh)
        return len(fresh)

    def _apply(self, wallet: str, fills: list[dict[str, Any]]) -> None:
        # startPosition-anchored: the latest fill per coin gives the absolute net.
        latest: dict[str, dict[str, Any]] = {}
        for f in fills:
            c = str(f["coin"])
            if c not in latest or int(f["time"]) >= int(latest[c]["time"]):
                latest[c] = f
        book = self._pos[wallet]
        for c, f in latest.items():
            signed = float(f["sz"]) if str(f["side"]) == "B" else -float(f["sz"])
            net = float(f["startPosition"]) + signed
            if abs(net) < _FLAT_EPS:
                book.pop(c, None)
            else:
                book[c] = net
        all_times = [int(f["time"]) for f in fills]
        top = max(all_times)
        self._cursor[wallet] = top
        self._boundary_tids[wallet] = {int(f["tid"]) for f in fills if int(f["time"]) == top}

    async def truth_up(self, wallet: str) -> None:
        """Overwrite from the exchange's authoritative positions — force-flat any coin
        the wallet no longer holds (kills the missed-close phantom). Also the cold-start
        seed."""
        await self._throttle.wait()
        st = await self._src.clearinghouse_state(wallet)
        truth: dict[str, float] = {}
        for ap in st.get("assetPositions", []):
            p = ap.get("position", {})
            szi = float(p.get("szi", 0.0))
            if abs(szi) >= _FLAT_EPS:
                truth[str(p["coin"])] = szi
        self._pos[wallet] = truth

    async def truth_up_all(self) -> None:
        for w in self._wallets:
            await self.truth_up(w)

    async def cold_start(self, since_ms: int) -> None:
        """Seed positions from the exchange and stream fills forward only."""
        await self.truth_up_all()
        for w in self._wallets:
            self._cursor[w] = since_ms
            self._boundary_tids[w] = set()

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
