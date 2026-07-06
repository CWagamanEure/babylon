"""Figures for Stage 1 cohort typology. Reads out/forensics_typology.parquet. Shows, per key descriptor,
the top-K cohort under BOTH vw and ew selection (point + bootstrap CI) vs the activity+notional-matched
control band + field — so a genuine trait (disjoint under BOTH) is visually distinct from a vw-selection
artifact (disjoint under vw only). Reliable-control coins only. Saved to out/figs_forensics/."""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
FIGS = OUT / "figs_forensics"; FIGS.mkdir(exist_ok=True)


def fig_typology(K=50):
    t = pl.read_parquet(OUT / "forensics_typology.parquet").filter(
        (pl.col("K") == K) & pl.col("control_reliable"))
    coins = sorted(t["coin"].unique().to_list())
    descs = [("highvol_frac", "High-vol-regime entry share\n(ROBUST: disjoint under BOTH selections)"),
             ("notl_cv", "Position-size dispersion (CV)\n(vw-only → VOLUME-SELECTION ARTIFACT)"),
             ("add_frac", "Adds-to-position fraction\n(consistent lean, stronger under ew)")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    x = np.arange(len(coins))
    for ax, (d, title) in zip(axes, descs):
        sub = t.filter(pl.col("descriptor") == d)
        vw = {r["coin"]: r for r in sub.filter(pl.col("selection") == "vw").iter_rows(named=True)}
        ew = {r["coin"]: r for r in sub.filter(pl.col("selection") == "ew").iter_rows(named=True)}
        # control band (from vw rows; matched band is selection-specific but near-identical, use vw for the shade)
        lo = [vw[c]["ctrl_lo"] for c in coins]; hi = [vw[c]["ctrl_hi"] for c in coins]
        for i, c in enumerate(coins):
            ax.add_patch(plt.Rectangle((i - 0.42, lo[i]), 0.84, hi[i] - lo[i], color="0.83", zorder=0))
        ax.plot(x, [vw[c]["field"] for c in coins], "_", ms=22, color="k", label="field", zorder=1)
        for sel, dx, col, mk in [("vw", -0.13, "#1f77b4", "o"), ("ew", 0.13, "#d62728", "s")]:
            src = vw if sel == "vw" else ew
            pt = np.array([src[c]["cohort"] for c in coins])
            lo_ = np.array([src[c]["cohort_ci_lo"] for c in coins]); hi_ = np.array([src[c]["cohort_ci_hi"] for c in coins])
            ax.errorbar(x + dx, pt, yerr=[pt - lo_, hi_ - pt], fmt=mk, color=col, ms=6, capsize=3,
                        label=f"{sel}-selected cohort ±CI", zorder=3)
            for i, c in enumerate(coins):
                if src[c]["ci_disjoint"]:
                    ax.scatter(x[i] + dx, hi_[i], marker="*", s=90, color="gold", edgecolor="k", zorder=4)
        ax.set_xticks(x); ax.set_xticklabels(coins); ax.set_title(title, fontsize=9.5)
        ax.grid(axis="y", alpha=0.25)
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle("Stage-1 typology (EXPLORATORY, top-50 vs activity+notional-matched control). ★ = cohort CI "
                 "disjoint from control band (fair test). A real trait clears under BOTH vw & ew selection; a "
                 "vw-only ★ is a volume-selection artifact.", y=1.02, fontsize=10)
    fig.tight_layout(); p = FIGS / f"01_typology_K{K}.png"; fig.savefig(p, dpi=110, bbox_inches="tight"); plt.close(fig)
    return str(p)


if __name__ == "__main__":
    print("OK ->", fig_typology())
