"""Split his monthly taker/maker fills into per-wallet parquet (our schema), so parameter
sweeps (lag / net / directional / top-N) read tiny per-wallet files instead of re-reshaping
~3.6GB of months every run. See other_repo_notes/README.txt.

Memory-safe on 8GB:
  Phase 1  per month: streaming `sink_parquet` of the reshaped SUPERSET-only rows -> one
           intermediate file each (sink streams; never materializes a whole month).
  Phase 2  regroup across months into data/follow/fills_his/{wallet}.parquet in small
           wallet-batches (a batch of whales can't blow memory).

Resumable: Phase 1 skips months whose intermediate exists; Phase 2 skips the batch if its
first wallet file already exists. Output schema matches fills_source._SCHEMA (sans `wallet`),
so ParquetFillsProvider / convergence_test.py read it directly.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import polars as pl

from babylon.follow.skill import ZERO_HASH

_NOTES = Path("other_repo_notes")
_NONZERO = "0x" + "1" * 64
_MONTHS = ["fills_Feb.parquet", "fills_Mar.parquet", "fills_Apr.parquet",
           "fills_May.parquet", "fills_Jun.parquet"]


def _hash_expr() -> pl.Expr:
    return pl.when(pl.col("zhash")).then(pl.lit(ZERO_HASH)).otherwise(pl.lit(_NONZERO)).alias("hash")


def _reshaped(path: Path, superset: list[str]) -> pl.LazyFrame:
    """His one-row-per-trade taker/maker file -> our per-wallet schema (lazy).
    Taker rows keep side + crossed=True; maker rows flip side, crossed=False."""
    base = pl.scan_parquet(path)
    cols_tail = [pl.lit(0.0).alias("startPosition"), _hash_expr(), "tid"]
    tk = base.filter(pl.col("taker").is_in(superset)).select(
        pl.col("taker").alias("wallet"), pl.col("ts").alias("time"), "coin", "px", "sz",
        "side", pl.lit(True).alias("crossed"), *cols_tail)
    mk = base.filter(pl.col("maker").is_in(superset)).select(
        pl.col("maker").alias("wallet"), pl.col("ts").alias("time"), "coin", "px", "sz",
        pl.when(pl.col("side") == "B").then(pl.lit("A")).otherwise(pl.lit("B")).alias("side"),
        pl.lit(False).alias("crossed"), *cols_tail)
    return pl.concat([tk, mk])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/follow/fills_his"))
    ap.add_argument("--batch", type=int, default=100, help="wallets per Phase-2 batch")
    ap.add_argument("--only-month", type=str, default="", help="Phase-1 smoke: one month then stop")
    args = ap.parse_args()

    out = args.out
    tmp = out / "_tmp"
    out.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(exist_ok=True)
    superset = pl.read_csv(_NOTES / "superset_wallets.csv")["wallet"].to_list()
    print(f"superset wallets: {len(superset)}")

    # ---- Phase 1: streaming reshape -> intermediate per month ----
    months = [args.only_month] if args.only_month else _MONTHS
    for m in months:
        dst = tmp / m
        if dst.exists():
            print(f"phase1 skip (exists): {dst}")
            continue
        _reshaped(_NOTES / m, superset).sink_parquet(dst)
        n = pl.scan_parquet(dst).select(pl.len()).collect().item()
        print(f"phase1 {m} -> {dst}  rows={n:,}")
    if args.only_month:
        print("only-month smoke done (Phase 2 skipped)")
        return

    # ---- Phase 2: wallet-batched regroup across months ----
    tmp_files = [str(tmp / m) for m in _MONTHS]
    written = skipped = 0
    for i in range(0, len(superset), args.batch):
        batch = superset[i:i + args.batch]
        if (out / f"{batch[0]}.parquet").exists():  # resume: batch already done
            skipped += len(batch)
            continue
        df = pl.scan_parquet(tmp_files).filter(pl.col("wallet").is_in(batch)).collect(engine="streaming")
        parts = df.partition_by("wallet", as_dict=True)
        for k, wdf in parts.items():
            w = k[0] if isinstance(k, tuple) else k
            wdf.drop("wallet").sort("time").write_parquet(out / f"{w}.parquet")
            written += 1
        print(f"phase2 batch {i // args.batch}: +{len(parts)} wallets (written={written})")
    print(f"DONE: written={written} skipped={skipped} -> {out}")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
