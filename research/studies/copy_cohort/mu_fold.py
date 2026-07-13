"""Per-fold μ_h(coin, ISO-week, ≤cutoff) — the leakage-safe baseline aggregation (ARCH §1, audit D3/W1).

Aggregates the built per-minute primitive `data/derived/fwd_returns/` (mu_baseline.py) into a
(coin, iso_week) → μ_h table with the `(t + h) ≤ cutoff` censor applied PER HORIZON — this is the
R2/R10 rule that keeps the baseline computable-at-cutoff and correctly truncates the straddle week.

⚠️ `data/derived/addr_coin_markout/` is FORBIDDEN as a μ source here: its censor is pinned to one
global cutoff (features_markout.CUTOFF_TS), which leaks for any earlier fold cutoff.

Also emits `mu_lag_5m_<h>`: the baseline for the follower-lag estimand — the per-minute return from
t+5m to t+h, `((1+fwd_ret_h/1e4)/(1+fwd_ret_5m/1e4) − 1)·1e4`, censored at (t + h) ≤ cutoff.
"""
from __future__ import annotations

from research.data.markout import HORIZONS, REPO_ROOT

FWD_GLOB = str(REPO_ROOT / "data" / "derived" / "fwd_returns" / "coin=*/part.parquet")
LAG_BASE = "5m"


def register_mu(con, cutoff_ms: int, horizons: tuple[str, ...] = ("1h", "2h", "4h", "8h"),
                start_ms: int | None = None, table: str = "mu") -> None:
    """CREATE OR REPLACE TEMP TABLE `table`(coin, iso_week, mu_<h>…, mu_lag_5m_<h>…, n_min_<h>…).

    Censors: minute t contributes to μ_h iff fwd_ret_h is non-NULL (staleness/tape-end, baked into
    the primitive) AND t + h_ms ≤ cutoff_ms (the per-fold leakage censor). `start_ms` optionally
    bounds the window on the left (e.g. the burn-in start); default = whole tape before cutoff.
    """
    unknown = [h for h in horizons if h not in HORIZONS]
    if unknown:
        raise ValueError(f"unknown horizons {unknown}; must be in {list(HORIZONS)}")
    lo = f"AND ts >= {start_ms}" if start_ms is not None else ""
    cols = []
    for h in horizons:
        ms = HORIZONS[h]
        cens = f"WHERE ts + {ms} <= {cutoff_ms}"
        cols.append(f"avg(fwd_ret_{h}) FILTER ({cens}) AS mu_{h}")
        cols.append(f"count(fwd_ret_{h}) FILTER ({cens}) AS n_min_{h}")
        if h != LAG_BASE:
            lag = (f"((1.0 + fwd_ret_{h}/1e4) / (1.0 + fwd_ret_{LAG_BASE}/1e4) - 1.0) * 1e4")
            cols.append(f"avg({lag}) FILTER ({cens} AND fwd_ret_{LAG_BASE} IS NOT NULL) "
                        f"AS mu_lag_{LAG_BASE}_{h}")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {table} AS
      SELECT coin, iso_week, {', '.join(cols)}
      FROM read_parquet('{FWD_GLOB}', hive_partitioning=true)
      WHERE ts < {cutoff_ms} {lo}
      GROUP BY coin, iso_week""")
