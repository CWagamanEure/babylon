"""Figures for hyperliquid_trader_composition.ipynb (report v2).
Sections generate independently; each function writes report_figs2/<name>.png.
Style: simple titles, dollar-labeled log axes where applicable, no jargon in titles."""
from pathlib import Path

import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "notebooks" / "report_figs2"
OUT.mkdir(exist_ok=True)
ML = ROOT / "scratch_conv" / "mlscreen"
plt.rcParams.update({"figure.dpi": 120, "axes.grid": True, "grid.alpha": 0.25,
                     "axes.spines.top": False, "axes.spines.right": False})

ARCHETYPES = {3: "Majors swing traders", 2: "Fast intraday traders", 1: "Alt position traders",
              4: "Big majors semi-pros", 0: "Maker-hybrids", 6: "Multi-coin spray", 5: "Mega-whales"}


def fig_taxonomy():
    F = pl.read_parquet(ML / "field_taxonomy.parquet")
    prof = (F.group_by("cl").agg(k=pl.len(), hold=pl.col("med_h").median(),
                                 maker=pl.col("maker").median(), majors=pl.col("majors").median(),
                                 size=pl.col("mean_notional").median())
            .sort("k", descending=True))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    names = [ARCHETYPES.get(c, f"cluster {c}") for c in prof["cl"]]
    y = np.arange(len(names))[::-1]
    ax.barh(y, prof["k"], color="#4878a8")
    for yi, (k, h, mk, mj, sz) in zip(y, prof.select(["k", "hold", "maker", "majors", "size"]).iter_rows()):
        ax.text(k + 150, yi, f"{k:,} wallets · {h:.0f}h holds · {mk:.0%} maker · "
                             f"{mj:.0%} majors · ${sz:,.0f} orders", va="center", fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=9)
    ax.set_xlim(0, prof["k"].max() * 2.1)
    ax.set_xlabel("wallets")
    ax.set_title("Behavioral archetypes of eligible wallets (k-means, field-wide)")
    fig.tight_layout(); fig.savefig(OUT / "01_taxonomy.png"); plt.close(fig)


def fig_maker_hold():
    F = pl.read_parquet(ML / "field_taxonomy.parquet")
    H = pl.read_parquet(ML / "holds.parquet")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    ax = axes[0]
    ax.hist(np.clip(F["maker"].to_numpy(), 0, 1), bins=50, color="#4878a8")
    ax.set_yscale("log")
    ax.set_yticks([1, 10, 100, 1000, 10000])
    ax.set_yticklabels(["1", "10", "100", "1k", "10k"])
    ax.set_xlabel("share of fills as maker"); ax.set_ylabel("wallets")
    ax.set_title("Maker share of fills")
    ax = axes[1]
    m = H["med_h"].to_numpy()
    ax.hist(np.log10(np.clip(m, 0.02, 2000)), bins=60, color="#4878a8")
    ticks = [0.1, 1, 4, 12, 24, 72, 168, 720]
    ax.set_xticks([np.log10(t) for t in ticks])
    ax.set_xticklabels(["6m", "1h", "4h", "12h", "1d", "3d", "1w", "1mo"])
    ax.set_xlabel("median position hold"); ax.set_ylabel("wallets")
    ax.set_title("Median position hold time")
    fig.tight_layout(); fig.savefig(OUT / "02_maker_hold.png"); plt.close(fig)


def fig_field_markout():
    rows = [json.loads(l) for l in open(ML / "markout2m.jsonl")]
    i24 = [1, 2, 4, 8, 12, 24, 48, 72, 168].index(24)
    v = []
    for r in rows:
        n = sum(r["m_n"][i][i24] for i in range(11))
        if n >= 30:
            v.append(sum(r["m_bps"][i][i24] for i in range(11)) / n)
    v = np.array(v)
    fig, ax = plt.subplots(figsize=(8.5, 4))
    ax.hist(np.clip(v, -300, 300), bins=120, color="#4878a8")
    ax.axvline(0, color="k", lw=0.8)
    ax.axvline(np.mean(v), color="#c0392b", lw=1.6,
               label=f"average wallet: {np.mean(v):+.0f}bp per entry")
    ax.axvline(np.median(v), color="#e67e22", lw=1.2, ls="--",
               label=f"median wallet: {np.median(v):+.0f}bp")
    ax.legend()
    ax.set_xlabel("average 24h markout per entry (bps)")
    ax.set_ylabel("wallets")
    ax.set_title(f"Per-wallet mean 24h markout ({v.size:,} wallets)")
    fig.tight_layout(); fig.savefig(OUT / "03_field_markout.png"); plt.close(fig)


def fig_horizon_rankcorr():
    rows = [json.loads(l) for l in open(ML / "markout2.jsonl")]
    H = [1, 2, 4, 8, 12, 24, 48, 72, 168]
    pnl = {h: [] for h in H}
    ws = []
    for r in rows:
        if r["train_n"][5] < 30: continue
        ws.append(r["w"])
        for hi, h in enumerate(H):
            pnl[h].append(r["train_pnl"][hi])
    M = np.zeros((9, 9))
    from scipy_free_rank import spearman  # placeholder replaced below
    fig = None


def _spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b))
    ra = (ra - ra.mean()) / ra.std(); rb = (rb - rb.mean()) / rb.std()
    return float((ra * rb).mean())


def fig_horizon_rankcorr2():
    rows = [json.loads(l) for l in open(ML / "markout2.jsonl")]
    H = [1, 2, 4, 8, 12, 24, 48, 72, 168]
    cols = []
    for hi in range(9):
        cols.append(np.array([r["train_pnl"][hi] for r in rows if r["train_n"][5] >= 30]))
    M = np.zeros((9, 9))
    for i in range(9):
        for j in range(9):
            M[i, j] = _spearman(cols[i], cols[j])
    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    im = ax.imshow(M, vmin=0, vmax=1, cmap="viridis")
    ax.set_xticks(range(9)); ax.set_xticklabels([f"{h}h" for h in H])
    ax.set_yticks(range(9)); ax.set_yticklabels([f"{h}h" for h in H])
    for i in range(9):
        for j in range(9):
            ax.text(j, i, f"{M[i,j]:.2f}", ha="center", va="center",
                    color="w" if M[i, j] < 0.6 else "k", fontsize=7)
    ax.set_title("Rank correlation of wallet markout PnL between horizons")
    fig.colorbar(im, shrink=0.8)
    fig.tight_layout(); fig.savefig(OUT / "04_horizon_rankcorr.png"); plt.close(fig)


def fig_winners_curse():
    rows = [json.loads(l) for l in open(ML / "markout2m.jsonl")]
    i24 = [1, 2, 4, 8, 12, 24, 48, 72, 168].index(24)
    a, b = [], []
    for r in rows:
        n1 = sum(r["m_n"][i][i24] for i in range(0, 5))
        n2 = sum(r["m_n"][i][i24] for i in range(5, 11))
        if n1 >= 20 and n2 >= 20:
            a.append(sum(r["m_pnl"][i][i24] for i in range(0, 5)))
            b.append(sum(r["m_pnl"][i][i24] for i in range(5, 11)))
    a, b = np.array(a), np.array(b)
    fig, ax = plt.subplots(figsize=(6.6, 5.4))
    ax.scatter(np.sign(a) * np.log10(1 + np.abs(a)), np.sign(b) * np.log10(1 + np.abs(b)),
               s=4, alpha=0.25, color="#4878a8")
    top = np.argsort(-a)[:50]
    ax.scatter(np.sign(a[top]) * np.log10(1 + np.abs(a[top])),
               np.sign(b[top]) * np.log10(1 + np.abs(b[top])),
               s=18, color="#c0392b", label="top-50 in first half")
    ticks = [-1e6, -1e4, -100, 0, 100, 1e4, 1e6]
    tv = [np.sign(t) * np.log10(1 + abs(t)) for t in ticks]
    ax.set_xticks(tv); ax.set_xticklabels(["-$1M", "-$10k", "-$100", "0", "$100", "$10k", "$1M"])
    ax.set_yticks(tv); ax.set_yticklabels(["-$1M", "-$10k", "-$100", "0", "$100", "$10k", "$1M"])
    ax.axhline(0, color="k", lw=0.6); ax.axvline(0, color="k", lw=0.6)
    ax.set_xlabel("markout PnL, first 5 months")
    ax.set_ylabel("markout PnL, next 6 months")
    ax.legend()
    ax.set_title("Markout PnL: first 5 months vs following 6 months")
    fig.tight_layout(); fig.savefig(OUT / "05_winners_curse.png"); plt.close(fig)


def fig_flipnull():
    d = np.load(ROOT / "notebooks" / "report_figs2_data_flipnull.npz")
    obs, null = d["obs"], d["null"]
    fig, ax = plt.subplots(figsize=(8.8, 4.2))
    bins = np.linspace(-8, 8, 160)
    ax.hist(null, bins=bins, density=True, alpha=0.55, color="#95a5a6",
            label="luck (direction-scrambled null)")
    ax.hist(obs, bins=bins, density=True, alpha=0.55, color="#4878a8",
            label="observed wallets")
    ax.axvline(4, color="#c0392b", lw=1.2, ls="--")
    n_o = int((obs > 4).sum()); n_e = float((null > 4).mean() * obs.size)
    ax.text(4.15, ax.get_ylim()[1] * 0.55,
            f"t > 4:\n{n_o} observed\n{n_e:.0f} expected by luck", fontsize=9, color="#c0392b")
    ax.set_yscale("log")
    ax.set_yticks([1e-5, 1e-4, 1e-3, 1e-2, 1e-1])
    ax.set_yticklabels(["1 in 100k", "1 in 10k", "1 in 1k", "1 in 100", "1 in 10"])
    ax.set_xlabel("wallet skill score (t-statistic)")
    ax.set_ylabel("share of wallets")
    ax.legend()
    ax.set_title("Wallet t-statistics: observed vs direction-scrambled null")
    fig.tight_layout(); fig.savefig(OUT / "06_flipnull.png"); plt.close(fig)


def fig_term_structure():
    d = json.load(open(ML / "coin_term_structure.json"))
    H = d["horizons"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    colors = {"BTC": "#f2a900", "ETH": "#627eea", "SOL": "#9945ff", "HYPE": "#2ecc71",
              "SPX": "#c0392b", "ALT": "#7f8c8d"}
    for g, col in colors.items():
        y = []
        for hi in range(len(H)):
            cell = d["cells"].get(f"{g}|{hi}")
            y.append(cell[0] / cell[1] if cell and cell[1] > 0 else np.nan)
        ax.plot(range(len(H)), y, marker="o", ms=4, color=col, label=g)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(len(H))); ax.set_xticklabels([f"{h}h" for h in H])
    ax.set_xlabel("horizon after entry")
    ax.set_ylabel("mean markout (bps)")
    ax.legend(ncol=6, fontsize=8)
    ax.set_title("Mean markout by horizon and market")
    fig.tight_layout(); fig.savefig(OUT / "07_term_structure.png"); plt.close(fig)


def fig_verdict_folds():
    V = json.load(open(ROOT / "notebooks" / "report2_verified_stats.json"))
    wf = V["walkforward_folds"]     # from walkforward.manifest.json (the registered artifact)
    folds = [{"202602": "Feb", "202603": "Mar", "202604": "Apr",
              "202605": "May", "202606": "Jun"}[f[0]] for f in wf]
    bps = [f[1] for f in wf]
    z = [f[3] for f in wf]
    fig, ax = plt.subplots(figsize=(7.6, 4))
    cols = ["#4878a8" if x >= 0 else "#c0392b" for x in bps]
    ax.bar(folds, bps, color=cols)
    for i, (b, zz) in enumerate(zip(bps, z)):
        ax.text(i, b + (5 if b >= 0 else -13), f"z={zz:+.2f}", ha="center", fontsize=8)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("roster markout next month (bps/entry)")
    ax.set_title("Walk-forward: roster next-month markout by fold")
    fig.tight_layout(); fig.savefig(OUT / "08_verdict_folds.png"); plt.close(fig)


def fig_maker_bands():
    V = json.load(open(ROOT / "notebooks" / "report2_verified_stats.json"))
    bands = V["maker_band_labels"]
    diffs = V["maker_bands"]        # recomputed from winbreadth.jsonl, decile-matched
    fig, ax = plt.subplots(figsize=(7.6, 4))
    ax.bar(bands, diffs, color="#4878a8")
    ax.set_xlabel("share of the wallet's fills that are maker")
    ax.set_ylabel("next-month transfer vs matched takers (bps)")
    ax.set_title("Next-month transfer vs matched controls, by maker share band")
    fig.tight_layout(); fig.savefig(OUT / "09_maker_bands.png"); plt.close(fig)


def fig_venue_matrix():
    V = json.load(open(ROOT / "notebooks" / "report2_verified_stats.json"))
    m = V["venue_matrix"]           # all cells from the CORRECTED venue_split (R6 fixes)
    M = np.array([[m["mj_mj"], m["mj_al"]], [m["al_mj"], m["al_al"]]])
    fig, ax = plt.subplots(figsize=(5.4, 4.4))
    im = ax.imshow(M, cmap="viridis", vmin=0, vmax=1.3)
    ax.set_xticks([0, 1]); ax.set_xticklabels(["score on majors", "score on alts"])
    ax.set_yticks([0, 1]); ax.set_yticklabels(["rank on majors", "rank on alts"])
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"z = {M[i,j]:+.2f}", ha="center", va="center",
                    color="w" if M[i, j] < 0.7 else "k")
    ax.set_title("Selection transfer (pooled z) by ranking venue and scoring venue")
    fig.tight_layout(); fig.savefig(OUT / "10_venue_matrix.png"); plt.close(fig)



MONTH_LABELS = ["Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]


def _monthly_cohort_series():
    rows = [json.loads(l) for l in open(ML / "markout2m.jsonl")]
    i24 = [1, 2, 4, 8, 12, 24, 48, 72, 168].index(24)
    F = pl.read_parquet(ML / "field_taxonomy.parquet")
    makers = set(F.filter(pl.col("maker") >= 0.5)["w"].to_list())
    basket = set(x["w"] for x in json.load(open(ROOT / "scratch_conv" / "badge_v2_basket.json"))["basket"])
    full = {r["w"]: r for r in rows}
    pnl24 = sorted(((sum(r["m_pnl"][i][i24] for i in range(11)), r["w"]) for r in rows
                    if sum(r["m_n"][i][i24] for i in range(11)) >= 30), reverse=True)
    top50 = set(w for _, w in pnl24[:50])
    def series(sel):
        out = []
        for mi in range(11):
            v = [r["m_bps"][mi][i24]/r["m_n"][mi][i24] for r in rows
                 if (sel is None or r["w"] in sel) and r["m_n"][mi][i24] >= 5]
            out.append(np.mean(v) if len(v) >= 5 else np.nan)
        return out
    return {"all eligible wallets": series(None), "top-50 by full-period markout PnL": series(top50),
            "t>4 certified basket (57)": series(basket), "maker-heavy wallets (>=50%)": series(makers)}


def fig_cohort_series():
    S = _monthly_cohort_series()
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    colors = {"all eligible wallets": "#7f8c8d", "top-50 by full-period markout PnL": "#c0392b",
              "t>4 certified basket (57)": "#4878a8", "maker-heavy wallets (>=50%)": "#2ecc71"}
    for k, v in S.items():
        ax.plot(range(11), v, marker="o", ms=4, label=k, color=colors[k])
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(11)); ax.set_xticklabels(MONTH_LABELS)
    ax.set_ylabel("mean 24h markout (bps per entry)")
    ax.set_title("Monthly mean 24h markout by cohort")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "11_cohort_series.png"); plt.close(fig)


def fig_cohort_cumpnl():
    rows = [json.loads(l) for l in open(ML / "markout2m.jsonl")]
    i24 = [1, 2, 4, 8, 12, 24, 48, 72, 168].index(24)
    basket = set(x["w"] for x in json.load(open(ROOT / "scratch_conv" / "badge_v2_basket.json"))["basket"])
    pnl24 = sorted(((sum(r["m_pnl"][i][i24] for i in range(11)), r["w"]) for r in rows
                    if sum(r["m_n"][i][i24] for i in range(11)) >= 30), reverse=True)
    top50 = set(w for _, w in pnl24[:50])
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    for label, sel, col in [("top-50 by full-period markout PnL", top50, "#c0392b"),
                            ("t>4 certified basket (57)", basket, "#4878a8"),
                            ("all eligible wallets", None, "#7f8c8d")]:
        m = []
        for mi in range(11):
            v = [r["m_bps"][mi][i24]/r["m_n"][mi][i24] for r in rows
                 if (sel is None or r["w"] in sel) and r["m_n"][mi][i24] >= 5]
            m.append(np.mean(v) if len(v) >= 5 else 0.0)
        ax.plot(range(11), np.cumsum(m), marker="o", ms=4, label=label, color=col)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(11)); ax.set_xticklabels(MONTH_LABELS)
    ax.set_ylabel("cumulative average markout (bps per entry)")
    ax.set_title("Cumulative per-entry markout by cohort")
    ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(OUT / "12_cohort_cumpnl.png"); plt.close(fig)


def fig_entity_network():
    """Ordered similarity heatmap of the 57 certified wallets (the SHIPPED figure).
    Reads the saved measured similarity matrix; ordering = entity groups then singletons."""
    d = np.load(ROOT / "notebooks" / "report_figs2_data_simmatrix.npz", allow_pickle=True)
    S, grp = d["S"], d["grp"]
    n = S.shape[0]
    fig, ax = plt.subplots(figsize=(8.6, 7.4))
    im = ax.imshow(S, cmap="inferno", vmin=0, vmax=1)
    cur = grp[0]; start_ = 0
    for i in range(1, n+1):
        if i == n or grp[i] != cur:
            if cur != -1 and i - start_ > 1:
                ax.add_patch(plt.Rectangle((start_-0.5, start_-0.5), i-start_, i-start_,
                                           fill=False, ec="#2ecc71", lw=1.6))
            cur = grp[i] if i < n else -2; start_ = i
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlabel("57 certified wallets (ordered: entity groups first, then singletons by t)")
    ax.set_title("Pairwise similarity of the certified wallets\n"
                 "(max of trade co-timing, daily PnL correlation, exposure overlap)")
    fig.colorbar(im, shrink=0.8, label="similarity")
    fig.tight_layout(); fig.savefig(OUT / "13_entity_network.png"); plt.close(fig)


def fig_style_map():
    """Style map (fade vs momentum x long share): field density + certified basket overlay."""
    S = pl.read_parquet(ML / "style_features.parquet")
    mom = S["mom"].to_numpy(); lng = S["long"].to_numpy()
    basket = set(x["w"] for x in json.load(open(ROOT / "scratch_conv" / "badge_v2_basket.json"))["basket"])
    bmask = np.array([w in basket for w in S["w"].to_list()])
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    ax = axes[0]
    h = ax.hist2d(mom, lng, bins=60, range=[[0.1, 0.9], [0, 1]], cmap="Blues", cmin=1)
    ax.axvline(0.5, color="k", lw=0.7, ls="--"); ax.axhline(0.5, color="k", lw=0.7, ls="--")
    ax.set_xlabel("share of entries WITH the prior 4h move  (left: fades  ·  right: momentum)")
    ax.set_ylabel("share of entries that are longs")
    ax.set_title("Style map of the eligible field (density)")
    fig.colorbar(h[3], ax=ax, shrink=0.8, label="wallets")
    ax = axes[1]
    ax.scatter(mom, lng, s=3, alpha=0.1, color="#aab4bd")
    ax.scatter(mom[bmask], lng[bmask], s=48, color="#4878a8", edgecolors="k", linewidths=0.4,
               label="t>4 certified basket")
    ax.axvline(0.5, color="k", lw=0.7, ls="--"); ax.axhline(0.5, color="k", lw=0.7, ls="--")
    ax.set_xlim(0.1, 0.9); ax.set_ylim(0, 1)
    ax.set_xlabel("share of entries WITH the prior 4h move")
    ax.set_ylabel("share of entries that are longs")
    ax.legend(fontsize=8)
    ax.set_title("Certified basket on the style map")
    fig.tight_layout(); fig.savefig(OUT / "18_style_map.png"); plt.close(fig)


def fig_hitrate_cohorts():
    basket = set(x["w"] for x in json.load(open(ROOT / "scratch_conv" / "badge_v2_basket.json"))["basket"])
    hr_b, hr_f = [], []
    for line in open(ML / "badge_v2.jsonl"):
        r = json.loads(line)
        cl = np.array(r["cl"], dtype=float)
        if cl.shape[0] < 50: continue
        hr = float((cl[:, 2] > 0).mean())
        (hr_b if r["w"] in basket else hr_f).append(hr)
    fig, ax = plt.subplots(figsize=(8.5, 4))
    bins = np.linspace(0.2, 0.8, 60)
    ax.hist(hr_f, bins=bins, density=True, alpha=0.55, color="#7f8c8d", label="all eligible wallets")
    ax.hist(hr_b, bins=bins, density=True, alpha=0.65, color="#4878a8", label="t>4 certified basket")
    ax.axvline(0.5, color="k", lw=0.8)
    ax.set_xlabel("share of positions with positive raw 24h markout (hit rate)")
    ax.set_ylabel("density")
    ax.legend()
    ax.set_title("Position-level hit rate: certified basket vs field")
    fig.tight_layout(); fig.savefig(OUT / "14_hitrate.png"); plt.close(fig)



def fig_trader_map():
    """Behavioral map: PCA of the SAME 9 standardized features the archetype clustering used.
    Axis meaning from loadings: PC1 = trading speed (fast/scalpy right, slow/patient left);
    PC2 = scale & breadth (busy, many-coin, larger books up). Three variants."""
    d = np.load(ROOT / "notebooks" / "report_figs2_data_pca.npz", allow_pickle=True)
    XY, W, cl = d["xy"], [str(w) for w in d["w"]], d["cl"]
    rows = [json.loads(l) for l in open(ML / "markout2m.jsonl")]
    i24 = [1, 2, 4, 8, 12, 24, 48, 72, 168].index(24)
    pnl24 = sorted(((sum(r["m_pnl"][i][i24] for i in range(11)), r["w"]) for r in rows
                    if sum(r["m_n"][i][i24] for i in range(11)) >= 30), reverse=True)
    top50 = set(w for _, w in pnl24[:50])
    basket = set(x["w"] for x in json.load(open(ROOT / "scratch_conv" / "badge_v2_basket.json"))["basket"])
    palette = {3: "#4878a8", 2: "#e67e22", 1: "#8e44ad", 4: "#2c3e50",
               0: "#2ecc71", 6: "#c0392b", 5: "#f1c40f"}
    cols = np.array([palette.get(c, "#7f8c8d") for c in cl])
    rng = np.random.default_rng(5)
    sub = rng.random(len(W)) < 0.35
    x, y = XY[:, 0], XY[:, 1]
    xl = (np.percentile(x, 0.3), np.percentile(x, 99.7))
    yl = (np.percentile(y, 0.3), np.percentile(y, 99.7))

    def base(ax, grey=False):
        if grey:
            ax.scatter(x[sub], y[sub], s=3, alpha=0.12, color="#aab4bd", zorder=1)
        else:
            ax.scatter(x[sub], y[sub], s=3, alpha=0.3, c=cols[sub], zorder=1)
        ax.set_xlim(*xl); ax.set_ylim(*yl)
        ax.set_xlabel("component 1  (left: patient, multi-day holds — right: fast, sub-hour trading)")
        ax.set_ylabel("component 2  (up: busier, more\ncoins, bigger books)")
        ax.set_xticks([]); ax.set_yticks([])

    idx = {w: i for i, w in enumerate(W)}
    fig, ax = plt.subplots(figsize=(8.8, 5.6))
    base(ax)
    for c, name in ARCHETYPES.items():
        ax.scatter([], [], s=22, color=palette.get(c, "#7f8c8d"), label=name)
    ax.legend(fontsize=7.5, loc="upper left", framealpha=0.9)
    ax.set_title("Behavioral map of the eligible field (PCA of 9 behavior features)")
    fig.tight_layout(); fig.savefig(OUT / "15_map_field.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 5.6))
    base(ax, grey=True)
    sel = [idx[w] for w in top50 if w in idx]
    ax.scatter(x[sel], y[sel], s=42, color="#c0392b", edgecolors="k", linewidths=0.4, zorder=3,
               label="top-50 by 24h markout PnL (all markets)")
    ax.legend(fontsize=8, loc="upper left")
    ax.set_title("Behavioral map: top-50 by markout PnL")
    fig.tight_layout(); fig.savefig(OUT / "16_map_top50.png"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 5.6))
    base(ax, grey=True)
    sel = [idx[w] for w in basket if w in idx]
    ax.scatter(x[sel], y[sel], s=42, color="#4878a8", edgecolors="k", linewidths=0.4, zorder=3,
               label="t>4 certified basket")
    ax.legend(fontsize=8, loc="upper left")
    ax.set_title("Behavioral map: certified basket")
    fig.tight_layout(); fig.savefig(OUT / "17_map_basket.png"); plt.close(fig)


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "ready"
    ready = [fig_taxonomy, fig_maker_hold, fig_field_markout, fig_horizon_rankcorr2,
             fig_winners_curse, fig_verdict_folds, fig_maker_bands, fig_venue_matrix,
             fig_cohort_series, fig_cohort_cumpnl, fig_entity_network, fig_hitrate_cohorts,
             fig_flipnull, fig_style_map]
    late = [fig_flipnull, fig_term_structure]
    fns = ready if which == "ready" else late if which == "late" else ready + late
    for f in fns:
        try:
            f(); print("ok", f.__name__)
        except Exception as e:
            print("SKIP", f.__name__, "->", e)
