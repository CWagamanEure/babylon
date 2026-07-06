"""Revised report figures (report_v2). Neutral descriptive titles; interpretation lives in the text.
Restrained style, day-block CIs where applicable, small-multiples / ECDFs / interval plots. Output -> figs_v2/."""
import sys, json; from pathlib import Path
import numpy as np, polars as pl
from scipy import stats as st
import matplotlib.pyplot as plt
import matplotlib as mpl
mpl.use("Agg")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; LB = ["1h", "2h", "4h", "8h", "24h"]; X = np.arange(5)
COL = {"BTC": "#4c6ef5", "ETH": "#7048e8", "SOL": "#0ca678", "HYPE": "#e8590c", "ALL": "#495057"}
GRP = {"recurring": "#c0392b", "ordinary": "#868e96", "control": "#ced4da"}
FD = "figs_v2"; Path(FD).mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 130, "savefig.dpi": 130, "font.size": 10, "font.family": "DejaVu Sans",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.2,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "axes.titlesize": 10.5, "axes.titleweight": "normal",
    "legend.frameon": False, "figure.constrained_layout.use": True})
def save(fig, n): p = f"{FD}/{n}.png"; fig.savefig(p, bbox_inches="tight"); plt.close(fig); return p
def cap(ax, s): ax.text(0, -0.30, s, transform=ax.transAxes, fontsize=7.6, color="#666", va="top")

ci = json.load(open("out/termstructure_ci.json"))
df = pl.read_parquet("out/cohort_K_entries.parquet")

# F1 — term structure by coin & horizon with day-block 95% CI
fig, ax = plt.subplots(figsize=(7.6, 4.4))
for c in COINS:
    pt = [ci[c][h][0] for h in LB]; lo = [ci[c][h][1] for h in LB]; hi = [ci[c][h][2] for h in LB]
    ax.plot(X, pt, "-o", color=COL[c], label=c, lw=1.6, ms=4)
    ax.fill_between(X, lo, hi, color=COL[c], alpha=0.10)
ax.axhline(0, color="#adb5bd", lw=0.8)
ax.set_xticks(X); ax.set_xticklabels(LB); ax.set_xlabel("horizon"); ax.set_ylabel("mean markout (bp)")
ax.set_title("Entry-weighted markout by coin and horizon")
ax.legend(ncol=4, fontsize=8.5, loc="lower left")
cap(ax, "Full sample, entry-weighted. Bands: 95% calendar-day block bootstrap. Markout = post-fill signed price return to horizon (gross, no costs).")
save(fig, "f1_termstructure")

# F2 — raw vs neutralized, pooled
fig, ax = plt.subplots(figsize=(6.6, 3.9))
raw = [df[f"raw_{h}"].mean() for h in LB]; neu = [df[f"neut_{h}"].mean() for h in LB]
ax.plot(X, raw, "-o", color="#495057", label="raw", lw=1.6, ms=4)
ax.plot(X, neu, "-s", color="#1c7ed6", label="drift-neutralized", lw=1.6, ms=4)
ax.axhline(0, color="#adb5bd", lw=0.8); ax.set_xticks(X); ax.set_xticklabels(LB)
ax.set_xlabel("horizon"); ax.set_ylabel("mean markout (bp)"); ax.set_title("Pooled markout: raw vs drift-neutralized")
ax.legend(fontsize=9)
cap(ax, "Pooled over four coins, entry-weighted. Neutralized = raw minus each coin's own monthly mean forward return.")
save(fig, "f2_raw_vs_neut")

# F3 — static ranking: train vs validation 8h markout by training decile + scatter
def perw(split):
    s = df.filter(pl.col("split") == split); return s.group_by("wallet").agg(m=pl.col("raw_8h").mean(), n=pl.len())
tr = perw("train").filter(pl.col("n") >= 50).rename({"m": "trm", "n": "trn"})
te = perw("test").filter(pl.col("n") >= 15).rename({"m": "tem", "n": "ten"})
J = tr.join(te, on="wallet", how="inner")
rho = st.spearmanr(J["trm"].to_numpy(), J["tem"].to_numpy())
J2 = J.with_columns(dec=(pl.col("trm").rank() / pl.len() * 10).ceil().clip(1, 10))
dec = J2.group_by("dec").agg(tr=pl.col("trm").mean(), te=pl.col("tem").mean()).sort("dec")
fig, axes = plt.subplots(1, 2, figsize=(10, 4.0))
ax = axes[0]; d = dec["dec"].to_numpy()
ax.plot(d, dec["tr"].to_numpy(), "-o", color="#495057", label="training", lw=1.6, ms=4)
ax.plot(d, dec["te"].to_numpy(), "-s", color="#c0392b", label="validation", lw=1.6, ms=4)
ax.axhline(0, color="#adb5bd", lw=0.8); ax.set_xlabel("training decile (10 = highest markout)")
ax.set_ylabel("mean 8h markout (bp)"); ax.set_title("Training and validation 8-hour markout by training decile"); ax.legend(fontsize=9)
ax = axes[1]; tx = J["trm"].to_numpy(); ty = J["tem"].to_numpy(); lim = np.percentile(np.abs(np.concatenate([tx, ty])), 99)
ax.scatter(tx, ty, s=7, alpha=0.3, color="#868e96"); ax.axhline(0, color="#ced4da", lw=0.7); ax.axvline(0, color="#ced4da", lw=0.7)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_xlabel("training 8h markout (bp)"); ax.set_ylabel("validation 8h markout (bp)")
ax.set_title("Validation vs training wallet 8-hour markout")
cap(axes[0], f"Static ranking: wallets ranked once on training, measured in validation. Entry-weighted per wallet. Train→validation rank correlation ρ={rho.correlation:+.2f} (p={rho.pvalue:.2f}), n={J.height}.")
save(fig, "f3_static_ranking")

# F4 — one-month-ahead rank persistence by horizon (rolling)
fig, ax = plt.subplots(figsize=(5.8, 3.9))
hz = ["4h", "8h", "24h"]; icv = [0.081, 0.093, 0.085]; lo = [0.054, 0.061, 0.041]; hi = [0.108, 0.126, 0.134]
xx = np.arange(3)
ax.errorbar(xx, icv, yerr=[np.array(icv)-np.array(lo), np.array(hi)-np.array(icv)], fmt="o", color="#1c7ed6", capsize=3, lw=1.5, ms=5)
ax.axhline(0, color="#adb5bd", lw=0.8); ax.set_xticks(xx); ax.set_xticklabels(hz); ax.set_ylim(0, 0.16)
ax.set_xlabel("horizon"); ax.set_ylabel("adjacent-month rank correlation"); ax.set_title("One-month-ahead rank persistence by horizon")
cap(ax, "Rolling monthly re-ranking (wallet-day-weighted, drift-neutralized). Spearman rank IC of month t rank vs month t+1 markout; 95% fold bootstrap.")
save(fig, "f4_rank_persistence")

# F5 — gross/net/benchmark-adjusted 8h returns (forest)
def forest(ax, labels, pts, los, his, colors, xlabel):
    y = np.arange(len(labels))[::-1]
    for yi, p, l, h, c in zip(y, pts, los, his, colors):
        ax.plot([l, h], [yi, yi], color=c, lw=2.2); ax.plot(p, yi, "o", color=c, ms=6)
    ax.axvline(0, color="#adb5bd", lw=1, ls="--"); ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9); ax.set_xlabel(xlabel)
fig, ax = plt.subplots(figsize=(7.4, 2.9))
forest(ax, ["gross", "net of costs", "benchmark-adjusted\n(minus mechanical fade)"], [13.99, 7.09, 1.00],
       [5.38, -1.94, -10.75], [22.81, 15.83, 13.66], ["#495057", "#1c7ed6", "#c0392b"], "bp per coin-day")
ax.set_title("Gross, net, and benchmark-adjusted 8-hour returns")
cap(ax, "Top training decile, wallet-day-capped, 8h horizon, validation period. Costs 6–9 bp/coin. 95% day-block CI. Benchmark = mechanical reversal at same timestamps.")
save(fig, "f5_gross_net_bench")

# F6 — returns under wallet-direction and fade rules (A/B/C/D)
fig, ax = plt.subplots(figsize=(7.4, 3.0))
forest(ax, ["wallet direction (A)", "fade at wallet times (B)", "fade at all bars (C)", "fade at matched non-wallet times (D)"],
       [2.61, 5.92, -7.00, -6.43], [-4.27, -5.03, -16.55, -10.13], [9.49, 17.27, 2.49, -2.74],
       ["#495057", "#1c7ed6", "#e8590c", "#868e96"], "net bp per coin-day")
ax.set_title("Returns under wallet-direction and fade rules")
cap(ax, "Train-only top decile, wallet-day-capped, 8h, validation period, net of costs. 95% day-block CI. Matched control on coin, month, time-of-day, trailing move and volatility.")
save(fig, "f6_abcd")

# F7 — residual after conditioning on market state
fig, ax = plt.subplots(figsize=(7.2, 2.6))
forest(ax, ["per-event", "wallet-day-capped"], [-1.30, 5.87], [-15.57, -5.54], [12.98, 17.66], ["#868e96", "#c0392b"], "residual bp")
ax.set_title("Residual return after conditioning on market state")
ax.text(0.99, 0.06, "minimum resolvable effect ≈ 11–16 bp", transform=ax.transAxes, ha="right", fontsize=7.8, color="#888")
cap(ax, "Fade return at wallet entries minus value predicted from trailing move, volatility, coin and time-of-day (model fit on non-wallet training bars). 95% day-block CI.")
save(fig, "f7_residual")

# F8 — market conditions at recurring-wallet entries (small multiples, own axes)
feats = [("|8h move|", [175, 151, 72]), ("signed 8h\nreturn", [-86, -12, np.nan]),
         ("dist below\n24h high", [-281, -218, -166]), ("acceleration", [-6.2, 0.0, -1.6]),
         ("2h volatility", [23.4, 21.5, 14.3])]
fig, axes = plt.subplots(1, 5, figsize=(12, 3.4), constrained_layout=False)
fig.subplots_adjust(wspace=0.55, left=0.055, right=0.985, top=0.80, bottom=0.20)
groups = ["recurring", "ordinary", "control"]; gc = [GRP[g] for g in groups]
for i, (ax, (title, vals)) in enumerate(zip(axes, feats)):
    ax.bar(range(3), vals, color=gc, width=0.72); ax.axhline(0, color="#adb5bd", lw=0.7)
    ax.set_xticks(range(3)); ax.set_xticklabels(["rec", "ord", "ctrl"], fontsize=8)
    ax.set_title(title, fontsize=9.5)
    if i == 0: ax.set_ylabel("group median (bp)")
fig.suptitle("Market conditions at recurring-wallet entries", fontsize=11, y=0.99)
fig.text(0.055, 0.02, "Group medians (bp). rec = 121 recurring cohort; ord = other cohort wallets; ctrl = random non-wallet bars. Signed return undefined for control.",
         fontsize=7.6, color="#666")
save(fig, "f8_behavioral")

# F9 — per-wallet contrarian entry share (ECDF)
pw = pl.read_parquet("out/cohort_P1b_perwallet.parquet")
rec = np.sort(pw.filter(pl.col("rec"))["fade_frac8"].to_numpy()); ordy = np.sort(pw.filter(~pl.col("rec"))["fade_frac8"].to_numpy())
fig, ax = plt.subplots(figsize=(6.4, 4.0))
ax.plot(rec, np.linspace(0, 1, len(rec)), color=GRP["recurring"], lw=1.8, label=f"recurring (n={len(rec)})")
ax.plot(ordy, np.linspace(0, 1, len(ordy)), color=GRP["ordinary"], lw=1.8, label=f"other wallets (n={len(ordy)})")
ax.axvline(0.5, color="#ced4da", lw=1, ls="--"); ax.set_xlabel("share of a wallet's entries that fade the trailing move")
ax.set_ylabel("cumulative fraction of wallets"); ax.set_title("Distribution of per-wallet contrarian entry share"); ax.legend(fontsize=9, loc="upper left")
cap(ax, "Per wallet, ≥20 training entries. Contrarian = entry direction opposite the trailing 8h move. Dashed line = 50% (coin-flip).")
save(fig, "f9_fade_ecdf")
print("saved figs_v2: f1..f9")

# quantile tables (appendix): trade size by coin; markout dispersion
qs = [0.1, 0.25, 0.5, 0.75, 0.9, 0.99]
with open("out/appendix_tables.md", "w") as f:
    f.write("### Trade size (notional $) by coin — quantiles\n\n| coin | p10 | p25 | p50 | p75 | p90 | p99 |\n|---|--:|--:|--:|--:|--:|--:|\n")
    for c in COINS:
        v = df.filter(pl.col("coin") == c)["notl"].to_numpy(); q = np.quantile(v[np.isfinite(v)], qs)
        f.write(f"| {c} | " + " | ".join(f"{x:,.0f}" for x in q) + " |\n")
    f.write("\n### Markout dispersion by coin at 8h — median, IQR, tails (bp)\n\n| coin | p10 | p25 | median | p75 | p90 | std |\n|---|--:|--:|--:|--:|--:|--:|\n")
    for c in COINS:
        v = df.filter(pl.col("coin") == c)["raw_8h"].to_numpy(); v = v[np.isfinite(v)]
        q = np.quantile(v, [0.1, 0.25, 0.5, 0.75, 0.9])
        f.write(f"| {c} | {q[0]:+.0f} | {q[1]:+.0f} | {q[2]:+.0f} | {q[3]:+.0f} | {q[4]:+.0f} | {v.std():.0f} |\n")
print("saved out/appendix_tables.md")
