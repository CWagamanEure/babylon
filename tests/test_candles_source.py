import asyncio

from babylon.follow.candles_source import fetch_lookups

H = 3_600_000


class _Candle:
    def __init__(self, ot, c): self.open_time = ot; self.close = c


class _FakeInfo:
    async def candle_snapshot(self, coin, interval, s, e):
        if coin == "BAD":
            raise RuntimeError("boom")
        if coin == "EMPTY":
            return []
        return [_Candle(H, 110.0), _Candle(0, 100.0)]   # unsorted on purpose


def test_fetch_lookups_sorts_and_skips_bad():
    lk = asyncio.run(fetch_lookups(_FakeInfo(), ["BTC", "BAD", "EMPTY"], 0, 10 * H, gap_s=0.0))
    assert set(lk) == {"BTC"}                            # BAD (error) + EMPTY skipped
    times, closes = lk["BTC"]
    assert list(times) == [0, H] and list(closes) == [100.0, 110.0]  # sorted by open_time
