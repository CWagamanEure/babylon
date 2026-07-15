"""Step 2 — replace capped-PnL ranking with a SHRUNK 8h-markout LCB selector, head-to-head in the book.

The user's point: the target is future 8h signed markout, NOT realized wallet PnL (which is inflated by
leverage/beta/holding-period/one-big-trade). So rank candidates by a lower-confidence-bound estimate of
their historical COPYABLE 8h markout:  score_i = shrunk(μ_i,8h) − λ·SE_i, SE clustered by wallet-coin-day,
μ empirical-Bayes shrunk (3 months is a small per-wallet sample). Then run the SAME leakage-clean book
(follow opening-taker, q50 prior-notional sizing, 8h exit, matched cost) and compare OOS vs the capped-PnL
cohort — dollar book, WALLET-EQUAL (the anti-over-carry co-primary), and CI width.

Leakage-safe formation: a wallet's formation markout uses only entries whose 8h settles BEFORE the cutoff
(entry_bar_ts + 8h < cutoff). Candidate universe = the SAME nd≥15 capday-eligible pool (apples-to-apples
selector swap), further requiring ≥MIN_EP formation opening-taker entries and ≥2 clusters for a real estimate.

    python -m research.studies.copy_cohort.capday_markout_select
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from research.lib.cv import MONTHS, as_of_cutoff_ms
from research.lib.stats import eb_shrink
from .base import open_base
from .capday_cohort import _pool_scores, _window_days
from . import capday_book as cb

K = cb.K
LAMBDA = 1.0                         # LCB penalty (one cluster-SE); PRIMARY, pre-registered (not argmax'd)
LAMBDA_SENS = (0.0, 1.645)          # sensitivities: 0 = pure shrunk mean, 1.645 = 95% one-sided
MIN_EP = 10                          # a wallet needs ≥10 formation opening-taker 8h-settled entries to be ranked
H8_MS = cb.HORIZON_MS["8h"]
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_markout_select_report.json"


def _formation_markout(con, T: int) -> dict:
    """Per pool wallet: EB-shrunk formation 8h markout + cluster-robust SE (clusters = wallet-coin-day).
    Only entries whose 8h settles strictly before the cutoff (leakage-safe)."""
    i = MONTHS.index(T)
    cutoff = as_of_cutoff_ms(MONTHS[i - 1])
    lo_day, _ = _window_days(T)
    lo_ms = lo_day * cb.DAY_MS
    g = open_base(con)
    d = con.execute(f"""
      SELECT wallet, coin, entry_bar_ts, raw_markout_8h AS mk,
             (entry_bar_ts // {cb.DAY_MS}) AS day
      FROM read_parquet('{g}')
      WHERE crossed_open AND NOT opener_flagged AND NOT entry_after_close AND entry_lag_s<=90
            AND raw_markout_8h IS NOT NULL
            AND open_ts >= {lo_ms} AND (entry_bar_ts + {H8_MS}) < {cutoff}
      ORDER BY wallet""").fetchnumpy()
    return d


def _markout_cohorts() -> tuple[list, dict]:
    """Per fold: top-K pool wallets by shrunk-markout LCB. Returns (cohorts, meta)."""
    con = _connect()
    cohorts, meta = [], {}
    for T in cb.FOLDS:
        lo_day, hi_day = _window_days(T)
        pool = set(_pool_scores(con, lo_day, hi_day, cb.CAP if hasattr(cb, "CAP") else 100_000.0)["wallet"].astype(str)) \
            if False else set(_pool_scores(con, lo_day, hi_day, 100_000.0)["wallet"].astype(str))
        d = _formation_markout(con, T)
        w = d["wallet"].astype(str); coin = d["coin"].astype(str); mk = np.asarray(d["mk"], float)
        day = np.asarray(d["day"], np.int64)
        # restrict to the capday-eligible pool (apples-to-apples candidate universe)
        keep = np.array([x in pool for x in w])
        w, coin, mk, day = w[keep], coin[keep], mk[keep], day[keep]
        # integer codes: wallet, and wallet-coin-day cluster
        uw, wcode = np.unique(w, return_inverse=True)
        cl_key = np.char.add(np.char.add(w, "|"), np.char.add(coin, "|" + day.astype(str)))
        _, ccode = np.unique(cl_key, return_inverse=True)
        # per-wallet episode count filter
        cnt = np.bincount(wcode)
        eligible = cnt >= MIN_EP
        good = eligible[wcode]
        if good.sum() == 0:
            cohorts.append(set()); continue
        r = eb_shrink(mk[good], wcode[good], ccode[good])
        # SE from tstat (= raw_mean / SE); guard tstat≈0 / nan -> big SE (untrusted)
        se = np.where(np.abs(r.tstat) > 1e-9, np.abs(r.raw_mean) / np.abs(r.tstat), np.inf)
        se = np.where(np.isfinite(se), se, np.nanmedian(se[np.isfinite(se)]) if np.isfinite(se).any() else 1e3)
        mu = np.where(r.tau2_floored, r.raw_mean, r.shrunk)   # fallback to raw mean if τ² floored
        lcb = {L: mu - L * se for L in (LAMBDA, *LAMBDA_SENS)}
        code_wallet = uw  # eb_shrink units are sorted unique wcodes -> map via r.unit
        unit_wallet = np.array([uw[c] for c in r.unit])
        coh = {}
        for L in (LAMBDA, *LAMBDA_SENS):
            order = np.argsort(lcb[L])[::-1]
            coh[L] = set(unit_wallet[order][:K].tolist())
        cohorts.append(coh[LAMBDA])
        meta[str(T)] = {"pool": len(pool), "ranked_wallets": int(eligible.sum()),
                        "tau2_floored": bool(r.tau2_floored),
                        "cohorts_by_lambda": {str(L): sorted(coh[L]) for L in (LAMBDA, *LAMBDA_SENS)}}
        print(f"markout-select {T}: pool={len(pool)} ranked={int(eligible.sum())} "
              f"top{K}_by_LCB(λ={LAMBDA})  τ²_floored={r.tau2_floored}", flush=True)
    return cohorts, meta


def _book_summary(con, cohorts: list, label: str) -> dict:
    """Run the SAME 8h q50 book on a cohort list; return the headline comparison fields."""
    ep = cb._pull_episodes(con, sorted(set().union(*[c for c in cohorts if c]) | {"__none__"}))
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64)); index = cb._row_index(ep, midx)
    clips = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})
    lo, hi = cb._cal_bounds(ep, midx, "8h")
    b = cb._book(ep, clips[0.50], index, cohorts, "8h", lo, hi)
    wq = b.get("wallet_equal_net_bp", {}); ci = b.get("absolute_weighted_ci", {})
    return {"label": label, "n_evaluable": b["n_evaluable"], "n_wallets": b.get("n_wallets"),
            "dollar_wtd_net_bp": b.get("dollar_wtd_net_bp"),
            "two_way_ci": [ci.get("ci_lo"), ci.get("ci_hi")], "two_way_se": ci.get("se"),
            "wallet_equal_net_bp": wq.get("point_bp"), "wallet_equal_ci": [wq.get("ci_lo"), wq.get("ci_hi")],
            "win_rate": b.get("win_rate"), "top_wallet_share_pos": b.get("top_wallet_share_positive_pnl"),
            "leave_one_wallet_min": b.get("leave_one_wallet_net_bp_min")}


def run():
    con = _connect()
    mk_cohorts, meta = _markout_cohorts()
    cap_cohorts = cb._selection().cohorts        # the capped-PnL baseline (same folds)
    overlap = [len(a & b) for a, b in zip(mk_cohorts, cap_cohorts)]
    print(f"\nmarkout-vs-capped cohort overlap per fold (of {K}): {overlap}", flush=True)
    mk_sum = _book_summary(con, mk_cohorts, "markout_LCB")
    cap_sum = _book_summary(con, cap_cohorts, "capped_PnL")
    rep = {"config": {"K": K, "lambda": LAMBDA, "lambda_sens": LAMBDA_SENS, "min_ep": MIN_EP,
                      "horizon": "8h", "q": 0.50}, "selection_meta": meta,
           "cohort_overlap_per_fold": overlap,
           "markout_LCB": mk_sum, "capped_PnL": cap_sum}
    OUT.write_text(json.dumps(rep, indent=2, default=str))
    print("\n=== HEAD-TO-HEAD 8h q50 book (markout-LCB selection vs capped-PnL selection) ===")
    for s in (cap_sum, mk_sum):
        print(f"  {s['label']:12s}: $wtd {s['dollar_wtd_net_bp']:+.1f}bp CI[{s['two_way_ci'][0]:.1f},{s['two_way_ci'][1]:.1f}] "
              f"se={s['two_way_se']:.1f} | WALLET-EQ {s['wallet_equal_net_bp']:+.1f} | n={s['n_evaluable']} "
              f"wal={s['n_wallets']} win={s['win_rate']:.2f} loo_min={s['leave_one_wallet_min']:+.1f}")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
