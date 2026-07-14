"""Streaming restore of Hyperliquid `node_fills_by_block` → the authoritative majors fill tape.

Promoted from scratchpad per docs/DATA_ARCHITECTURE.md (the crash-lost `full_backfill.py`), rebuilt
faithfully from research/markout_study/discovery/RESTORE_PLAN_v1.md §1–2. This is the ONLY writer of
`data/raw/fills/` — the immutable, archive-sourced tape the frozen Gate-A pipeline consumes.

Per hourly S3 object (`s3://hl-mainnet-node-data/node_fills_by_block/hourly/YYYYMMDD/{H}.lz4`,
requester-pays, us-east-1):
  1. `aws s3 cp` → `lz4 -d` → parse line-delimited block JSON (stream-and-discard; peak disk < 1 GB);
  2. keep only coin ∈ {BTC,ETH,SOL,HYPE}; retain EVERY per-user fill (maker AND taker — `crossed` is
     metadata, not a drop filter); counterparties stay as SEPARATE rows, never paired/collapsed;
  3. project the exact-decimal schema (schema.PART_COLUMNS) — monetary/size fields kept as ORIGINAL
     STRINGS (float is never authoritative); nulls preserved, never zero-filled;
  4. fail-loud: any null frozen-required field (schema.REQUIRED_FIELDS) on a retained row aborts the
     object (no silent partial);
  5. write ONE atomic parquet part `month=YYYYMM/day=YYYYMMDD/hourHH.parquet` (tmp-write + os.replace);
  6. write a per-object manifest shard; discard raw bytes.

Resumable + idempotent: an object is skipped iff its part exists AND a manifest shard records
status=done with the current SCHEMA_VERSION and code_commit. Atomic rename means a killed process
never leaves a half-part that reads as complete.

    python -m research.data.ingest hour  20250801 12      # one object (stage-1 gate)
    python -m research.data.ingest day   20250801         # 24 objects
    python -m research.data.ingest month 202508           # one month (~744 objects)
    python -m research.data.ingest range 202508 202606    # the full 2025-08 … 2026-06 window
    python -m research.data.ingest manifest               # consolidate shards → manifest.parquet + report
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import schema

# ---- fixed source + local layout -------------------------------------------------------------
S3_PREFIX = "s3://hl-mainnet-node-data/node_fills_by_block/hourly"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
FILLS_DIR = DATA_DIR / "raw" / "fills"          # month=*/day=*/hourHH.parquet land here
MANIFEST_DIR = FILLS_DIR / "_manifest"          # per-object shards (underscore ⇒ skipped by leaf glob)
LZ4_BIN = os.environ.get("LZ4_BIN", "lz4")      # /opt/miniconda3/bin/lz4 on this box
MAJORS = set(schema.MAJORS)

# pyarrow schema for the 24 physical columns (month/day come from the Hive path).
_STR = pa.string()
_I64 = pa.int64()
_COL_TYPE = {c: _I64 for c in ("ts", "oid", "tid", "block_number", "event_index")}
_COL_TYPE["crossed"] = pa.bool_()
PART_SCHEMA = pa.schema([(c, _COL_TYPE.get(c, _STR)) for c in schema.PART_COLUMNS])


def _code_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else "nogit"
    except Exception:
        return "nogit"


CODE_COMMIT = _code_commit()


class HardError(Exception):
    """Frozen-required field null on a retained row, or source-row-key collision — abort the object."""


# ---- object identity / resume ----------------------------------------------------------------
def _part_path(day: str, hh: int) -> Path:
    month = day[:6]
    return FILLS_DIR / f"month={month}" / f"day={day}" / f"hour{hh:02d}.parquet"


def _shard_path(day: str, hh: int) -> Path:
    return MANIFEST_DIR / f"{day}_{hh:02d}.json"


def _object_key(day: str, hh: int) -> str:
    return f"{S3_PREFIX}/{day}/{hh}.lz4"


def _is_done(day: str, hh: int) -> bool:
    """Done iff the part exists AND a fresh (same schema_version + code_commit) done-shard records it."""
    part, shard = _part_path(day, hh), _shard_path(day, hh)
    if not (part.exists() and shard.exists()):
        return False
    try:
        m = json.loads(shard.read_text())
    except Exception:
        return False
    return (m.get("status") == "done"
            and m.get("schema_version") == schema.SCHEMA_VERSION
            and m.get("code_commit") == CODE_COMMIT)


def _write_atomic(path: Path, write_fn) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    try:
        write_fn(tmp)
        os.replace(tmp, path)                        # atomic on same filesystem
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _write_shard(day: str, hh: int, row: dict) -> None:
    _write_atomic(_shard_path(day, hh), lambda p: p.write_text(json.dumps(row)))


# ---- S3 fetch + parse ------------------------------------------------------------------------
def _download(key: str, tmpdir: Path) -> tuple[Path, int] | None:
    """cp the object to a temp .lz4. Returns (path, size_bytes) or None on a MISS (absent/transient)."""
    lz = tmpdir / "obj.lz4"
    r = subprocess.run(["aws", "s3", "cp", key, str(lz), "--request-payer", "requester", "--quiet"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not lz.exists():
        sys.stderr.write(f"  MISS {key}: {r.stderr.strip()[:100]}\n")
        return None
    return lz, lz.stat().st_size


def _decompress(lz: Path, tmpdir: Path) -> Path:
    txt = tmpdir / "obj.txt"
    subprocess.run([LZ4_BIN, "-d", "-f", str(lz), str(txt)], capture_output=True, check=True)
    lz.unlink(missing_ok=True)
    return txt


def _parse_object(txt: Path, src_object: str) -> tuple[dict, dict]:
    """Stream blocks → columnar dict of retained major rows + a stats dict.

    event_index is a globally-increasing counter over EVERY event in the object (block order, then
    event order) — assigned before the majors filter, so it is the true positional row identity and
    (src_object, block_number, event_index) is unique per object by construction (asserted)."""
    cols: dict[str, list] = {c: [] for c in schema.PART_COLUMNS}
    decoded_rows = 0
    hard_errors = 0
    ts_min = ts_max = None
    idx = 0
    with open(txt) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                block = json.loads(ln)
            except json.JSONDecodeError:
                continue
            bn = block.get("block_number")
            bt = block.get("block_time")
            lt = block.get("local_time")
            events = block.get("events") or []
            for addr, fl in events:
                ei = idx
                idx += 1
                decoded_rows += 1
                coin = fl.get("coin")
                if coin not in MAJORS:
                    continue
                liq = fl.get("liquidation")
                row = {
                    "wallet": addr, "coin": coin, "ts": fl.get("time"),
                    "px": fl.get("px"), "sz": fl.get("sz"), "side": fl.get("side"),
                    "start_position": fl.get("startPosition"), "dir": fl.get("dir"),
                    "closed_pnl": fl.get("closedPnl"), "hash": fl.get("hash"),
                    "oid": fl.get("oid"), "tid": fl.get("tid"), "cloid": fl.get("cloid"),
                    "crossed": fl.get("crossed"), "fee": fl.get("fee"),
                    "fee_token": fl.get("feeToken"),
                    "liq_user": (liq or {}).get("liquidatedUser"),
                    "liq_method": (liq or {}).get("method"),
                    "liq_mark_px": (liq or {}).get("markPx"),
                    "builder": fl.get("builder"), "builder_fee": fl.get("builderFee"),
                    "src_object": src_object, "block_number": bn,
                    "block_time": bt, "local_time": lt,
                    "event_index": ei,
                }
                for f in schema.REQUIRED_FIELDS:
                    if row[f] is None:
                        hard_errors += 1
                        raise HardError(
                            f"null required field '{f}' at "
                            f"(src_object={src_object}, block_number={bn}, event_index={ei})")
                t = row["ts"]
                ts_min = t if ts_min is None else min(ts_min, t)
                ts_max = t if ts_max is None else max(ts_max, t)
                for k, v in row.items():
                    cols[k].append(v)
    # source-row-key uniqueness (RESTORE §2/§6): unique per object by event_index, asserted.
    keys = set(zip(cols["block_number"], cols["event_index"], cols["wallet"], cols["tid"]))
    if len(keys) != len(cols["event_index"]):
        raise HardError(f"source-row-key collision in {src_object}")
    stats = {"decoded_rows": decoded_rows, "retained_major_rows": len(cols["event_index"]),
             "ts_min": ts_min, "ts_max": ts_max, "hard_errors": hard_errors}
    return cols, stats


def _write_part(cols: dict, day: str, hh: int) -> None:
    table = pa.table({c: pa.array(cols[c], type=PART_SCHEMA.field(c).type)
                      for c in schema.PART_COLUMNS}, schema=PART_SCHEMA)
    _write_atomic(_part_path(day, hh), lambda p: pq.write_table(table, p, compression="zstd"))


# ---- per-object driver -----------------------------------------------------------------------
def ingest_hour(day: str, hh: int, force: bool = False) -> dict:
    """Ingest one hourly object end-to-end. Returns its manifest row (also persisted as a shard)."""
    key = _object_key(day, hh)
    if not force and _is_done(day, hh):
        return {"object_key": key, "status": "skipped"}
    base = {"object_key": key, "expected": True, "size_bytes": None, "decoded_rows": 0,
            "retained_major_rows": 0, "ts_min": None, "ts_max": None, "hard_errors": 0,
            "schema_version": schema.SCHEMA_VERSION, "code_commit": CODE_COMMIT}
    with tempfile.TemporaryDirectory(prefix="fills_ingest_") as td:
        tmpdir = Path(td)
        got = _download(key, tmpdir)
        if got is None:
            row = {**base, "status": "missing"}
            _write_shard(day, hh, row)
            return row
        lz, size = got
        base["size_bytes"] = size
        try:
            txt = _decompress(lz, tmpdir)
            cols, stats = _parse_object(txt, src_object=key)
        except (HardError, subprocess.CalledProcessError) as e:
            row = {**base, "status": "failed", "error": str(e)[:200]}
            _write_shard(day, hh, row)
            sys.stderr.write(f"  FAILED {key}: {e}\n")
            return row
        _write_part(cols, day, hh)                   # part first…
        row = {**base, **stats, "status": "done"}
        _write_shard(day, hh, row)                   # …then the done-shard (crash-safe ordering)
        return row


# ---- range helpers ---------------------------------------------------------------------------
def _days_in_month(month: str):
    y, m = int(month[:4]), int(month[4:6])
    d = datetime(y, m, 1, tzinfo=UTC)
    while d.month == m:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def _months_in_range(start: str, end: str):
    y, m = int(start[:4]), int(start[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    while (y, m) <= (ey, em):
        yield f"{y:04d}{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _ingest_hour_star(args):
    """Picklable entry for the process pool: (day, hh, force) → manifest row."""
    return ingest_hour(*args)


def _run_objects(objects: list[tuple[str, int]], workers: int, force: bool,
                 progress_every: int = 24) -> tuple[Counter, int]:
    """Ingest a list of (day, hh) objects, sequential or via a process pool. Embarrassingly parallel —
    each object writes its own part + shard, so there is no shared mutable state / no contention."""
    agg: Counter = Counter()
    total_rows = 0
    n = len(objects)
    if workers and workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_ingest_hour_star, (d, h, force)) for d, h in objects]
            for i, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                agg[r.get("status", "done")] += 1
                total_rows += r.get("retained_major_rows", 0) or 0
                if i % progress_every == 0 or i == n:
                    sys.stderr.write(f"    {i}/{n} objects | {total_rows:,} major fills | "
                                     f"{dict(agg)}\n")
                    sys.stderr.flush()
    else:
        for i, (d, h) in enumerate(objects, 1):
            r = ingest_hour(d, h, force=force)
            agg[r.get("status", "done")] += 1
            total_rows += r.get("retained_major_rows", 0) or 0
            if i % progress_every == 0 or i == n:
                sys.stderr.write(f"    {i}/{n} objects | {total_rows:,} major fills | {dict(agg)}\n")
                sys.stderr.flush()
    return agg, total_rows


def ingest_day(day: str, force: bool = False, workers: int = 1) -> dict:
    objects = [(day, hh) for hh in range(24)]
    agg, rows = _run_objects(objects, workers, force)
    sys.stderr.write(f"  {day}: {rows:,} major fills ({dict(agg)})\n")
    sys.stderr.flush()
    return {"retained_major_rows": rows, **agg}


def ingest_month(month: str, force: bool = False, workers: int = 1) -> dict:
    print(f"=== ingest month {month} → {FILLS_DIR}  workers={workers}  "
          f"({datetime.now(UTC):%Y-%m-%d %H:%M} UTC) ===", flush=True)
    objects = [(day, hh) for day in _days_in_month(month) for hh in range(24)]
    agg, rows = _run_objects(objects, workers, force)
    print(f"=== month {month} DONE: {rows:,} major fills | {dict(agg)} ===", flush=True)
    return {"month": month, "retained_major_rows": rows, **agg}


def ingest_range(start: str, end: str, force: bool = False, workers: int = 1) -> None:
    for month in _months_in_range(start, end):
        ingest_month(month, force=force, workers=workers)
    consolidate_manifest()


# ---- manifest consolidation + completeness ---------------------------------------------------
def consolidate_manifest() -> Path:
    """Fold per-object shards into data/raw/fills/manifest.parquet and print a completeness report."""
    rows = []
    for shard in sorted(MANIFEST_DIR.glob("*.json")) if MANIFEST_DIR.exists() else []:
        try:
            rows.append(json.loads(shard.read_text()))
        except Exception:
            continue
    cols = ["object_key", "expected", "status", "size_bytes", "decoded_rows",
            "retained_major_rows", "ts_min", "ts_max", "hard_errors",
            "schema_version", "code_commit"]
    table = pa.table({c: [r.get(c) for r in rows] for c in cols}) if rows else pa.table(
        {c: pa.array([], type=pa.string()) for c in cols})
    out = FILLS_DIR / "manifest.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    by_status: dict[str, int] = {}
    total_rows = 0
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
        total_rows += r.get("retained_major_rows", 0) or 0
    print(f"[manifest] {len(rows)} objects → {out}")
    print(f"[manifest] status: {by_status}")
    print(f"[manifest] retained major fills: {total_rows:,}")
    bad = [r["object_key"] for r in rows if r.get("status") in ("missing", "failed")]
    if bad:
        print(f"[manifest] {len(bad)} missing/failed objects (re-run to retry):")
        for k in bad[:20]:
            print(f"    {k}")
    return out


# ---- CLI -------------------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    force = "--force" in rest
    workers = 1
    kept = []
    for a in rest:
        if a == "--force":
            continue
        if a.startswith("--workers="):
            workers = int(a.split("=", 1)[1])
        else:
            kept.append(a)
    rest = kept
    if cmd == "hour":
        print(ingest_hour(rest[0], int(rest[1]), force=force))
    elif cmd == "day":
        ingest_day(rest[0], force=force, workers=workers)
    elif cmd == "month":
        ingest_month(rest[0], force=force, workers=workers)
        consolidate_manifest()
    elif cmd == "range":
        ingest_range(rest[0], rest[1], force=force, workers=workers)
    elif cmd == "manifest":
        consolidate_manifest()
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
