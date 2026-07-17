"""V2 SELECTOR BAKEOFF — candidate-ranking only, per V2_BAKEOFF_PREREG.md.

Six frozen formation-side selectors (t_v1, zband, winsor_t, sign_stat, t_noliq, t_notional),
each top-30/fold from the informedness pool minus the frozen-133 wallets, evaluated with the
alt_fresh_validate forward machinery (alt 8h markout, robust spec, wallet-cluster boot).
Folds 202511-202606 are BURNED (reused): results rank paper-trader candidates, never confirm.

    python -m research.studies.copy_cohort.v2_bakeoff
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import REPO_ROOT
from . import lake
from .alt_fresh_validate import (FROZEN, N_BOOT, SEED, _forward_entries, _robust_mask,
                                 _wallet_equal)
from .alt_select import _formation_months

POOL = REPO_ROOT / "data" / "derived" / "copy_cohort" / "informedness"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "v2_bakeoff_report.json"
FOLDS = [202511, 202512, 202601, 202602, 202603, 202604, 202605, 202606]
METHODS = ["t_v1", "zband", "winsor_t", "sign_stat", "t_noliq", "t_notional"]
CAP = 100_000.0
Z_THR = 6.84
TOP_K = 30
PREFILTER = 500
PREFILTER_EXT = 2000
NOTL_MIN = 250.0


# ---------- formation side ----------

def _pool(con, fold: int, excl: set[str]) -> dict[str, np.ndarray]:
    d = con.execute(f"""
        SELECT wallet, nd, t_stat, z FROM read_parquet(
          '{(POOL / f"fold={fold}" / "pool.parquet").as_posix()}')
        WHERE t_stat IS NOT NULL""").fetchnumpy()
    w = d["wallet"].astype(str)
    keep = ~np.isin(w, sorted(excl))
    return {"wallet": w[keep], "nd": np.asarray(d["nd"], float)[keep],
            "t": np.asarray(d["t_stat"], float)[keep], "z": np.asarray(d["z"], float)[keep]}


def _day_rows(con, fold: int, wallets: np.ndarray):
    """Formation wallet-day capped pnl + n_liq for `wallets` (exact _pool_panel day math)."""
    months = _formation_months(fold)
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in months)
    con.execute("CREATE OR REPLACE TEMP TABLE pw AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets.tolist())])
    return con.execute(f"""
        WITH wd AS (
          SELECT r.wallet, r.day,
                 SUM(CAST(r.pnl AS DOUBLE)) - SUM(CAST(r.fee AS DOUBLE)) AS day_pnl,
                 SUM(CAST(r.notional AS DOUBLE))                         AS day_notional,
                 SUM(r.n_liq) AS n_liq
          FROM read_parquet([{globs}]) r JOIN pw USING (wallet)
          GROUP BY r.wallet, r.day)
        SELECT wallet, day_pnl * LEAST(1.0, {CAP} / GREATEST(day_notional, 1e-12)) AS cap_pnl,
               n_liq
        FROM wd""").fetchnumpy()


def _med_notl(con, fold: int, wallets: list[str]) -> dict[str, float]:
    months = _formation_months(fold)
    globs = ",".join(f"'{lake.ope_month_glob(m)}'" for m in months)
    con.execute("CREATE OR REPLACE TEMP TABLE nw AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets)])
    rows = con.execute(f"""
        SELECT o.wallet, median(CAST(o.notl AS DOUBLE)) AS med
        FROM read_parquet([{globs}]) o JOIN nw USING (wallet)
        GROUP BY o.wallet""").fetchall()
    return {w: float(m) for w, m in rows}


def _select_fold(con, fold: int, excl: set[str]) -> tuple[dict[str, list[str]], dict]:
    p = _pool(con, fold, excl)
    w, t, z, nd = p["wallet"], p["t"], p["z"], p["nd"]
    order_t = np.argsort(-t)

    # wallet-day aggregates for the whole (fresh) pool
    dr = _day_rows(con, fold, w)
    dw = dr["wallet"].astype(str)
    cap = np.asarray(dr["cap_pnl"], float)
    nliq_day = np.asarray(dr["n_liq"], float)
    uw, inv = np.unique(dw, return_inverse=True)
    nd_agg = np.bincount(inv).astype(float)
    n_pos = np.bincount(inv, weights=(cap > 0).astype(float))
    n_liq = np.bincount(inv, weights=nliq_day)
    pos_of = dict(zip(uw.tolist(), n_pos.tolist()))
    liq_of = dict(zip(uw.tolist(), n_liq.tolist()))
    nd_of = dict(zip(uw.tolist(), nd_agg.tolist()))
    miss = int((~np.isin(w, uw)).sum())
    ndmis = int(sum(1 for x, n in zip(w, nd) if abs(nd_of.get(x, -1.0) - n) > 0.5))
    if miss or ndmis:
        print(f"  fold {fold}: WARN agg mismatch (missing={miss}, nd_mismatch={ndmis})", flush=True)

    sel: dict[str, list[str]] = {}
    sel["t_v1"] = w[order_t][:TOP_K].tolist()
    mb = z <= Z_THR
    sel["zband"] = w[mb][np.argsort(-t[mb])][:TOP_K].tolist()

    # winsor_t on the registered top-500 prefilter
    grp = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[grp], np.arange(uw.size + 1))
    uidx = {x: j for j, x in enumerate(uw.tolist())}
    pre = set(w[order_t][:PREFILTER].tolist())
    tw = {}
    for x in pre:
        j = uidx.get(x)
        if j is None:
            continue
        s = cap[grp[bounds[j]:bounds[j + 1]]]
        if s.size < 15:
            continue
        lo, hi = np.percentile(s, 5), np.percentile(s, 95)
        sw = np.clip(s, lo, hi)
        sd = sw.std(ddof=1)
        if sd > 0:
            tw[x] = float(sw.mean() / (sd / np.sqrt(sw.size)))
    sel["winsor_t"] = sorted(tw, key=tw.get, reverse=True)[:TOP_K]

    nd_s = np.array([nd_of.get(x, np.nan) for x in w])
    zs = (np.array([pos_of.get(x, np.nan) for x in w]) - nd_s / 2) / np.sqrt(nd_s / 4)
    oks = np.isfinite(zs)
    sel["sign_stat"] = w[oks][np.lexsort((-t[oks], -zs[oks]))][:TOP_K].tolist()

    ml = np.array([liq_of.get(x, 0.0) for x in w]) == 0
    sel["t_noliq"] = w[ml][np.argsort(-t[ml])][:TOP_K].tolist()

    med = _med_notl(con, fold, sorted(pre))
    passers = [x for x in w[order_t][:PREFILTER].tolist() if med.get(x, 0.0) >= NOTL_MIN]
    ext = False
    if len(passers) < TOP_K:
        ext = True
        pre2 = w[order_t][:PREFILTER_EXT].tolist()
        med = _med_notl(con, fold, pre2)
        passers = [x for x in pre2 if med.get(x, 0.0) >= NOTL_MIN]
    sel["t_notional"] = passers[:TOP_K]

    meta = {"pool_size": int(w.size), "n_zband_eligible": int(mb.sum()),
            "n_noliq_eligible": int(ml.sum()), "notional_prefilter_extended": ext,
            "n_notional_passers": len(passers),
            "overlap_with_t_v1": {m: len(set(sel[m]) & set(sel["t_v1"])) for m in METHODS}}
    return sel, meta


# ---------- forward inference (registered spec) ----------

def _boot(mk, wallet, fold, rng):
    """_cluster_boot semantics + one-sided p = (#draws<=0 + 1)/(n_valid + 1)."""
    uw = np.unique(wallet)
    idx = {x: np.flatnonzero(wallet == x) for x in uw}
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        rows = np.concatenate([idx[x] for x in rng.choice(uw, uw.size, replace=True)])
        stats[b] = _wallet_equal(mk[rows], wallet[rows], fold[rows])[0]
    stats = stats[np.isfinite(stats)]
    return {"ci": [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))],
            "p_gt0": float((stats > 0).mean()), "n_valid": int(stats.size),
            "p_one_sided": float(((stats <= 0).sum() + 1) / (stats.size + 1))}


def _infer(e: dict, rng) -> dict:
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
    pt, wf, _ = _wallet_equal(r["mk"], r["wallet"], r["fold"])
    res.update({"n_robust_entries": int(r["mk"].size), "n_robust_wallet_folds": int(wf.size),
                "n_robust_wallets": int(np.unique(r["wallet"]).size),
                "robust_point_bp": pt, "boot": _boot(r["mk"], r["wallet"], r["fold"], rng)})
    key = np.char.add(np.char.add(r["wallet"].astype(str), "|"), r["fold"].astype(str))
    uk, inv = np.unique(key, return_inverse=True)
    wf_mean = np.bincount(inv, weights=r["mk"]) / np.bincount(inv)
    wf_fold = np.array([int(k.split("|")[1]) for k in uk])
    wf_wal = np.array([k.split("|")[0] for k in uk], dtype=object)
    res["per_fold_mean_bp"] = {str(f): float(wf_mean[wf_fold == f].mean())
                               for f in sorted(set(wf_fold.tolist()))}
    res["per_fold_n_wallets"] = {str(f): int((wf_fold == f).sum())
                                 for f in sorted(set(wf_fold.tolist()))}
    loo = {str(x): float(wf_mean[wf_wal != x].mean())
           for x in np.unique(wf_wal) if (wf_wal != x).any()}
    if loo:
        kmin, kmax = min(loo, key=loo.get), max(loo, key=loo.get)
        res["loo"] = {"min_bp": loo[kmin], "min_dropped_wallet": kmin,
                      "max_bp": loo[kmax], "max_dropped_wallet": kmax}
    return res


def _bh(p: list[float]) -> list[float]:
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, p[i] * m / rank)
        adj[i] = prev
    return adj.tolist()


def run():
    old133 = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    con = lake.connect()

    cells = {m: {k: [] for k in ("mk", "wallet", "fold", "notl")} for m in METHODS}
    selections, fold_meta = {}, {}
    for fold in FOLDS:
        print(f"[v2_bakeoff] fold {fold}: selecting ...", flush=True)
        sel, meta = _select_fold(con, fold, old133)
        selections[str(fold)] = sel
        fold_meta[str(fold)] = meta
        union = sorted({x for v in sel.values() for x in v})
        d = _forward_entries(con, fold, union)
        if d is None:
            print(f"  fold {fold}: no ctx, skipped", flush=True)
            continue
        w = d["wallet"].astype(str)
        mk = np.asarray(d["mk"], float)
        ok = np.isfinite(mk)
        for meth in METHODS:
            mem = set(sel[meth])
            m = np.array([x in mem for x in w]) & ok
            cells[meth]["mk"].append(mk[m])
            cells[meth]["wallet"].append(w[m])
            cells[meth]["fold"].append(np.full(int(m.sum()), fold))
            cells[meth]["notl"].append(np.asarray(d["notl"], float)[m])
        print(f"  fold {fold}: union {len(union)} wallets, {int(ok.sum())} priced entries "
              f"| overlap-with-t_v1 {meta['overlap_with_t_v1']}", flush=True)

    rep = {"label": "V2 SELECTOR BAKEOFF — CANDIDATE-RANKING ONLY (burned folds 202511-202606)",
           "prereg": "V2_BAKEOFF_PREREG.md",
           "config": {"folds": FOLDS, "top_k": TOP_K, "z_thr": Z_THR, "cap": CAP,
                      "prefilter": PREFILTER, "notl_min": NOTL_MIN, "seed": SEED,
                      "n_boot": N_BOOT, "exclusion": "frozen-133 removed pre-ranking",
                      "robust_spec": "winsor p95 |mk|, wallet-folds >= 3, wallet-equal"},
           "fold_meta": fold_meta, "selections": selections, "methods": {}}

    p_one = {}
    for i, meth in enumerate(METHODS):
        e = {k: (np.concatenate(v) if v else np.array([])) for k, v in cells[meth].items()}
        res = _infer(e, np.random.default_rng(SEED + 1000 + i))
        if e["mk"].size:
            ms = e["notl"] >= NOTL_MIN
            if ms.sum() >= 5:
                s = _infer({k: e[k][ms] for k in e}, np.random.default_rng(SEED + 2000 + i))
                s.pop("loo", None)
                res["stratum_ge250"] = s
        rep["methods"][meth] = res
        b = res.get("boot")
        p_one[meth] = b["p_one_sided"] if b else 1.0
    adj = _bh([p_one[m] for m in METHODS])
    for i, meth in enumerate(METHODS):
        rep["methods"][meth]["p_one_sided"] = p_one[meth]
        rep["methods"][meth]["p_bh_adj"] = adj[i]

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print("\n=== V2 BAKEOFF (candidate-ranking only; burned folds) ===")
    hdr = (f"{'method':<11} {'robust':>7} {'CI95':>18} {'P>0':>5} {'p1s':>6} {'BHadj':>6} "
           f"{'nent':>6} {'nwal':>5} {'>=250bp':>8}")
    print(hdr)
    for meth in sorted(METHODS, key=lambda m: -(rep["methods"][m].get("robust_point_bp") or -1e9)):
        r = rep["methods"][meth]
        b = r.get("boot") or {}
        ci = b.get("ci") or [float("nan")] * 2
        s = (r.get("stratum_ge250") or {}).get("robust_point_bp")
        print(f"{meth:<11} {r.get('robust_point_bp', float('nan')):>+7.1f} "
              f"[{ci[0]:>+7.1f},{ci[1]:>+7.1f}] {b.get('p_gt0', float('nan')):>5.2f} "
              f"{r['p_one_sided']:>6.3f} {r['p_bh_adj']:>6.3f} {r.get('n_entries', 0):>6} "
              f"{r.get('n_wallets', 0):>5} {(f'{s:+.1f}' if s is not None else '—'):>8}")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
