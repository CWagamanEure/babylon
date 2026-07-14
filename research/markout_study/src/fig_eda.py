"""Sections 2-3 figures — universe funnel + wallet EDA distributions. Light polars, no bar-pricing."""
import sys; from pathlib import Path
import numpy as np, polars as pl
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_style as rs
rs.setup()
COINS = ["BTC", "ETH", "SOL", "HYPE"]
df = pl.read_parquet("out/cohort_K_entries.parquet")

# Fig A — cohort selection funnel
fig, ax = plt.subplots(figsize=(8, 3.8))
stages = ["All majors wallets\n(≥200 fills)", "Copyable takers\n(n_copy≥100, taker≥0.70)", "Mid-freq cohort\n(hold 1–24h, n_train≥200)"]
vals = [29334, 12544, 1694]
ypos = np.arange(len(vals))[::-1]
for i, (s, v, y) in enumerate(zip(stages, vals, ypos)):
    ax.barh(y, v, color=plt.cm.Blues(0.4 + 0.2 * i), edgecolor="white")
    ax.text(v * 1.02, y, f"{v:,}", va="center", fontsize=10, weight="bold")
ax.set_yticks(ypos); ax.set_yticklabels(stages, fontsize=9)
ax.set_xscale("log"); ax.set_xlim(1000, 60000); ax.set_xlabel("wallets (log scale)")
ax.set_title("Analysis-cohort funnel: 32,949 universe wallets → 1,694 studied")
rs.save(fig, "02_funnel")

# Fig B — trade size (notl) distribution, log scale, per coin
fig, ax = plt.subplots(figsize=(7.6, 4.2))
bins = np.logspace(1.5, 6.5, 60)
for c in COINS:
    v = df.filter(pl.col("coin") == c)["notl"].to_numpy(); v = v[v > 0]
    ax.hist(v, bins=bins, histtype="step", lw=1.8, color=rs.COIN_COLORS[c], label=c, density=True)
ax.set_xscale("log"); ax.set_xlabel("trade notional $ (log scale)"); ax.set_ylabel("density")
ax.set_title("Trade-size distribution by coin  (median ≈ $4k, heavy right tail to ~$1M+)")
ax.legend(fontsize=9)
rs.save(fig, "03_size_dist")

# Fig C — direction long-share by coin
fig, ax = plt.subplots(figsize=(6.4, 3.9))
longs = [(df.filter(pl.col("coin") == c)["dir"] > 0).mean() * 100 for c in COINS]
allc = (df["dir"] > 0).mean() * 100
bars = ax.bar(COINS + ["ALL"], longs + [allc], color=[rs.COIN_COLORS[c] for c in COINS] + ["#555"])
ax.axhline(50, color="#888", lw=0.9, ls="--")
for b, v in zip(bars, longs + [allc]): ax.text(b.get_x() + b.get_width()/2, v + 1, f"{v:.0f}%", ha="center", fontsize=9)
ax.set_ylabel("% long entries"); ax.set_ylim(0, 85)
ax.set_title("Directional balance — long-biased, most in HYPE (73%)")
rs.save(fig, "03_direction")

# Fig D — entries per wallet
fig, ax = plt.subplots(figsize=(6.8, 3.9))
epw = df.group_by("wallet").len()["len"].to_numpy()
ax.hist(epw, bins=np.linspace(200, 2400, 50), color="#4c78a8", edgecolor="white")
ax.axvline(np.median(epw), color="#d62728", lw=1.6, label=f"median {int(np.median(epw))}")
ax.set_xlabel("train entries per wallet"); ax.set_ylabel("wallets")
ax.set_title("Entries per wallet (min 200 by construction)"); ax.legend(fontsize=9)
rs.save(fig, "03_entries_per_wallet")

# Fig E — hold-time distribution (real round-trip, from hold_size_dist)
try:
    hs = pl.read_parquet("out/hold_size_dist.parquet")
    hcol = "med_hold_h"
    h = hs[hcol].to_numpy(); h = h[np.isfinite(h) & (h > 0)]
    fig, ax = plt.subplots(figsize=(6.8, 3.9))
    ax.hist(h, bins=np.logspace(-1.3, 2.7, 55), color="#59a14f", edgecolor="white")
    ax.axvline(np.median(h), color="#d62728", lw=1.6, label=f"median {np.median(h):.1f}h")
    ax.set_xscale("log"); ax.set_xlabel("median hold time per wallet (h, log scale)"); ax.set_ylabel("wallets")
    ax.set_title(f"Round-trip hold times (n={len(h):,} wallets) — median ≈ 2h")
    ax.legend(fontsize=9); rs.save(fig, "03_holdtime")
    print("hold median", round(float(np.median(h)), 2))
except Exception as e:
    print("hold-time fig skipped:", e)

# Fig F — temporal composition (monthly entries stacked by coin)
piv = (df.with_columns(mo=pl.col("ym").cast(pl.Utf8)).group_by("mo", "coin").len().sort("mo"))
mos = sorted(df["ym"].unique().to_list())
bottom = np.zeros(len(mos))
fig, ax = plt.subplots(figsize=(9, 4.0))
for c in COINS:
    counts = []
    for m in mos:
        r = piv.filter((pl.col("mo") == str(m)) & (pl.col("coin") == c))
        counts.append(r["len"][0] if r.height else 0)
    counts = np.array(counts)
    ax.bar(range(len(mos)), counts, bottom=bottom, color=rs.COIN_COLORS[c], label=c)
    bottom += counts
ax.set_xticks(range(len(mos))); ax.set_xticklabels([str(m)[:4] + "-" + str(m)[4:] for m in mos], rotation=45, fontsize=8)
ax.set_ylabel("entries"); ax.set_title("Monthly entry volume by coin — BTC share rises, tape thins over time")
ax.legend(ncol=4, fontsize=9)
rs.save(fig, "03_temporal")

# Fig G — regime distribution
fig, ax = plt.subplots(figsize=(5.6, 3.7))
reg = df.group_by("regime").len().sort("len", descending=True)
labels = reg["regime"].to_list(); vals = reg["len"].to_numpy(); tot = vals.sum()
cols = {"BULL": "#59a14f", "BEAR": "#e15759", "CHOP": "#bab0ac"}
ax.bar(labels, vals / tot * 100, color=[cols.get(l, "#888") for l in labels])
for i, v in enumerate(vals): ax.text(i, v/tot*100 + 0.8, f"{v/tot*100:.0f}%", ha="center", fontsize=9)
ax.set_ylabel("% of entries"); ax.set_title("BTC 7d regime tag at entry")
rs.save(fig, "03_regime")

print("saved EDA figs")
