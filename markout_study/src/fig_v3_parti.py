"""Part I figures for report_v3 -> figs_v3/. Light (reads entry_features, cohort_K_entries, json). No bar-pricing."""
import sys, json, shutil; from pathlib import Path
import numpy as np, polars as pl
import matplotlib.pyplot as plt, matplotlib as mpl
mpl.use("Agg")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; LB = ["1h", "2h", "4h", "8h", "24h"]
COL = {"BTC": "#4c6ef5", "ETH": "#7048e8", "SOL": "#0ca678", "HYPE": "#e8590c"}
FD = "figs_v3"; Path(FD).mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 130, "savefig.dpi": 130, "font.size": 10, "font.family": "DejaVu Sans",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.2,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "axes.titlesize": 10.5, "axes.titleweight": "normal",
    "legend.frameon": False, "figure.constrained_layout.use": True})
def save(fig, n): fig.savefig(f"{FD}/{n}.png", bbox_inches="tight"); plt.close(fig)
def cap(ax, s): ax.text(0, -0.34, s, transform=ax.transAxes, fontsize=7.4, color="#666", va="top")
df = pl.read_parquet("out/cohort_K_entries.parquet")
ef = pl.read_parquet("out/entry_features.parquet")
esj = json.load(open("out/eventstudy.json")); ci = json.load(open("out/termstructure_ci.json"))

# P1 — event study: signed price response around entries
off = esj["offsets_h"]; fig, ax = plt.subplots(figsize=(7.6, 4.4))
for c in COINS:
    pt = [esj["coins"][c][str(o)][0] for o in off]; lo = [esj["coins"][c][str(o)][1] for o in off]; hi = [esj["coins"][c][str(o)][2] for o in off]
    ax.plot(off, pt, "-o", color=COL[c], label=c, lw=1.5, ms=3.5); ax.fill_between(off, lo, hi, color=COL[c], alpha=0.10)
ax.axvline(0, color="#adb5bd", lw=1, ls="--"); ax.axhline(0, color="#adb5bd", lw=0.8)
ax.set_xlabel("hours relative to entry"); ax.set_ylabel("signed return in trade direction (bp)")
ax.set_title("Signed price response around taker entries"); ax.legend(ncol=4, fontsize=8.5)
cap(ax, "All cohort entries, entry-weighted. Positive pre-entry values = price moved against the trade before entry. 95% day-block CI. Dashed line = entry.")
save(fig, "p1_eventstudy")

# P2 — coin x horizon heatmap of mean markout with CI-excludes-zero mark
M = np.array([[ci[c][h][0] for h in LB] for c in COINS])
excl = np.array([[ (ci[c][h][1] > 0) or (ci[c][h][2] < 0) for h in LB] for c in COINS])
fig, ax = plt.subplots(figsize=(7.2, 3.6)); vmax = np.nanmax(np.abs(M))
im = ax.imshow(M, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
ax.set_xticks(range(5)); ax.set_xticklabels(LB); ax.set_yticks(range(4)); ax.set_yticklabels(COINS)
for i in range(4):
    for j in range(5):
        star = "*" if excl[i, j] else ""
        ax.text(j, i, f"{M[i,j]:+.1f}{star}", ha="center", va="center", fontsize=9,
                color="white" if abs(M[i, j]) > vmax*0.55 else "#222")
ax.set_title("Mean post-entry markout by coin and horizon")
fig.colorbar(im, ax=ax, shrink=0.8, label="bp")
cap(ax, "Full sample, entry-weighted, bp. * = 95% day-block interval excludes zero. N per cell 125k–356k.")
save(fig, "p2_heatmap")

# P3 — long vs short markout term structure, small multiples by coin
fig, axes = plt.subplots(1, 4, figsize=(12, 3.1), constrained_layout=False)
fig.subplots_adjust(wspace=0.32, left=0.05, right=0.99, top=0.80, bottom=0.22)
for ax, c in zip(axes, COINS):
    sub = df.filter(pl.col("coin") == c)
    for sgn, lab, col in [(1, "long", "#1c7ed6"), (-1, "short", "#c0392b")]:
        s = sub.filter(pl.col("dir") == sgn); m = [s[f"raw_{h}"].mean() for h in LB]
        ax.plot(range(5), m, "-o", color=col, label=lab, lw=1.5, ms=3.5)
    ax.axhline(0, color="#adb5bd", lw=0.7); ax.set_xticks(range(5)); ax.set_xticklabels(LB, fontsize=8)
    ax.set_title(c, fontsize=10);
    if c == "BTC": ax.set_ylabel("mean markout (bp)"); ax.legend(fontsize=8)
fig.suptitle("Markout term structure by entry direction", fontsize=11, y=0.99)
fig.text(0.05, 0.02, "Entry-weighted, by trade direction. Long/short split within coin.", fontsize=7.4, color="#666")
save(fig, "p3_long_short")

# P4 — subsequent 8h markout conditional on signed trailing 8h move
fig, ax = plt.subplots(figsize=(7.4, 4.4))
J = ef.select("coin", "trail_8h").with_columns(mk8=df["raw_8h"])
edges = np.array([-400, -200, -100, -50, -20, 20, 50, 100, 200, 400])
cent = (edges[:-1] + edges[1:]) / 2
for c in COINS:
    s = J.filter(pl.col("coin") == c).drop_nulls()
    t = s["trail_8h"].to_numpy(); y = s["mk8"].to_numpy(); ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok], y[ok]; b = np.digitize(t, edges)
    means = [y[b == k+1].mean() if (b == k+1).sum() > 50 else np.nan for k in range(len(edges)-1)]
    ax.plot(cent, means, "-o", color=COL[c], label=c, lw=1.5, ms=4)
ax.axhline(0, color="#adb5bd", lw=0.8); ax.axvline(0, color="#adb5bd", lw=0.8, ls="--")
ax.set_xlabel("signed trailing 8h return in trade direction (bp)"); ax.set_ylabel("subsequent 8h markout (bp)")
ax.set_title("Subsequent markout conditional on the pre-entry move"); ax.legend(ncol=4, fontsize=8.5)
cap(ax, "Entry-weighted. Negative x = entered against the prior move (contrarian); positive x = with the move (momentum). Bins with <50 entries dropped.")
save(fig, "p4_conditional")

# P5 — markout by entry notional bucket (equal- vs notional-weighted), 1h & 8h
fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
dd = df.with_columns(q=(pl.col("notl").rank() / pl.len() * 5).ceil().clip(1, 5))
for ax, h in zip(axes, ["1h", "8h"]):
    ew, nw, xs = [], [], []
    for qi in range(1, 6):
        s = dd.filter(pl.col("q") == qi); v = s[f"raw_{h}"].to_numpy(); n = s["notl"].to_numpy()
        m = np.isfinite(v)
        ew.append(v[m].mean()); nw.append(np.average(v[m], weights=n[m])); xs.append(qi)
    ax.plot(xs, ew, "-o", color="#495057", label="equal-weighted", lw=1.5, ms=4)
    ax.plot(xs, nw, "-s", color="#1c7ed6", label="notional-weighted", lw=1.5, ms=4)
    ax.axhline(0, color="#adb5bd", lw=0.7); ax.set_xticks(xs); ax.set_xlabel("notional quintile (5 = largest)")
    ax.set_ylabel(f"{h} markout (bp)"); ax.set_title(f"{h} horizon", fontsize=10)
    if h == "1h": ax.legend(fontsize=8.5)
fig.suptitle("Markout by entry notional", fontsize=11)
cap(axes[0], "Entry-weighted vs notional-weighted mean markout within notional quintiles. Pooled over coins.")
save(fig, "p5_size")

# P6 — monthly mean 8h markout by coin (heatmap)
mos = sorted(df["ym"].unique().to_list())
Mm = np.array([[ (df.filter((pl.col("coin")==c)&(pl.col("ym")==m))["raw_8h"].mean() or np.nan) for m in mos] for c in COINS], dtype=float)
fig, ax = plt.subplots(figsize=(9.5, 3.0)); vmax = np.nanpercentile(np.abs(Mm), 95)
im = ax.imshow(Mm, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
ax.set_xticks(range(len(mos))); ax.set_xticklabels([f"{str(m)[:4]}-{str(m)[4:]}" for m in mos], rotation=45, fontsize=7.5)
ax.set_yticks(range(4)); ax.set_yticklabels(COINS)
for i in range(4):
    for j in range(len(mos)):
        if np.isfinite(Mm[i, j]): ax.text(j, i, f"{Mm[i,j]:+.0f}", ha="center", va="center", fontsize=7, color="white" if abs(Mm[i,j])>vmax*0.55 else "#222")
ax.set_title("Mean 8-hour markout by coin and month"); fig.colorbar(im, ax=ax, shrink=0.8, label="bp")
cap(ax, "Entry-weighted mean 8h markout, bp. Later months thin and BTC-heavy; interpret sparse cells cautiously.")
save(fig, "p6_monthly")

# APPENDIX: distribution interval plot (median, IQR, p5/p95) for 8h by coin
fig, ax = plt.subplots(figsize=(7.0, 3.8))
for i, c in enumerate(COINS):
    v = df.filter(pl.col("coin") == c)["raw_8h"].to_numpy(); v = v[np.isfinite(v)]
    p5, q1, med, q3, p95 = np.percentile(v, [5, 25, 50, 75, 95])
    ax.plot([p5, p95], [i, i], color=COL[c], lw=1.2, alpha=0.5); ax.plot([q1, q3], [i, i], color=COL[c], lw=5, alpha=0.7)
    ax.plot(med, i, "|", color="#222", ms=14, mew=2)
ax.axvline(0, color="#adb5bd", lw=0.8, ls="--"); ax.set_yticks(range(4)); ax.set_yticklabels(COINS)
ax.set_xlabel("8h markout (bp)"); ax.set_title("Distribution of post-entry returns (8h)")
cap(ax, "Thin line: 5th–95th percentile; thick bar: IQR; marker: median. Entry-weighted.")
save(fig, "a_distribution")

# APPENDIX: markout by realized-vol quintile and time-of-day
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
J2 = ef.select("vol2h", "b_ts").with_columns(mk8=df["raw_8h"])
J2 = J2.with_columns(vq=(pl.col("vol2h").rank()/pl.len()*5).ceil().clip(1,5), tod=((pl.col("b_ts")//3600_000)%24))
vq = J2.group_by("vq").agg(m=pl.col("mk8").mean()).sort("vq")
axes[0].plot(vq["vq"].to_numpy(), vq["m"].to_numpy(), "-o", color="#1c7ed6", lw=1.5)
axes[0].axhline(0, color="#adb5bd", lw=0.7); axes[0].set_xlabel("realized-vol quintile (5 = highest)"); axes[0].set_ylabel("8h markout (bp)"); axes[0].set_title("By volatility", fontsize=10)
tb = J2.with_columns(b=(pl.col("tod")//4)).group_by("b").agg(m=pl.col("mk8").mean()).sort("b")
axes[1].plot(tb["b"].to_numpy()*4, tb["m"].to_numpy(), "-o", color="#0ca678", lw=1.5)
axes[1].axhline(0, color="#adb5bd", lw=0.7); axes[1].set_xlabel("hour of day (UTC, 4h buckets)"); axes[1].set_title("By time of day", fontsize=10)
fig.suptitle("8-hour markout by volatility and time of day", fontsize=11)
cap(axes[0], "Entry-weighted, pooled over coins.")
save(fig, "a_regime_time")

# reuse Part II figures from figs_v2 into figs_v3 (keep one directory)
for f in ["f3_static_ranking", "f4_rank_persistence", "f5_gross_net_bench", "f6_abcd", "f7_residual", "f8_behavioral", "f9_fade_ecdf", "f2_raw_vs_neut", "f1_termstructure"]:
    shutil.copy(f"figs_v2/{f}.png", f"{FD}/{f}.png")
print("saved Part I figs + copied Part II figs into figs_v3/")
