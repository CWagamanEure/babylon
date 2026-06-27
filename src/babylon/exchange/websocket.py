"""Async, auto-reconnecting WebSocket feed for Hyperliquid market data.

The feed owns one connection. Register typed handlers with :meth:`on`, declare
what you want with :meth:`subscribe`, then ``await feed.run()``. On disconnect it
reconnects with exponential backoff and replays every subscription, so callers
never have to think about connection lifecycle.

Liveness: the library's protocol-level ping/pong (``ping_interval``/``ping_timeout``)
detects a half-open (silently dead) socket and forces a reconnect; the app-level
``{"method":"ping"}`` heartbeat additionally satisfies Hyperliquid's ~60s
application-inactivity timeout.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from babylon.logging import get_logger

log = get_logger("ws")

# App-level heartbeat — well inside Hyperliquid's ~60s application timeout.
PING_INTERVAL = 50.0
# Protocol-level keepalive — catches half-open sockets the app ping can't.
WS_PING_INTERVAL = 20.0
WS_PING_TIMEOUT = 20.0
MAX_BACKOFF = 30.0

Handler = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Subscription:
    """A market-data subscription. ``coin`` / ``interval`` / ``user`` are
    filled per subscription ``type`` as required by Hyperliquid."""

    type: str
    coin: str | None = None
    interval: str | None = None
    user: str | None = None

    def payload(self) -> dict[str, str]:
        sub: dict[str, str] = {"type": self.type}
        if self.coin is not None:
            sub["coin"] = self.coin
        if self.interval is not None:
            sub["interval"] = self.interval
        if self.user is not None:
            sub["user"] = self.user
        return sub


@dataclass
class WebSocketFeed:
    url: str
    _subscriptions: set[Subscription] = field(default_factory=set)
    _handlers: dict[str, list[Handler]] = field(default_factory=dict)
    _ws: websockets.ClientConnection | None = field(default=None, repr=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _received: bool = field(default=False)

    def subscribe(self, sub: Subscription) -> None:
        """Declare a subscription. Must be called before :meth:`run`; new
        subscriptions take effect on the next (re)connect."""
        self._subscriptions.add(sub)

    def on(self, channel: str, handler: Handler) -> None:
        """Register an async handler for a WS channel (e.g. ``"trades"``)."""
        self._handlers.setdefault(channel, []).append(handler)

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._received = False
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=WS_PING_INTERVAL,
                    ping_timeout=WS_PING_TIMEOUT,
                ) as ws:
                    self._ws = ws
                    log.info("ws.connected", url=self.url)
                    await self._resubscribe()
                    await self._serve(ws)
            except ConnectionClosed:
                log.warning("ws.closed", reconnect_in=round(backoff, 1))
            except Exception as exc:  # noqa: BLE001 — log and reconnect, never die
                log.error("ws.error", error=str(exc))
            finally:
                self._ws = None
            if self._stop.is_set():
                break
            # Only reset backoff once a connection proved healthy (received data);
            # a server that accepts then instantly drops must not defeat backoff.
            if self._received:
                backoff = 1.0
            await asyncio.sleep(backoff)
            if not self._received:
                backoff = min(backoff * 2, MAX_BACKOFF)

    async def _serve(self, ws: websockets.ClientConnection) -> None:
        """Run reader + heartbeat until one ends or a stop is requested.

        Racing against ``_stop`` lets :meth:`stop` tear down a live connection
        promptly instead of only being noticed between reconnects.
        """
        hb = asyncio.create_task(self._heartbeat(ws))
        rd = asyncio.create_task(self._read_loop(ws))
        stop = asyncio.create_task(self._stop.wait())
        tasks: set[asyncio.Task[Any]] = {hb, rd, stop}
        try:
            done, _pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (hb, rd, stop):
                task.cancel()
            await asyncio.gather(hb, rd, stop, return_exceptions=True)
        # Surface a real failure (e.g. ConnectionClosed) so run() can reconnect.
        for task in done:
            if task is not stop and not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    raise exc

    async def _resubscribe(self) -> None:
        for sub in list(self._subscriptions):
            await self._send({"method": "subscribe", "subscription": sub.payload()})
            log.debug("ws.subscribe", **sub.payload())

    async def _send(self, msg: dict[str, Any]) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(msg))

    async def _heartbeat(self, ws: websockets.ClientConnection) -> None:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await ws.send(json.dumps({"method": "ping"}))

    async def _read_loop(self, ws: websockets.ClientConnection) -> None:
        async for raw in ws:
            self._received = True
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("ws.bad_json", raw=str(raw)[:200])
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        channel = msg.get("channel")
        if not isinstance(channel, str) or channel in ("pong", "subscriptionResponse"):
            return
        handlers = self._handlers.get(channel)
        if not handlers:
            return
        data = msg.get("data")
        for handler in handlers:
            try:
                await handler(data)
            except Exception:  # noqa: BLE001 — one bad handler must not kill the feed
                log.exception("ws.handler_error", channel=channel)
