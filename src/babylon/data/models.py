"""Typed models for Hyperliquid market data.

These parse the raw WebSocket / REST JSON into validated, strongly-typed objects.
Prices and sizes are kept as ``Decimal`` here to avoid float drift; the
storage/research layer (``to_row``) deliberately downcasts to ``float`` — see
the README's data-fidelity note.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TradeSide(StrEnum):
    """Aggressor (taker) side of a public trade print.

    Hyperliquid's trade ``side`` is the *taker* direction, NOT the resting book
    side: ``"B"`` means a market **buy** (taker lifted the ask) and ``"A"`` means
    a market **sell** (taker hit the bid). Name it by the taker action so signed
    order-flow / CVD features don't get inverted.
    """

    BUY = "B"
    SELL = "A"

    @property
    def sign(self) -> int:
        """+1 for taker buy, -1 for taker sell — for signed order-flow."""
        return 1 if self is TradeSide.BUY else -1


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class Trade(_Model):
    """A single public trade print."""

    coin: str
    side: TradeSide
    px: Decimal
    sz: Decimal
    time: int  # epoch millis (exchange time)
    hash: str = ""
    tid: int = 0

    @classmethod
    def from_ws(cls, d: dict[str, Any]) -> Trade:
        return cls(
            coin=d["coin"],
            side=TradeSide(d["side"]),
            px=Decimal(str(d["px"])),
            sz=Decimal(str(d["sz"])),
            time=int(d["time"]),
            hash=d.get("hash", ""),
            tid=int(d.get("tid", 0)),
        )

    def to_row(self) -> dict[str, Any]:
        """Flat, float-typed row for the storage/research layer.

        ``(time, tid)`` is the unique key — many prints from one sweep share a ``time``.
        """
        return {
            "time": self.time,
            "side": self.side.value,
            "px": float(self.px),
            "sz": float(self.sz),
            "tid": self.tid,
        }


class BookLevel(_Model):
    px: Decimal
    sz: Decimal
    n: int = 0  # number of resting orders at this level

    @classmethod
    def from_ws(cls, d: dict[str, Any]) -> BookLevel:
        return cls(px=Decimal(str(d["px"])), sz=Decimal(str(d["sz"])), n=int(d.get("n", 0)))


class L2Book(_Model):
    """A full L2 order-book snapshot for one coin.

    Hyperliquid sends ``levels = [bids, asks]`` with bids sorted descending and
    asks ascending; :meth:`is_valid` checks that invariant before the snapshot is
    trusted downstream.
    """

    coin: str
    time: int  # epoch millis (exchange time)
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    ver_num: int | None = None  # archive sequence number; None for live WS

    @classmethod
    def from_ws(cls, d: dict[str, Any], ver_num: int | None = None) -> L2Book:
        bids_raw, asks_raw = d["levels"]
        return cls(
            coin=d["coin"],
            time=int(d["time"]),
            bids=tuple(BookLevel.from_ws(x) for x in bids_raw),
            asks=tuple(BookLevel.from_ws(x) for x in asks_raw),
            ver_num=ver_num,
        )

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].px if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].px if self.asks else None

    @property
    def mid(self) -> Decimal | None:
        """Plain arithmetic mid. For a less-biased fair value compute the
        microprice downstream from the L1 sizes preserved in :meth:`to_row`."""
        if self.bids and self.asks:
            return (self.bids[0].px + self.asks[0].px) / 2
        return None

    def is_valid(self) -> bool:
        """True if the book obeys L2 ordering invariants (bids descending, asks
        ascending, not crossed). A failing snapshot is malformed and should be
        dropped rather than persisted as if real."""
        b, a = self.bids, self.asks
        if any(b[i].px < b[i + 1].px for i in range(len(b) - 1)):
            return False
        if any(a[i].px > a[i + 1].px for i in range(len(a) - 1)):
            return False
        if b and a and b[0].px >= a[0].px:
            return False
        return True

    def to_row(self, max_levels: int = 20) -> dict[str, Any]:
        """Flat, float-typed snapshot row preserving full depth (px/sz/n) as lists.

        Used by both the live recorder and the historical archive ingester so
        live and backfilled L2 land in one schema. ``(time, ver_num)`` is the key.
        """
        bids = self.bids[:max_levels]
        asks = self.asks[:max_levels]
        return {
            "time": self.time,
            "ver_num": self.ver_num,
            "best_bid": float(self.best_bid) if self.best_bid is not None else None,
            "best_ask": float(self.best_ask) if self.best_ask is not None else None,
            "mid": float(self.mid) if self.mid is not None else None,
            "bid_px": [float(lvl.px) for lvl in bids],
            "bid_sz": [float(lvl.sz) for lvl in bids],
            "bid_n": [lvl.n for lvl in bids],
            "ask_px": [float(lvl.px) for lvl in asks],
            "ask_sz": [float(lvl.sz) for lvl in asks],
            "ask_n": [lvl.n for lvl in asks],
        }


class Candle(_Model):
    """An OHLCV candle."""

    coin: str = Field(alias="s")
    interval: str = Field(alias="i")
    open_time: int = Field(alias="t")
    close_time: int = Field(alias="T")
    open: Decimal = Field(alias="o")
    close: Decimal = Field(alias="c")
    high: Decimal = Field(alias="h")
    low: Decimal = Field(alias="l")
    volume: Decimal = Field(alias="v")
    trades: int = Field(alias="n", default=0)

    @classmethod
    def from_ws(cls, d: dict[str, Any]) -> Candle:
        return cls(
            s=d["s"],
            i=d["i"],
            t=int(d["t"]),
            T=int(d["T"]),
            o=Decimal(str(d["o"])),
            c=Decimal(str(d["c"])),
            h=Decimal(str(d["h"])),
            l=Decimal(str(d["l"])),
            v=Decimal(str(d["v"])),
            n=int(d.get("n", 0)),
        )


class Bbo(_Model):
    """Best bid/offer tick."""

    coin: str
    time: int
    bid: BookLevel | None
    ask: BookLevel | None

    @classmethod
    def from_ws(cls, d: dict[str, Any]) -> Bbo:
        bid_raw, ask_raw = d["bbo"]
        return cls(
            coin=d["coin"],
            time=int(d["time"]),
            bid=BookLevel.from_ws(bid_raw) if bid_raw else None,
            ask=BookLevel.from_ws(ask_raw) if ask_raw else None,
        )

    def to_row(self) -> dict[str, Any]:
        """Flat, float-typed row matching the L2 fidelity (floats, not strings)."""
        return {
            "time": self.time,
            "bid_px": float(self.bid.px) if self.bid else None,
            "bid_sz": float(self.bid.sz) if self.bid else None,
            "bid_n": self.bid.n if self.bid else None,
            "ask_px": float(self.ask.px) if self.ask else None,
            "ask_sz": float(self.ask.sz) if self.ask else None,
            "ask_n": self.ask.n if self.ask else None,
        }


class AllMids(_Model):
    """Snapshot of mid prices for every coin."""

    mids: dict[str, Decimal]

    @classmethod
    def from_ws(cls, d: dict[str, Any]) -> AllMids:
        return cls(mids={k: Decimal(str(v)) for k, v in d["mids"].items()})
