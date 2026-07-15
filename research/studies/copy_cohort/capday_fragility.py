"""Step 3 — ex-ante fragility filter on the capday top-30 cohort (8h q50 book).

Step 1 established the capday book's wide CI is CONCENTRATED_BLOWUPS, not broad weakness: the median
wallet is +3.1bp, worst-5-of-46 wallets carry 72% of gross loss, dropping them lifts +16.7→+42.6bp, and
the blowups are IDIOSYNCRATIC (crash-corr −0.02 to the field). NECESSARY condition for a fragility filter
is met. This step tests the SUFFICIENT condition the user named: are the blowups EX-ANTE predictable from
formation-window behaviour, WITHOUT overfitting?

Design (pre-registered, no γ tuned — the anti-overfit stance the user demanded):
  FEATURES (formation window only, day_idx < cutoff — strictly pre-test; from capday_base wallet×day PnL):
    es_tail   = |mean of worst-decile daily net PnL| / mean daily notional     (tail-loss magnitude)
    pnl_hhi   = Σ (|cap_pnl_day| / Σ|cap_pnl_day|)²                              (PnL made on few days)
    loss_pers = longest consecutive losing-day streak / active days             (loss persistence)
    dd_recov  = max drawdown of cum daily net PnL / (|window net PnL| + eps)     (drawdown depth vs gain)
    notl_cv   = std(daily notional) / mean(daily notional)                       (sizing instability)
  COMPOSITE = mean of within-fold z-scores (equal weight — NO fitted γ). Higher ⇒ more fragile.
  RULE (frozen): from each fold's top-30, EXCLUDE the worst-quintile (6) by composite → 24-wallet cohort;
        run the identical 8h q50 leakage-clean book (capday_book._book).

Honesty gates (both required before any positive verdict):
  (1) RANDOM-EXCLUSION NULL — drop a random 6-of-30 each fold, N times; the fragility book must beat the
      random-exclusion band. Removing ANY 6 wallets tends to help a fat-tailed book; only beating random
      exclusion shows the blowups were ex-ante IDENTIFIED, not just that fewer trades = thinner tail.
  (2) HELD-OUT FOLDS — report lift on dev folds (first half) vs held-out folds (second half). Nothing is
      fit, so a real signal must appear on the folds too; a dev-only lift = overfit rule.
  Plus a descriptive univariate: ex-ante fragility rank vs realized OOS per-wallet net_usd (Spearman).

    python -m research.studies.copy_cohort.capday_fragility
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from research.lib.stats import t_ppf
from .capday_cohort import _window_days, CAPDAY
from . import base as basemod
from . import capday_book as cb

HORIZON = "8h"
Q = 0.50
DROP_FRAC = 0.20                 # exclude worst quintile (pre-registered, not tuned)
N_RANDEX = 1000                  # random-exclusion null draws
SEED = 20260714
FEATURES = ("es_tail", "pnl_hhi", "loss_pers", "dd_recov", "notl_cv")
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_fragility_report.json"


def _fragility_features(con, wallets: list[str], lo_day: int, hi_day: int) -> dict:
    """Per wallet, the formation-window fragility features from capday_base (wallet×day PnL). Strictly
    pre-cutoff (day_idx < hi_day). Returns {wallet: {feat: value}} for wallets with ≥3 active days."""
    if not wallets:
        return {}
    con.register("frw_src", {"wallet": np.asarray(wallets, dtype=str)})
    con.execute("CREATE OR REPLACE TEMP TABLE frw AS SELECT DISTINCT wallet FROM frw_src")
    con.unregister("frw_src")
    d = con.execute(f"""
      SELECT b.wallet, b.day_idx,
             (b.day_closed_pnl - b.day_fee)                          AS net,
             b.day_notional                                          AS notl,
             (b.day_closed_pnl - b.day_fee) * least(1.0, {cb.CAP} / b.day_notional) AS capday
      FROM read_parquet('{CAPDAY}') b JOIN frw ON b.wallet = frw.wallet
      WHERE b.day_idx >= {lo_day} AND b.day_idx < {hi_day} AND b.day_notional > 0
      ORDER BY b.wallet, b.day_idx""").fetchnumpy()
    # A9-style leak guard: no formation feature may read a day at/after the cutoff.
    if d["day_idx"].size:
        assert int(np.asarray(d["day_idx"]).max()) < hi_day, "fragility leak: formation day >= cutoff"
    w = d["wallet"].astype(str)
    out: dict = {}
    for u in np.unique(w):
        m = w == u
        net = np.asarray(d["net"][m], float)
        notl = np.asarray(d["notl"][m], float)
        capday = np.asarray(d["capday"][m], float)
        nd = net.size
        if nd < 3:
            continue
        # tail-loss: mean of the worst decile of daily net PnL (≥1 day), normalized by typical notional
        k = max(1, int(np.ceil(0.10 * nd)))
        worst = np.sort(net)[:k]
        es_tail = float(-worst.mean() / (notl.mean() + 1e-9))          # positive = deeper loss tail
        # PnL concentration across days (Herfindahl of |capped daily PnL|)
        a = np.abs(capday); s = a.sum()
        pnl_hhi = float(((a / s) ** 2).sum()) if s > 0 else 1.0
        # loss persistence: longest consecutive losing-day run / active days
        neg = (net < 0).astype(int)
        best = cur = 0
        for x in neg:
            cur = cur + 1 if x else 0
            best = max(best, cur)
        loss_pers = float(best / nd)
        # drawdown recovery: max drawdown of cumulative net PnL vs window gain
        eq = np.cumsum(net); dd = float((np.maximum.accumulate(np.r_[0.0, eq]) - np.r_[0.0, eq]).max())
        dd_recov = float(dd / (abs(eq[-1]) + 1e-9))
        # notional instability
        notl_cv = float(notl.std(ddof=0) / (notl.mean() + 1e-9))
        out[str(u)] = {"es_tail": es_tail, "pnl_hhi": pnl_hhi, "loss_pers": loss_pers,
                       "dd_recov": dd_recov, "notl_cv": notl_cv, "nd": int(nd)}
    return out


def _composite_rank(feats_by_w: dict, cohort: list[str]) -> dict:
    """Within-fold equal-weight z-score composite over the cohort wallets that HAVE features.
    Returns {wallet: composite}; wallets without formation features get +inf (treated most-fragile:
    a top-30 wallet with too little history to characterize is conservatively droppable)."""
    have = [w for w in cohort if w in feats_by_w]
    comp: dict = {}
    if len(have) >= 3:
        mat = np.array([[feats_by_w[w][f] for f in FEATURES] for w in have], float)
        mu = mat.mean(0); sd = mat.std(0, ddof=0)
        z = (mat - mu) / np.where(sd > 0, sd, 1.0)
        c = z.mean(1)
        for w, v in zip(have, c):
            comp[w] = float(v)
    else:
        for w in have:
            comp[w] = 0.0
    for w in cohort:
        if w not in comp:
            comp[w] = float("inf")                 # no formation features -> most fragile
    return comp


def _filtered_cohorts(sel, feats_folds: list) -> tuple[list, list]:
    """Per fold: drop the worst-quintile-fragile wallets. Returns (filtered_cohorts, excluded_per_fold)."""
    filt, excluded = [], []
    for f, cohort in enumerate(sel.cohorts):
        cl = sorted(cohort)
        comp = _composite_rank(feats_folds[f], cl)
        ndrop = max(1, int(round(DROP_FRAC * len(cl))))
        order = sorted(cl, key=lambda w: (-comp[w], w))       # most-fragile first, deterministic tiebreak
        drop = set(order[:ndrop])
        filt.append(set(cohort) - drop)
        excluded.append(sorted(drop))
    return filt, excluded


def _book_bp(con, ep, clips, index, cal_lo, cal_hi, cohorts) -> dict:
    b = cb._book(ep, clips[Q], index, cohorts, HORIZON, cal_lo, cal_hi)
    wq = b.get("wallet_equal_net_bp", {}); ci = b.get("absolute_weighted_ci", {})
    return {"dollar_wtd_net_bp": b.get("dollar_wtd_net_bp"), "n_evaluable": b["n_evaluable"],
            "n_wallets": b.get("n_wallets"), "two_way_ci": [ci.get("ci_lo"), ci.get("ci_hi")],
            "two_way_se": ci.get("se"), "wallet_equal_net_bp": wq.get("point_bp"),
            "win_rate": b.get("win_rate"), "leave_one_wallet_min": b.get("leave_one_wallet_net_bp_min"),
            "daily_sharpe": b.get("daily_sharpe")}


def _book_bp_light(ep, clips, index, cal_lo, cal_hi, cohorts) -> float:
    b = cb._book(ep, clips[Q], index, cohorts, HORIZON, cal_lo, cal_hi, light=True)
    return b.get("dollar_wtd_net_bp")


def _split_book(con, ep, clips, index, folds_idx, cohorts) -> dict:
    """Book restricted to a subset of folds (dev vs held-out generalization)."""
    sub = [c if i in folds_idx else set() for i, c in enumerate(cohorts)]
    cal_lo, cal_hi = cb._cal_bounds(ep, cb._month_idx(np.asarray(ep["open_ts"], np.int64)), HORIZON)
    return _book_bp(con, ep, clips, index, cal_lo, cal_hi, sub)


def run() -> dict:
    con = _connect()
    sel = cb._selection()
    # formation fragility features per fold (strictly pre-cutoff)
    feats_folds = []
    for f, T in enumerate(cb.FOLDS):
        lo_day, hi_day = _window_days(T)
        feats_folds.append(_fragility_features(con, sorted(sel.cohorts[f]), lo_day, hi_day))
    filt_cohorts, excluded = _filtered_cohorts(sel, feats_folds)
    for f, T in enumerate(cb.FOLDS):
        print(f"fold {T}: cohort={len(sel.cohorts[f])} -> filtered={len(filt_cohorts[f])} "
              f"(dropped {len(excluded[f])})", flush=True)

    # pull episodes for baseline ∪ filtered ∪ random-exclusion universe = just the baseline cohort union
    used = sorted(set().union(*sel.cohorts))
    ep = cb._pull_episodes(con, used)
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64)); index = cb._row_index(ep, midx)
    clips = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})
    cal_lo, cal_hi = cb._cal_bounds(ep, midx, HORIZON)

    base = _book_bp(con, ep, clips, index, cal_lo, cal_hi, sel.cohorts)
    frag = _book_bp(con, ep, clips, index, cal_lo, cal_hi, filt_cohorts)

    # ---- (1) random-exclusion null: drop a random ndrop-of-cohort each fold, N times
    rng = np.random.default_rng(SEED)
    ndrops = [max(1, int(round(DROP_FRAC * len(c)))) for c in sel.cohorts]
    rand_bp = []
    for _ in range(N_RANDEX):
        rc = []
        for f, cohort in enumerate(sel.cohorts):
            cl = list(cohort)
            drop = set(rng.choice(cl, size=min(ndrops[f], len(cl)), replace=False)) if cl else set()
            rc.append(set(cohort) - drop)
        v = _book_bp_light(ep, clips, index, cal_lo, cal_hi, rc)
        if v is not None:
            rand_bp.append(v)
    rand_bp = np.array(rand_bp, float)
    frag_pt = frag["dollar_wtd_net_bp"]
    rand_rank = float((1 + np.sum(rand_bp >= frag_pt)) / (rand_bp.size + 1)) if (frag_pt is not None and rand_bp.size) else None

    # ---- (2) held-out folds: dev = first half, test = second half (nothing is fit; must generalize)
    nF = len(cb.FOLDS); half = nF // 2
    dev_idx, test_idx = set(range(half)), set(range(half, nF))
    dev_base = _split_book(con, ep, clips, index, dev_idx, sel.cohorts)
    dev_frag = _split_book(con, ep, clips, index, dev_idx, filt_cohorts)
    test_base = _split_book(con, ep, clips, index, test_idx, sel.cohorts)
    test_frag = _split_book(con, ep, clips, index, test_idx, filt_cohorts)

    # ---- descriptive univariate: ex-ante fragility composite vs realized OOS per-wallet net_usd
    #   (does the composite actually rank the realized blowups? Spearman over cohort wallets that traded)
    rows = cb._rows_for_membership(index, sel.cohorts)
    sizeable = rows[np.isfinite(clips[Q][rows])]
    mk = ep[cb.MK_COL[HORIZON]]
    fev = sizeable[np.isfinite(mk[sizeable])]
    if fev.size:
        w_ev = ep["wallet"][fev].astype(str)
        net_usd = clips[Q][fev] * (np.asarray(mk[fev], float) - cb.RT_COST_BP) / 1e4
        # realized net_usd per (fold,wallet) matched to that fold's ex-ante composite
        fold_ev = midx[fev]
        comp_ev, real_ev = [], []
        for f in range(nF):
            comp_f = _composite_rank(feats_folds[f], sorted(sel.cohorts[f]))
            sel_mask = fold_ev == f
            for w in np.unique(w_ev[sel_mask]):
                if w in comp_f and np.isfinite(comp_f[w]):
                    comp_ev.append(comp_f[w]); real_ev.append(float(net_usd[sel_mask][w_ev[sel_mask] == w].sum()))
        comp_ev = np.array(comp_ev); real_ev = np.array(real_ev)
        if comp_ev.size >= 5:
            rc = np.argsort(np.argsort(comp_ev)); rr = np.argsort(np.argsort(real_ev))
            spearman = float(np.corrcoef(rc, rr)[0, 1])   # want NEGATIVE: high fragility -> low realized
        else:
            spearman = None
    else:
        spearman, comp_ev = None, np.array([])

    # ---- per-feature univariate direction (descriptive)
    feat_spear = {}
    if fev.size and comp_ev.size >= 5:
        for fi, fname in enumerate(FEATURES):
            xv, yv = [], []
            for f in range(nF):
                comp_f = feats_folds[f]
                sel_mask = midx[fev] == f
                for w in np.unique(ep["wallet"][fev][sel_mask].astype(str)):
                    if w in comp_f:
                        xv.append(comp_f[w][fname])
                        yv.append(float((clips[Q][fev][sel_mask] *
                                  (np.asarray(mk[fev][sel_mask], float) - cb.RT_COST_BP) / 1e4)
                                  [ep["wallet"][fev][sel_mask].astype(str) == w].sum()))
            xv, yv = np.array(xv), np.array(yv)
            if xv.size >= 5 and xv.std() > 0:
                feat_spear[fname] = float(np.corrcoef(np.argsort(np.argsort(xv)),
                                                      np.argsort(np.argsort(yv)))[0, 1])

    rep = {
        "config": {"horizon": HORIZON, "q": Q, "drop_frac": DROP_FRAC, "features": FEATURES,
                   "n_randex": N_RANDEX, "seed": SEED, "code_commit": basemod._git_commit(),
                   "rule": "exclude worst-quintile fragility composite (equal-weight z, NO fitted gamma)"},
        "excluded_per_fold": {str(T): excluded[f] for f, T in enumerate(cb.FOLDS)},
        "baseline_book": base, "fragility_book": frag,
        "lift_bp": (frag["dollar_wtd_net_bp"] - base["dollar_wtd_net_bp"])
        if (frag["dollar_wtd_net_bp"] is not None and base["dollar_wtd_net_bp"] is not None) else None,
        "random_exclusion_null": {
            "n_draws": int(rand_bp.size), "median_bp": float(np.median(rand_bp)) if rand_bp.size else None,
            "p90_bp": float(np.quantile(rand_bp, 0.9)) if rand_bp.size else None,
            "baseline_bp": base["dollar_wtd_net_bp"], "fragility_bp": frag_pt,
            "fragility_rank_vs_random": rand_rank,
            "rank_NOTE": "frac of random-exclusion books >= fragility book; SMALL = fragility beats random exclusion"},
        "held_out": {"dev_folds": sorted(dev_idx), "test_folds": sorted(test_idx),
                     "dev": {"baseline": dev_base["dollar_wtd_net_bp"], "fragility": dev_frag["dollar_wtd_net_bp"]},
                     "test": {"baseline": test_base["dollar_wtd_net_bp"], "fragility": test_frag["dollar_wtd_net_bp"]}},
        "univariate": {"composite_spearman_vs_realized_net_usd": spearman,
                       "per_feature_spearman": feat_spear,
                       "NOTE": "NEGATIVE spearman = higher ex-ante fragility -> lower realized OOS PnL (desired)"},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== capday 8h q50 fragility filter (drop worst {int(DROP_FRAC*100)}% by ex-ante composite) ===")
    print(f"baseline : $wtd {base['dollar_wtd_net_bp']:+.1f}bp CI[{base['two_way_ci'][0]:.1f},{base['two_way_ci'][1]:.1f}] "
          f"wal-eq {base['wallet_equal_net_bp']:+.1f} n={base['n_evaluable']} wal={base['n_wallets']} loo_min={base['leave_one_wallet_min']:+.1f}")
    print(f"fragility: $wtd {frag['dollar_wtd_net_bp']:+.1f}bp CI[{frag['two_way_ci'][0]:.1f},{frag['two_way_ci'][1]:.1f}] "
          f"wal-eq {frag['wallet_equal_net_bp']:+.1f} n={frag['n_evaluable']} wal={frag['n_wallets']} loo_min={frag['leave_one_wallet_min']:+.1f}")
    print(f"lift = {rep['lift_bp']:+.1f}bp")
    print(f"\n(1) RANDOM-EXCLUSION NULL (drop random {int(DROP_FRAC*100)}%): random median {rep['random_exclusion_null']['median_bp']:+.1f}bp "
          f"p90 {rep['random_exclusion_null']['p90_bp']:+.1f} | fragility {frag_pt:+.1f} rank={rand_rank}")
    print(f"(2) HELD-OUT: dev base {dev_base['dollar_wtd_net_bp']:+.1f}->frag {dev_frag['dollar_wtd_net_bp']:+.1f} | "
          f"TEST base {test_base['dollar_wtd_net_bp']:+.1f}->frag {test_frag['dollar_wtd_net_bp']:+.1f}")
    print(f"univariate composite Spearman vs realized net_usd = {spearman} (want NEGATIVE)")
    print(f"per-feature Spearman: {feat_spear}")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
