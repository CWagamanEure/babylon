"""report v4 figures -> figs_v4/. Corrections + readability. Reads out/v4.json, eventstudy.json, termstructure_ci.json,
cohort_K_entries, entry_features. Larger panels, consistent widths, embedded-ready."""
import json, shutil; from pathlib import Path
import numpy as np, polars as pl
import matplotlib.pyplot as plt, matplotlib as mpl
mpl.use("Agg")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; LB = ["1h", "2h", "4h", "8h", "24h"]
COL = {"BTC": "#4c6ef5", "ETH": "#7048e8", "SOL": "#0ca678", "HYPE": "#e8590c"}
FD = "figs_v4"; Path(FD).mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 140, "savefig.dpi": 140, "font.size": 11, "font.family": "DejaVu Sans",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.18,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "axes.titlesize": 12, "legend.frameon": False})
def save(fig, n): fig.savefig(f"{FD}/{n}.png", bbox_inches="tight"); plt.close(fig)
def cap(ax, s, y=-0.30): ax.text(0, y, s, transform=ax.transAxes, fontsize=8.2, color="#666", va="top")
V = json.load(open("out/v4.json")); esj = json.load(open("out/eventstudy.json")); ci = json.load(open("out/termstructure_ci.json"))
df = pl.read_parquet("out/cohort_K_entries.parquet")
ef = pl.read_parquet("out/entry_features.parquet")

# P1 — event study (corrected labelling)
off = esj["offsets_h"]; fig, ax = plt.subplots(figsize=(8.4, 4.9))
for c in COINS:
    pt = [esj["coins"][c][str(o)][0] for o in off]; lo = [esj["coins"][c][str(o)][1] for o in off]; hi = [esj["coins"][c][str(o)][2] for o in off]
    ax.plot(off, pt, "-o", color=COL[c], label=c, lw=1.8, ms=4); ax.fill_between(off, lo, hi, color=COL[c], alpha=0.10)
ax.axvline(0, color="#adb5bd", lw=1, ls="--"); ax.axhline(0, color="#adb5bd", lw=0.8)
ax.set_xlabel("hours relative to entry"); ax.set_ylabel("earlier price minus entry price,\nin trade direction (bp)")
ax.set_title("Price path around taker entries, aligned in trade direction")
ax.legend(ncol=4, fontsize=10, loc="upper right")
cap(ax, "All cohort entries, entry-weighted. Left of 0 = before entry. Positive pre-entry = price was above (long) / below (short) the entry price,\n"
        "i.e. it moved against the eventual trade direction into entry. Right of 0 = subsequent markout. 95% calendar-day cluster CI.", y=-0.24)
save(fig, "p1_eventstudy")

# P2 — coin x horizon heatmap (reuse)
M = np.array([[ci[c][h][0] for h in LB] for c in COINS]); excl = np.array([[(ci[c][h][1] > 0) or (ci[c][h][2] < 0) for h in LB] for c in COINS])
fig, ax = plt.subplots(figsize=(7.8, 3.9)); vmax = np.nanmax(np.abs(M))
im = ax.imshow(M, cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
ax.set_xticks(range(5)); ax.set_xticklabels(LB); ax.set_yticks(range(4)); ax.set_yticklabels(COINS)
for i in range(4):
    for j in range(5):
        ax.text(j, i, f"{M[i,j]:+.1f}{'*' if excl[i,j] else ''}", ha="center", va="center", fontsize=10, color="white" if abs(M[i,j]) > vmax*0.55 else "#222")
ax.set_title("Mean post-entry markout by coin and horizon"); fig.colorbar(im, ax=ax, shrink=0.85, label="bp")
cap(ax, "Full sample, entry-weighted, bp. * = 95% calendar-day cluster interval excludes zero.", y=-0.32)
save(fig, "p2_heatmap")

# P3 — long vs short, RAW (top) and NEUTRALIZED (bottom), small multiples, enlarged
fig, axes = plt.subplots(2, 4, figsize=(13, 6.2)); H3 = ["1h", "2h", "4h", "8h", "24h"]
for r, kind in enumerate(["raw", "neut"]):
    for cidx, c in enumerate(COINS):
        ax = axes[r, cidx]
        for sgn, lab, col in [(1, "long", "#1c7ed6"), (-1, "short", "#c0392b")]:
            s = df.filter((pl.col("coin") == c) & (pl.col("dir") == sgn)); m = [s[f"{kind}_{h}"].mean() for h in H3]
            ax.plot(range(5), m, "-o", color=col, label=lab, lw=1.8, ms=4)
        ax.axhline(0, color="#adb5bd", lw=0.7); ax.set_xticks(range(5)); ax.set_xticklabels(H3, fontsize=9)
        if r == 0: ax.set_title(c, fontsize=12)
        if cidx == 0: ax.set_ylabel(("Raw" if kind == "raw" else "Neutralized")+"\nmarkout (bp)")
        if r == 0 and cidx == 3: ax.legend(fontsize=10)
fig.suptitle("Markout term structure by entry direction — raw (top) vs coin-month neutralized (bottom)", fontsize=13, y=1.00)
fig.text(0.01, -0.01, "Entry-weighted. Raw long/short asymmetry at 24h reflects sample-period directional drift; neutralization removes most of it.", fontsize=8.4, color="#666")
fig.tight_layout(); save(fig, "p3_long_short")

# P4 — conditional: quantile bins with day-cluster CI + fitted training slope
fig, ax = plt.subplots(figsize=(8.4, 5.0))
for c in COINS:
    bins = [b for b in V["conditional"][c]["bins"] if b]
    x = [b[0] for b in bins]; y = [b[1] for b in bins]; lo = [b[2] for b in bins]; hi = [b[3] for b in bins]
    ax.plot(x, y, "-o", color=COL[c], lw=1.8, ms=4, label=f"{c} (slope {V['conditional'][c]['train_slope_per_bp']:+.3f}/bp)")
    ax.fill_between(x, lo, hi, color=COL[c], alpha=0.08)
ax.axhline(0, color="#adb5bd", lw=0.8); ax.axvline(0, color="#adb5bd", lw=0.8, ls="--")
ax.set_xlabel("signed pre-entry 8h move in trade direction (bp)  —  negative = entered against prior move")
ax.set_ylabel("subsequent 8h markout (bp)")
ax.set_title("Subsequent markout declines with the signed pre-entry move")
ax.legend(fontsize=9.5, title="training-fit linear slope", title_fontsize=9)
cap(ax, "Entry-weighted, fixed pooled-quantile bins (bins <200 entries dropped). Bands 95% calendar-day cluster CI.\n"
        "Training slopes negative in all four coins; p(slope≥0) ≤ 0.03 each.", y=-0.24)
save(fig, "p4_conditional")

# P5 — size within coin x month, equal & notl weighted, 1h & 8h, with CI
fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
for ax, h in zip(axes, ["1h", "8h"]):
    q = range(1, 6)
    for key, lab, col, mk in [("equal", "equal-weighted", "#495057", "o"), ("notl", "notional-weighted", "#1c7ed6", "s")]:
        m = [V["size"][h][str(qi)][key][0] for qi in q]; lo = [V["size"][h][str(qi)][key][1] for qi in q]; hi = [V["size"][h][str(qi)][key][2] for qi in q]
        ax.plot(q, m, "-"+mk, color=col, label=lab, lw=1.8, ms=5)
        ax.fill_between(list(q), lo, hi, color=col, alpha=0.08)
    ax.axhline(0, color="#adb5bd", lw=0.7); ax.set_xticks(list(q)); ax.set_xlabel("notional quintile within coin-month (5 = largest)")
    ax.set_ylabel(f"{h} markout (bp)"); ax.set_title(f"{h} horizon", fontsize=11.5)
    if h == "1h": ax.legend(fontsize=10)
fig.suptitle("Markout by entry notional (quintiles within coin and month)", fontsize=13)
fig.text(0.01, -0.02, "Larger entry notional is not associated with higher subsequent decision markout. Bands 95% calendar-day cluster CI.", fontsize=8.4, color="#666")
fig.tight_layout(); save(fig, "p5_size")

# ROLLING DECILE — next-month markout by prior-month rank decile (4h & 8h) + field
fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
for ax, hz in zip(axes, ["4h", "8h"]):
    dd = V["rolling_decile"][hz]["deciles"]; ks = sorted(int(k) for k in dd)
    pt = [dd[str(k)][0] for k in ks]; lo = [dd[str(k)][1] for k in ks]; hi = [dd[str(k)][2] for k in ks]
    ax.bar(ks, pt, color=["#c0392b" if p < 0 else "#1c7ed6" for p in pt], alpha=0.85, width=0.7)
    ax.errorbar(ks, pt, yerr=[np.array(pt)-np.array(lo), np.array(hi)-np.array(pt)], fmt="none", ecolor="#333", lw=1, capsize=2)
    fld = V["rolling_decile"][hz]["field"][0]; ax.axhline(fld, color="#495057", lw=1.2, ls="--", label=f"field mean {fld:+.1f}")
    ax.axhline(0, color="#adb5bd", lw=0.7); ax.set_xticks(ks); ax.set_xlabel("prior-month rank decile (10 = best)")
    ax.set_ylabel("next-month markout (bp)"); ax.set_title(f"{hz} horizon", fontsize=11.5); ax.legend(fontsize=9.5)
fig.suptitle("Next-month markout by prior-month wallet-rank decile", fontsize=13)
fig.text(0.01, -0.02, "Neutralized, wallet-day-weighted; adjacent-month pairs pooled. Returns rise across deciles, strongest in the top decile. 95% month-cluster CI.", fontsize=8.4, color="#666")
fig.tight_layout(); save(fig, "p7_rolling_decile")

# ROLLING top-minus-field by month
td = V["rolling_decile"]["8h"]["topdiff_by_month"]; fig, ax = plt.subplots(figsize=(9.5, 3.8))
xs = [t[0] for t in td]; ys = [t[1] for t in td]
ax.bar(range(len(xs)), ys, color=["#c0392b" if y < 0 else "#1c7ed6" for y in ys], alpha=0.85)
ax.axhline(0, color="#495057", lw=0.9); ax.set_xticks(range(len(xs))); ax.set_xticklabels(xs, rotation=45, fontsize=8.5, ha="right")
ax.set_ylabel("top-decile − field (bp)"); ax.set_title("Top-decile minus field, next-month 8h markout, by month")
cap(ax, f"Neutralized wallet-day-weighted. Positive in {sum(1 for y in ys if y>0)} of {len(ys)} months.", y=-0.42)
save(fig, "p8_topdiff_month")

# STATIC ranking (enlarged, clean): train-decile -> validation mean + scatter
w = (df.group_by("wallet").agg(
        tr=pl.col("raw_8h").filter(pl.col("split") == "train").mean(), ntr=pl.col("split").filter(pl.col("split") == "train").len(),
        va=pl.col("raw_8h").filter(pl.col("split") == "test").mean(), nva=pl.col("split").filter(pl.col("split") == "test").len())
     .filter((pl.col("ntr") >= 30) & (pl.col("nva") >= 20)))
w = w.with_columns(dec=(pl.col("tr").rank()/pl.len()*10).ceil().clip(1, 10))
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
dm = w.group_by("dec").agg(m=pl.col("va").mean()).sort("dec")
axes[0].bar(dm["dec"].to_numpy(), dm["m"].to_numpy(), color="#7048e8", alpha=0.85)
axes[0].axhline(0, color="#adb5bd", lw=0.7); axes[0].set_xlabel("training-mean 8h decile (10 = best in-sample)")
axes[0].set_ylabel("validation mean 8h markout (bp)"); axes[0].set_title("Validation return by training decile", fontsize=11.5)
tr = w["tr"].to_numpy(); va = w["va"].to_numpy()
axes[1].scatter(tr, va, s=6, alpha=0.25, color="#495057"); axes[1].axhline(0, color="#adb5bd", lw=0.7); axes[1].axvline(0, color="#adb5bd", lw=0.7)
rho = np.corrcoef(tr, va)[0, 1]
axes[1].set_xlabel("training mean 8h markout (bp)"); axes[1].set_ylabel("validation mean 8h markout (bp)")
axes[1].set_title(f"Training vs validation wallet means (rho={rho:+.02f})", fontsize=11.5)
fig.suptitle("Static full-history wallet ranking does not generalize", fontsize=13)
fig.text(0.01, -0.02, f"Wallets with >=30 training and >=20 validation entries (n={w.height}). Entry-weighted wallet means.", fontsize=8.4, color="#666")
fig.tight_layout(); save(fig, "p6_static")

# BEHAVIORAL — clean grouped bars (readable), recurring vs ordinary vs control
metrics = [("|8h| markout (bp)", [175, 151, 72]), ("pullback depth (bp)", [-281, -218, -166]),
           ("pre-entry acceleration (bp)", [-6.2, 0.0, -1.6]), ("realized vol (bp)", [23.4, 21.5, 14.3])]
grp = ["recurring 121", "other cohort", "random control"]; gc = ["#e8590c", "#4c6ef5", "#adb5bd"]
fig, axes = plt.subplots(2, 2, figsize=(11, 7)); axes = axes.ravel()
for ax, (title, vals) in zip(axes, metrics):
    ax.bar(range(3), vals, color=gc, alpha=0.9); ax.axhline(0, color="#888", lw=0.7)
    ax.set_xticks(range(3)); ax.set_xticklabels(grp, fontsize=9.5); ax.set_title(title, fontsize=11)
    for i, v in enumerate(vals): ax.text(i, v, f"{v:g}", ha="center", va="bottom" if v >= 0 else "top", fontsize=9.5)
fig.suptitle("Market conditions at entry: recurring cohort vs others vs random control (medians)", fontsize=12.5)
fig.text(0.01, 0.005, "Recurring wallets enter after deeper pullbacks and larger absolute moves. Medians over wallet entries.", fontsize=8.4, color="#666")
fig.tight_layout(rect=[0, 0.02, 1, 1]); save(fig, "p9_behavioral")

# APPENDIX reuse from figs_v3
for f in ["p6_monthly", "a_distribution", "a_regime_time", "f2_raw_vs_neut", "f9_fade_ecdf", "f5_gross_net_bench", "f6_abcd", "f7_residual", "f1_termstructure"]:
    shutil.copy(f"figs_v3/{f}.png", f"{FD}/{f}.png")
print("saved figs_v4/ (corrected + enlarged + new rolling-decile & static)")
