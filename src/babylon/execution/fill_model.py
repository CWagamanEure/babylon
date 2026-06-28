"""Backtest fill model — taker fills against a replayed L2 depth snapshot.

Follows the SAME cross-the-spread rule as ``PaperExecutor`` (buy lifts the ask,
sell hits the bid) but, given real depth, **walks the book** for size beyond the
top level so large orders pay realistic slippage instead of a free fill at touch.

v1 is deliberately constrained (per the backtest audit, ``docs/BACKTEST.md`` §8b):
- **Full-fill-or-no-fill, never partial.** A partial fill corrupts the engine's
  per-strategy share attribution (built on a full-fill assumption) and trips the
  ledger==executor invariant. So if an order would consume more than
  ``max_depth_fraction`` of the visible book — or exhaust it — we return **None**
  (no fill) and let the reconciler re-attempt; we never invent liquidity or sweep
  the whole frozen book for free.
- **Float book in, Decimal price out.** The replay book is float (speed); the fill
  price crosses to ``Decimal`` at this boundary for the ledger.
- **Zero-latency** (fills at the decision-time book) with an optional
  ``slippage_bps`` haircut — a crude stand-in until event-time ``T+δ`` fills land.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from babylon.core import Fill, Order

FILL_MODEL_VERSION = 1
TAKER_FEE = 0.00045  # 4.5 bps/side — the single source of truth (engine imports this)


@dataclass(frozen=True, slots=True)
class Book:
    """Top-N depth per side, best level first, as floats (from the replay)."""

    bid_px: tuple[float, ...]
    bid_sz: tuple[float, ...]
    ask_px: tuple[float, ...]
    ask_sz: tuple[float, ...]

    @property
    def best_bid(self) -> float | None:
        return self.bid_px[0] if self.bid_px else None

    @property
    def best_ask(self) -> float | None:
        return self.ask_px[0] if self.ask_px else None

    @property
    def crossed(self) -> bool:
        bb, ba = self.best_bid, self.best_ask
        return bb is not None and ba is not None and bb >= ba


@dataclass(frozen=True, slots=True)
class FillReport:
    """Diagnostics for one fill attempt (for the backtest report)."""

    filled: bool
    depth_fraction: float  # of the side's visible size this order consumed (0 if no-fill)
    no_fill_reason: str | None = None


def fill(
    order: Order,
    book: Book,
    *,
    now: int,
    slippage_bps: float = 0.0,
    fee_bps: float = 0.0,
    max_depth_fraction: float = 0.25,
) -> tuple[Fill | None, FillReport]:
    """Attempt a taker fill. Returns (Fill or None, diagnostics). ``fee_bps`` (the
    taker fee) is folded into the fill price so the EQUITY curve actually pays it —
    otherwise the headline log-growth is fee-blind (the fee would only ever hit the
    separate edge series)."""
    if order.size == 0:
        return None, FillReport(False, 0.0, "zero size")
    is_buy = order.is_buy
    levels_px = book.ask_px if is_buy else book.bid_px
    levels_sz = book.ask_sz if is_buy else book.bid_sz
    if not levels_px:
        return None, FillReport(False, 0.0, "no liquidity this side")

    need = abs(float(order.size))
    visible = sum(levels_sz)
    if visible <= 0:
        return None, FillReport(False, 0.0, "no visible size")
    frac = need / visible
    # Cap the single-fill book consumption — beyond it the frozen-snapshot VWAP is
    # fiction (no impact, instant refill). Too big → no fill (NOT a partial).
    if frac > max_depth_fraction:
        return None, FillReport(False, frac, "exceeds max_depth_fraction")

    remaining, cost, got = need, 0.0, 0.0
    for px, sz in zip(levels_px, levels_sz, strict=False):
        take = min(remaining, sz)
        cost += take * px
        got += take
        remaining -= take
        if remaining <= 1e-15:
            break
    if remaining > 1e-12:  # not enough visible depth to fill in full
        return None, FillReport(False, frac, "insufficient depth")

    vwap = cost / got
    worsen = (slippage_bps + fee_bps) / 1e4  # taker pays both, against the fill
    adj = vwap * (1.0 + worsen) if is_buy else vwap * (1.0 - worsen)
    f = Fill(coin=order.coin, size=order.size, price=Decimal(str(adj)), time=now,
             cloid=order.cloid)
    return f, FillReport(True, frac)
