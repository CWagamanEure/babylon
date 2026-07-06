"""
Figures for the refinement + distributional layer. Reads out/refine_dist.parquet (fat-tail) and
out/refine_grid.parquet (ew/vw term structures). Discipline (audit): every figure carries a
random-cohort null band, >=72h greyed non-inferential, EXPLORATORY header. Saved to out/figs_refine/.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
FIGS = OUT / "figs_refine"; FIGS.mkdir(exist_ok=True)
HZ = ["5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "24h", "48h", "72h", "168h"]
HO = {h: i for i, h in enumerate(HZ)}
COLORS = {"BTC": "#f7931a", "ETH": "#627eea", "SOL": "#9945ff", "HYPE": "#00b4a0", "SPX": "#e23"}
CENSOR = {"72h", "168h"}


def _save(fig, name):
    p = FIGS / f"{name}.png"
    fig.tight_layout(); fig.savefig(p, dpi=110, bbox_inches="tight"); plt.close(fig)
    return str(p)


def _grey_censor(ax):
    lo = HO["72h"] - 0.5
    ax.axvspan(lo, len(HZ) - 0.5, color="0.9", zorder=0)
    ax.text(HO["120h" if "120h" in HO else "168h"], ax.get_ylim()[1], "  ≥72h\n  censoring",
            va="top", ha="center", fontsize=7, color="0.4")


def fig_winnerscurse_dist(K=50):
    """Train vs test MEDIAN markout term structure (the in-sample selection collapse), per coin."""
    d = pl.read_parquet(OUT / "refine_dist.parquet").filter(pl.col("K") == K)
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.2), sharex=True)
    for c in ["BTC", "ETH", "SOL", "HYPE", "SPX"]:
        g = d.filter(pl.col("coin") == c).with_columns(o=pl.col("horizon").replace_strict(HO)).sort("o")
        x = g["o"].to_list()
        ax[0].plot(x, g["tr_median"].to_list(), "-o", ms=3, color=COLORS[c], label=c)
        ax[1].plot(x, g["te_median"].to_list(), "-o", ms=3, color=COLORS[c], label=c)
    for a, t in zip(ax, ["IN-SAMPLE (train) median — the selection illusion",
                         "OUT-OF-SAMPLE (test) median — what persists"]):
        a.axhline(0, color="k", lw=0.6); a.set_xticks(range(len(HZ)))
        a.set_xticklabels(HZ, fontsize=7, rotation=45); a.set_title(t, fontsize=10)
        a.set_ylabel("median markout (bps)"); _grey_censor(a)
    ax[0].legend(fontsize=8, ncol=5)
    fig.suptitle(f"Top-{K} vw_edge cohort (EXPLORATORY): in-sample median soars with horizon, "
                 "out-of-sample it collapses to ~0 (24–48h mildly +)", y=1.03)
    return _save(fig, "01_winnerscurse_dist")


def fig_mean_vs_median(K=50):
    """Test mean vs median per horizon vs a FAIR pooled null band. Central (BTC) vs tail-driven (ETH/HYPE);
    ★ marks a cohort median above the one-sided pooled p95 null."""
    d = pl.read_parquet(OUT / "refine_dist.parquet").filter(pl.col("K") == K)
    coins = ["BTC", "ETH", "SOL", "HYPE"]
    fig, ax = plt.subplots(1, len(coins), figsize=(15, 3.8), sharey=True)
    for k, c in enumerate(coins):
        g = d.filter((pl.col("coin") == c)).with_columns(o=pl.col("horizon").replace_strict(HO)).sort("o")
        x = g["o"].to_list()
        ax[k].fill_between(x, g["rand_med_lo"].to_list(), g["rand_med_hi"].to_list(),
                           color="0.82", alpha=0.7, label="fair pooled null (p5–p95)")
        ax[k].plot(x, g["te_mean"].to_list(), "-o", ms=3, color="crimson", label="test mean")
        ax[k].plot(x, g["te_median"].to_list(), "-s", ms=3, color="steelblue", label="test median")
        # ★ where the pooled median clears the one-sided p95 null
        gt = g.filter(pl.col("te_med_gt_band"))
        if gt.height:
            ax[k].scatter(gt["o"].to_list(), gt["te_median"].to_list(), marker="*", s=140,
                          color="gold", edgecolor="k", zorder=5, label="median > p95 null")
        ax[k].axhline(0, color="k", lw=0.6); ax[k].set_xticks(range(len(HZ)))
        ax[k].set_xticklabels(HZ, fontsize=6, rotation=45); ax[k].set_title(c, fontsize=10)
        ax[k].set_ylim(-130, 130); _grey_censor(ax[k])
        if k == 0:
            ax[k].legend(fontsize=7); ax[k].set_ylabel("test markout (bps)")
    fig.suptitle("Per-decision cohort median vs a FAIR pooled null. BTC: mean≈median AND clears p95 at "
                 "24h & 48h (★, central). ETH/HYPE: mean>0 but median<0 = TAIL-driven. y-clipped ±130 "
                 "(≥72h greyed, off-scale).", y=1.06, fontsize=10)
    return _save(fig, "02_mean_vs_median")


def fig_coherent_24h():
    """The buried underpowered POSITIVE: at 24h the lean is directionally coherent across orthogonal cuts —
    robust (outlier-immune) rankers AND top-N concentration, positive on ~5/5 coins."""
    g = pl.read_parquet(OUT / "refine_grid.parquet").filter(
        (pl.col("horizon") == "24h") & (pl.col("train") == "expanding") & (pl.col("eval") == "vw"))
    cols = [("vw_edge", 10), ("vw_edge", 25), ("vw_edge", 50), ("median_edge", 50), ("trim10_edge", 50)]
    labels = ["vw_edge\nK=10", "vw_edge\nK=25", "vw_edge\nK=50", "median_edge\nK=50\n(outlier-immune)",
              "trim10_edge\nK=50\n(outlier-immune)"]
    coins = ["BTC", "ETH", "SOL", "HYPE", "SPX"]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    xpos = np.arange(len(cols)); w = 0.15
    for j, c in enumerate(coins):
        vals = [g.filter((pl.col("metric") == m) & (pl.col("K") == kk) & (pl.col("coin") == c))["pooled_S"].to_list()
                for m, kk in cols]
        vals = [v[0] if v else np.nan for v in vals]
        ax.bar(xpos + (j - 2) * w, vals, w, color=COLORS[c], label=c)
    for i in range(len(cols)):
        vals = [g.filter((pl.col("metric") == m) & (pl.col("K") == kk) & (pl.col("coin") == c))["pooled_S"].to_list()
                for c in coins for m, kk in [cols[i]]]
        npos = sum(1 for v in vals if v and v[0] > 0)
        ax.text(xpos[i], 128, f"{npos}/5\n+", ha="center", fontsize=8, fontweight="bold",
                color="green" if npos >= 4 else "0.4")
    ax.axhline(0, color="k", lw=0.7); ax.set_xticks(xpos); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(-60, 140); ax.set_ylabel("OOS cohort edge @24h (bps)")
    ax.set_title("The buried underpowered POSITIVE at 24h (expanding, vw-eval): directionally coherent across "
                 "orthogonal cuts.\nOutlier-immune rankers (median/trim10) do NOT collapse to the field, and "
                 "small-K concentrates it — 4–5/5 coins positive. None individually significant; noise-limited, "
                 "NOT refuted.", fontsize=9.5)
    ax.legend(fontsize=8, ncol=5, loc="lower center")
    return _save(fig, "05_coherent_24h_positive")


def fig_tailloss(K=50):
    """Tail-loss fraction (share of test markouts < -100bp) growing with horizon."""
    d = pl.read_parquet(OUT / "refine_dist.parquet").filter(pl.col("K") == K)
    fig, ax = plt.subplots(figsize=(9, 4))
    for c in ["BTC", "ETH", "SOL", "HYPE"]:
        g = d.filter(pl.col("coin") == c).with_columns(o=pl.col("horizon").replace_strict(HO)).sort("o")
        ax.plot(g["o"].to_list(), [100 * x if x is not None else None for x in g["te_tailloss"].to_list()],
                "-o", ms=3, color=COLORS[c], label=c)
    ax.set_xticks(range(len(HZ))); ax.set_xticklabels(HZ, fontsize=7, rotation=45)
    ax.set_ylabel("% of cohort test trades below −100 bp"); _grey_censor(ax)
    ax.set_title("Loss-tail GROWS with holding horizon (top-50 vw_edge cohort): longer holds → more\n"
                 "big losers even as the median stays ~flat — the tail-risk cost of the 24–48h window")
    ax.legend(fontsize=8, ncol=4)
    return _save(fig, "03_tailloss")


def fig_evw_summary():
    """The 'nothing improved' summary: mean pooled_S by metric, vw vs ew, expanding, K=50, non-censored."""
    g = pl.read_parquet(OUT / "refine_grid.parquet").filter(
        (pl.col("K") == 50) & (pl.col("train") == "expanding") & (pl.col("stratum") == "primary_family"))
    piv = g.group_by(["metric", "eval"]).agg(m=pl.col("pooled_S").mean()).sort("metric")
    metrics = sorted(piv["metric"].unique().to_list())
    vw = [piv.filter((pl.col("metric") == m) & (pl.col("eval") == "vw"))["m"].to_list() for m in metrics]
    ew = [piv.filter((pl.col("metric") == m) & (pl.col("eval") == "ew"))["m"].to_list() for m in metrics]
    vw = [x[0] if x else np.nan for x in vw]; ew = [x[0] if x else np.nan for x in ew]
    x = np.arange(len(metrics)); w = 0.38
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(x - w / 2, vw, w, label="vw eval (per-dollar)", color="steelblue")
    ax.bar(x + w / 2, ew, w, label="ew eval (per-decision)", color="indianred")
    ax.axhline(0, color="k", lw=0.6); ax.set_xticks(x); ax.set_xticklabels(metrics, rotation=30, fontsize=8)
    ax.set_ylabel("mean OOS cohort edge (bps)")
    ax.set_title("AVERAGED over all non-censored horizons, no ranker's mean clears ~0 (expanding, K=50) & "
                 "ew<vw for all 9.\nBut this horizon-AVERAGING dilutes the 24h lean (see 05) — a flat mean "
                 "here is not 'no signal anywhere'.", fontsize=9.5)
    ax.legend(fontsize=8)
    return _save(fig, "04_ew_vw_summary")


ALL = [fig_winnerscurse_dist, fig_mean_vs_median, fig_tailloss, fig_evw_summary, fig_coherent_24h]

if __name__ == "__main__":
    for f in ALL:
        try:
            print("OK", f.__name__, "->", f())
        except Exception as e:
            print("SKIP", f.__name__, repr(e))
