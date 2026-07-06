"""
EDA figure library for the Majors Markout Study. One function per figure; each loads the
stage-2/3 (+ eda_prep) artifacts, computes, saves a PNG to out/figs/, and returns the fig so
a notebook can display it. NO heavy recompute here — everything reads the aggregated parquets.

Correctness notes (audited):
- Horizons are ALWAYS ordered by the ladder index H_LABELS, never alphabetically.
- The field term structure uses the WINSORIZED field mean (matches the deployable estimator).
- "Deployable" numbers are volume-weighted (vw_edge / net_exec); equal-weight (avg_edge) is
  shown only where explicitly labelled size-blind.
- Every figure that shows selected/candidate wallets carries the in-sample caveat in its title.
"""
from pathlib import Path

import numpy as np
import polars as pl
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
FIGS = OUT / "figs"
FIGS.mkdir(exist_ok=True)

H_LABELS = ["5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "24h", "48h", "72h", "168h"]
HIDX = {h: i for i, h in enumerate(H_LABELS)}
MAJORS = ["BTC", "ETH", "SOL", "HYPE", "SPX"]
COLORS = {"BTC": "#F7931A", "ETH": "#627EEA", "SOL": "#14F195", "HYPE": "#2EC4B6",
          "SPX": "#111111", "ALT": "#B0B0B0"}
plt.rcParams.update({"figure.dpi": 110, "axes.grid": True, "grid.alpha": 0.25,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})


def _load(name):
    return pl.read_parquet(OUT / name)


def _save(fig, name):
    fig.tight_layout()
    fig.savefig(FIGS / f"{name}.png", bbox_inches="tight")
    return fig


def _hx(labels):
    """map a list of horizon labels to their ladder x-positions."""
    return [HIDX[l] for l in labels]


# ------------------------------------------------------------------ scope / data quality
def fig_scope():
    s = _load("markout_stats.parquet")
    per = (s.group_by("coin").agg(cells=pl.len(), wallets=pl.col("wallet").n_unique())
           .filter(pl.col("coin").is_in(MAJORS)))
    per = per.sort("wallets", descending=True)
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
    b0 = ax[0].bar(per["coin"], per["wallets"], color=[COLORS[c] for c in per["coin"]])
    ax[0].bar_label(b0, fmt="%d", padding=2, fontsize=8)
    ax[0].set_title("Wallets scored per market (>=30 entries)"); ax[0].set_ylabel("wallets")
    b1 = ax[1].bar(per["coin"], per["cells"], color=[COLORS[c] for c in per["coin"]])
    ax[1].bar_label(b1, fmt="%d", padding=2, fontsize=8)
    ax[1].set_title("(wallet,horizon) stat cells per market"); ax[1].set_ylabel("cells")
    for a in ax:
        a.margins(y=0.15)
    return _save(fig, "01_scope")


def fig_coverage():
    c = _load("coverage_report.parquet").filter(pl.col("coin").is_in(MAJORS))
    M = np.full((len(MAJORS), len(H_LABELS)), np.nan)
    for r in c.iter_rows(named=True):
        if r["horizon"] in HIDX and r["coin"] in MAJORS:
            M[MAJORS.index(r["coin"]), HIDX[r["horizon"]]] = r["valid_frac"] * 100
    fig, ax = plt.subplots(figsize=(9, 3.2))
    im = ax.imshow(M, aspect="auto", cmap="viridis", vmin=90, vmax=100)
    ax.set_xticks(range(len(H_LABELS))); ax.set_xticklabels(H_LABELS)
    ax.set_yticks(range(len(MAJORS))); ax.set_yticklabels(MAJORS)
    ax.set_title("Coverage: % of entries priceable at each horizon (>=90% shown)")
    for i in range(len(MAJORS)):
        for j in range(len(H_LABELS)):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{M[i,j]:.0f}", ha="center", va="center",
                        color="white" if M[i, j] < 97 else "black", fontsize=7)
    fig.colorbar(im, ax=ax, label="% valid")
    return _save(fig, "02_coverage")


# ------------------------------------------------------------------ THE centerpiece
def fig_term_structure(metric="field_mean_bps", title=None, name="03_term_structure"):
    f = _load("field_by_coin_horizon.parquet")
    fig, ax = plt.subplots(figsize=(9, 5))
    for coin in MAJORS + ["ALT"]:
        sub = f.filter((pl.col("coin") == coin) & pl.col(metric).is_not_null())
        if sub.height == 0:
            continue
        rows = sorted([(HIDX[r["horizon"]], r[metric]) for r in sub.iter_rows(named=True)
                       if r["horizon"] in HIDX])
        xs = [a for a, _ in rows]; ys = [b for _, b in rows]
        ax.plot(xs, ys, "-o", ms=4, lw=1.8 if coin != "ALT" else 1.2,
                color=COLORS[coin], label=coin, alpha=0.9 if coin != "ALT" else 0.6)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(len(H_LABELS))); ax.set_xticklabels(H_LABELS)
    ax.set_xlabel("holding horizon"); ax.set_ylabel("mean markout (bps)")
    ax.set_title(title or "Field markout term structure — mean signed markout by exit horizon")
    ax.legend(ncol=3, fontsize=9)
    return _save(fig, name)


def fig_term_structure_zoom():
    """Same as centerpiece but zoomed to the short horizons where the hump lives."""
    f = _load("field_by_coin_horizon.parquet")
    fig, ax = plt.subplots(figsize=(9, 5))
    short = ["5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "24h"]
    for coin in MAJORS + ["ALT"]:
        sub = f.filter((pl.col("coin") == coin) & pl.col("field_mean_bps").is_not_null())
        rows = sorted([(HIDX[r["horizon"]], r["field_mean_bps"]) for r in sub.iter_rows(named=True)
                       if r["horizon"] in short])
        if not rows:
            continue
        xs = [a for a, _ in rows]; ys = [b for _, b in rows]
        ax.plot(xs, ys, "-o", ms=4, lw=1.8 if coin != "ALT" else 1.2, color=COLORS[coin],
                label=coin, alpha=0.9 if coin != "ALT" else 0.6)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylim(-12, 6)   # focus on the hump; SPX/ALT continue down off-panel (see full fig)
    ax.set_xticks([HIDX[h] for h in short]); ax.set_xticklabels(short)
    ax.set_xlabel("holding horizon"); ax.set_ylabel("mean markout (bps)")
    ax.set_title("Term structure, short-horizon zoom (5m–24h): the positive-drift window\n(SPX/ALT fall off-panel past 8h — see full figure)")
    ax.legend(ncol=3, fontsize=9)
    return _save(fig, "04_term_structure_zoom")


def fig_winsor_effect():
    f = _load("eda_field_dir.parquet")
    fig, ax = plt.subplots(1, len(MAJORS), figsize=(15, 3), sharey=False)
    for k, coin in enumerate(MAJORS):
        sub = f.filter(pl.col("coin") == coin)
        rows = sorted([(HIDX[r["horizon"]], r["field_raw_bps"], r["field_wins_bps"])
                       for r in sub.iter_rows(named=True) if r["horizon"] in HIDX])
        xs = [a for a, _, _ in rows]
        ax[k].plot(xs, [b for _, b, _ in rows], "-o", ms=3, color="crimson", label="raw", alpha=0.7)
        ax[k].plot(xs, [c for _, _, c in rows], "-o", ms=3, color="steelblue", label="winsorized")
        ax[k].axhline(0, color="k", lw=0.6)
        ax[k].set_xticks(range(0, len(H_LABELS), 3)); ax[k].set_xticklabels(H_LABELS[::3], fontsize=7)
        ax[k].set_title(coin, fontsize=10)
        if k == 0:
            ax[k].set_ylabel("field mean (bps)"); ax[k].legend(fontsize=8)
    fig.suptitle("Winsorization effect on the field mean (raw vs p99-magnitude winsorized)", y=1.05)
    return _save(fig, "05_winsor_effect")


def fig_downside_term():
    f = _load("field_by_coin_horizon.parquet").filter(pl.col("field_dd_bps").is_not_null())
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for coin in MAJORS:
        sub = f.filter(pl.col("coin") == coin)
        rows = sorted([(HIDX[r["horizon"]], r["field_dd_bps"]) for r in sub.iter_rows(named=True)
                       if r["horizon"] in HIDX])
        if not rows:
            continue
        ax.plot([a for a, _ in rows], [b for _, b in rows], "-o", ms=4, color=COLORS[coin], label=coin)
    ax.set_xticks(range(len(H_LABELS))); ax.set_xticklabels(H_LABELS)
    ax.set_xlabel("holding horizon"); ax.set_ylabel("downside deviation (bps)")
    ax.set_title("Field downside-deviation term structure (risk grows with horizon)")
    ax.legend(ncol=3, fontsize=9)
    return _save(fig, "06_downside_term")


def fig_long_short():
    f = _load("eda_field_dir.parquet")
    fig, ax = plt.subplots(1, len(MAJORS), figsize=(15, 3), sharey=False)
    for k, coin in enumerate(MAJORS):
        sub = f.filter(pl.col("coin") == coin)
        rows = sorted([(HIDX[r["horizon"]], r["long_bps"], r["short_bps"])
                       for r in sub.iter_rows(named=True) if r["horizon"] in HIDX])
        xs = [a for a, _, _ in rows]
        ax[k].plot(xs, [b for _, b, _ in rows], "-o", ms=3, color="green", label="long", alpha=0.8)
        ax[k].plot(xs, [c for _, _, c in rows], "-o", ms=3, color="red", label="short", alpha=0.8)
        ax[k].axhline(0, color="k", lw=0.6)
        ax[k].set_xticks(range(0, len(H_LABELS), 3)); ax[k].set_xticklabels(H_LABELS[::3], fontsize=7)
        ax[k].set_title(coin, fontsize=10)
        if k == 0:
            ax[k].set_ylabel("markout (bps)"); ax[k].legend(fontsize=8)
    fig.suptitle("Long vs short taker markout by horizon (directional asymmetry)", y=1.05)
    return _save(fig, "07_long_short")


# ------------------------------------------------------------------ per-wallet distributions
def fig_edge_dist():
    s = _load("markout_stats.parquet")
    hs = ["1h", "24h", "168h"]
    fig, ax = plt.subplots(1, 3, figsize=(14, 3.6))
    for k, h in enumerate(hs):
        for coin in ["BTC", "HYPE"]:
            v = s.filter((pl.col("coin") == coin) & (pl.col("horizon") == h))["vw_edge_bps"].drop_nulls().to_numpy()
            n = v.size
            v = v[np.abs(v) < np.nanpercentile(np.abs(v), 99)]  # trim for display only
            ax[k].hist(v, bins=60, alpha=0.5, color=COLORS[coin], label=f"{coin} (n={n:,})", density=True)
        ax[k].axvline(0, color="k", lw=0.8)
        ax[k].set_title(f"per-wallet vw_edge @ {h}"); ax[k].set_xlabel("bps")
        ax[k].legend(fontsize=8)
    fig.suptitle("Per-wallet deployable edge: BTC (deepest market) vs HYPE (widest dispersion) "
                 "— display-trimmed at 99th pct", y=1.04)
    return _save(fig, "08_edge_dist")


def fig_size_blind_vs_deployable():
    s = _load("markout_stats.parquet").filter((pl.col("coin") == "BTC") & (pl.col("horizon") == "24h"))
    a = s["avg_edge_bps"].to_numpy(); v = s["vw_edge_bps"].to_numpy()
    m = np.isfinite(a) & np.isfinite(v)
    lim = np.nanpercentile(np.abs(np.concatenate([a[m], v[m]])), 99)
    fig, ax = plt.subplots(figsize=(5.4, 5.2))
    ax.scatter(a[m], v[m], s=5, alpha=0.15, color="steelblue")
    ax.plot([-lim, lim], [-lim, lim], "k--", lw=0.8, label="y=x")
    ax.axhline(0, color="k", lw=0.5); ax.axvline(0, color="k", lw=0.5)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.set_xlabel("equal-weight edge (size-blind, bps)"); ax.set_ylabel("volume-weight edge (deployable, bps)")
    ax.set_title("BTC 24h: size-blind vs deployable per-wallet edge\n(divergence = capacity trap)")
    ax.legend()
    return _save(fig, "09_size_blind_vs_deployable")


def fig_n_vs_edge():
    s = _load("markout_stats.parquet").filter((pl.col("coin") == "BTC") & (pl.col("horizon") == "24h"))
    n = s["n"].to_numpy(); v = s["vw_edge_bps"].to_numpy()
    m = np.isfinite(v) & (n > 0)
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.scatter(n[m], v[m], s=5, alpha=0.15, color="darkorange")
    ax.set_xscale("log"); ax.axhline(0, color="k", lw=0.6)
    ax.set_ylim(np.nanpercentile(v[m], 1), np.nanpercentile(v[m], 99))
    ax.set_xlabel("entries (evidence, log)"); ax.set_ylabel("deployable edge (bps)")
    ax.set_title("BTC 24h: does more activity mean more edge? (evidence vs edge)")
    return _save(fig, "10_n_vs_edge")


# ------------------------------------------------------------------ the deliverable / candidates
def fig_hstar_dist():
    o = _load("optimal_exit.parquet").filter(pl.col("peak_stable"))
    cnt = {h: 0 for h in H_LABELS}
    for r in o.iter_rows(named=True):
        cnt[r["h_star"]] = cnt.get(r["h_star"], 0) + 1
    fig, ax = plt.subplots(figsize=(9, 3.8))
    bars = ax.bar(range(len(H_LABELS)), [cnt[h] for h in H_LABELS], color="teal")
    bars[-1].set_color("#c0392b")  # 168h flagged
    ax.set_xticks(range(len(H_LABELS))); ax.set_xticklabels(H_LABELS)
    ax.set_xlabel("optimal exit horizon (h_star)"); ax.set_ylabel("# stable candidates")
    ax.set_title("Where stable candidates' optimal exit lands (IN-SAMPLE candidate set)")
    ax.annotate("168h = LADDER CEILING:\nthe curve never reversed inside our\nwindow — this pile-up is largely\nright-censoring, not a found exit",
                xy=(len(H_LABELS) - 1, cnt["168h"]), xytext=(len(H_LABELS) - 5.5, cnt["168h"] * 0.75),
                fontsize=8, color="#c0392b", ha="left",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=1))
    return _save(fig, "11_hstar_dist")


def fig_stable_counts():
    o = _load("optimal_exit.parquet")
    g = (o.group_by("coin").agg(scored=pl.len(),
                                held=(pl.col("peak_net_bps").is_not_null()).sum(),
                                stable=pl.col("peak_stable").sum())
         .filter(pl.col("coin").is_in(MAJORS)).sort("scored", descending=True))
    fig, ax = plt.subplots(figsize=(8, 3.8))
    x = np.arange(g.height); w = 0.27
    ax.bar(x - w, g["scored"], w, label="scored", color="#cccccc")
    ax.bar(x, g["held"], w, label="held-out eval", color="#7fb2d6")
    ax.bar(x + w, g["stable"], w, label="peak_stable", color="#d64550")
    ax.set_xticks(x); ax.set_xticklabels(g["coin"]); ax.set_yscale("log")
    ax.set_ylabel("wallets (log)"); ax.legend()
    ax.set_title("Candidate funnel per market (scored -> held-out -> stable)")
    return _save(fig, "12_stable_counts")


def fig_peak_vs_lo():
    o = _load("optimal_exit.parquet").filter(pl.col("peak_net_bps").is_not_null()
                                             & pl.col("peak_net_lo").is_not_null())
    x = o["peak_net_bps"].to_numpy(); y = o["peak_net_lo"].to_numpy()
    stab = o["peak_stable"].to_numpy()
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(x[~stab], y[~stab], s=5, alpha=0.15, color="gray", label="not stable")
    ax.scatter(x[stab], y[stab], s=6, alpha=0.35, color="crimson", label="peak_stable")
    ax.axhline(0, color="k", lw=0.8, ls="--", label="lo=0 gate")
    lim = np.nanpercentile(x, 99)
    ax.set_xlim(-lim, lim); ax.set_ylim(np.nanpercentile(y, 1), lim)
    ax.set_xlabel("held-out peak net (bps)"); ax.set_ylabel("block-bootstrap lower CI (bps)")
    ax.set_title("The stability gate: candidacy requires lower CI > 0")
    ax.legend()
    return _save(fig, "13_peak_vs_lo")


def fig_winnerscurse():
    w = _load("eda_winnerscurse.parquet")
    x = w["train_peak_bps"].to_numpy(); y = w["heldout_bps"].to_numpy()
    m = np.isfinite(x) & np.isfinite(y)
    xq = np.nanpercentile(x[m], [1, 99]); yq = np.nanpercentile(y[m], [1, 99])
    fig, ax = plt.subplots(figsize=(6, 5.4))
    ax.scatter(x[m], y[m], s=5, alpha=0.12, color="purple")
    lim = [min(xq[0], yq[0]), max(xq[1], yq[1])]
    ax.plot(lim, lim, "k--", lw=0.8, label="y=x (no regression)")
    ax.axhline(0, color="k", lw=0.5)
    # binned mean to show regression to the mean
    bins = np.linspace(xq[0], xq[1], 12); idx = np.digitize(x[m], bins)
    bx = [x[m][idx == i].mean() for i in range(1, len(bins)) if (idx == i).sum() >= 50]
    by = [y[m][idx == i].mean() for i in range(1, len(bins)) if (idx == i).sum() >= 50]
    ax.plot(bx, by, "-o", color="orange", lw=2, label="binned mean (bins n>=50)")
    ax.set_xlim(xq[0], xq[1]); ax.set_ylim(yq[0], yq[1])
    ax.set_xlabel("train-half peak (in-sample, bps)"); ax.set_ylabel("held-out value at same horizon (bps)")
    ax.set_title("Winner's curse: in-sample peak vs held-out (regression to the mean)")
    ax.legend()
    return _save(fig, "14_winnerscurse")


def fig_example_candidates(n=6):
    """Full markout term structures for a sample of stable candidates (one panel each)."""
    o = _load("optimal_exit.parquet").filter(pl.col("peak_stable")).sort("peak_net_bps", descending=True)
    s = _load("markout_stats.parquet")
    picks = o.head(n)
    fig, axes = plt.subplots(2, 3, figsize=(14, 6.5))
    for k, r in enumerate(picks.iter_rows(named=True)):
        ax = axes[k // 3][k % 3]
        cell = s.filter((pl.col("wallet") == r["wallet"]) & (pl.col("coin") == r["coin"]))
        rows = sorted([(HIDX[x["horizon"]], x["vw_edge_bps"], x["net_exec_bps"])
                       for x in cell.iter_rows(named=True) if x["horizon"] in HIDX and x["vw_edge_bps"] is not None])
        if not rows:
            continue
        xs = [a for a, _, _ in rows]
        ax.plot(xs, [b for _, b, _ in rows], "-o", ms=3, color="steelblue", label="vw edge (per-horizon)")
        ax.plot(xs, [c for _, _, c in rows], "-o", ms=3, color="crimson", label="net of cost")
        ax.axhline(0, color="k", lw=0.6)
        ax.axvline(HIDX[r["h_star"]], color="green", ls="--", lw=1, alpha=0.6, label="train-half h*")
        ax.set_xticks(range(0, len(H_LABELS), 3)); ax.set_xticklabels(H_LABELS[::3], fontsize=7)
        ax.set_title(f"{r['coin']} {r['wallet'][:8]}… h*={r['h_star']} n={r['n']}", fontsize=9)
        if k == 0:
            ax.legend(fontsize=7)
    fig.suptitle("TOP-6 candidates by IN-SAMPLE peak — best case, cherry-picked, NOT typical. "
                 "Most peak at 168h (ladder ceiling = still climbing, not a found exit). See winner's-curse (fig 14).",
                 y=1.04, fontsize=9)
    return _save(fig, "15_example_candidates")


def fig_activity_decile():
    s = _load("markout_stats.parquet").filter((pl.col("coin") == "BTC") & (pl.col("horizon") == "24h"))
    n = s["n"].to_numpy(); v = s["vw_edge_bps"].to_numpy()
    m = np.isfinite(v)
    n, v = n[m], v[m]
    dec = np.clip((np.argsort(np.argsort(n)) * 10 // len(n)), 0, 9)
    means = [np.mean(v[dec == d]) for d in range(10)]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.bar(range(10), means, color="slateblue")
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xlabel("activity decile (0=least active BTC wallets, 9=most)")
    ax.set_ylabel("mean deployable edge @24h (bps)")
    ax.set_title("BTC 24h deployable edge by wallet-activity decile")
    return _save(fig, "16_activity_decile")


ALL = [fig_scope, fig_coverage, fig_term_structure, fig_term_structure_zoom, fig_winsor_effect,
       fig_downside_term, fig_long_short, fig_edge_dist, fig_size_blind_vs_deployable,
       fig_n_vs_edge, fig_hstar_dist, fig_stable_counts, fig_peak_vs_lo, fig_winnerscurse,
       fig_example_candidates, fig_activity_decile]


if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    for f in ALL:
        try:
            f(); print(f"OK  {f.__name__}", flush=True)
        except Exception as e:
            print(f"ERR {f.__name__}: {e}", flush=True)
