"""Actual copy-trade BOOK backtest (not markout-averaging) for the Arm-C capped-PnL-per-day cohort.

The user's correction: averaging per-position markout bps is NOT running the book. A real follower SIZES
each entry and the PORTFOLIO's dollar P&L / equity curve is the result (dollar-weighted, aggregated, with
its own Sharpe) — which can differ from (and beat) an equal-weighted bps average.

Spec (validated here):
  SELECTION  : top-30 wallets by capped-PnL-per-active-day, CAP_DAILY = 100k (the user's cap), 3-month
               trailing window, monthly roll, data ≤ T−1 — identical to capday_cohort._pool_scores.
  FOLLOW     : the cohort's forward OPENING TAKER episodes in month T (crossed_open; opening from the
               start_position/dir reconstruction, not buy/sell side).
  SIZE       : per (wallet, coin), the follower clips at the qXX percentile of that wallet's PRIOR
               opening-taker notionals in that coin (expanding, strictly ts < entry → leakage-safe).
               Runs q50 and q75. Entries with no prior same-coin trade are un-sizeable → skipped (counted).
  EXIT       : ~8h markout (raw_markout_8h = dir-signed 8h return, bps).
  P&L        : net$ = clip_notional · (raw_markout_8h − round_trip_cost) / 1e4, round_trip = 2·1.3bp taker.
  BOOK       : sum of independent sized positions → equity curve (unlevered); report total net$, total
               deployed clip$, dollar-weighted net bps, daily-Sharpe, max drawdown, n positions. Benchmarked
               against R random-30 cohorts drawn from the SAME ≥15-active-day pool each month (same sizing
               rule) → p-value on total net$.

    python -m research.studies.copy_cohort.book run
"""
from __future__ import annotations

import bisect
import json
import sys

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from research.lib.cv import MONTHS, as_of_cutoff_ms
from .capday_cohort import BASE_GLOB, CAPDAY, _window_days, _pool_scores, K, TAKER_COST_BP

CAP = 100_000.0
QS = (0.50, 0.75)
N_RAND = 200
SEED = 20260712
RT_COST_BP = 2 * TAKER_COST_BP                 # taker in + taker out
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "book_report.json"
EQ_OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "book_equity.json"

TEST_MONTHS = MONTHS[3:]
CUTS = np.array([as_of_cutoff_ms(m) for m in MONTHS])     # cutoff[i] = first ms of MONTHS[i]+1
MONTH_LO = np.array([as_of_cutoff_ms(MONTHS[MONTHS.index(T) - 1]) for T in TEST_MONTHS])  # start of each test month
MONTH_HI = np.array([as_of_cutoff_ms(T) for T in TEST_MONTHS])


def _cohorts(con):
    """Per test-month: the top-30 @CAP cohort AND the eligible pool (for random draws)."""
    coh, pools = {}, {}
    for T in TEST_MONTHS:
        lo_day, hi_day = _window_days(T)
        pool = _pool_scores(con, lo_day, hi_day, CAP)
        pools[T] = pool["wallet"]
        if pool["wallet"].size >= K:
            order = np.argsort(pool["metric"])[::-1]
            coh[T] = pool["wallet"][order][:K]
        else:
            coh[T] = np.array([], dtype=pool["wallet"].dtype)
    return coh, pools


def _pull_episodes(con, wallets: np.ndarray) -> dict:
    """All opening-taker episodes (any month) for the given wallets — needed for BOTH sizing history and
    the followed positions."""
    con.register("u_src", {"wallet": wallets.astype(str)})
    con.execute("CREATE OR REPLACE TEMP TABLE u AS SELECT DISTINCT wallet FROM u_src")
    con.unregister("u_src")
    d = con.execute(f"""
      SELECT b.wallet, b.coin, b.entry_bar_ts AS ts, b.open_ts,
             b.initial_notional_usd AS notl, b.raw_markout_8h AS mk
      FROM read_parquet('{BASE_GLOB}', hive_partitioning=false) b
      JOIN u ON b.wallet = u.wallet
      WHERE b.crossed_open AND NOT b.opener_flagged AND NOT b.is_liquidation_close
        AND b.initial_notional_usd > 0
      ORDER BY b.wallet, b.coin, b.entry_bar_ts""").fetchnumpy()
    return d


def _expanding_clip(ep: dict, q: float) -> np.ndarray:
    """Per (wallet,coin), qXX percentile of PRIOR notionals (strictly earlier ts). NaN if no prior trade."""
    wallet, coin, ts, notl = ep["wallet"], ep["coin"], ep["ts"], ep["notl"]
    clip = np.full(notl.size, np.nan)
    key = np.char.add(wallet.astype(str), np.char.add("|", coin.astype(str)))
    # rows are already ORDER BY wallet, coin, ts → contiguous groups
    uk, starts = np.unique(key, return_index=True)
    bounds = list(starts) + [notl.size]
    for gi in range(len(uk)):
        a, b = bounds[gi], bounds[gi + 1]
        sizes = notl[a:b]
        tss = ts[a:b]
        for j in range(1, b - a):                      # j=0 has no prior → stays NaN
            # prior = same group, ts strictly < tss[j]; group sorted by ts
            hi = bisect.bisect_left(tss, tss[j], 0, j)  # count of ts < tss[j] among first j
            if hi > 0:
                clip[a + j] = np.quantile(sizes[:hi], q)
    return clip


def _month_idx(open_ts: np.ndarray) -> np.ndarray:
    """Test-month index for each episode (0..len(TEST_MONTHS)-1), or -1 if outside all test months."""
    idx = np.searchsorted(MONTH_HI, open_ts, side="right")     # first month whose HI > open_ts
    good = (idx < len(TEST_MONTHS)) & (open_ts >= MONTH_LO[np.clip(idx, 0, len(TEST_MONTHS) - 1)])
    return np.where(good, idx, -1)


def _build_index(ep: dict, clip: np.ndarray, midx: np.ndarray) -> dict:
    """Map (test_month_index, wallet) -> array of sizeable episode row indices (built once per q)."""
    sel = np.flatnonzero(~np.isnan(clip) & (midx >= 0))
    idx = {}
    for i in sel:
        idx.setdefault((int(midx[i]), ep["wallet"][i]), []).append(i)
    return {k: np.array(v) for k, v in idx.items()}


def _book(ep: dict, clip: np.ndarray, idx_by_key: dict, membership: dict, want_equity=False) -> dict:
    """Aggregate the sized book for {test_month_index -> set(wallets)} via the prebuilt (month,wallet) index."""
    parts = [idx_by_key[(mi, w)] for mi, wset in membership.items() for w in wset if (mi, w) in idx_by_key]
    f = np.concatenate(parts) if parts else np.array([], dtype=int)
    if f.size == 0:
        return {"n_pos": 0, "net_usd": 0.0, "daily_sharpe": 0.0}
    clp = clip[f]; mk = ep["mk"][f]; ts = ep["ts"][f]
    net_usd = clp * (mk - RT_COST_BP) / 1e4
    gross_usd = clp * mk / 1e4
    order = np.argsort(ts)
    eq = np.cumsum(net_usd[order])
    # daily aggregation for Sharpe
    day = ts[order] // 86_400_000
    ud, inv = np.unique(day, return_inverse=True)
    daily = np.bincount(inv, weights=net_usd[order])
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    maxdd = float((peak - eq).max())
    deployed = float(clp.sum())
    out = {
        "n_pos": int(f.size), "n_wallets": int(np.unique(ep["wallet"][f]).size),
        "deployed_usd": deployed, "gross_usd": float(gross_usd.sum()), "net_usd": float(net_usd.sum()),
        "dollar_wtd_net_bp": float(net_usd.sum() / deployed * 1e4) if deployed else 0.0,
        "dollar_wtd_gross_bp": float(gross_usd.sum() / deployed * 1e4) if deployed else 0.0,
        "equal_wtd_net_bp": float((mk - RT_COST_BP).mean()),
        "win_rate": float((net_usd > 0).mean()), "daily_sharpe": sharpe, "max_dd_usd": maxdd,
        "median_clip_usd": float(np.median(clp)),
    }
    if want_equity:
        out["_equity_ts"] = (ts[order]).tolist(); out["_equity"] = eq.tolist()
    return out


def run() -> dict:
    con = _connect()
    rng = np.random.default_rng(SEED)
    coh, pools = _cohorts(con)
    # pre-draw random cohorts so we can pull ALL needed wallet histories in ONE query
    rand_sets = {mi: [] for mi in range(len(TEST_MONTHS))}
    for mi, T in enumerate(TEST_MONTHS):
        P = pools[T]
        for _ in range(N_RAND):
            rand_sets[mi].append(rng.choice(P, size=K, replace=False) if P.size >= K else np.array([]))
    need = set()
    for T in TEST_MONTHS:
        need.update(coh[T].tolist())
    for mi in rand_sets:
        for arr in rand_sets[mi]:
            need.update(arr.tolist())
    U = np.array(sorted(need))
    print(f"pulling episodes for {U.size:,} wallets (cohort ∪ {N_RAND} random draws/month)…", flush=True)
    ep = _pull_episodes(con, U)
    midx = _month_idx(ep["open_ts"])
    print(f"  {ep['wallet'].size:,} opening-taker episodes; {int((midx>=0).sum()):,} in test months", flush=True)

    idx_all = _build_index(ep, np.zeros(midx.size), midx)   # all test-month episodes (clip filter no-op)
    report = {"config": {"cap": CAP, "K": K, "qs": list(QS), "n_rand": N_RAND, "seed": SEED,
                         "round_trip_cost_bp": RT_COST_BP, "test_months": TEST_MONTHS,
                         "exit": "8h markout", "book": "unlevered sum of qXX-per-(wallet,coin)-sized positions"},
              "by_q": {}}
    equity = {}
    for q in QS:
        clip = _expanding_clip(ep, q)
        idx_by_key = _build_index(ep, clip, midx)
        cohort_mem = {mi: set(coh[T].tolist()) for mi, T in enumerate(TEST_MONTHS)}
        cb = _book(ep, clip, idx_by_key, cohort_mem, want_equity=True)
        equity[f"q{int(q*100)}"] = {"ts": cb.pop("_equity_ts"), "eq": cb.pop("_equity")}
        # random books
        r_net, r_shp = [], []
        for r in range(N_RAND):
            mem = {mi: set(rand_sets[mi][r].tolist()) for mi in range(len(TEST_MONTHS))}
            rb = _book(ep, clip, idx_by_key, mem)
            r_net.append(rb["net_usd"]); r_shp.append(rb.get("daily_sharpe", 0.0))
        r_net = np.array(r_net); r_shp = np.array(r_shp)
        p_net = (np.sum(r_net >= cb["net_usd"]) + 1) / (r_net.size + 1)
        p_shp = (np.sum(r_shp >= cb["daily_sharpe"]) + 1) / (r_shp.size + 1)
        n_followable = int(sum(idx_all[(mi, w)].size for mi, wset in cohort_mem.items()
                               for w in wset if (mi, w) in idx_all))
        report["by_q"][f"q{int(q*100)}"] = {
            "cohort": cb,
            "n_cohort_entries_in_test_months": n_followable,
            "n_unsizeable_dropped": int(n_followable - cb["n_pos"]),
            "random_net_usd_median": float(np.median(r_net)),
            "random_net_usd_p90": float(np.percentile(r_net, 90)),
            "p_beat_random_net": float(p_net),
            "random_sharpe_median": float(np.median(r_shp)), "p_beat_random_sharpe": float(p_shp),
        }
        print(f"q{int(q*100)}: cohort net ${cb['net_usd']:,.0f} on ${cb['deployed_usd']:,.0f} "
              f"({cb['dollar_wtd_net_bp']:+.1f}bp $-wtd, {cb['equal_wtd_net_bp']:+.1f}bp eq-wtd)  "
              f"Sharpe {cb['daily_sharpe']:.2f}  n={cb['n_pos']}  win {cb['win_rate']:.2f}  "
              f"| random med ${np.median(r_net):,.0f}  p_net={p_net:.3f} p_sharpe={p_shp:.3f}")
    OUT.write_text(json.dumps(report, indent=2, default=str))
    EQ_OUT.write_text(json.dumps(equity, default=str))
    print(f"-> {OUT}")
    return report


if __name__ == "__main__":
    run()
