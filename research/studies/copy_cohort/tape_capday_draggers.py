"""DRAGGER ANATOMY for the tape capday F0 top-30 — post-hoc DESCRIPTIVE, burned folds.

Who inside the F0 cohort drags forward 8h markout down, and do they share an archetype the
pre-declared screens missed? Every number here is hypothesis-grade (post-hoc labels on burned
folds); any resulting screen must be registered as a FORWARD rule only.

    python -m research.studies.copy_cohort.tape_capday_draggers
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from .tape_capday_filter import (CACHE, DERIVED, FOLDS, RT_COST_BP, _formation_features,
                                 _rosters, _sha)

OUT = DERIVED / "tape_capday_draggers_report.json"
MAJORS = ("BTC", "ETH", "SOL", "HYPE")


def _load_fold(fold: int, sha: str):
    featp = CACHE / f"feat_{fold}_{sha}.parquet"
    entp = CACHE / f"ent_{fold}_{sha}.parquet"
    assert featp.exists() and entp.exists(), f"missing caches for fold {fold} — run the study first"
    lc = duckdb.connect()
    feats = lc.execute(f"SELECT * FROM read_parquet('{featp.as_posix()}')").fetchnumpy()
    ents = lc.execute(f"SELECT * FROM read_parquet('{entp.as_posix()}')").fetchnumpy()
    lc.close()
    return feats, ents


def _np(a, dtype=float):
    arr = np.ma.filled(a, np.nan) if np.ma.isMaskedArray(a) else a
    return np.asarray(arr, dtype)


def run():
    sha = _sha()
    con = duckdb.connect()  # only for _formation_features cache hits (never recompute here)
    con.close()

    wallets_rows = []          # one row per (wallet, fold) in F0 with >=1 evaluable mk8
    for fold in FOLDS:
        feats, ents = _load_fold(fold, sha)
        fw = feats["wallet"].astype(str)
        rosters, funnel = _rosters(CACHE / f"feat_{fold}_{sha}.parquet")
        f0 = set(rosters["F0"])
        ew = ents["wallet"].astype(str)
        mk8 = _np(ents["mk8"])
        mk1 = _np(ents["mk1"])
        ts = _np(ents["ts"])
        coin = ents["coin"].astype(str)
        dirn = _np(ents["dir_sign"])
        notl = _np(ents["notional"])
        for w in sorted(f0):
            m = (ew == w) & np.isfinite(mk8)
            fi = np.flatnonzero(fw == w)
            if not fi.size:
                continue
            fi = fi[0]
            row = {"wallet": w, "fold": fold, "n_entries": int(m.sum())}
            if m.sum():
                days = np.unique((ts[m] // 86_400_000).astype(int))
                row |= {
                    "mk8_mean": float(mk8[m].mean()), "mk1_mean": float(np.nanmean(mk1[m])),
                    "mk8_median": float(np.median(mk8[m])),
                    "pnl_usd_1k": float(((mk8[m] - RT_COST_BP) / 1e4 * 1000).sum()),
                    "hit8": float((mk8[m] > 0).mean()),
                    "coins": {c: int((coin[m] == c).sum()) for c in MAJORS if (coin[m] == c).any()},
                    "hype_share": float((coin[m] == "HYPE").mean()),
                    "short_share": float((dirn[m] < 0).mean()),
                    "entry_notl_med": float(np.median(notl[m])),
                    "active_entry_days": int(days.size),
                    "entries_per_active_day": float(m.sum() / days.size),
                    "max_entries_one_day": int(np.bincount(
                        ((ts[m] // 86_400_000).astype(int) - days.min())).max()),
                }
            for k in ("nd", "metric", "fills_per_day", "taker_share", "n_own_liq", "conc",
                      "med_open_notl", "n_open"):
                v = _np(feats[k])[fi]
                row[f"form_{k}"] = (None if not np.isfinite(v) else float(v))
            wallets_rows.append(row)

    evald = [r for r in wallets_rows if r["n_entries"] > 0]
    silent = [r for r in wallets_rows if r["n_entries"] == 0]

    # pooled per-WALLET view (wallets recur across folds)
    byw = {}
    for r in evald:
        byw.setdefault(r["wallet"], []).append(r)
    pooled = []
    for w, rs in byw.items():
        n = sum(r["n_entries"] for r in rs)
        mk = sum(r["mk8_mean"] * r["n_entries"] for r in rs) / n
        pooled.append({
            "wallet": w, "folds": len(rs), "n_entries": n, "mk8_mean": mk,
            "pnl_usd_1k": sum(r["pnl_usd_1k"] for r in rs),
            "hit8": sum(r["hit8"] * r["n_entries"] for r in rs) / n,
            "hype_share": sum(r["hype_share"] * r["n_entries"] for r in rs) / n,
            "short_share": sum(r["short_share"] * r["n_entries"] for r in rs) / n,
            "entries_per_active_day": float(np.mean([r["entries_per_active_day"] for r in rs])),
            "entry_notl_med": float(np.median([r["entry_notl_med"] for r in rs])),
            **{f"form_{k}": float(np.nanmean([r[f"form_{k}"] for r in rs
                                              if r[f"form_{k}"] is not None]))
               for k in ("nd", "metric", "fills_per_day", "taker_share", "conc",
                         "med_open_notl", "n_open")},
        })
    pooled.sort(key=lambda r: r["pnl_usd_1k"])

    # dragger vs helper split on pooled book contribution
    draggers = [r for r in pooled if r["pnl_usd_1k"] < 0]
    helpers = [r for r in pooled if r["pnl_usd_1k"] >= 0]

    def prof(rows, keys):
        out = {}
        for k in keys:
            v = np.array([r[k] for r in rows if r.get(k) is not None and np.isfinite(r[k])])
            if v.size:
                out[k] = {"median": float(np.median(v)), "mean": float(v.mean()),
                          "p25": float(np.quantile(v, .25)), "p75": float(np.quantile(v, .75))}
        return out

    KEYS = ("mk8_mean", "hit8", "n_entries", "entries_per_active_day", "entry_notl_med",
            "hype_share", "short_share", "form_nd", "form_metric", "form_fills_per_day",
            "form_taker_share", "form_conc", "form_med_open_notl", "form_n_open")
    rep = {
        "stamp": "POST-HOC DESCRIPTIVE on burned folds — hypothesis-grade; any screen from this "
                 "is a REGISTERED FORWARD RULE only, never a burned-fold claim",
        "config_sha": sha,
        "n_wallet_folds_in_f0": len(wallets_rows),
        "n_evaluable_wallet_folds": len(evald),
        "n_silent_wallet_folds": len(silent),
        "n_pooled_wallets": len(pooled),
        "n_draggers": len(draggers), "n_helpers": len(helpers),
        "dragger_pnl_usd": float(sum(r["pnl_usd_1k"] for r in draggers)),
        "helper_pnl_usd": float(sum(r["pnl_usd_1k"] for r in helpers)),
        "profiles": {"draggers": prof(draggers, KEYS), "helpers": prof(helpers, KEYS)},
        "top10_draggers": draggers[:10],
        "top10_helpers": sorted(helpers, key=lambda r: -r["pnl_usd_1k"])[:10],
        "concentration": {},
        "cuts": {},
    }

    # concentration: is the negative side few-wallet or broad?
    dp = np.array([r["pnl_usd_1k"] for r in draggers])
    if dp.size:
        tot = dp.sum()
        rep["concentration"] = {
            "worst1_share_of_drag": float(dp[0] / tot) if tot else None,
            "worst3_share_of_drag": float(dp[:3].sum() / tot) if tot else None,
            "n_draggers_for_half": int(np.searchsorted(np.cumsum(dp) / tot, 0.5) + 1)
            if tot else None,
        }

    # candidate archetype cuts (pre-listed axes, descriptive deltas; book = ex-cut re-mean)
    all_rows = pooled
    tot_pnl = sum(r["pnl_usd_1k"] for r in all_rows)
    tot_n = sum(r["n_entries"] for r in all_rows)

    def cut(name, pred):
        keep = [r for r in all_rows if not pred(r)]
        drop = [r for r in all_rows if pred(r)]
        kn = sum(r["n_entries"] for r in keep)
        rep["cuts"][name] = {
            "n_dropped_wallets": len(drop), "entries_dropped_frac":
                round(1 - kn / tot_n, 3) if tot_n else None,
            "dropped_pnl_usd": round(sum(r["pnl_usd_1k"] for r in drop), 1),
            "book_pnl_usd_before": round(tot_pnl, 1),
            "book_pnl_usd_after": round(sum(r["pnl_usd_1k"] for r in keep), 1),
            "book_mk8_wallet_equal_before": round(float(np.mean(
                [r["mk8_mean"] for r in all_rows])), 2),
            "book_mk8_wallet_equal_after": round(float(np.mean(
                [r["mk8_mean"] for r in keep])), 2) if keep else None,
        }

    med_fpd = float(np.median([r["form_fills_per_day"] for r in all_rows]))
    cut("hyperactive_form_fills_per_day_top_quartile",
        lambda r: r["form_fills_per_day"] >= np.quantile(
            [x["form_fills_per_day"] for x in all_rows], .75))
    cut("burst_entries_per_active_day_ge_3", lambda r: r["entries_per_active_day"] >= 3)
    cut("short_biased_ge_half", lambda r: r["short_share"] >= 0.5)
    cut("hype_dominant_ge_half", lambda r: r["hype_share"] >= 0.5)
    cut("low_hit_lt_45", lambda r: r["hit8"] < 0.45)          # outcome-circular — labeled
    cut("small_entry_notl_lt_1k", lambda r: r["entry_notl_med"] < 1000)
    cut("high_form_conc_gt_30", lambda r: r["form_conc"] > 0.30)
    cut("thin_form_nd_lt_45", lambda r: r["form_nd"] < 45)
    rep["cuts"]["low_hit_lt_45"]["circularity_warning"] = \
        "cut uses FORWARD outcome (hit8) — diagnostic only, never a screen"

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: rep[k] for k in ("n_pooled_wallets", "n_draggers", "n_helpers",
                                          "dragger_pnl_usd", "helper_pnl_usd",
                                          "concentration")}, indent=1))
    print("\n== dragger vs helper medians ==")
    for k in KEYS:
        d = rep["profiles"]["draggers"].get(k, {}).get("median")
        h = rep["profiles"]["helpers"].get(k, {}).get("median")
        if d is not None and h is not None:
            print(f"  {k:>28}: draggers {d:>10.3f} | helpers {h:>10.3f}")
    print("\n== candidate cuts (descriptive) ==")
    for name, c in rep["cuts"].items():
        print(f"  {name:>44}: drop {c['n_dropped_wallets']:>2} wallets "
              f"({c['entries_dropped_frac']:.0%} entries) book ${c['book_pnl_usd_before']:.0f}"
              f" -> ${c['book_pnl_usd_after']:.0f}  wallet-eq {c['book_mk8_wallet_equal_before']}"
              f" -> {c['book_mk8_wallet_equal_after']}bp")
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
