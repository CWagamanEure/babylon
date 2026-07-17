"""K-SWEEP x VENUE — registered candidate-ranking grid (CONSTRUCTION_PREREG.md §K-SWEEP).

8 cells: K in {10,30,50,100} top-K by t_stat (informedness pool, frozen-133 excluded)
x venue in {MAJORS, LIQUID_ALT (test-month ADV >= $10M)}. Burned folds 202511-202606.
Entries = test-month flat taker opens (lake open_entries), notl >= $250. Markout = 1h gross
dir-signed vs local asset_ctx mid (backward ASOF <= 90s both ends). Robust spec: winsor p95
within cell, wf >= 3, wallet-fold-equal; wallet-cluster boot 4000, per-cell rng
default_rng(20260716 + 1000*k_idx + venue_idx).

    python -m research.studies.copy_cohort.ksweep
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from .alt_fresh_validate import _ctx_parts, _np, MAJORS, STALE_MS

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
POOL_DIR = DERIVED / "informedness"
FROZEN = DERIVED / "frozen_alt_universe.json"
CACHE = DERIVED / "ksweep"
OUT = DERIVED / "ksweep_report.json"

FOLDS = MONTHS[3:]                     # 202511..202606 (burned)
KS = (10, 30, 50, 100)
VENUES = ("MAJORS", "LIQUID_ALT")
ADV_MIN = 10_000_000.0
NOTL_MIN = 250.0
H1_MS = 3_600_000
N_BOOT = 4000
SEED = 20260716
CAL_DAYS = 242                         # calendar days in the 8 fold months


def _top100(fold: int, frozen: set[str]) -> list[str]:
    import duckdb
    con = duckdb.connect()
    d = con.execute(f"""SELECT wallet, t_stat
                        FROM read_parquet('{(POOL_DIR / f'fold={fold}' / 'pool.parquet').as_posix()}')
                        WHERE t_stat IS NOT NULL""").fetchnumpy()
    con.close()
    w = d["wallet"].astype(str)
    t = np.asarray(d["t_stat"], float)
    keep = np.array([x not in frozen for x in w])
    w, t = w[keep], t[keep]
    order = np.lexsort((w, -t))        # t_stat desc, wallet asc tie-break (deterministic)
    return w[order[:100]].tolist()


def _fold_pull(con, fold: int, wallets: list[str]):
    """Cache (per fold): ADV per coin (test month) + top-100 entries with 1h markout."""
    CACHE.mkdir(parents=True, exist_ok=True)
    advp = CACHE / f"adv_{fold}.parquet"
    entp = CACHE / f"entries_{fold}.parquet"
    if not advp.exists():
        con.execute(f"""COPY (
            SELECT coin, SUM(CAST(notional AS DOUBLE)) / 2 / COUNT(DISTINCT day) AS adv
            FROM read_parquet('{lake.wcd_month_glob(fold)}') GROUP BY coin
        ) TO '{advp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: ADV cached", flush=True)
    if not entp.exists():
        ctx_list = ",".join(f"'{p}'" for p in _ctx_parts(fold))
        con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT UNNEST(?) AS wallet, "
                    "UNNEST(?) AS rk", [wallets, list(range(len(wallets)))])
        con.execute(f"""COPY (
            WITH ent AS (
              SELECT o.wallet, cw.rk, o.coin, o.ts, o.dir_sign, CAST(o.notl AS DOUBLE) AS notl
              FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
              WHERE CAST(o.notl AS DOUBLE) >= {NOTL_MIN}
            ),
            ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL),
            p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS px0_ts
                   FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts),
            p1 AS (SELECT p0.*, c.mid_px AS px1, c.ts AS px1_ts
                   FROM p0 ASOF LEFT JOIN ctx c ON p0.coin = c.coin AND (p0.ts + {H1_MS}) >= c.ts)
            SELECT wallet, rk, coin, ts, notl,
                   CASE WHEN px0 IS NOT NULL AND px1 IS NOT NULL AND px0 > 0
                          AND (ts - px0_ts) <= {STALE_MS} AND ((ts + {H1_MS}) - px1_ts) <= {STALE_MS}
                        THEN dir_sign * (px1 - px0) / px0 * 1e4 END AS mk
            FROM p1
        ) TO '{entp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: entries cached", flush=True)
    import duckdb
    lc = duckdb.connect()
    adv = {c: float(a) for c, a in lc.execute(
        f"SELECT coin, adv FROM read_parquet('{advp.as_posix()}')").fetchall()}
    d = lc.execute(f"SELECT * FROM read_parquet('{entp.as_posix()}')").fetchnumpy()
    lc.close()
    return adv, d


def _cell_inference(mk, wallet, fold, rng):
    """Registered robust spec on one cell; returns dict + per-fold signs."""
    n_eval = int(mk.size)
    out = {"n_entries": n_eval, "n_wallets_covered": int(np.unique(wallet).size) if n_eval else 0}
    if n_eval == 0:
        return out
    wf_key = np.char.add(np.char.add(wallet, "|"), fold.astype(str))
    out["n_wf_covered"] = int(np.unique(wf_key).size)
    # raw wallet-fold-equal point
    uk, inv = np.unique(wf_key, return_inverse=True)
    out["raw_point_bp"] = float((np.bincount(inv, weights=mk) / np.bincount(inv)).mean())
    # robust: winsor p95 |mk| in cell, keep wf with >=3 evaluable entries
    lim = float(np.percentile(np.abs(mk), 95))
    mk_w = np.clip(mk, -lim, lim)
    cnt = np.bincount(inv)
    keep = cnt[inv] >= 3
    if not keep.any():
        out["robust"] = None
        return out
    uk2, inv2 = np.unique(wf_key[keep], return_inverse=True)
    wf_mean = np.bincount(inv2, weights=mk_w[keep]) / np.bincount(inv2)
    wf_wal = np.array([k.split("|")[0] for k in uk2])
    wf_fold = np.array([int(k.split("|")[1]) for k in uk2])
    out["n_robust_entries"] = int(keep.sum())
    out["n_robust_wf"] = int(uk2.size)
    out["robust_point_bp"] = float(wf_mean.mean())
    # wallet-cluster bootstrap on wf means (clusters = wallets; identical statistic)
    uw, winv = np.unique(wf_wal, return_inverse=True)
    s = np.bincount(winv, weights=wf_mean)          # sum of wf means per wallet
    c = np.bincount(winv).astype(float)             # n wf per wallet
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        m = np.bincount(rng.integers(0, uw.size, uw.size), minlength=uw.size)
        stats[b] = (m @ s) / (m @ c)
    stats = stats[np.isfinite(stats)]
    out["ci"] = [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))]
    out["p_gt0"] = float((stats > 0).mean())
    # per-fold signs of the robust per-fold mean
    pf = {}
    for f in FOLDS:
        m = wf_fold == f
        pf[str(f)] = (float(wf_mean[m].mean()) if m.any() else None)
    out["per_fold_mean_bp"] = pf
    signs = [v for v in pf.values() if v is not None]
    out["per_fold_signs"] = f"{sum(1 for v in signs if v > 0)}/{len(signs)} folds > 0"
    out["entries_per_day"] = round(n_eval / CAL_DAYS, 2)
    return out


def run():
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    con = lake.connect()
    rows = {k: [] for k in ("mk", "wallet", "fold", "coin", "rk", "liq_alt")}
    n_sel_wf = 0
    for f in FOLDS:
        top = _top100(f, frozen)
        n_sel_wf += len(top)
        adv, d = _fold_pull(con, f, top)
        mk = _np(d["mk"])          # masked->NaN guard (audit 2026-07-17); never bare asarray
        ok = np.isfinite(mk)
        coin = d["coin"].astype(str)[ok]
        rows["mk"].append(mk[ok])
        rows["wallet"].append(d["wallet"].astype(str)[ok])
        rows["fold"].append(np.full(ok.sum(), f))
        rows["coin"].append(coin)
        rows["rk"].append(_np(d["rk"], int)[ok])
        is_major = np.isin(coin, MAJORS)
        rows["liq_alt"].append(~is_major & np.array([adv.get(c, 0.0) >= ADV_MIN for c in coin]))
        print(f"  fold {f}: {ok.sum():,} evaluable entries "
              f"({(~is_major).sum():,} alt, {rows['liq_alt'][-1].sum():,} liquid-alt)", flush=True)
    e = {k: np.concatenate(v) for k, v in rows.items()}

    rep = {"config": {"prereg": "CONSTRUCTION_PREREG.md §K-SWEEP x VENUE", "stamp":
                      "CANDIDATE-RANKING, burned folds 202511-202606", "ks": list(KS),
                      "venues": list(VENUES), "adv_min": ADV_MIN, "notl_min": NOTL_MIN,
                      "horizon": "1h", "basis": "asset_ctx mid (gross); ~1bp follower lag "
                      "haircut per lag_haircut_report.json (3s slip mean -1.3bp)",
                      "adv_lookahead": "test-month ADV (mild liquidity look-ahead; "
                      "deployment uses trailing ADV)",
                      "robust_spec": "winsor p95 in cell, wf>=3, wallet-fold-equal",
                      "n_boot": N_BOOT, "seed": SEED, "cal_days": CAL_DAYS,
                      "code_commit": lake.git_describe(),
                      "audit_2026_07_17": "masked->NaN markout guard (weighted cluster boot "
                                          "here was already multiplicity-correct)"},
           "cells": {}}
    for ki, K in enumerate(KS):
        in_k = e["rk"] < K
        for vi, venue in enumerate(VENUES):
            vm = np.isin(e["coin"], MAJORS) if venue == "MAJORS" else e["liq_alt"]
            m = in_k & vm
            rng = np.random.default_rng(SEED + 1000 * ki + vi)
            cell = _cell_inference(e["mk"][m], e["wallet"][m], e["fold"][m], rng)
            cell["n_selected_wf"] = 8 * K
            rep["cells"][f"K{K}/{venue}"] = cell
            b = cell.get("robust_point_bp")
            ci = cell.get("ci", [None, None])
            print(f"K={K:>3} {venue:<10} n={cell['n_entries']:>6,} wal={cell.get('n_wallets_covered', 0):>3} "
                  f"robust={'' if b is None else f'{b:+.1f}'}bp "
                  f"CI[{ci[0]:+.1f},{ci[1]:+.1f}] P(>0)={cell.get('p_gt0', float('nan')):.3f} "
                  f"{cell.get('per_fold_signs', '')} e/d={cell.get('entries_per_day')}"
                  if b is not None else f"K={K:>3} {venue:<10} n={cell['n_entries']} (no robust wf)",
                  flush=True)

    # K-frontier: efficient K per venue = max robust/CI-half-width s.t. entries/day >= 1
    rep["k_frontier"] = {}
    for venue in VENUES:
        front = {}
        best, best_score = None, -np.inf
        for K in KS:
            c = rep["cells"][f"K{K}/{venue}"]
            b, ci = c.get("robust_point_bp"), c.get("ci")
            if b is None or ci is None:
                continue
            hw = (ci[1] - ci[0]) / 2
            score = b / hw if hw > 0 else None
            front[f"K{K}"] = {"robust_bp": b, "ci_half_width": hw, "score": score,
                              "entries_per_day": c.get("entries_per_day")}
            if score is not None and c.get("entries_per_day", 0) >= 1 and score > best_score:
                best, best_score = K, score
        rep["k_frontier"][venue] = {"per_k": front, "efficient_K": best}
        print(f"frontier {venue}: efficient K = {best}", flush=True)

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
