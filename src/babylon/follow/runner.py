"""FollowRunner — the live paper run loop for the copy-trade experiment.

Wires the audited pieces into one driver (docs/LIVE_FOLLOW.md §v3.3-3.4): the
WalletWatcher (polled on the same event loop) feeds the aggregate consensus; each
trading tick sizes a per-coin target from the edge-weighted consensus, reconciles it
against the executor's net, and fills via PaperExecutor.submit_book against the LIVE L2
book (depth-aware, cost in the fill price). Single aggregate strategy → a direct
per-coin reconcile (no multi-strategy netting needed).

Built to the executor audit's integration spec: it stores full L2 depth (not just
top-of-book), unpacks (fill, report), gates the net/journal on `fill is not None`, and
applies a staleness guard so a quiet coin is never traded on a stale book.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

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
    no_fills: dict[str, str]      # coin -> reason (capacity/staleness diagnostics)
    stale_skipped: tuple[str, ...]
    halted: bool = False          # signal stale (no recent poll) → traded nothing


class FollowRunner:
    def __init__(
        self, watcher: WalletWatcher, weights: dict[str, float], universe: list[str],
        sizer: Sizer, executor: PaperExecutor, *, budget_usd: float,
        max_coin_frac: float = 0.08, staleness_ms: int = 30_000,
        min_rebalance_usd: float = 20.0, heartbeat_ms: int = 600_000,
    ) -> None:
        self._watcher = watcher
        self._weights = weights                 # frozen per-wallet Kelly weights (Σ≤1)
        self._universe = sorted(set(universe))
        self._sizer = sizer
        self._ex = executor
        self._budget = Decimal(str(budget_usd))
        self._max_coin = Decimal(str(max_coin_frac))
        self._staleness_ms = staleness_ms
        self._min_rebal = Decimal(str(min_rebalance_usd))
        self._heartbeat_ms = heartbeat_ms
        self._books: dict[str, tuple[Book, int]] = {}
        self._last_poll_ok: int | None = None   # heartbeat: last successful roster sweep

    def on_book(self, coin: str, book: Book, ts: int) -> None:
        """Feed a live L2 book update (from the WS l2Book feed)."""
        self._books[coin] = (book, ts)

    @staticmethod
    def _mid(book: Book) -> Decimal | None:
        bb, ba = book.best_bid, book.best_ask
        if bb is None or ba is None or bb <= 0 or ba <= 0 or bb >= ba:
            return None
        return (Decimal(str(bb)) + Decimal(str(ba))) / 2

    def _target(self, coin: str, mark: Decimal) -> Decimal:
        """Signed target position (coin units) from the edge-weighted consensus, capped
        at max_coin_frac of budget."""
        consensus = self._watcher.consensus_sign(coin, self._weights)  # ∈ [-1, 1]
        if consensus == 0.0:
            return Decimal(0)
        raw = self._sizer.target_size(
            edge=_DUMMY_EDGE, direction=consensus, budget_equity=self._budget, mark_price=mark)
        cap = self._max_coin * self._budget / mark   # hard per-coin notional cap
        if raw > cap:
            return cap
        if raw < -cap:
            return -cap
        return raw

    def tick(self, now: int) -> TickReport:
        """One trading tick: reconcile every universe coin's target vs net, fill the
        deltas against the live book. Coins with a stale/absent book are skipped."""
        # heartbeat halt: never trade a stale SIGNAL (poll loop dead / not yet started).
        if self._last_poll_ok is None or now - self._last_poll_ok > self._heartbeat_ms:
            return TickReport((), {}, tuple(self._universe), halted=True)
        fills: list[object] = []
        no_fills: dict[str, str] = {}
        stale: list[str] = []
        for coin in self._universe:
            bt = self._books.get(coin)
            if bt is None or now - bt[1] > self._staleness_ms:
                stale.append(coin)
                continue
            book, _ = bt
            mark = self._mid(book)
            if mark is None:
                stale.append(coin)
                continue
            target = self._target(coin, mark)
            current = self._ex.net_position(coin)
            delta = target - current
            if abs(delta) * mark < self._min_rebal:     # deadband (avoid churning dust)
                continue
            order = Order(coin=coin, size=delta, price=None, reduce_only=False,
                          tif=TimeInForce.IOC, cloid=f"{coin}-{now}")
            fill, report = self._ex.submit_book(order, book, now)
            if fill is not None:
                fills.append(fill)
            elif not report.filled:
                no_fills[coin] = report.no_fill_reason or "no fill"
        return TickReport(tuple(fills), no_fills, tuple(stale))

    async def poll(self, now_ms: int) -> None:
        """One watcher sweep over the followed roster (run as a task on the same loop)."""
        for wallet in self._weights:
            try:
                await self._watcher.poll_wallet(wallet, now_ms)
            except Exception as exc:  # noqa: BLE001 — per-wallet isolation (audit #7)
                log.warning("poll.wallet_failed", wallet=wallet, error=str(exc))
        self._last_poll_ok = now_ms      # heartbeat: the signal is fresh as of this sweep

    async def run(
        self, now_fn: Callable[[], int], *, tick_s: float = 2.0, truthup_s: float = 300.0,
        poll_pause_s: float = 1.0, stop: asyncio.Event | None = None,
    ) -> None:
        """Drive the loop: a continuous poll sweep (throttled inside the watcher, with a
        small inter-sweep pause) + periodic clearinghouse truth-up, concurrently with a
        fixed-cadence trading tick. tick() is synchronous, so it reads a consistent
        consensus snapshot between the poll's awaits (the watcher's per-wallet locks
        protect _pos)."""
        stop = stop or asyncio.Event()
        await asyncio.gather(
            self._poll_loop(now_fn, truthup_s, poll_pause_s, stop),
            self._tick_loop(now_fn, tick_s, stop),
        )

    async def _poll_loop(self, now_fn: Callable[[], int], truthup_s: float,
                         poll_pause_s: float, stop: asyncio.Event) -> None:
        last_tu = 0.0
        while not stop.is_set():
            now = now_fn()
            if now - last_tu >= truthup_s * 1000:
                try:
                    await self._watcher.truth_up_all()
                except Exception as exc:  # noqa: BLE001
                    log.warning("truthup.failed", error=str(exc))
                last_tu = now
            await self.poll(now)
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_pause_s)
            except (TimeoutError, asyncio.TimeoutError):
                pass

    async def _tick_loop(self, now_fn: Callable[[], int], tick_s: float,
                         stop: asyncio.Event) -> None:
        while not stop.is_set():
            rep = self.tick(now_fn())
            if rep.halted:
                log.warning("tick.halted_stale_signal")
            try:
                await asyncio.wait_for(stop.wait(), timeout=tick_s)
            except (TimeoutError, asyncio.TimeoutError):
                pass


def book_from_l2(l2: L2Book, max_levels: int = 20) -> Book:
    """Convert a live WS L2Book snapshot to the fill_model.Book the executor walks."""
    b, a = l2.bids[:max_levels], l2.asks[:max_levels]
    return Book(
        bid_px=tuple(float(lvl.px) for lvl in b), bid_sz=tuple(float(lvl.sz) for lvl in b),
        ask_px=tuple(float(lvl.px) for lvl in a), ask_sz=tuple(float(lvl.sz) for lvl in a),
    )


def attach_l2_feed(runner: FollowRunner, feed: WebSocketFeed, universe: list[str]) -> None:
    """Subscribe l2Book for the universe and pipe each snapshot into runner.on_book."""
    for coin in universe:
        feed.subscribe(Subscription(type="l2Book", coin=coin))

    async def _on_book(data: object) -> None:
        if not isinstance(data, dict):
            return
        l2 = L2Book.from_ws(data)
        if l2.is_valid():
            runner.on_book(l2.coin, book_from_l2(l2), l2.time)

    feed.on("l2Book", _on_book)
