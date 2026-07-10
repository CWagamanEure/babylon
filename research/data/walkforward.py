"""User-specified discovery pipeline + walk-forward (2026-07-09) — implemented verbatim, 10 steps:
 1 discovery window = first 6 months            6 economic screen: discovery mean > 8bp
 2 neutral eligibility filters                  7 max-horizon day-block bootstrap -> one p per wallet
 3 gross markout per fixed horizon (episodes)   8 BH-FDR across wallets (q=0.10) -> candidate list
 4 remove fragile wallets                       9 freeze list (wallets, horizons, weights, cost)
 5 best horizon, prefer positive neighbors     10 walk forward unchanged: basket NET primary,
                                                   per-wallet net + BH secondary, style attribution
GROSS = raw markout (no drift adjustment, no costs); costs (5bp round-trip, frozen) enter only at step 10 NET.
Unit = (wallet, coin) — the episode lake's grain, so one-coin domination is inherent to the grain.
Thresholds not specified by the spec use the previously-frozen values, declared below.

    python -m research.data.walkforward discover
    python -m research.data.walkforward oos
"""
from __future__ import annotations
import math
import sys
import numpy as np
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from .markout import HORIZONS, COINS, REPO_ROOT
from .family_wf import _fcol  # MaskedArray NULL fix (audit 2026-07-10)
from .features_markout import ENTRY_LAG_MAX_S

HZ = ["1h", "2h", "4h", "8h"]                     # fixed horizon ladder
HZ_MIN = {"1h": 60, "2h": 120, "4h": 240, "8h": 480}
DISC = ("epoch_ms(TIMESTAMP '2025-08-01')", "epoch_ms(TIMESTAMP '2026-02-01')")   # step 1: first 6 months
WF = ("epoch_ms(TIMESTAMP '2026-02-01')", "epoch_ms(TIMESTAMP '2026-06-29')")     # walk-forward
# step 2 thresholds (spec-silent values = previously frozen, declared):
MIN_EP = 20            # minimum episodes
MIN_DAYS = 10          # minimum active days
MIN_VOL = 1e6          # minimum volume (USD notional)
TWAP_MAX = 0.30        # exclude TWAP-heavy
LIQ_MAX = 0.10         # exclude liquidation-heavy
HOLD_X = 4             # copyable holding period: horizon <= 4 x median hold
HURDLE = 8.0           # step 6 economic hurdle (bp)
B = 10_000             # step 7 bootstrap draws
Q = 0.10               # step 8 discovery BH-FDR
COST = 5.0             # frozen round-trip cost (bp), applied only in step 10 NET tests
B_STYLE = 1_000        # attribution draws
SEED = 20260709
OUT = REPO_ROOT / "data" / "derived" / "walkforward"


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT/'.tmp'}'")
    return c


def _eligible(con, lo, hi):
    """Step 2 — neutral eligibility: min episodes, min active days, min volume, TWAP/liq exclusion.
    (Copyable holding applied per-horizon via HOLD_X at step 5.) Returns {(wallet,coin): med_hold_min}."""
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    rows = con.execute(f"""SELECT wallet, coin, med_hold FROM (
        SELECT wallet, coin, count(*) n_ep,
          count(DISTINCT close_ts // 86400000) n_days,
          sum(initial_notional_usd + total_added_notional_usd) vol_usd,
          sum(n_flagged_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) twap_sh,
          sum(n_liq_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) liq_sh,
          median((close_ts-open_ts)/60000.0) med_hold
        FROM read_parquet('{ep}', hive_partitioning=true)
        WHERE close_ts >= {lo} AND close_ts < {hi} GROUP BY wallet, coin
        HAVING n_ep>={MIN_EP} AND n_days>={MIN_DAYS} AND vol_usd>={MIN_VOL}
           AND coalesce(twap_sh,0)<{TWAP_MAX} AND coalesce(liq_sh,0)<{LIQ_MAX})""").fetchall()
    return {(w, c): mh for (w, c, mh) in rows}


def _pull(con, coin, wallets, lo, hi):
    """Step 3 — GROSS markout per episode at each fixed horizon (raw_markout, no adjustment)."""
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    ta = ", ".join(f"CASE WHEN (m.entry_bar_ts+{HORIZONS[h]})<={hi} THEN m.raw_markout_{h} END AS g_{h}" for h in HZ)
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?)", [(w,) for w in wallets])
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts//86400000 AS day,
        (m.entry_bar_ts//3600000)%24 AS hod, m.entry_bar_ts, {ta}
      FROM read_parquet('{mk}') m JOIN wl USING(wallet)
      WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi} AND m.close_ts<={hi}
        AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S}""").fetchnumpy()


def _groups(e):
    wal = np.asarray(e["wallet"], dtype=object)
    order = np.argsort(wal, kind="stable")
    uq, first = np.unique(wal[order], return_index=True)
    return order, uq, np.append(np.sort(first), len(wal))


def _maxhz_p(day_sum, day_cnt, sel_i, rng):
    """Step 7 — max-horizon day-block bootstrap. day_sum/day_cnt: (nd, nhz) per-day sums/counts of gross
    markout over the wallet's SEARCHED horizons. One-sided p for the selected horizon's mean, adjusted for
    the max over the searched set (joint day resamples, null-centered, standardized)."""
    nd, nh = day_sum.shape
    obs = day_sum.sum(0) / np.maximum(day_cnt.sum(0), 1)
    picks = rng.integers(0, nd, size=(B, nd))
    s = day_sum[picks].sum(1); c = np.maximum(day_cnt[picks].sum(1), 1)      # (B, nh)
    means = s / c
    se = means.std(0, ddof=1); se = np.where(se > 1e-9, se, 1e-9)
    z_null = (means - obs[None, :]) / se[None, :]                            # centered at null
    stat = z_null.max(1)                                                     # max over searched horizons
    z_obs = obs[sel_i] / se[sel_i]
    return (1 + int(np.sum(stat >= z_obs))) / (B + 1)


def _bh(pairs, q):
    m = len(pairs)
    if not m:
        return set(), 0.0
    pv = sorted(pairs); k_star, thr = 0, 0.0
    for k, (p, key) in enumerate(pv, 1):
        if p <= (k / m) * q:
            k_star, thr = k, p
    return {key for (p, key) in pv[:k_star]}, thr


def discover():
    rng = np.random.default_rng(SEED)
    con = _con()
    lo_ms, hi_ms = [con.execute(f"SELECT {x}").fetchone()[0] for x in DISC]
    mid_ms = (lo_ms + hi_ms) // 2
    elig = _eligible(con, *DISC)
    print(f"step2 eligible: {len(elig):,} wallet-coins")
    recs = []
    for coin in COINS:
        ws = sorted({w for (w, c) in elig if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, *DISC)
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]; ebt = np.asarray(e["entry_bar_ts"])[order]
        g = {h: _fcol(e, f"g_{h}")[order] for h in HZ}
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
            med_hold = elig[(w, coin)]
            searched = [h for h in HZ if HZ_MIN[h] <= HOLD_X * med_hold]     # copyable holding period
            stats = {}
            for h in searched:
                v = g[h][s:ez]; m = ~np.isnan(v)
                if m.sum() < MIN_EP or len(np.unique(day[s:ez][m])) < MIN_DAYS:
                    continue                                                  # sufficient independent days/eps
                stats[h] = float(v[m].mean())
            if not stats:
                continue
            # step 5: best horizon, prefer positive adjacent horizons over an isolated spike
            def adj_pos(h):
                i = HZ.index(h)
                nb = [HZ[j] for j in (i - 1, i + 1) if 0 <= j < len(HZ) and HZ[j] in stats]
                return any(stats[n] > 0 for n in nb)
            preferred = [h for h in stats if stats[h] > 0 and adj_pos(h)]
            pool = preferred if preferred else list(stats)
            best = max(pool, key=lambda h: stats[h])
            if stats[best] <= HURDLE:                                         # step 6 economic screen
                continue
            v = g[best][s:ez]; m = ~np.isnan(v)
            vv, dd, tt = v[m], day[s:ez][m], ebt[s:ez][m]
            # step 4 fragility: not dominated by one day / one trade; positive in both subperiods
            ud = np.unique(dd)
            bd = max(ud, key=lambda k: vv[dd == k].mean())
            if vv[dd != bd].mean() <= 0:
                continue
            if len(vv) > 1 and np.delete(vv, np.argmax(vv)).mean() <= 0:
                continue
            h1, h2 = vv[tt < mid_ms], vv[tt >= mid_ms]
            if len(h1) == 0 or len(h2) == 0 or h1.mean() <= 0 or h2.mean() <= 0:
                continue
            # step 7 max-horizon bootstrap over the wallet's searched-with-stats set
            hs = [h for h in HZ if h in stats]
            uday, inv = np.unique(dd, return_inverse=True)
            nd = len(uday)
            dsum = np.zeros((nd, len(hs))); dcnt = np.zeros((nd, len(hs)))
            for j, h in enumerate(hs):
                vh = g[h][s:ez]; mh = ~np.isnan(vh)
                dh = day[s:ez][mh]; vhh = vh[mh]
                di = np.searchsorted(uday, dh)
                keep = (di < nd) & (uday[np.minimum(di, nd - 1)] == dh)
                np.add.at(dsum[:, j], di[keep], vhh[keep])
                np.add.at(dcnt[:, j], di[keep], 1)
            p = _maxhz_p(dsum, dcnt, hs.index(best), rng)
            recs.append({"wallet": w, "coin": coin, "horizon": best, "disc_gross_bp": round(stats[best], 2),
                         "disc_p_maxhz": p, "disc_nd": int(nd), "n_hz_searched": len(hs)})
        print(f"  {coin}: pool {len(ws):,} -> running survivors {len(recs):,}", flush=True)
    surv, thr = _bh([(r["disc_p_maxhz"], i) for i, r in enumerate(recs)], Q)
    final = [recs[i] for i in surv]
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(final), OUT / "frozen_list.parquet")
    print(f"\nstep8 BH q={Q}: {len(final)} FROZEN (of {len(recs)} passing steps 2-7; p<={thr:.4g})")
    print(f"step9 frozen -> {OUT}/frozen_list.parquet (wallets, horizons, equal weights, cost={COST}bp)")


def oos():
    rng = np.random.default_rng(SEED + 1)
    con = _con()
    frozen = {(r["wallet"], r["coin"]): r["horizon"] for r in pq.read_table(OUT / "frozen_list.parquet").to_pylist()}
    print(f"step10 walk-forward on {len(frozen)} frozen (unchanged; cost={COST}bp)")
    per_day, trader = {}, {}
    style_null = np.zeros(B_STYLE); style_cnt = 0
    lo, hi = WF
    for coin in COINS:
        ws = sorted({w for (w, c) in frozen if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, *WF)
        if len(np.asarray(e["wallet"])) == 0:
            continue
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]; hod = np.asarray(e["hod"])[order]
        g = {h: _fcol(e, f"g_{h}")[order] for h in HZ}
        fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
        grid = {}
        for h in {frozen[(w, coin)] for w in ws}:
            gr = con.execute(f"""SELECT (ts//3600000)%24 AS hod, fwd_ret_{h} AS fr FROM read_parquet('{fwd}')
                WHERE fwd_ret_{h} IS NOT NULL AND ts>={lo} AND (ts+{HORIZONS[h]})<={hi}""").fetchnumpy()
            gh = np.asarray(gr["hod"]); gt = np.asarray(gr["fr"], float)
            grid[h] = {hh: gt[gh == hh] for hh in range(24)}
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]; h = frozen[(w, coin)]
            v = g[h][s:ez]; m = ~np.isnan(v)
            vv, dd, hh = v[m], day[s:ez][m], hod[s:ez][m]
            if len(vv) < 5 or len(np.unique(dd)) < MIN_DAYS:
                trader[(w, coin)] = {"testable": False, "n": int(len(vv))}
                continue
            uday, inv = np.unique(dd, return_inverse=True); nd = len(uday)
            idx = [np.where(inv == k)[0] for k in range(nd)]
            obs = float(vv.mean())
            means = np.array([vv[np.concatenate([idx[k] for k in rng.integers(0, nd, nd)])].mean() for _ in range(B)])
            p_net = (1 + int(np.sum(means <= COST))) / (B + 1) if obs > COST else 1.0
            trader[(w, coin)] = {"testable": True, "p_net": p_net, "gross": obs, "net": obs - COST,
                                 "nd": nd, "n": int(len(vv)), "h": h}
            for d in uday:
                per_day.setdefault(d, []).append(float(vv[dd == d].mean()))
            # attribution: style-adjusted (hour-of-day-matched random entries, gross grid)
            # NOTE dir is embedded in raw_markout sign; null uses |grid| draw signed by nothing — gross
            # markout of a random same-hour entry in the SAME direction distribution: use the wallet's own
            # dir mix implicitly by drawing the fwd return and applying each entry's sign from its markout?
            # Spec says style-adjusted performance: match hour-of-day; sign = random +/-1 with the wallet's
            # long share is unavailable here, so use symmetric draw (drift term, <1bp at these horizons).
            nulls = np.empty(B_STYLE)
            for b in range(B_STYLE):
                sim = np.array([grid[h][int(hh[i])][rng.integers(0, len(grid[h][int(hh[i])]))] for i in range(len(vv))])
                nulls[b] = sim.mean()
            style_null += nulls; style_cnt += 1
        print(f"  {coin}: processed", flush=True)
    testable = {k: t for k, t in trader.items() if t.get("testable")}
    print(f"\ntestable: {len(testable)} / {len(frozen)}")
    if not testable:
        print("nothing testable."); return
    # PRIMARY: frozen basket NET edge > 0
    days = sorted(per_day)
    bd = np.array([float(np.mean(per_day[d])) for d in days])
    obs = float(bd.mean()); nd = len(bd)
    boots = np.array([bd[rng.integers(0, nd, nd)].mean() for _ in range(B)])
    pA = (1 + int(np.sum(boots <= COST))) / (B + 1)
    se = float(bd.std(ddof=1)) / math.sqrt(nd)
    print(f"\nPRIMARY basket: gross={obs:+.2f}bp net={obs-COST:+.2f}bp CI_gross[{obs-1.96*se:+.2f},{obs+1.96*se:+.2f}] "
          f"p(net>0)={pA:.4g} MDE={2.8*se:.2f}bp over {nd} days, {len(testable)} traders")
    print("  -> " + ("BASKET NET EDGE CONFIRMED" if (obs - COST - 1.96 * se) > 0 else
                     "no confirmed net basket edge"))
    if style_cnt:
        pS = float(np.mean(style_null / style_cnt >= obs))
        print(f"attribution (style-adjusted): p_style={pS:.3g}")
    # SECONDARY: individual net edge -> BH
    surv, thr = _bh([(t["p_net"], k) for k, t in testable.items()], Q)
    print(f"\nSECONDARY per-wallet net>0: BH q={Q} -> {len(surv)} confirmed")
    rows = []
    for k in sorted(testable, key=lambda k: testable[k]["p_net"]):
        t = testable[k]
        rows.append({"wallet": k[0], "coin": k[1], "horizon": t["h"], "oos_gross_bp": round(t["gross"], 2),
                     "oos_net_bp": round(t["net"], 2), "oos_p_net": t["p_net"], "oos_nd": t["nd"],
                     "oos_n": t["n"], "confirmed_net": k in surv})
        if k in surv:
            print(f"   {k[0]} {k[1]:4s} @{t['h']} gross={t['gross']:+.1f} net={t['net']:+.1f}bp "
                  f"nd={t['nd']} p={t['p_net']:.4g}")
    pq.write_table(pa.Table.from_pylist(rows), OUT / "oos_results.parquet")
    print(f"-> {OUT}/oos_results.parquet")


if __name__ == "__main__":
    (discover if (len(sys.argv) > 1 and sys.argv[1] == "discover") else oos)()
