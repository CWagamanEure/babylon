"""FollowRunner — the live paper run loop for the copy-trade experiment.

Wires the audited pieces into one driver (docs/LIVE_FOLLOW.md §v3.3-3.4): the
WalletWatcher (polled on the same event loop) feeds the aggregate consensus; each
trading tick sizes a per-coin target from the edge-weighted consensus, reconciles it
against the executor's net, and fills via PaperExecutor.submit_book against the LIVE L2
book (depth-aware, cost in the fill price). Single aggregate strategy → a direct
per-coin reconcile.

Hardened against the run-loop audit's failure modes:
- TWO clocks: a MONOTONIC clock for liveness (heartbeat) and the exchange WALL-CLOCK for
  book staleness (book ts are exchange-epoch ms) — one clock can't serve both safely.
- Heartbeat only refreshes on a SUCCESSFUL poll sweep (a total-failure sweep no longer
  looks fresh → the dead-feed guard actually fires).
- Loops are isolated and tear each other down: a tick exception is logged-and-continued,
  and any loop exit sets `stop` so a crash can't leave a heartbeat-refreshing orphan.
- Reduce-only EXIT is allowed on a stale book / halted signal (within exit_staleness) so a
  position whose feed died can still be flattened — only ENTRIES require a fresh book.
- Flip hysteresis: a sign reversal is gated by a cooldown so a flapping wallet can't churn.
- Truth-up runs in CHUNKS so it doesn't monopolise the shared throttle and starve the
  heartbeat.
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
from babylon.data.models import L2Book
from babylon.exchange.websocket import Subscription, WebSocketFeed
from babylon.execution.fill_model import Book, FillReport
from babylon.execution.paper import PaperExecutor
from babylon.follow.watcher import WalletWatcher
from babylon.logging import get_logger
from babylon.sizing.edge import FrozenEdge
from babylon.sizing.sizer import Sizer

log = get_logger("follow.runner")
_DUMMY_EDGE = FrozenEdge([0.0], 0).estimate()  # FixedFractionSizer ignores the edge


@dataclass(frozen=True, slots=True)
class TickReport:
    fills: tuple[object, ...]
    no_fills: dict[str, str]      # coin -> reason (capacity diagnostics)
    stale_skipped: tuple[str, ...]
    halted: bool = False          # signal stale (no recent successful poll) → flatten only
    frozen: tuple[str, ...] = ()  # OPEN positions that can't be managed (feed dead) — ALERT


class FollowRunner:
    def __init__(
        self, watcher: WalletWatcher, weights: dict[str, float], universe: list[str],
        sizer: Sizer, executor: PaperExecutor, *, budget_usd: float,
        max_coin_frac: float = 0.08, staleness_ms: int = 30_000,
        exit_staleness_ms: int = 300_000, min_rebalance_usd: float = 20.0,
        heartbeat_ms: int = 1_200_000, flip_cooldown_ms: int = 300_000,
        truthup_chunk: int = 20, equity_fn: Callable[[], float] | None = None,
    ) -> None:
        if getattr(executor, "_mode", "retail") == "validator":
            raise ValueError(
                "validator executor needs a wallet_px feed not yet plumbed into FollowRunner; "
                "use retail (the experiment's binding arm) until the wallet-px path exists")
        self._watcher = watcher
        self._weights = weights                 # frozen per-wallet Kelly weights (Σ≤1)
        self._universe = sorted(set(universe))
        self._sizer = sizer
        self._ex = executor
        self._budget = Decimal(str(budget_usd))
        self._equity_fn = equity_fn             # mark-to-market equity; None → fixed budget
        self._max_coin = Decimal(str(max_coin_frac))
        self._staleness_ms = staleness_ms
        self._exit_staleness_ms = exit_staleness_ms
        self._min_rebal = Decimal(str(min_rebalance_usd))
        self._heartbeat_ms = heartbeat_ms
        self._flip_cooldown_ms = flip_cooldown_ms
        self._truthup_chunk = max(1, truthup_chunk)
        self._books: dict[str, tuple[Book, int]] = {}
        self._last_poll_mono: int | None = None   # heartbeat (MONOTONIC ms)
        self._last_fill_wall: dict[str, int] = {}  # for flip hysteresis (WALL ms)
        self._tu_cursor = 0
        self._cash = Decimal(str(budget_usd))     # paper cash; fills book their cashflow
        self._funding_pnl = Decimal(0)            # cumulative funding carry (in cash already)

    def on_book(self, coin: str, book: Book, ts: int) -> None:
        """Feed a live L2 book update; ``ts`` is the snapshot's EXCHANGE wall-clock ms."""
        self._books[coin] = (book, ts)

    @staticmethod
    def _mid(book: Book) -> Decimal | None:
        bb, ba = book.best_bid, book.best_ask
        if bb is None or ba is None or bb <= 0 or ba <= 0 or bb >= ba:
            return None
        return (Decimal(str(bb)) + Decimal(str(ba))) / 2

    def equity(self) -> Decimal:
        """Mark-to-market paper equity = cash + Σ position·mark (funding already in cash).
        Coins with no usable mark are valued at cost (their cash impact is already booked)."""
        eq = self._cash
        for coin in self._ex.net_positions():
            bt = self._books.get(coin)
            mark = self._mid(bt[0]) if bt is not None else None
            if mark is not None:
                eq += self._ex.net_position(coin) * mark
        return eq

    def _budget_equity(self) -> Decimal:
        eq = self._equity_fn() if self._equity_fn is not None else float(self.equity())
        return min(self._budget, Decimal(str(max(0.0, eq))))  # de-lever as equity bleeds

    def accrue_funding(self, rates: dict[str, float]) -> None:
        """Apply one funding period: a long pays `rate` of its notional when rate>0, a
        short receives. Books into cash so equity/sizing reflect the carry (material on
        the multi-hour/day holds these wallets take)."""
        for coin, pos in self._ex.net_positions().items():
            bt = self._books.get(coin)
            mark = self._mid(bt[0]) if bt is not None else None
            rate = rates.get(coin)
            if mark is None or rate is None:
                continue
            cost = pos * mark * Decimal(str(rate))   # signed: long·+rate = pays (cash down)
            self._cash -= cost
            self._funding_pnl -= cost

    def _target(self, coin: str, mark: Decimal) -> Decimal:
        consensus = self._watcher.consensus_sign(coin, self._weights)  # ∈ [-1, 1]
        if consensus == 0.0:
            return Decimal(0)
        budget = self._budget_equity()
        raw = self._sizer.target_size(
            edge=_DUMMY_EDGE, direction=consensus, budget_equity=budget, mark_price=mark)
        cap = self._max_coin * budget / mark
        return cap if raw > cap else (-cap if raw < -cap else raw)

    def tick(self, now_wall: int, now_mono: int) -> TickReport:
        """One trading tick. Heartbeat halt (monotonic) → flatten-only; a stale book blocks
        ENTRIES but a reduce-only EXIT is allowed within exit_staleness; a position with no
        usable price is reported `frozen` (operator alert) rather than silently held."""
        halted = self._last_poll_mono is None or now_mono - self._last_poll_mono > self._heartbeat_ms
        fills: list[object] = []
        no_fills: dict[str, str] = {}
        stale: list[str] = []
        frozen: list[str] = []
        for coin in self._universe:
            bt = self._books.get(coin)
            book = bt[0] if bt is not None else None
            age = (now_wall - bt[1]) if bt is not None else None
            mark = self._mid(book) if book is not None else None
            current = self._ex.net_position(coin)
            entry_fresh = age is not None and age <= self._staleness_ms and not halted
            # target: flatten on halt; on an entry-stale book only exit; else size normally
            if halted or not entry_fresh:
                if current == 0:
                    stale.append(coin)
                    continue
                target = Decimal(0)                      # flatten the (orphaned) position
            else:
                target = self._target(coin, mark) if mark is not None else current
            if mark is None:                             # no price → can't act on an open pos
                frozen.append(coin) if current != 0 else stale.append(coin)
                continue
            delta = target - current
            if abs(delta) * mark < self._min_rebal:
                continue
            reducing = abs(target) < abs(current)
            if (halted or not entry_fresh):
                # exit path: only reduce, only within the (looser) exit-staleness window
                if not reducing or age is None or age > self._exit_staleness_ms:
                    if current != 0:
                        frozen.append(coin)
                    continue
            elif current != 0 and (target < 0) != (current < 0):
                # flip hysteresis: don't reverse sign within the cooldown
                if now_wall - self._last_fill_wall.get(coin, -10**18) < self._flip_cooldown_ms:
                    continue
            order = Order(coin=coin, size=delta, price=None, reduce_only=reducing,
                          tif=TimeInForce.IOC, cloid=f"{coin}-{now_wall}")
            assert book is not None  # guaranteed: mark is not None ⇒ book is not None
            fill, report = self._ex.submit_book(order, book, now_wall)
            if fill is not None:
                fills.append(fill)
                self._cash -= fill.size * fill.price   # book the cashflow (buy↓ / sell↑)
                self._last_fill_wall[coin] = now_wall
            elif not report.filled:
                no_fills[coin] = report.no_fill_reason or "no fill"
        if frozen:
            log.error("tick.frozen_positions", coins=frozen)  # operator must intervene
        return TickReport(tuple(fills), no_fills, tuple(stale), halted=halted, frozen=tuple(frozen))

    async def poll(self, now_wall: int, now_mono: int,
                   stop: asyncio.Event | None = None) -> int:
        """One watcher sweep; the heartbeat refreshes ONLY if ≥1 wallet polled OK (a total
        failure must not look fresh). Honors `stop` mid-sweep so shutdown is prompt even at
        the throttled roster scale. Returns the success count."""
        ok = 0
        for wallet in self._weights:
            if stop is not None and stop.is_set():
                break
            try:
                await self._watcher.poll_wallet(wallet, now_wall)
                ok += 1
            except Exception as exc:  # noqa: BLE001 — per-wallet isolation (audit #7)
                log.warning("poll.wallet_failed", wallet=wallet, error=str(exc))
        if ok:
            self._last_poll_mono = now_mono
        else:
            log.error("poll.total_failure", n=len(self._weights))
        return ok

    async def _truthup_chunk_step(self, now_wall: int) -> None:
        """Truth-up a few wallets per cycle (chunked) so it doesn't monopolise the shared
        throttle and starve the heartbeat."""
        roster = list(self._weights)
        if not roster:
            return
        chunk = roster[self._tu_cursor:self._tu_cursor + self._truthup_chunk]
        self._tu_cursor = (self._tu_cursor + self._truthup_chunk) % len(roster)
        for wallet in chunk:
            try:
                await self._watcher.truth_up(wallet)
            except Exception as exc:  # noqa: BLE001
                log.warning("truthup.wallet_failed", wallet=wallet, error=str(exc))

    def to_state(self) -> dict[str, Any]:
        return {
            "watcher": self._watcher.to_state(), "net": self._ex.to_state(),
            "cash": str(self._cash), "funding_pnl": str(self._funding_pnl),
            "last_fill_wall": dict(self._last_fill_wall),
            "last_poll_mono": self._last_poll_mono, "tu_cursor": self._tu_cursor,
        }

    def from_state(self, st: dict[str, Any]) -> None:
        self._watcher.from_state(st["watcher"])
        self._ex.from_state(st["net"])
        self._cash = Decimal(st["cash"])
        self._funding_pnl = Decimal(st["funding_pnl"])
        self._last_fill_wall = {k: int(v) for k, v in st["last_fill_wall"].items()}
        self._last_poll_mono = None   # force a fresh poll (heartbeat) before trading on resume
        self._tu_cursor = int(st["tu_cursor"])

    def checkpoint(self, path: Path) -> None:
        """Atomic durable snapshot (temp → fsync → rename). A CONSISTENT cut: called
        synchronously from the tick loop, and tick() has no awaits, so the watcher _pos
        and the executor net are captured at the same instant (no poll mid-mutation)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_state()))
        with tmp.open("rb+") as f:
            os.fsync(f.fileno())
        tmp.rename(path)

    async def run(
        self, now_wall_fn: Callable[[], int], now_mono_fn: Callable[[], int], *,
        tick_s: float = 2.0, poll_pause_s: float = 1.0, truthup_every: int = 5,
        checkpoint_path: Path | None = None, checkpoint_every: int = 30,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Concurrent poll-loop (sweep + chunked truth-up) and trading tick-loop. Pass a
        WALL-clock ms source and a MONOTONIC ms source. Any loop's exit sets `stop`, so a
        crash tears down its sibling instead of leaving a zombie."""
        stop = stop or asyncio.Event()
        await asyncio.gather(
            self._poll_loop(now_wall_fn, now_mono_fn, poll_pause_s, truthup_every, stop),
            self._tick_loop(now_wall_fn, now_mono_fn, tick_s, checkpoint_path,
                            checkpoint_every, stop),
        )

    async def _poll_loop(self, now_wall_fn: Callable[[], int], now_mono_fn: Callable[[], int],
                         poll_pause_s: float, truthup_every: int, stop: asyncio.Event) -> None:
        cycle = 0
        try:
            while not stop.is_set():
                if cycle % max(1, truthup_every) == 0:
                    await self._truthup_chunk_step(now_wall_fn())
                await self.poll(now_wall_fn(), now_mono_fn(), stop)
                cycle += 1
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_pause_s)
                except (TimeoutError, asyncio.TimeoutError):
                    pass
        finally:
            stop.set()  # tear down the sibling on any exit

    async def _tick_loop(self, now_wall_fn: Callable[[], int], now_mono_fn: Callable[[], int],
                         tick_s: float, checkpoint_path: Path | None, checkpoint_every: int,
                         stop: asyncio.Event) -> None:
        n = 0
        try:
            while not stop.is_set():
                try:
                    rep = self.tick(now_wall_fn(), now_mono_fn())
                    if rep.halted:
                        log.warning("tick.halted_stale_signal")
                    n += 1
                    if checkpoint_path is not None and n % max(1, checkpoint_every) == 0:
                        self.checkpoint(checkpoint_path)
                except Exception as exc:  # noqa: BLE001 — one bad tick must not kill the run
                    log.error("tick.failed", error=str(exc))
                try:
                    await asyncio.wait_for(stop.wait(), timeout=tick_s)
                except (TimeoutError, asyncio.TimeoutError):
                    pass
        finally:
            stop.set()


def book_from_l2(l2: L2Book, max_levels: int = 20) -> Book:
    """Convert a live WS L2Book snapshot to the fill_model.Book the executor walks."""
    b, a = l2.bids[:max_levels], l2.asks[:max_levels]
    return Book(
        bid_px=tuple(float(lvl.px) for lvl in b), bid_sz=tuple(float(lvl.sz) for lvl in b),
        ask_px=tuple(float(lvl.px) for lvl in a), ask_sz=tuple(float(lvl.sz) for lvl in a),
    )


def attach_l2_feed(runner: FollowRunner, feed: WebSocketFeed, universe: list[str]) -> None:
    """Subscribe l2Book for the universe and pipe each valid snapshot into runner.on_book.
    Dropped (invalid) snapshots are counted per coin so a feed-integrity outage is visible,
    not mistaken for a quiet market."""
    drops: dict[str, int] = {}
    for coin in universe:
        feed.subscribe(Subscription(type="l2Book", coin=coin))

    async def _on_book(data: object) -> None:
        if not isinstance(data, dict):
            return
        l2 = L2Book.from_ws(data)
        if l2.is_valid():
            runner.on_book(l2.coin, book_from_l2(l2), l2.time)
        else:
            drops[l2.coin] = drops.get(l2.coin, 0) + 1
            if drops[l2.coin] % 25 == 0:
                log.warning("feed.invalid_snapshots", coin=l2.coin, count=drops[l2.coin])

    feed.on("l2Book", _on_book)
