"""Reservoir alt-flow ingest → `data/derived/alt_flow/` (research alt lane, ALL coins, 5-min aggregate).

COMPACT-PROJECTED ingest (disk-frugal; local disk is the binding constraint — a faithful 109 GB per-fill
mirror won't fit). Per the 4-agent pre-build audit (`audit/reservoir_ingest/`, binding corollaries in
RESERVOIR_ALT_FILLS_SPEC §0) + the compact-projected decision:

  - Per day: `aws s3 cp` the source parquet to a TEMP file, aggregate to per (wallet, coin, 5-min bucket,
    crossed) SIGNED NOTIONAL flow, write a compact ~19 MB/day parquet to
    `derived/alt_flow/month=YYYYMM/day=YYYYMMDD/flow.parquet`, then DELETE the temp. Full window ≈ 6.4 GB.
  - Keeps everything the wallet-cohort study needs: re-bucketable ≥5-min flow, taker/maker split (crossed) for
    OFI, both-counterparties (Σ flow_signed over all rows = 0). DROPS per-fill px/sz/start_position/liq/fees —
    Reservoir remains the re-pullable source of truth for those (no alt position-reconstruction from this lake).
  - Reservoir is MUTABLE (mass-republished 2026-03-20; recent days land T+1): idempotency keys on the S3
    **ETag** (one cheap HEAD/day), NOT code_commit. `verify` re-HEADs & reports drift. Last PROVISIONAL_DAYS
    partitions always re-HEADed. Atomic write: part first, done-shard second.
  - flow_signed is DOUBLE USD — a SIGNAL aggregate (asset_ctx convention: reference data, never an exact
    position ledger), not the exact-string money of the node_fills tape.

FIREWALL: research alt lane ONLY. Never imported/read by `src/babylon/` or `markout_study/gate_a/`.

    python -m research.data.reservoir_ingest day   20260601        # one day (stage-1 gate)
    python -m research.data.reservoir_ingest month 202508          # one month
    python -m research.data.reservoir_ingest range 20250801 20260630   # the full window (~6.4 GB)
    python -m research.data.reservoir_ingest verify 202508         # HEAD all days, report ETag drift
    python -m research.data.reservoir_ingest manifest              # consolidate shards → manifest.parquet
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import schema

BUCKET = "hydromancer-reservoir"
REGION = "ap-northeast-1"
PREFIX = "by_dex/hyperliquid/fills/perp/all"        # perp/all ONLY (siblings are subsets → double-count)
BUCKET_MS = 300_000                                  # 5-minute aggregation grid (re-bucketable to coarser)
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
ALT_DIR = DATA_DIR / "derived" / "alt_flow"          # DERIVED (projected aggregate), not raw
MANIFEST_DIR = ALT_DIR / "_manifest"                 # underscore ⇒ skipped by the leaf glob
PROVISIONAL_DAYS = 2
DUCK_MEM = "1200MB"


def _code_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else "nogit"
    except Exception:
        return "nogit"


CODE_COMMIT = _code_commit()


def _key(day: str) -> str:
    return f"{PREFIX}/date={day[:4]}-{day[4:6]}-{day[6:8]}/fills.parquet"


def _s3_uri(day: str) -> str:
    return f"s3://{BUCKET}/{_key(day)}"


def _part_path(day: str) -> Path:
    return ALT_DIR / f"month={day[:6]}" / f"day={day}" / "flow.parquet"


def _shard_path(day: str) -> Path:
    return MANIFEST_DIR / f"{day}.json"


def _head(day: str) -> dict | None:
    r = subprocess.run(
        ["aws", "s3api", "head-object", "--bucket", BUCKET, "--key", _key(day),
         "--request-payer", "requester", "--region", REGION, "--output", "json"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        m = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    return {"etag": (m.get("ETag") or "").strip('"'),
            "last_modified": m.get("LastModified"), "size_bytes": m.get("ContentLength")}


def _provisional(day: str) -> bool:
    d = date(int(day[:4]), int(day[4:6]), int(day[6:8]))
    return (datetime.now(UTC).date() - d).days <= PROVISIONAL_DAYS


def _is_done(day: str, head: dict | None) -> bool:
    """Done iff part+shard exist, status=done, current ALT_SCHEMA_VERSION, and SAME S3 ETag (mutability guard).
    Provisional (recent) days are never treated as done — always re-checked."""
    part, shard = _part_path(day), _shard_path(day)
    if not (part.exists() and shard.exists()) or head is None or _provisional(day):
        return False
    try:
        m = json.loads(shard.read_text())
    except Exception:
        return False
    return (m.get("status") == "done"
            and m.get("schema_version") == schema.ALT_SCHEMA_VERSION
            and m.get("etag") == head.get("etag"))


def _write_atomic(path: Path, write_fn) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}"
    try:
        write_fn(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _write_shard(day: str, row: dict) -> None:
    _write_atomic(_shard_path(day), lambda p: p.write_text(json.dumps(row)))


def _cp(day: str, dest: Path) -> bool:
    r = subprocess.run(["aws", "s3", "cp", _s3_uri(day), str(dest),
                        "--request-payer", "requester", "--region", REGION, "--quiet"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not dest.exists():
        sys.stderr.write(f"  MISS {_s3_uri(day)}: {r.stderr.strip()[:120]}\n")
        return False
    return True


def _aggregate(raw: Path, out_tmp: Path) -> int:
    """Aggregate one raw day parquet → per (wallet, coin, 5-min bucket, crossed) signed-notional flow.
    flow_signed = Σ(side='buy' ? +notional : −notional); n = fill count. Returns row count."""
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{DUCK_MEM}'; SET threads=1")
    con.execute(f"""COPY (
        SELECT address AS wallet, coin,
               (epoch_ms(timestamp) - epoch_ms(timestamp) % {BUCKET_MS}) AS bucket,
               crossed,
               sum(CASE WHEN side='buy' THEN (abs(size)*price) ELSE -(abs(size)*price) END)::DOUBLE AS flow_signed,
               count(*) AS n
        FROM read_parquet('{raw.as_posix()}')
        GROUP BY wallet, coin, bucket, crossed
    ) TO '{out_tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out_tmp.as_posix()}')").fetchone()[0]
    con.close()
    return n


def ingest_day(day: str, force: bool = False) -> dict:
    head = _head(day)
    base = {"object_key": _s3_uri(day), "day": int(day), "month": int(day[:6]),
            "schema_version": schema.ALT_SCHEMA_VERSION, "code_commit": CODE_COMMIT,
            "etag": (head or {}).get("etag"), "last_modified": (head or {}).get("last_modified"),
            "size_bytes": (head or {}).get("size_bytes")}
    if not force and _is_done(day, head):
        return {**base, "status": "skipped"}
    if head is None:
        _write_shard(day, {**base, "status": "missing"})
        return {**base, "status": "missing"}
    with tempfile.TemporaryDirectory(prefix="reservoir_") as td:      # temp raw + agg, freed on exit
        tmpdir = Path(td)
        raw = tmpdir / "raw.parquet"
        if not _cp(day, raw):
            _write_shard(day, {**base, "status": "missing"})
            return {**base, "status": "missing"}
        agg_tmp = tmpdir / "agg.parquet"
        try:
            n_rows = _aggregate(raw, agg_tmp)
        except Exception as e:
            _write_shard(day, {**base, "status": "failed", "error": str(e)[:160]})
            sys.stderr.write(f"  FAILED {day}: {e}\n")
            return {**base, "status": "failed"}
        raw.unlink(missing_ok=True)                                   # free the 400 MB raw ASAP
        _write_atomic(_part_path(day), lambda p: __import__("shutil").copyfile(agg_tmp, p))  # part first…
    _write_shard(day, {**base, "rows": n_rows, "status": "done"})     # …then done-shard
    return {**base, "rows": n_rows, "status": "done"}


# ---- ranges -----------------------------------------------------------------------------------
def _days(start: str, end: str):
    d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    while d <= e:
        yield d.strftime("%Y%m%d")
        d += timedelta(days=1)


def _month_bounds(month: str) -> tuple[str, str]:
    y, m = int(month[:4]), int(month[4:6])
    start = f"{y:04d}{m:02d}01"
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, (date(ny, nm, 1) - timedelta(days=1)).strftime("%Y%m%d")


def _run_days(days: list[str], force: bool) -> dict:
    agg: dict[str, int] = {}
    total = 0
    for i, day in enumerate(days, 1):
        r = ingest_day(day, force=force)
        st = r.get("status", "done")
        agg[st] = agg.get(st, 0) + 1
        total += r.get("rows", 0) or 0
        sys.stderr.write(f"  {i}/{len(days)} {day}: {st}"
                         + (f" ({r.get('rows',0):,} agg rows)" if st == "done" else "") + "\n")
        sys.stderr.flush()
    print(f"  -> {dict(agg)} | {total:,} agg rows", flush=True)
    return {"status_counts": agg, "rows": total}


def ingest_month(month: str, force: bool = False) -> dict:
    s, e = _month_bounds(month)
    print(f"=== reservoir alt-flow month {month} → {ALT_DIR}  ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC) ===",
          flush=True)
    return _run_days(list(_days(s, e)), force)


def ingest_range(start: str, end: str, force: bool = False) -> None:
    print(f"=== reservoir alt-flow range {start}..{end} ===", flush=True)
    _run_days(list(_days(start, end)), force)
    consolidate_manifest()


def verify(start: str, end: str | None = None) -> None:
    if end is None:
        start, end = _month_bounds(start)
    drift, missing, ok = [], [], 0
    for day in _days(start, end):
        head = _head(day)
        shard = _shard_path(day)
        rec = json.loads(shard.read_text()) if shard.exists() else None
        if head is None:
            missing.append(day)
        elif rec and rec.get("etag") != head.get("etag"):
            drift.append((day, rec.get("etag"), head.get("etag")))
        else:
            ok += 1
    print(f"[verify] {ok} unchanged, {len(drift)} DRIFTED, {len(missing)} missing")
    for day, old, new in drift[:20]:
        print(f"    DRIFT {day}: shard {old} != live {new}  (re-run `day {day} --force`)")
    if missing:
        print(f"    missing: {missing[:20]}")


def consolidate_manifest() -> Path:
    rows = []
    for shard in sorted(MANIFEST_DIR.glob("*.json")) if MANIFEST_DIR.exists() else []:
        try:
            rows.append(json.loads(shard.read_text()))
        except Exception:
            continue
    cols = ["object_key", "day", "month", "status", "etag", "last_modified", "size_bytes",
            "rows", "schema_version", "code_commit"]
    table = (pa.table({c: [r.get(c) for r in rows] for c in cols}) if rows
             else pa.table({c: pa.array([], type=pa.string()) for c in cols}))
    out = ALT_DIR / "manifest.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    by_status: dict[str, int] = {}
    total = 0
    for r in rows:
        by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
        total += r.get("rows", 0) or 0
    print(f"[manifest] {len(rows)} days → {out} | status {by_status} | {total:,} agg rows")
    bad = [r["day"] for r in rows if r.get("status") in ("missing", "failed")]
    if bad:
        print(f"[manifest] {len(bad)} missing/failed (re-run to retry): {bad[:20]}")
    return out


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], [a for a in argv[1:] if a != "--force"]
    force = "--force" in argv
    if cmd == "day":
        print(ingest_day(rest[0], force=force))
    elif cmd == "month":
        ingest_month(rest[0], force=force)
        consolidate_manifest()
    elif cmd == "range":
        ingest_range(rest[0], rest[1], force=force)
    elif cmd == "verify":
        verify(rest[0], rest[1] if len(rest) > 1 else None)
    elif cmd == "manifest":
        consolidate_manifest()
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
