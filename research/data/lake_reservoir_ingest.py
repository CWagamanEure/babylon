"""Reservoir → incerto-datalake-v1 streaming ingest (runs STANDALONE on a DO droplet; no repo imports).

Per day: HEAD source (etag) → skip if lake manifest matches → download (~417MB, requester-pays) →
re-HEAD (mutable-source TOCTOU guard) → duckdb project/filter to perp per-fill parquet + two derived
aggregates (+ partial-day + row-accounting guards) → upload to Spaces → manifest LAST (crash-safe).
Disk stays <2GB. Idempotent + mutable-source-safe (etag+schema+commit keyed). Re-run after any crash.

Audited 2026-07-16 (correctness + data-integrity agents): DECIMAL widening exact (notional lands
DECIMAL(38,20), overflow raises, never wraps); epoch_ms(TIMESTAMPTZ) is instant-based and session-tz-safe
(the older RESERVOIR_ALT_FILLS_SPEC §0 "never epoch_ms" rule was wrong — the naive TIMESTAMP cast is the
tz-corrupting one); uint64 ids pass through UBIGINT. This version adds the audit's provenance fixes:
404-vs-transient classification, status manifests for gaps, retries + nonzero exit on errors, post-download
etag, rows_source/ts_min/ts_max accounting, code_commit keying, force deletes the manifest first, verify mode.

Lake layout (see research/data/DATALAKE_SPEC.md):
  source=hyperliquid_reservoir/dataset=perp_fills/date=YYYY-MM-DD/fills.parquet          (full per-fill)
  source=hyperliquid_reservoir/dataset=perp_fills_manifest/date=YYYY-MM-DD/manifest.json (status: ok|source_missing)
  source=babylon_derived/dataset=alt_universe_wallet_coin_day/date=YYYY-MM-DD/part.parquet
  source=babylon_derived/dataset=alt_universe_open_entries/date=YYYY-MM-DD/part.parquet

Env (/root/.lake_env): AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (Reservoir requester-pays read),
SPACES_KEY, SPACES_SECRET, SPACES_ENDPOINT, SPACES_BUCKET, LAKE_CODE_COMMIT (stamped at deploy).

    python3 lake_reservoir_ingest.py day    20260601 [--force]
    python3 lake_reservoir_ingest.py range  20250801 20260630 [--force]
    python3 lake_reservoir_ingest.py verify 20250801 20260630   # HEAD-only drift report, no downloads
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import duckdb

SRC_BUCKET = "hydromancer-reservoir"
SRC_REGION = "ap-northeast-1"
SRC_PREFIX = "by_dex/hyperliquid/fills/perp/all"
SCHEMA_VERSION = 2
CODE_COMMIT = os.environ.get("LAKE_CODE_COMMIT", "unknown")
DUCK_MEM = "1200MB"          # audited guidance for this workload on small hosts
DUCK_THREADS = 1
RETRIES = 2                  # per-day transient-failure retries
TMP_ROOT = Path("/root/tmp_ingest")
DAY_MS = 86_400_000
EDGE_MS = 900_000            # partial-day guard: first fill <00:15, last >23:45 UTC

SPACES = {
    "AWS_ACCESS_KEY_ID": os.environ["SPACES_KEY"],
    "AWS_SECRET_ACCESS_KEY": os.environ["SPACES_SECRET"],
}
EP = os.environ["SPACES_ENDPOINT"]
LAKE = os.environ["SPACES_BUCKET"]


class Transient(Exception):
    """Non-404 source/S3 failure — retry, then count as error (never a silent gap)."""


def _iso(day: str) -> str:
    if not re.fullmatch(r"\d{8}", day):
        raise SystemExit(f"bad day arg {day!r} (want YYYYMMDD)")
    return f"{day[:4]}-{day[4:6]}-{day[6:8]}"


def _day_bounds_ms(day: str) -> tuple[int, int]:
    d = datetime(int(day[:4]), int(day[4:6]), int(day[6:8]), tzinfo=timezone.utc)
    t0 = int(d.timestamp() * 1000)
    return t0, t0 + DAY_MS - 1


def _aws(args, env_extra=None, check=True):
    env = {**os.environ, **(env_extra or {})}
    r = subprocess.run(["aws", *args], capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise Transient(f"aws {args[0]} {args[1] if len(args) > 1 else ''}: {r.stderr.strip()[:300]}")
    return r


def _src_head(day: str):
    """None = confirmed 404 (day absent at source); raises Transient on any other failure."""
    r = _aws(["s3api", "head-object", "--bucket", SRC_BUCKET,
              "--key", f"{SRC_PREFIX}/date={_iso(day)}/fills.parquet",
              "--request-payer", "requester", "--region", SRC_REGION], check=False)
    if r.returncode != 0:
        err = r.stderr.strip()
        if "(404)" in err or "Not Found" in err:
            return None
        raise Transient(f"head {day}: {err[:300]}")
    h = json.loads(r.stdout)
    return {"etag": h["ETag"].strip('"'), "size": h["ContentLength"]}


def _manifest_key(day: str) -> str:
    return f"source=hyperliquid_reservoir/dataset=perp_fills_manifest/date={_iso(day)}/manifest.json"


def _lake_manifest(day: str):
    r = _aws(["s3", "cp", f"s3://{LAKE}/{_manifest_key(day)}", "-", "--endpoint-url", EP],
             env_extra=SPACES, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None    # corrupt manifest → treat as absent → reprocess


def _upload(local: Path, key: str):
    _aws(["s3", "cp", str(local), f"s3://{LAKE}/{key}", "--endpoint-url", EP, "--quiet"],
         env_extra=SPACES)


def _put_manifest(day: str, payload: dict, td: Path):
    man = td / "manifest.json"
    man.write_text(json.dumps({**payload, "schema_version": SCHEMA_VERSION, "code_commit": CODE_COMMIT,
                               "created_utc": datetime.now(timezone.utc).isoformat()}))
    _upload(man, _manifest_key(day))


def _process_day(day: str, force: bool) -> str:
    head = _src_head(day)
    d = _iso(day)
    TMP_ROOT.mkdir(exist_ok=True)
    if head is None:
        with tempfile.TemporaryDirectory(prefix="lake_", dir=TMP_ROOT) as td:
            _put_manifest(day, {"day": day, "status": "source_missing"}, Path(td))
        return f"absent {day} (recorded)"
    m = _lake_manifest(day)
    if (not force and m and m.get("status") == "ok" and m.get("source_etag") == head["etag"]
            and m.get("schema_version") == SCHEMA_VERSION and m.get("code_commit") == CODE_COMMIT):
        return f"skip {day} (etag+schema+commit match)"
    if force and m:
        _aws(["s3", "rm", f"s3://{LAKE}/{_manifest_key(day)}", "--endpoint-url", EP, "--quiet"],
             env_extra=SPACES, check=False)   # close the force-crash window: no stale manifest can gate a mix
    with tempfile.TemporaryDirectory(prefix="lake_", dir=TMP_ROOT) as tds:
        td = Path(tds)
        raw = td / "raw.parquet"
        _aws(["s3", "cp", f"s3://{SRC_BUCKET}/{SRC_PREFIX}/date={d}/fills.parquet", str(raw),
              "--request-payer", "requester", "--region", SRC_REGION, "--quiet"])
        head2 = _src_head(day)                # TOCTOU guard: etag of what we actually (likely) downloaded
        if head2 is None:
            raise Transient(f"{day}: source vanished mid-download")
        if head2["size"] != raw.stat().st_size:
            raise Transient(f"{day}: downloaded size {raw.stat().st_size} != source {head2['size']}")
        con = duckdb.connect()
        con.execute(f"SET memory_limit='{DUCK_MEM}'; SET threads={DUCK_THREADS}; "
                    f"SET temp_directory='{tds}/duck_spill'")
        rows_source = con.execute(
            f"SELECT count(*) FROM read_parquet('{raw.as_posix()}')").fetchone()[0]
        fills, wcd, ope = td / "fills.parquet", td / "wcd.parquet", td / "open.parquet"
        # full per-fill (perp only), projected — exact decimals + uint64 preserved end-to-end
        con.execute(f"""COPY (
            SELECT f.address AS wallet, f.base_symbol AS coin, epoch_ms(f.timestamp) AS ts,
                   f.price AS px, f.size AS sz, f.side, f.direction, f.start_position,
                   f.crossed, f.realized_pnl, f.fee, f.builder_fee,
                   f.is_liquidation, f.liquidation_mark_px, f.liquidation_method,
                   f.order_id, f.trade_id, f.twap_id, f.tx_hash
            FROM read_parquet('{raw.as_posix()}') f
            WHERE f.asset_class = 'perp'
        ) TO '{fills.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        n_f, ts_min, ts_max = con.execute(
            f"SELECT count(*), min(ts), max(ts) FROM read_parquet('{fills.as_posix()}')").fetchone()
        lo, hi = _day_bounds_ms(day)
        if n_f == 0 or ts_min > lo + EDGE_MS or ts_max < hi - EDGE_MS:
            raise Transient(f"{day}: partial-day source (n={n_f}, ts_min={ts_min}, ts_max={ts_max})")
        con.execute(f"""COPY (
            SELECT wallet, coin, {int(day)} AS day,
                   count(*) AS n_fills,
                   count(*) FILTER (WHERE crossed) AS n_taker,
                   SUM(realized_pnl) AS pnl, SUM(fee) AS fee, SUM(builder_fee) AS builder_fee,
                   SUM(abs(sz) * px) AS notional,
                   count(*) FILTER (WHERE crossed AND direction IN ('Open Long','Open Short')
                                      AND start_position = 0) AS n_open_flat,
                   count(*) FILTER (WHERE is_liquidation) AS n_liq
            FROM read_parquet('{fills.as_posix()}')
            GROUP BY 1, 2, 3
        ) TO '{wcd.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        con.execute(f"""COPY (
            SELECT wallet, coin, ts,
                   CASE WHEN direction = 'Open Long' THEN 1 ELSE -1 END AS dir_sign,
                   abs(sz) AS abs_sz, px, abs(sz) * px AS notl, fee
            FROM read_parquet('{fills.as_posix()}')
            WHERE crossed AND direction IN ('Open Long','Open Short') AND start_position = 0
        ) TO '{ope.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        n_w = con.execute(f"SELECT count(*) FROM read_parquet('{wcd.as_posix()}')").fetchone()[0]
        n_o = con.execute(f"SELECT count(*) FROM read_parquet('{ope.as_posix()}')").fetchone()[0]
        con.close()
        _upload(fills, f"source=hyperliquid_reservoir/dataset=perp_fills/date={d}/fills.parquet")
        _upload(wcd, f"source=babylon_derived/dataset=alt_universe_wallet_coin_day/date={d}/part.parquet")
        _upload(ope, f"source=babylon_derived/dataset=alt_universe_open_entries/date={d}/part.parquet")
        _put_manifest(day, {
            "day": day, "status": "ok",
            "source_key": f"{SRC_PREFIX}/date={d}/fills.parquet",
            "source_etag": head2["etag"], "source_size": head2["size"],
            "rows_source": rows_source, "rows_fills": n_f,
            "rows_dropped_nonperp": rows_source - n_f,
            "ts_min": ts_min, "ts_max": ts_max,
            "rows_wallet_coin_day": n_w, "rows_open_entries": n_o,
            "bytes_fills": fills.stat().st_size,
        }, td)
    return f"done {day}: {n_f:,} fills ({rows_source - n_f} nonperp) | {n_w:,} wcd | {n_o:,} opens"


def ingest_day(day: str, force: bool = False) -> tuple[str, str]:
    """Returns (status, message); status ∈ done|skip|absent|error."""
    t0 = time.time()
    last = ""
    for attempt in range(RETRIES + 1):
        try:
            msg = _process_day(day, force)
            return msg.split()[0].replace("(recorded)", "absent"), f"{msg} | {time.time()-t0:.0f}s"
        except Transient as e:
            last = str(e)
            time.sleep(5 * (attempt + 1))
    return "error", f"ERROR {day} after {RETRIES + 1} tries: {last[:300]}"


def _days(start: str, end: str):
    d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    if d > e:
        raise SystemExit(f"start {start} > end {end}")
    while d <= e:
        yield d.strftime("%Y%m%d"); d += timedelta(days=1)


def verify(start: str, end: str) -> int:
    """HEAD-only drift/coverage report vs lake manifests. No downloads."""
    bad = 0
    for day in _days(start, end):
        m = _lake_manifest(day)
        try:
            head = _src_head(day)
        except Transient as e:
            print(f"  ERR  {day}: {e}", flush=True); bad += 1; continue
        if m is None:
            print(f"  GAP  {day}: no manifest (never ingested)", flush=True); bad += 1
        elif m.get("status") == "source_missing":
            if head is not None:
                print(f"  NEW  {day}: source appeared after recorded absent", flush=True); bad += 1
        elif head is None:
            print(f"  GONE {day}: ingested but source now 404", flush=True)
        elif (m.get("source_etag") != head["etag"] or m.get("schema_version") != SCHEMA_VERSION
              or m.get("code_commit") != CODE_COMMIT):
            print(f"  DRIFT {day}: etag/schema/commit mismatch — re-ingest", flush=True); bad += 1
    print(f"verify: {bad} day(s) need attention", flush=True)
    return 0 if bad == 0 else 1


def main(argv):
    force = "--force" in argv
    if argv and argv[0] == "day":
        st, msg = ingest_day(argv[1], force)
        print(msg, flush=True)
        return 0 if st != "error" else 1
    if argv and argv[0] == "range":
        counts = {}
        for day in _days(argv[1], argv[2]):
            st, msg = ingest_day(day, force)
            counts[st] = counts.get(st, 0) + 1
            print(f"  {msg}", flush=True)
        print(f"summary: {counts}", flush=True)
        return 1 if counts.get("error", 0) else 0
    if argv and argv[0] == "verify":
        return verify(argv[1], argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
