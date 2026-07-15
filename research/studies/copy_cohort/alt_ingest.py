"""Wallet-FILTERED raw alt-fills ingest for the frozen copy_cohort alt validation (research lane only).

The general `research.data.reservoir_ingest` keeps only a 5-min flow AGGREGATE (deletes the raw), which cannot
build opening-taker episodes. Here we need per-fill price/size/direction — but ONLY for the 133 frozen wallets,
so we download each daily Reservoir object (same requester-pays egress), FILTER to those wallets, project the
episode-relevant columns, and write a tiny per-day parquet to `data/raw/alt_fills/`. The raw temp is deleted
immediately. Firewall: alt data feeds `research/` only (never src/babylon or gate_a).

Idempotent: skip a day whose part already exists. Resumable: just re-run.

    python -m research.studies.copy_cohort.alt_ingest day   20260601
    python -m research.studies.copy_cohort.alt_ingest range 20250801 20260630
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import duckdb

from research.data.markout import REPO_ROOT

BUCKET = "hydromancer-reservoir"
REGION = "ap-northeast-1"
PREFIX = "by_dex/hyperliquid/fills/perp/all"
OUT_DIR = REPO_ROOT / "data" / "raw" / "alt_fills"
FROZEN = REPO_ROOT / "data" / "derived" / "copy_cohort" / "frozen_alt_universe.json"
DUCK_MEM = "6GB"


def _s3_uri(day: str) -> str:
    return f"s3://{BUCKET}/{PREFIX}/date={day[:4]}-{day[4:6]}-{day[6:8]}/fills.parquet"


def _part(day: str) -> Path:
    return OUT_DIR / f"month={day[:6]}" / f"day={day}" / "fills.parquet"


def _wallets() -> list[str]:
    return sorted(json.loads(FROZEN.read_text())["distinct_wallets"])


def ingest_day(day: str, wallets: list[str], force: bool = False) -> str:
    part = _part(day)
    if part.exists() and not force:
        return f"skip {day}"
    with tempfile.TemporaryDirectory(prefix="altfills_") as td:
        raw = Path(td) / "raw.parquet"
        r = subprocess.run(["aws", "s3", "cp", _s3_uri(day), str(raw),
                            "--request-payer", "requester", "--region", REGION, "--quiet"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not raw.exists():
            return f"MISS {day}: {r.stderr.strip()[:100]}"
        con = duckdb.connect()
        con.execute(f"SET memory_limit='{DUCK_MEM}'; SET threads=2")
        con.execute("CREATE TEMP TABLE frz AS SELECT * FROM (SELECT UNNEST(?) AS wallet)", [wallets])
        part.parent.mkdir(parents=True, exist_ok=True)
        tmp = part.parent / f".{part.name}.tmp"
        con.execute(f"""COPY (
            SELECT f.address                              AS wallet,
                   f.base_symbol                          AS coin,
                   epoch_ms(f.timestamp)                  AS ts,
                   f.price                                AS px,
                   f.size                                 AS sz,
                   f.side                                 AS side,
                   f.direction                            AS direction,
                   f.start_position                       AS start_position,
                   f.crossed                              AS crossed,
                   f.realized_pnl                         AS realized_pnl,
                   f.is_liquidation                       AS is_liquidation,
                   f.order_id, f.trade_id, f.fee
            FROM read_parquet('{raw.as_posix()}') f
            JOIN frz ON f.address = frz.wallet
            WHERE f.asset_class = 'perp'
        ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()[0]
        con.close()
        tmp.replace(part)
    return f"done {day}: {n} fills"


def _days(start: str, end: str):
    d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    while d <= e:
        yield d.strftime("%Y%m%d"); d += timedelta(days=1)


def main(argv):
    wallets = _wallets()
    print(f"[alt_ingest] {len(wallets)} frozen wallets -> {OUT_DIR}", flush=True)
    if argv and argv[0] == "day":
        print(ingest_day(argv[1], wallets, force="--force" in argv))
    elif argv and argv[0] == "range":
        tot = 0
        for day in _days(argv[1], argv[2]):
            msg = ingest_day(day, wallets, force="--force" in argv)
            if msg.startswith("done"):
                tot += int(msg.split(":")[1].split()[0])
            print(f"  {msg}  (cum {tot:,})", flush=True)
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
