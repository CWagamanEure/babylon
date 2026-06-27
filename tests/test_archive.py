import io
import json

import lz4.frame
import pytest
from botocore.exceptions import ClientError

from babylon.data.archive import HyperliquidArchive, daterange


def test_daterange_inclusive():
    assert list(daterange("20260101", "20260103")) == ["20260101", "20260102", "20260103"]
    assert list(daterange("20260101", "20260101")) == ["20260101"]


def test_daterange_rejects_backwards():
    with pytest.raises(ValueError):
        list(daterange("20260103", "20260101"))


def _l2_line(coin: str, ts: int, bid: str, ask: str) -> bytes:
    rec = {
        "time": "2026-06-01T00:00:13.264116654",
        "ver_num": 1,
        "raw": {
            "channel": "l2Book",
            "data": {
                "coin": coin,
                "time": ts,
                "levels": [[{"px": bid, "sz": "1", "n": 1}], [{"px": ask, "sz": "2", "n": 1}]],
            },
        },
    }
    return json.dumps(rec).encode()


class _FakeS3:
    """Minimal stand-in for the boto3 S3 client."""

    def __init__(self, key_to_body: dict[str, bytes]):
        self._bodies = key_to_body

    def get_object(self, Bucket, Key, RequestPayer):  # noqa: N803 — boto3 kwarg names
        if Key not in self._bodies:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self._bodies[Key])}


def test_iter_l2_hour_parses_frame():
    payload = b"\n".join(
        [_l2_line("BTC", 1, "100", "102"), _l2_line("BTC", 2, "101", "103"), b""]
    )
    key = "market_data/20260601/0/l2Book/BTC.lz4"
    s3 = _FakeS3({key: lz4.frame.compress(payload)})
    archive = HyperliquidArchive(s3_client=s3)

    books = list(archive.iter_l2_hour("BTC", "20260601", 0))
    assert len(books) == 2
    assert books[0].best_bid == 100 and books[0].best_ask == 102
    assert books[1].mid == 102  # (101 + 103) / 2

    row = books[0].to_row()
    assert row["bid_px"] == [100.0]
    assert row["ask_sz"] == [2.0]


def test_iter_l2_hour_missing_key_yields_nothing():
    archive = HyperliquidArchive(s3_client=_FakeS3({}))
    assert list(archive.iter_l2_hour("DOGE", "20260601", 5)) == []


def test_l2_key_format():
    assert (
        HyperliquidArchive.l2_key("BTC", "20260601", 9)
        == "market_data/20260601/9/l2Book/BTC.lz4"
    )


def test_ver_num_is_retained():
    payload = _l2_line("BTC", 1, "100", "102")
    key = "market_data/20260601/0/l2Book/BTC.lz4"
    archive = HyperliquidArchive(s3_client=_FakeS3({key: lz4.frame.compress(payload)}))
    book = next(iter(archive.iter_l2_hour("BTC", "20260601", 0)))
    assert book.ver_num == 1  # _l2_line stamps ver_num=1


def test_bad_line_is_skipped_not_fatal():
    payload = b"\n".join(
        [_l2_line("BTC", 1, "100", "102"), b"{garbage not json", _l2_line("BTC", 2, "101", "103")]
    )
    key = "market_data/20260601/0/l2Book/BTC.lz4"
    archive = HyperliquidArchive(s3_client=_FakeS3({key: lz4.frame.compress(payload)}))
    books = list(archive.iter_l2_hour("BTC", "20260601", 0))
    assert len(books) == 2  # the malformed middle line is skipped
    assert archive._bad_lines == 1


class _FlakyS3(_FakeS3):
    """Throws a transient error N times before succeeding."""

    def __init__(self, key_to_body, fail_times):
        super().__init__(key_to_body)
        self._left = fail_times

    def get_object(self, Bucket, Key, RequestPayer):  # noqa: N803
        if self._left > 0:
            self._left -= 1
            raise ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")
        return super().get_object(Bucket=Bucket, Key=Key, RequestPayer=RequestPayer)


def test_transient_error_is_retried(monkeypatch):
    monkeypatch.setattr("babylon.data.archive.time.sleep", lambda _s: None)
    payload = _l2_line("BTC", 1, "100", "102")
    key = "market_data/20260601/0/l2Book/BTC.lz4"
    s3 = _FlakyS3({key: lz4.frame.compress(payload)}, fail_times=2)
    archive = HyperliquidArchive(s3_client=s3)
    books = list(archive.iter_l2_hour("BTC", "20260601", 0))
    assert len(books) == 1  # succeeded after 2 retries


def test_persistent_error_raises(monkeypatch):
    monkeypatch.setattr("babylon.data.archive.time.sleep", lambda _s: None)
    s3 = _FlakyS3({}, fail_times=99)
    archive = HyperliquidArchive(s3_client=s3)
    import pytest

    with pytest.raises(ClientError):
        list(archive.iter_l2_hour("BTC", "20260601", 0))
