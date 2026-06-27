from babylon.exchange.websocket import Subscription, WebSocketFeed


def test_subscription_payload_omits_none():
    assert Subscription(type="trades", coin="BTC").payload() == {"type": "trades", "coin": "BTC"}
    assert Subscription(type="allMids").payload() == {"type": "allMids"}
    assert Subscription(type="candle", coin="BTC", interval="1m").payload() == {
        "type": "candle",
        "coin": "BTC",
        "interval": "1m",
    }


async def test_dispatch_routes_to_handler():
    feed = WebSocketFeed(url="wss://example/ws")
    seen = []
    feed.on("trades", lambda data: seen.append(data) or _noop())
    await feed._dispatch({"channel": "trades", "data": [{"coin": "BTC"}]})
    assert seen == [[{"coin": "BTC"}]]


async def test_dispatch_ignores_control_frames():
    feed = WebSocketFeed(url="wss://example/ws")
    feed.on("pong", lambda data: (_ for _ in ()).throw(AssertionError("should not fire")))
    await feed._dispatch({"channel": "pong"})  # must not raise


async def test_bad_handler_does_not_propagate():
    feed = WebSocketFeed(url="wss://example/ws")

    async def boom(_data):
        raise RuntimeError("handler blew up")

    feed.on("trades", boom)
    await feed._dispatch({"channel": "trades", "data": []})  # swallowed + logged


async def _noop():
    return None
