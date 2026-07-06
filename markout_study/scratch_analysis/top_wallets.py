import polars as pl

pl.Config.set_tbl_rows(25)
pl.Config.set_tbl_width_chars(200)

SRC = "/Users/corywagamaneure/bablyon/markout_study/out/cohort_K_entries.parquet"
NFLOOR = 100

def build_table(horizon: str, split: str = "train") -> pl.DataFrame:
    col = f"raw_{horizon}"
    df = (
        pl.scan_parquet(SRC)
        .filter(pl.col("split") == split)
        .filter(pl.col(col).is_not_null())
        .select("wallet", "b_ts", "notl", col)
        .sort(["wallet", "b_ts"])
        .with_columns(
            pl.col(col).cum_sum().over("wallet").alias("_cum"),
        )
        .with_columns(
            pl.col("_cum").cum_max().over("wallet").alias("_cummax"),
        )
        .with_columns(
            (pl.col("_cummax") - pl.col("_cum")).alias("_dd"),
        )
        .group_by("wallet")
        .agg(
            pl.len().alias("n"),
            pl.col(col).mean().alias("mean_bp"),
            pl.col(col).std().alias("std_bp"),
            (pl.col(col) > 0).mean().alias("hit_rate"),
            pl.col("notl").median().alias("median_notl"),
            pl.col("_dd").max().alias("max_dd_bp"),
        )
        .filter(pl.col("n") >= NFLOOR)
        .with_columns(
            (pl.col("mean_bp") / pl.col("std_bp")).alias("sharpe"),
        )
        .sort("mean_bp", descending=True)
        .collect()
    )
    return df

for h in ["1h", "8h"]:
    t = build_table(h, "train")
    print(f"=== horizon {h} | split=train | N-floor={NFLOOR} | n_wallets_eligible={t.height} ===")
    top20 = t.head(20).select(
        "wallet", "n", "mean_bp", "std_bp", "sharpe", "max_dd_bp", "hit_rate", "median_notl"
    )
    print(top20)
    top20.write_parquet(f"/Users/corywagamaneure/bablyon/markout_study/scratch_analysis/top20_{h}_train.parquet")
    print()
