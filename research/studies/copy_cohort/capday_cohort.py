"""Arm C — capped-PnL-per-active-day cohort selector (reproduce the user's other-repo finding).

The user's spec (validated here on the majors node_fills tape; closed_pnl only exists there):

  SELECTION (from raw per-wallet fills; use the EXCHANGE closed_pnl field, do NOT reconstruct PnL):
    1. per fill take wallet, ts, notional(=|sz|·px), closed_pnl, fee
    2. wallet×day:   day_pnl = Σ(closed_pnl − fee);  day_notional = Σ notional
    3. cap_pnl_day = day_pnl · min(1, CAP_DAILY / day_notional)         # daily notional cap
    4. wallet×month: cpnl_month = Σ cap_pnl_day;  ndays_month = #active days
    5. walk-forward monthly (test month T from the 4th month on; first 3 consumed by the window):
         window     = last 3 months (T−3..T−1), data STRICTLY up to month T−1
         per wallet  cpnl = Σ cpnl_month, nd = Σ ndays_month  over the window
         keep wallets with nd ≥ 15
         cap_pnl_per_day = cpnl / nd            # the selection metric — per ACTIVE DAY, not per order
         cohort = top-30 by cap_pnl_per_day     # re-selected every month

  EVALUATION (does the cohort's forward book earn a copytradeable ~8h markout?):
    6. only OPENING trades — identified from the episode reconstruction (start_position/dir), NOT buy/sell side
    7. keep only opening positions that are TAKERS (crossed_open)
    → per-wallet & per-episode forward raw_markout_8h (dir-signed 8h return, bps), vs a random-K baseline
      drawn from the same nd≥15 eligible pool, with a cross-fold sign test. wallet-equal is the headline
      (anti-over-carry); episode-equal is the literal all-trades follower. Gross; a taker-cost haircut is
      reported alongside.

Reuses the frozen copy_cohort base table (majors, has raw_markout_8h, crossed_open, opener flags) for the
eval side, and a fresh raw-fills aggregate (capday_base.parquet) for the novel selection metric.

    python -m research.studies.copy_cohort.capday_cohort base     # one-time wallet×day aggregate
    python -m research.studies.copy_cohort.capday_cohort run      # sweep CAP_DAILY, walk-forward
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from research.lib.cv import MONTHS, as_of_cutoff_ms
from .walkforward import _one_sided_sign_p

BASE_GLOB = str(REPO_ROOT / "data" / "derived" / "copy_cohort" / "base" / "coin=*/part.parquet")
FILLS_GLOB = str(REPO_ROOT / "data" / "raw" / "fills" / "month=*/day=*/*.parquet")
CAPDAY = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_base.parquet"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_cohort_report.json"

DAY_MS = 86_400_000
W_MONTHS = 3
K = 30
MIN_ND = 15                                   # ≥15 active days in the window
CAP_SWEEP = [100_000.0, 500_000.0, 1_000_000.0, 5_000_000.0]
N_RAND = 500
SEED = 20260712
TAKER_COST_BP = 1.3                           # ~majors taker fee+half-spread, per side (context only)


# ---------------------------------------------------------------- selection base
def build_capday_base() -> None:
    """One-time: wallet×day PnL/fee/notional over the whole majors fills tape (DOUBLE — this is a
    RANKING signal, not the exact money ledger, so float is fine per the asset-ctx/signal convention).
    Day index is epoch-days (ts // 86.4M); month boundaries are exact multiples so window slicing on
    day_idx aligns to the walk-forward month cutoffs."""
    con = _connect()
    con.execute("PRAGMA threads=4")
    tmp = str(CAPDAY) + ".tmp"
    t0 = time.time()
    con.execute(f"""COPY (
      SELECT wallet,
             (ts // {DAY_MS})                                       AS day_idx,
             sum(TRY_CAST(closed_pnl AS DOUBLE))                    AS day_closed_pnl,
             sum(TRY_CAST(fee AS DOUBLE))                           AS day_fee,
             sum(abs(TRY_CAST(sz AS DOUBLE)) * TRY_CAST(px AS DOUBLE)) AS day_notional
      FROM read_parquet('{FILLS_GLOB}', hive_partitioning=true)
      GROUP BY wallet, ts // {DAY_MS}
    ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    os.replace(tmp, CAPDAY)
    n = con.execute(f"SELECT count(*), count(DISTINCT wallet) FROM read_parquet('{CAPDAY}')").fetchone()
    print(f"capday_base: {n[0]:,} wallet-days, {n[1]:,} wallets  {time.time()-t0:.0f}s -> {CAPDAY}")


# ---------------------------------------------------------------- walk-forward
def _window_days(test_month: int) -> tuple[int, int]:
    """[lo_day, hi_day) epoch-day bounds of the 3-month formation window ending at T−1's cutoff."""
    i = MONTHS.index(test_month)
    start_month = MONTHS[i - W_MONTHS]
    y, m = divmod(start_month, 100)
    prev = (y - 1) * 100 + 12 if m == 1 else start_month - 1
    lo_ms = as_of_cutoff_ms(prev)                    # first instant of start_month
    hi_ms = as_of_cutoff_ms(MONTHS[i - 1])           # first instant of test_month
    assert lo_ms % DAY_MS == 0 and hi_ms % DAY_MS == 0
    return lo_ms // DAY_MS, hi_ms // DAY_MS


def _pool_scores(con, lo_day: int, hi_day: int, cap: float) -> dict:
    """Eligible pool (nd≥MIN_ND) with the cap_pnl_per_day metric, formation-window only."""
    return con.execute(f"""
      WITH d AS (
        SELECT wallet,
               (day_closed_pnl - day_fee) * least(1.0, {cap} / day_notional) AS cap_pnl_day
        FROM read_parquet('{CAPDAY}')
        WHERE day_idx >= {lo_day} AND day_idx < {hi_day} AND day_notional > 0
      )
      SELECT wallet, sum(cap_pnl_day) / count(*) AS metric, count(*) AS nd
      FROM d GROUP BY wallet HAVING count(*) >= {MIN_ND}""").fetchnumpy()


def _forward_eval(con, test_month: int, pool: np.ndarray) -> dict:
    """Forward opening-taker episodes (8h markout) for pool wallets, opened in test_month."""
    i = MONTHS.index(test_month)
    lo = as_of_cutoff_ms(MONTHS[i - 1])
    hi = as_of_cutoff_ms(test_month)
    con.register("pool_src", {"wallet": pool.astype(str)})
    con.execute("CREATE OR REPLACE TEMP TABLE poolf AS SELECT * FROM pool_src")
    con.unregister("pool_src")
    # y = raw 8h markout (bps); y_dm = field-demeaned by (coin, ISO-week of entry) over ALL pool episodes
    # that month (a contemporaneous 'vs field' number — removes coin/week beta; the cohort-vs-random
    # comparison is demean-invariant, this just reframes the absolute level).
    d = con.execute(f"""
      WITH e AS (
        SELECT b.wallet, b.raw_markout_8h AS y,
               strftime(make_timestamp(b.entry_bar_ts*1000), '%G%V') AS wk, b.coin
        FROM read_parquet('{BASE_GLOB}', hive_partitioning=false) b
        JOIN poolf p ON b.wallet = p.wallet
        WHERE b.crossed_open AND NOT b.opener_flagged AND NOT b.is_liquidation_close
          AND b.raw_markout_8h IS NOT NULL
          AND b.open_ts >= {lo} AND b.open_ts < {hi})
      SELECT wallet, y, y - avg(y) OVER (PARTITION BY coin, wk) AS y_dm FROM e""").fetchnumpy()
    return d


def _fwd_wallet_means(wallet: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Collapse forward episodes to (unique_wallet, per-wallet mean y) ONCE per fold."""
    uw, inv = np.unique(wallet, return_inverse=True)
    means = np.bincount(inv, weights=y) / np.bincount(inv)
    return uw, means


def run() -> dict:
    if not CAPDAY.exists():
        sys.exit("run `capday_cohort base` first (missing capday_base.parquet)")
    con = _connect()
    rng = np.random.default_rng(SEED)
    test_months = MONTHS[W_MONTHS:]
    report = {"config": {"W_months": W_MONTHS, "K": K, "min_nd": MIN_ND, "cap_sweep": CAP_SWEEP,
                         "test_months": test_months, "n_rand": N_RAND, "seed": SEED,
                         "eval": "raw_markout_8h (dir-signed 8h return, bps) on opening taker episodes",
                         "taker_cost_bp_per_side": TAKER_COST_BP}, "by_cap": {}}
    for cap in CAP_SWEEP:
        coh_we, rnd_we, folds = [], [], {}
        per_wallet_all, per_ep_all, ep_beats = [], [], []
        for T in test_months:
            lo_day, hi_day = _window_days(T)
            pool = _pool_scores(con, lo_day, hi_day, cap)
            if pool["wallet"].size < K:
                folds[str(T)] = {"skip": f"pool {pool['wallet'].size} < K"}
                continue
            order = np.argsort(pool["metric"])[::-1]
            pool_w = pool["wallet"]
            cohort_w = pool_w[order][:K]
            fwd = _forward_eval(con, T, pool_w)
            # per-wallet forward aggregates ONCE, aligned to pool_w: n episodes, Σy, Σy_dm (0 if absent)
            uw, inv = np.unique(fwd["wallet"], return_inverse=True)
            u_n = np.bincount(inv).astype(float)
            u_sy = np.bincount(inv, weights=fwd["y"])
            u_sydm = np.bincount(inv, weights=fwd["y_dm"])
            idx = {w: k for k, w in enumerate(uw.tolist())}
            pk = np.array([idx.get(w, -1) for w in pool_w.tolist()])       # pool_w → uw index, -1 absent
            pres = pk >= 0
            n_al = np.where(pres, u_n[pk.clip(0)], 0.0)
            sy_al = np.where(pres, u_sy[pk.clip(0)], 0.0)
            sydm_al = np.where(pres, u_sydm[pk.clip(0)], 0.0)
            wmean_al = np.where(n_al > 0, sy_al / np.maximum(n_al, 1), np.nan)     # per-wallet mean raw
            wmdm_al = np.where(n_al > 0, sydm_al / np.maximum(n_al, 1), np.nan)    # per-wallet mean demeaned

            cmask = np.isin(pool_w, cohort_w)
            we = wmean_al[cmask & pres]                    # cohort wallet-equal raw
            we_dm = wmdm_al[cmask & pres]                  # cohort wallet-equal demeaned
            ep_raw = (sy_al[cmask].sum() / n_al[cmask].sum()) if n_al[cmask].sum() else np.nan   # episode-equal raw
            ep_dm = (sydm_al[cmask].sum() / n_al[cmask].sum()) if n_al[cmask].sum() else np.nan

            # random-K baselines (BOTH wallet-equal and episode-equal), sampled from the full pool
            P = pool_w.size
            r_we, r_ep = [], []
            for _ in range(N_RAND):
                dr = rng.choice(P, size=K, replace=False)
                m = wmean_al[dr]; m = m[~np.isnan(m)]
                if m.size:
                    r_we.append(float(m.mean()))
                sn = n_al[dr].sum()
                if sn:
                    r_ep.append(float(sy_al[dr].sum() / sn))
            r_we = np.array(r_we); r_ep = np.array(r_ep)
            rnd_we_med = float(np.median(r_we)) if r_we.size else float("nan")
            rnd_ep_med = float(np.median(r_ep)) if r_ep.size else float("nan")
            p_beat_we = ((np.sum(r_we >= we.mean()) + 1) / (r_we.size + 1)) if we.size and r_we.size else float("nan")
            p_beat_ep = ((np.sum(r_ep >= ep_raw) + 1) / (r_ep.size + 1)) if r_ep.size else float("nan")
            folds[str(T)] = {
                "pool": int(P), "n_cohort_fwd_active": int(we.size),
                "cohort_wallet_equal_bp": float(we.mean()) if we.size else None,
                "cohort_wallet_equal_dm_bp": float(we_dm[~np.isnan(we_dm)].mean()) if we_dm.size else None,
                "cohort_episode_equal_bp": float(ep_raw) if np.isfinite(ep_raw) else None,
                "cohort_episode_equal_dm_bp": float(ep_dm) if np.isfinite(ep_dm) else None,
                "n_cohort_episodes": int(n_al[cmask].sum()),
                "random_we_med_bp": rnd_we_med, "p_beat_random_we": p_beat_we,
                "random_ep_med_bp": rnd_ep_med, "p_beat_random_ep": p_beat_ep,
                "beats_random_we": bool(we.size and we.mean() > rnd_we_med),
                "beats_random_ep": bool(np.isfinite(ep_raw) and ep_raw > rnd_ep_med),
            }
            if we.size:                                 # ≥1 cohort wallet trades forward (else fold is uninformative)
                coh_we.append(float(we.mean())); rnd_we.append(rnd_we_med)
                per_wallet_all.append(we)
                per_ep_all.append(float(ep_raw))        # fold-level episode-equal
                ep_beats.append(bool(np.isfinite(ep_raw) and ep_raw > rnd_ep_med))
        pooled = None
        if per_wallet_all:                                             # ≥1 informative fold (we.size>0)
            allw = np.concatenate(per_wallet_all)                       # cohort per-wallet raw means, all folds
            coh_ep = np.array(per_ep_all, dtype=float)
            rnd_ep_folds = [f["random_ep_med_bp"] for f in folds.values()
                            if "skip" not in f and f["cohort_episode_equal_bp"] is not None]
            # bootstrap CI on the pooled wallet-equal mean (wallets resampled)
            bidx = rng.integers(0, allw.size, size=(2000, allw.size))
            boot = allw[bidx].mean(axis=1)
            ci = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))
            pooled = {
                "n_folds": len(coh_we),
                "we_folds_beat_random": int(sum(c > r for c, r in zip(coh_we, rnd_we))),
                "ep_folds_beat_random": int(sum(ep_beats)),
                "mean_cohort_wallet_equal_bp": float(np.mean(coh_we)),
                "mean_random_wallet_equal_bp": float(np.mean(rnd_we)),
                "pooled_wallet_equal_bp": float(allw.mean()), "n_wallet_folds": int(allw.size),
                "pooled_wallet_equal_CI95": ci,
                "mean_cohort_episode_equal_bp": float(np.mean(coh_ep)),
                "mean_random_episode_equal_bp": float(np.mean(rnd_ep_folds)),
                "we_fold_sign_frac_pos": float(np.mean([c > 0 for c in coh_we])),
                "we_fold_sign_p_one_sided": _one_sided_sign_p(np.array(coh_we)),
                "ep_fold_sign_p_one_sided": _one_sided_sign_p(coh_ep),
            }
        report["by_cap"][str(int(cap))] = {"folds": folds, "pooled": pooled}
        if pooled:
            print(f"CAP={cap:>10,.0f}  WE cohort {pooled['mean_cohort_wallet_equal_bp']:+6.2f} vs "
                  f"rand {pooled['mean_random_wallet_equal_bp']:+5.2f} (beat {pooled['we_folds_beat_random']}/{pooled['n_folds']}, "
                  f"p={pooled['we_fold_sign_p_one_sided']:.3f})  |  "
                  f"EP cohort {pooled['mean_cohort_episode_equal_bp']:+6.2f} vs rand "
                  f"{pooled['mean_random_episode_equal_bp']:+5.2f} (beat {pooled['ep_folds_beat_random']}/{pooled['n_folds']})  "
                  f"CI_we{tuple(round(x,1) for x in pooled['pooled_wallet_equal_CI95'])}")
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"-> {OUT}")
    return report


POUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_powered_report.json"


def _fwd_pool_episodes(con, test_month: int, pool: np.ndarray) -> dict:
    """Forward opening-taker episodes for pool wallets, with coin + entry ISO-week for field-neutralization."""
    i = MONTHS.index(test_month)
    lo, hi = as_of_cutoff_ms(MONTHS[i - 1]), as_of_cutoff_ms(test_month)
    con.register("pool_src", {"wallet": pool.astype(str)})
    con.execute("CREATE OR REPLACE TEMP TABLE poolp AS SELECT * FROM pool_src")
    con.unregister("pool_src")
    return con.execute(f"""
      SELECT b.wallet, b.coin,
             strftime(make_timestamp(b.entry_bar_ts*1000), '%G%V') AS wk,
             b.raw_markout_8h AS y
      FROM read_parquet('{BASE_GLOB}', hive_partitioning=false) b
      JOIN poolp p ON b.wallet = p.wallet
      WHERE b.crossed_open AND NOT b.opener_flagged AND NOT b.is_liquidation_close
        AND b.raw_markout_8h IS NOT NULL AND b.open_ts >= {lo} AND b.open_ts < {hi}""").fetchnumpy()


def powered(caps=(500_000.0, 1_000_000.0)) -> dict:
    """The powered evaluation the anti-ratchet rule demands: coin×week field-NEUTRALIZED, episode-level,
    POOLED across all 8 folds, cluster-bootstrap CI by wallet AND by coin×week. Residual = y − (mean y over
    the POOL's episodes in the same coin×entry-week that fold) → strips the +4-5bp pool field beta that
    inflates variance; a cohort residual >0 is the selection premium OVER the field. Selection stays exactly
    the user's spec (formation ≤ T−1). This is the estimand that can actually resolve ±13bp — vs the blind
    8-fold sign test."""
    if not CAPDAY.exists():
        sys.exit("run `capday_cohort base` first")
    con = _connect()
    rng = np.random.default_rng(SEED)
    test_months = MONTHS[W_MONTHS:]
    report = {"config": {"neutralize": "coin×entry-ISO-week field mean over pool episodes, per fold",
                         "pooled_across_folds": True, "caps": list(caps), "seed": SEED}, "by_cap": {}}
    for cap in caps:
        res, resw, cwk, ecoh = [], [], [], []       # cohort episode residual, its wallet, its coin×wk id, and a per-episode flag
        we_res = []                                  # per (fold,wallet) cohort residual means (wallet-equal)
        for T in test_months:
            lo_day, hi_day = _window_days(T)
            pool = _pool_scores(con, lo_day, hi_day, cap)
            if pool["wallet"].size < K:
                continue
            order = np.argsort(pool["metric"])[::-1]
            cohort = set(pool["wallet"][order][:K].tolist())
            ep = _fwd_pool_episodes(con, T, pool["wallet"])
            if ep["wallet"].size == 0:
                continue
            key = np.char.add(ep["coin"].astype(str), ep["wk"].astype(str))
            uk, invk = np.unique(key, return_inverse=True)
            fld = np.bincount(invk, weights=ep["y"]) / np.bincount(invk)   # pool field mean per coin×wk
            resid = ep["y"] - fld[invk]                                    # neutralized episode residual
            cmask = np.isin(ep["wallet"], list(cohort))
            if not cmask.any():
                continue
            res.append(resid[cmask]); resw.append(ep["wallet"][cmask])
            cwk.append(np.char.add(f"{T}|", key[cmask]))                   # global coin×wk id (fold-scoped)
            # wallet-equal residual within fold
            cw, ci_ = np.unique(ep["wallet"][cmask], return_inverse=True)
            we_res.append(np.bincount(ci_, weights=resid[cmask]) / np.bincount(ci_))
        r = np.concatenate(res); rw = np.concatenate(resw); rk = np.concatenate(cwk)
        wq = np.concatenate(we_res)
        # cluster bootstrap by wallet, and by coin×week
        def clus_ci(vals, clus, B=5000):
            uc, inv = np.unique(clus, return_inverse=True)
            groups = [np.flatnonzero(inv == g) for g in range(uc.size)]
            means = np.empty(B)
            for b in range(B):
                pick = rng.integers(0, uc.size, size=uc.size)
                idx = np.concatenate([groups[g] for g in pick])
                means[b] = vals[idx].mean()
            return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
        ci_w = clus_ci(r, rw)
        ci_cw = clus_ci(r, rk)
        report["by_cap"][str(int(cap))] = {
            "n_episodes": int(r.size), "n_wallets": int(np.unique(rw).size),
            "episode_equal_residual_bp": float(r.mean()),
            "episode_equal_net_bp": float(r.mean() - 2 * TAKER_COST_BP),
            "CI95_cluster_wallet": ci_w, "CI95_cluster_coinweek": ci_cw,
            "wallet_equal_residual_bp": float(wq.mean()), "n_wallet_folds": int(wq.size),
        }
        d = report["by_cap"][str(int(cap))]
        print(f"CAP={cap:>10,.0f}  neutralized episode-equal residual {d['episode_equal_residual_bp']:+.2f}bp "
              f"(net {d['episode_equal_net_bp']:+.2f})  CI_wallet{tuple(round(x,1) for x in ci_w)}  "
              f"CI_coinwk{tuple(round(x,1) for x in ci_cw)}  | wallet-equal {d['wallet_equal_residual_bp']:+.2f}bp  "
              f"n_ep={d['n_episodes']} n_w={d['n_wallets']}")
    POUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"-> {POUT}")
    return report


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "base":
        build_capday_base()
    elif cmd == "run":
        run()
    elif cmd == "powered":
        powered()
    else:
        sys.exit(f"unknown cmd {cmd!r} (base|run|powered)")
