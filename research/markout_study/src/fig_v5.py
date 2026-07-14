"""report v5 figures -> figs_v5/. Rebuilds behavioral (dir-aligned), static (canonical rho), fixed-121 estimand forest,
conditional (corrected caption). Copies unchanged figures from figs_v4."""
import json, shutil; from pathlib import Path
import numpy as np, polars as pl
import matplotlib.pyplot as plt, matplotlib as mpl
mpl.use("Agg")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; COL = {"BTC": "#4c6ef5", "ETH": "#7048e8", "SOL": "#0ca678", "HYPE": "#e8590c"}
FD = "figs_v5"; Path(FD).mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 140, "savefig.dpi": 140, "font.size": 11, "font.family": "DejaVu Sans",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.18,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "axes.titlesize": 12, "legend.frameon": False})
def save(fig, n): fig.savefig(f"{FD}/{n}.png", bbox_inches="tight"); plt.close(fig)
def cap(ax, s, y=-0.30): ax.text(0, y, s, transform=ax.transAxes, fontsize=8.2, color="#666", va="top")
V5 = json.load(open("out/v5.json")); V4 = json.load(open("out/v4.json"))

# p9 behavioral — direction-aligned, recurring-121 vs rest-of-cohort
b = V5["behavioral"]; rec = b["recurring121"]; rest = b["rest_cohort"]
panels = [("Signed pre-entry 8h move (bp)\n(negative = entered against the move)", "signed_pre8h"),
          ("Absolute pre-entry 8h move (bp)", "abs_pre8h"),
          ("Distance from the relevant trailing\nextreme (bp, direction-aligned)", "stretch"),
          ("Realized 2h volatility (bp)", "vol2h")]
fig, axes = plt.subplots(2, 2, figsize=(11, 7)); axes = axes.ravel()
for ax, (title, key) in zip(axes, panels):
    vals = [rec[key], rest[key]]; ax.bar([0, 1], vals, color=["#e8590c", "#4c6ef5"], alpha=0.9, width=0.6)
    ax.axhline(0, color="#888", lw=0.7); ax.set_xticks([0, 1]); ax.set_xticklabels(["recurring 121", "rest of cohort"], fontsize=10)
    ax.set_title(title, fontsize=11)
    for i, v in enumerate(vals): ax.text(i, v, f"{v:g}", ha="center", va="bottom" if v >= 0 else "top", fontsize=10)
fig.suptitle("Entry conditions of the recurring cohort vs the rest (medians)", fontsize=12.5)
fig.text(0.01, 0.005, "Per-entry medians, direction-aligned. Recurring wallets enter after larger adverse moves, further from the trailing extreme, in higher volatility.", fontsize=8.2, color="#666")
fig.tight_layout(rect=[0, 0.02, 1, 1]); save(fig, "p9_behavioral")

# p6 static — canonical rho label
df = pl.read_parquet("out/cohort_K_entries.parquet")
w = (df.group_by("wallet").agg(
        tr=pl.col("raw_8h").filter(pl.col("split") == "train").mean(), ntr=pl.col("split").filter(pl.col("split") == "train").len(),
        va=pl.col("raw_8h").filter(pl.col("split") == "test").mean(), nva=pl.col("split").filter(pl.col("split") == "test").len())
     .filter((pl.col("ntr") >= 30) & (pl.col("nva") >= 20)).with_columns(dec=(pl.col("tr").rank()/pl.len()*10).ceil().clip(1, 10)))
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
dm = w.group_by("dec").agg(m=pl.col("va").mean()).sort("dec")
axes[0].bar(dm["dec"].to_numpy(), dm["m"].to_numpy(), color="#7048e8", alpha=0.85)
axes[0].axhline(0, color="#adb5bd", lw=0.7); axes[0].set_xlabel("training-mean 8h decile (10 = best in-sample)")
axes[0].set_ylabel("validation mean 8h markout (bp)"); axes[0].set_title("Validation return by training decile", fontsize=11.5)
tr = w["tr"].to_numpy(); va = w["va"].to_numpy()
axes[1].scatter(tr, va, s=6, alpha=0.25, color="#495057"); axes[1].axhline(0, color="#adb5bd", lw=0.7); axes[1].axvline(0, color="#adb5bd", lw=0.7)
sr = V5["static_rho"]
axes[1].set_xlabel("training mean 8h markout (bp)"); axes[1].set_ylabel("validation mean 8h markout (bp)")
axes[1].set_title(f"Training vs validation wallet means", fontsize=11.5)
fig.suptitle(f"Static full-history ranking does not generalize (Pearson {sr['pearson']:+.2f}, Spearman {sr['spearman']:+.2f}, n={sr['n']})", fontsize=12.5)
fig.text(0.01, -0.02, "Wallets with >=30 training and >=20 validation entries. One canonical static specification used throughout.", fontsize=8.4, color="#666")
fig.tight_layout(); save(fig, "p6_static")

# p10 fixed-121 estimand forest (no "net"): A absolute, B minus field, C minus fade, x weighting
s = V5["fixed121"]["schemes"]; rows = []
rows.append(("A gross (wallet-day)", s["wd"]["A_gross"], None, None, "#495057"))
rows.append(("A cost-adjusted (wallet-day)", s["wd"]["A_costadj"], None, None, "#868e96"))
for key, lab, col in [("wd", "wallet-day", "#1c7ed6"), ("ew", "equal-wallet", "#e8590c"), ("wcd", "wallet-coin-day", "#0ca678")]:
    B = s[key]["B_minus_field"]; rows.append((f"B: minus field ({lab})", B[0], B[1], B[2], col))
for key, lab, col in [("wd", "wallet-day", "#1c7ed6"), ("ew", "equal-wallet", "#e8590c"), ("wcd", "wallet-coin-day", "#0ca678")]:
    C = s[key]["C_minus_fade"]; rows.append((f"C: minus matched fade ({lab})", C[0], C[1], C[2], col))
fig, ax = plt.subplots(figsize=(9.2, 5.4)); y = np.arange(len(rows))[::-1]
for yi, (lab, pt, lo, hi, col) in zip(y, rows):
    if lo is not None: ax.plot([lo, hi], [yi, yi], color=col, lw=2)
    ax.plot(pt, yi, "o", color=col, ms=7)
    ax.text(pt, yi+0.22, f"{pt:+.1f}", ha="center", fontsize=8.5, color=col)
ax.axvline(0, color="#495057", lw=1, ls="--"); ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows], fontsize=9.5)
ax.set_xlabel("bp (validation period)"); ax.set_title("Fixed-121 cohort: absolute, field-relative and fade-relative returns")
cap(ax, "8h markout, validation only. A = absolute cohort (gross, and cost-adjusted under the 8/8/10/14 bp schedule). "
        "B = cohort minus non-cohort field (drift-neutralized, no cost). C = cohort minus matched mechanical fade. Bars 95% CI.", y=-0.20)
save(fig, "p10_fixed121_forest")

# p4 conditional — corrected caption (pooled slope; per-coin = heterogeneity)
ps = V5["pooled_slope"]; fig, ax = plt.subplots(figsize=(8.4, 5.0))
for c in COINS:
    bins = [x for x in V4["conditional"][c]["bins"] if x]
    x = [z[0] for z in bins]; yv = [z[1] for z in bins]; lo = [z[2] for z in bins]; hi = [z[3] for z in bins]
    ax.plot(x, yv, "-o", color=COL[c], lw=1.8, ms=4, label=c); ax.fill_between(x, lo, hi, color=COL[c], alpha=0.08)
ax.axhline(0, color="#adb5bd", lw=0.8); ax.axvline(0, color="#adb5bd", lw=0.8, ls="--")
ax.set_xlabel("signed pre-entry 8h move in trade direction (bp)  —  negative = entered against prior move")
ax.set_ylabel("subsequent 8h markout (bp)")
ax.set_title("Subsequent markout declines with the signed pre-entry move")
ax.legend(ncol=4, fontsize=9.5)
cap(ax, f"Entry-weighted, fixed pooled-quantile bins; bands 95% calendar-day cluster CI. Pooled model (coin+month FE, vol control): "
        f"slope {ps['slope_per_bp']:+.3f}/bp [{ps['ci95_2sided'][0]:+.3f}, {ps['ci95_2sided'][1]:+.3f}]. Per-coin curves are heterogeneity checks.", y=-0.24)
save(fig, "p4_conditional")

# copy unchanged figures from figs_v4
for f in ["p1_eventstudy", "p2_heatmap", "p3_long_short", "p5_size", "p6_monthly", "p7_rolling_decile",
          "p8_topdiff_month", "a_distribution", "a_regime_time", "f2_raw_vs_neut", "f1_termstructure", "f9_fade_ecdf"]:
    shutil.copy(f"figs_v4/{f}.png", f"{FD}/{f}.png")
print("saved figs_v5/ (behavioral dir-aligned, static canonical, fixed-121 forest, conditional pooled)")
