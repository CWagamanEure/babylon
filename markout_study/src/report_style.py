"""Shared matplotlib style for the markout-analysis report figures. Consistent coin colors, bp formatting, clean look."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

COIN_COLORS = {"BTC": "#f7931a", "ETH": "#627eea", "SOL": "#14f195", "HYPE": "#e6007a", "ALL": "#333333"}
GROUP_COLORS = {"RECURRING": "#d62728", "ORDINARY": "#7f7f7f", "CONTROL": "#c7c7c7",
                "cohort": "#d62728", "field": "#7f7f7f"}
FIGDIR = "figs"

def setup():
    plt.rcParams.update({
        "figure.dpi": 130, "savefig.dpi": 130, "font.size": 10.5, "font.family": "DejaVu Sans",
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.alpha": 0.25, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "legend.frameon": False,
        "figure.constrained_layout.use": True})

def bp_axis(ax, which="y"):
    f = FuncFormatter(lambda v, _: f"{v:+.0f}")
    (ax.yaxis if which == "y" else ax.xaxis).set_major_formatter(f)

def save(fig, name):
    import os; os.makedirs(FIGDIR, exist_ok=True)
    p = f"{FIGDIR}/{name}.png"; fig.savefig(p, bbox_inches="tight"); plt.close(fig); return p
