"""
Selection/survivorship audit of individual_persistence.py's train/test split.
Reruns the SAME avg-cost ledger (per_close, unchanged) over the SAME universe
(>=2000 train majors fills), but keeps EVERY wallet regardless of test-window
activity, and stores raw close counts + stats at floor=2 so we can re-apply
any n>=K gate post-hoc without re-walking the tape.
"""
import glob, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl

sys.path.insert(0, "src")
from individual_persistence import per_close, COINS, TRAIN_HI, TEST_LO, TAPE, ms, BP

t_start = time.time()


def stats_any(recs, floor=2):
    """Like original stats() but floor is a parameter; returns None only if < floor."""
    if len(recs) < floor:
        return None
    r = np.array([x[0] for x in recs]); notn = np.array([x[1] for x in recs])
    good = notn > 0; r = r[good]; notn = notn[good]
    if r.size < floor:
        return None
    bps = r / notn * BP
    n = bps.size; mean = bps.mean(); sd = bps.std()
    t = mean / (sd / np.sqrt(n)) if sd > 0 else 0.0
    vw = r.sum() / notn.sum() * BP
    return n, mean, t, vw


def main():
    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS))
    cnt = (lf.filter(pl.col("ts") < TRAIN_HI).group_by("wallet").agg(n=pl.len())
           .filter(pl.col("n") >= 2000).select("wallet").collect())
    uni = set(cnt["wallet"].to_list())
    print(f"universe (>=2000 train majors fills): {len(uni)} wallets", flush=True)
    uni = sorted(uni); W = {}
    BATCH = 400
    for bi in range(0, len(uni), BATCH):
        batch = set(uni[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch)).select("wallet", "coin", "ts", "px", "sz")
              .collect().sort("ts"))
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            g = g.sort("ts")
            d = W.setdefault(wal, {"tr": [], "te": []})
            for t, r, notn in per_close(g["px"].to_numpy(), g["sz"].to_numpy(), g["ts"].to_numpy()):
                if t < TRAIN_HI:
                    d["tr"].append((r, notn))
                elif t >= TEST_LO:
                    d["te"].append((r, notn))
        del df
        print(f"  batch {bi//BATCH+1}/{(len(uni)-1)//BATCH+1} done "
              f"({bi+len(batch)} wallets, {time.time()-t_start:.0f}s elapsed)", flush=True)

    rows = []
    for wal, d in W.items():
        ntr_raw, nte_raw = len(d["tr"]), len(d["te"])
        st = stats_any(d["tr"], floor=2)
        se = stats_any(d["te"], floor=2)
        rows.append((
            wal, ntr_raw, nte_raw,
            *(st if st is not None else (None, None, None, None)),
            *(se if se is not None else (None, None, None, None)),
        ))
    R = pl.DataFrame(rows, schema=[
        "wallet", "ntr_raw", "nte_raw",
        "ntr", "tr_bps", "tr_t", "tr_vw",
        "nte", "te_bps", "te_t", "te_vw",
    ], orient="row")
    print(f"total universe rows: {R.height}")
    R.write_parquet("out/individual_persistence_full.parquet")
    print(f"done in {time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
