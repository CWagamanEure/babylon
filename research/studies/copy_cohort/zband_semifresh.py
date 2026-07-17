"""SEMI-FRESH ROBUSTNESS PROBE — z-band hypothesis on wallets the hypothesis never saw.

⚠️ NOT a registered confirmation: the z <= 6.84 threshold was derived from THESE months'
forward returns (TSPLIT_HYPOTHESIS.md); only the *wallets* are new. Same-regime caveat applies.

Per fold 202511..202606, from informedness/fold=T/pool.parquet:
  BAND cell:       eligible wallets with z <= 6.84, top-30 by t_stat desc
  COMPLEMENT cell: eligible wallets with z >  6.84, top-30 by t_stat desc
then EXCLUDE (a) that fold's original arm-T or arm-P top-30 (alt_universe_cohorts.json)
and (b) the 133 frozen wallets (frozen_alt_universe.json). Forward-month ALT 8h markout
exactly as alt_fresh_validate (its functions imported): local asset_ctx, <=90s staleness,
robust spec = winsor p95 |mk| + wallet-folds >= 3, wallet-equal, 4000-rep wallet-cluster boot.

    python -m research.studies.copy_cohort.zband_semifresh
"""
from __future__ import annotations

import glob
import json

import numpy as np

from research.data.markout import REPO_ROOT
from . import lake
from .alt_fresh_validate import (COHORTS, FROZEN, SEED, _cluster_boot, _forward_entries,
                                 _robust_mask, _wallet_equal)

Z_THR = 6.84
TOP_K = 30
FOLDS = [202511, 202512, 202601, 202602, 202603, 202604, 202605, 202606]
POOL = REPO_ROOT / "data" / "derived" / "copy_cohort" / "informedness"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "zband_semifresh_report.json"


def _select(con, fold: int, excl: set[str]) -> dict[str, list[str]]:
    d = con.execute(f"""
        SELECT wallet, t_stat, z
        FROM read_parquet('{(POOL / f"fold={fold}" / "pool.parquet").as_posix()}')
        WHERE t_stat IS NOT NULL AND z IS NOT NULL""").fetchnumpy()
    w, t, z = d["wallet"].astype(str), np.asarray(d["t_stat"], float), np.asarray(d["z"], float)
    out = {}
    for name, m in (("band", z <= Z_THR), ("complement", z > Z_THR)):
        ranked = w[m][np.argsort(-t[m])]
        top = ranked[:TOP_K]
        out[name] = [x for x in top.tolist() if x not in excl]
        # secondary (deviation, labeled): top-30 AFTER exclusion, so the cell can't be
        # vacated purely by overlap with the original arms
        out[name + "_post"] = [x for x in ranked.tolist() if x not in excl][:TOP_K]
    return out


def _infer(e: dict, rng) -> dict:
    """Robust-spec inference for one cell (mirrors alt_fresh_validate semantics)."""
    n = int(e["mk"].size)
    if n == 0:
        return {"n_entries": 0}
    raw_pt, _, _ = _wallet_equal(e["mk"], e["wallet"], e["fold"])
    mk_w, keep = _robust_mask(e["mk"], e["wallet"], e["fold"])
    r = {k: e[k][keep] for k in e}
    r["mk"] = mk_w[keep]
    res = {"n_entries": n, "n_wallets": int(np.unique(e["wallet"]).size),
           "n_folds": int(np.unique(e["fold"]).size), "raw_point_bp": raw_pt}
    if r["mk"].size == 0:
        res["robust"] = None
        return res
    pt, wf, wf_wal = _wallet_equal(r["mk"], r["wallet"], r["fold"])
    res.update({"n_robust_entries": int(r["mk"].size),
                "n_robust_wallet_folds": int(wf.size),
                "n_robust_wallets": int(np.unique(r["wallet"]).size),
                "robust_point_bp": pt,
                "boot": _cluster_boot(r["mk"], r["wallet"], r["fold"], rng)})
    # per-fold means of robust wallet-fold means
    key = np.char.add(np.char.add(r["wallet"].astype(str), "|"), r["fold"].astype(str))
    uk, inv = np.unique(key, return_inverse=True)
    wf_mean = np.bincount(inv, weights=r["mk"]) / np.bincount(inv)
    wf_fold = np.array([int(k.split("|")[1]) for k in uk])
    wf_wallet = np.array([k.split("|")[0] for k in uk], dtype=object)
    res["per_fold_mean_bp"] = {str(f): float(wf_mean[wf_fold == f].mean())
                               for f in sorted(set(wf_fold.tolist()))}
    res["per_fold_n_wallets"] = {str(f): int((wf_fold == f).sum())
                                 for f in sorted(set(wf_fold.tolist()))}
    # leave-one-wallet-out on the robust wallet-equal point
    loo = {}
    for wl in np.unique(wf_wallet):
        m = wf_wallet != wl
        if m.any():
            loo[str(wl)] = float(wf_mean[m].mean())
    if loo:
        kmin = min(loo, key=loo.get)
        kmax = max(loo, key=loo.get)
        res["loo"] = {"min_bp": loo[kmin], "min_dropped_wallet": kmin,
                      "max_bp": loo[kmax], "max_dropped_wallet": kmax}
    return res


def run():
    cohorts = json.loads(COHORTS.read_text())
    old133 = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    con = lake.connect()

    cell_names = ("band", "complement", "band_post", "complement_post")
    cells = {c: {k: [] for k in ("mk", "wallet", "fold", "coin", "notl")} for c in cell_names}
    selection = {}
    for fold in FOLDS:
        f = cohorts["folds"][str(fold)]
        arm_tp = set(f["arms"]["T"]["members"]) | set(f["arms"]["P"]["members"])
        sel = _select(con, fold, arm_tp | old133)
        selection[str(fold)] = {c: len(sel[c]) for c in sel}
        union = sorted({x for c in cell_names for x in sel[c]})
        if not union:
            print(f"  fold {fold}: no semi-fresh wallets survive exclusion", flush=True)
            continue
        d = _forward_entries(con, fold, union)
        if d is None:
            print(f"  fold {fold}: no ctx, skipped", flush=True)
            continue
        w = d["wallet"].astype(str)
        mk = np.asarray(d["mk"], float)
        ok = np.isfinite(mk)
        for c in cell_names:
            mem = set(sel[c])
            m = np.array([x in mem for x in w]) & ok
            cells[c]["mk"].append(mk[m])
            cells[c]["wallet"].append(w[m])
            cells[c]["fold"].append(np.full(int(m.sum()), fold))
            cells[c]["coin"].append(d["coin"].astype(str)[m])
            cells[c]["notl"].append(np.asarray(d["notl"], float)[m])
        print(f"  fold {fold}: band {len(sel['band'])} wallets, "
              f"complement {len(sel['complement'])} wallets, {int(ok.sum())} priced entries", flush=True)

    rep = {"label": "SEMI-FRESH ROBUSTNESS PROBE",
           "caveat": ("z<=6.84 threshold derived from these months' forward returns "
                      "(TSPLIT_HYPOTHESIS.md); wallets are new but regime is not — "
                      "NOT a registered out-of-sample confirmation."),
           "config": {"z_threshold": Z_THR, "top_k": TOP_K, "folds": FOLDS, "seed": SEED,
                      "n_boot": 4000, "exclusions": "fold arm-T/arm-P top-30 + frozen 133",
                      "robust_spec": "winsor p95 |mk|, wallet-folds >= 3, wallet-equal"},
           "selection_per_fold": selection, "cells": {}}
    rep["config"]["cells_note"] = ("band/complement = spec cells (top-30 first, then exclude); "
                                   "*_post = labeled deviation, top-30 taken AFTER exclusion so the "
                                   "complement isn't vacated by arm-T/P overlap")
    for i, c in enumerate(cell_names):
        e = {k: (np.concatenate(v) if v else np.array([])) for k, v in cells[c].items()}
        rng = np.random.default_rng(SEED + 100 + i)
        res = _infer(e, rng)
        # notional strata (robust point on the stratum, like alt_fresh_validate)
        if e["mk"].size:
            res["notional_strata"] = {}
            for thr in (250.0, 1000.0):
                m = e["notl"] >= thr
                if m.sum() >= 5:
                    s = _infer({k: e[k][m] for k in e}, np.random.default_rng(SEED + 200 + i))
                    res["notional_strata"][f">=${int(thr)}"] = {
                        "n_entries": s["n_entries"], "n_wallets": s.get("n_wallets"),
                        "raw_point_bp": s.get("raw_point_bp"),
                        "robust_point_bp": s.get("robust_point_bp"),
                        "boot": s.get("boot")}
        rep["cells"][c] = res

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print("\n=== SEMI-FRESH z-band probe ===")
    for c in cell_names:
        r = rep["cells"][c]
        b = r.get("boot") or {}
        ci = b.get("ci") or [None, None]
        print(f"{c}: n={r.get('n_entries')} wallets={r.get('n_wallets')} folds={r.get('n_folds')} | "
              f"robust {r.get('robust_point_bp')} CI[{ci[0]},{ci[1]}] P(>0)={b.get('p_gt0')} "
              f"(raw {r.get('raw_point_bp')})")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
