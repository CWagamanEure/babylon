"""Phase-2 leakage audit: recompute the cohort eligibility variables (majors-fill count, taker_share, med_hold_h)
on TRAINING DATA ONLY, and measure how many of the 1,694 cohort wallets change membership. Reuses hold_size_dist.ledger.
RAM-safe: scoped to cohort wallets, training window, batched."""
import sys, glob; from datetime import datetime, timezone
import numpy as np, polars as pl
sys.path.insert(0, "src")
from hold_size_dist import ledger, TAPE, COINS, BANDS, MIN_NOTL

CUT = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)   # training < 2026-02-01
TAKER = 0.70; cohort = set(l.strip() for l in open("out/cohort_K.txt") if l.strip())
print(f"cohort wallets: {len(cohort)} | train cutoff ts < {CUT}", flush=True)

lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS) & pl.col("wallet").is_in(list(cohort)) & (pl.col("ts") < CUT))
uni = sorted(cohort); rows = []; BATCH = 150
for bi in range(0, len(uni), BATCH):
    batch = set(uni[bi:bi + BATCH])
    df = lf.filter(pl.col("wallet").is_in(batch)).select("wallet", "coin", "ts", "px", "sz", "crossed").collect().sort(["ts"])
    acc = {}
    for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
        g = g.sort("ts"); px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); tsr = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
        a = acc.setdefault(wal, {"closes": [], "fill_notl": 0.0, "fill_tk": 0.0, "nfill": 0})
        fn = np.abs(sz) * px; a["fill_notl"] += float(fn.sum()); a["fill_tk"] += float(fn[cr.astype(bool)].sum())
        a["nfill"] += int(g.height); a["closes"].extend(ledger(px, sz, tsr, cr))
    for wal, a in acc.items():
        cl = a["closes"]
        ts_ = a["fill_tk"] / a["fill_notl"] if a["fill_notl"] > 0 else np.nan
        if cl:
            hold = np.array([x[1] for x in cl]); ots = np.array([x[2] for x in cl])
            tkh = hold[np.isfinite(ots) & (ots > 0.5) & (hold > 0)]
            med_h = float(np.median(tkh)) if tkh.size else np.nan
        else:
            med_h = np.nan
        rows.append((wal, a["nfill"], float(ts_), med_h))
    del df, acc
    print(f"  batch {bi//BATCH+1} ({bi+len(batch)}/{len(uni)})", flush=True)

R = pl.DataFrame(rows, schema=["wallet", "nfill_train", "taker_share_train", "med_hold_train"], orient="row")
R.write_parquet("out/eligibility_train.parquet")
# apply the SAME thresholds on training-only variables
passes = R.filter((pl.col("nfill_train") >= 200) & (pl.col("taker_share_train") >= TAKER) &
                  (pl.col("med_hold_train") >= 1.0) & (pl.col("med_hold_train") <= 24.0))
keep = set(passes["wallet"].to_list())
present = set(R["wallet"].to_list())
missing_from_tape = cohort - present
print(f"\n=== TRAIN-ONLY ELIGIBILITY on the {len(cohort)} cohort wallets ===")
print(f"  wallets with training tape data: {len(present)} (missing {len(missing_from_tape)})")
for var, thr in [("nfill_train>=200", (R['nfill_train'] >= 200)), ("taker_share_train>=0.70", (R['taker_share_train'] >= TAKER)),
                 ("med_hold_train in [1,24]", (R['med_hold_train'] >= 1.0) & (R['med_hold_train'] <= 24.0))]:
    print(f"    {var:26s}: {int(thr.sum())}/{R.height} pass")
print(f"  STILL qualify under train-only eligibility: {len(keep)}/{len(cohort)} ({len(keep)/len(cohort)*100:.1f}%)")
print(f"  would be DROPPED (leak-driven inclusions): {len(cohort)-len(keep)}")
open("out/cohort_K_trainonly.txt", "w").write("\n".join(sorted(keep)) + "\n")
print("wrote out/cohort_K_trainonly.txt, out/eligibility_train.parquet")
