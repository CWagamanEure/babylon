"""
Stage K, Job D: the honest read. Cohort markout TERM STRUCTURE (equal-weight across wallets, the honest skill
estimand) at 1/2/4/8/24h, raw + drift-stripped, TRAIN and TEST, with wallet-clustered bootstrap CI + MDE.
Plus direction split (a down test window makes shorts win / longs lose on BETA) and regime x dir at 4h.
In-memory on out/cohort_K_entries.parquet. Answers: do they have positive markout at their true (~2-4h) horizon?
"""
import numpy as np, polars as pl
RNG = np.random.default_rng(3)
df = pl.read_parquet("out/cohort_K_entries.parquet")
HZ = ["1h", "2h", "4h", "8h", "24h"]
print(f"entries: {df.height} | wallets: {df['wallet'].n_unique()}")
print(f"net direction (test): {df.filter(pl.col('split')=='test')['dir'].mean():+.3f}  (+=net long)\n")

def cohort_ew(sub, col, min_e=10):
    """per-wallet mean of col (>=min_e non-null entries), then equal-weight across wallets + wallet-boot CI."""
    g = (sub.select("wallet", col).drop_nulls()
         .group_by("wallet").agg(m=pl.col(col).mean(), n=pl.len()).filter(pl.col("n") >= min_e))
    if g.height < 20: return None
    x = g["m"].to_numpy()
    boot = np.array([x[RNG.choice(x.size, x.size, True)].mean() for _ in range(2000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    mde = 2.8 * x.std() / np.sqrt(x.size)
    return x.mean(), lo, hi, mde, x.size

print("=== TERM STRUCTURE — equal-weight across wallets, bps  [95% CI]  (MDE) ===")
for split in ["train", "test"]:
    s = df.filter(pl.col("split") == split)
    print(f"\n  {split.upper()}:")
    print(f"    {'horizon':8s} {'RAW':>24s}   {'DRIFT-STRIPPED (neut)':>24s}")
    for hl in HZ:
        r = cohort_ew(s, f"raw_{hl}"); n = cohort_ew(s, f"neut_{hl}")
        rs = f"{r[0]:+6.1f} [{r[1]:+5.1f},{r[2]:+5.1f}] MDE{r[3]:.1f}" if r else "n/a"
        ns = f"{n[0]:+6.1f} [{n[1]:+5.1f},{n[2]:+5.1f}] MDE{n[3]:.1f}" if n else "n/a"
        print(f"    {hl:8s} {rs:>24s}   {ns:>24s}")

print("\n=== DIRECTION SPLIT (test, entry-level mean bps) — exposes beta in the down window ===")
t = df.filter(pl.col("split") == "test")
print(f"    {'horizon':8s} {'LONG raw':>12s} {'SHORT raw':>12s} {'LONG neut':>12s} {'SHORT neut':>12s}")
for hl in HZ:
    row = []
    for col in [f"raw_{hl}", f"raw_{hl}", f"neut_{hl}", f"neut_{hl}"]:
        pass
    lo_r = t.filter(pl.col("dir")==1)[f"raw_{hl}"].drop_nulls().mean()
    sh_r = t.filter(pl.col("dir")==-1)[f"raw_{hl}"].drop_nulls().mean()
    lo_n = t.filter(pl.col("dir")==1)[f"neut_{hl}"].drop_nulls().mean()
    sh_n = t.filter(pl.col("dir")==-1)[f"neut_{hl}"].drop_nulls().mean()
    f=lambda v:f"{v:+.1f}" if v is not None else "n/a"
    print(f"    {hl:8s} {f(lo_r):>12s} {f(sh_r):>12s} {f(lo_n):>12s} {f(sh_n):>12s}")

print("\n=== REGIME x DIRECTION at 4h (test, drift-stripped bps) — timing vs beta ===")
print(f"    {'regime':8s} {'LONG neut':>14s} {'SHORT neut':>14s}   n_long / n_short")
for rg in ["BULL", "CHOP", "BEAR"]:
    tr = t.filter(pl.col("regime") == rg)
    lo = tr.filter(pl.col("dir")==1)["neut_4h"].drop_nulls()
    sh = tr.filter(pl.col("dir")==-1)["neut_4h"].drop_nulls()
    f=lambda x:(f"{x.mean():+.1f}" if x.len()>0 else "n/a")
    print(f"    {rg:8s} {f(lo):>14s} {f(sh):>14s}   {lo.len()} / {sh.len()}")

print("\n(equal-weight = honest skill estimand. neut strips coin-month drift. A down test window makes raw")
print(" shorts look good on beta alone -> the drift-stripped/neut columns are the skill read.)")
