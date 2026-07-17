"""RECONCILIATION — why wallet-equal robust stats are positive while dollar books are negative.

Burned-fold stamp: all 8 folds 202511-202606 consumed by construction/selection studies.
This is NOT new selection — it explains the disagreement between two measurements of the
same burned data (robust wallet-fold-equal stats vs entry-weighted dollar books).

Steps:
 1. Block-bootstrap (by calendar day, 2000 reps) CIs on the final-slate dollar books
    (Book G gated-alt grinder @8h, Book M majors K30 @8h): total net PnL and net bp/trade.
 2. Decompose Book G accepted trades by their (wallet,fold) candidate-entry count
    (1-2 vs 3+): does the wf>=3 subset reproduce the positive robust stat in dollars?
 3. Rebuild the K100 liquid-alt @1h book (ksweep caches) and the grinder @8h book
    (final_slate_altG caches + trailing-ADV + grinder gate) three ways, $5k clips:
      (i)   all entries (the failed originals),
      (ii)  EX-ANTE activity gate: wallet's FORMATION window (trailing 3 months, from
            lake open_entries) shows >= 0.5 flat-opens/day,
      (iii) gate + ex-ante within-day: entry kept only if the wallet already made >= 2
            candidate entries earlier that same UTC day (counted within the book's own
            post-gate candidate stream, strictly earlier ts).
 4. Verdict: does an ex-ante activity condition reconcile stat-vs-dollar / revive either
    alt book net of 21.5bp RT?

Outputs: data/derived/copy_cohort/reconciliation_report.json
         + "RECONCILIATION" section appended to research/studies/copy_cohort/BACKTEST.md

Run: .venv/bin/python -m research.studies.copy_cohort.reconciliation
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from . import backtest_book as bb
from . import final_backtest as fb   # registers HOLD_MS/COST_BP for books M and G
from . import lake

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
COHORTS = DERIVED / "alt_universe_cohorts.json"
OPECNT_DIR = DERIVED / "reconciliation"
OUT_JSON = DERIVED / "reconciliation_report.json"
OUT_MD = REPO_ROOT / "research" / "studies" / "copy_cohort" / "BACKTEST.md"

FOLDS = bb.FOLDS
DAY_MS = bb.DAY_MS
N_DAYS = bb.N_DAYS
SPAN_T0_MS = bb.SPAN_T0_MS
N_BOOT = 2000
SEED = 20260716
ACT_MIN_OPENS_PER_DAY = 0.5
WITHIN_DAY_MIN_PRIOR = 2
BURST_MIN_SHARE = 0.5          # ii-b: formation share of entries on >=3-entry days


# ------------------------------------------------------------------ bootstrap
def daily_sums(frame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-calendar-day (242) sums of net $, gross $, traded size $ (entry-day attribution)."""
    day_i = np.clip(((frame["ts"] - SPAN_T0_MS) // DAY_MS).astype(np.int64), 0, N_DAYS - 1)
    net = np.zeros(N_DAYS)
    gross = np.zeros(N_DAYS)
    size = np.zeros(N_DAYS)
    np.add.at(net, day_i, frame["net"])
    np.add.at(gross, day_i, frame["gross"])
    np.add.at(size, day_i, frame["size"])
    return net, gross, size


def block_boot(frame, rng) -> dict:
    """Day-block bootstrap (2000 reps) on total net PnL $ and net bp/trade."""
    dnet, dgross, dsize = daily_sums(frame)
    idx = rng.integers(0, N_DAYS, size=(N_BOOT, N_DAYS))
    tot_net = dnet[idx].sum(axis=1)
    tot_size = dsize[idx].sum(axis=1)
    ok = tot_size > 0
    bp = np.full(N_BOOT, np.nan)
    bp[ok] = tot_net[ok] / tot_size[ok] * 1e4
    point_net = float(dnet.sum())
    point_bp = float(dnet.sum() / dsize.sum() * 1e4) if dsize.sum() > 0 else None
    mu, sd = dnet.mean(), dnet.std(ddof=1)
    return {
        "trades": int(frame["ts"].size),
        "total_net_usd": round(point_net, 2),
        "total_gross_usd": round(float(dgross.sum()), 2),
        "net_bp_per_trade": round(point_bp, 2) if point_bp is not None else None,
        "gross_bp_per_trade": round(float(dgross.sum() / dsize.sum() * 1e4), 2) if dsize.sum() > 0 else None,
        "ci_total_net_usd": [round(float(np.percentile(tot_net, q)), 2) for q in (2.5, 97.5)],
        "ci_net_bp": [round(float(np.nanpercentile(bp, q)), 2) for q in (2.5, 97.5)],
        "p_bp_gt0": round(float(np.nanmean(bp > 0)), 4),
        "p_bp_gt20": round(float(np.nanmean(bp > 20)), 4),
        "ann_sharpe_daily": round(float(mu / sd * np.sqrt(365)), 2) if sd > 0 else None,
    }


def sub_frame(frame, m: np.ndarray) -> dict:
    return {k: v[m] for k, v in frame.items() if isinstance(v, np.ndarray)}


# ------------------------------------------------ formation activity (ex-ante)
def formation_activity(wallets_all: set[str]) -> tuple[dict[int, dict[str, float]],
                                                        dict[int, dict[str, float]]]:
    """Returns (rates, burstiness):
      rates[fold][wallet]      = flat-opens/day over the fold's trailing-3-month formation
                                 window (ALL lake open_entries rows / calendar days).
      burstiness[fold][wallet] = share of the wallet's formation entries falling on days
                                 where it made >= 3 entries (wallet trait, ex-ante)."""
    cohorts = json.loads(COHORTS.read_text())
    form_months = {int(f): [int(m) for m in info["formation_months"]]
                   for f, info in cohorts["folds"].items()}
    months = sorted({m for ms in form_months.values() for m in ms})
    OPECNT_DIR.mkdir(parents=True, exist_ok=True)
    wl = sorted(wallets_all)
    con = None
    month_counts: dict[int, dict[str, tuple[int, int]]] = {}   # wallet -> (n, n_bursty)
    for m in months:
        p = OPECNT_DIR / f"opecnt_daily_{m}.parquet"
        if not p.exists():
            if con is None:
                con = lake.connect()
                con.execute("CREATE TEMP TABLE cw AS SELECT UNNEST(?) AS wallet", [wl])
            tmp = str(p) + ".tmp"
            con.execute(f"""COPY (
                WITH d AS (
                  SELECT o.wallet, o.ts // {DAY_MS} AS day_i, count(*) AS n
                  FROM read_parquet('{lake.ope_month_glob(m)}') o JOIN cw USING (wallet)
                  GROUP BY 1, 2)
                SELECT wallet, SUM(n) AS n_opens,
                       SUM(CASE WHEN n >= 3 THEN n ELSE 0 END) AS n_bursty
                FROM d GROUP BY wallet) TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)""")
            Path(tmp).replace(p)
            print(f"  formation opens cached: {m}", flush=True)
        lc = duckdb.connect()
        month_counts[m] = {w: (int(n), int(nb)) for w, n, nb in lc.execute(
            f"SELECT wallet, n_opens, n_bursty FROM read_parquet('{p.as_posix()}')").fetchall()}
        lc.close()
    import calendar
    mdays = {m: calendar.monthrange(m // 100, m % 100)[1] for m in months}
    rates: dict[int, dict[str, float]] = {}
    burst: dict[int, dict[str, float]] = {}
    for f, ms in form_months.items():
        days = sum(mdays[m] for m in ms)
        acc: dict[str, list] = {}
        for m in ms:
            for w, (n, nb) in month_counts[m].items():
                a = acc.setdefault(w, [0, 0])
                a[0] += n
                a[1] += nb
        rates[f] = {w: a[0] / days for w, a in acc.items()}
        burst[f] = {w: (a[1] / a[0] if a[0] > 0 else 0.0) for w, a in acc.items()}
    return rates, burst


def wallet_fold_mask(c, table: dict[int, dict[str, float]], thresh: float) -> np.ndarray:
    keys = {}
    out = np.zeros(c["ts"].size, bool)
    for i, (f, w) in enumerate(zip(c["fold"], c["wallet"])):
        k = (int(f), w)
        v = keys.get(k)
        if v is None:
            v = table.get(int(f), {}).get(w, 0.0) >= thresh
            keys[k] = v
        out[i] = v
    return out


def within_day_mask(c, base: np.ndarray) -> np.ndarray:
    """Keep entry iff wallet already made >= WITHIN_DAY_MIN_PRIOR candidate entries
    strictly earlier that UTC day, counted within the base (post-gate) candidate stream."""
    idx = np.flatnonzero(base)
    ts = c["ts"][idx]
    day = (ts // DAY_MS).astype(np.int64)
    key = np.char.add(np.char.add(c["wallet"][idx], "|"), day.astype(str))
    o = np.argsort(ts, kind="stable")           # candidate stream is ts-sorted already; be safe
    occ = np.zeros(idx.size, np.int64)
    seen: dict[str, list] = {}
    # prior strictly-earlier-ts count per (wallet, day)
    for j in o:
        rec = seen.get(key[j])
        if rec is None:
            seen[key[j]] = [ts[j], 1, 0]         # [last_ts, count_at_last_ts, count_before_last_ts]
            occ[j] = 0
        else:
            if ts[j] > rec[0]:
                rec[2] += rec[1]
                rec[0], rec[1] = ts[j], 1
            else:                                # same ts: not "before this one"
                rec[1] += 1
            occ[j] = rec[2]
    out = np.zeros(c["ts"].size, bool)
    out[idx[occ >= WITHIN_DAY_MIN_PRIOR]] = True
    return out


# ---------------------------------------------------------------------- main
def run() -> None:
    rng = np.random.default_rng(SEED)
    print("loading books ...", flush=True)
    cm, _, _ = fb.load_book_m()
    cg, grinder_mask, verifs, _, _ = fb.load_book_g()
    assert all(v["match"] for v in verifs)
    ca = bb.load_candidates()["A"]

    s1 = lambda c: np.full(c["ts"].size, bb.S1_SIZE)

    # ---- 1. bootstrap CIs on the final-slate dollar books ----
    sim_m = bb.simulate(cm, s1(cm), "M")
    sim_g = bb.simulate(cg, s1(cg), "G", mask=grinder_mask)
    fr_m, fr_g = bb.trade_frames(sim_m), bb.trade_frames(sim_g)
    step1 = {"Book M (majors K30 @8h, RT 5.5bp)": block_boot(fr_m, rng),
             "Book G (gated-alt grinder @8h, RT 21.5bp)": block_boot(fr_g, rng)}
    for k, v in step1.items():
        print(f"{k}: net {v['net_bp_per_trade']}bp CI {v['ci_net_bp']} "
              f"net$ {v['total_net_usd']} CI {v['ci_total_net_usd']}", flush=True)

    # ---- 2. Book G decomposition by (wallet,fold) candidate-entry count ----
    gidx = np.flatnonzero(grinder_mask)
    wf_key_cand = np.char.add(np.char.add(cg["wallet"][gidx], "|"),
                              cg["fold"][gidx].astype(str))
    uk, cnts = np.unique(wf_key_cand, return_counts=True)
    cnt_map = dict(zip(uk.tolist(), cnts.tolist()))
    wf_key_acc = np.char.add(np.char.add(sim_g["wallet"], "|"), sim_g["fold"].astype(str))
    acc_cnt = np.array([cnt_map[k] for k in wf_key_acc])
    m_lo, m_hi = acc_cnt <= 2, acc_cnt >= 3
    step2 = {}
    for lbl, m in (("wf_count_1_2", m_lo), ("wf_count_3plus", m_hi)):
        f = sub_frame(fr_g, m)
        step2[lbl] = block_boot(f, rng)
        step2[lbl]["n_wallet_folds"] = int(np.unique(wf_key_acc[m]).size)
    # robust-style wallet-fold-equal stat on the accepted 3+ subset (gross, winsor p95)
    mk3 = sim_g["mk"][m_hi]
    lim = float(np.percentile(np.abs(mk3), 95)) if mk3.size else 0.0
    u3, inv3 = np.unique(wf_key_acc[m_hi], return_inverse=True)
    wf_mean = np.bincount(inv3, weights=np.clip(mk3, -lim, lim)) / np.bincount(inv3)
    step2["wf3plus_walletfold_equal_gross_winsor_bp"] = round(float(wf_mean.mean()), 2)
    step2["candidate_wf_count_dist"] = {
        "n_wf_total": int(uk.size),
        "n_wf_1_2": int((cnts <= 2).sum()),
        "n_wf_3plus": int((cnts >= 3).sum()),
        "share_entries_from_1_2_wf": round(float(m_lo.mean()), 3),
    }
    print(f"Book G decomposition: 1-2 -> {step2['wf_count_1_2']['net_bp_per_trade']}bp "
          f"(n={step2['wf_count_1_2']['trades']}); 3+ -> "
          f"{step2['wf_count_3plus']['net_bp_per_trade']}bp "
          f"(n={step2['wf_count_3plus']['trades']})", flush=True)

    # ---- 2b. stage decomposition of the grinder stat -> dollar gap ----
    def robust_stat(mk, wf_key):
        lim = float(np.percentile(np.abs(mk), 95))
        mk_w = np.clip(mk, -lim, lim)
        u, inv = np.unique(wf_key, return_inverse=True)
        keep = np.bincount(inv)[inv] >= 3
        u2, inv2 = np.unique(wf_key[keep], return_inverse=True)
        m = np.bincount(inv2, weights=mk_w[keep]) / np.bincount(inv2)
        return {"robust_wf_equal_bp": round(float(m.mean()), 1), "n_wf_robust": int(u2.size),
                "entry_weighted_raw_bp": round(float(mk.mean()), 1), "n_entries": int(mk.size)}

    census = json.loads((DERIVED / "cohort_census.json").read_text())
    grinders = sorted(w["wallet"] for w in census["wallets"] if w["cluster"] == fb.GRINDER_CLUSTER)
    lc = duckdb.connect()
    parts = []
    for f in FOLDS:
        p = (DERIVED / "final_slate_altG" / f"entries_{f}.parquet").as_posix()
        parts.append(lc.execute(f"""SELECT wallet, mk_8h AS mk, {f} AS fold
            FROM read_parquet('{p}') WHERE mk_8h IS NOT NULL AND notl >= 250""").fetchnumpy())
    lc.close()
    w0 = np.concatenate([p["wallet"].astype(str) for p in parts])
    mk0 = np.concatenate([np.asarray(p["mk"], float) for p in parts])
    f0 = np.concatenate([np.asarray(p["fold"], np.int64) for p in parts])
    gm = np.isin(w0, grinders)
    stage0 = robust_stat(mk0[gm], np.char.add(np.char.add(w0[gm], "|"), f0[gm].astype(str)))
    stage1 = robust_stat(cg["mk"][gidx], wf_key_cand)
    stage2b = robust_stat(sim_g["mk"], wf_key_acc)
    ua, inva = np.unique(wf_key_acc, return_inverse=True)
    nb = np.bincount(inva)
    mkb = np.bincount(inva, weights=sim_g["mk"])
    top = np.argsort(nb)[::-1][:5]
    step2["stage_decomposition_grinder"] = {
        "stage0_full_cell_ge250": stage0,
        "stage1_plus_trailing_ADV_screen": stage1,
        "stage2_plus_skip_rules_accepted": stage2b,
        "note": "stage0 = termstructure stat surface (no ADV, no dedup); the robust stat "
                "collapses only at stage2 -> the edge lives in overlapping/repeat entries "
                "inside the 8h hold window that a max-1-concurrent book cannot take",
        "top5_walletfolds_by_accepted_entries": [
            {"wf": str(ua[j]), "n": int(nb[j]), "share": round(float(nb[j] / sim_g["mk"].size), 3),
             "mean_gross_bp": round(float(mkb[j] / nb[j]), 1)} for j in top],
    }
    print("stage decomposition:", stage0["robust_wf_equal_bp"], "->",
          stage1["robust_wf_equal_bp"], "->", stage2b["robust_wf_equal_bp"], flush=True)

    # ---- 3. activity-gated rebuilds ----
    wallets_all = set(ca["wallet"]) | set(cg["wallet"])
    print(f"formation activity for {len(wallets_all)} wallets ...", flush=True)
    rates, burst = formation_activity(wallets_all)

    step3 = {}
    for name, c, base, book in (
            ("K100_liquid_alt_1h", ca, np.ones(ca["ts"].size, bool), "A"),
            ("grinder_8h", cg, grinder_mask, "G")):
        act = wallet_fold_mask(c, rates, ACT_MIN_OPENS_PER_DAY) & base
        wd = within_day_mask(c, act)
        bt = wallet_fold_mask(c, burst, BURST_MIN_SHARE) & base
        variants = {"i_all": base, "ii_activity_gate": act,
                    "ii_b_burstiness_trait_gate": bt, "iii_gate_plus_withinday": wd}
        step3[name] = {}
        for vlbl, m in variants.items():
            sim = bb.simulate(c, s1(c), book, mask=m)
            res = block_boot(bb.trade_frames(sim), rng)
            res["candidates"] = int(m.sum())
            n_wal = np.unique(np.char.add(np.char.add(c["wallet"][m], "|"),
                                          c["fold"][m].astype(str))).size if m.any() else 0
            res["n_wallet_folds"] = int(n_wal)
            step3[name][vlbl] = res
            print(f"{name}/{vlbl}: n={res['trades']} net {res['net_bp_per_trade']}bp "
                  f"CI {res['ci_net_bp']} SR {res['ann_sharpe_daily']}", flush=True)
        step3[name]["gate_pass_walletfolds"] = int(sum(
            1 for f in FOLDS for w in set(c["wallet"][c["fold"] == f])
            if rates.get(f, {}).get(w, 0.0) >= ACT_MIN_OPENS_PER_DAY))
        step3[name]["burst_pass_walletfolds"] = int(sum(
            1 for f in FOLDS for w in set(c["wallet"][c["fold"] == f])
            if burst.get(f, {}).get(w, 0.0) >= BURST_MIN_SHARE))
        step3[name]["total_walletfolds"] = int(sum(
            len(set(c["wallet"][c["fold"] == f])) for f in FOLDS))
        # descriptive: formation burstiness vs forward per-wallet-fold copy markout (gross)
        bidx = np.flatnonzero(base)
        wf = np.char.add(np.char.add(c["wallet"][bidx], "|"), c["fold"][bidx].astype(str))
        uwf, inv = np.unique(wf, return_inverse=True)
        fwd_mk = np.bincount(inv, weights=c["mk"][bidx]) / np.bincount(inv)
        bvals = np.array([burst.get(int(k.split("|")[1]), {}).get(k.split("|")[0], 0.0)
                          for k in uwf])
        ok = np.isfinite(fwd_mk)
        if ok.sum() >= 3 and np.std(bvals[ok]) > 0 and np.std(fwd_mk[ok]) > 0:
            pear = float(np.corrcoef(bvals[ok], fwd_mk[ok])[0, 1])
            rb = np.argsort(np.argsort(bvals[ok]))
            rm = np.argsort(np.argsort(fwd_mk[ok]))
            spear = float(np.corrcoef(rb, rm)[0, 1])
        else:
            pear = spear = None
        step3[name]["burstiness_vs_fwd_walletfold_mk"] = {
            "n_wallet_folds": int(ok.sum()),
            "pearson": round(pear, 4) if pear is not None else None,
            "spearman": round(spear, 4) if spear is not None else None,
            "note": "descriptive; fwd mk = per-wallet-fold mean gross candidate markout"}

    report = {
        "label": "RECONCILIATION — wallet-equal robust stats vs entry-weighted dollar books "
                 "(burned folds 202511-202606; no new selection; explanatory only)",
        "config": {
            "n_boot": N_BOOT, "seed": SEED, "block": "calendar day (242)",
            "activity_gate": f"formation (trailing 3 months, lake open_entries, all rows) "
                             f">= {ACT_MIN_OPENS_PER_DAY} flat-opens/day, ex-ante",
            "within_day": f"entry kept iff wallet already made >= {WITHIN_DAY_MIN_PRIOR} "
                          "candidate entries strictly earlier that UTC day, counted within "
                          "the book's post-gate candidate stream (ex-ante)",
            "burstiness_trait_gate": f"ii-b: share of the wallet's FORMATION entries falling "
                                     f"on days it made >= 3 entries; keep wallets with share "
                                     f">= {BURST_MIN_SHARE} (ex-ante trait, no day-state)",
            "sizing": "S1 $5k/entry; same skip rules as final_backtest",
        },
        "step1_dollar_book_cis": step1,
        "step2_bookG_by_walletfold_count": step2,
        "step3_activity_gated_rebuilds": step3,
    }
    OUT_JSON.write_text(json.dumps(report, indent=1))
    print(f"-> {OUT_JSON}", flush=True)
    return report


if __name__ == "__main__":
    run()
