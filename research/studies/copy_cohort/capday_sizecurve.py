"""Step 3c — SIZE-RESPONSE CURVE + frozen α-sizing curve (does relative clip size carry edge?).

The user's correction to the anatomy: the damaging trade being unusually LARGE is information available at
COPY time, so the question is a trade-level SIZING one, not a wallet blowup classifier. And the containment
sweep already showed equalizing DESTROYS the edge (+16.7→−3.1) while capping only the >q90 tail IMPROVES it —
so size is informative and full equalization throws away the strategy's only edge. This step measures the
edge-vs-size shape directly and tests a frozen family of size transforms, before any containment verdict.

PART 1 — anatomy conditioning controls (fix the mechanical artifacts I over-read):
  worst-entry share and P(worst entry = largest clip) are computed FOR blowups AND ordinary wallet-folds,
  STRATIFIED by entry count (a 1-entry fold trivially has worst=100% and worst=largest). Plus the recurrence
  DENOMINATOR: how many blowup wallets are even evaluable in ≥2 folds (is recurrence measurable at all?).

PART 2 — size-response curve: bucket every evaluable followed entry by its within-wallet clip percentile
  (bottom50 / 50-75 / 75-90 / 90-100 / new-record) and report OOS net 8h markout per bucket with a
  wallet-CLUSTERED CI. Learns whether edge rises with size, plateaus, or size is pure variance.

PART 3 — frozen α-sizing curve: copy_it = notl_it^α · median_it^(1-α)  (median = expanding-prior q50, the
  capday baseline; notl = the wallet's actual position size, known at copy). α∈{0,0.25,0.5,1.0} spans fixed→
  proportional; plus hard caps at the wallet's expanding formation q75/q90/q95. For each: $wtd + two-way CI,
  wallet-equal, ES5% (per-entry net_usd), worst wallet-fold, top-3 winner & loser contribution, frac folds
  positive, and leave-top-3-winners-out $wtd. NONE of these is tuned — the whole grid is reported.

    python -m research.studies.copy_cohort.capday_sizecurve
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
H_MS = cb.HORIZON_MS[HORIZON]
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_sizecurve_report.json"


def _load():
    con = _connect()
    sel = cb._selection()
    ep = cb._pull_episodes(con, sorted(set().union(*sel.cohorts)))
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64)); index = cb._row_index(ep, midx)
    clips = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]},
                                qs=(0.50, 0.75, 0.90, 0.95))
    return con, sel, ep, midx, index, clips


def _evaluable(sel, ep, midx, index, clips):
    """The exact 8h q50 evaluable book rows + aligned per-entry arrays."""
    rows = cb._rows_for_membership(index, sel.cohorts)
    base_clip = clips[0.50]
    sz = rows[np.isfinite(base_clip[rows])]
    mk = ep[cb.MK_COL[HORIZON]]
    ev = sz[np.isfinite(mk[sz])]
    order = np.argsort(np.asarray(ep["ts"][ev], np.int64), kind="stable")   # chronological (for new-record)
    ev = ev[order]
    return {
        "ev": ev,
        "wallet": ep["wallet"][ev].astype(str), "coin": ep["coin"][ev].astype(str),
        "fold": midx[ev].astype(int), "ts": np.asarray(ep["ts"][ev], np.int64),
        "notl": np.asarray(ep["notl"][ev], float), "med": base_clip[ev].astype(float),
        "q75": clips[0.75][ev].astype(float), "q90": clips[0.90][ev].astype(float),
        "q95": clips[0.95][ev].astype(float),
        "net_bp": np.asarray(mk[ev], float) - cb.RT_COST_BP,
    }


# ---------------- PART 1: conditioning controls ----------------
def _conditioning(sel, ep, midx, index, clips) -> dict:
    """worst-entry share & P(worst=largest clip) stratified by entry count; recurrence denominator."""
    rows = cb._rows_for_membership(index, sel.cohorts)
    base_clip = clips[0.50]
    sz = rows[np.isfinite(base_clip[rows])]
    mk = ep[cb.MK_COL[HORIZON]]
    ev = sz[np.isfinite(mk[sz])]
    wal = ep["wallet"][ev].astype(str); fold = midx[ev].astype(int)
    clip = base_clip[ev].astype(float); net_bp = np.asarray(mk[ev], float) - cb.RT_COST_BP
    net_usd = clip * net_bp / 1e4
    key = np.array([f"{w}|{f}" for w, f in zip(wal, fold)])
    uk, ki = np.unique(key, return_inverse=True)
    wf_usd = np.bincount(ki, weights=net_usd)
    n_bottom = max(1, int(np.ceil(0.10 * uk.size)))
    bottom = set(np.argsort(wf_usd)[:n_bottom].tolist())
    # per wallet-fold: n_entries, worst-entry share of loss, worst==largest-clip flag
    strata: dict = {}     # n_entries -> {blowup:[...], other:[...]} of (worst_share, worst_is_largest)
    for u in range(uk.size):
        ii = np.flatnonzero(ki == u)
        usd = net_usd[ii]; cl = clip[ii]
        n = ii.size
        loss = -usd[usd < 0].sum()
        j = int(np.argmin(usd))
        share = float(-usd[j] / loss) if loss > 0 else None
        worst_is_largest = bool(cl[j] == cl.max())
        grp = "blowup" if u in bottom else "other"
        s = strata.setdefault(n, {"blowup": [], "other": []})
        s[grp].append((share, worst_is_largest))
    strat_out = {}
    for n in sorted(strata):
        row = {}
        for grp in ("blowup", "other"):
            vals = strata[n][grp]
            shares = [s for s, _ in vals if s is not None]
            larg = [int(l) for _, l in vals]
            row[grp] = {"n_wf": len(vals),
                        "mean_worst_share": float(np.mean(shares)) if shares else None,
                        "frac_worst_is_largest": float(np.mean(larg)) if larg else None}
        strat_out[str(n)] = row
    # recurrence denominator: for each blowup wallet, in how many folds is it evaluable at all
    wf_wallet = np.array([k.split("|")[0] for k in uk])
    evaluable_folds = {}
    for w in np.unique(wal):
        evaluable_folds[w] = int(len(set(fold[wal == w].tolist())))
    blowup_wallets = [wf_wallet[i] for i in bottom]
    recur_denom = {w: {"n_evaluable_folds": evaluable_folds[w],
                       "n_bottom_folds": int(sum(1 for i in bottom if wf_wallet[i] == w))}
                   for w in set(blowup_wallets)}
    measurable = sum(1 for w, d in recur_denom.items() if d["n_evaluable_folds"] >= 2)
    # IID expectation: P(a wallet evaluable in k folds lands ≥2 bottom) with per-fold prob p=0.10
    p = n_bottom / uk.size
    exp_recur = 0.0
    for w, d in recur_denom.items():
        k = d["n_evaluable_folds"]
        exp_recur += 1 - (1 - p) ** k - k * p * (1 - p) ** (k - 1)      # P(≥2 successes in k)
    return {"n_wallet_folds": int(uk.size), "n_bottom": int(n_bottom),
            "worst_entry_by_entry_count": strat_out,
            "recurrence": {"blowup_wallets": len(set(blowup_wallets)),
                           "measurable_ge2_evaluable_folds": measurable,
                           "observed_recurring_ge2_bottom": int(sum(1 for d in recur_denom.values() if d["n_bottom_folds"] >= 2)),
                           "iid_expected_recurring_ge2": float(exp_recur),
                           "per_wallet": recur_denom}}


# ---------------- PART 2: size-response curve ----------------
def _within_wallet_pct(wallet: np.ndarray, val: np.ndarray) -> np.ndarray:
    """Percentile of each entry's val within its wallet's evaluable entries (0..1)."""
    out = np.zeros(val.size)
    for w in np.unique(wallet):
        m = wallet == w
        v = val[m]
        r = (np.argsort(np.argsort(v)) + 1) / v.size
        out[m] = r
    return out


def _wallet_clustered_ci(net_bp: np.ndarray, wallet: np.ndarray) -> dict:
    return cb._wallet_equal_ci(net_bp, wallet)     # per-wallet mean then wallet-t (co-primary machinery)


def _response_curve(d: dict) -> dict:
    wallet = d["wallet"]; notl = d["notl"]; net_bp = d["net_bp"]; ts = d["ts"]
    pct = _within_wallet_pct(wallet, notl)
    # new-record: notl exceeds all prior (chronological) notl for that wallet
    newrec = np.zeros(notl.size, bool)
    for w in np.unique(wallet):
        m = np.flatnonzero(wallet == w)
        m = m[np.argsort(ts[m], kind="stable")]
        run = -np.inf
        for j in m:
            if notl[j] > run:
                newrec[j] = True
            run = max(run, notl[j])
    buckets = [("bottom50", (pct <= 0.5)), ("p50_75", (pct > 0.5) & (pct <= 0.75)),
               ("p75_90", (pct > 0.75) & (pct <= 0.90)), ("p90_100", (pct > 0.90)),
               ("new_record", newrec)]
    out = {}
    for name, m in buckets:
        if m.sum() == 0:
            out[name] = {"n": 0}; continue
        ci = _wallet_clustered_ci(net_bp[m], wallet[m])
        out[name] = {"n": int(m.sum()), "n_wallets": ci.get("n_wallets"),
                     "mean_net_bp": float(net_bp[m].mean()),
                     "wallet_mean_net_bp": ci.get("point_bp"),
                     "wallet_ci": [ci.get("ci_lo"), ci.get("ci_hi")],
                     "mean_notl_usd": float(notl[m].mean()),
                     "es5_net_bp": float(np.sort(net_bp[m])[:max(1, int(np.ceil(0.05*m.sum())))].mean())}
    return out


# ---------------- PART 3: α-sizing curve + caps ----------------
def _risk(clip: np.ndarray, net_bp: np.ndarray, wallet: np.ndarray, fold: np.ndarray, ts: np.ndarray) -> dict:
    good = np.isfinite(clip) & (clip > 0)
    clip, net_bp, wallet, fold, ts = clip[good], net_bp[good], wallet[good], fold[good], ts[good]
    net_usd = clip * net_bp / 1e4
    turn = clip.sum()
    dollar_bp = float(net_usd.sum() / turn * 1e4) if turn > 0 else None
    exit_day = ((ts + H_MS) // DAY_MS).astype(np.int64)
    week = ((exit_day + 3) // 7).astype(str)
    ci = cb._weighted_twoway_ci(net_bp, clip, wallet, week)
    weq = cb._wallet_equal_ci(net_bp, wallet)
    # wallet-fold contributions
    key = np.array([f"{w}|{f}" for w, f in zip(wallet, fold)])
    uk, ki = np.unique(key, return_inverse=True)
    wf_usd = np.bincount(ki, weights=net_usd)
    pos = wf_usd[wf_usd > 0]; neg = wf_usd[wf_usd < 0]
    top3w = float(np.sort(pos)[::-1][:3].sum() / pos.sum()) if pos.sum() > 0 else None
    top3l = float(np.sort(neg)[:3].sum() / neg.sum()) if neg.sum() < 0 else None
    # leave-top-3-winners-out $wtd
    top3_wf = set(uk[np.argsort(wf_usd)[::-1][:3]].tolist())
    keep = ~np.isin(key, list(top3_wf))
    lto = float(net_usd[keep].sum() / clip[keep].sum() * 1e4) if clip[keep].sum() > 0 else None
    # per-fold positive fraction
    ufo = np.unique(fold); fold_bp = []
    for fo in ufo:
        mm = fold == fo
        fold_bp.append(float(net_usd[mm].sum() / clip[mm].sum() * 1e4) if clip[mm].sum() > 0 else np.nan)
    fold_bp = np.array(fold_bp)
    es5 = float(np.sort(net_usd)[:max(1, int(np.ceil(0.05 * net_usd.size)))].sum())
    return {"dollar_wtd_net_bp": dollar_bp, "two_way_ci": [ci.get("ci_lo"), ci.get("ci_hi")],
            "two_way_se": ci.get("se"), "wallet_equal_net_bp": weq.get("point_bp"),
            "n": int(net_usd.size), "turnover_usd": float(turn),
            "es5_net_usd": es5, "worst_wallet_fold_usd": float(wf_usd.min()),
            "top3_winner_share_pos": top3w, "top3_loser_share_neg": top3l,
            "leave_top3_winners_dollar_bp": lto,
            "frac_folds_positive": float(np.mean(fold_bp[np.isfinite(fold_bp)] > 0)),
            "n_folds_positive": int(np.sum(fold_bp[np.isfinite(fold_bp)] > 0))}


def _alpha_curve(d: dict) -> dict:
    notl, med = d["notl"], d["med"]
    net_bp, wallet, fold, ts = d["net_bp"], d["wallet"], d["fold"], d["ts"]
    r = np.divide(notl, med, out=np.ones_like(notl), where=med > 0)
    out = {}
    for a in (0.0, 0.25, 0.5, 1.0):
        clip = med * np.power(r, a)                # = notl^a · med^(1-a)
        out[f"alpha_{a}"] = _risk(clip, net_bp, wallet, fold, ts)
    for qq, cap in (("q75", d["q75"]), ("q90", d["q90"]), ("q95", d["q95"])):
        clip = np.minimum(notl, np.where(np.isfinite(cap), cap, notl))    # cap actual size at formation qX
        out[f"cap_{qq}"] = _risk(clip, net_bp, wallet, fold, ts)
    # references: pure proportional (notl) and capday baseline (med)
    out["ref_proportional_notl"] = _risk(notl, net_bp, wallet, fold, ts)
    out["ref_baseline_med"] = _risk(med, net_bp, wallet, fold, ts)
    return out


def run() -> dict:
    con, sel, ep, midx, index, clips = _load()
    cond = _conditioning(sel, ep, midx, index, clips)
    d = _evaluable(sel, ep, midx, index, clips)
    curve = _response_curve(d)
    alpha = _alpha_curve(d)
    rep = {"config": {"horizon": HORIZON, "q": Q, "code_commit": basemod._git_commit(),
                      "n_evaluable": int(d["ev"].size)},
           "conditioning_controls": cond, "size_response_curve": curve, "alpha_sizing_curve": alpha}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== PART 1: worst-entry share & P(worst=largest clip) BY ENTRY COUNT (blowup vs other) ===")
    print(f"{'nEnt':>4} | {'#bl':>3} {'blShare':>7} {'blLarg':>6} | {'#oth':>4} {'othShare':>8} {'othLarg':>7}")
    for n, row in cond["worst_entry_by_entry_count"].items():
        b, o = row["blowup"], row["other"]
        print(f"{n:>4} | {b['n_wf']:>3} {_f(b['mean_worst_share'],2):>7} {_f(b['frac_worst_is_largest'],2):>6} | "
              f"{o['n_wf']:>4} {_f(o['mean_worst_share'],2):>8} {_f(o['frac_worst_is_largest'],2):>7}")
    rc = cond["recurrence"]
    print(f"recurrence: {rc['blowup_wallets']} blowup wallets, {rc['measurable_ge2_evaluable_folds']} evaluable in ≥2 folds; "
          f"observed recur≥2={rc['observed_recurring_ge2_bottom']} vs IID-expected={rc['iid_expected_recurring_ge2']:.2f}")

    print(f"\n=== PART 2: SIZE-RESPONSE CURVE (within-wallet clip pctile → OOS 8h net bp) ===")
    print(f"{'bucket':>11} {'n':>4} {'wal':>4} {'meanBp':>7} {'walBp':>7} {'CI_lo':>7} {'CI_hi':>7} {'ES5bp':>7} {'meanNotl':>9}")
    for name, s in curve.items():
        if s.get("n", 0) == 0:
            continue
        ci = s["wallet_ci"]
        print(f"{name:>11} {s['n']:>4} {s['n_wallets']:>4} {_f(s['mean_net_bp'],1):>7} {_f(s['wallet_mean_net_bp'],1):>7} "
              f"{_f(ci[0],1):>7} {_f(ci[1],1):>7} {_f(s['es5_net_bp'],0):>7} {_f(s['mean_notl_usd'],0):>9}")

    print(f"\n=== PART 3: α-SIZING CURVE + CAPS (full risk) ===")
    print(f"{'variant':>20} {'$wtdBp':>7} {'CI_lo':>7} {'CI_hi':>7} {'walEq':>6} {'ES5$':>8} {'worstWF':>8} {'t3win':>6} {'t3los':>6} {'LTO':>7} {'f+':>3}")
    for name, s in alpha.items():
        ci = s["two_way_ci"]
        print(f"{name:>20} {_f(s['dollar_wtd_net_bp'],1):>7} {_f(ci[0],1):>7} {_f(ci[1],1):>7} "
              f"{_f(s['wallet_equal_net_bp'],1):>6} {_f(s['es5_net_usd'],0):>8} {_f(s['worst_wallet_fold_usd'],0):>8} "
              f"{_f(s['top3_winner_share_pos'],2):>6} {_f(s['top3_loser_share_neg'],2):>6} "
              f"{_f(s['leave_top3_winners_dollar_bp'],1):>7} {s['n_folds_positive']:>3}")
    print(f"-> {OUT}")
    return rep


def _f(x, nd=1):
    return "" if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(x, nd)


if __name__ == "__main__":
    run()
