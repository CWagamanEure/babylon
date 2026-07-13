"""Rolling-WF realized-PnL top-K cohort — reproduce the user's other-repo finding on this tape, then
extend (consensus predictiveness, copy-trade sim come later). Step 1: does ranking the pool by
realized PnL over a rolling window and taking the top-K produce a cohort that OUT-PERFORMS next month?

Faithful to the user's description: rank by realized PnL (total $ over the window), top-K=30, rolling
window. Reads the base table directly (closed episodes only). Reports forward per-wallet realized bps
(copytrade-relevant return), forward $ PnL (the 'exceptional' framing), hold-time (confirm week+
holders), all vs a random-K baseline from the same eligible pool, with a cross-fold sign test — the
same anti-over-carry discipline: wallet-equal (per-decision) forward mean is the headline, not
episode/notional-weighted.

    python -m research.studies.copy_cohort.pnl_cohort run
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import as_of_cutoff_ms, MONTHS
from research.lib.stats import sign_test
from . import selectors
from .walkforward import _one_sided_sign_p

BASE_GLOB = selectors.BASE_GLOB
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "pnl_cohort_report.json"
START_MS = selectors.START_MS
W_MONTHS = 3                # rolling formation window
K = 30                      # user's top-30
MIN_CLOSED = 5              # ex-ante: ≥5 closed episodes in the window (drop single-trade whales)
N_RAND = 200               # random-K baseline draws
SEED = 20260712


def _window_lo(test_month: int, w: int) -> int:
    """First ms of the rolling formation window = w months before the test month's start."""
    idx = MONTHS.index(test_month)
    start_month = MONTHS[idx - w]
    y, m = divmod(start_month, 100)
    pm = (y - 1) * 100 + 12 if m == 1 else start_month - 1
    return as_of_cutoff_ms(pm)


def _closed(con, lo: int, hi: int) -> dict:
    """Per-(wallet) closed-episode aggregates in [lo, hi): total realized $, per-episode bps list via
    a flat table. Returns raw episode rows (wallet, bps, pnl_usd, notional, hold_days, coin, dir_sign)."""
    return con.execute(f"""
      SELECT wallet, coin, dir_sign,
             realized_pnl_usd AS pnl,
             initial_notional_usd + total_added_notional_usd AS notional,
             realized_pnl_usd / (initial_notional_usd + total_added_notional_usd) * 1e4 AS bps,
             (close_ts - open_ts) / 86400000.0 AS hold_days
      FROM read_parquet('{BASE_GLOB}', hive_partitioning=false)
      WHERE close_ts IS NOT NULL AND close_ts >= {lo} AND close_ts < {hi}
        AND NOT opener_flagged AND NOT is_liquidation_close
        AND initial_notional_usd + total_added_notional_usd > 0""").fetchnumpy()


def _rank_pool(d: dict) -> tuple[np.ndarray, dict]:
    """Eligible pool (≥MIN_CLOSED closed eps) ranked by TOTAL realized $ PnL over the window."""
    w = d["wallet"]
    uw, inv = np.unique(w, return_inverse=True)
    n = np.bincount(inv)
    tot_pnl = np.bincount(inv, weights=d["pnl"])
    elig = n >= MIN_CLOSED
    order = np.argsort(np.where(elig, tot_pnl, -np.inf))[::-1]
    ranked = uw[order][: int(elig.sum())]
    return ranked, {"n_pool": int(elig.sum()), "tot_pnl_top": float(tot_pnl[order[0]]) if elig.any() else 0.0}


def _fwd_wallet_bps(d: dict, cohort: set) -> np.ndarray:
    """Per-wallet forward mean realized bps (wallet-equal / per-decision) for cohort wallets present."""
    mask = np.isin(d["wallet"], list(cohort))
    if not mask.any():
        return np.array([])
    w = d["wallet"][mask]; bps = d["bps"][mask]
    uw, inv = np.unique(w, return_inverse=True)
    return np.bincount(inv, weights=bps) / np.bincount(inv)


def run() -> dict:
    con = selectors.connect()
    rng = np.random.default_rng(SEED)
    test_months = [m for m in MONTHS if MONTHS.index(m) >= W_MONTHS]
    report = {"config": {"W_months": W_MONTHS, "K": K, "min_closed": MIN_CLOSED,
                         "rank_metric": "total realized $ PnL over window", "test_months": test_months,
                         "n_rand_baseline": N_RAND, "seed": SEED}, "folds": {}}
    coh_means, rnd_means, coh_signp = [], [], []
    per_wallet_all = []
    for T in test_months:
        lo, hi = _window_lo(T, W_MONTHS), as_of_cutoff_ms(_prev(T))
        fhi = as_of_cutoff_ms(T)
        form = _closed(con, lo, hi)
        fwd = _closed(con, hi, fhi)
        ranked, meta = _rank_pool(form)
        if ranked.size < K:
            report["folds"][str(T)] = {"skip": f"pool {ranked.size} < K"}
            continue
        cohort = set(ranked[:K].tolist())
        # confirm week+ holders: cohort hold-time in the forward month
        fwd_hold = fwd["hold_days"][np.isin(fwd["wallet"], list(cohort))]
        cm = _fwd_wallet_bps(fwd, cohort)
        # random-K baseline from the eligible pool
        pool = ranked
        rand_means = []
        for _ in range(N_RAND):
            rc = set(rng.choice(pool, size=K, replace=False).tolist())
            rb = _fwd_wallet_bps(fwd, rc)
            if rb.size:
                rand_means.append(float(rb.mean()))
        rand_med = float(np.median(rand_means)) if rand_means else float("nan")
        p_beat = (int(np.sum(np.array(rand_means) >= cm.mean())) + 1) / (len(rand_means) + 1) if cm.size else float("nan")
        signp = _one_sided_sign_p(cm) if cm.size else float("nan")
        # forward $ PnL of the cohort (their 'exceptional' framing)
        fwd_pnl = float(fwd["pnl"][np.isin(fwd["wallet"], list(cohort))].sum())
        report["folds"][str(T)] = {
            "pool": meta["n_pool"], "cohort_fwd_wallet_equal_bps": float(cm.mean()) if cm.size else None,
            "n_cohort_fwd_active": int(cm.size), "random_med_bps": rand_med,
            "beats_random": bool(cm.size and cm.mean() > rand_med), "p_beat_random": p_beat,
            "sign_frac_pos": float((cm > 0).mean()) if cm.size else None, "sign_p_one_sided": signp,
            "cohort_fwd_total_pnl_usd": fwd_pnl,
            "cohort_median_hold_days": float(np.median(fwd_hold)) if fwd_hold.size else None}
        if cm.size:
            coh_means.append(float(cm.mean())); rnd_means.append(rand_med)
            coh_signp.append(signp); per_wallet_all.append(cm)
    # pooled
    if per_wallet_all:
        allw = np.concatenate(per_wallet_all)
        report["pooled"] = {
            "n_folds": len(coh_means), "folds_beat_random": int(sum(c > r for c, r in zip(coh_means, rnd_means))),
            "mean_cohort_fwd_bps": float(np.mean(coh_means)), "mean_random_fwd_bps": float(np.mean(rnd_means)),
            "pooled_wallet_equal_fwd_bps": float(allw.mean()), "n_wallet_folds": int(allw.size),
            "pooled_sign_frac_pos": float((allw > 0).mean()), "pooled_sign_p_one_sided": _one_sided_sign_p(allw),
            "CAVEAT": "wallet-folds not independent (overlapping cohort across folds); random baseline "
                      "unmatched on style — first-look reproduction, not the hardened verdict"}
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"pnl_cohort done -> {OUT}")
    if "pooled" in report:
        p = report["pooled"]
        print(f"  folds beat random: {p['folds_beat_random']}/{p['n_folds']}  "
              f"cohort {p['mean_cohort_fwd_bps']:.1f}bp vs random {p['mean_random_fwd_bps']:.1f}bp  "
              f"pooled sign {p['pooled_sign_frac_pos']:.2f} p={p['pooled_sign_p_one_sided']:.4f}")
    return report


def _prev(month: int) -> int:
    y, m = divmod(month, 100)
    return (y - 1) * 100 + 12 if m == 1 else month - 1


if __name__ == "__main__":
    run()
