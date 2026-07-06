"""
Feature-conditioned OOS hunt over out/steelman_features.parquet.
For each TRAIN-only feature (and combinations), threshold/sort and report OOS te_vw with N and
a bootstrap 95% CI. Also tests the user's two named hypotheses directly:
  (1) high taker_share (copyable/aggressive) persists vs low taker_share (maker) doesn't
  (2) directional (few coins / high top_coin_share) vs MM (many coins) persistence differs
Cheap: reads a small parquet already on disk, no tape access.
"""
import numpy as np, polars as pl
from numpy.random import default_rng

R = pl.read_parquet("out/steelman_features.parquet")
print(f"N wallets in steelman_features: {R.height}")
rng = default_rng(0)


def boot_ci(x, n=4000):
    if len(x) < 5:
        return (np.nan, np.nan)
    bs = np.array([rng.choice(x, len(x)).mean() for _ in range(n)])
    return np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def report(mask, label):
    s = R.filter(mask)
    if s.height < 8:
        print(f"  {label:42s} n={s.height:5d}  (too few)")
        return None
    tv = s["te_vw"].to_numpy()
    lo, hi = boot_ci(tv)
    tb = s["te_bps"].to_numpy()
    print(f"  {label:42s} n={s.height:5d}  te_vw={tv.mean():+8.2f}  CI=[{lo:+7.2f},{hi:+7.2f}]  "
          f"te_bps(eqw)={tb.mean():+7.2f}  %te_vw>0={100*np.mean(tv>0):5.1f}%")
    return s.height, tv.mean(), lo, hi


print("\n=== baseline ===")
report(pl.col("ntr") > 0, "ALL wallets")
report(pl.col("tr_vw") > 0, "train vw>0")
report(pl.col("tr_t") >= 2, "train t>=2")
report(pl.col("tr_t") >= 3, "train t>=3")

print("\n=== HYPOTHESIS 1: taker_share (copyable/aggressive vs maker) ===")
q = R["taker_share"].to_numpy()
qs = np.nanquantile(q, [0.25, 0.5, 0.75, 0.9])
print(f"  taker_share quartiles: {qs}")
report(pl.col("taker_share") >= 0.8, "taker_share>=0.8 (very aggressive)")
report(pl.col("taker_share") >= 0.5, "taker_share>=0.5")
report(pl.col("taker_share") < 0.2, "taker_share<0.2 (mostly maker)")
report(pl.col("taker_share") < 0.05, "taker_share<0.05 (pure maker)")
report((pl.col("taker_share") >= 0.8) & (pl.col("tr_t") >= 2), "taker>=0.8 & tr_t>=2")
report((pl.col("taker_share") >= 0.5) & (pl.col("tr_vw") > 0), "taker>=0.5 & train vw>0")

print("\n=== exit_maker_share (closing side passive = inventory-style) ===")
report(pl.col("exit_maker") >= 0.8, "exit_maker>=0.8 (exits mostly passive)")
report(pl.col("exit_maker") < 0.2, "exit_maker<0.2 (exits mostly taker/aggressive)")

print("\n=== HYPOTHESIS 2: directional (few coins) vs MM (many coins) ===")
report(pl.col("n_coins") <= 1, "n_coins<=1 (single-coin)")
report(pl.col("n_coins") <= 2, "n_coins<=2 (directional)")
report(pl.col("n_coins") >= 4, "n_coins>=4 (multi-coin/MM-like)")
report(pl.col("top_coin_share") >= 0.9, "top_coin_share>=0.9 (concentrated)")
report(pl.col("top_coin_share") < 0.5, "top_coin_share<0.5 (diversified)")

print("\n=== holding period (med_hold_h, sz-wtd TRAIN) ===")
qh = np.nanquantile(R["med_hold_h"].to_numpy(), [0.25, 0.5, 0.75, 0.9])
print(f"  med_hold_h quartiles: {qh}")
report(pl.col("med_hold_h") < 1, "med_hold_h<1h (fast round-trip)")
report(pl.col("med_hold_h") < 0.25, "med_hold_h<15min (HFT)")
report(pl.col("med_hold_h") >= 24, "med_hold_h>=24h (slow/directional)")
report(pl.col("med_hold_h") >= 168, "med_hold_h>=168h (>=1wk, likely legacy-bag risk)")

print("\n=== monthly hit rate / sharpe / n_mo (train consistency) ===")
report(pl.col("mo_hit") >= 0.8, "mo_hit>=0.8 (train: profitable most months)")
report((pl.col("mo_hit") >= 0.8) & (pl.col("n_mo") >= 4), "mo_hit>=0.8 & n_mo>=4")
report(pl.col("tr_sharpe") > 0, "tr_sharpe>0")

print("\n=== COMBINATIONS aimed at the user's exact story: fast, high-taker, directional, consistent ===")
report((pl.col("taker_share") >= 0.5) & (pl.col("n_coins") <= 2), "taker>=0.5 & n_coins<=2")
report((pl.col("taker_share") >= 0.5) & (pl.col("med_hold_h") < 24), "taker>=0.5 & hold<24h")
report((pl.col("taker_share") >= 0.5) & (pl.col("tr_t") >= 2) & (pl.col("n_coins") <= 3),
       "taker>=0.5 & tr_t>=2 & n_coins<=3")
report((pl.col("taker_share") >= 0.7) & (pl.col("tr_vw") > 0) & (pl.col("mo_hit") >= 0.7),
       "taker>=0.7 & train vw>0 & mo_hit>=0.7")
report((pl.col("exit_maker") < 0.3) & (pl.col("tr_t") >= 2), "exit_maker<0.3 (aggressive exits) & tr_t>=2")

# systematic scan: bin every numeric feature into terciles, report top/bottom tercile OOS te_vw
print("\n=== SYSTEMATIC TERCILE SCAN (every feature) ===")
feats = ["taker_share", "exit_maker", "med_hold_h", "n_coins", "top_coin_share", "mo_hit",
         "tr_t", "tr_vw", "tr_sharpe", "ntr"]
best = []
for f in feats:
    x = R[f].to_numpy()
    fin = np.isfinite(x)
    if fin.sum() < 30:
        continue
    q33, q67 = np.nanquantile(x[fin], [1/3, 2/3])
    for lab, mask in [("low", pl.col(f) <= q33), ("high", pl.col(f) >= q67)]:
        res = report(mask, f"{f} {lab} tercile (<= or >= {q33 if lab=='low' else q67:.3g})")
        if res is not None:
            n, m, lo, hi = res
            best.append((f, lab, n, m, lo, hi))

print("\n=== ALL tercile results ranked by OOS te_vw (descending) ===")
best.sort(key=lambda r: -r[3])
for f, lab, n, m, lo, hi in best:
    sig = "  <-- CI excludes 0" if (lo > 0 or hi < 0) else ""
    print(f"  {f:16s} {lab:5s} n={n:5d} te_vw={m:+7.2f} CI=[{lo:+7.2f},{hi:+7.2f}]{sig}")

R.write_parquet("out/steelman_hunt_done.marker.parquet")
