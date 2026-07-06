"""
Stage K, Job B: ISOLATE the copyable cohort = {taker-dominant AND 1-24h median hold AND large N},
characterize it, and read its EXISTING 24h markouts (train + OOS test) equal-weight vs entry-weight.
In-memory join of out/hold_size_dist.parquet (taker_share/hold/bands) + out/wallet_level_persistence.parquet
(train/test 24h markout). Freezes out/cohort_K.txt. RAM-trivial.
NOTE: this reads the existing (dollar-ish) 24h markout; Job C will add the 4h horizon + coin-month-neut +
proper per-entry equal-weight + regime split. This is the FIRST honest look.
"""
import numpy as np, polars as pl
from scipy import stats as st
RNG = np.random.default_rng(11); BP = 1e4

hs = pl.read_parquet("out/hold_size_dist.parquet")
wl = pl.read_parquet("out/wallet_level_persistence.parquet").rename({"n": "n_train"})
df = hs.join(wl, on="wallet", how="inner")
print(f"wallets with both hold-features and markout: {df.height}\n")

# ---- COHORT FILTERS (outcome-independent: behavior + sample size only) ----
TAKER = 0.70
cohort = df.filter(
    (pl.col("taker_share") >= TAKER) &
    (pl.col("med_hold_h") >= 1.0) & (pl.col("med_hold_h") <= 24.0) &
    (pl.col("n_train") >= 200)
)
print(f"=== COHORT: taker_share>={TAKER} AND median hold in [1h,24h] AND n_train>=200 ===")
print(f"    size: {cohort.height} wallets")
# hold-floor sensitivity (audit B4: high-N wallets may hold <1h and be excised)
for lo, lab in [(0.5, ">=0.5h"), (1.0, ">=1h"), (2.0, ">=2h")]:
    c = df.filter((pl.col("taker_share") >= TAKER) & (pl.col("med_hold_h") >= lo) &
                  (pl.col("med_hold_h") <= 24.0) & (pl.col("n_train") >= 200))
    print(f"      hold floor {lab:7s}: {c.height} wallets")
# by sample tier
print("    by n_train tier:")
for lo, hi, lab in [(200,500,"200-500"),(500,1000,"500-1000"),(1000,10**9,">=1000")]:
    c = cohort.filter((pl.col("n_train")>=lo)&(pl.col("n_train")<hi))
    print(f"      {lab:9s}: {c.height}")

cohort.select("wallet").write_csv("out/cohort_K.txt", include_header=False)
cohort.write_parquet("out/cohort_K_features.parquet")

# ---- CHARACTERIZATION (who are they) ----
print("\n=== CHARACTERIZATION ===")
c = cohort
print(f"  taker_share: median {c['taker_share'].median():.2f}  (all >= {TAKER})")
print(f"  median hold (h): p25 {c['med_hold_h'].quantile(0.25):.1f} / med {c['med_hold_h'].median():.1f} / p75 {c['med_hold_h'].quantile(0.75):.1f}")
print(f"  n_train (decisions): med {int(c['n_train'].median())} / p90 {int(c['n_train'].quantile(0.9))} / max {int(c['n_train'].max())}")
print(f"  n_copyable (taker 1-24h round-trips): med {int(c['n_copyable'].median())}")
# hold-band composition (cohort-aggregate share of taker round-trips)
bands = ["lt15m","15m_1h","1_4h","4_24h","24_72h","gt72h"]
tot = {b: int(c["nb_"+b].sum()) for b in bands}; s = sum(tot.values())
print("  hold-band mix of their taker round-trips:")
for b in bands: print(f"      {b:8s}: {tot[b]/s*100:5.1f}%")

# ---- MARKOUTS: do they have positive markout? (existing 24h; train + OOS test) ----
print("\n=== 24h MARKOUTS (existing metric; equal-weight across wallets vs entry-weighted) ===")
def look(sub, lab):
    m = sub.filter((pl.col("n_test")>=30) & pl.col("edge").is_finite() & pl.col("edge_test").is_finite())
    if m.height < 20: print(f"  {lab}: N={m.height} too few"); return
    tr = m["edge"].to_numpy()*BP; te = m["edge_test"].to_numpy()*BP; w = m["n_train"].to_numpy().astype(float)
    def boot(x, wt=None):
        idx=np.arange(x.size)
        if wt is None: return np.percentile([x[RNG.choice(idx,idx.size,True)].mean() for _ in range(2000)],[2.5,97.5])
        return np.percentile([np.average(x[s:=RNG.choice(idx,idx.size,True)], weights=wt[s]) for _ in range(2000)],[2.5,97.5])
    tr_ew, te_ew = tr.mean(), te.mean()
    tr_vw, te_vw = np.average(tr,weights=w), np.average(te,weights=w)
    lo,hi = boot(te)          # equal-weight OOS CI (the honest skill estimand)
    frac_tr = (tr>0).mean(); frac_te = (te>0).mean()
    print(f"  {lab} (N={m.height}, median n_test={int(m['n_test'].median())}):")
    print(f"      TRAIN  edge: equal-wt {tr_ew:+6.1f}bp | entry-wt {tr_vw:+6.1f}bp | frac wallets>0 {frac_tr:.2f}")
    print(f"      OOS TEST edge: equal-wt {te_ew:+6.1f}bp CI[{lo:+.1f},{hi:+.1f}] | entry-wt {te_vw:+6.1f}bp | frac>0 {frac_te:.2f}")
look(cohort, "FULL cohort")
for lo,hi,lab in [(200,500,"200-500"),(500,1000,"500-1000"),(1000,10**9,">=1000")]:
    look(cohort.filter((pl.col("n_train")>=lo)&(pl.col("n_train")<hi)), f"tier {lab}")
print("\n(caveat: 24h existing metric; Job C adds 4h horizon + coin-month-neut + regime. Equal-weight is the honest read.)")
