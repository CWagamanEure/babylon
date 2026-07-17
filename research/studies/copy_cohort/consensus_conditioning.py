"""CONSENSUS CONDITIONING — descriptive re-binning of the two frozen books (burned folds).

Implements the pre-declared grid stamped in WALLET_ATTRIBUTION.md ("CONSENSUS CONDITIONING —
pre-declared grid", 2026-07-17): definitions were written BEFORE any outcome was computed.
DESCRIPTIVE: no new selection; 18 grid cells + 2 score-weighted variant rows, all dependent.

    python -m research.studies.copy_cohort.consensus_conditioning
"""
from __future__ import annotations

import json
from math import ceil

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from . import pyramid_book as pb
from .alt_fresh_validate import MAJORS

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
MN = DERIVED / "majors_native"
CDIR = DERIVED / "consensus"
FROZEN = DERIVED / "frozen_alt_universe.json"
ATTR = DERIVED / "wallet_attribution_report.json"
OUT_JSON = DERIVED / "consensus_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "WALLET_ATTRIBUTION.md"

FOLDS = MONTHS[3:]                          # 202511..202606 (burned)
K_M = 30
COST_M_BP = 5.5
UNIT_USD = 2_500.0
WINDOWS = (("1h", 3_600_000), ("6h", 21_600_000), ("24h", 86_400_000))
LEVELS = ("solo", "pair", "crowd")
FILLS_DAY_MAX = 1000.0                      # v1.1 bot screen (book A only)
N_BOOT = 1000
SEED = 20260717
STAMP = ("DESCRIPTIVE — burned folds 202511-202606; pre-declared grid (stamped before compute); "
         "18+2 dependent cells; no multiplicity correction; no new selection.")


# ------------------------------------------------------------------ lake caches
def _majors_k30_wallets(fold: int) -> list[str]:
    """Replicate majors_native._select_top100 ordering; return top-30."""
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    lc = duckdb.connect()
    d = lc.execute(f"SELECT wallet, t_stat FROM read_parquet("
                   f"'{(MN / f'sel_{fold}.parquet').as_posix()}') "
                   "WHERE t_stat IS NOT NULL").fetchnumpy()
    lc.close()
    w = d["wallet"].astype(str)
    t = np.asarray(d["t_stat"], float)
    keep = np.array([x not in frozen for x in w])
    w, t = w[keep], t[keep]
    order = np.lexsort((w, -t))
    return w[order[:K_M]].tolist()


def _majors_opens(con, fold: int, wallets: list[str]):
    """K30 majors flat opens with dir_sign, block-collapsed (counting pool + dir join)."""
    p = CDIR / f"majors_opens_{fold}.parquet"
    if not p.exists():
        majors = ",".join(f"'{m}'" for m in MAJORS)
        con.execute("CREATE OR REPLACE TEMP TABLE kw AS SELECT UNNEST(?) AS wallet",
                    [sorted(wallets)])
        tmp = str(p) + ".tmp"
        con.execute(f"""COPY (
            SELECT o.wallet, o.coin, o.ts, o.dir_sign, SUM(CAST(o.notl AS DOUBLE)) AS notl
            FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN kw USING (wallet)
            WHERE o.coin IN ({majors})
            GROUP BY o.wallet, o.coin, o.ts, o.dir_sign
        ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
        (CDIR / (p.name + ".tmp")).replace(p)
        print(f"  fold {fold}: majors K30 opens cached", flush=True)
    lc = duckdb.connect()
    d = lc.execute(f"SELECT * FROM read_parquet('{p.as_posix()}')").fetchnumpy()
    lc.close()
    return d


def _fillsday(con, fold: int, wallets: list[str]) -> dict[str, float]:
    """Formation fills/day per pyramid-cohort wallet (v1.1 screen input)."""
    p = CDIR / f"fillsday_{fold}.parquet"
    if not p.exists():
        months = pb._formation_months(fold)
        globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in months)
        con.execute("CREATE OR REPLACE TEMP TABLE pw AS SELECT UNNEST(?) AS wallet",
                    [sorted(wallets)])
        tmp = str(p) + ".tmp"
        con.execute(f"""COPY (
            SELECT d.wallet, SUM(d.n_fills) AS n_fills, COUNT(DISTINCT d.day) AS n_days
            FROM read_parquet([{globs}]) d JOIN pw USING (wallet) GROUP BY d.wallet
        ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
        (CDIR / (p.name + ".tmp")).replace(p)
        print(f"  fold {fold}: formation fills/day cached", flush=True)
    lc = duckdb.connect()
    rows = lc.execute(f"SELECT wallet, n_fills, n_days FROM read_parquet('{p.as_posix()}')").fetchall()
    lc.close()
    return {w: float(nf) / max(float(nd), 1.0) for w, nf, nd in rows}


# ------------------------------------------------------------------ consensus sweep
def count_consensus(entries, signals, tophalf: set[str]):
    """Per-entry counts of distinct OTHER cohort wallets with a signal in [t-W, t).

    entries: dict(ts, wallet, coin, dir) arrays; signals: dict(ts, wallet, coin, dir) arrays.
    Returns (n_others[W_key] arrays, n_others_tophalf_6h array), aligned to entries order.
    """
    ne = entries["ts"].size
    out = {wk: np.zeros(ne, np.int64) for wk, _ in WINDOWS}
    out_top = np.zeros(ne, np.int64)
    ekey = np.char.add(np.char.add(entries["coin"], "|"), entries["dir"].astype("U4"))
    skey = np.char.add(np.char.add(signals["coin"], "|"), signals["dir"].astype("U4"))
    for g in np.unique(ekey):
        ei = np.flatnonzero(ekey == g)
        si = np.flatnonzero(skey == g)
        eo = ei[np.argsort(entries["ts"][ei], kind="stable")]
        so = si[np.argsort(signals["ts"][si], kind="stable")]
        sts = signals["ts"][so]
        swal = signals["wallet"][so]
        last: dict[str, int] = {}
        j = 0
        for idx in eo:
            t = int(entries["ts"][idx])
            w = entries["wallet"][idx]
            while j < sts.size and int(sts[j]) < t:        # strictly before t -> [t-W, t)
                last[swal[j]] = int(sts[j])
                j += 1
            for wk, wms in WINDOWS:
                out[wk][idx] = sum(1 for lw, lt in last.items()
                                   if lt >= t - wms and lw != w)
            out_top[idx] = sum(1 for lw, lt in last.items()
                               if lt >= t - 21_600_000 and lw != w and lw in tophalf)
    return out, out_top


# ------------------------------------------------------------------ book loaders
def load_book_a(con):
    """Re-sim pyramid (full cohort, reconcile), then v1.1 screen; build entries + signals."""
    cohorts = json.loads(pb.COHORTS_JSON.read_text())
    funnel = {"n_watch_started": 0, "n_watch_expired": 0, "n_add_ignored_idle": 0,
              "n_after_4th": 0, "n_miss_entry_px": 0, "n_cap_skip_book": 0,
              "n_cap_skip_coin": 0, "n_units_filled_rung": {}, "exit_flag_counts": {},
              "n_units_no_exit_px": 0}
    units: list[dict] = []
    fold_units: dict[int, tuple[int, int]] = {}
    for f in pb.FOLDS:
        info = cohorts["folds"][str(f)]
        liq = pb._liquid_alts(None, f)
        sig, _ = pb._fold_signals(None, f, info["wallets"], liq)
        ctx = pb._ctx_by_coin(f, set(sig["coin"].tolist()))
        n0 = len(units)
        pb.simulate_fold(f, sig, ctx, funnel, units)
        fold_units[f] = (n0, len(units))
        print(f"  A fold {f}: {len(units) - n0:,} units", flush=True)

    # ---- reconciliation gate vs wallet_attribution_report.json
    attr = json.loads(ATTR.read_text())["books"]["P"]["concentration"]
    tot = round(sum(u["net"] for u in units), 2)
    recon = {"n_units_resim": len(units), "n_units_attr": attr["n_trades"],
             "net_usd_resim": tot, "net_usd_attr": attr["total_net_usd"]}
    if len(units) != attr["n_trades"] or abs(tot - attr["total_net_usd"]) > 1.0:
        raise RuntimeError(f"reconciliation FAILED: {recon}")
    print(f"  A reconciliation OK: {recon}", flush=True)

    # ---- v1.1 screen per fold + screened cohorts (entries AND counting pool)
    screened: dict[int, list[str]] = {}
    fd_all: dict[int, dict[str, float]] = {}
    for f in pb.FOLDS:
        cw = cohorts["folds"][str(f)]["wallets"]        # formation-t descending order
        fd = _fillsday(con, f, cw)
        fd_all[f] = fd
        screened[f] = [w for w in cw if fd.get(w, 0.0) < FILLS_DAY_MAX]
    n_bot = {str(f): len(cohorts["folds"][str(f)]["wallets"]) - len(screened[f])
             for f in pb.FOLDS}

    keep_units = [u for u in units if fd_all[u["fold"]].get(u["wallet"], 0.0) < FILLS_DAY_MAX]
    entries = {
        "ts": np.array([u["ts_sig"] for u in keep_units], np.int64),
        "wallet": np.array([u["wallet"] for u in keep_units]),
        "coin": np.array([u["coin"] for u in keep_units]),
        "dir": np.array([u["dir"] for u in keep_units], np.int64),
        "fold": np.array([u["fold"] for u in keep_units], np.int64),
        "gross_bp": np.array([u["gross"] / UNIT_USD * 1e4 for u in keep_units]),
        "net_bp": np.array([u["net"] / UNIT_USD * 1e4 for u in keep_units]),
    }

    # ---- counting signal pools per fold: screened cohort opens + adds (no notl filter)
    signals_by_fold, tophalf_by_fold = {}, {}
    for f in pb.FOLDS:
        sset = set(screened[f])
        op = pb._opens(None, f, cohorts["folds"][str(f)]["wallets"])
        ad = pb._adds(f)
        parts = []
        for d in (op, ad):
            w = d["wallet"].astype(str)
            m = np.array([x in sset for x in w])
            parts.append({"ts": np.asarray(d["ts"], np.int64)[m], "wallet": w[m],
                          "coin": d["coin"].astype(str)[m],
                          "dir": np.asarray(d["dir_sign"], np.int64)[m]})
        signals_by_fold[f] = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        tophalf_by_fold[f] = set(screened[f][:ceil(len(screened[f]) / 2)])
    return entries, signals_by_fold, tophalf_by_fold, recon, n_bot, len(units) - len(keep_units)


def load_book_b(con):
    """Majors-native K30 entries (rk<30, finite mk8) + dir join + counting pools."""
    ent_parts, signals_by_fold, tophalf_by_fold = [], {}, {}
    n_amb = 0
    for f in FOLDS:
        k30 = _majors_k30_wallets(f)
        op = _majors_opens(con, f, k30)
        ow = op["wallet"].astype(str)
        oc = op["coin"].astype(str)
        ots = np.asarray(op["ts"], np.int64)
        od = np.asarray(op["dir_sign"], np.int64)
        signals_by_fold[f] = {"ts": ots, "wallet": ow, "coin": oc, "dir": od}
        tophalf_by_fold[f] = set(k30[:K_M // 2])         # rk < 15
        # dir map (wallet|coin|ts -> dir); ambiguous (both dirs) dropped
        keys = [f"{a}|{b}|{c}" for a, b, c in zip(ow, oc, ots.tolist())]
        dmap: dict[str, int] = {}
        amb: set[str] = set()
        for kk, dd in zip(keys, od.tolist()):
            if kk in dmap and dmap[kk] != dd:
                amb.add(kk)
            dmap[kk] = dd
        lc = duckdb.connect()
        d = lc.execute(
            f"SELECT wallet, coin, ts, mk8 FROM read_parquet("
            f"'{(MN / f'entries_{f}.parquet').as_posix()}') "
            f"WHERE rk < {K_M} AND mk8 IS NOT NULL AND isfinite(mk8)").fetchnumpy()
        lc.close()
        ew = d["wallet"].astype(str)
        ec = d["coin"].astype(str)
        ets = np.asarray(d["ts"], np.int64)
        mk8 = np.asarray(d["mk8"], float)
        ekeys = [f"{a}|{b}|{c}" for a, b, c in zip(ew, ec, ets.tolist())]
        ok = np.array([(kk in dmap) and (kk not in amb) for kk in ekeys])
        n_amb += int(sum(1 for kk in ekeys if kk in amb))
        if not ok.all():
            miss = int((~ok).sum())
            print(f"  B fold {f}: {miss} entries dropped (ambiguous/no dir match)", flush=True)
        edir = np.array([dmap[kk] for kk, o in zip(ekeys, ok) if o], np.int64)
        ent_parts.append({"ts": ets[ok], "wallet": ew[ok], "coin": ec[ok], "dir": edir,
                          "fold": np.full(int(ok.sum()), f, np.int64),
                          "gross_bp": mk8[ok], "net_bp": mk8[ok] - COST_M_BP})
    entries = {k: np.concatenate([p[k] for p in ent_parts]) for k in ent_parts[0]}
    return entries, signals_by_fold, tophalf_by_fold, n_amb


# ------------------------------------------------------------------ cell inference
DAY_MS = 86_400_000


def _coinday(coin, ts):
    """(coin × calendar-day) cluster labels + inverse index."""
    day = (np.asarray(ts, np.int64) // DAY_MS).astype("U16")
    key = np.char.add(np.char.add(coin.astype(str), "|"), day)
    return np.unique(key, return_inverse=True)


def _quant(boot):
    boot = boot[np.isfinite(boot)]
    if boot.size == 0:
        return None
    return [round(float(np.quantile(boot, .025)), 2), round(float(np.quantile(boot, .975)), 2)]


def _wider(ci_a, ci_b):
    """Pick the wider of two CIs (audit 2026-07-17: quote the conservative cluster unit)."""
    if ci_a is None:
        return ci_b, "coinday"
    if ci_b is None:
        return ci_a, "wallet"
    return (ci_a, "wallet") if (ci_a[1] - ci_a[0]) >= (ci_b[1] - ci_b[0]) else (ci_b, "coinday")


def cell_stats(gross, net, wallet, coin, ts, seed):
    """n, entry-equal net, wallet-equal winsorized gross + TWO cluster boot CIs.

    AUDIT FIX 2026-07-17: consensus cells share coin-time shocks across wallets, so a
    wallet-only cluster CI understates dependence. Report BOTH the wallet-cluster CI and a
    (coin × calendar-day)-cluster CI (multiplicity-weighted, ksweep pattern); ci95 = the
    WIDER of the two (binding)."""
    n = int(gross.size)
    out = {"n": n}
    if n == 0:
        return out
    out["net_bp_entry_equal"] = round(float(net.mean()), 2)
    lim = float(np.percentile(np.abs(gross), 95))
    gw = np.clip(gross, -lim, lim)
    uw, inv = np.unique(wallet, return_inverse=True)
    s = np.bincount(inv, weights=gw)
    c = np.bincount(inv).astype(float)
    wmean = s / c
    out["n_wallets"] = int(uw.size)
    out["gross_bp_wallet_equal_winsor"] = round(float(wmean.mean()), 2)
    ci_w = None
    if uw.size >= 2:
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, uw.size, size=(N_BOOT, uw.size))
        ci_w = _quant(wmean[idx].mean(axis=1))
    # (coin × day)-cluster boot of the SAME statistic: cluster weights -> entry weights ->
    # weighted per-wallet means -> mean over wallets with weight (multiplicity-preserving)
    ug, ginv = _coinday(coin, ts)
    ci_cd = None
    out["n_coinday_clusters"] = int(ug.size)
    if ug.size >= 2:
        rng2 = np.random.default_rng(seed + 500_000)
        boot = np.empty(N_BOOT)
        for b in range(N_BOOT):
            mult = np.bincount(rng2.integers(0, ug.size, ug.size), minlength=ug.size).astype(float)
            ew = mult[ginv]
            ws = np.bincount(inv, weights=gw * ew)
            wc = np.bincount(inv, weights=ew)
            live = wc > 0
            boot[b] = float((ws[live] / wc[live]).mean()) if live.any() else np.nan
        ci_cd = _quant(boot)
    out["ci95_wallet"], out["ci95_coinday"] = ci_w, ci_cd
    out["ci95"], out["ci95_binding"] = _wider(ci_w, ci_cd)
    return out


def gap_ci(gross_a, wal_a, coin_a, ts_a, gross_b, wal_b, coin_b, ts_b, seed):
    """crowd-vs-solo gap on wallet-equal winsorized gross; TWO cluster boots
    (audit 2026-07-17): wallet-cluster (union frame, as before) AND (coin × calendar-day)-
    cluster resampled JOINTLY across both cells; ci95 = the WIDER."""
    if gross_a.size == 0 or gross_b.size == 0:
        return None

    def winsor(g):
        lim = float(np.percentile(np.abs(g), 95))
        return np.clip(g, -lim, lim)

    gwa, gwb = winsor(gross_a), winsor(gross_b)

    def wmeans(gw, w):
        uw, inv = np.unique(w, return_inverse=True)
        return dict(zip(uw.tolist(), (np.bincount(inv, weights=gw) / np.bincount(inv)).tolist()))

    ma, mb = wmeans(gwa, wal_a), wmeans(gwb, wal_b)
    union = sorted(set(ma) | set(mb))
    va = np.array([ma.get(w, np.nan) for w in union])
    vb = np.array([mb.get(w, np.nan) for w in union])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(union), size=(N_BOOT, len(union)))
    boots = np.nanmean(va[idx], axis=1) - np.nanmean(vb[idx], axis=1)
    ci_w = _quant(boots)
    point = float(np.nanmean(va) - np.nanmean(vb))
    # joint (coin × day)-cluster boot over the union of both cells' clusters
    daya = (np.asarray(ts_a, np.int64) // DAY_MS).astype("U16")
    dayb = (np.asarray(ts_b, np.int64) // DAY_MS).astype("U16")
    ka = np.char.add(np.char.add(coin_a.astype(str), "|"), daya)
    kb = np.char.add(np.char.add(coin_b.astype(str), "|"), dayb)
    ug, ginv = np.unique(np.concatenate([ka, kb]), return_inverse=True)
    ga, gb = ginv[:ka.size], ginv[ka.size:]
    uwa, inva = np.unique(wal_a, return_inverse=True)
    uwb, invb = np.unique(wal_b, return_inverse=True)
    ci_cd = None
    if ug.size >= 2:
        rng2 = np.random.default_rng(seed + 500_000)
        boot = np.empty(N_BOOT)
        for b in range(N_BOOT):
            mult = np.bincount(rng2.integers(0, ug.size, ug.size), minlength=ug.size).astype(float)

            def cell_mean(gw, invx, gx, nw):
                ew = mult[gx]
                ws = np.bincount(invx, weights=gw * ew, minlength=nw)
                wc = np.bincount(invx, weights=ew, minlength=nw)
                live = wc > 0
                return float((ws[live] / wc[live]).mean()) if live.any() else np.nan

            boot[b] = (cell_mean(gwa, inva, ga, uwa.size)
                       - cell_mean(gwb, invb, gb, uwb.size))
        ci_cd = _quant(boot)
    ci, binding = _wider(ci_w, ci_cd)
    return {"gap_bp": round(point, 2), "ci95": ci, "ci95_binding": binding,
            "ci95_wallet": ci_w, "ci95_coinday": ci_cd,
            "n_coinday_clusters": int(ug.size)}


# ------------------------------------------------------------------ main
def run():
    CDIR.mkdir(parents=True, exist_ok=True)
    con = lake.connect()
    print("[A] pyramid-alt re-sim + v1.1 screen ...", flush=True)
    ent_a, sig_a, top_a, recon, n_bot, n_dropped_units = load_book_a(con)
    print(f"  A: {ent_a['ts'].size:,} screened units "
          f"({n_dropped_units:,} bot units dropped; bots/fold {n_bot})", flush=True)
    print("[B] majors-native K30 entries + dir join ...", flush=True)
    ent_b, sig_b, top_b, n_amb = load_book_b(con)
    print(f"  B: {ent_b['ts'].size:,} entries ({n_amb} ambiguous-dir dropped)", flush=True)
    con.close()

    books = {}
    cell_idx = 0
    counts_cache = {}
    for bk, ent, sigs, tops in (("A", ent_a, sig_a, top_a), ("B", ent_b, sig_b, top_b)):
        nO = {wk: np.zeros(ent["ts"].size, np.int64) for wk, _ in WINDOWS}
        nTop = np.zeros(ent["ts"].size, np.int64)
        for f in FOLDS:
            m = ent["fold"] == f
            if not m.any():
                continue
            sub = {k: ent[k][m] for k in ("ts", "wallet", "coin", "dir")}
            o, ot = count_consensus(sub, sigs[f], tops[f])
            for wk, _ in WINDOWS:
                nO[wk][m] = o[wk]
            nTop[m] = ot
        counts_cache[bk] = (nO, nTop)
        n_book = int(ent["ts"].size)
        sec = {"n_book_entries": n_book, "grid": {}, "variant_6h_tophalf": {},
               "monotonicity": {}, "crowd_vs_solo": {}}
        for wk, _ in WINDOWS:
            lv = {"solo": nO[wk] == 0, "pair": nO[wk] == 1, "crowd": nO[wk] >= 2}
            row = {}
            for name in LEVELS:
                m = lv[name]
                cs = cell_stats(ent["gross_bp"][m], ent["net_bp"][m], ent["wallet"][m],
                                ent["coin"][m], ent["ts"][m], SEED + cell_idx)
                cs["pct_entries"] = round(float(m.mean()) * 100, 1)
                row[name] = cs
                cell_idx += 1
            sec["grid"][wk] = row
            g = [row[n].get("gross_bp_wallet_equal_winsor") for n in LEVELS]
            sec["monotonicity"][wk] = {
                "solo_pair_crowd_bp": g,
                "rises": (None if any(v is None for v in g)
                          else bool(g[0] < g[1] < g[2]))}
            sec["crowd_vs_solo"][wk] = gap_ci(
                ent["gross_bp"][lv["crowd"]], ent["wallet"][lv["crowd"]],
                ent["coin"][lv["crowd"]], ent["ts"][lv["crowd"]],
                ent["gross_bp"][lv["solo"]], ent["wallet"][lv["solo"]],
                ent["coin"][lv["solo"]], ent["ts"][lv["solo"]],
                SEED + 100 + cell_idx)
        lvt = {"solo": nTop == 0, "pair": nTop == 1, "crowd": nTop >= 2}
        for name in LEVELS:
            m = lvt[name]
            cs = cell_stats(ent["gross_bp"][m], ent["net_bp"][m], ent["wallet"][m],
                            ent["coin"][m], ent["ts"][m], SEED + cell_idx)
            cs["pct_entries"] = round(float(m.mean()) * 100, 1)
            sec["variant_6h_tophalf"][name] = cs
            cell_idx += 1
        sec["variant_crowd_vs_solo"] = gap_ci(
            ent["gross_bp"][lvt["crowd"]], ent["wallet"][lvt["crowd"]],
            ent["coin"][lvt["crowd"]], ent["ts"][lvt["crowd"]],
            ent["gross_bp"][lvt["solo"]], ent["wallet"][lvt["solo"]],
            ent["coin"][lvt["solo"]], ent["ts"][lvt["solo"]],
            SEED + 100 + cell_idx)
        books[bk] = sec

    rep = {"label": "consensus conditioning of frozen books (pre-declared grid)",
           "stamp": STAMP,
           "config": {"windows": [w for w, _ in WINDOWS], "levels": list(LEVELS),
                      "window_def": "[t-W, t) strictly before entry ts; distinct OTHER cohort "
                                    "wallets, same coin+dir",
                      "book_a": "pyramid-alt re-sim (reconciled) + v1.1 fills/day<1000 screen "
                                "(entries and counting pool); entry ts = ts_sig; cost 21.5bp in net",
                      "book_b": f"majors-native rk<{K_M}, finite mk8, net = mk8 - {COST_M_BP}bp; "
                                "dir from lake open_entries join; counting pool = K30 majors opens",
                      "cell_metric": "winsor p95 |gross| within cell -> per-wallet mean -> "
                                     "wallet-equal mean; 1000-rep cluster boot percentile CIs: "
                                     "wallet AND (coin x calendar-day); ci95 = wider (binding)",
                      "n_boot": N_BOOT, "seed": SEED,
                      "code_commit": lake.git_describe(),
                      "audit_2026_07_17": "two-way cluster CIs (wallet + coin-day), wider quoted",
                      "reconciliation": recon, "a_bots_per_fold": n_bot,
                      "a_bot_units_dropped": n_dropped_units,
                      "b_ambiguous_dir_dropped": n_amb},
           "books": books}
    OUT_JSON.write_text(json.dumps(rep, indent=1))
    print(f"-> {OUT_JSON}")
    append_md(rep)
    return rep


def append_md(rep):
    lines = ["\n## CONSENSUS CONDITIONING — RESULTS (computed after the stamp above)\n",
             "*2026-07-17 audit re-print: every boot CI below is the WIDER of the wallet-cluster "
             "and (coin × calendar-day)-cluster CI (both stored in the JSON artifact); "
             f"code_commit {rep['config']['code_commit']}.*\n"]
    for bk, title in (("A", "PYRAMID-ALT (v1.1-screened units, cost 21.5bp)"),
                      ("B", "MAJORS-NATIVE K30 @8h (cost 5.5bp)")):
        b = rep["books"][bk]
        lines.append(f"\n### Book {bk} — {title} ({b['n_book_entries']:,} entries)\n")
        lines.append("| W | level | n | % | net bp (entry-eq) | gross bp (wallet-eq winsor) "
                     "| boot CI95 (binding cluster) | wallets |\n|---|---|---|---|---|---|---|---|")
        for wk, _ in WINDOWS:
            for name in LEVELS:
                c = b["grid"][wk][name]
                if c["n"] == 0:
                    lines.append(f"| {wk} | {name} | 0 | 0.0% | — | — | — | — |")
                    continue
                ci = c["ci95"]
                cis = (f"[{ci[0]:+.1f}, {ci[1]:+.1f}] ({c.get('ci95_binding', '?')})"
                       if ci else "—")
                lines.append(f"| {wk} | {name} | {c['n']:,} | {c['pct_entries']}% | "
                             f"{c['net_bp_entry_equal']:+.1f} | "
                             f"{c['gross_bp_wallet_equal_winsor']:+.1f} | {cis} | "
                             f"{c['n_wallets']} |")
        lines.append("| 6h-topT | " + " / ".join(
            f"{n}: n={b['variant_6h_tophalf'][n].get('n', 0)}, "
            f"{b['variant_6h_tophalf'][n].get('gross_bp_wallet_equal_winsor', '—')}bp"
            for n in LEVELS) + " | | | | | | |")
        lines.append("\nMonotonicity (wallet-eq winsor gross, solo->pair->crowd): " + "; ".join(
            f"{wk}: {b['monotonicity'][wk]['solo_pair_crowd_bp']} rises={b['monotonicity'][wk]['rises']}"
            for wk, _ in WINDOWS))
        def _gap(g):
            return (f"{g['gap_bp']:+.1f} [{g['ci95'][0]:+.1f}, {g['ci95'][1]:+.1f}] "
                    f"({g.get('ci95_binding', '?')})")
        lines.append("\nCrowd-vs-solo gap (binding cluster boot CI95): " + "; ".join(
            f"{wk}: {_gap(b['crowd_vs_solo'][wk])}"
            if b["crowd_vs_solo"][wk] else f"{wk}: n/a" for wk, _ in WINDOWS) +
            (f"; 6h-topT variant: {_gap(b['variant_crowd_vs_solo'])}"
             if b.get("variant_crowd_vs_solo") else ""))
        lines.append("")
    lines.append("\nArtifact: `data/derived/copy_cohort/consensus_report.json`.\n")
    with OUT_MD.open("a") as fh:
        fh.write("\n".join(lines))
    print(f"-> appended to {OUT_MD}")


if __name__ == "__main__":
    run()
