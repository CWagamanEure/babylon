"""Async REST client for the Hyperliquid ``/info`` endpoint.

This covers read-only market and account queries. Order placement (which needs
EIP-712 signing) will live in a separate execution module built on the official
``hyperliquid-python-sdk``.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, cast

import aiohttp

from babylon.data.models import AllMids, Candle, L2Book
from babylon.logging import get_logger

log = get_logger("rest")


class InfoClient:
    """Thin async wrapper over POST ``/info``. Use as an async context manager."""

    def __init__(self, rest_url: str, *, timeout: float = 10.0) -> None:
        self._url = rest_url.rstrip("/") + "/info"
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> InfoClient:
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _post(self, body: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("InfoClient must be used as an async context manager")
        async with self._session.post(self._url, json=body) as resp:
            resp.raise_for_status()
            return await resp.json()

    # --- market data ---------------------------------------------------------

    async def meta(self) -> dict[str, Any]:
        """Perp universe metadata (assets, size decimals, max leverage)."""
        return cast("dict[str, Any]", await self._post({"type": "meta"}))

    async def all_mids(self) -> AllMids:
        raw = await self._post({"type": "allMids"})
        return AllMids.from_ws({"mids": raw})

    async def l2_book(self, coin: str) -> L2Book:
        raw = await self._post({"type": "l2Book", "coin": coin})
        return L2Book.from_ws(raw)

    async def candle_snapshot(
        self, coin: str, interval: str, start_ms: int, end_ms: int
    ) -> list[Candle]:
        raw = await self._post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            }
        )
        return [Candle.from_ws(c) for c in raw]

    # --- account -------------------------------------------------------------

    async def clearinghouse_state(self, address: str) -> dict[str, Any]:
        """Perp account state: positions, margin, withdrawable balance."""
        body = {"type": "clearinghouseState", "user": address}
        return cast("dict[str, Any]", await self._post(body))

    async def open_orders(self, address: str) -> list[dict[str, Any]]:
        body = {"type": "openOrders", "user": address}
        return cast("list[dict[str, Any]]", await self._post(body))
