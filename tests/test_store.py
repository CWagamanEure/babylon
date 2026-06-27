import glob

import polars as pl

from babylon.data.models import L2Book, Trade
from babylon.data.store import _SCHEMAS, ParquetStore


def _book_row(coin, t, bids, asks, ver_num=None):
    return L2Book.from_ws(
        {
            "coin": coin,
            "time": t,
            "levels": [
                [{"px": str(p), "sz": str(s), "n": 1} for p, s in bids],
                [{"px": str(p), "sz": str(s), "n": 1} for p, s in asks],
            ],
        },
        ver_num=ver_num,
    ).to_row()


def test_schema_keys_match_to_row():
    # The store's explicit schemas must stay in lockstep with the models' rows.
    assert set(_SCHEMAS["l2Book"]) == set(
        _book_row("BTC", 1, [(100, 1)], [(102, 1)]).keys()
    )
    trade_row = Trade.from_ws(
        {"coin": "BTC", "side": "B", "px": "1", "sz": "1", "time": 1}
    ).to_row()
    assert set(_SCHEMAS["trades"]) == set(trade_row.keys())


def test_thin_book_then_full_book_does_not_crash(tmp_path):
    # Regression: empty-side rows first made polars infer Null and crash on the
    # first real float. Explicit schema must make this a no-op.
    store = ParquetStore(tmp_path, flush_every=10_000)
    for _ in range(50):
        store.write("l2Book", "BTC", _book_row("BTC", 1780272000000, [], []))
    for i in range(5):
        store.write("l2Book", "BTC", _book_row("BTC", 1780272001000 + i, [(100, 1)], [(102, 1)]))
    store.flush()
    df = pl.read_parquet(glob.glob(f"{tmp_path}/l2Book/BTC/**/*.parquet", recursive=True))
    assert df.height == 55
    assert df["best_bid"].dtype == pl.Float64


def test_partition_uses_event_time_not_wall_clock(tmp_path):
    # 1780272000000 ms = 2026-06-01 UTC. Must be filed under that day, not today.
    store = ParquetStore(tmp_path, flush_every=10_000)
    store.write("l2Book", "BTC", _book_row("BTC", 1780272000000, [(100, 1)], [(102, 1)]))
    store.flush()
    days = glob.glob(f"{tmp_path}/l2Book/BTC/*")
    assert [d.rsplit("/", 1)[-1] for d in days] == ["2026-06-01"]


def test_failed_flush_keeps_buffer(tmp_path, monkeypatch):
    store = ParquetStore(tmp_path, flush_every=10_000)
    store.write("l2Book", "BTC", _book_row("BTC", 1780272000000, [(100, 1)], [(102, 1)]))

    # Simulate a write failure; the buffer must survive (write-before-pop).
    import polars as _pl

    def boom(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(_pl.DataFrame, "write_parquet", boom)
    try:
        store.flush()
    except OSError:
        pass
    assert store._buffers[("l2Book", "BTC")]  # still buffered, not lost


def test_rows_split_across_event_days(tmp_path):
    store = ParquetStore(tmp_path, flush_every=10_000)
    store.write("l2Book", "BTC", _book_row("BTC", 1780272000000, [(100, 1)], [(102, 1)]))  # 06-01
    store.write("l2Book", "BTC", _book_row("BTC", 1780358400000, [(100, 1)], [(102, 1)]))  # 06-02
    store.flush()
    days = sorted(d.rsplit("/", 1)[-1] for d in glob.glob(f"{tmp_path}/l2Book/BTC/*"))
    assert days == ["2026-06-01", "2026-06-02"]
