"""Section 4 figures — markout term structure per coin per horizon (raw + neutralized). Data computed fresh (light polars)."""
import sys; from pathlib import Path
import numpy as np, polars as pl
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_style as rs
rs.setup()
LB = ["1h", "2h", "4h", "8h", "24h"]; X = np.arange(len(LB)); COINS = ["BTC", "ETH", "SOL", "HYPE"]
df = pl.read_parquet("out/cohort_K_entries.parquet")

def curve(frame, kind):  # kind in {raw,neut}; returns dict coin-> (means, sems)
    out = {}
    for coin in COINS + ["ALL"]:
        sub = frame if coin == "ALL" else frame.filter(pl.col("coin") == coin)
        means = [sub[f"{kind}_{h}"].mean() for h in LB]
        sems = [sub[f"{kind}_{h}"].std() / np.sqrt(sub.height) for h in LB]
        out[coin] = (np.array(means), np.array(sems))
    return out

raw = curve(df, "raw"); neut = curve(df, "neut")

# Fig 1 — headline raw term structure per coin + ALL
fig, ax = plt.subplots(figsize=(8, 4.6))
for coin in COINS:
    m, s = raw[coin]; ax.plot(X, m, "-o", color=rs.COIN_COLORS[coin], label=coin, lw=2, ms=5)
m, s = raw["ALL"]; ax.plot(X, m, "--", color=rs.COIN_COLORS["ALL"], label="ALL (pooled)", lw=2.2)
ax.axhline(0, color="#888", lw=0.8, zorder=0)
ax.set_xticks(X); ax.set_xticklabels(LB); rs.bp_axis(ax)
ax.set_xlabel("markout horizon"); ax.set_ylabel("mean raw markout (bp)")
ax.set_title("Raw markout term structure by coin  (entry-weighted, full sample)")
ax.legend(ncol=3, fontsize=9)
ax.annotate("HYPE hump\n(peak 8h)", xy=(3, raw["HYPE"][0][3]), xytext=(1.4, 6.5), fontsize=8.5,
            arrowprops=dict(arrowstyle="->", color="#999"), color=rs.COIN_COLORS["HYPE"])
rs.save(fig, "04_raw_termstructure")

# Fig 2 — raw vs neutralized (pooled) : how much of raw markout is just coin drift
fig, ax = plt.subplots(figsize=(7.2, 4.4))
mr, _ = raw["ALL"]; mn, _ = neut["ALL"]
ax.plot(X, mr, "-o", color="#1f77b4", label="raw markout", lw=2, ms=5)
ax.plot(X, mn, "-s", color="#d62728", label="neutralized (coin-month drift stripped)", lw=2, ms=5)
ax.fill_between(X, mn, mr, color="#bbb", alpha=0.35, label="coin drift")
ax.axhline(0, color="#888", lw=0.8, zorder=0)
ax.set_xticks(X); ax.set_xticklabels(LB); rs.bp_axis(ax)
ax.set_xlabel("markout horizon"); ax.set_ylabel("mean markout (bp), pooled")
ax.set_title("Raw vs neutralized markout — drift dominates the long horizons")
ax.legend(fontsize=9)
rs.save(fig, "04_raw_vs_neut")

# Fig 3 — per-coin raw vs neut at 24h (the drift flip, esp HYPE)
fig, ax = plt.subplots(figsize=(7.2, 4.2))
w = 0.36; xc = np.arange(len(COINS))
r24 = [raw[c][0][4] for c in COINS]; n24 = [neut[c][0][4] for c in COINS]
ax.bar(xc - w/2, r24, w, color="#1f77b4", label="raw 24h")
ax.bar(xc + w/2, n24, w, color="#d62728", label="neutralized 24h")
ax.axhline(0, color="#888", lw=0.8)
ax.set_xticks(xc); ax.set_xticklabels(COINS); rs.bp_axis(ax)
ax.set_ylabel("mean 24h markout (bp)")
ax.set_title("24h markout: raw vs neutralized — HYPE's +2.8bp is entirely coin drift (neut −18.6)")
ax.legend(fontsize=9)
rs.save(fig, "04_drift_flip_24h")

# Fig 4 — distribution (violin) of raw markout per coin at 4h and 24h
fig, axes = plt.subplots(1, 2, figsize=(10, 4.3))
for ax, h in zip(axes, ["4h", "24h"]):
    data = [df.filter(pl.col("coin") == c)[f"raw_{h}"].to_numpy() for c in COINS]
    data = [d[np.isfinite(d)] for d in data]
    # clip for display so violins are readable (tails are huge)
    clip = 400 if h == "4h" else 900
    dclip = [np.clip(d, -clip, clip) for d in data]
    parts = ax.violinplot(dclip, showmedians=True, showextrema=False)
    for i, b in enumerate(parts["bodies"]):
        b.set_facecolor(rs.COIN_COLORS[COINS[i]]); b.set_alpha(0.55)
    parts["cmedians"].set_color("#222")
    ax.axhline(0, color="#888", lw=0.8)
    ax.set_xticks(range(1, 5)); ax.set_xticklabels(COINS); rs.bp_axis(ax)
    ax.set_ylabel("raw markout (bp)" if h == "4h" else "")
    ax.set_title(f"{h} markout distribution (clipped ±{clip}bp)")
fig.suptitle("Markout distributions are wide and near-symmetric — means are small vs dispersion", fontsize=11.5, weight="bold")
rs.save(fig, "04_violin_dist")

print("raw ALL:", np.round(raw["ALL"][0], 2), "| neut ALL:", np.round(neut["ALL"][0], 2))
print("saved 04_raw_termstructure, 04_raw_vs_neut, 04_drift_flip_24h, 04_violin_dist")
