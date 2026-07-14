"""report v6 figures -> figs_v6/. Updates fixed-121 forest (absolute inference), adds coin-decomposition and
rolling fold-IC figures. Copies unchanged figures from figs_v5."""
import json, shutil; from pathlib import Path
import numpy as np, matplotlib.pyplot as plt, matplotlib as mpl
mpl.use("Agg")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; COL = {"BTC": "#4c6ef5", "ETH": "#7048e8", "SOL": "#0ca678", "HYPE": "#e8590c"}
FD = "figs_v6"; Path(FD).mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 140, "savefig.dpi": 140, "font.size": 11, "font.family": "DejaVu Sans",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.18,
    "grid.linewidth": 0.5, "axes.axisbelow": True, "axes.titlesize": 12, "legend.frameon": False})
def save(fig, n): fig.savefig(f"{FD}/{n}.png", bbox_inches="tight"); plt.close(fig)
def cap(ax, s, y=-0.16): ax.text(0, y, s, transform=ax.transAxes, fontsize=8.2, color="#666", va="top")
V = json.load(open("out/v6.json"))
WC = {"ew": "#e8590c", "wd": "#1c7ed6", "wcd": "#0ca678"}; WN = {"ew": "equal-wallet", "wd": "wallet-day", "wcd": "wallet-coin-day"}

# p10 — fixed-121 estimand forest with absolute inference (A gross, A cost-adj, B field, C fade) x 3 weightings
ff = V["fixed_full"]; groups = [("A_gross", "A: absolute gross"), ("A_costadj", "A: absolute cost-adjusted"),
                                ("B_field", "C: minus non-cohort field"), ("C_fade", "D: minus matched fade")]
rows = []
for gk, gl in groups:
    for w in ["ew", "wd", "wcd"]:
        v = ff[w][gk]; rows.append((f"{gl} · {WN[w]}", v[0], v[1], v[2], v[3], WC[w]))
    rows.append((None, None, None, None, None, None))  # spacer
rows = rows[:-1]
fig, ax = plt.subplots(figsize=(9.6, 8.2)); y = np.arange(len(rows))[::-1]
for yi, (lab, ptv, lo, hi, p, col) in zip(y, rows):
    if lab is None: continue
    ax.plot([lo, hi], [yi, yi], color=col, lw=2.2); ax.plot(ptv, yi, "o", color=col, ms=7)
    ax.text(hi, yi, f"  {ptv:+.1f} (p={p:.2f})", va="center", fontsize=8.3, color=col)
ax.axvline(0, color="#495057", lw=1, ls="--")
ax.set_yticks([yi for yi, r in zip(y, rows) if r[0]]); ax.set_yticklabels([r[0] for r in rows if r[0]], fontsize=8.6)
ax.set_xlabel("bp (validation period, 8h markout)")
ax.set_title("Fixed-121 cohort: absolute, field-relative and fade-relative returns")
cap(ax, "A = absolute cohort markout statistic (gross; cost-adjusted under 8/8/10/14 bp). C = minus non-cohort field (drift-neutralized, no cost). "
        "D = minus matched fade. Bars 95% calendar-day cluster CI; p = one-sided (A) / two-sided-vs-zero (C,D).", y=-0.11)
save(fig, "p10_fixed121_forest")

# p11 — coin decomposition of B (field-relative), wallet-day
cd = V["coin_decomp"]["per_coin"]; fig, ax = plt.subplots(figsize=(8.4, 4.6))
xs = np.arange(4)
for i, c in enumerate(COINS):
    b = cd[c]["B_field"]; ax.bar(i, b[0], color=COL[c], alpha=0.85, width=0.6)
    ax.plot([i, i], [b[1], b[2]], color="#222", lw=1.4)
ax.axhline(0, color="#adb5bd", lw=0.8)
ax.axhline(V["coin_decomp"]["coin_balanced_B"], color="#495057", lw=1.2, ls="--", label=f"coin-balanced {V['coin_decomp']['coin_balanced_B']:+.1f}")
ax.axhline(V["coin_decomp"]["ex_SOL_B"], color="#868e96", lw=1.1, ls=":", label=f"excluding SOL {V['coin_decomp']['ex_SOL_B']:+.1f}")
ax.set_xticks(xs); ax.set_xticklabels([f"{c}\n(n={cd[c]['active']}, wd={cd[c]['wallet_days']})" for c in COINS], fontsize=9)
ax.set_ylabel("cohort minus non-cohort field (bp)"); ax.set_title("Fixed-cohort field advantage by coin (wallet-day)")
ax.legend(fontsize=9.5)
cap(ax, "8h drift-neutralized, wallet-day weighted. Bars 95% calendar-day cluster CI. Present in all four coins (BTC/ETH/SOL resolved); ETH strongest; not SOL-dependent.")
save(fig, "p11_coin_decomp")

# p12 — rolling fold ICs
ri = V["rolling_ic"]; fic = ri["fold_ic"]; ks = list(fic.keys()); vals = [fic[k] for k in ks]
fig, ax = plt.subplots(figsize=(9.4, 4.2))
ax.bar(range(len(ks)), vals, color=["#c0392b" if v <= 0 else "#1c7ed6" for v in vals], alpha=0.85)
ax.axhline(ri["mean"], color="#495057", lw=1.3, ls="--", label=f"mean IC {ri['mean']:+.3f}")
ax.axhline(0, color="#adb5bd", lw=0.8)
ax.set_xticks(range(len(ks))); ax.set_xticklabels(ks, rotation=45, fontsize=8.5, ha="right")
ax.set_ylabel("adjacent-month rank IC (Spearman)"); ax.set_title("Rolling wallet-rank persistence, fold by fold")
ax.legend(fontsize=9.5)
cap(ax, f"Each bar = one month-pair forecast (neut_8h, wallet-day). {ri['n_positive']}/{ri['n_folds']} positive; sign test p={ri['sign_test_p']}; "
        f"leave-one-month-out mean IC in [{ri['lomo_mean_ic_range'][0]}, {ri['lomo_mean_ic_range'][1]}].", y=-0.42)
save(fig, "p12_rolling_ic")

# copy unchanged figures from figs_v5
for f in ["p1_eventstudy", "p2_heatmap", "p3_long_short", "p4_conditional", "p5_size", "p6_static", "p6_monthly",
          "p7_rolling_decile", "p8_topdiff_month", "p9_behavioral", "a_distribution", "a_regime_time",
          "f2_raw_vs_neut", "f1_termstructure", "f9_fade_ecdf"]:
    shutil.copy(f"figs_v5/{f}.png", f"{FD}/{f}.png")
print("saved figs_v6/ (fixed-121 forest + coin decomp + rolling IC; rest copied)")
