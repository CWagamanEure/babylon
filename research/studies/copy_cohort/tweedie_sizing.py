"""Tweedie N-sizing test (descriptive, burned folds): equal-weight top-30 vs theta-weighted book,
and a theta-weighted emergent-N sweep. Answers "did we try the Tweedie sizing" head-on with the
arm-T cohort's REAL forward 8h alt markouts.

theta-weighting is self-truncating (max(theta,0) → ~0 weight for marginal wallets), so pulling the
top-200 by theta per fold captures ~all the weight an emergent-N rule would ever place. Metrics per
scheme: pooled wallet-fold book return (bp), hit rate (% wallet-folds > 0), effective N = (Σw)²/Σw²,
and the single largest wallet weight (concentration). Descriptive only — NOT a selection claim.
"""
from __future__ import annotations

import glob
import json

import numpy as np
import pyarrow.parquet as pq

from research.studies.copy_cohort import alt_fresh_validate as afv
from research.studies.copy_cohort import informed, lake

PULL_TOP = 200  # theta-weighting self-truncates; top-200 by theta captures ~all placed weight


def _wallet_fold_means(con, fold, wallets):
    """Per-(wallet) forward 8h markout means for `wallets` in test month `fold` (robust-masked)."""
    d = afv._forward_entries(con, fold, list(wallets))
    if d is None:
        return {}
    mk = afv._np(d["mk"])
    wal = d["wallet"].astype(str)
    ok = np.isfinite(mk)
    mk, wal = mk[ok], wal[ok]
    if mk.size == 0:
        return {}
    fold_arr = np.full(mk.size, fold)
    mk_w, keep = afv._robust_mask(mk, wal, fold_arr)  # winsor p95 in cell, wf>=3
    mk, wal = mk_w[keep], wal[keep]
    out = {}
    for w in np.unique(wal):
        out[w] = float(mk[wal == w].mean())
    return out


def _book(pairs):
    """pairs: list of (theta, wallet_fold_mean). Returns metrics for equal and theta weighting."""
    th = np.array([p[0] for p in pairs], float)
    r = np.array([p[1] for p in pairs], float)
    n = r.size
    res = {}
    for name, w in (("equal", np.ones(n)), ("theta", np.clip(th, 0, None))):
        if w.sum() <= 0:
            continue
        wn = w / w.sum()
        res[name] = {
            "n_wallet_folds": int(n),
            "book_bp": float(wn @ r),
            "hit_rate": float((r > 0).mean()),
            "hit_rate_wtd": float(wn @ (r > 0).astype(float)),
            "eff_N": float((w.sum() ** 2) / (w ** 2).sum()),
            "max_weight": float(wn.max()),
        }
    return res


def main():
    cohorts = json.load(open("data/derived/copy_cohort/alt_universe_cohorts.json"))
    con = lake.connect(mem="4GB")
    # gather (theta, forward-mean) pairs per fold for the top-PULL_TOP theta wallets
    by_fold = {}
    for pf in sorted(glob.glob("data/derived/copy_cohort/informedness/fold=*/pool.parquet")):
        fold = int(pf.split("fold=")[1].split("/")[0])
        if str(fold) not in cohorts["folds"]:
            continue
        d = pq.read_table(pf).to_pydict()
        z = np.asarray(d["z"], float)
        wal = np.asarray(d["wallet"], object).astype(str)
        theta = informed.two_groups(z)["theta_of"](z)
        order = np.argsort(-theta)[:PULL_TOP]
        cand = {wal[i]: float(theta[i]) for i in order}
        means = _wallet_fold_means(con, fold, list(cand))
        by_fold[fold] = [(cand[w], means[w]) for w in means]  # only wallets with forward entries
        print(f"fold {fold}: {len(cand)} theta-cand, {len(means)} followable")

    # scheme comparison. K = emergent-N proxy: keep top-K by theta among the followable, per fold.
    schemes = {}
    for K in (30, 60, 100, PULL_TOP):
        pooled = []
        for fold, pairs in by_fold.items():
            top = sorted(pairs, key=lambda p: -p[0])[:K]
            pooled.extend(top)
        schemes[f"top{K}"] = _book(pooled)

    report = {"stamp": "descriptive, burned folds 202511-202607, arm-T forward 8h alt markout",
              "pull_top": PULL_TOP, "schemes": schemes,
              "per_fold_followable": {str(k): len(v) for k, v in by_fold.items()}}
    json.dump(report, open("data/derived/copy_cohort/tweedie_sizing_report.json", "w"), indent=1)

    print(f"\n{'scheme':8} {'weighting':9} {'nWF':>5} {'book_bp':>8} {'hit%':>6} {'effN':>6} {'maxWt':>6}")
    for s, r in schemes.items():
        for wname, m in r.items():
            print(f"{s:8} {wname:9} {m['n_wallet_folds']:5d} {m['book_bp']:8.1f} "
                  f"{m['hit_rate']*100:6.1f} {m['eff_N']:6.1f} {m['max_weight']:6.3f}")


if __name__ == "__main__":
    main()
