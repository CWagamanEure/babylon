"""DIAGNOSTIC decay anatomy — arm-T cohort: trader forward persistence x copy forward markout.

Label: DIAGNOSTIC/DESCRIPTIVE. Reuses the 8 validation folds (202511..202606); mechanism
attribution, NOT effect confirmation. No new inference claims.

Per arm-T wallet-fold (alt_universe_cohorts.json, 240 memberships):
  TRADER axis: own forward-month realized capped PnL/day from lake wallet_coin_day for the test
    month, SAME capday formula as selection (day_pnl = SUM(pnl) - SUM(fee) across coins, cap
    factor min(1, 100k/day_notional), divide by active days).
  COPY axis: forward alt 8h markout, wallet-fold mean over evaluable entries (recomputed via
    alt_fresh_validate._forward_entries — same lattice/staleness spec).
Quadrants: TW/TL (trader won/lost) x CW/CL (copy won/lost); buckets for forward-inactive
wallets and wallet-folds with no evaluable copy entries.
Base rate: same forward-own-capday persistence over the FULL eligible pool
(informedness/fold=T/pool.parquet, nd>=15 & sd>0 in formation) with >=1 forward active day.
Feature scan: tsplit_features.parquet medians per quadrant + trader-lost vs trader-won
median-difference permutation p (hypothesis-grade, uncorrected).

    python -m research.studies.copy_cohort.decay_anatomy
"""
from __future__ import annotations

import json

import numpy as np

from research.data.markout import REPO_ROOT
from . import lake
from .alt_fresh_validate import _forward_entries

COHORTS = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_universe_cohorts.json"
INF_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "informedness"
TSPLIT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "tsplit_features.parquet"
OUT_JSON = REPO_ROOT / "data" / "derived" / "copy_cohort" / "decay_anatomy_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "DECAY_ANATOMY.md"
CAP = 100_000.0
SEED = 20260716
N_PERM = 5000
FEATURES = ("f_taker_share", "f_coin_breadth", "f_majors_share", "f_fills_per_day",
            "f_notional_per_day", "f_openflat_per_day", "e_entries_per_day",
            "e_med_notl", "e_p90_notl", "e_dust_share")


def _fwd_capday(con, month: int) -> dict[str, tuple[float, int]]:
    """wallet -> (forward capped pnl/day, active days) for one calendar month, ALL wallets."""
    rows = con.execute(f"""
        WITH wd AS (
          SELECT wallet, day,
                 SUM(CAST(pnl AS DOUBLE)) - SUM(CAST(fee AS DOUBLE)) AS day_pnl,
                 SUM(CAST(notional AS DOUBLE))                       AS day_notional
          FROM read_parquet('{lake.wcd_month_glob(month)}')
          GROUP BY wallet, day
        )
        SELECT wallet,
               avg(day_pnl * LEAST(1.0, {CAP} / GREATEST(day_notional, 1e-12))) AS fwd_capday,
               count(*) AS nd_fwd
        FROM wd GROUP BY wallet""").fetchall()
    return {w: (float(m), int(n)) for w, m, n in rows}


def _median(x) -> float | None:
    x = np.asarray([v for v in x if v is not None and np.isfinite(v)], float)
    return float(np.median(x)) if x.size else None


def run():
    cohorts = json.loads(COHORTS.read_text())
    con = lake.connect()

    # tsplit formation features for arm-T wallet-folds
    ts = con.execute(f"""SELECT * FROM read_parquet('{TSPLIT.as_posix()}')
                         WHERE "group" IN ('T_only', 'T_and_P')""").fetchnumpy()
    ts_key = {(int(f), w): i for i, (f, w) in enumerate(zip(ts["fold"], ts["wallet"].astype(str)))}

    wf = []          # one dict per arm-T wallet-fold
    base_rates = {}  # per-fold eligible-pool forward persistence
    for fold_s, fdef in sorted(cohorts["folds"].items()):
        fold = int(fold_s)
        members = fdef["arms"]["T"]["members"]
        print(f"[decay_anatomy] fold {fold}: fwd capday ...", flush=True)
        fwd = _fwd_capday(con, fold)

        # base rate on the FULL eligible pool (formation nd>=15 & sd>0), >=1 fwd active day
        pool_w = con.execute(f"""SELECT wallet FROM read_parquet(
            '{(INF_DIR / f'fold={fold}' / 'pool.parquet').as_posix()}')""").fetchnumpy()["wallet"].astype(str)
        pool_fwd = np.array([fwd[x][0] for x in pool_w if x in fwd])
        base_rates[fold_s] = {"pool_size": int(pool_w.size), "n_fwd_active": int(pool_fwd.size),
                              "n_fwd_pos": int((pool_fwd > 0).sum()),
                              "persist_rate": float((pool_fwd > 0).mean()) if pool_fwd.size else None,
                              "fwd_capday_median": _median(pool_fwd)}

        print(f"[decay_anatomy] fold {fold}: copy markout ...", flush=True)
        d = _forward_entries(con, fold, sorted(members))
        mk_by_w: dict[str, np.ndarray] = {}
        if d is not None and d["wallet"].size:
            w = d["wallet"].astype(str)
            mk = np.asarray(d["mk"], float)
            ok = np.isfinite(mk)
            for x in np.unique(w[ok]):
                mk_by_w[x] = mk[ok & (w == x)]

        for wal, m in members.items():
            mks = mk_by_w.get(wal)
            fw = fwd.get(wal)
            wf.append({"fold": fold, "wallet": wal,
                       "form_t": m["t"], "form_z": m["z"], "form_nd": m["nd"],
                       "form_capday": m["metric_capday"], "form_scale": m["scale_med_notl"],
                       "fwd_capday": (fw[0] if fw else None), "fwd_nd": (fw[1] if fw else 0),
                       "copy_mk_bp": (float(mks.mean()) if mks is not None else None),
                       "copy_n": (int(mks.size) if mks is not None else 0),
                       "ts_idx": ts_key.get((fold, wal))})

    # ---- quadrant assignment ----
    def quad(r):
        if r["fwd_capday"] is None:
            return "FWD_INACTIVE"
        if r["copy_mk_bp"] is None:
            return "NO_COPY_ENTRIES"
        tw = r["fwd_capday"] > 0
        cw = r["copy_mk_bp"] > 0
        return ("TW_CW" if cw else "TW_CL") if tw else ("TL_CW" if cw else "TL_CL")

    for r in wf:
        r["quadrant"] = quad(r)

    evaluable = [r for r in wf if r["quadrant"] not in ("FWD_INACTIVE", "NO_COPY_ENTRIES")]
    neg_total = sum(r["copy_mk_bp"] for r in evaluable if r["copy_mk_bp"] < 0)  # total drawdown (bp, wf-equal)

    def qstats(rows):
        mk = [r["copy_mk_bp"] for r in rows]
        neg = sum(v for v in mk if v is not None and v < 0)
        mk_v = [v for v in mk if v is not None and np.isfinite(v)]
        s = {"n_wallet_folds": len(rows),
             "copy_mk_mean_bp": (float(np.mean(mk_v)) if mk_v else None),
             "copy_mk_median_bp": _median(mk),
             "copy_mk_sum_bp": (float(sum(mk_v)) if mk_v else None),
             "share_of_copy_drawdown": (neg / neg_total if neg_total < 0 else None),
             "fwd_capday_median": _median([r["fwd_capday"] for r in rows]),
             "formation": {k: _median([r[f"form_{k}"] for r in rows])
                           for k in ("t", "z", "nd", "capday", "scale")},
             "copy_n_median": _median([r["copy_n"] for r in rows])}
        feat = {}
        for f in FEATURES:
            vals = [float(ts[f][r["ts_idx"]]) for r in rows
                    if r["ts_idx"] is not None and ts[f][r["ts_idx"]] is not None
                    and np.isfinite(float(ts[f][r["ts_idx"]]))]
            feat[f] = float(np.median(vals)) if vals else None
        s["feature_medians"] = feat
        return s

    quads = {}
    for q in ("TW_CW", "TW_CL", "TL_CW", "TL_CL", "NO_COPY_ENTRIES", "FWD_INACTIVE"):
        quads[q] = qstats([r for r in wf if r["quadrant"] == q])

    # ---- key numbers ----
    tw = [r for r in wf if r["fwd_capday"] is not None and r["fwd_capday"] > 0]
    tl = [r for r in wf if r["fwd_capday"] is not None and r["fwd_capday"] <= 0]
    active = len(tw) + len(tl)
    tw_mk = [r["copy_mk_bp"] for r in tw if r["copy_mk_bp"] is not None]
    tl_mk = [r["copy_mk_bp"] for r in tl if r["copy_mk_bp"] is not None]
    wedge_dd = quads["TW_CL"]["copy_mk_sum_bp"] or 0.0
    curse_dd = quads["TL_CL"]["copy_mk_sum_bp"] or 0.0

    pool_act = sum(b["n_fwd_active"] for b in base_rates.values())
    pool_pos = sum(b["n_fwd_pos"] for b in base_rates.values())

    key = {
        "cohort_trader_persist_rate": len(tw) / active if active else None,
        "cohort_n_active": active, "cohort_n_inactive": sum(1 for r in wf if r["fwd_capday"] is None),
        "pool_trader_persist_rate": pool_pos / pool_act if pool_act else None,
        "pool_n_active": pool_act,
        "trader_won_copy_mk_mean_bp": float(np.mean(tw_mk)) if tw_mk else None,
        "trader_won_copy_mk_median_bp": _median(tw_mk),
        "trader_lost_copy_mk_mean_bp": float(np.mean(tl_mk)) if tl_mk else None,
        "trader_lost_copy_mk_median_bp": _median(tl_mk),
        "drawdown_bp_sum_total": neg_total,
        "drawdown_share_wedge_TW_CL": (wedge_dd / neg_total if neg_total < 0 else None),
        "drawdown_share_curse_TL_CL": (curse_dd / neg_total if neg_total < 0 else None),
        "cohort_copy_mk_wf_equal_mean_bp": float(np.mean([r["copy_mk_bp"] for r in evaluable])) if evaluable else None,
    }

    # ---- ex-ante feature scan: trader-lost vs trader-won (hypothesis-grade) ----
    rng = np.random.default_rng(SEED)
    scan = {}
    tw_e = [r for r in tw if r["ts_idx"] is not None]
    tl_e = [r for r in tl if r["ts_idx"] is not None]
    form_feats = {"form_t": None, "form_z": None, "form_nd": None, "form_capday": None,
                  "form_scale": None}
    for f in list(FEATURES) + list(form_feats):
        def vals(rows):
            if f.startswith("form_"):
                v = [r[f] for r in rows]
            else:
                v = [float(ts[f][r["ts_idx"]]) for r in rows]
            return np.asarray([x for x in v if x is not None and np.isfinite(x)], float)
        a, b = vals(tl_e if not f.startswith("form_") else tl), vals(tw_e if not f.startswith("form_") else tw)
        if a.size < 5 or b.size < 5:
            continue
        obs = float(np.median(a) - np.median(b))
        pool = np.concatenate([a, b]); na = a.size
        hits = 0
        for _ in range(N_PERM):
            rng.shuffle(pool)
            if abs(np.median(pool[:na]) - np.median(pool[na:])) >= abs(obs):
                hits += 1
        scan[f] = {"median_trader_lost": float(np.median(a)), "median_trader_won": float(np.median(b)),
                   "median_diff_lost_minus_won": obs, "perm_p_two_sided": (hits + 1) / (N_PERM + 1),
                   "n_lost": int(a.size), "n_won": int(b.size)}

    rep = {"label": "DIAGNOSTIC/DESCRIPTIVE — reused folds, mechanism attribution only",
           "config": {"arm": "T", "folds": sorted(cohorts["folds"]), "cap": CAP,
                      "copy_spec": "alt 8h gross dir-signed markout, local asset_ctx mid, <=90s stale, "
                                   "raw wallet-fold mean (no winsor)",
                      "seed": SEED, "n_perm": N_PERM},
           "key_numbers": key,
           "quadrants": quads,
           "base_rate_per_fold": base_rates,
           "feature_scan_trader_lost_vs_won": scan,
           "wallet_folds": [{k: v for k, v in r.items() if k != "ts_idx"} for r in wf]}
    OUT_JSON.write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(key, indent=1))
    print(f"-> {OUT_JSON}")
    return rep


if __name__ == "__main__":
    run()
