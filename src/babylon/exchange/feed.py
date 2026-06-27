"""The Feed seam.

The engine consumes market data through this Protocol, never a concrete class —
so the live ``WebSocketFeed`` and the backtest ``NullFeed`` are interchangeable.
In backtest the engine's ``run()`` is never called (a synchronous driver pumps
``MarketView`` directly), so ``NullFeed`` only has to satisfy the type and the
constructor; its methods are no-ops.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from babylon.exchange.websocket import Handler, Subscription


@runtime_checkable
class Feed(Protocol):
    def subscribe(self, sub: Subscription) -> None: ...

    def on(self, channel: str, handler: Handler) -> None: ...

    def stop(self) -> None: ...

    async def run(self) -> None: ...


class NullFeed:
    """A feed that does nothing — for backtest, where the driver replays data
    itself and the engine's ``run()`` loop is bypassed."""

    def subscribe(self, sub: Subscription) -> None:
        return None

    def on(self, channel: str, handler: Handler) -> None:
        return None

    def stop(self) -> None:
        return None

    async def run(self) -> None:
        return None
