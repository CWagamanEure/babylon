"""PRE-REGISTERED confirmatory protocol — docs/CONFIRMATORY_PREREG.md (frozen 2026-07-09). Implements it
verbatim: Stage-1 discovery (eligibility E1-E8, selection S1-S4, BH q=.10) -> freeze candidates.parquet ->
Stage-2 OOS (Tier A basket primary, Tier B per-trader secondary, style-matched attribution). All results carry
the data-contamination asterisk until the forward re-run.

    python -m research.data.confirmatory discover
    python -m research.data.confirmatory oos
"""
from __future__ import annotations
import json
import math
import sys
import numpy as np
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from .markout import HORIZONS, COINS, REPO_ROOT
from .family_wf import _fcol  # MaskedArray NULL fix (audit 2026-07-10)
from .features_markout import ENTRY_LAG_MAX_S

HZ = ["1h", "2h", "4h", "8h"]
HZ_MIN = {"1h": 60, "2h": 120, "4h": 240, "8h": 480}
DISC = ("epoch_ms(TIMESTAMP '2025-08-01')", "epoch_ms(TIMESTAMP '2026-02-01')")
OOS = ("epoch_ms(TIMESTAMP '2026-02-01')", "epoch_ms(TIMESTAMP '2026-06-29')")
B = 10_000
B_STYLE = 1_000
Q = 0.10          # OOS Tier-B FDR (frozen)
Q_DISC = 0.20     # discovery FDR (amendment A2: discovery FPs are cheap, OOS gates them)
SEED = 20260709
COST_BP = 5.0
CARE_BP = 8.0
MIN_DAYS = 10
OUT = REPO_ROOT / "data" / "derived" / "confirmatory"


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT/'.tmp'}'")
    return c


def _coin_hz(coin):
    return [h for h in HZ if not (coin == "HYPE" and h == "8h")]   # pre-registered HYPE-8h exclusion


def _eligible(con, lo, hi, performance: bool = False):
    """E1-E6 from the episode lake, per (wallet,coin). AMENDMENT A1: S2 (net PnL>0) removed as a gate —
    over-filtered 75% of the pool and gates the wrong quantity; PnL is now a REPORTED column only.
    Returns {(wallet,coin): (median_hold_min, net_pnl_usd)}."""
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    perf = "AND sum(realized_net_usd) > 0" if performance else ""
    rows = con.execute(f"""SELECT wallet, coin, med_hold, pnl FROM (
        SELECT wallet, coin,
          sum(n_taker_fills + n_maker_fills) n_ord,
          count(DISTINCT strftime(make_timestamp(close_ts*1000), '%G%V')) n_wk,
          sum(initial_notional_usd + total_added_notional_usd) vol_usd,
          sum(n_flagged_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) twap_sh,
          sum(n_liq_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) liq_sh,
          sum(n_taker_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) taker_sh,
          median((close_ts-open_ts)/60000.0) med_hold,
          sum(realized_net_usd) pnl
        FROM read_parquet('{ep}', hive_partitioning=true)
        WHERE close_ts >= {lo} AND close_ts < {hi}
        GROUP BY wallet, coin
        HAVING n_ord>=200 AND n_wk>=8 AND vol_usd>=1e6 AND coalesce(twap_sh,0)<0.30
           AND coalesce(liq_sh,0)<0.10 AND taker_sh>=0.50 {perf})""").fetchall()
    return {(w, c): (mh, p) for (w, c, mh, p) in rows}


def _pull(con, coin, wallets, lo, hi):
    """Per-episode timing_alpha at all coin horizons (+day, hour, dir) for the given wallets in [lo,hi)."""
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
    hz = _coin_hz(coin)
    mus = {h: f"(SELECT avg(fwd_ret_{h}) FROM read_parquet('{fwd}') WHERE fwd_ret_{h} IS NOT NULL AND ts>={lo} AND (ts+{HORIZONS[h]})<={hi})" for h in hz}
    ta = ", ".join(f"CASE WHEN (m.entry_bar_ts+{HORIZONS[h]})<={hi} THEN m.raw_markout_{h} - m.dir_sign*{mus[h]} END AS ta_{h}" for h in hz)
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?)", [(w,) for w in wallets])
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts//86400000 AS day,
        (m.entry_bar_ts//3600000)%24 AS hod, m.dir_sign,
        {ta}
      FROM read_parquet('{mk}') m JOIN wl USING(wallet)
      WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi} AND m.close_ts<={hi}
        AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S}""").fetchnumpy()


def _groups(e):
    wal = np.asarray(e["wallet"], dtype=object)
    order = np.argsort(wal, kind="stable")
    uq, first = np.unique(wal[order], return_index=True)
    bounds = np.append(np.sort(first), len(wal))
    return order, uq, bounds


def _dayblock_p(vals, days, rng):
    uday, inv = np.unique(days, return_inverse=True)
    nd = len(uday)
    idx = [np.where(inv == k)[0] for k in range(nd)]
    obs = float(vals.mean())
    if obs <= 0:
        return 1.0, obs, nd
    means = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, nd, size=nd)
        means[b] = vals[np.concatenate([idx[k] for k in pick])].mean()
    return (1 + int(np.sum(means <= 0))) / (B + 1), obs, nd


def _bh(pairs, q=Q):
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
    elig = _eligible(con, *DISC)   # E1-E6 (A1: PnL gate removed; PnL reported only)
    print(f"discovery eligible (E1-E6, amendment A1): {len(elig):,} wallet-coins")
    cands = []
    for coin in COINS:
        ws = sorted({w for (w, c) in elig if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, *DISC)
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]
        ta = {h: _fcol(e, f"ta_{h}")[order] for h in _coin_hz(coin)}
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
            med_hold, net_pnl = elig[(w, coin)]
            # E8: horizon-hold consistency; E7 handled below per-horizon on valid rows
            hz_ok = [h for h in _coin_hz(coin) if HZ_MIN[h] <= 4 * med_hold]
            best, best_est = None, -1e18
            for h in hz_ok:                          # S1: argmax over ELIGIBLE horizons
                v = ta[h][s:ez]; m = ~np.isnan(v)
                if m.sum() < 5 or len(np.unique(day[s:ez][m])) < MIN_DAYS:
                    continue
                est = float(v[m].mean())
                if est > best_est:
                    best, best_est = h, est
            if best is None or best_est <= CARE_BP:  # S1: est > 8bp
                continue
            v = ta[best][s:ez]; m = ~np.isnan(v)
            vv, dd = v[m], day[s:ez][m]
            # S3: drop-best-day
            ud = np.unique(dd)
            dmean = {k: vv[dd == k].mean() for k in ud}
            worst = max(dmean, key=dmean.get)
            if float(vv[dd != worst].mean()) <= 0:
                continue
            # S4: horizon-adjusted p (Bonferroni x len(hz_ok))
            p, obs, nd = _dayblock_p(vv, dd, rng)
            cands.append({"wallet": w, "coin": coin, "horizon": best, "disc_est": round(obs, 2),
                          "disc_p_adj": min(1.0, p * len(hz_ok)), "disc_nd": nd, "n_hz_searched": len(hz_ok),
                          "disc_net_pnl_usd": round(net_pnl, 0)})   # A1: reported, not a gate
        print(f"  {coin}: pool {len(ws):,} -> running candidates {len(cands):,}", flush=True)
    surv, thr = _bh([(c["disc_p_adj"], i) for i, c in enumerate(cands)], q=Q_DISC)
    final = [cands[i] for i in surv]
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(final), OUT / "candidates.parquet")
    (OUT / "freeze.json").write_text(json.dumps({"protocol": "CONFIRMATORY_PREREG.md", "cost_bp": COST_BP,
        "q_oos": Q, "q_disc": Q_DISC, "seed": SEED, "n_candidates": len(final)}, indent=1))
    print(f"\nS4 BH q={Q_DISC}: {len(final)} CANDIDATES frozen (of {len(cands)} passing S1-S3; p<={thr:.4g})")
    print(f"-> {OUT}/candidates.parquet  (FROZEN before any OOS computation)")


def oos():
    rng = np.random.default_rng(SEED + 1)
    con = _con()
    cand = pq.read_table(OUT / "candidates.parquet").to_pylist()
    print(f"OOS confirmation on {len(cand)} frozen candidates (asterisk: data previously examined)")
    frozen = {(c["wallet"], c["coin"]): c["horizon"] for c in cand}
    per_day = {}          # day -> list of trader-day alphas (Tier A)
    trader = {}           # (w,c) -> dict for Tier B
    style_null = np.zeros(B_STYLE); style_cnt = 0
    for coin in COINS:
        ws = sorted({w for (w, c) in frozen if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, *OOS)
        if len(np.asarray(e["wallet"])) == 0:
            continue
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]; hod = np.asarray(e["hod"])[order]
        dirs = np.asarray(e["dir_sign"], float)[order]
        ta = {h: _fcol(e, f"ta_{h}")[order] for h in _coin_hz(coin)}
        # style-null grid: TA_h(minute) with hour-of-day index, OOS window
        fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
        lo, hi = OOS
        g = {}
        for h in set(frozen[(w, coin)] for w in ws if (w, coin) in frozen):
            gr = con.execute(f"""SELECT (ts//3600000)%24 AS hod, fwd_ret_{h} -
                 (SELECT avg(fwd_ret_{h}) FROM read_parquet('{fwd}') WHERE fwd_ret_{h} IS NOT NULL AND ts>={lo} AND (ts+{HORIZONS[h]})<={hi}) AS tag
              FROM read_parquet('{fwd}') WHERE fwd_ret_{h} IS NOT NULL AND ts>={lo} AND (ts+{HORIZONS[h]})<={hi}""").fetchnumpy()
            gh = np.asarray(gr["hod"]); gt = np.asarray(gr["tag"], float)
            g[h] = {hh: gt[gh == hh] for hh in range(24)}
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]; h = frozen[(w, coin)]
            if h not in ta:
                continue
            v = ta[h][s:ez]; m = ~np.isnan(v)
            vv, dd, hh, ds = v[m], day[s:ez][m], hod[s:ez][m], dirs[s:ez][m]
            if len(vv) < 5 or len(np.unique(dd)) < MIN_DAYS:
                trader[(w, coin)] = {"testable": False, "n": int(len(vv))}
                continue
            p, obs, nd = _dayblock_p(vv, dd, rng)
            trader[(w, coin)] = {"testable": True, "p": p, "est": obs, "nd": nd, "n": int(len(vv)), "h": h}
            for d in np.unique(dd):
                per_day.setdefault(d, []).append(float(vv[dd == d].mean()))
            # style-matched null: per draw, random same-hour grid minutes, dir kept
            nulls = np.empty(B_STYLE)
            for b in range(B_STYLE):
                sim = np.array([ds[i] * rng.choice(g[h][int(hh[i])]) for i in range(len(vv))])
                nulls[b] = sim.mean()
            style_null += nulls; style_cnt += 1
        print(f"  {coin}: OOS-processed", flush=True)

    testable = {k: t for k, t in trader.items() if t.get("testable")}
    print(f"\ntestable in OOS: {len(testable)} / {len(cand)} candidates")
    if not testable:
        print("VERDICT: nothing testable OOS."); return
    # Tier A — basket (primary)
    days = sorted(per_day)
    bd = np.array([float(np.mean(per_day[d])) for d in days])
    obs = float(bd.mean()); nd = len(bd)
    boots = np.array([bd[rng.integers(0, nd, nd)].mean() for _ in range(B)])
    pA = (1 + int(np.sum(boots <= 0))) / (B + 1)
    se = float(bd.std(ddof=1)) / math.sqrt(nd); mde = 2.8 * se
    ci = (obs - 1.96 * se, obs + 1.96 * se)
    print(f"\nTIER A (PRIMARY) basket: est={obs:+.2f}bp CI[{ci[0]:+.2f},{ci[1]:+.2f}] p={pA:.4g} "
          f"MDE={mde:.2f}bp over {nd} days, {len(testable)} traders")
    if ci[0] > 0 and obs > COST_BP:
        print(f"  -> BASKET CONFIRMED (CI>0 and est>{COST_BP}bp cost) [asterisked]")
    elif mde <= CARE_BP and ci[1] < CARE_BP:
        print(f"  -> basket EARNED-NULL (MDE<={CARE_BP} and CI-high<{CARE_BP})")
    else:
        print("  -> basket INCONCLUSIVE per frozen rules")
    # style attribution
    if style_cnt:
        null_mean = style_null / style_cnt
        pS = float(np.mean(null_mean >= obs))
        print(f"style-matched attribution: p_style={pS:.3g} "
              f"({'timing beyond style' if pS < 0.05 else 'NOT distinguishable from structural footprint'})")
    # Tier B — per-trader
    survB, thrB = _bh([(t["p"], k) for k, t in testable.items()])
    conf = [k for k in survB if testable[k]["est"] > COST_BP]
    print(f"\nTIER B per-trader: BH q={Q} -> {len(survB)} significant; economic filter est>{COST_BP}bp -> "
          f"{len(conf)} CONFIRMED wallets [asterisked]")
    rows = []
    for k in sorted(testable, key=lambda k: testable[k]["p"]):
        t = testable[k]
        rows.append({"wallet": k[0], "coin": k[1], "horizon": t["h"], "oos_p": t["p"],
                     "oos_est_bp": round(t["est"], 2), "oos_nd": t["nd"], "oos_n": t["n"],
                     "fdr_sig": k in survB, "confirmed": k in set(conf)})
        if k in survB:
            print(f"   {k[0][:14]}… {k[1]:4s} @{t['h']} est={t['est']:+.1f}bp nd={t['nd']} p={t['p']:.4g}"
                  f"{'  CONFIRMED' if k in set(conf) else '  (sig but <cost)'}")
    pq.write_table(pa.Table.from_pylist(rows), OUT / "oos_results.parquet")
    print(f"-> {OUT}/oos_results.parquet")


if __name__ == "__main__":
    (discover if (len(sys.argv) > 1 and sys.argv[1] == "discover") else oos)()
