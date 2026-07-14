"""Phase-1 verification for report v2: (1) rolling monthly forward-decile at 4h AND 8h (horizon check on the +4.48 claim);
(2) whether the fixed-121 cohort was ever forward-tested; (3) day-block 95% CIs for the raw term structure. Light, no bars."""
import numpy as np, polars as pl
from scipy import stats as st
RNG = np.random.default_rng(0); MIN_D = 8; DEC = 0.10

df = pl.read_parquet("out/cohort_K_entries.parquet")
df = df.with_columns(month=pl.from_epoch(pl.col("b_ts"), time_unit="ms").dt.strftime("%Y-%m"),
                     day=(pl.col("b_ts") // 86_400_000))

# ---- (1) rolling monthly forward-decile at 4h and 8h (neut, day-weighted) ----
print("=== rolling monthly re-ranked top-decile, forward next-month (neut, day-weighted) ===")
for hz, col in [("4h", "neut_4h"), ("8h", "neut_8h")]:
    wmd = df.group_by("wallet", "month", "day").agg(d=pl.col(col).mean())
    wm = wmd.group_by("wallet", "month").agg(m=pl.col("d").mean(), nd=pl.len()).filter(pl.col("nd") >= MIN_D)
    months = sorted(wm["month"].unique().to_list())
    diffs, tops, fields = [], [], []
    for i in range(len(months) - 1):
        a = wm.filter(pl.col("month") == months[i]).with_columns(top=(pl.col("m") >= pl.col("m").quantile(1 - DEC)).cast(pl.Int8)).select("wallet", "top")
        b = wm.filter(pl.col("month") == months[i + 1]).select("wallet", nxt=pl.col("m"))
        j = a.join(b, on="wallet", how="inner")
        if j.height < 20: continue
        t = j.filter(pl.col("top") == 1)["nxt"].to_numpy(); f = j.filter(pl.col("top") == 0)["nxt"].to_numpy()
        if len(t) and len(f): diffs.append(t.mean() - f.mean()); tops.append(t.mean()); fields.append(f.mean())
    diffs = np.array(diffs)
    boot = np.array([np.mean(diffs[RNG.integers(0, len(diffs), len(diffs))]) for _ in range(5000)])
    print(f"  {hz}: top {np.mean(tops):+.2f} vs field {np.mean(fields):+.2f} = DIFF {diffs.mean():+.2f} "
          f"[{np.percentile(boot,2.5):+.2f},{np.percentile(boot,97.5):+.2f}] | {int((diffs>0).sum())}/{len(diffs)} folds +")

# ---- (2) was the FIXED 121 cohort ever forward-tested for an over-field markout estimate? ----
print("\n=== fixed-121 cohort forward test (validation-period neut_8h, day-weighted, vs field) — for transparency ===")
frozen = set(l.strip() for l in open("out/cohort_M_frozen.txt") if l.strip() and not l.startswith("#"))
te = df.filter(pl.col("split") == "test")
wd = te.group_by("wallet", "day").agg(d=pl.col("neut_8h").mean())
wm = wd.group_by("wallet").agg(m=pl.col("d").mean(), nd=pl.len()).filter(pl.col("nd") >= 5)
wm = wm.with_columns(coh=pl.col("wallet").is_in(list(frozen)))
coh = wm.filter(pl.col("coh"))["m"].to_numpy(); fld = wm.filter(~pl.col("coh"))["m"].to_numpy()
# day-block bootstrap over test days for the cohort-minus-field diff
days = np.sort(te["day"].unique().to_numpy())
print(f"  121-cohort validation neut_8h day-weighted: cohort {np.mean(coh):+.2f} (n={len(coh)}) vs field {np.mean(fld):+.2f} (n={len(fld)}) "
      f"| DIFF {np.mean(coh)-np.mean(fld):+.2f} bp  [NOTE: this is the FIXED cohort, distinct from the rolling decile above]")

# ---- (3) day-block 95% CI for the raw term structure (entry-weighted mean per coin x horizon) ----
print("\n=== raw term-structure entry-weighted mean with day-block 95% CI (full sample) ===")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; LB = ["1h", "2h", "4h", "8h", "24h"]; NB = 2000
out = {}
for coin in COINS + ["ALL"]:
    sub = df if coin == "ALL" else df.filter(pl.col("coin") == coin)
    dymean = sub.group_by("day").agg([pl.col(f"raw_{h}").mean().alias(h) for h in LB], n=pl.len()).sort("day")
    D = {h: dymean[h].to_numpy() for h in LB}; N = dymean["n"].to_numpy(); nd = len(N)
    def wmean(vals, wts):                                       # NaN-aware weighted mean (24h has unpriceable tail days)
        m = np.isfinite(vals)
        return np.average(vals[m], weights=wts[m]) if m.any() and wts[m].sum() > 0 else np.nan
    row = {}
    for h in LB:
        pt = wmean(D[h], N)
        bs = np.array([wmean(D[h][idx], N[idx]) for idx in (RNG.integers(0, nd, nd) for _ in range(NB))])
        row[h] = (pt, np.nanpercentile(bs, 2.5), np.nanpercentile(bs, 97.5))
    out[coin] = row
    print(f"  {coin:4}: " + "  ".join(f"{h} {row[h][0]:+.2f}[{row[h][1]:+.1f},{row[h][2]:+.1f}]" for h in LB))
import json
json.dump({c: {h: list(v) for h, v in r.items()} for c, r in out.items()}, open("out/termstructure_ci.json", "w"))
print("saved out/termstructure_ci.json")
