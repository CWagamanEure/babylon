"""Step 3f — FREEZE the entry rule: scale × position-consensus 2×2 interaction (constrained, pre-defined).

Per the user: establish WHO and WHEN to copy before optimizing exits (MAE/MFE) or expanding to alts. One
interaction table, formation-known variables only, no tuning:

  Wallet scale × Position consensus → OOS 8h wallet-equal return
    Large + Yes  = candidate core signal        Large + No  = is scale alone sufficient?
    Small + Yes  = can consensus rescue small?   Small + No  = expected weakest

  PRE-DEFINED (no search):
    scale      = wallet-fold strict-prior 3-mo median opening notional; LARGE = top half WITHIN each fold.
    consensus  = ≥1 OTHER selected wallet already HOLDING the same coin+direction at entry (position-state).
    sizing     = fixed within-wallet (equal per decision); NO source clip-size dependence.
    exit       = fixed 8h (unchanged).  universe = BTC/ETH/SOL (core) reported SEPARATELY from HYPE (reversal).

  PRIMARY: Δ = R(large+consensus) − R(large+no-consensus), paired wallet-cluster bootstrap + fold-by-fold.
  DECISION (frozen): consensus improves large-scale across most folds w/o extreme concentration → freeze
  large+consensus; consensus adds nothing → freeze scale-only; unresolved → freeze the simpler scale-only rule.
  Then alts are EXTERNAL VALIDATION, not more dev data. Do NOT proceed to MAE/MFE until the entry rule is frozen.

    python -m research.studies.copy_cohort.capday_interaction
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import _connect, REPO_ROOT
from . import base as basemod
from . import capday_book as cb

HORIZON = "8h"
CORE = ("BTC", "ETH", "SOL")
N_BOOT = 2000
SEED = 20260714
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "capday_interaction_report.json"


def _entries():
    con = _connect(); sel = cb._selection()
    ep = cb._pull_episodes(con, sorted(set().union(*sel.cohorts)))
    midx = cb._month_idx(np.asarray(ep["open_ts"], np.int64)); index = cb._row_index(ep, midx)
    rows = cb._rows_for_membership(index, sel.cohorts)
    clip = cb._expanding_clips({"wallet": ep["wallet"], "coin": ep["coin"], "ts": ep["ts"], "notl": ep["notl"]})[0.50]
    mk = ep[cb.MK_COL[HORIZON]]
    w = ep["wallet"][rows].astype(str); coin = ep["coin"][rows].astype(str)
    ts = np.asarray(ep["ts"][rows], np.int64); fold = midx[rows]
    dirn = np.asarray(np.ma.filled(np.ma.asarray(ep["dir_sign"][rows]), 0)).astype(int)
    close = np.asarray(ep["close_ts"][rows], float); close = np.where(np.isfinite(close), close, 9e18)
    scale_e = clip[rows]                                    # strict-prior median at entry (leakage-safe scale)
    net = np.asarray(mk[rows], float) - cb.RT_COST_BP
    ev = np.isfinite(clip[rows]) & np.isfinite(mk[rows])
    # position-state consensus: # distinct OTHER cohort wallets holding same coin+dir at entry
    breadth = np.zeros(rows.size, int)
    for i in range(rows.size):
        hold = (coin == coin[i]) & (dirn == dirn[i]) & (fold == fold[i]) & (ts <= ts[i]) & (close > ts[i]) & (w != w[i])
        breadth[i] = len(set(w[hold].tolist()))
    # wallet-fold scale = its expanding median at its FIRST entry; LARGE = top-half within each fold
    key = np.array([f"{a}|{b}" for a, b in zip(w, fold)])
    uk, ki = np.unique(key, return_inverse=True)
    wf_scale = np.array([scale_e[np.flatnonzero(ki == u)[np.argmin(ts[ki == u])]] for u in range(uk.size)])
    wf_fold = np.array([fold[np.flatnonzero(ki == u)[0]] for u in range(uk.size)])
    large_wf = np.zeros(uk.size, bool)
    for f in np.unique(wf_fold):
        m = wf_fold == f
        large_wf[m] = wf_scale[m] >= np.median(wf_scale[m])
    large = large_wf[ki]
    return dict(w=w, coin=coin, fold=fold, net=net, ev=ev, large=large, consensus=(breadth >= 1),
                breadth=breadth, key=key, ki=ki)


def _R(e, mask):
    """Wallet-equal cell return: per wallet-fold mean net bp, then equal mean over wallet-folds."""
    m = mask
    if m.sum() == 0:
        return None, 0, 0
    k = e["key"][m]; uk, ki = np.unique(k, return_inverse=True)
    wf_mean = np.bincount(ki, weights=e["net"][m]) / np.bincount(ki)
    return float(wf_mean.mean()), int(m.sum()), int(uk.size)


def _cell(e, base, label):
    out = {}
    for sc, scname in ((True, "large"), (False, "small")):
        for cons, cname in ((True, "consensus"), (False, "solo")):
            m = base & e["ev"] & (e["large"] == sc) & (e["consensus"] == cons)
            R, n, nwf = _R(e, m)
            # top wallet-fold concentration of positive contribution (guard "extreme concentration")
            conc = None
            if m.sum():
                k = e["key"][m]; uk, ki = np.unique(k, return_inverse=True)
                wf_mean = np.bincount(ki, weights=e["net"][m]) / np.bincount(ki)
                pos = wf_mean[wf_mean > 0]
                conc = float(pos.max() / pos.sum()) if pos.sum() > 0 else None
            out[f"{scname}_{cname}"] = {"R_wallet_equal_bp": R, "n": n, "n_wallet_folds": nwf, "top_wf_share_pos": conc}
    return out


def _paired(e, base, maskA_fn, maskB_fn, rng):
    """Paired wallet-cluster bootstrap of Δ = R(A) − R(B) on cell subsets."""
    sub = base & e["ev"]
    uw = np.unique(e["w"][sub]); idx = {x: np.flatnonzero(sub & (e["w"] == x)) for x in uw}
    d = np.empty(N_BOOT)
    for b in range(N_BOOT):
        rows = np.concatenate([idx[x] for x in rng.choice(uw, size=uw.size, replace=True)])
        eb = {"key": e["key"][rows], "net": e["net"][rows]}
        mA = maskA_fn(e, rows); mB = maskB_fn(e, rows)
        def R(mask):
            if mask.sum() == 0:
                return np.nan
            k = eb["key"][mask]; uk, ki = np.unique(k, return_inverse=True)
            return (np.bincount(ki, weights=eb["net"][mask]) / np.bincount(ki)).mean()
        d[b] = R(mA) - R(mB)
    d = d[np.isfinite(d)]
    return {"delta_bp": float(d.mean()), "ci": [float(np.quantile(d, .025)), float(np.quantile(d, .975))],
            "p_gt0": float((d > 0).mean()), "n_boot_valid": int(d.size)}


def _fold_by_fold(e, base, sc):
    """Per fold: R(large+consensus) − R(large+solo) (sc=True) within `base` universe."""
    out = {}
    for f in sorted(set(e["fold"][base & e["ev"]].tolist())):
        if f < 0:
            continue
        ff = base & e["ev"] & (e["fold"] == f) & (e["large"] == sc)
        Ra, na, _ = _R(e, ff & e["consensus"]); Rb, nb, _ = _R(e, ff & ~e["consensus"])
        out[str(cb.FOLDS[f])] = {"consensus_bp": Ra, "solo_bp": Rb,
                                 "delta_bp": (Ra - Rb) if (Ra is not None and Rb is not None) else None,
                                 "n_cons": na, "n_solo": nb}
    return out


def run():
    e = _entries()
    rng = np.random.default_rng(SEED)
    universes = {"CORE_BTC_ETH_SOL": np.isin(e["coin"], CORE), "HYPE": e["coin"] == "HYPE"}
    rep = {"config": {"horizon": HORIZON, "core": CORE, "n_boot": N_BOOT, "seed": SEED,
                      "scale": "wf strict-prior median notl, LARGE=top-half within fold",
                      "consensus": ">=1 other selected wallet holding same coin+dir at entry (position-state)",
                      "sizing": "wallet-equal (fixed within-wallet)", "exit": "fixed 8h",
                      "code_commit": basemod._git_commit()}, "universes": {}}
    for ui,(uname, base) in enumerate(universes.items()):
        cells = _cell(e, base, uname)
        cA = lambda ee, rows: (ee["large"][rows]) & (ee["consensus"][rows])
        cB = lambda ee, rows: (ee["large"][rows]) & (~ee["consensus"][rows])
        primary = _paired(e, base, cA, cB, np.random.default_rng(SEED + 100*ui))
        # secondary: can consensus rescue small?  and scale main effect (large vs small)
        sA = lambda ee, rows: (~ee["large"][rows]) & (ee["consensus"][rows])
        sB = lambda ee, rows: (~ee["large"][rows]) & (~ee["consensus"][rows])
        rescue = _paired(e, base, sA, sB, np.random.default_rng(SEED + 100*ui + 7))
        lA = lambda ee, rows: ee["large"][rows]
        lB = lambda ee, rows: ~ee["large"][rows]
        scale_main = _paired(e, base, lA, lB, np.random.default_rng(SEED + 100*ui + 13))
        fbf = _fold_by_fold(e, base, True)
        nfolds = sum(1 for v in fbf.values() if v["delta_bp"] is not None)
        nwin = sum(1 for v in fbf.values() if v["delta_bp"] is not None and v["delta_bp"] > 0)
        rep["universes"][uname] = {"cells": cells, "primary_large_consensus_vs_large_solo": primary,
                                   "small_consensus_vs_small_solo": rescue, "scale_main_large_vs_small": scale_main,
                                   "fold_by_fold_large_cons_minus_solo": fbf,
                                   "folds_delta_positive": f"{nwin}/{nfolds}"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2, default=str))

    for uname in universes:
        u = rep["universes"][uname]; c = u["cells"]
        print(f"\n=== {uname} : scale × consensus 2×2 (wallet-equal 8h net bp) ===")
        print(f"{'':>16}{'consensus':>22}{'solo':>22}")
        for sc in ("large", "small"):
            cc = c[f"{sc}_consensus"]; cs = c[f"{sc}_solo"]
            print(f"{sc:>16}{_fmt(cc):>22}{_fmt(cs):>22}")
        p = u["primary_large_consensus_vs_large_solo"]
        print(f"  PRIMARY Δ(large: consensus−solo) = {p['delta_bp']:+.1f}bp CI[{p['ci'][0]:+.1f},{p['ci'][1]:+.1f}] "
              f"P(Δ>0)={p['p_gt0']:.2f} | folds+ {u['folds_delta_positive']}")
        r = u["small_consensus_vs_small_solo"]; s = u["scale_main_large_vs_small"]
        print(f"  small rescue Δ = {r['delta_bp']:+.1f} P(Δ>0)={r['p_gt0']:.2f} | scale main Δ(large−small) = "
              f"{s['delta_bp']:+.1f} P(Δ>0)={s['p_gt0']:.2f}")
    print(f"-> {OUT}")
    return rep


def _fmt(c):
    R = c["R_wallet_equal_bp"]
    return f"{'' if R is None else round(R,1)}bp(n{c['n']}/wf{c['n_wallet_folds']})"


if __name__ == "__main__":
    run()
