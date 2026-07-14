"""
Freeze the ONE canonical recurring top-decile cohort (audit round-3 fix for the 3-conflated-cohorts problem).
TRAIN-ONLY, recurrence-based, leak-free, persisted to disk so M-phase / Phase-1/2 all read the SAME list.
Rule: within each TRAIN month (b_ts < 2026-02-01), rank wallets by day-weighted neut_8h (drift-stripped 8h markout,
reproducible from the parquet — no external bars); flag monthly top-decile; a wallet is "recurring" if top-decile in
>= K eligible train months (eligible = >= 8 active days that month). PRIMARY K=2 (recurring); strict subset K=3.
Also freezes a CONTINUOUS per-wallet train conviction rank (mean monthly percentile) for the M1 forward model.
Writes out/cohort_M_frozen.parquet (+ .txt list). RAM-light, deterministic, no bar pricing.
"""
import numpy as np, polars as pl

TRAIN_HI_MS = 1_769_904_000_000          # 2026-02-01 (cohort train/test boundary; embargo Feb, test Mar+)
MIN_D = 8; DEC = 0.10; K_PRIMARY = 2; K_STRICT = 3

df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "notl", "neut_8h")
df = df.filter(pl.col("b_ts") < TRAIN_HI_MS).with_columns(          # TRAIN ONLY — no test/embargo data enters the freeze
    month=pl.from_epoch(pl.col("b_ts"), time_unit="ms").dt.strftime("%Y-%m"), day=(pl.col("b_ts") // 86_400_000))
months = sorted(df["month"].unique().to_list())
print(f"TRAIN months: {months[0]}..{months[-1]} ({len(months)})", flush=True)

# day-weighted neut_8h per wallet-month; eligibility >= MIN_D active days
wmd = df.group_by("wallet", "month", "day").agg(d8=pl.col("neut_8h").mean())
wm = wmd.group_by("wallet", "month").agg(m8=pl.col("d8").mean(), nd=pl.len()).filter(pl.col("nd") >= MIN_D)

# per-month top-decile flag + percentile rank (continuous conviction)
frames = []
for mo in months:
    sub = wm.filter(pl.col("month") == mo)
    v = sub["m8"].to_numpy(); thr = np.quantile(v, 1 - DEC)
    pct = (v[:, None] >= v[None, :]).mean(axis=1)                    # fraction of field this wallet beats (1.0 = best)
    frames.append(sub.with_columns(top=pl.Series((v >= thr).astype(int)), pctile=pl.Series(pct)))
WM = pl.concat(frames)

rec = WM.group_by("wallet").agg(n_elig=pl.len(), n_top=pl.col("top").sum(), conv=pl.col("pctile").mean())
# behavioral traits (train-only, pre-specified): size, activity, direction bias
tr = df.group_by("wallet").agg(
    notl_med=pl.col("notl").median(), notl_mean=pl.col("notl").mean(),
    dir_bias=pl.col("dir").mean(), n_entries=pl.len(),
    n_days=pl.col("day").n_unique(), n_coins=pl.col("coin").n_unique())
rec = rec.join(tr, on="wallet", how="left").sort("n_top", "conv", descending=True)

for K in [1, 2, 3, 4]:
    print(f"  recurring top-decile in >= {K} train months: {rec.filter(pl.col('n_top') >= K).height} wallets")
prim = rec.filter(pl.col("n_top") >= K_PRIMARY)
rec = rec.with_columns(
    cohort=pl.when(pl.col("n_top") >= K_STRICT).then(pl.lit("strict"))
             .when(pl.col("n_top") >= K_PRIMARY).then(pl.lit("primary"))
             .otherwise(pl.lit("none")))
rec.write_parquet("out/cohort_M_frozen.parquet")
with open("out/cohort_M_frozen.txt", "w") as f:
    f.write(f"# canonical recurring top-decile cohort — TRAIN-ONLY neut_8h, top-decile in >= {K_PRIMARY} of {len(months)} train months\n")
    f.write(f"# PRIMARY (>= {K_PRIMARY} months): {prim.height} wallets | STRICT (>= {K_STRICT}): {rec.filter(pl.col('n_top')>=K_STRICT).height}\n")
    for w in prim["wallet"].to_list():
        f.write(w + "\n")
print(f"\nFROZEN -> out/cohort_M_frozen.{{parquet,txt}} | PRIMARY cohort N={prim.height} (>= {K_PRIMARY} mo), "
      f"STRICT N={rec.filter(pl.col('n_top')>=K_STRICT).height} (>= {K_STRICT} mo)")
print("  primary cohort trait medians:",
      f"size≈${prim['notl_med'].median():,.0f} | dir_bias={prim['dir_bias'].mean():+.2f} | "
      f"entries/wallet={prim['n_entries'].median():.0f} | conv={prim['conv'].mean():.2f}")
