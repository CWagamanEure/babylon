"""
Figures for the OOS-persistence findings notebook. Reads out/persistence_{verdict,splits,controls}
.parquet (fast); ONE figure recomputes the joint-null distribution for BTC's primary cell so we can
show the real statistic against the full null (imports oos_persistence, ~1 min).

All figures saved to out/figs_persist/*.png. No fabricated data — every number traces to the run.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
FIGS = OUT / "figs_persist"
FIGS.mkdir(exist_ok=True)

COLORS = {"BTC": "#f7931a", "ETH": "#627eea", "SOL": "#9945ff", "HYPE": "#00b4a0", "SPX": "#e23"}
COINS = ["BTC", "ETH", "SOL", "HYPE", "SPX"]
METRICS = ["vw_edge", "avg_edge", "sharpe", "hit_rate", "cum_pnl"]
HZ = ["4h", "24h", "168h"]
PRIMARY = ("vw_edge", "24h")


def _save(fig, name):
    p = FIGS / f"{name}.png"
    fig.tight_layout(); fig.savefig(p, dpi=110, bbox_inches="tight"); plt.close(fig)
    return str(p)


def _V():
    return pl.read_parquet(OUT / "persistence_verdict.parquet")


def _S():
    return pl.read_parquet(OUT / "persistence_splits.parquet")


def _C():
    return pl.read_parquet(OUT / "persistence_controls.parquet")


def fig_primary_vs_null():
    """THE headline: primary-cell cohort edge vs the top-50-random null p95, per coin."""
    v = _V().filter((pl.col("metric") == PRIMARY[0]) & (pl.col("horizon") == PRIMARY[1]))
    v = v.sort("coin")
    coins = v["coin"].to_list()
    S = v["S_bps"].to_list(); p95 = v["null_p95_bps"].to_list(); p = v["joint_p"].to_list()
    x = np.arange(len(coins)); w = 0.38
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x - w / 2, S, w, label="cohort edge (top-50 by train vw_edge)", color=[COLORS[c] for c in coins])
    ax.bar(x + w / 2, p95, w, label="random-selection null (95th pct)", color="#bbb")
    for i, (s, pp) in enumerate(zip(S, p)):
        ax.annotate(f"p={pp:.2f}", (i, max(S[i], p95[i]) + 3), ha="center", fontsize=8)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xticks(x); ax.set_xticklabels(coins)
    ax.set_ylabel("test-window deployable edge (bps)")
    ax.set_title("Primary cell (vw_edge @ 24h): ranked cohort does not CLEAR random selection\n"
                 "4/5 coins positive but each inside its own null (min p=0.09, BTC) — inconclusive, not disproof")
    ax.legend(fontsize=8)
    return _save(fig, "01_primary_vs_null")


def fig_pgrid():
    """Joint-null p across all coin x (metric,horizon) cells; mark raw-sig and FDR survivors."""
    v = _V()
    cells = [(m, h) for h in HZ for m in METRICS]
    labels = [f"{m}\n{h}" for (m, h) in cells]
    grid = np.full((len(COINS), len(cells)), np.nan)
    rawsig = np.zeros_like(grid, bool); fdr = np.zeros_like(grid, bool)
    for i, c in enumerate(COINS):
        for j, (m, h) in enumerate(cells):
            r = v.filter((pl.col("coin") == c) & (pl.col("metric") == m) & (pl.col("horizon") == h))
            if r.height:
                grid[i, j] = r["joint_p"][0]
                rawsig[i, j] = bool(r["persists"][0]); fdr[i, j] = bool(r["persists_fdr"][0])
    fig, ax = plt.subplots(figsize=(13, 3.6))
    im = ax.imshow(grid, aspect="auto", cmap="RdYlGn", vmin=0, vmax=0.5)
    ax.set_xticks(range(len(cells))); ax.set_xticklabels(labels, fontsize=6)
    ax.set_yticks(range(len(COINS))); ax.set_yticklabels(COINS)
    for i in range(len(COINS)):
        for j in range(len(cells)):
            if rawsig[i, j]:
                ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1, fill=False, edgecolor="k", lw=1.6))
            if not np.isnan(grid[i, j]):
                ax.text(j, i, f"{grid[i,j]:.2f}", ha="center", va="center", fontsize=6,
                        color="k" if grid[i, j] > .30 else "w")
    fig.colorbar(im, ax=ax, label="joint-null p", fraction=0.02)
    ax.set_title(f"Joint-null p across all 75 cells — {int(rawsig.sum())} cross raw p<0.05 & S>0 "
                 f"(boxed, ALL at 168h); {int(fdr.sum())} survive FDR. "
                 "168h = right-censored horizon (see fig 6), so these are low-N noise.")
    return _save(fig, "02_pgrid")


def fig_power():
    """Positive-control detection rate vs injected delta (MDE), negative control at 5%."""
    c = _C()
    pos = c.filter(pl.col("control") == "positive").sort("delta_bps")
    neg = c.filter(pl.col("control") == "negative")
    mde = c.filter(pl.col("control") == "MDE")["delta_bps"]
    mde = mde[0] if mde.len() and mde[0] is not None else None
    d = pos["delta_bps"].to_list(); rate = pos["rate"].to_list()
    fig, ax = plt.subplots(figsize=(8.5, 4))
    ax.plot(d, rate, "-o", color="#c0392b", lw=2, label="positive control (injected edge)")
    ax.axhline(0.8, color="gray", ls="--", lw=1, label="80% power")
    ax.axhline(float(neg["rate"][0]), color="steelblue", ls=":", lw=1.2,
               label=f"negative control FP = {float(neg['rate'][0]):.2f}")
    if mde:
        ax.axvline(mde, color="k", ls="--", lw=1)
        ax.annotate(f"MDE = {mde} bp/entry", (mde, 0.45), rotation=90, fontsize=8, va="center")
    ax.set_xscale("log"); ax.set_xticks(d); ax.set_xticklabels([str(x) for x in d])
    ax.set_xlabel("injected persistent edge Δ (bps PER ENTRY)"); ax.set_ylabel("detection rate")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("Power (BTC primary, best case): the test only resolves a >= 160 bp/ENTRY edge.\n"
                 "Realistic per-entry edges are far smaller -> naive top-50 ranking is BLIND to them,\n"
                 "so a null here is inconclusive for realistic persistence, not proof of none.")
    ax.legend(fontsize=8, loc="center right")
    return _save(fig, "03_power")


def fig_recovered():
    """Recovered cohort edge vs injected delta — winsor-cap attenuation ceiling."""
    c = _C().filter(pl.col("control") == "positive").sort("delta_bps")
    d = c["delta_bps"].to_list(); rec = c["recovered_bps"].to_list()
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.plot(d, rec, "-o", color="teal", lw=2, label="recovered cohort edge")
    ax.plot(d, d, "--", color="gray", lw=1, label="y = Δ (no attenuation)")
    ax.axhline(890, color="crimson", ls=":", lw=1.2, label="winsor cap ~890 bp")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("injected Δ (bps/entry)"); ax.set_ylabel("recovered cohort edge (bps)")
    ax.set_title("Recovered edge attenuates increasingly below Δ toward the p99 winsor cap (~890 bp).\n"
                 "Confirms the magnitude clip works as designed (does not amplify).")
    ax.legend(fontsize=8)
    return _save(fig, "04_recovered")


def fig_spearman():
    """Rank-correlation(train metric, test edge) per coin x metric — the 'no predictive power' view."""
    v = _V().filter(pl.col("horizon") == PRIMARY[1])
    x = np.arange(len(METRICS)); w = 0.15
    fig, ax = plt.subplots(figsize=(9, 4))
    for k, c in enumerate(COINS):
        vals = [v.filter((pl.col("coin") == c) & (pl.col("metric") == m))["spearman"].to_list() for m in METRICS]
        vals = [x[0] if x else np.nan for x in vals]
        ax.bar(x + (k - 2) * w, vals, w, label=c, color=COLORS[c])
    ax.axhspan(-0.05, 0.05, color="gray", alpha=0.15, label="|rho|<0.05 (~noise)")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xticks(x); ax.set_xticklabels(METRICS)
    ax.set_ylabel("Spearman(train metric, test edge)")
    ax.set_ylim(-1.0, 1.0)   # full range: a real rank signal would fill much of this; these hug 0
    ax.set_title("Rank correlation hugs 0 (|rho|<0.07) for every metric x coin (24h).\n"
                 "NB rho is survivor-conditioned & attenuated by the >=10-entry floor -> corroborating, not decisive")
    ax.legend(fontsize=8, ncol=3)
    return _save(fig, "05_spearman")


def fig_censoring():
    """n_active per top-50 pick, 24h vs 168h, showing the 168h low-N/censoring artifact."""
    s = _S().filter(pl.col("metric") == "vw_edge")
    fig, ax = plt.subplots(figsize=(9, 4))
    for h, col in [("24h", "#2c7"), ("168h", "#c0392b")]:
        d = s.filter(pl.col("horizon") == h).group_by("test_bucket").agg(n=pl.col("n_active").mean()).sort("test_bucket")
        ax.plot(d["test_bucket"], d["n"], "-o", color=col, label=f"{h}")
    ax.axhline(50, color="gray", ls="--", lw=1, label="top-50 (full cohort)")
    ax.set_xlabel("test split (bucket)"); ax.set_ylabel("active wallets in top-50 (mean over coins)")
    ax.set_title("Both horizons are thin (only ~12-19 of top-50 trade in the next window), but 168h\n"
                 "decays to ~0 at the final seam (7-day exits right-censored) -> the 168h 'hits' are low-N noise")
    ax.legend(fontsize=8)
    return _save(fig, "06_censoring")


def fig_split_scatter():
    """Per-split primary-cell cohort edge per coin vs the null band — spread around ~0."""
    s = _S().filter((pl.col("metric") == PRIMARY[0]) & (pl.col("horizon") == PRIMARY[1]))
    v = _V().filter((pl.col("metric") == PRIMARY[0]) & (pl.col("horizon") == PRIMARY[1]))
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for i, c in enumerate(COINS):
        d = s.filter(pl.col("coin") == c)["cohort_vw_bps"].drop_nulls().to_numpy()
        ax.scatter(np.full(d.size, i) + np.linspace(-0.15, 0.15, d.size), d, color=COLORS[c], s=28,
                   alpha=0.7, label="per-split cohort edge" if i == 0 else None)
        r = v.filter(pl.col("coin") == c)
        if r.height and r["S_bps"][0] is not None:
            ax.plot([i - 0.28, i + 0.28], [r["S_bps"][0]] * 2, color="k", lw=2.4,
                    label="AGGREGATE S (the verdict statistic)" if i == 0 else None)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xticks(range(len(COINS))); ax.set_xticklabels(COINS)
    ax.set_ylabel("cohort edge (bps)")
    ax.set_title("Per-split cohort edge (dots) has HUGE spread — single splits swing +/-hundreds of bp.\n"
                 "The verdict is the turnover-weighted AGGREGATE (black bar), which the joint null tests;\n"
                 "no single split is the finding, and the aggregate lands within its null.")
    ax.legend(fontsize=8, loc="upper left")
    return _save(fig, "07_split_scatter")


def fig_null_hist(recompute=True):
    """BTC primary cell: real statistic S against the FULL joint-null distribution."""
    v = _V().filter((pl.col("coin") == "BTC") & (pl.col("metric") == PRIMARY[0]) & (pl.col("horizon") == PRIMARY[1]))
    S = float(v["S_bps"][0]); p = float(v["joint_p"][0])
    if recompute:
        import oos_persistence as P
        from mkcommon import _load_bars
        lk = _load_bars(); ctx = P.build_coin("BTC", lk["BTC"]); tab = P.split_tables(ctx)
        hi = P.PH.index(PRIMARY[1])
        s_null = P.joint_null(tab[hi], ctx["codes"], ctx["W"])
        s_null = s_null[np.isfinite(s_null)]
    else:
        s_null = np.array([])
    fig, ax = plt.subplots(figsize=(8, 4))
    if s_null.size:
        ax.hist(s_null, bins=50, color="#bbb", label="null: top-50 by RANDOM score")
        ax.axvline(np.percentile(s_null, 95), color="gray", ls="--", lw=1.2, label="null 95th pct")
    ax.axvline(S, color="#f7931a", lw=2.5, label=f"real ranked cohort S = {S:.0f} bp")
    ax.set_xlabel("aggregate top-50 test edge (bps)"); ax.set_ylabel("permutations")
    ax.set_title(f"BTC vw_edge@24h: the ranked cohort (orange) falls INSIDE the random null.\n"
                 f"joint p = {p:.2f} — ranking by past edge does not beat random selection.")
    ax.legend(fontsize=8)
    return _save(fig, "08_null_hist")


ALL = [fig_primary_vs_null, fig_pgrid, fig_power, fig_recovered, fig_spearman,
       fig_censoring, fig_split_scatter, fig_null_hist]

if __name__ == "__main__":
    for f in ALL:
        print("OK", f.__name__, "->", f())
