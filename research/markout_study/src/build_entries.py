"""
Stage 1 — build the bar-net entry table from cand2 fills (ARCHITECTURE v3 §4.1-4.4).

Sharded by wallet-address prefix 0x0..0xf (16 shards) for RAM safety on 8 GB: each shard
scans the 11 cand2 files filtered to its prefix, reduces fills -> bar-net entries per
(wallet, coin), prices entries post-fill, drops NaN-priced and sub-$100 dust entries, and
writes out/entries/part_<p>.parquet. Downstream stages scan the 16 parts lazily.

Stores ALL coins (majors get per-wallet stats downstream; alts feed the field baseline only).
Columns: wallet, coin, b_ts, dir, q, entry_px, notl.
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import T0, taker_entries, price_entries, load_flat_units, _load_bars, MIN_NOTL

ROOT = Path(__file__).resolve().parents[1]
CAND = sorted(glob(str(ROOT.parent / "scratch_conv/mlscreen/cand2_*.parquet")))
OUTD = ROOT / "out" / "entries"
OUTD.mkdir(parents=True, exist_ok=True)


def main():
    assert CAND, "no cand2 files found"
    print(f"cand2 files: {len(CAND)}", flush=True)
    lookups = _load_bars()
    flat_u = load_flat_units(CAND)
    print(f"bars: {len(lookups)} coins | flat_units computed for {len(flat_u)} coins", flush=True)

    only = None
    if len(sys.argv) > 1:                 # dry-run one shard: python build_entries.py 4
        only = int(sys.argv[1], 16)
        print(f"DRY-RUN shard 0x{only:x} only", flush=True)
    grand = 0
    for p in range(16):
        if only is not None and p != only:
            continue
        pfx = f"0x{p:x}"
        # sort INSIDE the lazy plan so polars can stream/spill it (worst shard ~23M rows)
        df = (pl.scan_parquet(CAND)
              .filter(pl.col("wallet").str.starts_with(pfx) & (pl.col("ts") >= T0))
              .select("wallet", "coin", "ts", "tid", "sz", "crossed", "zhash", "px")
              .sort(["wallet", "coin", "ts", "tid"])
              .collect(engine="streaming"))
        W, C, B, D, Q, PX, N = [], [], [], [], [], [], []
        POS, AVG, FVW = [], [], []            # [Stage 0] true position, open-inventory avg entry, cluster fill-VWAP
        for (w,), g in df.group_by("wallet", maintain_order=True):
            for (coin,), gc in g.group_by("coin", maintain_order=True):
                c = str(coin)
                lk = lookups.get(c)
                if lk is None or lk[0].size < 100:
                    continue
                assert c in flat_u, f"coin {c} missing from flat_units"
                b_ts, d, q, pos_after, avg_px, fill_vwap = taker_entries(
                    gc["ts"].to_numpy(), gc["sz"].to_numpy(),
                    gc["crossed"].to_numpy(), gc["zhash"].to_numpy(),
                    flat_u[c], px=gc["px"].to_numpy(), return_pos=True)
                if b_ts.size == 0:
                    continue
                entry_px, notl = price_entries(lk, b_ts, q)
                keep = np.isfinite(entry_px) & (entry_px > 0) & (np.abs(notl) >= MIN_NOTL)
                if not keep.any():
                    continue
                k = int(keep.sum())
                W.extend([str(w)] * k); C.extend([c] * k)
                B.append(b_ts[keep]); D.append(d[keep]); Q.append(q[keep])
                PX.append(entry_px[keep]); N.append(notl[keep])
                POS.append(pos_after[keep]); AVG.append(avg_px[keep]); FVW.append(fill_vwap[keep])
        if not W:
            print(f"  shard {pfx}: 0 entries", flush=True)
            continue
        out = pl.DataFrame({
            "wallet": W, "coin": C,
            "b_ts": np.concatenate(B), "dir": np.concatenate(D).astype(np.int64),
            "q": np.concatenate(Q), "entry_px": np.concatenate(PX), "notl": np.concatenate(N),
            "pos_after": np.concatenate(POS), "avg_entry_px": np.concatenate(AVG),
            "fill_vwap": np.concatenate(FVW),
        })
        out.write_parquet(OUTD / f"part_{pfx}.parquet")
        grand += out.height
        print(f"  shard {pfx}: {out.height:,} entries  (running {grand:,})", flush=True)
        del df, out
    print(f"DONE: {grand:,} entries -> {OUTD}", flush=True)


if __name__ == "__main__":
    main()
