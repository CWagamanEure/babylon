"""CORRECTED pipeline (user spec 2026-07-09, after the family-selection critique):
 1 neutral eligibility ONLY: volume, history, episode count, TWAP/liq share, recent activity
 2 for EVERY eligible wallet-coin: day-block bootstrap of the MAX statistic across horizons
 3 tested against the actual cost hurdle (H0: edge <= 5bp at all horizons)
 4 BH-FDR across the ENTIRE eligible family (no outcome-based prefilter is charged less)
 5 concentration/stability diagnostics attached as LABELS, never gates
 6 freeze basket (eligibility already requires activity near the discovery cutoff)
 7 OOS primary: frozen-basket net performance per calendar day
 8 OOS secondary: per-wallet net p-values -> BH
Two OOS verdicts reported separately: conditional skill vs static-list deployability.
Resolution: two-stage bootstrap (B0=5,000 everyone; B1=200,000 refinement for p<=0.01) so the p-floor
(1/(B+1), plus-one correction, never zero) sits below the BH rank-1 threshold for isolated signals.

    python -m research.data.family_wf discover
    python -m research.data.family_wf oos
"""
from __future__ import annotations
import math
import sys
import numpy as np
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from .markout import HORIZONS, COINS, REPO_ROOT
from .features_markout import ENTRY_LAG_MAX_S

HZ = ["1h", "2h", "4h", "8h"]
DISC = ("epoch_ms(TIMESTAMP '2025-08-01')", "epoch_ms(TIMESTAMP '2026-02-01')")
WF = ("epoch_ms(TIMESTAMP '2026-02-01')", "epoch_ms(TIMESTAMP '2026-06-29')")
# step 1 — neutral eligibility (activity/data-quality only; NOTHING outcome-based)
MIN_EP = 20; MIN_DAYS = 10; MIN_VOL = 1e6; TWAP_MAX = 0.30; LIQ_MAX = 0.10
RECENT_MS = 30 * 86_400_000          # active near cutoff: >=1 close in last 30 days of discovery
COST = 5.0                           # bp round-trip; the H0 hurdle AND the OOS net line
Q = 0.10
B0, B1, REFINE_P = 5_000, 200_000, 0.01
SEED = 20260709
OUT = REPO_ROOT / "data" / "derived" / "family_wf"


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT/'.tmp'}'")
    return c


def _eligible(con, lo, hi):
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    rows = con.execute(f"""SELECT wallet, coin FROM (
        SELECT wallet, coin, count(*) n_ep, count(DISTINCT close_ts // 86400000) n_days,
          sum(initial_notional_usd + total_added_notional_usd) vol_usd,
          sum(n_flagged_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) twap_sh,
          sum(n_liq_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) liq_sh,
          max(close_ts) last_close
        FROM read_parquet('{ep}', hive_partitioning=true)
        WHERE close_ts >= {lo} AND close_ts < {hi} GROUP BY wallet, coin
        HAVING n_ep>={MIN_EP} AND n_days>={MIN_DAYS} AND vol_usd>={MIN_VOL}
           AND coalesce(twap_sh,0)<{TWAP_MAX} AND coalesce(liq_sh,0)<{LIQ_MAX}
           AND last_close >= ({hi}) - {RECENT_MS})""").fetchall()
    return {(w, c) for (w, c) in rows}


def _pull(con, coin, wallets, lo, hi):
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    g = ", ".join(f"CASE WHEN (m.entry_bar_ts+{HORIZONS[h]})<={hi} THEN m.raw_markout_{h} END AS g_{h}" for h in HZ)
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?)", [(w,) for w in wallets])
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts//86400000 AS day, m.entry_bar_ts, {g}
      FROM read_parquet('{mk}') m JOIN wl USING(wallet)
      WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi} AND m.close_ts<={hi}
        AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S}""").fetchnumpy()


def _fcol(e, name):
    """Audit-F1 fix: DuckDB fetchnumpy returns MaskedArray for nullable columns; np.asarray DROPS the mask,
    turning NULLs into ~0.0 garbage (dead NaN-censoring). Fill masked slots with NaN explicitly."""
    a = e[name]
    if isinstance(a, np.ma.MaskedArray):
        return np.ma.filled(a.astype(float), np.nan)
    return np.asarray(a, float)


def _groups(e):
    wal = np.asarray(e["wallet"], dtype=object)
    order = np.argsort(wal, kind="stable")
    uq, first = np.unique(wal[order], return_index=True)
    return order, uq, np.append(np.sort(first), len(wal))


def _daysums(vals4, days):
    """vals4: (n, nhz) with NaN; days: (n,). Returns uday, day_sum (nd,nhz), day_cnt (nd,nhz)."""
    uday, inv = np.unique(days, return_inverse=True)
    nd, nh = len(uday), vals4.shape[1]
    dsum = np.zeros((nd, nh)); dcnt = np.zeros((nd, nh))
    ok = ~np.isnan(vals4)
    v0 = np.where(ok, vals4, 0.0)
    for j in range(nh):
        np.add.at(dsum[:, j], inv, v0[:, j])
        np.add.at(dcnt[:, j], inv, ok[:, j].astype(float))
    return uday, dsum, dcnt


def _maxstat_p(dsum, dcnt, use, rng, B):
    """One-sided max-statistic day-block bootstrap p for H0: mean_h <= COST for all h in `use`.
    Plus-one corrected; never zero. Returns (p, sel_idx, obs_means, se)."""
    nd = dsum.shape[0]
    tot_c = np.maximum(dcnt.sum(0), 1)
    obs = dsum.sum(0) / tot_c
    T_parts, se = None, None
    means_all = []
    for start in range(0, B, 20_000):                       # chunked for memory
        nb = min(20_000, B - start)
        picks = rng.integers(0, nd, size=(nb, nd))
        s = dsum[picks].sum(1); c = np.maximum(dcnt[picks].sum(1), 1)
        means_all.append(s / c)
    means = np.concatenate(means_all)                        # (B, nhz)
    se = means.std(0, ddof=1); se = np.where(se > 1e-9, se, 1e-9)
    z_obs = (obs - COST) / se
    z_obs_use = np.where(use, z_obs, -np.inf)
    T_obs = z_obs_use.max()
    sel = int(np.argmax(z_obs_use))
    z_null = (means - obs[None, :]) / se[None, :]
    z_null = np.where(use[None, :], z_null, -np.inf)
    T_b = z_null.max(1)
    p = (1 + int(np.sum(T_b >= T_obs))) / (B + 1)
    return p, sel, obs, se


def _labels(v, dd, tt, mid):
    """Step 5 — concentration/stability diagnostics as LABELS (never gates), at the selected horizon."""
    ud = np.unique(dd)
    bd = max(ud, key=lambda k: v[dd == k].mean()) if len(ud) > 1 else ud[0]
    lab = {"lbl_drop_best_day_pos": bool(v[dd != bd].mean() > 0) if len(ud) > 1 else False,
           "lbl_drop_best_trade_pos": bool(np.delete(v, np.argmax(v)).mean() > 0) if len(v) > 1 else False}
    h1, h2 = v[tt < mid], v[tt >= mid]
    lab["lbl_both_halves_pos"] = bool(len(h1) and len(h2) and h1.mean() > 0 and h2.mean() > 0)
    return lab


def discover():
    rng = np.random.default_rng(SEED)
    con = _con()
    lo_ms, hi_ms = [con.execute(f"SELECT {x}").fetchone()[0] for x in DISC]
    mid_ms = (lo_ms + hi_ms) // 2
    elig = _eligible(con, *DISC)
    print(f"step1 neutral-eligible (incl. active in last 30d of discovery): {len(elig):,} wallet-coins")
    fam = []          # every tested wallet-coin gets a p — this is the BH family
    for coin in COINS:
        ws = sorted({w for (w, c) in elig if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, *DISC)
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]; ebt = np.asarray(e["entry_bar_ts"])[order]
        G = np.column_stack([_fcol(e, f"g_{h}")[order] for h in HZ])
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
            uday, dsum, dcnt = _daysums(G[s:ez], day[s:ez])
            # neutral observation-count condition per horizon (data quantity, not outcome)
            use = (dcnt.sum(0) >= MIN_EP) & ((dcnt > 0).sum(0) >= MIN_DAYS)
            if not use.any() or len(uday) < MIN_DAYS:
                continue
            p, sel, obs, se = _maxstat_p(dsum, dcnt, use, rng, B0)
            fam.append({"wallet": w, "coin": coin, "sel": sel, "p": p, "obs": obs, "use": use,
                        "s": s, "ez": ez, "coin_key": coin})
        print(f"  {coin}: family so far {len(fam):,}", flush=True)
        # keep per-coin arrays for refinement + labels
        for r in fam:
            if r["coin_key"] == coin and "G" not in r:
                r["G"] = G[r["s"]:r["ez"]]; r["day"] = day[r["s"]:r["ez"]]; r["ebt"] = ebt[r["s"]:r["ez"]]
    m = len(fam)
    nref = sum(1 for r in fam if r["p"] <= REFINE_P)
    print(f"\nstep2-3 family tested: {m:,}  (stage-A B={B0:,}; refining {nref:,} with p<= {REFINE_P} at B={B1:,})")
    for r in fam:
        if r["p"] <= REFINE_P:
            uday, dsum, dcnt = _daysums(r["G"], r["day"])
            r["p"], r["sel"], r["obs"], _ = _maxstat_p(dsum, dcnt, r["use"], rng, B1)
    # persist the full family's p-values (for BH verification)
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([
        {"wallet": r["wallet"], "coin": r["coin"], "sel_horizon": HZ[r["sel"]],
         "obs_gross_bp": round(float(r["obs"][r["sel"]]), 2), "p": r["p"]} for r in fam]),
        OUT / "family_pvalues.parquet")
    # step 4 — BH across the ENTIRE family
    pv = sorted((r["p"], i) for i, r in enumerate(fam))
    k_star, thr = 0, 0.0
    for k, (p, i) in enumerate(pv, 1):
        if p <= (k / m) * Q:
            k_star, thr = k, p
    surv = [fam[i] for (p, i) in pv[:k_star]]
    print(f"step4 BH q={Q} over m={m:,}: {len(surv)} survive (p<={thr:.3g}; rank-1 threshold {Q/m:.2e}; "
          f"floor {1/(B1+1):.2e})")
    rows = []
    for r in surv:
        h = HZ[r["sel"]]
        v = r["G"][:, r["sel"]]; mm = ~np.isnan(v)
        lab = _labels(v[mm], r["day"][mm], r["ebt"][mm], mid_ms)
        rows.append({"wallet": r["wallet"], "coin": r["coin"], "horizon": h,
                     "disc_gross_bp": round(float(r["obs"][r["sel"]]), 2), "disc_p": r["p"],
                     "disc_nd": int(len(np.unique(r["day"][mm]))), **lab})
        print(f"   {r['wallet']} {r['coin']:4s} @{h} gross={rows[-1]['disc_gross_bp']:+.1f}bp "
              f"p={r['p']:.3g} nd={rows[-1]['disc_nd']} labels={ {k: v for k, v in lab.items()} }")
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows if rows else [{"wallet": "", "coin": "", "horizon": "",
        "disc_gross_bp": 0.0, "disc_p": 1.0, "disc_nd": 0, "lbl_drop_best_day_pos": False,
        "lbl_drop_best_trade_pos": False, "lbl_both_halves_pos": False}][:0]), OUT / "frozen_list.parquet")
    print(f"step6 frozen -> {OUT}/frozen_list.parquet ({len(rows)} wallets; equal weight; cost={COST}bp)")


def oos():
    rng = np.random.default_rng(SEED + 1)
    con = _con()
    frozen = {(r["wallet"], r["coin"]): r["horizon"] for r in pq.read_table(OUT / "frozen_list.parquet").to_pylist()}
    print(f"walk-forward on {len(frozen)} frozen (unchanged; cost={COST}bp)")
    if not frozen:
        print("VERDICT conditional skill: NOT TESTABLE (empty frozen list).")
        print("VERDICT static-list deployability: NOT APPLICABLE (nothing survived discovery FDR)."); return
    per_day, trader = {}, {}
    lo_ms, hi_ms = [con.execute(f"SELECT {x}").fetchone()[0] for x in WF]
    wf_days_total = (hi_ms - lo_ms) // 86_400_000
    for coin in COINS:
        ws = sorted({w for (w, c) in frozen if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, *WF)
        if len(np.asarray(e["wallet"])) == 0:
            for w in ws:
                trader[(w, coin)] = {"testable": False, "n": 0}
            continue
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]
        G = {h: _fcol(e, f"g_{h}")[order] for h in HZ}
        seen = set()
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]; seen.add(w)
            h = frozen[(w, coin)]
            v = G[h][s:ez]; mm = ~np.isnan(v)
            vv, dd = v[mm], day[s:ez][mm]
            if len(vv) < 5 or len(np.unique(dd)) < MIN_DAYS:
                trader[(w, coin)] = {"testable": False, "n": int(len(vv))}
                continue
            uday, inv = np.unique(dd, return_inverse=True); nd = len(uday)
            idx = [np.where(inv == k)[0] for k in range(nd)]
            obs = float(vv.mean())
            means = np.array([vv[np.concatenate([idx[k] for k in rng.integers(0, nd, nd)])].mean()
                              for _ in range(10_000)])
            p_net = (1 + int(np.sum(means <= COST))) / 10_001 if obs > COST else 1.0
            trader[(w, coin)] = {"testable": True, "p_net": p_net, "gross": obs, "net": obs - COST,
                                 "nd": nd, "n": int(len(vv)), "h": h}
            for d in uday:
                per_day.setdefault(d, []).append(float(vv[dd == d].mean()))
        for w in ws:
            if w not in seen:
                trader[(w, coin)] = {"testable": False, "n": 0}
        print(f"  {coin}: processed", flush=True)
    testable = {k: t for k, t in trader.items() if t.get("testable")}
    n_attrit = len(frozen) - len(testable)
    # --- two verdicts, per the critique ---
    print(f"\n== DEPLOYABILITY (static frozen list) ==")
    print(f"frozen {len(frozen)} | testable {len(testable)} | attrition {n_attrit} "
          f"({100*n_attrit/len(frozen):.0f}%) | basket-active days {len(per_day)}/{wf_days_total}")
    if testable:
        days = sorted(per_day)
        bd = np.array([float(np.mean(per_day[d])) for d in days]); nd = len(bd)
        obs = float(bd.mean())
        boots = np.array([bd[rng.integers(0, nd, nd)].mean() for _ in range(10_000)])
        pA = (1 + int(np.sum(boots <= COST))) / 10_001
        se = float(bd.std(ddof=1)) / math.sqrt(nd)
        print(f"PRIMARY basket: gross={obs:+.2f}bp net={obs-COST:+.2f}bp "
              f"CI_gross[{obs-1.96*se:+.2f},{obs+1.96*se:+.2f}] p(net>0)={pA:.4g} MDE={2.8*se:.2f}bp")
        print(f"\n== CONDITIONAL SKILL (when they trade) ==")
        m2 = len(testable)
        pv = sorted((t["p_net"], k) for k, t in testable.items())
        k_star, thr = 0, 0.0
        for k, (p, kk) in enumerate(pv, 1):
            if p <= (k / m2) * Q:
                k_star, thr = k, p
        surv = {kk for (p, kk) in pv[:k_star]}
        print(f"SECONDARY per-wallet net>0, BH q={Q} over {m2}: {len(surv)} confirmed")
        rows = []
        for kk in sorted(testable, key=lambda kk: testable[kk]["p_net"]):
            t = testable[kk]
            rows.append({"wallet": kk[0], "coin": kk[1], "horizon": t["h"],
                         "oos_gross_bp": round(t["gross"], 2), "oos_net_bp": round(t["net"], 2),
                         "oos_p_net": t["p_net"], "oos_nd": t["nd"], "oos_n": t["n"],
                         "confirmed_net": kk in surv})
            print(f"   {kk[0]} {kk[1]:4s} @{t['h']} gross={t['gross']:+.1f} net={t['net']:+.1f}bp "
                  f"nd={t['nd']} p={t['p_net']:.4g}{'  CONFIRMED' if kk in surv else ''}")
        pq.write_table(pa.Table.from_pylist(rows), OUT / "oos_results.parquet")
        print(f"-> {OUT}/oos_results.parquet")
    else:
        print("PRIMARY basket: no active days — deployability FAILED by attrition alone.")
        print(f"\n== CONDITIONAL SKILL ==\nINCONCLUSIVE: insufficient OOS trades for every frozen wallet.")


if __name__ == "__main__":
    (discover if (len(sys.argv) > 1 and sys.argv[1] == "discover") else oos)()
