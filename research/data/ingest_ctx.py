"""Ingest Hyperliquid historical asset_ctxs → `data/raw/asset_ctx` (the research price/funding panel).

THE only writer of `data/raw/asset_ctx/`. Source: `s3://hyperliquid-archive/asset_ctxs/{YYYYMMDD}.csv.lz4`
(requester-pays, us-east-1) — one CSV per day, ~201 coins × per-minute. Mirrors the fills ingest
(`ingest.py`): Hive-partitioned parquet, atomic writes, idempotent/resumable via done-shards keyed on
`ASSET_CTX_SCHEMA_VERSION`. All 12 raw columns kept; numerics stay float64 (reference data — verified
bit-exact to the source; see schema.py). Note the archive trails "now" by ~8 days, so recent days 404
(recorded as `missing`, retried on a later run).

    python -m research.data.ingest_ctx day 20250801         # one day (stage-1 gate)
    python -m research.data.ingest_ctx month 202508          # one month
    python -m research.data.ingest_ctx range 20250801 20260629
    python -m research.data.ingest_ctx manifest              # fold shards → manifest.parquet + gap report

Crash-safe/idempotent: a day is done iff its `ctx.parquet` exists AND an `ok` shard records the current
`ASSET_CTX_SCHEMA_VERSION`. The part is written INTO the destination dir (never system temp — os.replace must
be intra-filesystem) under a dot-prefixed non-`.parquet` name, then atomically renamed. A `missing` (404) or
`failed` (exception) day writes a status shard so gaps are VISIBLE (never silent) and is retried next run.
One bad day never aborts the batch. Bump the schema version to force re-ingest on a contract change.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from . import schema

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "asset_ctx"
MANIFEST = RAW / "_manifest"
S3_PREFIX = "s3://hyperliquid-archive/asset_ctxs"
MAJORS = tuple(schema.MAJORS)
# the 12 raw source columns, in file order (time, coin, then the 10 numerics) — asserted per day.
EXPECTED_HEADER = ("time", "coin", *schema.ASSET_CTX_NUMERIC)


def _day_dir(day: str) -> Path:
    return RAW / f"month={day[:6]}" / f"day={day}"


def _shard_path(day: str) -> Path:
    return MANIFEST / f"{day}.json"


def _write_shard(day: str, payload: dict) -> None:
    MANIFEST.mkdir(parents=True, exist_ok=True)
    tmp = _shard_path(day).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, _shard_path(day))


def _is_done(day: str) -> bool:
    part = _day_dir(day) / "ctx.parquet"
    shard = _shard_path(day)
    if not (part.exists() and shard.exists()):
        return False
    try:
        s = json.loads(shard.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return s.get("status") == "ok" and s.get("schema_version") == schema.ASSET_CTX_SCHEMA_VERSION


def _copy_sql(csv: str, out: str) -> str:
    """COPY that pins EVERY numeric to DOUBLE (never trust per-day read_csv_auto inference — an
    all-integer sample window would type a column BIGINT and silently TRUNCATE later fractional values).
    `time`/`coin` forced VARCHAR so no TIMESTAMPTZ inference (avoids a pytz/tz drag). Column list is
    driven off the contract so writer and schema.py cannot diverge."""
    types = "{" + ", ".join(["'time': 'VARCHAR'", "'coin': 'VARCHAR'"]
                            + [f"'{c}': 'DOUBLE'" for c in schema.ASSET_CTX_NUMERIC]) + "}"
    numcols = ", ".join(schema.ASSET_CTX_NUMERIC)
    return f"""
    COPY (
      SELECT
        CAST(epoch_ms(strptime(time, '%Y-%m-%dT%H:%M:%SZ')) AS BIGINT) AS ts,
        time, coin, {numcols}
      FROM read_csv_auto('{csv}', header=true, types={types})
      ORDER BY coin, ts
    ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
    """


def ingest_day(day: str, force: bool = False) -> dict:
    if _is_done(day) and not force:
        return {"day": day, "status": "skip"}
    ddir = _day_dir(day)
    ddir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        lz4p = os.path.join(tmp, f"{day}.csv.lz4")
        dl = subprocess.run(
            ["aws", "s3", "cp", f"{S3_PREFIX}/{day}.csv.lz4", lz4p,
             "--request-payer", "requester", "--only-show-errors"],
            capture_output=True, text=True)
        if dl.returncode != 0:
            # a 404 is archive-lag / a genuine gap, not fatal: record it (visible) and retry next run.
            _write_shard(day, {"day": day, "status": "missing",
                               "schema_version": schema.ASSET_CTX_SCHEMA_VERSION,
                               "err": dl.stderr.strip()[:200]})
            return {"day": day, "status": "MISSING"}
        csvp = os.path.join(tmp, f"{day}.csv")
        subprocess.run(["lz4", "-d", "-f", lz4p, csvp], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # header assertion: fail loud on ANY drift (missing/renamed → we'd crash anyway; NEW column would
        # silently drop raw). Converts both into a controlled, recorded failure.
        with open(csvp, encoding="utf-8") as fh:
            hdr = tuple(fh.readline().strip().split(","))
        if hdr != EXPECTED_HEADER:
            raise RuntimeError(f"{day}: source header drift {hdr} != {EXPECTED_HEADER}")

        # part is written INTO the dest dir (intra-fs os.replace) under a non-`.parquet` tmp name so a
        # concurrent lake/manifest glob can never see a half-written file.
        part_tmp = ddir / f".ctx.parquet.tmp-{os.getpid()}"
        try:
            con = duckdb.connect()
            con.execute("PRAGMA threads=4")
            con.execute(_copy_sql(csvp, str(part_tmp)))
            P = f"read_parquet('{part_tmp}')"
            n, coins, ts_null, mn, mx = con.execute(
                f"SELECT count(*), count(DISTINCT coin), sum(CASE WHEN ts IS NULL THEN 1 ELSE 0 END),"
                f" min(ts), max(ts) FROM {P}").fetchone()
            major_counts = {c: con.execute(f"SELECT count(*) FROM {P} WHERE coin = '{c}'").fetchone()[0]
                            for c in MAJORS}
            null_expr = " + ".join(f"sum(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)"
                                   for c in schema.ASSET_CTX_NUMERIC)
            major_nulls = con.execute(f"SELECT {null_expr} FROM {P} WHERE coin IN {MAJORS}").fetchone()[0]
            all_nulls = con.execute(f"SELECT {null_expr} FROM {P}").fetchone()[0]
            con.close()
            # fail-loud invariants: a broken derived join-key, or a structurally missing major.
            if ts_null and ts_null > 0:
                raise RuntimeError(f"{day}: {ts_null} rows have NULL ts (time-format drift)")
            if any(v == 0 for v in major_counts.values()):
                raise RuntimeError(f"{day}: a major coin has 0 rows (corrupt day?): {major_counts}")
            os.replace(part_tmp, ddir / "ctx.parquet")
        finally:
            if part_tmp.exists():
                part_tmp.unlink()
    _write_shard(day, {"day": day, "status": "ok", "rows": n, "coins": coins,
                       "ts_min": mn, "ts_max": mx, "major_counts": major_counts,
                       "major_numeric_nulls": major_nulls, "all_numeric_nulls": all_nulls,
                       "schema_version": schema.ASSET_CTX_SCHEMA_VERSION})
    warn = "" if all(v == 1440 for v in major_counts.values()) else f"  ⚠ majors≠1440: {major_counts}"
    return {"day": day, "status": "ok", "rows": n, "coins": coins,
            "major_nulls": major_nulls, "all_nulls": all_nulls, "warn": warn}


def _daterange(start: str, end: str):
    d = datetime.strptime(start, "%Y%m%d").replace(tzinfo=timezone.utc)
    last = datetime.strptime(end, "%Y%m%d").replace(tzinfo=timezone.utc)
    while d <= last:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def _run(days: list[str], force: bool = False) -> None:
    ok = miss = fail = skip = 0
    for day in days:
        try:
            r = ingest_day(day, force=force)
        except Exception as e:  # ISOLATE: one bad day is a recorded failure, never a batch-killer.
            fail += 1
            _write_shard(day, {"day": day, "status": "failed", "error": str(e)[:300],
                               "schema_version": schema.ASSET_CTX_SCHEMA_VERSION})
            print(f"  FAIL {day}: {e}", flush=True)
            continue
        st = r["status"]
        if st == "ok":
            ok += 1
            print(f"  ok  {day}  rows={r['rows']:,} coins={r['coins']} "
                  f"major_nulls={r['major_nulls']} all_nulls={r['all_nulls']}{r['warn']}", flush=True)
        elif st == "skip":
            skip += 1
        else:
            miss += 1
            print(f"  MISSING {day}", flush=True)
    print(f"=== done: {ok} ingested, {skip} skipped, {miss} missing, {fail} failed (of {len(days)} days) ===")


def manifest_report() -> None:
    shards = sorted(MANIFEST.glob("*.json"))
    if not shards:
        print("no shards yet")
        return
    oks, missing, failed = [], [], []
    for s in shards:
        try:
            d = json.loads(s.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        {"ok": oks, "missing": missing, "failed": failed}.get(d.get("status"), oks).append(d)
    con = duckdb.connect()
    # fold ok shards into a single manifest.parquet (parity with the fills tape)
    if oks:
        con.execute("CREATE TABLE m AS SELECT * FROM (VALUES " + ",".join(
            f"('{d['day']}', {d['rows']}, {d['coins']}, {d['ts_min']}, {d['ts_max']}, "
            f"{d.get('major_numeric_nulls',0)}, {d.get('all_numeric_nulls',0)})" for d in oks)
            + ") AS t(day, rows, coins, ts_min, ts_max, major_numeric_nulls, all_numeric_nulls)")
        con.execute(f"COPY m TO '{RAW}/manifest.parquet' (FORMAT parquet)")
    lake_rows = con.execute(
        f"SELECT count(*) FROM read_parquet('{RAW}/month=*/day=*/*.parquet')").fetchone()[0] if oks else 0
    days = sorted(d["day"] for d in oks)
    print(f"ok={len(oks)} ({days[0]}..{days[-1]} )  missing={len(missing)}  failed={len(failed)}  "
          f"lake_rows={lake_rows:,}  schema={schema.ASSET_CTX_SCHEMA_VERSION}")
    if missing:
        print("  MISSING:", ", ".join(sorted(d["day"] for d in missing)))
    if failed:
        for d in failed:
            print(f"  FAILED {d['day']}: {d.get('error','')}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "manifest"
    force = "--force" in sys.argv
    if cmd == "day":
        _run([sys.argv[2]], force)
    elif cmd == "month":
        m = sys.argv[2]
        y, mo = int(m[:4]), int(m[4:6])
        nxt = datetime(y + (mo == 12), (mo % 12) + 1, 1, tzinfo=timezone.utc)
        _run(list(_daterange(f"{m}01", (nxt - timedelta(days=1)).strftime("%Y%m%d"))), force)
    elif cmd == "range":
        _run(list(_daterange(sys.argv[2], sys.argv[3])), force)
    elif cmd == "manifest":
        manifest_report()
    else:
        print(__doc__)
        sys.exit(1)
