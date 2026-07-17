"""WALLET x COIN HIERARCHICAL SELECTOR — registered CLOSING LOOK of the burned-fold line
(CONSTRUCTION_PREREG.md §WALLET×COIN HIERARCHICAL SELECTOR). Burned folds 202511-202606.

Formation: lake wallet_coin_day, wallet-DAY-level capping (min(1, 100k/wallet_day_notional)
across all coins, applied to each coin's day pnl-fee). Cells nd_wc>=8, sd>0, wallet in the
informedness pool. Shrinkage: z_wc_shrunk = w*z_wc + (1-w)*z_w, w = nd_wc/(nd_wc+20),
z via informed.t_to_z. Top 300 cells/fold (frozen-133 excluded), then venue rule: MAJORS or
trailing-last-formation-month ADV >= $10M. Forward: copy each wallet ONLY in its selected
coin(s); 8h majors / 1h alts; winsor p95 within venue, wf>=3, wallet-fold-equal,
wallet-cluster boot 4000, per-book rng default_rng(20260716 + book_idx), books
(MAJORS, ALT, COMBINED).

    python -m research.studies.copy_cohort.wallet_coin_selector
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from .alt_fresh_validate import _ctx_parts, MAJORS, STALE_MS
from .informed import t_to_z

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
POOL_DIR = DERIVED / "informedness"
FROZEN = DERIVED / "frozen_alt_universe.json"
CACHE = DERIVED / "wallet_coin_cache"
SEL_DIR = DERIVED / "wallet_coin_selection"
OUT = DERIVED / "wallet_coin_report.json"

FOLDS = MONTHS[3:]                     # 202511..202606 (burned)
CAP = 100_000.0
ND_WC_MIN = 8
TAU = 20.0
TOP_CELLS = 300
ADV_MIN = 10_000_000.0
NOTL_MIN = 250.0
H_MAJOR, H_ALT = 8, 1                  # frozen per-venue horizons
N_BOOT = 4000
SEED = 20260716
CAL_DAYS = 242
BOOKS = ("MAJORS", "ALT", "COMBINED")


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


def _cell_panel(con, fold: int):
    """Per-(wallet, coin) formation stats with WALLET-DAY-level capping (cached)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"cells_{fold}.parquet"
    if not p.exists():
        globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in _formation_months(fold))
        con.execute(f"""COPY (
            WITH wcd AS (
              SELECT wallet, coin, day,
                     SUM(CAST(pnl AS DOUBLE)) - SUM(CAST(fee AS DOUBLE)) AS c_pnl,
                     SUM(CAST(notional AS DOUBLE))                       AS c_notl
              FROM read_parquet([{globs}]) GROUP BY wallet, coin, day
            ),
            wd AS (SELECT wallet, day, SUM(c_notl) AS d_notl FROM wcd GROUP BY wallet, day),
            capd AS (
              SELECT w.wallet, w.coin,
                     w.c_pnl * LEAST(1.0, {CAP} / GREATEST(d.d_notl, 1e-12)) AS cap_pnl,
                     w.c_notl
              FROM wcd w JOIN wd d USING (wallet, day)
            )
            SELECT wallet, coin, count(*) AS nd_wc, avg(cap_pnl) AS mu,
                   stddev_samp(cap_pnl) AS sd, SUM(c_notl) AS wc_notl
            FROM capd GROUP BY wallet, coin
        ) TO '{p.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: cell panel cached", flush=True)
    return p


def _adv_trailing(con, fold: int) -> dict[str, float]:
    """Coin ADV over the LAST formation month (trailing, no look-ahead) (cached)."""
    p = CACHE / f"adv_{fold}.parquet"
    if not p.exists():
        tm = _formation_months(fold)[-1]
        con.execute(f"""COPY (
            SELECT coin, SUM(CAST(notional AS DOUBLE)) / 2 / COUNT(DISTINCT day) AS adv
            FROM read_parquet('{lake.wcd_month_glob(tm)}') GROUP BY coin
        ) TO '{p.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: trailing ADV (month {tm}) cached", flush=True)
    lc = duckdb.connect()
    adv = {c: float(a) for c, a in lc.execute(
        f"SELECT coin, adv FROM read_parquet('{p.as_posix()}')").fetchall()}
    lc.close()
    return adv


def _select_fold(con, fold: int, frozen: set[str]) -> dict:
    """Registered selection: top-300 z_wc_shrunk cells, then venue rule. Writes parquet."""
    cellp = _cell_panel(con, fold)
    adv = _adv_trailing(con, fold)
    lc = duckdb.connect()
    d = lc.execute(f"""
        SELECT c.wallet, c.coin, c.nd_wc, c.mu, c.sd, c.wc_notl, p.z AS z_w
        FROM read_parquet('{cellp.as_posix()}') c
        JOIN read_parquet('{(POOL_DIR / f'fold={fold}' / 'pool.parquet').as_posix()}') p
          USING (wallet)
        WHERE c.nd_wc >= {ND_WC_MIN} AND c.sd > 0""").fetchnumpy()
    wtot = {w: float(t) for w, t in lc.execute(
        f"SELECT wallet, SUM(wc_notl) FROM read_parquet('{cellp.as_posix()}') "
        "GROUP BY wallet").fetchall()}
    lc.close()
    w = d["wallet"].astype(str)
    coin = d["coin"].astype(str)
    keep = np.array([x not in frozen for x in w])
    w, coin = w[keep], coin[keep]
    nd_wc = np.asarray(d["nd_wc"], float)[keep]
    mu = np.asarray(d["mu"], float)[keep]
    sd = np.asarray(d["sd"], float)[keep]
    wc_notl = np.asarray(d["wc_notl"], float)[keep]
    z_w = np.asarray(d["z_w"], float)[keep]
    t_wc = mu / (sd / np.sqrt(nd_wc))
    z_wc = t_to_z(t_wc, nd_wc - 1)
    ww = nd_wc / (nd_wc + TAU)
    score = ww * z_wc + (1 - ww) * z_w
    order = np.lexsort((coin, w, -score))          # score desc, wallet asc, coin asc
    top = order[:TOP_CELLS]
    is_major = np.isin(coin[top], MAJORS)
    tradeable = is_major | np.array([adv.get(c, 0.0) >= ADV_MIN for c in coin[top]])
    sel = top[tradeable]
    venue = np.where(np.isin(coin[sel], MAJORS), "MAJORS", "ALT")
    share = wc_notl[sel] / np.array([max(wtot.get(x, 0.0), 1e-12) for x in w[sel]])
    tbl = {
        "wallet": w[sel].tolist(), "coin": coin[sel].tolist(),
        "nd_wc": nd_wc[sel].astype(int).tolist(), "t_wc": t_wc[sel].tolist(),
        "z_wc": z_wc[sel].tolist(), "z_w": z_w[sel].tolist(), "w": ww[sel].tolist(),
        "z_wc_shrunk": score[sel].tolist(), "venue": venue.tolist(),
        "horizon_h": [H_MAJOR if v == "MAJORS" else H_ALT for v in venue],
        "adv_trailing": [adv.get(c) for c in coin[sel]],
        "notl_share": share.tolist(), "specialist": (share >= 0.5).tolist(),
    }
    part = SEL_DIR / f"fold={fold}"
    part.mkdir(parents=True, exist_ok=True)
    lc = duckdb.connect()
    lc.execute("CREATE TEMP TABLE s AS SELECT " + ", ".join(
        f"UNNEST(?) AS {k}" for k in tbl), list(tbl.values()))
    lc.execute(f"COPY s TO '{(part / 'selected.parquet').as_posix()}' "
               "(FORMAT PARQUET, COMPRESSION zstd)")
    lc.close()
    return {"n_eligible_cells": int(keep.sum()), "n_top": int(top.size),
            "n_selected": int(sel.size), "n_majors_cells": int(is_major[tradeable].sum()),
            "n_dropped_illiquid": int((~tradeable).sum()), "table": tbl}


def _fold_entries(con, fold: int, pairs: list[tuple[str, str, int]]):
    """Test-month flat taker opens of the selected (wallet, coin) pairs, mk at 1h + 8h."""
    p = CACHE / f"entries_{fold}.parquet"
    if not p.exists():
        ctx_list = ",".join(f"'{x}'" for x in _ctx_parts(fold))
        con.execute("CREATE OR REPLACE TEMP TABLE sel AS SELECT UNNEST(?) AS wallet, "
                    "UNNEST(?) AS coin, UNNEST(?) AS horizon_h",
                    [[a for a, _, _ in pairs], [b for _, b, _ in pairs],
                     [h for _, _, h in pairs]])
        joins, cols = [], []
        prev = "p0"
        for h in (H_ALT, H_MAJOR):
            ms = h * 3_600_000
            joins.append(
                f"p{h} AS (SELECT {prev}.*, c.mid_px AS px{h}, c.ts AS px{h}_ts "
                f"FROM {prev} ASOF LEFT JOIN ctx c ON {prev}.coin = c.coin "
                f"AND ({prev}.ts + {ms}) >= c.ts)")
            cols.append(
                f"CASE WHEN px0 IS NOT NULL AND px{h} IS NOT NULL AND px0 > 0 "
                f"AND (ts - px0_ts) <= {STALE_MS} AND ((ts + {ms}) - px{h}_ts) <= {STALE_MS} "
                f"THEN dir_sign * (px{h} - px0) / px0 * 1e4 END AS mk{h}")
            prev = f"p{h}"
        con.execute(f"""COPY (
            WITH ent AS (
              SELECT o.wallet, o.coin, s.horizon_h, o.ts, o.dir_sign,
                     CAST(o.notl AS DOUBLE) AS notl
              FROM read_parquet('{lake.ope_month_glob(fold)}') o
              JOIN sel s ON o.wallet = s.wallet AND o.coin = s.coin
              WHERE CAST(o.notl AS DOUBLE) >= {NOTL_MIN}
            ),
            ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}])
                    WHERE mid_px IS NOT NULL),
            p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS px0_ts
                   FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts),
            {",".join(joins)}
            SELECT wallet, coin, horizon_h, ts, notl, {",".join(cols)}
            FROM {prev}
        ) TO '{p.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        print(f"  fold {fold}: entries cached", flush=True)
    lc = duckdb.connect()
    d = lc.execute(f"SELECT * FROM read_parquet('{p.as_posix()}')").fetchnumpy()
    lc.close()
    return d


def _wf_means(mk, wallet, fold):
    """Registered per-venue robust reduction: winsor p95 |mk| in the sub-book, wf>=3."""
    if mk.size == 0:
        return None
    wf_key = np.char.add(np.char.add(wallet, "|"), fold.astype(str))
    uk, inv = np.unique(wf_key, return_inverse=True)
    raw = float((np.bincount(inv, weights=mk) / np.bincount(inv)).mean())
    lim = float(np.percentile(np.abs(mk), 95))
    mk_w = np.clip(mk, -lim, lim)
    cnt = np.bincount(inv)
    keep = cnt[inv] >= 3
    if not keep.any():
        return {"raw_point_bp": raw, "n_entries": int(mk.size), "robust": None}
    uk2, inv2 = np.unique(wf_key[keep], return_inverse=True)
    wf_mean = np.bincount(inv2, weights=mk_w[keep]) / np.bincount(inv2)
    return {"raw_point_bp": raw, "n_entries": int(mk.size),
            "n_entries_robust": int(keep.sum()),
            "n_wf_covered": int(uk.size),
            "wf_mean": wf_mean,
            "wf_wallet": np.array([k.split("|")[0] for k in uk2]),
            "wf_fold": np.array([int(k.split("|")[1]) for k in uk2])}


def _book_inference(red, rng) -> dict:
    """Wallet-fold-equal point + wallet-cluster bootstrap on reduced wf means."""
    out = {"n_entries": red["n_entries"], "raw_point_bp": red["raw_point_bp"]}
    if red.get("wf_mean") is None:
        out["robust"] = None
        return out
    wf_mean, wf_wal, wf_fold = red["wf_mean"], red["wf_wallet"], red["wf_fold"]
    out["n_entries_robust"] = red["n_entries_robust"]
    out["n_wf_covered"] = red["n_wf_covered"]
    out["n_robust_wf"] = int(wf_mean.size)
    out["n_wallets"] = int(np.unique(wf_wal).size)
    out["robust_point_bp"] = float(wf_mean.mean())
    uw, winv = np.unique(wf_wal, return_inverse=True)
    s = np.bincount(winv, weights=wf_mean)
    c = np.bincount(winv).astype(float)
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        m = np.bincount(rng.integers(0, uw.size, uw.size), minlength=uw.size)
        stats[b] = (m @ s) / (m @ c)
    stats = stats[np.isfinite(stats)]
    out["ci"] = [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))]
    out["p_gt0"] = float((stats > 0).mean())
    pf = {}
    for f in FOLDS:
        m = wf_fold == f
        pf[str(f)] = (float(wf_mean[m].mean()) if m.any() else None)
    out["per_fold_mean_bp"] = pf
    signs = [v for v in pf.values() if v is not None]
    out["per_fold_signs"] = f"{sum(1 for v in signs if v > 0)}/{len(signs)} folds > 0"
    out["entries_per_day"] = round(red["n_entries"] / CAL_DAYS, 2)
    return out


def run():
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    con = lake.connect()

    sel_summary, census = {}, {"specialist_cells": 0, "generalist_cells": 0,
                               "majors_cells": 0, "alt_cells": 0, "share_values": [],
                               "cells_per_wallet": {}}
    rows = {k: [] for k in ("wallet", "coin", "fold", "venue")} | {"mk1": [], "mk8": []}
    for f in FOLDS:
        sel = _select_fold(con, f, frozen)
        t = sel.pop("table")
        sel_summary[str(f)] = sel
        n_cells = len(t["wallet"])
        census["specialist_cells"] += sum(t["specialist"])
        census["generalist_cells"] += n_cells - sum(t["specialist"])
        census["majors_cells"] += sum(1 for v in t["venue"] if v == "MAJORS")
        census["alt_cells"] += sum(1 for v in t["venue"] if v == "ALT")
        census["share_values"] += t["notl_share"]
        cpw = {}
        for x in t["wallet"]:
            cpw[x] = cpw.get(x, 0) + 1
        for k, v in cpw.items():
            census["cells_per_wallet"][str(v)] = census["cells_per_wallet"].get(str(v), 0) + 1
        print(f"  fold {f}: {n_cells} cells selected "
              f"({sel['n_majors_cells']} majors, {sel['n_dropped_illiquid']} illiquid dropped; "
              f"{sum(t['specialist'])} specialists; {len(cpw)} wallets)", flush=True)
        pairs = list(zip(t["wallet"], t["coin"], t["horizon_h"]))
        d = _fold_entries(con, f, pairs)
        n = d["wallet"].size
        rows["wallet"].append(d["wallet"].astype(str))
        rows["coin"].append(d["coin"].astype(str))
        rows["fold"].append(np.full(n, f))
        rows["venue"].append(np.where(np.isin(d["coin"].astype(str), MAJORS), "MAJORS", "ALT"))
        rows["mk1"].append(np.asarray(d["mk1"], float))
        rows["mk8"].append(np.asarray(d["mk8"], float))
    e = {k: np.concatenate(v) for k, v in rows.items()}

    # census reduction
    sv = np.array(census.pop("share_values"), float)
    census["notl_share_median"] = float(np.median(sv)) if sv.size else None
    census["notl_share_mean"] = float(sv.mean()) if sv.size else None
    census["n_cells_total"] = int(census["specialist_cells"] + census["generalist_cells"])

    rep = {"config": {"prereg": "CONSTRUCTION_PREREG.md §WALLET×COIN HIERARCHICAL SELECTOR "
                                "(closing look)",
                      "stamp": "CANDIDATE-RANKING, burned folds 202511-202606; declared "
                               "LAST burned-fold look of the line",
                      "cap": CAP, "nd_wc_min": ND_WC_MIN, "tau": TAU,
                      "top_cells": TOP_CELLS, "adv_min_trailing": ADV_MIN,
                      "notl_min": NOTL_MIN, "horizons": {"MAJORS": H_MAJOR, "ALT": H_ALT},
                      "basis": "asset_ctx mid (gross); ~1-1.6bp follower lag haircut + "
                               "taker fees before any net read",
                      "robust_spec": "winsor p95 within venue sub-book, wf>=3, "
                                     "wallet-fold-equal, wallet-cluster boot",
                      "n_boot": N_BOOT, "seed": SEED, "cal_days": CAL_DAYS,
                      "baselines_restated": {
                          "ksweep_K100_LIQUID_ALT_1h": {"robust_bp": 15.3,
                                                        "ci": [3.6, 28.6]},
                          "majors_native_K30_8h": {"robust_bp": 28.1, "ci": [4.0, 54.8]}}},
           "selection_per_fold": sel_summary, "specialist_census": census, "books": {}}

    # per-venue reductions (registered winsor within venue sub-book)
    m_maj = (e["venue"] == "MAJORS") & np.isfinite(e["mk8"])
    m_alt = (e["venue"] == "ALT") & np.isfinite(e["mk1"])
    red_maj = _wf_means(e["mk8"][m_maj], e["wallet"][m_maj], e["fold"][m_maj])
    red_alt = _wf_means(e["mk1"][m_alt], e["wallet"][m_alt], e["fold"][m_alt])
    reds = {"MAJORS": red_maj, "ALT": red_alt}
    # combined: pooled wallet-fold-venue units from the two venue reductions
    parts = [r for r in (red_maj, red_alt) if r is not None and r.get("wf_mean") is not None]
    if parts:
        red_comb = {
            "n_entries": sum(r["n_entries"] for r in (red_maj, red_alt) if r),
            "raw_point_bp": None,
            "n_entries_robust": sum(r["n_entries_robust"] for r in parts),
            "n_wf_covered": sum(r["n_wf_covered"] for r in (red_maj, red_alt)
                                if r and "n_wf_covered" in r),
            "wf_mean": np.concatenate([r["wf_mean"] for r in parts]),
            "wf_wallet": np.concatenate([r["wf_wallet"] for r in parts]),
            "wf_fold": np.concatenate([r["wf_fold"] for r in parts])}
    else:
        red_comb = None
    reds["COMBINED"] = red_comb

    for bi, book in enumerate(BOOKS):
        red = reds[book]
        rng = np.random.default_rng(SEED + bi)
        if red is None:
            rep["books"][book] = {"n_entries": 0, "robust": None}
            print(f"{book:<9} EMPTY", flush=True)
            continue
        cell = _book_inference(red, rng)
        rep["books"][book] = cell
        b = cell.get("robust_point_bp")
        ci = cell.get("ci", [None, None])
        if b is not None:
            print(f"{book:<9} n={cell['n_entries']:>6,} wal={cell.get('n_wallets', 0):>3} "
                  f"robust={b:+.1f}bp CI[{ci[0]:+.1f},{ci[1]:+.1f}] "
                  f"P(>0)={cell.get('p_gt0', float('nan')):.3f} "
                  f"{cell.get('per_fold_signs', '')} e/d={cell.get('entries_per_day')}",
                  flush=True)
        else:
            print(f"{book:<9} n={cell['n_entries']} (no robust wf)", flush=True)

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
