"""Step 3b — CONTAINMENT benchmark: make blowups harmless with ex-ante sizing/risk rules (no prediction).

The anatomy (Step 3a) said the capday book's tails are ONE-TRADE realizations: blowups don't recur (0%),
aren't ex-ante fragile (+0.10z), and are dominated by a single entry that is the WALLET'S LARGEST clip.
Symmetrically the +16.7bp dollar book is carried by a few large winners (top-3 wallet-folds = 48% of +PnL).
So the lever is robust SIZING, not wallet prediction. Each rule below is implementable ex-ante and needs no
identification of the future loser:

  baseline            expanding q50 prior-notional clip (the capday_book sizing)
  equal_per_entry     every followed entry the same notional (kills clip concentration)
  equal_per_walletfold each wallet-fold equal total notional, split across its entries (capacity equalize)
  clip_cap_q75/q90    cap each clip at the pool qX of evaluable clips (chop the oversized worst entries)
  wallet_cap_q75      scale each wallet-fold's clips so its total ≤ q75 of per-wallet-fold totals
  dd_stop_Mx          per wallet-fold, chronological: after copied cum-PnL draws M×median-clip below peak,
                      stop following that wallet for the rest of the fold (live risk control)

Each variant re-books through the IDENTICAL leakage-clean 8h q50 machine (capday_book._book) — only the clip
vector changes — and reports $wtd + two-way wallet×wk CI, WALLET-EQUAL, leave-one-out, Sharpe, plus the
per-fold paired lift. The read is the PATTERN across rules (not the max): does robust sizing (a) tighten the
CI / lift loo above zero, and (b) reconcile the dollar book with wallet-equal — i.e. is the edge capacity-
weighting or accidental concentration?

    python -m research.studies.copy_cohort.capday_caps
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from . import base as basemod
from . import capday_book as cb

HORIZON = "8h"
Q = 0.50
DAY_MS = cb.DAY_MS
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_caps_report.json"


def _summary(b: dict) -> dict:
    wq = b.get("wallet_equal_net_bp", {}); ci = b.get("absolute_weighted_ci", {})
    return {"dollar_wtd_net_bp": b.get("dollar_wtd_net_bp"), "n_evaluable": b["n_evaluable"],
            "n_wallets": b.get("n_wallets"), "turnover_usd": b.get("evaluable_turnover_usd"),
            "two_way_ci": [ci.get("ci_lo"), ci.get("ci_hi")], "two_way_se": ci.get("se"),
            "wallet_equal_net_bp": wq.get("point_bp"), "wallet_equal_ci": [wq.get("ci_lo"), wq.get("ci_hi")],
            "win_rate": b.get("win_rate"), "daily_sharpe": b.get("daily_sharpe"),
            "leave_one_wallet_min": b.get("leave_one_wallet_net_bp_min"),
            "top_wallet_share_pos": b.get("top_wallet_share_positive_pnl")}


def run() -> dict:
    con = _connect()
    sel = cb._selection()
    ep = cb._pull_episodes(con, sorted(set().union(*sel.cohorts)))
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64)); index = cb._row_index(ep, midx)
    clips = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})
    base_clip = clips[Q]
    cal_lo, cal_hi = cb._cal_bounds(ep, midx, HORIZON)
    mk = ep[cb.MK_COL[HORIZON]]

    # sizeable book rows (finite base clip) — the population sizing rules act on
    rows = cb._rows_for_membership(index, sel.cohorts)
    sz = rows[np.isfinite(base_clip[rows])]
    wal = ep["wallet"][sz].astype(str); fold = midx[sz].astype(int)
    ts = np.asarray(ep["ts"][sz], np.int64); c0 = base_clip[sz].astype(float)
    wf = np.array([f"{w}|{f}" for w, f in zip(wal, fold)])
    med_clip = float(np.median(c0))

    def _clip_from(vec_sz: np.ndarray) -> np.ndarray:
        """Embed a per-sizeable-row clip vector back into a full-length clip array (others = base)."""
        out = base_clip.copy().astype(float)
        out[sz] = vec_sz
        return out

    variants: dict = {}
    variants["baseline"] = base_clip
    # equal notional per entry
    variants["equal_per_entry"] = _clip_from(np.full(sz.size, med_clip))
    # equal notional per wallet-fold (total med_clip*n_entries_in_wf split equally = same total, equal within)
    uwf, wi = np.unique(wf, return_inverse=True)
    n_in_wf = np.bincount(wi).astype(float)
    tot_target = med_clip * uwf.size                      # each wf gets med_clip total? -> per-entry = med/n
    variants["equal_per_walletfold"] = _clip_from(med_clip / n_in_wf[wi])
    # clip caps at pool quantiles of evaluable clips
    for qq in (0.75, 0.90):
        cap = float(np.quantile(c0, qq))
        variants[f"clip_cap_q{int(qq*100)}"] = _clip_from(np.minimum(c0, cap))
    # per-wallet-fold total cap: scale each wf's clips so its total ≤ q75 of per-wf totals
    wf_tot = np.bincount(wi, weights=c0)
    cap_tot = float(np.quantile(wf_tot, 0.75))
    scale = np.minimum(1.0, cap_tot / np.maximum(wf_tot, 1e-9))[wi]
    variants["wallet_cap_q75"] = _clip_from(c0 * scale)
    # drawdown stop: per wf, chronological by entry ts; copied net at 8h exit; after cum drops
    # M*median-clip below running peak, zero the wf's later entries.
    net_bp_sz = np.where(np.isfinite(mk[sz]), np.asarray(mk[sz], float) - cb.RT_COST_BP, 0.0)
    for M in (3,):
        keep = np.ones(sz.size, bool)
        for u in range(uwf.size):
            ii = np.flatnonzero(wi == u)
            ii = ii[np.argsort(ts[ii])]
            cum = peak = 0.0; stopped = False
            thr = M * med_clip
            for j in ii:
                if stopped:
                    keep[j] = False; continue
                pnl = c0[j] * net_bp_sz[j] / 1e4
                cum += pnl; peak = max(peak, cum)
                if peak - cum > thr:
                    stopped = True                        # stop AFTER this entry realizes
        v = c0.copy(); v[~keep] = 0.0
        variants[f"dd_stop_{M}x"] = _clip_from(v)

    # book each variant (full), + per-fold paired lift vs baseline
    def _book_full(clip):
        return cb._book(ep, clip, index, sel.cohorts, HORIZON, cal_lo, cal_hi)

    def _fold_bp(clip):
        out = []
        for fo in range(len(cb.FOLDS)):
            b = cb._book(ep, clip, index, cb._one_fold(sel.cohorts, fo), HORIZON, cal_lo, cal_hi, light=True)
            out.append(b.get("dollar_wtd_net_bp"))
        return out

    base_folds = _fold_bp(variants["baseline"])
    results = {}
    for name, clip in variants.items():
        b = _book_full(clip)
        s = _summary(b)
        fb = _fold_bp(clip)
        wins = sum(1 for a, c in zip(fb, base_folds)
                   if a is not None and c is not None and a > c)
        s["fold_net_bp"] = fb
        s["folds_beat_baseline"] = wins
        results[name] = s

    rep = {"config": {"horizon": HORIZON, "q": Q, "median_clip_usd": med_clip,
                      "code_commit": basemod._git_commit(),
                      "NOTE": "sizing rules are ex-ante; only the clip vector changes; same book machine"},
           "variants": results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== capday 8h CONTAINMENT benchmark (median clip ${med_clip:,.0f}) ===")
    print(f"{'variant':>21} {'$wtd':>7} {'CI_lo':>7} {'CI_hi':>7} {'wal-eq':>7} {'loo':>7} {'shrp':>5} {'topW%':>6} {'n':>4} {'f>base':>6}")
    for name, s in results.items():
        ci = s["two_way_ci"]
        print(f"{name:>21} {_f(s['dollar_wtd_net_bp']):>7} {_f(ci[0]):>7} {_f(ci[1]):>7} "
              f"{_f(s['wallet_equal_net_bp']):>7} {_f(s['leave_one_wallet_min']):>7} "
              f"{_f(s['daily_sharpe'],2):>5} {_f(s['top_wallet_share_pos'],2):>6} "
              f"{s['n_evaluable']:>4} {s['folds_beat_baseline']:>6}")
    print(f"-> {OUT}")
    return rep


def _f(x, nd=1):
    return "" if x is None else round(x, nd)


if __name__ == "__main__":
    run()
