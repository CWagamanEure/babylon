"""HarvestRunner — drives the HarvestLedger against the PaperExecutor (docs/HARVEST_EXECUTOR.md).

The ledger (harvest.py) is the pure brain: open events in, due entries/exits out. This binds it to
the live book + executor:

- `ingest_opens(wallet, opens)`: the watcher's per-poll open events → ledger tranches (filtered to
  taker+conviction in the universe, sized by the wallet's tail-aware per-event notional).
- `on_book(coin, book, ts)`: live L2 books (exchange wall-clock ts) for fills + staleness.
- `step(now_wall)`: enter every due tranche, exit every expired one — each as a DEDICATED order so
  the realized round-trip is attributable (the gate's TOP arm). Exits are NORMAL orders sized to
  offset exactly that tranche's contracts (NOT reduce-only: tranches from different wallets can net
  to ~flat, where reduce-only would wrongly block the close). A depth-capped no-fill leaves the
  ledger consistent — a failed entry is dropped (no exposure), a failed exit is retried next step.

`run()` drives the concurrent poll-loop (detect opens) + tick-loop (enter/exit) under one stop,
mirroring FollowRunner's machinery, with durable checkpoints; `step` is the deterministic,
unit-tested core. Sizes/prices are Decimal at the order boundary; the ledger keeps float
bps/notional (the validated returns pipeline is float).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from babylon.core import Order, TimeInForce
from babylon.execution.fill_model import Book
from babylon.execution.paper import PaperExecutor
from babylon.follow.harvest import HarvestLedger, RealizedRoundTrip
from babylon.follow.watcher import WalletWatcher
from babylon.logging import get_logger

log = get_logger("follow.harvest_runner")


@dataclass(frozen=True, slots=True)
class HarvestTick:
    entries: int
    exits: int
    realized: tuple[RealizedRoundTrip, ...]
    no_fill: dict[str, str]                 # coin -> reason (capacity/staleness diagnostics)


class HarvestRunner:
    def __init__(
        self, ledger: HarvestLedger, notionals: dict[str, float], executor: PaperExecutor, *,
        universe: set[str], watcher: WalletWatcher | None = None,
        roster: list[str] | None = None, budget_usd: float = 1000.0,
        staleness_ms: int = 30_000, exit_staleness_ms: int = 300_000,
        truthup_chunk: int = 20, taker_only: bool = True, conviction_only: bool = True,
    ) -> None:
        self._ledger = ledger
        self._notional = dict(notionals)     # per-wallet per-event tail-aware notional (USD)
        self._ex = executor
        self._universe = set(universe)
        self._watcher = watcher              # polled for fills → opens via the watcher sink
        self._roster = list(roster or notionals)
        self._staleness_ms = staleness_ms
        self._exit_staleness_ms = exit_staleness_ms
        self._truthup_chunk = max(1, truthup_chunk)
        self._taker_only = taker_only
        self._conviction_only = conviction_only
        self._books: dict[str, tuple[Book, int]] = {}
        self._contracts: dict[str, Decimal] = {}   # tranche id -> filled entry contracts (for exit)
        self._cash = Decimal(str(budget_usd))      # paper cash; fills book their cashflow
        self._last_poll_mono: int | None = None
        self._tu_cursor = 0
        self._delivered: set[str] = set()          # realized tranche ids already sent on_realized

    @property
    def n_roster(self) -> int:
        return len(self._roster)

    def on_book(self, coin: str, book: Book, ts: int) -> None:
        self._books[coin] = (book, ts)

    def adopt_roster(self, notionals: dict[str, float], roster: list[str], *,
                     since_ms: int) -> None:
        """Roll seam: swap sizing + re-point the watcher. OPEN tranches from the prior roster KEEP
        their 6h clocks (we still harvest them); only NEW opens come from the new roster."""
        self._notional = dict(notionals)
        self._roster = list(roster)
        if self._watcher is not None:
            self._watcher.update_roster(roster, since_ms=since_ms)

    def equity(self) -> float:
        """Mark-to-market: paper cash + Σ net_position·mid over books we hold."""
        eq = float(self._cash)
        for coin, pos in self._ex.net_positions().items():
            bt = self._books.get(coin)
            if bt is not None and pos != 0:
                eq += float(pos) * float(self._mid(bt[0]))
        return eq

    def set_notionals(self, notionals: dict[str, float]) -> None:
        """Swap in fresh per-wallet sizing on a roll (new roster → new tail-aware notionals)."""
        self._notional = dict(notionals)

    def ingest_opens(self, wallet: str, opens: list) -> int:
        """Register tranches for a wallet's detected opens. Filtered to taker+conviction in the
        universe; sized by the wallet's tail-aware notional. Idempotent via the ledger's event id
        (the same open re-seen across overlapping polls is ignored). Returns # newly registered."""
        notional = self._notional.get(wallet, 0.0)
        if notional <= 0.0:
            return 0
        n = 0
        for coin, ev in opens:
            if coin not in self._universe:
                continue
            if (self._taker_only and not ev.taker_open) or \
               (self._conviction_only and not ev.conviction):
                continue
            eid = f"{wallet}:{coin}:{ev.entry_t}:{ev.tid}"
            if self._ledger.on_open_event(
                    event_id=eid, wallet=wallet, coin=coin, direction=ev.direction,
                    notional=notional, open_event_ms=ev.entry_t):
                n += 1
        return n

    def step(self, now_wall: int) -> HarvestTick:
        no_fill: dict[str, str] = {}
        entries = self._do_entries(now_wall, no_fill)
        realized = self._do_exits(now_wall, no_fill)
        # We deliver this step's realized via `rep.realized`; drain the ledger's buffer so its
        # internal `_realized` list can't grow unbounded over a long run.
        self._ledger.drain_realized()
        return HarvestTick(entries=entries, exits=len(realized),
                           realized=tuple(realized), no_fill=no_fill)

    # ── internals ─────────────────────────────────────────────────────────────────────────
    def _do_entries(self, now_wall: int, no_fill: dict[str, str]) -> int:
        entries = 0
        for t in self._ledger.due_entries(now_wall):
            bt = self._books.get(t.coin)
            if bt is None or now_wall - bt[1] > self._staleness_ms:
                no_fill[t.coin] = "stale_book_entry"     # stays PENDING → retried next step
                continue
            book = bt[0]
            contracts = self._to_contracts(t.direction, t.notional, self._mid(book))
            if contracts == 0:
                self._ledger.on_entry_failed(t.id)
                continue
            order = Order(coin=t.coin, size=contracts, price=None, reduce_only=False,
                          tif=TimeInForce.IOC, cloid=f"{t.id}:in")
            fill, rep = self._ex.submit_book(order, book, now_wall)
            if fill is not None:
                self._ledger.on_entry_fill(t.id, float(fill.price), now_wall)
                self._contracts[t.id] = fill.size
                self._cash -= fill.size * fill.price       # book cashflow (buy↓ / sell↑)
                entries += 1
            else:
                self._ledger.on_entry_failed(t.id)        # no liquidity/depth-capped → drop
                no_fill[t.coin] = rep.no_fill_reason or "no_entry_fill"
        return entries

    def _do_exits(self, now_wall: int, no_fill: dict[str, str]) -> list[RealizedRoundTrip]:
        realized: list[RealizedRoundTrip] = []
        for t in self._ledger.due_exits(now_wall):
            bt = self._books.get(t.coin)
            if bt is None or now_wall - bt[1] > self._exit_staleness_ms:
                no_fill[t.coin] = "stale_book_exit"        # stays OPEN → retried next step
                continue
            contracts = self._contracts.get(t.id)
            if contracts is None:                          # invariant: entry recorded it
                continue
            order = Order(coin=t.coin, size=-contracts, price=None, reduce_only=False,
                          tif=TimeInForce.IOC, cloid=f"{t.id}:out")
            fill, rep = self._ex.submit_book(order, bt[0], now_wall)
            if fill is not None:
                rt = self._ledger.on_exit_fill(t.id, float(fill.price), now_wall)
                if rt is not None:                          # None = no-op (already exited)
                    realized.append(rt)
                self._cash -= fill.size * fill.price       # sell → cash in
                self._contracts.pop(t.id, None)
            else:
                no_fill[t.coin] = rep.no_fill_reason or "no_exit_fill"
        return realized

    # ── async run-loop (mirrors FollowRunner: concurrent poll + tick) ─────────────────────
    async def poll(self, now_wall: int, now_mono: int, stop: asyncio.Event | None = None) -> int:
        """One watcher sweep over the roster; each poll emits opens via the watcher sink →
        `ingest_opens`. Heartbeat refreshes on ≥1 OK poll. Per-wallet isolation."""
        if self._watcher is None:
            return 0
        ok = 0
        for wallet in self._roster:
            if stop is not None and stop.is_set():
                break
            try:
                await self._watcher.poll_wallet(wallet, now_wall)
                ok += 1
                self._last_poll_mono = now_mono
            except Exception as exc:  # noqa: BLE001 — per-wallet isolation
                log.warning("harvest.poll_failed", wallet=wallet, error=str(exc))
        if not ok:
            log.error("harvest.poll_total_failure", n=len(self._roster))
        return ok

    async def _truthup_step(self, now_mono: int) -> None:
        if self._watcher is None or not self._roster:
            return
        chunk = self._roster[self._tu_cursor:self._tu_cursor + self._truthup_chunk]
        self._tu_cursor = (self._tu_cursor + self._truthup_chunk) % len(self._roster)
        for wallet in chunk:
            try:
                await self._watcher.truth_up(wallet)
                self._last_poll_mono = now_mono
            except Exception as exc:  # noqa: BLE001
                log.warning("harvest.truthup_failed", wallet=wallet, error=str(exc))

    async def run(
        self, now_wall_fn: Callable[[], int], now_mono_fn: Callable[[], int], *,
        tick_s: float = 2.0, poll_pause_s: float = 1.0, truthup_every: int = 5,
        checkpoint_path: Path | None = None, checkpoint_every: int = 30,
        on_realized: Callable[[tuple[RealizedRoundTrip, ...]], None] | None = None,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Concurrent poll-loop (detect opens) + tick-loop (enter/exit tranches). `on_realized`
        receives each step's harvested round-trips (the gate-feed hook)."""
        stop = stop or asyncio.Event()
        await asyncio.gather(
            self._poll_loop(now_wall_fn, now_mono_fn, poll_pause_s, truthup_every, stop),
            self._tick_loop(now_wall_fn, now_mono_fn, tick_s, checkpoint_path,
                            checkpoint_every, on_realized, stop))

    async def _poll_loop(self, wall_fn, mono_fn, poll_pause_s, truthup_every, stop):  # noqa: ANN001
        cycle = 0
        try:
            while not stop.is_set():
                if cycle % max(1, truthup_every) == 0:
                    await self._truthup_step(mono_fn())
                await self.poll(wall_fn(), mono_fn(), stop)
                cycle += 1
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_pause_s)
                except TimeoutError:
                    pass
        finally:
            stop.set()

    async def _tick_loop(self, wall_fn, mono_fn, tick_s, ckpt_path, ckpt_every, on_realized, stop):  # noqa: ANN001, E501
        n = 0
        try:
            while not stop.is_set():
                try:
                    rep = self.step(wall_fn())
                    if rep.realized and on_realized is not None:
                        # Delivery is at-least-once (checkpoint every N ticks): dedup by tranche id
                        # so a crash between deliver and checkpoint can't re-deliver an already-
                        # journaled round-trip (a duplicate TOP observation for the gate).
                        fresh = tuple(rt for rt in rep.realized if rt.id not in self._delivered)
                        if fresh:
                            on_realized(fresh)
                            self._delivered.update(rt.id for rt in fresh)
                    n += 1
                    if n % max(1, ckpt_every) == 0:
                        log.info("harvest.status", n=n, books=len(self._books),
                                 open_tranches=len(self._ledger.open_tranches()),
                                 gross=round(self._ledger.gross_open_notional(), 1),
                                 equity=round(self.equity(), 2))
                        if ckpt_path is not None:
                            self.checkpoint(ckpt_path)
                except Exception as exc:  # noqa: BLE001 — one bad tick must not kill the run
                    log.error("harvest.tick_failed", error=str(exc))
                try:
                    await asyncio.wait_for(stop.wait(), timeout=tick_s)
                except TimeoutError:
                    pass
        finally:
            stop.set()

    # ── durability ────────────────────────────────────────────────────────────────────────
    def to_state(self) -> dict[str, Any]:
        return {
            "watcher": self._watcher.to_state() if self._watcher is not None else None,
            "ledger": self._ledger.to_state(), "net": self._ex.to_state(),
            "cash": str(self._cash), "tu_cursor": self._tu_cursor,
            "contracts": {i: str(c) for i, c in self._contracts.items()},
            # Persist the per-wallet tail-aware sizing so a resume doesn't zero every notional (a
            # resume may pass empty lookups → all sizes 0 → no new tranches until the next roll).
            "notionals": dict(self._notional),
            "delivered": sorted(self._delivered),   # dedup realized deliveries across a restart
        }

    def from_state(self, st: dict[str, Any]) -> None:
        if self._watcher is not None and st.get("watcher") is not None:
            self._watcher.from_state(st["watcher"])
        self._ledger.from_state(st["ledger"])
        self._ex.from_state(st["net"])
        self._cash = Decimal(st["cash"])
        self._tu_cursor = int(st.get("tu_cursor", 0))
        self._contracts = {i: Decimal(c) for i, c in st.get("contracts", {}).items()}
        if "notionals" in st:                     # restore sizing so new tranches keep their size
            self._notional = {w: float(v) for w, v in st["notionals"].items()}
        self._delivered = set(st.get("delivered", []))
        self._last_poll_mono = None   # force a fresh poll before trading on resume

    def checkpoint(self, path: Path) -> None:
        """Atomic durable snapshot (temp → fsync → rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_state()))
        with tmp.open("rb+") as f:
            os.fsync(f.fileno())
        tmp.rename(path)

    @staticmethod
    def _mid(book: Book) -> Decimal:
        return (Decimal(str(book.best_bid)) + Decimal(str(book.best_ask))) / 2

    @staticmethod
    def _to_contracts(direction: int, notional: float, mark: Decimal) -> Decimal:
        if mark <= 0:
            return Decimal(0)
        return Decimal(direction) * Decimal(str(notional)) / mark
