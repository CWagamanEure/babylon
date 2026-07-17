"""ALL-WALLET Reservoir streaming aggregate — per-(wallet,coin,day) PnL/activity + flat taker-open entries.

Purpose: alt-inclusive capday SELECTION on the full wallet universe (fresh-wallet replication of the frozen
scale rule). We stream each daily Reservoir object (~417MB), aggregate, and DELETE the raw immediately —
disk stays ~0.5GB while the retained layer is small. Two outputs per day:

  wallet_coin_day/  one row per (wallet, coin, day): n_fills, n_taker, pnl, fee, builder_fee, notional,
                    n_open_flat, n_liq — everything the capped-PnL/active-day selector + activity/identity
                    features need. Exact DECIMAL sums (never DOUBLE — see BABYLON_CONVENTIONS).
  open_entries/     one row per TRUE flat position-open taker fill (crossed, Open Long/Short,
                    start_position=0): the copyable forward entries + the scale-classification input
                    (median opening notional), for ANY future cohort without re-pulling.

FIREWALL: Reservoir-derived → research lane only (never src/babylon, never gate_a). Not block-identified.
Idempotent per day (part exists → skip); atomic tmp+rename; resumable — just re-run.

    python -m research.studies.copy_cohort.alt_universe_ingest day   20260601
    python -m research.studies.copy_cohort.alt_universe_ingest range 20250801 20260630
"""
from __future__ import annotations

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
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_universe"
DUCK_MEM = "6GB"


def _s3_uri(day: str) -> str:
    return f"s3://{BUCKET}/{PREFIX}/date={day[:4]}-{day[4:6]}-{day[6:8]}/fills.parquet"


def _parts(day: str) -> tuple[Path, Path]:
    sub = f"month={day[:6]}/day={day}"
    return OUT / "wallet_coin_day" / sub / "part.parquet", OUT / "open_entries" / sub / "part.parquet"


def ingest_day(day: str, force: bool = False) -> str:
    wcd, ope = _parts(day)
    if wcd.exists() and ope.exists() and not force:
        return f"skip {day}"
    with tempfile.TemporaryDirectory(prefix="altuni_") as td:
        raw = Path(td) / "raw.parquet"
        r = subprocess.run(["aws", "s3", "cp", _s3_uri(day), str(raw),
                            "--request-payer", "requester", "--region", REGION, "--quiet"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not raw.exists():
            return f"MISS {day}: {r.stderr.strip()[:100]}"
        con = duckdb.connect()
        con.execute(f"SET memory_limit='{DUCK_MEM}'; SET threads=2")
        for p in (wcd, ope):
            p.parent.mkdir(parents=True, exist_ok=True)
        tmp1, tmp2 = str(wcd) + ".tmp", str(ope) + ".tmp"
        con.execute(f"""COPY (
            SELECT f.address                                        AS wallet,
                   f.base_symbol                                    AS coin,
                   {day}                                            AS day,
                   count(*)                                         AS n_fills,
                   count(*) FILTER (WHERE f.crossed)                AS n_taker,
                   SUM(f.realized_pnl)                              AS pnl,
                   SUM(f.fee)                                       AS fee,
                   SUM(f.builder_fee)                               AS builder_fee,
                   SUM(abs(f.size) * f.price)                       AS notional,
                   count(*) FILTER (WHERE f.crossed AND f.direction IN ('Open Long','Open Short')
                                      AND f.start_position = 0)     AS n_open_flat,
                   count(*) FILTER (WHERE f.is_liquidation)         AS n_liq
            FROM read_parquet('{raw.as_posix()}') f
            WHERE f.asset_class = 'perp'
            GROUP BY 1, 2, 3
        ) TO '{tmp1}' (FORMAT PARQUET, COMPRESSION zstd)""")
        con.execute(f"""COPY (
            SELECT f.address                                        AS wallet,
                   f.base_symbol                                    AS coin,
                   epoch_ms(f.timestamp)                            AS ts,
                   CASE WHEN f.direction = 'Open Long' THEN 1 ELSE -1 END AS dir_sign,
                   abs(f.size)                                      AS abs_sz,
                   f.price                                          AS px,
                   abs(f.size) * f.price                            AS notl,
                   f.fee                                            AS fee
            FROM read_parquet('{raw.as_posix()}') f
            WHERE f.asset_class = 'perp' AND f.crossed
              AND f.direction IN ('Open Long','Open Short') AND f.start_position = 0
        ) TO '{tmp2}' (FORMAT PARQUET, COMPRESSION zstd)""")
        n1 = con.execute(f"SELECT count(*) FROM read_parquet('{tmp1}')").fetchone()[0]
        n2 = con.execute(f"SELECT count(*) FROM read_parquet('{tmp2}')").fetchone()[0]
        con.close()
        Path(tmp1).replace(wcd)
        Path(tmp2).replace(ope)
    return f"done {day}: {n1:,} wallet-coin-days | {n2:,} flat opens"


def _days(start: str, end: str):
    d = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    while d <= e:
        yield d.strftime("%Y%m%d"); d += timedelta(days=1)


def main(argv):
    if argv and argv[0] == "day":
        print(ingest_day(argv[1], force="--force" in argv), flush=True)
    elif argv and argv[0] == "range":
        for day in _days(argv[1], argv[2]):
            print(f"  {ingest_day(day, force='--force' in argv)}", flush=True)
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
