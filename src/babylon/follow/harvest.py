"""HarvestLedger — the event-driven 6h-drift tranche state machine (docs/HARVEST_EXECUTOR.md).

Each conviction taker-open by a selected wallet spawns a TRANCHE: enter at
`open_t + entry_lag`, hold `horizon` (6h), exit (reduce-only) on its own clock — BLIND to the
wallet's exit. This harvests the validated fixed-horizon markout edge (a wallet's entry predicts
~+30bp net drift over 6h), NOT the wallet's round-trip (measured NULL). Tranches are independent
and overlap; each is harvested EXACTLY ONCE (keyed by open-event id).

The ledger is PURE and time-driven by the caller (`now_ms`): no network, no clock, no executor —
so it is fully unit-testable. It owns the lifecycle + the gross/per-coin caps; the caller owns
order submission and feeds fills back. Sizing policy is the CALLER's job (an open design decision,
see the doc): the caller passes a per-tranche notional, the ledger only enforces caps + lifecycle.

bps/price math is float (consistent with the validated returns pipeline in followable/skill);
notional is float intended USD. The executor converts to Decimal contracts at the order boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from babylon.logging import get_logger

log = get_logger("follow.harvest")


class TrancheState(Enum):
    PENDING_ENTRY = "pending_entry"   # registered, not yet entered (waiting out the entry lag)
    OPEN = "open"                     # entry filled, holding the 6h clock
    CLOSED = "closed"                 # exit filled, realized round-trip emitted
    CANCELLED = "cancelled"           # entry never filled (no liquidity) — dropped, no exposure


@dataclass
class Tranche:
    id: str
    wallet: str
    coin: str
    direction: int                    # +1 long / -1 short
    notional: float                   # intended USD exposure (may be scaled down by caps at entry)
    entry_target_ms: int              # open_event_t + entry_lag; executed at max(now, this)
    state: TrancheState = TrancheState.PENDING_ENTRY
    entry_fill_px: float | None = None
    entry_fill_ms: int | None = None
    expiry_ms: int | None = None      # entry_fill_ms + horizon (set on entry fill)
    exit_fill_px: float | None = None
    exit_fill_ms: int | None = None
    raw_bps: float | None = None      # directional, pre-neutralization (basket subtracted later)

    @property
    def signed_notional(self) -> float:
        return self.direction * self.notional


@dataclass
class RealizedRoundTrip:
    """One disposition-free harvest = one TOP-arm observation for the gate. `raw_bps` is the
    directional round-trip; neutralization against the basket is applied downstream (it needs
    candle data the ledger doesn't hold), exactly as followable/skill separate the two."""
    id: str
    wallet: str
    coin: str
    direction: int
    entry_px: float
    exit_px: float
    entry_ms: int
    exit_ms: int
    raw_bps: float
    entry_lag_ms: int                 # realized entry lag (entry_fill_ms − open_event_ms)


class HarvestLedger:
    def __init__(
        self, *, entry_lag_ms: int, horizon_ms: int,
        max_coin_notional: float | None = None, max_gross_notional: float | None = None,
        min_tranche_notional: float = 0.0, max_entry_lag_ms: int = 0,
    ) -> None:
        assert horizon_ms > 0 and entry_lag_ms >= 0 and max_entry_lag_ms >= 0
        self._entry_lag_ms = entry_lag_ms
        self._horizon_ms = horizon_ms
        self._max_coin = max_coin_notional
        self._max_gross = max_gross_notional
        self._min_tranche = min_tranche_notional
        # a PENDING tranche that can't enter within this long past its target (chronically stale
        # book) is CANCELLED, not held: entering hours late would harvest a contaminated window,
        # and holding it forever leaks memory + reserves cap room. 0 = disabled (no deadline).
        self._max_entry_lag_ms = max_entry_lag_ms
        self._tranches: dict[str, Tranche] = {}
        self._open_event_ms: dict[str, int] = {}     # id -> the originating open-event time
        self._realized: list[RealizedRoundTrip] = []
        # coverage counters (cumulative, survive resume) — the DENOMINATOR the gate never saw: how
        # many detected opens actually harvested vs were dropped by cap or entry-staleness.
        self._n_registered = 0                       # opens registered as tranches
        self._n_capped = 0                           # dropped: cap left < min_tranche room
        self._n_entry_expired = 0                    # dropped: never entered before the deadline

    # ── ingest ────────────────────────────────────────────────────────────────────────────
    def on_open_event(
        self, *, event_id: str, wallet: str, coin: str, direction: int, notional: float,
        open_event_ms: int,
    ) -> bool:
        """Register a tranche for a detected conviction open. Idempotent: a duplicate event_id
        (the same open re-seen across polls) is ignored. Returns True if newly registered."""
        if event_id in self._tranches:
            return False
        if direction not in (1, -1) or notional <= 0:
            return False
        self._tranches[event_id] = Tranche(
            id=event_id, wallet=wallet, coin=coin, direction=direction, notional=float(notional),
            entry_target_ms=open_event_ms + self._entry_lag_ms)
        self._open_event_ms[event_id] = open_event_ms
        self._n_registered += 1
        return True

    # ── entry side ────────────────────────────────────────────────────────────────────────
    def due_entries(self, now_ms: int) -> list[Tranche]:
        """PENDING tranches whose entry time has arrived, with notional SCALED to fit the
        per-coin and gross caps given current OPEN exposure (+ entries approved earlier this
        call). A tranche scaled below `min_tranche_notional` is CANCELLED (logged — never a
        silent truncation). Caller submits an entry order for each returned tranche."""
        due = sorted(
            (t for t in self._tranches.values()
             if t.state is TrancheState.PENDING_ENTRY and t.entry_target_ms <= now_ms),
            key=lambda t: (t.entry_target_ms, t.id))   # deterministic: oldest signal first
        gross = self.gross_open_notional()
        coin_exposed = {c: self.coin_open_notional(c) for c in {t.coin for t in due}}
        approved: list[Tranche] = []
        for t in due:
            # stale-entry deadline: if this open never entered within max_entry_lag of its target
            # (chronically stale book), cancel it — a late entry harvests a contaminated window.
            if self._max_entry_lag_ms and now_ms - t.entry_target_ms > self._max_entry_lag_ms:
                t.state = TrancheState.CANCELLED
                self._n_entry_expired += 1
                log.info("harvest.entry_expired", id=t.id, coin=t.coin,
                         late_ms=now_ms - t.entry_target_ms)
                continue
            room = t.notional
            if self._max_coin is not None:
                room = min(room, max(0.0, self._max_coin - coin_exposed.get(t.coin, 0.0)))
            if self._max_gross is not None:
                room = min(room, max(0.0, self._max_gross - gross))
            if room < self._min_tranche or room <= 0.0:
                t.state = TrancheState.CANCELLED
                self._n_capped += 1
                log.info("harvest.tranche_capped_out", id=t.id, coin=t.coin,
                         wanted=t.notional, room=room)
                continue
            if room < t.notional:
                log.info("harvest.tranche_scaled", id=t.id, coin=t.coin,
                         wanted=t.notional, took=room)
                t.notional = room
            coin_exposed[t.coin] = coin_exposed.get(t.coin, 0.0) + t.notional
            gross += t.notional
            approved.append(t)
        return approved

    def on_entry_fill(self, event_id: str, fill_px: float, fill_ms: int) -> None:
        t = self._tranches[event_id]
        if t.state is not TrancheState.PENDING_ENTRY:
            return
        t.entry_fill_px = float(fill_px)
        t.entry_fill_ms = int(fill_ms)
        t.expiry_ms = int(fill_ms) + self._horizon_ms
        t.state = TrancheState.OPEN

    def on_entry_failed(self, event_id: str) -> None:
        """Entry order never filled (no liquidity in the staleness window) — drop it, no risk."""
        t = self._tranches.get(event_id)
        if t is not None and t.state is TrancheState.PENDING_ENTRY:
            t.state = TrancheState.CANCELLED

    # ── exit side ─────────────────────────────────────────────────────────────────────────
    def due_exits(self, now_ms: int) -> list[Tranche]:
        """OPEN tranches whose 6h clock has fired. Keeps returning a tranche until its exit
        actually fills (so a failed reduce-only is retried next tick — we always flatten)."""
        return sorted(
            (t for t in self._tranches.values()
             if t.state is TrancheState.OPEN and t.expiry_ms is not None and t.expiry_ms <= now_ms),
            key=lambda t: (t.expiry_ms or 0, t.id))

    def on_exit_fill(self, event_id: str, fill_px: float, fill_ms: int) -> RealizedRoundTrip | None:
        t = self._tranches.get(event_id)
        # Idempotent guard (survives `python -O`, which strips asserts): a duplicate or late exit
        # fill on a tranche that isn't OPEN (already CLOSED/CANCELLED, or gone) is a no-op, NOT a
        # second harvest (which would fabricate an extra realized round-trip).
        if t is None or t.state is not TrancheState.OPEN or t.entry_fill_px is None:
            return None
        assert t.entry_fill_px > 0, "entry price must be positive to compute a return"
        t.exit_fill_px = float(fill_px)
        t.exit_fill_ms = int(fill_ms)
        t.raw_bps = t.direction * (t.exit_fill_px / t.entry_fill_px - 1.0) * 1e4
        t.state = TrancheState.CLOSED
        rt = RealizedRoundTrip(
            id=t.id, wallet=t.wallet, coin=t.coin, direction=t.direction,
            entry_px=t.entry_fill_px, exit_px=t.exit_fill_px,
            entry_ms=t.entry_fill_ms or 0, exit_ms=t.exit_fill_ms,
            raw_bps=t.raw_bps,
            entry_lag_ms=(t.entry_fill_ms or 0) - self._open_event_ms.get(event_id, 0))
        self._realized.append(rt)
        return rt

    # ── exposure / introspection ──────────────────────────────────────────────────────────
    def coin_open_notional(self, coin: str) -> float:
        return sum(t.notional for t in self._tranches.values()
                   if t.state is TrancheState.OPEN and t.coin == coin)

    def gross_open_notional(self) -> float:
        return sum(t.notional for t in self._tranches.values() if t.state is TrancheState.OPEN)

    def target_net(self, coin: str) -> float:
        """Signed Σ of OPEN tranches in a coin — the intended net position (risk view)."""
        return sum(t.signed_notional for t in self._tranches.values()
                   if t.state is TrancheState.OPEN and t.coin == coin)

    def open_tranches(self) -> list[Tranche]:
        return [t for t in self._tranches.values() if t.state is TrancheState.OPEN]

    def coverage(self) -> dict[str, int]:
        """The gate's missing DENOMINATOR: registered opens vs those dropped by cap/entry-staleness,
        and how many are still stuck PENDING (book never fresh) or OPEN past when they should exit.
        A high dropped/stuck fraction means the harvested sample is a biased subset of conviction
        opens — surfaced so silent coverage collapse can't read as 'measured everything'."""
        pending = sum(1 for t in self._tranches.values() if t.state is TrancheState.PENDING_ENTRY)
        return {"registered": self._n_registered, "capped": self._n_capped,
                "entry_expired": self._n_entry_expired, "pending": pending,
                "open": len(self.open_tranches())}

    @property
    def realized(self) -> list[RealizedRoundTrip]:
        return self._realized

    def drain_realized(self) -> list[RealizedRoundTrip]:
        """Pop the realized round-trips accumulated since the last drain (for journaling)."""
        out = self._realized
        self._realized = []
        return out

    # ── durability ────────────────────────────────────────────────────────────────────────
    def to_state(self) -> dict[str, Any]:
        """Serializable snapshot — OPEN tranches (live exposure) + un-drained realized must
        survive a restart so the 6h clocks and the gate feed aren't lost. Terminal tranches are
        dropped (already harvested/cancelled)."""
        live = [t for t in self._tranches.values()
                if t.state in (TrancheState.PENDING_ENTRY, TrancheState.OPEN)]
        return {
            "tranches": [{**asdict(t), "state": t.state.value} for t in live],
            "open_event_ms": {t.id: self._open_event_ms[t.id]
                              for t in live if t.id in self._open_event_ms},
            "realized": [asdict(r) for r in self._realized],
            "coverage": {"registered": self._n_registered, "capped": self._n_capped,
                         "entry_expired": self._n_entry_expired},
        }

    def from_state(self, st: dict[str, Any]) -> None:
        self._tranches = {}
        for d in st.get("tranches", []):
            d = dict(d)
            d["state"] = TrancheState(d["state"])
            t = Tranche(**d)
            self._tranches[t.id] = t
        self._open_event_ms = {k: int(v) for k, v in st.get("open_event_ms", {}).items()}
        self._realized = [RealizedRoundTrip(**r) for r in st.get("realized", [])]
        cov = st.get("coverage", {})
        self._n_registered = int(cov.get("registered", 0))
        self._n_capped = int(cov.get("capped", 0))
        self._n_entry_expired = int(cov.get("entry_expired", 0))

    def prune_closed(self, ids: Iterable[str] | None = None) -> int:
        """Drop CLOSED/CANCELLED tranches (bounded memory on a long run). Without `ids`, prunes
        all terminal tranches. Returns the count removed."""
        terminal = {TrancheState.CLOSED, TrancheState.CANCELLED}
        drop = [i for i, t in self._tranches.items() if t.state in terminal
                and (ids is None or i in set(ids))]
        for i in drop:
            del self._tranches[i]
            self._open_event_ms.pop(i, None)
        return len(drop)
