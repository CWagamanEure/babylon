"""Droplet-side K100 adds pull (PYRAMID-ALT mechanics pass). Reads lake perp_fills same-region.

Modeled on /root/pull_adds_droplet.py (construction E3 pattern); differences: K100 cohorts from
/root/pyramid_wallets.json, and rows are collapsed per (wallet,coin,ts,dir) block event with the
summed notional (px*sz) so the ladder sees one signal per taker order-block, not per fill.

Run:  SPACES_KEY=... SPACES_SECRET=... /root/lakeenv/bin/python /root/pull_pyramid_adds_droplet.py
"""
import json
import os
from pathlib import Path

import duckdb

BUCKET = "incerto-datalake-v1"
PF = f"s3://{BUCKET}/source=hyperliquid_reservoir/dataset=perp_fills"
wallets_by_fold = json.load(open("/root/pyramid_wallets.json"))
con = duckdb.connect()
con.execute("SET memory_limit='1200MB'; SET threads=2")
con.execute("INSTALL httpfs; LOAD httpfs")
con.execute("CREATE SECRET lake (TYPE S3, KEY_ID ?, SECRET ?, "
            "ENDPOINT 'nyc3.digitaloceanspaces.com', REGION 'nyc3')",
            [os.environ["SPACES_KEY"], os.environ["SPACES_SECRET"]])
out_dir = Path("/root/pyramid_adds")
out_dir.mkdir(exist_ok=True)
for fold, wallets in sorted(wallets_by_fold.items()):
    part = out_dir / f"fold={fold}.parquet"
    if part.exists():
        print(f"skip {fold}", flush=True)
        continue
    y, m = int(fold[:4]), int(fold[4:6])
    glob = f"{PF}/date={y:04d}-{m:02d}-*/fills.parquet"
    wl = ",".join(f"'{w}'" for w in wallets)
    tmp = str(part) + ".tmp"
    con.execute(f"""COPY (
        SELECT wallet, coin, ts,
               CASE WHEN direction = 'Open Long' THEN 1 ELSE -1 END AS dir_sign,
               SUM(CAST(px AS DOUBLE) * CAST(sz AS DOUBLE)) AS notl
        FROM read_parquet('{glob}')
        WHERE wallet IN ({wl}) AND crossed
          AND direction IN ('Open Long', 'Open Short') AND start_position <> 0
        GROUP BY wallet, coin, ts, dir_sign
    ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
    Path(tmp).replace(part)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{part.as_posix()}')").fetchone()[0]
    print(f"done {fold}: {n:,} add signals", flush=True)
print("ALL DONE", flush=True)
