"""Historical L2 order-book ingestion from Hyperliquid's public S3 archive.

The official ``hyperliquid-archive`` bucket exposes L2 book snapshots at::

    s3://hyperliquid-archive/market_data/{YYYYMMDD}/{hour}/l2Book/{coin}.lz4

Each object is an LZ4 frame that decompresses to newline-delimited JSON, one
snapshot per line::

    {"time": "<ISO ns>", "ver_num": 1, "raw": {"channel": "l2Book", "data": {...}}}

``raw.data`` is byte-for-byte the same shape as the live WebSocket ``l2Book``
payload, so snapshots parse through the same :class:`L2Book` model — historical
and live data land in one schema.

The bucket is **requester-pays**: downloads require AWS credentials and you pay
egress. Be deliberate about how wide a date range you request.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import boto3
import lz4.frame
from botocore.exceptions import BotoCoreError, ClientError

from babylon.data.models import L2Book
from babylon.data.store import ParquetStore
from babylon.logging import get_logger

log = get_logger("archive")

BUCKET = "hyperliquid-archive"
_MISSING = {"NoSuchKey", "404", "NotFound"}
# S3 error codes worth retrying with backoff (throttling / transient server).
_TRANSIENT = {
    "Throttling",
    "ThrottlingException",
    "SlowDown",
    "RequestTimeout",
    "RequestTimeoutException",
    "InternalError",
    "ServiceUnavailable",
    "500",
    "503",
}
_MAX_RETRIES = 5
_MAX_RETRY_SLEEP = 30.0


def daterange(start: str, end: str) -> Iterator[str]:
    """Yield inclusive ``YYYYMMDD`` strings from ``start`` to ``end``."""
    d0 = date.fromisoformat(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
    d1 = date.fromisoformat(f"{end[:4]}-{end[4:6]}-{end[6:8]}")
    if d1 < d0:
        raise ValueError(f"end {end} is before start {start}")
    cur = d0
    while cur <= d1:
        yield cur.strftime("%Y%m%d")
        cur += timedelta(days=1)


@dataclass
class BackfillStats:
    files: int = 0  # coin-hours that yielded at least one snapshot
    snapshots: int = 0  # total snapshots persisted
    empty_hours: int = 0  # coin-hours absent or with no usable data
    bad_lines: int = 0  # malformed JSON lines skipped


class HyperliquidArchive:
    def __init__(self, s3_client: Any = None) -> None:
        self._s3 = s3_client or boto3.client("s3")
        self._bad_lines = 0  # accumulated across the current backfill

    @staticmethod
    def l2_key(coin: str, day: str, hour: int) -> str:
        return f"market_data/{day}/{hour}/l2Book/{coin}.lz4"

    def list_coins(self, day: str, hour: int) -> list[str]:
        prefix = f"market_data/{day}/{hour}/l2Book/"
        paginator = self._s3.get_paginator("list_objects_v2")
        coins: list[str] = []
        for page in paginator.paginate(
            Bucket=BUCKET, Prefix=prefix, RequestPayer="requester"
        ):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if name.endswith(".lz4"):
                    coins.append(name[: -len(".lz4")])
        return coins

    def _get_object(self, key: str) -> bytes | None:
        """Fetch an object's bytes, retrying transient errors. ``None`` if absent."""
        delay = 1.0
        for attempt in range(_MAX_RETRIES):
            try:
                obj = self._s3.get_object(Bucket=BUCKET, Key=key, RequestPayer="requester")
                return obj["Body"].read()  # type: ignore[no-any-return]
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in _MISSING:
                    return None
                if code not in _TRANSIENT or attempt == _MAX_RETRIES - 1:
                    raise
                log.warning("archive.retry", key=key, code=code, attempt=attempt)
            except BotoCoreError as exc:  # network/connection layer
                if attempt == _MAX_RETRIES - 1:
                    raise
                log.warning("archive.retry", key=key, error=str(exc), attempt=attempt)
            time.sleep(delay)
            delay = min(delay * 2, _MAX_RETRY_SLEEP)
        return None

    def iter_l2_hour(self, coin: str, day: str, hour: int) -> Iterator[L2Book]:
        """Stream parsed L2 snapshots for one coin-hour, or nothing if absent.

        Corrupt objects and individual malformed lines are skipped and logged
        rather than aborting the whole backfill.
        """
        key = self.l2_key(coin, day, hour)
        raw = self._get_object(key)
        if raw is None:
            log.debug("archive.missing", key=key)
            return
        try:
            payload = lz4.frame.decompress(raw)
        except Exception as exc:  # noqa: BLE001 — corrupt object, skip the hour
            log.error("archive.decompress_failed", key=key, error=str(exc))
            return
        bad = 0
        for line in payload.split(b"\n"):
            if not line:
                continue
            try:
                rec = json.loads(line)
                yield L2Book.from_ws(rec["raw"]["data"], ver_num=rec.get("ver_num"))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                bad += 1
                log.debug("archive.bad_line", key=key, error=str(exc))
        if bad:
            self._bad_lines += bad
            log.warning("archive.bad_lines", key=key, count=bad)

    def backfill_l2(
        self,
        store: ParquetStore,
        coins: list[str],
        start: str,
        end: str,
        *,
        hours: Iterable[int] = range(24),
        max_levels: int = 20,
    ) -> BackfillStats:
        """Download, parse, and persist L2 snapshots to ``store`` over a range.

        Writes rows via :meth:`L2Book.to_row`, matching the live recorder's schema.
        """
        stats = BackfillStats()
        self._bad_lines = 0
        for day in daterange(start, end):
            for hour in hours:
                for coin in coins:
                    rows = 0
                    for book in self.iter_l2_hour(coin, day, hour):
                        store.write("l2Book", coin, book.to_row(max_levels))
                        rows += 1
                    if rows:
                        stats.files += 1
                        stats.snapshots += rows
                        log.debug("archive.hour", coin=coin, day=day, hour=hour, rows=rows)
                    else:
                        stats.empty_hours += 1
            log.info(
                "archive.day_done",
                day=day,
                files=stats.files,
                snapshots=stats.snapshots,
            )
        store.flush()
        stats.bad_lines = self._bad_lines
        return stats
