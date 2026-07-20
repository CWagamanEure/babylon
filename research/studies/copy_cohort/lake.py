"""incerto-datalake-v1 access for the alt-universe study (research lane only).

DuckDB httpfs over DO Spaces. Credentials use INCERTO_RAW_STORE_S3_* env vars, falling back
to ~/incerto/.env (user-designated source). Globs are leaf-only; manifests use a separate
dataset prefix and are never swept by data globs.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import subprocess
from pathlib import Path

import boto3
import duckdb

BUCKET = "incerto-datalake-v1"
ENDPOINT = "nyc3.digitaloceanspaces.com"
WCD = f"s3://{BUCKET}/source=babylon_derived/dataset=alt_universe_wallet_coin_day/date=*/part.parquet"
OPE = f"s3://{BUCKET}/source=babylon_derived/dataset=alt_universe_open_entries/date=*/part.parquet"
MANIFEST = f"s3://{BUCKET}/source=hyperliquid_reservoir/dataset=perp_fills_manifest/date=*/manifest.json"
_S3_CLIENT = None

def _creds() -> tuple[str, str]:
    k = os.environ.get("INCERTO_RAW_STORE_S3_ACCESS_KEY_ID")
    s = os.environ.get("INCERTO_RAW_STORE_S3_SECRET_ACCESS_KEY")
    if k and s:
        return k, s
    env = Path.home() / "incerto" / ".env"
    kv = {}
    for line in env.read_text().splitlines():
        if line.startswith("INCERTO_RAW_STORE_S3_"):
            key, _, val = line.partition("=")
            kv[key.strip()] = val.strip()
    return kv["INCERTO_RAW_STORE_S3_ACCESS_KEY_ID"], kv["INCERTO_RAW_STORE_S3_SECRET_ACCESS_KEY"]


def connect(mem: str = "6GB", threads: int = 4) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{mem}'; SET threads={threads}")
    con.execute("INSTALL httpfs; LOAD httpfs")
    k, s = _creds()
    con.execute(f"""CREATE SECRET lake (TYPE S3, KEY_ID '{k}', SECRET '{s}',
                    ENDPOINT '{ENDPOINT}', REGION 'nyc3')""")
    return con


def git_describe() -> str:
    """`git describe --always --dirty` provenance stamp for emitted reports."""
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty"],
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[3]).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def month_dates(month: int) -> str:
    """Glob fragment for one calendar month: date=YYYY-MM-*."""
    y, m = divmod(month, 100)
    return f"{y:04d}-{m:02d}-*"


def wcd_month_glob(month: int) -> str:
    return WCD.replace("date=*", f"date={month_dates(month)}")


def ope_month_glob(month: int) -> str:
    return OPE.replace("date=*", f"date={month_dates(month)}")


def expected_iso_days(months: list[int]) -> list[str]:
    out: list[str] = []
    for month in months:
        y, m = divmod(month, 100)
        for d in range(1, calendar.monthrange(y, m)[1] + 1):
            out.append(f"{y:04d}-{m:02d}-{d:02d}")
    return out


def _derived_head(dataset: str, iso_day: str) -> dict[str, object]:
    """Fingerprint the actual derived object consumed, not merely its raw manifest."""
    key = f"source=babylon_derived/dataset={dataset}/date={iso_day}/part.parquet"
    global _S3_CLIENT
    if _S3_CLIENT is None:
        k, s = _creds()
        _S3_CLIENT = boto3.client(
            "s3", endpoint_url=f"https://{ENDPOINT}", region_name="nyc3",
            aws_access_key_id=k, aws_secret_access_key=s,
        )
    try:
        h = _S3_CLIENT.head_object(Bucket=BUCKET, Key=key)
    except Exception as exc:
        raise RuntimeError(f"missing/unreadable derived object s3://{BUCKET}/{key}") from exc
    return {
        "key": key, "etag": str(h.get("ETag", "")).strip('"'),
        "size": int(h["ContentLength"]),
        "last_modified": str(h.get("LastModified")),
    }


def validated_lineage(con, months: list[int], datasets: tuple[str, ...]) -> dict[str, object]:
    """Fail closed on daily manifest coverage and bind caches to actual derived objects."""
    expected = expected_iso_days(months)
    globs = [MANIFEST.replace("date=*", f"date={month_dates(m)}") for m in months]
    marks = ",".join("?" for _ in globs)
    rows = con.execute(
        f"""SELECT CAST(day AS VARCHAR), status, source_etag, source_size,
                   schema_version, code_commit, created_utc
            FROM read_json_auto([{marks}], union_by_name=true) ORDER BY day""",
        globs,
    ).fetchall()
    by_day: dict[str, list[tuple]] = {}
    for row in rows:
        raw = str(row[0]).replace("-", "")
        iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        by_day.setdefault(iso, []).append(row)
    bad = [d for d in expected if len(by_day.get(d, [])) != 1]
    extra = sorted(set(by_day) - set(expected))
    non_ok = [d for d in expected if by_day.get(d) and by_day[d][0][1] != "ok"]
    if bad or extra or non_ok:
        raise RuntimeError(
            f"manifest coverage failed months={months}: missing/duplicate={bad[:8]} "
            f"extra={extra[:8]} non_ok={non_ok[:8]}"
        )
    manifest_payload = [[str(v) if v is not None else None for v in by_day[d][0]]
                        for d in expected]
    objects = {dataset: [_derived_head(dataset, d) for d in expected]
               for dataset in datasets}
    raw = json.dumps({"manifests": manifest_payload, "objects": objects},
                     sort_keys=True, separators=(",", ":")).encode()
    return {
        "months": months, "expected_days": len(expected), "datasets": list(datasets),
        "manifest_schema_versions": sorted({int(by_day[d][0][4]) for d in expected}),
        "manifest_code_commits": sorted({str(by_day[d][0][5]) for d in expected}),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "objects": objects,
    }
