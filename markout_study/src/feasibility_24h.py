"""
FEASIBILITY: can we filter to a cohort of mid/low-freq TAKERS with enough 24h-markout samples to
statistically significy a realistic edge? Pure power arithmetic on markout_stats.parquet (full-window
aggregate; fine for SIZING — we ask 'are there enough samples', not an OOS claim). In-memory, no tape.

MDE(edge, bp) = 2.8 * sigma_perentry / sqrt(N)   (2.8 ~= z_.975+z_.80, 80% power at 5%).
Two estimands: (i) PER-WALLET significance; (ii) POOLED-COHORT significance (portfolio selection rule).
"""
import numpy as np, polars as pl

H = "24h"
ms = pl.read_parquet("out/markout_stats.parquet").filter(pl.col("horizon") == H)
print(f"24h rows (wallet x coin): {ms.height}   distinct wallets: {ms['wallet'].n_unique()}\n")

# ---- per-entry 24h markout sigma: std = avg_edge_bps / sharpe (sharpe = mean/std per entry) ----
s = ms.filter((pl.col("sharpe").abs() > 1e-6) & pl.col("avg_edge_bps").is_finite() & (pl.col("n") >= 30))
sigma = (s["avg_edge_bps"] / s["sharpe"]).abs().to_numpy()
sigma = sigma[np.isfinite(sigma) & (sigma > 0) & (sigma < 5000)]
nvec = s["n"].to_numpy()[:sigma.size] if False else None
sig_med = np.median(sigma); sig_mean = float(np.average(sigma))
print(f"per-entry 24h markout sigma (bp):  median={sig_med:.0f}  mean={sig_mean:.0f}  "
      f"p25={np.percentile(sigma,25):.0f} p75={np.percentile(sigma,75):.0f}")
SIG = sig_med
print(f"  -> using sigma = {SIG:.0f} bp/entry for MDE arithmetic\n")

# ---- clustering: how much does n_eff shrink n? (the user's effective-N point) ----
c = ms.filter((pl.col("n") >= 30) & pl.col("n_eff").is_finite())
ratio = (c["n_eff"] / c["n"]).to_numpy()
ratio = ratio[np.isfinite(ratio)]
print(f"n_eff / n  (independence retention): median={np.median(ratio):.2f}  "
      f"p25={np.percentile(ratio,25):.2f} p75={np.percentile(ratio,75):.2f}")
print("  (a 24h entry overlaps neighbors -> effective independent samples < raw entry count)\n")

# ---- per-WALLET 24h sample availability (pooled across coins) ----
perw = ms.group_by("wallet").agg(n=pl.col("n").sum(), n_eff=pl.col("n_eff").sum())
n_all = perw["n"].to_numpy(); neff_all = perw["n_eff"].to_numpy()
print(f"per-wallet total 24h entries: median={np.median(n_all):.0f}  "
      f"p75={np.percentile(n_all,75):.0f} p90={np.percentile(n_all,90):.0f} p99={np.percentile(n_all,99):.0f} max={n_all.max():.0f}")
for thr in [50, 100, 200, 500, 1000, 2000, 5000]:
    print(f"   wallets with >= {thr:5d} 24h entries: {int((n_all>=thr).sum()):5d}"
          f"   (>= that many n_eff: {int((neff_all>=thr).sum()):5d})")
print()

# ---- (i) PER-WALLET MDE: what edge can ONE wallet's own samples resolve? ----
print("PER-WALLET feasibility (raw 24h markout, sigma={:.0f}bp):".format(SIG))
print("  n_entries   MDE(raw)   MDE(coin-day-neut, ~sigma/3.5*)")
for n in [50, 100, 300, 1000, 3000, 8000]:
    mde = 2.8 * SIG / np.sqrt(n)
    mde_neut = 2.8 * (SIG/3.5) / np.sqrt(n)   # neut cuts sigma ~3.5x (Stage E/F: MDE 160->~13 raw->neut+pool)
    print(f"   {n:6d}     {mde:6.0f}bp    {mde_neut:6.0f}bp")
print("  * neutralization factor illustrative (Stage E/F variance reduction). A 'realistic edge' we'd act on ~ +10-25bp.\n")

# ---- (ii) POOLED-COHORT MDE: a selection RULE over K mid/low-freq takers ----
print("POOLED-COHORT feasibility (a selection rule; total N = K wallets x n_per):")
print("  Assume mid/low-freq taker ~ 150 24h entries each over the window.")
n_per = 150
for K in [20, 50, 100, 300, 1000]:
    Ntot = K * n_per
    Neff = Ntot * np.median(ratio)                    # honor clustering
    mde_raw = 2.8 * SIG / np.sqrt(Neff)
    mde_neut = 2.8 * (SIG/3.5) / np.sqrt(Neff)
    print(f"   K={K:5d} wallets -> N={Ntot:7d} (N_eff~{Neff:.0f})   MDE_raw={mde_raw:5.1f}bp   MDE_neut={mde_neut:4.1f}bp")
print("\n  care-about edge ~ +10-25 bp.  Feasible when MDE <= care-about.")
