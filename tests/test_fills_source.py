import asyncio

import polars as pl

from babylon.follow.fills_source import (
    ParquetFillsProvider, RestFillsProvider, fills_to_frame, page_fills,
)


def _raw(tid, t, coin="BTC"):
    return {"time": t, "coin": coin, "px": "100.5", "sz": "1.0", "side": "B",
            "crossed": True, "startPosition": "0.0", "hash": "0xabc", "tid": tid}


class _FakeInfo:
    def __init__(self, fills): self._f = sorted(fills, key=lambda x: x["time"])
    async def user_fills_by_time(self, addr, start, end):
        return [f for f in self._f if start <= f["time"] <= end][:2000]


def test_fills_to_frame_maps_dedups_sorts():
    df = fills_to_frame([_raw(2, 200), _raw(1, 100), _raw(2, 200)])  # dup tid 2
    assert df.height == 2 and df["time"].to_list() == [100, 200]     # deduped + sorted
    assert df["px"].dtype == pl.Float64 and df["crossed"].dtype == pl.Boolean
    assert df["tid"].to_list() == [1, 2]


def test_fills_to_frame_empty():
    df = fills_to_frame([])
    assert df.height == 0 and set(df.columns) >= {"time", "coin", "px", "tid"}


def test_page_fills_paginates_past_cap():
    fills = [_raw(i, i) for i in range(2500)]                        # 2500 distinct times
    raw = asyncio.run(page_fills(_FakeInfo(fills), "w", 0, 10_000))
    assert fills_to_frame(raw).height == 2500                        # all retrieved via paging


def test_page_fills_under_cap_single_call():
    raw = asyncio.run(page_fills(_FakeInfo([_raw(i, i) for i in range(50)]), "w", 0, 10_000))
    assert fills_to_frame(raw).height == 50


def test_rest_provider_prefetch_then_sync_read():
    info = _FakeInfo([_raw(1, 100), _raw(2, 500), _raw(3, 5000)])
    prov = RestFillsProvider(info)
    asyncio.run(prov.prefetch(["w"], 0, 10_000))
    full = prov("w", 0, 10_000)
    assert full.height == 3
    windowed = prov("w", 200, 1000)                                 # sync filter to a sub-window
    assert windowed.height == 1 and windowed["tid"].to_list() == [2]
    assert prov("unknown", 0, 10_000).height == 0                   # missing wallet → empty


def test_parquet_provider(tmp_path):
    fills_to_frame([_raw(1, 100), _raw(2, 9000)]).write_parquet(tmp_path / "w.parquet")
    prov = ParquetFillsProvider(tmp_path)
    assert prov("w", 0, 10_000).height == 2
    assert prov("w", 0, 1000).height == 1                           # window filter
    assert prov("missing", 0, 10_000).height == 0
