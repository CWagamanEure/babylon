"""Step 3a — BLOWUP ANATOMY: is a capped-cohort blowup a predictable wallet trait or a one-trade tail?

The decision gate the user posed. If each bad wallet-fold is destroyed by ONE entry and blowups do NOT
recur across folds, then ex-ante wallet FILTERING cannot work and the right tool is portfolio-level
CONTAINMENT (caps/stops, Step 3b), not prediction. If blowups are persistent (recur, ex-ante fragility
elevated, driven by pyramiding rather than a single tail draw), a fragility filter is worth building.

UNIT = wallet-FOLD (the user's correction: a wallet can be safe one period, fragile another). For each of
the worst wallet-folds in the clean 8h q50 book we compute:
  worst_entry_share   loss from its single worst entry / its total wallet-fold loss
  worst_coin_share    loss from its worst coin / its total wallet-fold loss
  max_overlap         max concurrent open followed positions (entry_ts..entry_ts+8h)
  same_dir_adds       # entries opened while a same-coin,same-dir position was already open (pyramiding)
  signal_vs_size      worst entry's net_bp (signal) and its clip's percentile within the wallet (sizing)
  recurs_in_folds     # OTHER folds where this wallet is itself a bottom-decile wallet-fold
  formation_fragility this wallet-fold's ex-ante formation composite z (elevated BEFORE the test month?)

Reuses the exact leakage-clean book reconstruction (capday_book primitives); nothing is re-derived.

    python -m research.studies.copy_cohort.capday_anatomy
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from .capday_cohort import _window_days
from . import base as basemod
from . import capday_book as cb
from .capday_fragility import _fragility_features, _composite_rank, FEATURES

HORIZON = "8h"
Q = 0.50
N_WORST = 12                      # decompose the worst-N wallet-folds
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_anatomy_report.json"


def _entries():
    """Per followed evaluable entry in the 8h q50 book: wallet, fold, coin, dir, entry_ts, clip, net_usd,
    net_bp. Identical reconstruction to capday_book / capday_diag."""
    con = _connect()
    sel = cb._selection()
    ep = cb._pull_episodes(con, sorted(set().union(*sel.cohorts)))
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64))
    index = cb._row_index(ep, midx)
    clips = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})
    clip = clips[Q]
    rows = cb._rows_for_membership(index, sel.cohorts)
    sizeable = rows[np.isfinite(clip[rows])]
    mk = ep[cb.MK_COL[HORIZON]]
    f = sizeable[np.isfinite(mk[sizeable])]
    net_bp = np.asarray(mk[f], float) - cb.RT_COST_BP
    dir_sign = np.asarray(np.ma.filled(np.ma.asarray(ep["dir_sign"][f]), 0)).astype(int)
    e = dict(wallet=ep["wallet"][f].astype(str), coin=ep["coin"][f].astype(str),
             fold=midx[f].astype(int), ts=np.asarray(ep["ts"][f], np.int64),
             clip=clip[f].astype(float), net_bp=net_bp, net_usd=clip[f].astype(float) * net_bp / 1e4,
             dir=dir_sign,
             clip_all=clip, wallet_all=ep["wallet"].astype(str))     # for within-wallet clip percentile
    return con, sel, e


def _anatomy_of(e, wf_mask) -> dict:
    """Decompose one wallet-fold's followed entries."""
    idx = np.flatnonzero(wf_mask)
    usd = e["net_usd"][idx]; coin = e["coin"][idx]; ts = e["ts"][idx]
    dirn = e["dir"][idx]; clip = e["clip"][idx]; net_bp = e["net_bp"][idx]
    tot = float(usd.sum()); loss = float(-usd[usd < 0].sum())
    # single worst entry
    j = int(np.argmin(usd)); worst_entry_usd = float(usd[j])
    worst_entry_share = float(-worst_entry_usd / loss) if loss > 0 else None
    # worst coin
    uc, ci = np.unique(coin, return_inverse=True)
    coin_usd = np.bincount(ci, weights=usd)
    kc = int(np.argmin(coin_usd)); worst_coin_usd = float(coin_usd[kc])
    worst_coin_share = float(-worst_coin_usd / loss) if loss > 0 else None
    # max concurrent overlap (interval sweep, 8h windows) and same-dir pyramiding adds
    H = cb.HORIZON_MS[HORIZON]
    order = np.argsort(ts)
    starts = ts[order]; ends = ts[order] + H
    # max overlap
    evt = np.r_[starts, ends]; typ = np.r_[np.ones_like(starts), -np.ones_like(ends)]
    so = np.argsort(evt, kind="stable"); max_overlap = int(np.max(np.cumsum(typ[so]))) if evt.size else 0
    # same-coin same-dir adds while already open
    adds = 0
    for a in range(order.size):
        ta, ca, da = starts[a], coin[order][a], dirn[order][a]
        for b in range(a):
            if ends[b] > ta and coin[order][b] == ca and dirn[order][b] == da:
                adds += 1; break
    # signal vs size on the worst entry: its net_bp, and its clip percentile within the WALLET's all clips
    w = e["wallet"][idx][0]
    wclips = e["clip_all"][(e["wallet_all"] == w) & np.isfinite(e["clip_all"])]
    worst_clip_pct = float((wclips <= clip[j]).mean()) if wclips.size else None
    return {"n_entries": int(idx.size), "net_usd": tot, "gross_loss_usd": loss,
            "worst_entry_net_usd": worst_entry_usd, "worst_entry_share_of_loss": worst_entry_share,
            "worst_coin": str(uc[kc]), "worst_coin_share_of_loss": worst_coin_share,
            "max_concurrent_overlap": max_overlap, "same_dir_adds": int(adds),
            "worst_entry_net_bp": float(net_bp[j]), "worst_entry_clip_pctile_in_wallet": worst_clip_pct,
            "worst_entry_clip_usd": float(clip[j])}


def run() -> dict:
    con, sel, e = _entries()
    nF = len(cb.FOLDS)
    # wallet-fold aggregation
    key = np.array([f"{w}|{fo}" for w, fo in zip(e["wallet"], e["fold"])])
    uk, ki = np.unique(key, return_inverse=True)
    wf_usd = np.bincount(ki, weights=e["net_usd"])
    wf_wallet = np.array([k.split("|")[0] for k in uk])
    wf_fold = np.array([int(k.split("|")[1]) for k in uk])
    order = np.argsort(wf_usd)                                    # worst (most negative) first
    # bottom-decile wallet-folds = "blowups"
    n_bottom = max(1, int(np.ceil(0.10 * uk.size)))
    bottom = set(order[:n_bottom].tolist())
    # recurrence: for each wallet, in how many folds is it a bottom-decile wallet-fold
    recur = {}
    for i in order[:n_bottom]:
        recur[wf_wallet[i]] = recur.get(wf_wallet[i], 0) + 1

    # formation fragility composite per wallet-fold (ex-ante)
    feats_folds = [_fragility_features(con, sorted(sel.cohorts[f]), *_window_days(cb.FOLDS[f])) for f in range(nF)]
    comp_folds = [_composite_rank(feats_folds[f], sorted(sel.cohorts[f])) for f in range(nF)]

    worst = []
    for i in order[:N_WORST]:
        w = wf_wallet[i]; fo = wf_fold[i]
        wf_mask = (e["wallet"] == w) & (e["fold"] == fo)
        a = _anatomy_of(e, wf_mask)
        comp = comp_folds[fo].get(w)
        a.update({"wallet": w, "fold_idx": int(fo), "test_month": cb.FOLDS[fo],
                  "recurs_in_bottom_folds": int(recur.get(w, 0)),
                  "wallet_selected_in_folds": int(sum(w in sel.cohorts[ff] for ff in range(nF))),
                  "formation_fragility_z": None if comp is None or not np.isfinite(comp) else float(comp)})
        worst.append(a)

    # aggregate anatomy stats over the bottom-decile blowups
    bl = [worst[j] for j in range(len(worst)) if int(order[j]) in bottom]  # worst N ∩ bottom decile
    def _fracge(key, thr):
        vals = [b[key] for b in bl if b.get(key) is not None]
        return float(np.mean([v >= thr for v in vals])) if vals else None
    single_entry_frac = _fracge("worst_entry_share_of_loss", 0.70)
    single_coin_frac = _fracge("worst_coin_share_of_loss", 0.80)
    recurs_frac = float(np.mean([b["recurs_in_bottom_folds"] >= 2 for b in bl])) if bl else None
    # formation fragility: do blowups have higher ex-ante composite than the rest of the cohort?
    comp_all = np.array([v for cf in comp_folds for v in cf.values() if np.isfinite(v)])
    comp_bl = np.array([b["formation_fragility_z"] for b in bl if b.get("formation_fragility_z") is not None])
    frag_gap = (float(comp_bl.mean()) - float(comp_all.mean())) if comp_bl.size else None

    # winner mirror (is +16.7 accidental concentration in a few large winners?)
    top_w = wf_wallet[np.argmax(wf_usd)]; top_usd = float(wf_usd.max())
    pos = wf_usd[wf_usd > 0]
    top1_share_pos = float(top_usd / pos.sum()) if pos.sum() > 0 else None
    top3_share_pos = float(np.sort(pos)[::-1][:3].sum() / pos.sum()) if pos.sum() > 0 else None

    verdict = ("ONE_TRADE_TAIL (containment > prediction)" if (single_entry_frac and single_entry_frac >= 0.5
               and (recurs_frac is not None and recurs_frac < 0.34))
               else "PERSISTENT_TRAIT (fragility filter viable)" if (recurs_frac and recurs_frac >= 0.5
               and (frag_gap is not None and frag_gap > 0.3))
               else "MIXED / UNDERPOWERED")

    rep = {"config": {"horizon": HORIZON, "q": Q, "unit": "wallet-fold", "n_worst_decomposed": N_WORST,
                      "code_commit": basemod._git_commit()},
           "n_wallet_folds": int(uk.size), "n_bottom_decile": int(n_bottom),
           "wallet_fold_net_usd_quantiles": {q: float(np.quantile(wf_usd, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
           "worst_wallet_folds": worst,
           "aggregate": {"single_entry_ge70pct_of_loss_frac": single_entry_frac,
                         "single_coin_ge80pct_of_loss_frac": single_coin_frac,
                         "blowup_recurs_ge2folds_frac": recurs_frac,
                         "formation_fragility_gap_blowup_minus_pool": frag_gap},
           "winner_concentration": {"top_wallet_fold_net_usd": top_usd,
                                    "top1_share_of_positive": top1_share_pos,
                                    "top3_share_of_positive": top3_share_pos},
           "VERDICT": verdict}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    print(f"\n=== capday 8h q50 BLOWUP ANATOMY (unit=wallet-fold, {uk.size} wallet-folds) ===")
    print(f"wf net_usd q10/25/50/75/90: {[round(np.quantile(wf_usd,q)) for q in (.1,.25,.5,.75,.9)]}")
    print(f"\nworst {N_WORST} wallet-folds:")
    print(f"{'wallet':>10} {'mo':>6} {'net$':>9} {'nE':>3} {'wEntry%':>7} {'wCoin%':>6} {'ovlp':>4} {'adds':>4} {'wBp':>7} {'clipPct':>7} {'recur':>5} {'fragZ':>6}")
    for b in worst:
        print(f"{b['wallet'][:10]:>10} {b['test_month']:>6} {b['net_usd']:>9.0f} {b['n_entries']:>3} "
              f"{'' if b['worst_entry_share_of_loss'] is None else round(b['worst_entry_share_of_loss'],2):>7} "
              f"{'' if b['worst_coin_share_of_loss'] is None else round(b['worst_coin_share_of_loss'],2):>6} "
              f"{b['max_concurrent_overlap']:>4} {b['same_dir_adds']:>4} {b['worst_entry_net_bp']:>7.0f} "
              f"{'' if b['worst_entry_clip_pctile_in_wallet'] is None else round(b['worst_entry_clip_pctile_in_wallet'],2):>7} "
              f"{b['recurs_in_bottom_folds']:>5} "
              f"{'' if b['formation_fragility_z'] is None else round(b['formation_fragility_z'],2):>6}")
    ag = rep["aggregate"]
    print(f"\nAGGREGATE (bottom-decile blowups, n={len(bl)}):")
    print(f"  single worst entry ≥70% of wallet-fold loss : {ag['single_entry_ge70pct_of_loss_frac']}")
    print(f"  single worst coin  ≥80% of loss             : {ag['single_coin_ge80pct_of_loss_frac']}")
    print(f"  blowup recurs in ≥2 folds                   : {ag['blowup_recurs_ge2folds_frac']}")
    print(f"  formation fragility gap (blowup − pool z)    : {ag['formation_fragility_gap_blowup_minus_pool']}")
    wc = rep["winner_concentration"]
    print(f"  winner mirror: top1 {wc['top1_share_of_positive']} / top3 {wc['top3_share_of_positive']} of +PnL")
    print(f"\n>>> VERDICT: {verdict}")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
