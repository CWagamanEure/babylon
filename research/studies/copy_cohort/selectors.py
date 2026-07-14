"""Per-fold eligibility panel + the two pre-registered selector arms (COPY_COHORT_ARCH §3–§4).

Everything here is computable-at-cutoff: Arm-A membership is the WINDOW censor
`entry_bar_ts + 4h < cutoff` (no close requirement — audit W1/W3); Arm-B membership additionally
requires `close_ts < cutoff` (realized PnL needs the close). μ is rebuilt per fold via
mu_fold.register_mu (censored at the fold cutoff); evaluation-side μ is censored at the NEXT
fold's cutoff.

Registered implementation choices (recorded here, echoed in the run report):
- The eligibility pool is defined on Arm-A-scoreable episodes (the primary membership); Arm B is
  scored on its own closed-episode population within pool wallets (a pool wallet with < 2 Arm-B
  clusters scores at the pool mean, per eb_shrink's single-cluster rule).
- F7's flagged share is computed over ALL the wallet's non-inherited formation episodes (any
  opener type) — flags must not be laundered by the taker filter.
- Arm-B bps = realized_pnl_usd / (initial + total added notional) · 1e4 on closed episodes,
  two-sided winsor at the formation (p01, p99), demeaned by (coin, ISO-week of close_ts) formation
  means; clustering for eb_shrink stays wallet × ISO-week(open_ts) (the Stage-0 anchor).
- Selector clustering = the Stage-0 frozen level: wallet_week (open_ts anchor).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from research.data.markout import _connect, HORIZONS, REPO_ROOT
from research.lib.cv import as_of_cutoff_ms
from research.lib.stats import eb_shrink
from . import mu_fold

BASE_GLOB = str(REPO_ROOT / "data" / "derived" / "copy_cohort" / "base" / "coin=*/part.parquet")
H = "4h"
H_MS = HORIZONS[H]
START_MS = 1754006400000                       # 2025-08-01T00:00Z — tape start
ENTRY_LAG_MAX_S = 90                           # F0
K_COHORT = 100                                 # §4
MIN_FWD_EP = 3                                 # §5.3
WINSOR = (0.01, 0.99)                          # §4 Arm B
FROZEN_CLUSTER = "wallet_week"                 # Stage-0 adoption (stage0_report.json)

# F1–F8 frozen values (§3)
F1_MIN_EP, F2_MIN_DAYS, F3_MIN_WEEKS = 30, 20, 6
F4_MIN_MED_HOLD_MIN, F5_MIN_MED_NOTIONAL = 60.0, 1_000.0
F6_MAX_EP_SHARE, F7_MAX_FLAG_SHARE = 0.25, 0.20


def connect():
    return _connect()


def _score_arm(vals: np.ndarray, w_code: np.ndarray, c_code: np.ndarray,
               wallet: np.ndarray) -> tuple[dict, dict]:
    """eb_shrink on integer wallet/cluster codes (fast), then map codes → wallet ids. Returns
    (wallet→selection-score dict, meta). NaN vals are dropped (eb_shrink refuses NaN)."""
    good = ~np.isnan(vals)
    r = eb_shrink(vals[good], w_code[good], c_code[good])
    rank = r.tstat if r.tau2_floored else r.shrunk
    rank = np.where(np.isnan(rank), -np.inf, rank)
    # r.unit are the sorted-unique integer w_codes; recover each code's wallet id
    uw, idx = np.unique(w_code[good], return_index=True)
    code_to_wallet = dict(zip(uw.tolist(), wallet[good][idx].tolist()))
    score = {code_to_wallet[c]: s for c, s in zip(r.unit.tolist(), rank.tolist())}
    meta = {"tau2": r.tau2, "tau2_floored": r.tau2_floored,
            "ranking": "tstat" if r.tau2_floored else "shrunk", "n_scored": int(r.unit.size)}
    return score, meta


def _arm_a_sql(lo_ms: int | None = None, hi_ms: int | None = None,
               censor_ms: int | None = None) -> str:
    """Arm-A scoreable episodes with y. Formation: censor_ms = window censor at the cutoff (open
    range implied). Forward: pass [lo, hi) open_ts range and censor_ms=None (no window censor).
    Assumes a `mu` temp table registered at the appropriate cutoff."""
    conds = [f"b.open_ts >= {lo_ms if lo_ms is not None else START_MS}",
             "b.crossed_open", "NOT b.opener_flagged",
             "NOT b.entry_after_close", f"b.entry_lag_s <= {ENTRY_LAG_MAX_S}",
             f"b.raw_markout_{H} IS NOT NULL"]
    if hi_ms is not None:
        conds.append(f"b.open_ts < {hi_ms}")
    if censor_ms is not None:
        conds.append(f"b.entry_bar_ts + {H_MS} < {censor_ms}")
        # A liquidation close is usable only once known at the cutoff. A bare
        # `NOT is_liquidation_close` peeks through episodes liquidated after C.
        conds.append(f"(NOT b.is_liquidation_close OR b.close_ts IS NULL OR b.close_ts >= {censor_ms})")
    return f"""
      SELECT b.wallet, b.coin, b.open_ts, b.close_ts, b.entry_bar_ts, b.dir_sign,
             b.iso_week_open AS week_open,
             b.initial_notional_usd, b.hold_minutes,
             b.raw_markout_{H} - b.dir_sign * mu.mu_{H} AS y
      FROM read_parquet('{BASE_GLOB}', hive_partitioning=false) b
      JOIN mu ON mu.coin = b.coin AND mu.iso_week = b.iso_week_entry
      WHERE {' AND '.join(conds)} AND mu.mu_{H} IS NOT NULL"""


@dataclass
class FoldPanel:
    cutoff_month: int              # last formation month
    cutoff_ms: int
    pool: np.ndarray               # eligible wallets (sorted)
    features: dict                 # wallet -> (n_ep, med_notional, majority_coin, long_share)
    score_a: dict                  # wallet -> Arm-A selection score
    score_b: dict                  # wallet -> Arm-B selection score
    score_a_meta: dict
    score_b_meta: dict


def build_formation(con, cutoff_month: int, arm_b_apply_f0: bool = True) -> FoldPanel:
    """Eligibility pool + both arms' scores, all formation-only at cutoff = end of cutoff_month.

    `arm_b_apply_f0=True` is the corrected Arm-B v2 config (2026-07-13). The original Arm-B SQL
    accidentally omitted the registered entry-freshness predicates; pass False only to reproduce
    that legacy as-implemented cohort as a labeled sensitivity.
    """
    c = as_of_cutoff_ms(cutoff_month)
    mu_fold.register_mu(con, cutoff_ms=c, horizons=(H,), start_ms=START_MS)
    con.execute(f"CREATE OR REPLACE TEMP TABLE fa AS {_arm_a_sql(censor_ms=c)}")

    # wallet-level features + F1–F6/F8 from the Arm-A panel; F7 from the unfiltered episode lake
    feats = con.execute(f"""
      SELECT wallet,
             count(*)                                   AS n_ep,
             count(DISTINCT open_ts // 86400000)        AS n_days,
             count(DISTINCT week_open)                  AS n_weeks,
             coalesce(median((least(coalesce(close_ts, {c}), {c}) - open_ts) / 60000.0), 0.0)
                                                            AS med_hold,
             coalesce(median(initial_notional_usd), 0.0) AS med_notional,
             max(initial_notional_usd) / sum(initial_notional_usd) AS max_ep_share,
             avg(CASE WHEN dir_sign > 0 THEN 1.0 ELSE 0.0 END)     AS long_share,
             max_by(coin, coin_n)                       AS majority_coin
      FROM (SELECT *, count(*) OVER (PARTITION BY wallet, coin) AS coin_n FROM fa)
      GROUP BY wallet""").fetchnumpy()
    flags = con.execute(f"""
      SELECT wallet,
             avg(CASE WHEN opener_flagged OR
                           (close_ts IS NOT NULL AND close_ts < {c} AND is_liquidation_close)
                      THEN 1.0 ELSE 0.0 END) AS flag_share
      FROM read_parquet('{BASE_GLOB}', hive_partitioning=false)
      WHERE open_ts >= {START_MS} AND open_ts < {c}
      GROUP BY wallet""").fetchnumpy()
    flag_map = dict(zip(flags["wallet"].tolist(), flags["flag_share"].tolist()))

    w = feats["wallet"]
    elig = ((feats["n_ep"] >= F1_MIN_EP) & (feats["n_days"] >= F2_MIN_DAYS)
            & (feats["n_weeks"] >= F3_MIN_WEEKS) & (feats["med_hold"] >= F4_MIN_MED_HOLD_MIN)
            & (feats["med_notional"] >= F5_MIN_MED_NOTIONAL)
            & (feats["max_ep_share"] <= F6_MAX_EP_SHARE))
    fshare = np.array([flag_map.get(x, 0.0) for x in w.tolist()])
    elig &= fshare <= F7_MAX_FLAG_SHARE
    pool = np.sort(w[elig])
    # register the pool so both arms restrict + factorize wallet→int codes IN SQL (avoids np.unique
    # / np.isin on millions of 42-char hex strings — that string work, not the scans, was the ~1h cost)
    con.register("pool_src", {"wallet": pool.astype(str)})
    con.execute("CREATE OR REPLACE TEMP TABLE poolt AS SELECT * FROM pool_src")
    con.unregister("pool_src")

    # Arm A score: eb_shrink on pool-wallet formation episodes, frozen wallet_week clusters
    a = con.execute("""
      SELECT dense_rank() OVER (ORDER BY f.wallet) - 1               AS w_code,
             dense_rank() OVER (ORDER BY f.wallet, f.week_open) - 1  AS c_code,
             f.wallet, f.y
      FROM fa f JOIN poolt p ON f.wallet = p.wallet""").fetchnumpy()
    score_a, meta_a = _score_arm(a["y"], a["w_code"], a["c_code"], a["wallet"])

    # Arm B: pool-wallet closed episodes, winsorized (coin,week_close)-demeaned realized bps
    arm_b_f0 = (f"AND NOT b.entry_after_close AND b.entry_lag_s <= {ENTRY_LAG_MAX_S}"
                if arm_b_apply_f0 else "")
    b = con.execute(f"""
      WITH cl AS (
        SELECT b.wallet, b.coin,
               b.iso_week_open AS week_open,
               strftime(make_timestamp(b.close_ts*1000), '%G%V') AS week_close,
               b.realized_pnl_usd / (b.initial_notional_usd + b.total_added_notional_usd) * 1e4 AS bps
        FROM read_parquet('{BASE_GLOB}', hive_partitioning=false) b
        JOIN poolt p ON b.wallet = p.wallet
        WHERE b.open_ts >= {START_MS} AND b.close_ts IS NOT NULL AND b.close_ts < {c}
          AND b.crossed_open AND NOT b.opener_flagged AND NOT b.is_liquidation_close
          {arm_b_f0}
          AND b.initial_notional_usd + b.total_added_notional_usd > 0
      ),
      wz AS (SELECT quantile_cont(bps, {WINSOR[0]}) AS q_lo,
                    quantile_cont(bps, {WINSOR[1]}) AS q_hi FROM cl),
      wc AS (SELECT cl.*, greatest(least(bps, wz.q_hi), wz.q_lo) AS bps_w FROM cl, wz)
      SELECT dense_rank() OVER (ORDER BY wallet) - 1              AS w_code,
             dense_rank() OVER (ORDER BY wallet, week_open) - 1   AS c_code,
             wallet,
             bps_w - avg(bps_w) OVER (PARTITION BY coin, week_close) AS bps_dm
      FROM wc""").fetchnumpy()
    if b["wallet"].size > 0:
        score_b, meta_b = _score_arm(b["bps_dm"], b["w_code"], b["c_code"], b["wallet"])
    else:
        score_b, meta_b = {}, {"n_scored": 0}
    meta_b["arm_b_apply_f0"] = bool(arm_b_apply_f0)
    meta_b["config_epoch"] = "arm_b_v2_f0_2026-07-13" if arm_b_apply_f0 else "legacy_no_f0"

    features = {}
    act_edges = np.quantile(feats["n_ep"][elig], [0.2, 0.4, 0.6, 0.8])
    not_edges = np.quantile(feats["med_notional"][elig], [0.2, 0.4, 0.6, 0.8])
    for i in np.flatnonzero(elig):
        features[w[i]] = {
            "act_q": int(np.searchsorted(act_edges, feats["n_ep"][i], side="right")),
            "not_q": int(np.searchsorted(not_edges, feats["med_notional"][i], side="right")),
            "coin": feats["majority_coin"][i],
            "long_h": int(feats["long_share"][i] >= 0.5),
            "n_ep": int(feats["n_ep"][i]),
        }
    return FoldPanel(cutoff_month, c, pool, features, score_a, score_b, meta_a, meta_b)


@dataclass
class ForwardFrame:
    test_month: int
    wallet_mean: dict              # wallet -> forward mean y (episode-equal-weight)
    wallet_n: dict                 # wallet -> n forward episodes
    ep_wallet: np.ndarray          # episode-level arrays for pooled CI construction
    ep_week: np.ndarray            # ISO-week (open_ts) labels
    ep_y: np.ndarray


def build_forward(con, test_month: int, restrict_wallets: np.ndarray) -> ForwardFrame:
    """Forward outcomes for month T: episodes OPENED in [C_T, C_next) by `restrict_wallets`
    (the eligible pool — placebos need pool-wide coverage). μ censored at the NEXT cutoff.
    Scans all partitions; predicate on open_ts only (finalize-month trap)."""
    y, m = divmod(test_month, 100)
    prev_month = (y - 1) * 100 + 12 if m == 1 else test_month - 1
    lo = as_of_cutoff_ms(prev_month)
    hi = as_of_cutoff_ms(test_month)
    mu_fold.register_mu(con, cutoff_ms=hi, horizons=(H,), start_ms=START_MS, table="mu")
    con.execute("CREATE OR REPLACE TEMP TABLE fw AS "
                + _arm_a_sql(lo_ms=lo, hi_ms=hi, censor_ms=None))
    con.register("pool_src", {"wallet": restrict_wallets.astype(str)})
    con.execute("CREATE OR REPLACE TEMP TABLE pool AS SELECT * FROM pool_src")
    con.unregister("pool_src")
    d = con.execute("""
      SELECT f.wallet, f.week_open, f.y FROM fw f JOIN pool p ON f.wallet = p.wallet""").fetchnumpy()
    assert d["wallet"].size > 0, f"no forward episodes for month {test_month} — check open_ts window"
    wallets, inv = np.unique(d["wallet"], return_inverse=True)
    n_w = np.bincount(inv)
    mean_w = np.bincount(inv, weights=d["y"]) / np.maximum(n_w, 1)
    return ForwardFrame(test_month,
                        dict(zip(wallets.tolist(), mean_w.tolist())),
                        dict(zip(wallets.tolist(), n_w.tolist())),
                        d["wallet"], d["week_open"], d["y"])


def formation_episodes(con, cutoff_month: int) -> dict:
    """Raw Arm-A formation episodes for the power gate, restricted to pool wallets with integer
    wallet/week codes (so the planted control can inject BEFORE eb_shrink and score fast). `poolt`
    is left registered by build_formation."""
    panel = build_formation(con, cutoff_month)
    d = con.execute("""
      SELECT dense_rank() OVER (ORDER BY f.wallet) - 1              AS w_code,
             dense_rank() OVER (ORDER BY f.wallet, f.week_open) - 1 AS wk_code,
             f.wallet, f.open_ts, f.week_open, f.y
      FROM fa f JOIN poolt p ON f.wallet = p.wallet""").fetchnumpy()
    return {"wallet": d["wallet"], "w_code": d["w_code"], "wk_code": d["wk_code"],
            "open_ts": d["open_ts"], "week_open": d["week_open"], "y": d["y"],
            "pool": panel.pool, "features": panel.features, "cutoff_ms": panel.cutoff_ms}


def top_k(score: dict, pool: np.ndarray, k: int = K_COHORT) -> np.ndarray:
    """Frozen id-list: top-k pool wallets by score; deterministic tie-break by wallet id."""
    scored = sorted(((score.get(w, -np.inf), w) for w in pool.tolist()),
                    key=lambda t: (-t[0] if np.isfinite(t[0]) else np.inf, t[1]))
    return np.array([w for _, w in scored[:k]])
