"""<STUDY NAME> — analysis entry point.

Starter skeleton. Draws on the shared data source (`research.data`) and the shared rigor toolkit
(`research.lib`). Nothing else. Run from the repo root:

    python -m research.studies.<name>.run
"""
from __future__ import annotations
from pathlib import Path

from research.data.db import connect
from research.lib import stats, power, cv, cost, backtest

OUT = Path(__file__).parent / "out"
SEED = 20260707  # study-local exploratory seed (NOT the frozen Gate-A seed)


def build_signal(con):
    """Construct the per-unit signal + outcome from the tape. Return a table you can slice by month."""
    # Example shape — replace with the real query. Money fields are exact strings → TRY_CAST to DECIMAL.
    # asset_ctx joins must be AS-OF (ctx.ts <= fill.ts), never an equi-join.
    raise NotImplementedError("build the signal query")


def evaluate():
    con = connect()
    _ = build_signal(con)

    # Walk-forward, OOS only — never report an in-sample number.
    for split in cv.walkforward_splits(mode="expanding"):
        # fit/rank on split.train, evaluate on split.test ...
        pass

    # Portfolio simulation of the OOS targets (gross + net, funding-aware):
    #   bar_ts, coins, price = backtest.pivot_panel(rows_ts, rows_coin, rows_oracle_px)
    #   _,      _,     tgt   = backtest.pivot_panel(rows_ts, rows_coin, rows_target_notional)
    #   res = backtest.simulate(bar_ts, coins, price, tgt, funding=fund, cost=cost.DEFAULT)
    #   print(res.summary())   # equity, log-growth + mean-ret CI, drawdown, turnover, cost/funding drag

    # The over-null gate — produce ALL FOUR before any null verdict:
    #   unit_stats = per-unit (wallet/coin/week) OOS means
    #   ci   = stats.cluster_bootstrap_ci(cluster_id, values, seed=SEED)
    #   pw   = power.power_check(values, care_about=<bps you'd deploy on>)
    #   sgn  = stats.sign_test(unit_stats)
    #   net  = cost.DEFAULT.net_edge_bp(gross_edge_bp)   # label NET explicitly
    #   rej, q = stats.bh_fdr(pvals)                      # multiplicity across the arc
    OUT.mkdir(exist_ok=True)


if __name__ == "__main__":
    evaluate()
