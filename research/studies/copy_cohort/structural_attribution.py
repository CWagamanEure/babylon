"""WALLET ATTRIBUTION for the frozen STRUCTURAL_TOPN cohort (burned folds, descriptive).

Question (user, 2026-07-21): are the cohort's persistent draggers structurally different traders
(pre-filterable) rather than winner's-curse noise? Tests: (1) drag PERSISTENCE across folds
(noise does not repeat; structure does); (2) formation-feature separation draggers vs helpers;
(3) individual dossiers for the top draggers (what are they actually doing).

Book under attribution = the frozen PRIMARY (long-only top-30) plus both-sides views for context.
Any screen suggested here is a PREREG AMENDMENT candidate (timing-stamped), never a silent edit.

    python -m research.studies.copy_cohort.structural_attribution
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from .tape_capday_filter import CACHE, DERIVED, RT_COST_BP, _np
from .structural_knives import BOT_MAX_FILLS_DAY, FEATS, _pct
from .tape_metric_sweep import FOLDS, SWEEP_V

OUT = DERIVED / "structural_attribution_report.json"
FEAT_COLS = ("metric_cap", "nd", "f_max_dd_usd", "f_trades_per_day", "f_turnover",
             "f_med_entry_notl", "f_maker_share", "f_hold_proxy_min", "f_coin_hhi",
             "f_top_coin_pnl_share", "f_pct_prof_days", "f_mean_daily_pnl", "f_consistency",
             "f_clip_lumpiness", "f_ret_autocorr", "f_mk_8h", "f_ls_gap_8h",
             "f_entry_consensus", "n_form_entries")


def _cohort(d):
    w = d["wallet"]
    elig = np.isfinite(d["metric_cap"]) & (d["metric_cap"] > 0) \
        & (d["f_trades_per_day"] < BOT_MAX_FILLS_DAY)
    comp = np.nanmean(np.column_stack(
        [_pct(np.where(elig, d[FEATS[k][0]] * FEATS[k][1], np.nan)) for k in FEATS]), axis=1)
    order = np.argsort(-np.where(np.isfinite(comp), comp, -np.inf))
    return w[order[:30]].tolist(), comp


def run():
    rows = []                                   # one row per (wallet, fold)
    for f in FOLDS:
        lc = duckdb.connect()
        d = lc.execute(f"SELECT * FROM read_parquet("
                       f"'{(CACHE / f'sweep_feat_{f}_{SWEEP_V}.parquet').as_posix()}')").fetchnumpy()
        e = lc.execute(f"""SELECT wallet, coin, ts, dir_sign, notional, mk_8h,
                           close_gap_min FROM read_parquet(
            '{(CACHE / f'sweep_ent_{f}_{SWEEP_V}.parquet').as_posix()}')
            WHERE notional >= 250 AND mk_8h IS NOT NULL""").fetchnumpy()
        lc.close()
        d = {k: (v.astype(str) if k == "wallet" else _np(v)) for k, v in d.items()}
        top, comp = _cohort(d)
        ew = e["wallet"].astype(str)
        mk, dirn = _np(e["mk_8h"]), _np(e["dir_sign"])
        coin, ts, notl = e["coin"].astype(str), _np(e["ts"]), _np(e["notional"])
        cg = _np(e["close_gap_min"])
        w2i = {x: i for i, x in enumerate(d["wallet"])}
        for rank, w in enumerate(top):
            m = ew == w
            ml = m & (dirn > 0)
            row = {"wallet": w, "fold": f, "rank": rank,
                   "score": float(comp[w2i[w]]),
                   "n_entries_all": int(m.sum()), "n_entries_long": int(ml.sum())}
            for c in FEAT_COLS:
                v = d[c][w2i[w]]
                row[c] = None if not np.isfinite(v) else float(v)
            if ml.any():
                row |= {"mk8_long": float(mk[ml].mean()),
                        "pnl_long_usd": float(((mk[ml] - RT_COST_BP) / 1e4 * 1000).sum()),
                        "hit_long": float((mk[ml] > 0).mean())}
            if m.any():
                days = (ts[m] // 86_400_000).astype(int)
                row |= {"mk8_all": float(mk[m].mean()),
                        "short_share_test": float((dirn[m] < 0).mean()),
                        "mk8_short": (float(mk[m & (dirn < 0)].mean())
                                      if (m & (dirn < 0)).any() else None),
                        "hype_share_test": float((coin[m] == "HYPE").mean()),
                        "test_notl_med": float(np.median(notl[m])),
                        "test_close_gap_med_min": (float(np.nanmedian(cg[m]))
                                                   if np.isfinite(cg[m]).any() else None),
                        "test_entries_per_day": float(m.sum() / np.unique(days).size),
                        "test_hour_med_utc": float(np.median((ts[m] // 3_600_000) % 24))}
            rows.append(row)

    # ---- pooled per wallet -------------------------------------------------------------------
    byw = {}
    for r in rows:
        byw.setdefault(r["wallet"], []).append(r)
    pooled = []
    for w, rs in byw.items():
        nl = sum(r["n_entries_long"] for r in rs)
        p = {"wallet": w, "folds_selected": len(rs),
             "folds": [r["fold"] for r in rs],
             "n_entries_long": nl,
             "pnl_long_usd": round(sum(r.get("pnl_long_usd", 0) for r in rs), 1),
             "pnl_by_fold": {str(r["fold"]): round(r.get("pnl_long_usd", 0), 1) for r in rs},
             "mk8_long": (sum(r.get("mk8_long", 0) * r["n_entries_long"] for r in rs) / nl
                          if nl else None),
             "short_share_test": float(np.mean([r["short_share_test"] for r in rs
                                                if "short_share_test" in r] or [np.nan])),
             "mk8_short": float(np.nanmean([r["mk8_short"] for r in rs
                                            if r.get("mk8_short") is not None] or [np.nan])),
             "hype_share": float(np.mean([r["hype_share_test"] for r in rs
                                          if "hype_share_test" in r] or [np.nan]))}
        for c in FEAT_COLS + ("score", "test_notl_med", "test_close_gap_med_min",
                              "test_entries_per_day", "test_hour_med_utc"):
            vals = [r[c] for r in rs if r.get(c) is not None]
            p[c] = float(np.mean(vals)) if vals else None
        pooled.append(p)
    pooled.sort(key=lambda r: r["pnl_long_usd"])

    active = [p for p in pooled if p["n_entries_long"] > 0]
    silent = [p for p in pooled if p["n_entries_long"] == 0]
    drag = [p for p in active if p["pnl_long_usd"] < 0]
    helpme = [p for p in active if p["pnl_long_usd"] >= 0]

    # ---- persistence test: does drag repeat across folds? ------------------------------------
    multi = [p for p in active if sum(1 for v in p["pnl_by_fold"].values() if v != 0) >= 2]
    pairs = []
    for p in multi:
        v = [x for x in p["pnl_by_fold"].values() if x != 0]
        for i in range(len(v) - 1):
            pairs.append((v[i], v[i + 1]))
    pairs = np.array(pairs) if pairs else np.empty((0, 2))
    persistence = {
        "n_multi_fold_wallets": len(multi),
        "n_consecutive_pairs": int(pairs.shape[0]),
        "sign_agreement": (float((np.sign(pairs[:, 0]) == np.sign(pairs[:, 1])).mean())
                           if pairs.size else None),
        "corr_next_vs_prev": (float(np.corrcoef(pairs[:, 0], pairs[:, 1])[0, 1])
                              if pairs.shape[0] >= 5 else None),
        "repeat_draggers": [p["wallet"][:10] for p in multi
                            if sum(1 for v in p["pnl_by_fold"].values() if v < 0) >= 2],
        "repeat_helpers": [p["wallet"][:10] for p in multi
                           if sum(1 for v in p["pnl_by_fold"].values() if v > 0) >= 2],
    }

    # ---- feature separation draggers vs helpers ----------------------------------------------
    def med(rows_, k):
        v = np.array([r[k] for r in rows_ if r.get(k) is not None], float)
        return round(float(np.median(v)), 4) if v.size else None

    KEYS = ("score", "metric_cap", "f_max_dd_usd", "f_trades_per_day", "f_turnover",
            "f_med_entry_notl", "f_maker_share", "f_hold_proxy_min", "f_coin_hhi",
            "f_pct_prof_days", "f_consistency", "f_clip_lumpiness", "f_mk_8h", "f_ls_gap_8h",
            "f_entry_consensus", "n_form_entries", "short_share_test", "hype_share",
            "test_notl_med", "test_close_gap_med_min", "test_entries_per_day",
            "test_hour_med_utc", "n_entries_long", "folds_selected")
    separation = {k: {"draggers": med(drag, k), "helpers": med(helpme, k)} for k in KEYS}

    rep = {"stamp": "DESCRIPTIVE attribution, burned folds; screens = prereg-amendment "
                    "candidates only (timing-stamped)",
           "cohort": {"n_wallet_folds": len(rows), "n_pooled": len(pooled),
                      "n_active_long": len(active), "n_silent": len(silent),
                      "n_draggers": len(drag), "n_helpers": len(helpme),
                      "drag_usd": round(sum(p["pnl_long_usd"] for p in drag), 1),
                      "help_usd": round(sum(p["pnl_long_usd"] for p in helpme), 1)},
           "persistence": persistence,
           "feature_separation_medians": separation,
           "top12_draggers": drag[:12],
           "top8_helpers": sorted(helpme, key=lambda p: -p["pnl_long_usd"])[:8]}
    OUT.write_text(json.dumps(rep, indent=1, default=str))

    print(json.dumps(rep["cohort"], indent=1))
    print("\n== persistence ==")
    print(json.dumps(persistence, indent=1))
    print("\n== dragger vs helper medians ==")
    for k, v in separation.items():
        if v["draggers"] is not None and v["helpers"] is not None:
            print(f"  {k:>24}: drag {v['draggers']:>12.4g} | help {v['helpers']:>12.4g}")
    print("\n== top draggers (long book $, folds) ==")
    for p in drag[:12]:
        print(f"  {p['wallet'][:12]} folds={p['folds_selected']} nL={p['n_entries_long']:>3} "
              f"${p['pnl_long_usd']:>7.1f} mk8L={p['mk8_long'] if p['mk8_long'] is None else round(p['mk8_long'], 1)} "
              f"byfold={p['pnl_by_fold']}")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
