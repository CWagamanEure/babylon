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

from dataclasses import dataclass
from decimal import Decimal

from babylon.core import Order, TimeInForce
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


class FollowRunner:
    def __init__(
        self, watcher: WalletWatcher, weights: dict[str, float], universe: list[str],
        sizer: Sizer, executor: PaperExecutor, *, budget_usd: float,
        max_coin_frac: float = 0.08, staleness_ms: int = 30_000,
        min_rebalance_usd: float = 20.0,
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
        self._books: dict[str, tuple[Book, int]] = {}

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
