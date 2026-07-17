"""incerto-datalake-v1 access for the alt-universe study (research lane only).

DuckDB httpfs over DO Spaces. Credentials: INCERTO_RAW_STORE_S3_* env vars, falling back to ~/incerto/.env
(user-designated source). Globs are leaf-only per convention; manifests live under a separate dataset=
prefix and are never swept by data globs.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

BUCKET = "incerto-datalake-v1"
ENDPOINT = "nyc3.digitaloceanspaces.com"
WCD = f"s3://{BUCKET}/source=babylon_derived/dataset=alt_universe_wallet_coin_day/date=*/part.parquet"
OPE = f"s3://{BUCKET}/source=babylon_derived/dataset=alt_universe_open_entries/date=*/part.parquet"
MANIFEST = f"s3://{BUCKET}/source=hyperliquid_reservoir/dataset=perp_fills_manifest/date=*/manifest.json"


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


def month_dates(month: int) -> str:
    """Glob fragment for one calendar month: date=YYYY-MM-*."""
    y, m = divmod(month, 100)
    return f"{y:04d}-{m:02d}-*"


def wcd_month_glob(month: int) -> str:
    return WCD.replace("date=*", f"date={month_dates(month)}")


def ope_month_glob(month: int) -> str:
    return OPE.replace("date=*", f"date={month_dates(month)}")
