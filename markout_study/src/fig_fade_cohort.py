"""Sections 8-10 — fade decomposition forest plots + cohort construction/characterization. Published point+CI (confirmed) + P1b parquet."""
import sys; from pathlib import Path
import numpy as np, polars as pl
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_style as rs
rs.setup()

def forest(ax, labels, pts, los, his, colors=None, title="", xlabel="bp"):
    y = np.arange(len(labels))[::-1]
    colors = colors or ["#4c78a8"] * len(labels)
    for yi, p, lo, hi, c in zip(y, pts, los, his, colors):
        ax.plot([lo, hi], [yi, yi], color=c, lw=2.4)
        ax.plot(p, yi, "o", color=c, ms=7)
    ax.axvline(0, color="#888", lw=1, ls="--")
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9.5); ax.set_xlabel(xlabel)
    ax.set_title(title); rs.bp_axis(ax, "x")

# Fig 8A — decile deployability: gross survives, alpha vs fade ~0
fig, ax = plt.subplots(figsize=(8, 3.4))
forest(ax, ["gross (long-only)", "net realistic cost", "net campaign cost", "ALPHA vs mechanical fade"],
       [13.99, 7.09, 4.19, 1.00], [5.38, -1.94, -4.52, -10.75], [22.81, 15.83, 12.92, 13.66],
       colors=["#59a14f", "#4c78a8", "#4c78a8", "#d62728"],
       title="Top-decile @8h: +14bp gross is REAL, but alpha over a costless mechanical fade ≈ 0", xlabel="bp per coin-day")
rs.save(fig, "08_alpha_vs_fade")

# Fig 9A — A/B/C/D net (day-capped, corrected M3)
fig, ax = plt.subplots(figsize=(8, 3.2))
forest(ax, ["A  wallet direction", "B  fade @ wallet times", "C  fade everywhere (untriggered)", "D  fade @ matched non-wallet times"],
       [2.61, 5.92, -7.00, -6.43], [-4.27, -5.03, -16.55, -10.13], [9.49, 17.27, 2.49, -2.74],
       colors=["#4c78a8", "#59a14f", "#e15759", "#b07aa1"],
       title="Wallet direction adds nothing (A≈B); untriggered fade LOSES (C); the fade needs a trigger", xlabel="net bp per coin-day")
rs.save(fig, "09_abcd")

# Fig 9B — M4 residual with MDE band
fig, ax = plt.subplots(figsize=(8, 3.0))
ax.axvspan(-16.3, 16.3, color="#eee", label="±MDE(80% power) ≈ 16bp — window is blind here")
forest(ax, ["per-event residual", "day-capped residual (primary)"],
       [-1.30, 5.87], [-15.57, -5.54], [12.98, 17.66], colors=["#7f7f7f", "#d62728"],
       title="Continuous-control residual: per-event ≈0; day-capped +5.87 is a LIVE UNDERPOWERED positive", xlabel="bp")
ax.legend(fontsize=8, loc="lower right"); rs.save(fig, "09_m4_residual_mde")

# Fig 8B — recurrence vs luck null (corrected)
fig, ax = plt.subplots(figsize=(6.6, 3.9))
K = ["≥2 months", "≥3 months", "≥4 months"]; obs = [204, 48, 9]; luck = [184, 35, 5]
x = np.arange(3); w = 0.38
ax.bar(x - w/2, obs, w, color="#4c78a8", label="observed")
ax.bar(x + w/2, luck, w, color="#bab0ac", label="luck-null expected")
for i, (o, l) in enumerate(zip(obs, luck)): ax.text(i - w/2, o + 3, str(o), ha="center", fontsize=8.5)
ax.set_xticks(x); ax.set_xticklabels(K); ax.set_ylabel("# wallets")
ax.set_title("Recurrence in the top decile vs luck (only ≥3mo clears: 48 vs 35, p=0.017)")
ax.legend(fontsize=9); rs.save(fig, "08_recurrence")

# Fig 8C — construction funnel to 121
fig, ax = plt.subplots(figsize=(7.6, 3.4))
labs = ["cohort universe", "≥1 top-decile month", "≥2 months\n(PRIMARY = 121)", "≥3 months\n(STRICT = 28)", "≥4 months"]
vals = [1694, 496, 121, 28, 5]; y = np.arange(len(vals))[::-1]
for i, (v, yy) in enumerate(zip(vals, y)):
    ax.barh(yy, v, color=plt.cm.Reds(0.35 + 0.13 * i), edgecolor="white")
    ax.text(v * 1.03, yy, f"{v:,}", va="center", fontsize=9.5, weight="bold")
ax.set_yticks(y); ax.set_yticklabels(labs, fontsize=9); ax.set_xscale("log"); ax.set_xlim(3, 3000)
ax.set_xlabel("wallets (log)"); ax.set_title("Building the 121: train-only recurrence in the neut-8h top decile")
rs.save(fig, "08_cohort_funnel")

# Fig 10A — behavioral decomposition (group medians)
feats = ["|8h move|", "signed 8h\n(in trade dir)", "dist below\n24h high", "acceleration", "vol 2h"]
REC = [175, -86, -281, -6.2, 23.4]; ORD = [151, -12, -218, 0.0, 21.5]; CON = [72, np.nan, -166, -1.6, 14.3]
fig, ax = plt.subplots(figsize=(9, 4.0)); x = np.arange(len(feats)); w = 0.26
ax.bar(x - w, REC, w, color=rs.GROUP_COLORS["RECURRING"], label="recurring (121)")
ax.bar(x, ORD, w, color=rs.GROUP_COLORS["ORDINARY"], label="ordinary wallets")
ax.bar(x + w, CON, w, color=rs.GROUP_COLORS["CONTROL"], label="non-wallet control")
ax.axhline(0, color="#888", lw=0.8); ax.set_xticks(x); ax.set_xticklabels(feats, fontsize=9)
ax.set_ylabel("median (bp; accel/vol in bp)")
ax.set_title("Recurring wallets enter hard AGAINST large decelerating moves at deep pullbacks")
ax.legend(fontsize=9); rs.save(fig, "10_behavioral")

# Fig 10B — per-wallet fade-fraction histogram
pw = pl.read_parquet("out/cohort_P1b_perwallet.parquet")
rec = pw.filter(pl.col("rec"))["fade_frac8"].to_numpy(); ordy = pw.filter(~pl.col("rec"))["fade_frac8"].to_numpy()
fig, ax = plt.subplots(figsize=(7.4, 4.0)); bins = np.linspace(0, 1, 26)
ax.hist(ordy, bins=bins, density=True, color=rs.GROUP_COLORS["ORDINARY"], alpha=0.55, label=f"ordinary (median {np.median(ordy):.2f})")
ax.hist(rec, bins=bins, density=True, histtype="step", lw=2.4, color=rs.GROUP_COLORS["RECURRING"], label=f"recurring (median {np.median(rec):.2f})")
ax.axvline(0.5, color="#888", ls="--", lw=1)
ax.set_xlabel("share of a wallet's entries that fade the trailing move"); ax.set_ylabel("density")
ax.set_title("83% of the 121 are net faders; 65% fade ≥60% of entries — a tilt, not a monolith")
ax.legend(fontsize=9); rs.save(fig, "10_fade_fraction")

# Fig 10C — cohort beats the field (forward decile + rank-IC term structure)
fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
ax = axes[0]
ax.bar(["recurring\ntop-decile", "field"], [5.72, 1.24], color=[rs.GROUP_COLORS["cohort"], rs.GROUP_COLORS["field"]])
ax.errorbar(0, 5.72, yerr=[[5.72 - 2.17], [7.54 - 5.72]], color="#333", capsize=4, lw=1.2)
ax.set_ylabel("next-month neut 8h markout (bp)"); ax.axhline(0, color="#888", lw=0.8)
ax.set_title("Forward: +4.48bp over field [+2.2,+7.5], 9/10 folds")
ax = axes[1]
hz = ["4h", "8h", "24h"]; ic = [0.081, 0.093, 0.085]; lo = [0.054, 0.061, 0.041]; hi = [0.108, 0.126, 0.134]
xx = np.arange(3)
ax.errorbar(xx, ic, yerr=[np.array(ic) - np.array(lo), np.array(hi) - np.array(ic)], fmt="o-", color="#4c78a8", capsize=4, lw=1.8)
ax.axhline(0, color="#888", lw=0.8); ax.set_xticks(xx); ax.set_xticklabels(hz)
ax.set_ylabel("adjacent-month rank-IC"); ax.set_xlabel("horizon"); ax.set_ylim(0, 0.16)
ax.set_title("Rank persists (weak but real): 8h IC +0.093, 10/10")
fig.suptitle("The persistence that IS real — but it is generic reversal (alpha vs fade ≈ +1bp)", fontsize=11, weight="bold")
rs.save(fig, "10_cohort_vs_field")
print("saved fade + cohort figs")
