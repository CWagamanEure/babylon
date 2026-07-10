"""PERSISTENCE-SCORE rolling walk-forward (user spec 2026-07-10) — frozen, run ONCE, no tuning.

Predictive framing: not "prove this wallet has edge" but "which currently-active wallet-coins are most
likely to show positive net copyable markout next month." Selector = a 5-component equal-weight
percentile persistence score. No p-value gate, no per-wallet horizon argmax, no optimized weights.

FROZEN SPEC (constants the user's spec left open are frozen here, before results):
  Unit: wallet x coin. Cost line: 5bp round-trip. Horizon band: FIXED {1h, 2h, 4h}; an episode's
  band markout = mean of its non-NaN horizon markouts; a wallet's measure = mean over episodes.
  Eligibility (trailing 6 months, prior data only): >=50 episodes, >=30 active entry-days,
  >=$1M notional, twap<30%, liq<10%, traded in last 30d, median hold >= 15min (1h copyable),
  >=15 active days in the last 90d.
  Score components (each -> percentile rank among that month's eligible family, then averaged):
    C1 recent edge:   5/95-winsorized mean band NET markout, entries in last 90d
    C2 longer edge:   5/95-winsorized mean band NET markout, full 6mo
    C3 consistency:   fraction of active months with positive mean band net
    C4 robustness:    mean band net EXCLUDING the single best entry-day
    C5 activity:      0.5*pct(active days last 90d) + 0.5*pct(activity ratio (30d rate / 180d rate), cap 2)
  Hard safeguards (gates, applied after scoring): 6mo band GROSS >= 8bp (5 cost + 3 buffer);
    90d band net > 0; >=3 positive months; drop-best-day net > 0; >=2 of 3 horizons positive (6mo).
  Basket: top 20 by score. Freeze for one month. Roll monthly (disc [M-6mo,M) -> test [M,M+1)).
  Test measurement: band gross per episode (entries in test month, horizons resolve forward),
    wallet-day equal weighting -> daily basket series -> combined across months.
  Inference: MOVING-BLOCK bootstrap (block = 7 consecutive days, circular, B=10,000) on the combined
    daily series vs the 5bp cost line. Ex-HYPE line reported with equal standing. Inactivity of a
    frozen slot = deployment failure (reported as attrition).

    python -m research.data.persistence_wf
"""
from __future__ import annotations
import math
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
from .markout import HORIZONS, COINS, REPO_ROOT
from .features_markout import ENTRY_LAG_MAX_S
from .family_wf import _con, _fcol, _groups

BAND = ["1h", "2h", "4h"]
STARTS = ["2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01",
          "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01", "2026-06-01"]
TAPE_END = "2026-06-29"
COST = 5.0
BUFFER = 3.0
N_BASKET = 20
WINSOR = (5, 95)
BLOCK_DAYS = 7
B = 10_000
SEED = 20260710
DAY = 86_400_000
OUT = REPO_ROOT / "data" / "derived" / "persistence_wf"


def _ts(d):
    return f"epoch_ms(TIMESTAMP '{d}')"


def _eligible(con, lo, hi):
    """Frozen eligibility over trailing window [lo,hi): activity/copyability only."""
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    rows = con.execute(f"""SELECT wallet, coin FROM (
        SELECT wallet, coin, count(*) n_ep,
          count(DISTINCT open_ts // {DAY}) n_days,
          sum(initial_notional_usd + total_added_notional_usd) vol_usd,
          sum(n_flagged_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) twap_sh,
          sum(n_liq_fills)::DOUBLE/nullif(sum(n_taker_fills+n_maker_fills),0) liq_sh,
          max(close_ts) last_close,
          median((close_ts-open_ts)/60000.0) med_hold,
          count(DISTINCT CASE WHEN open_ts >= ({hi}) - 90::BIGINT*{DAY} THEN open_ts // {DAY} END) days90
        FROM read_parquet('{ep}', hive_partitioning=true)
        WHERE close_ts >= {lo} AND close_ts < {hi} GROUP BY wallet, coin
        HAVING n_ep>=50 AND n_days>=30 AND vol_usd>=1e6 AND coalesce(twap_sh,0)<0.30
           AND coalesce(liq_sh,0)<0.10 AND last_close >= ({hi}) - 30::BIGINT*{DAY}
           AND med_hold >= 15 AND days90 >= 15)""").fetchall()
    return {(w, c) for (w, c) in rows}


def _pull(con, coin, wallets, lo, hi, censor):
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    if censor:   # discovery: selection sees nothing past its cutoff
        g = ", ".join(f"CASE WHEN (m.entry_bar_ts+{HORIZONS[h]})<={hi} THEN m.raw_markout_{h} END AS g_{h}"
                      for h in BAND)
        close = f"AND m.close_ts<={hi}"
    else:        # test month: horizons resolve forward
        g = ", ".join(f"m.raw_markout_{h} AS g_{h}" for h in BAND)
        close = ""
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?)", [(w,) for w in wallets])
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts//{DAY} AS day, m.entry_bar_ts, {g}
      FROM read_parquet('{mk}') m JOIN wl USING(wallet)
      WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi} {close}
        AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S}""").fetchnumpy()


def _wins_mean(x):
    if len(x) == 0:
        return float("nan")
    lo, hi = np.percentile(x, WINSOR)
    return float(np.clip(x, lo, hi).mean())


def _pctrank(v):
    v = np.asarray(v, float)
    order = np.argsort(np.argsort(v))
    return order / max(len(v) - 1, 1)


def score_window(con, lo_d, hi_d):
    """One discovery window -> (top-20 basket rows, family size)."""
    lo, hi = _ts(lo_d), _ts(hi_d)
    hi_ms = con.execute(f"SELECT {hi}").fetchone()[0]
    lo_ms = con.execute(f"SELECT {lo}").fetchone()[0]
    elig = _eligible(con, lo, hi)
    cand = []
    for coin in COINS:
        ws = sorted({w for (w, c) in elig if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, lo, hi, censor=True)
        if len(np.asarray(e["wallet"])) == 0:
            continue
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]
        ebt = np.asarray(e["entry_bar_ts"])[order]
        G = np.column_stack([_fcol(e, f"g_{h}")[order] for h in BAND])
        band = np.nanmean(G, axis=1)                      # per-episode band markout (gross bp)
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
            b = band[s:ez]; d = day[s:ez]; t = ebt[s:ez]
            m = ~np.isnan(b)
            b, d, t = b[m], d[m], t[m]
            if len(b) < 10:
                continue
            hz_means = [np.nanmean(G[s:ez, j]) for j in range(3)]
            g6 = float(b.mean())
            r90 = b[t >= hi_ms - 90 * DAY]
            # months: index by 30d buckets back from hi
            mo = ((hi_ms - 1 - t) // (30 * DAY)).astype(int)
            mo_means = [b[mo == k].mean() for k in range(6) if (mo == k).any()]
            pos_months = sum(1 for x in mo_means if x - COST > 0)
            ud = np.unique(d)
            bd = ud[np.argmax([b[d == k].sum() for k in ud])] if len(ud) > 1 else ud[0]
            dropbest = float(b[d != bd].mean()) if len(ud) > 1 else float("nan")
            act90 = len(np.unique(d[t >= hi_ms - 90 * DAY]))
            act30 = len(np.unique(d[t >= hi_ms - 30 * DAY]))
            act180 = len(ud)
            ratio = min((act30 / 30.0) / max(act180 / 180.0, 1e-9), 2.0)
            cand.append({
                "wallet": w, "coin": coin, "n_ep": int(len(b)),
                "c1": _wins_mean(r90) - COST, "c2": _wins_mean(b) - COST,
                "c3": (pos_months / max(len(mo_means), 1)), "c4": dropbest - COST,
                "act90": act90, "ratio": ratio,
                # safeguards
                "sg_gross6": g6, "sg_r90net": (float(r90.mean()) - COST) if len(r90) else float("nan"),
                "sg_posmo": pos_months, "sg_dropbest": dropbest - COST,
                "sg_hz2of3": sum(1 for x in hz_means if x > 0) >= 2,
            })
    if not cand:
        return [], 0
    # percentile ranks among the FULL eligible family, then equal-weight average
    p1, p2 = _pctrank([c["c1"] for c in cand]), _pctrank([c["c2"] for c in cand])
    p3, p4 = _pctrank([c["c3"] for c in cand]), _pctrank([c["c4"] for c in cand])
    p5 = 0.5 * _pctrank([c["act90"] for c in cand]) + 0.5 * _pctrank([c["ratio"] for c in cand])
    for i, c in enumerate(cand):
        c["score"] = float((p1[i] + p2[i] + p3[i] + p4[i] + p5[i]) / 5.0)
    ok = [c for c in cand if c["sg_gross6"] >= COST + BUFFER and
          (not math.isnan(c["sg_r90net"]) and c["sg_r90net"] > 0) and c["sg_posmo"] >= 3 and
          (not math.isnan(c["sg_dropbest"]) and c["sg_dropbest"] > 0) and c["sg_hz2of3"]]
    ok.sort(key=lambda c: (-c["score"], c["wallet"]))
    return ok[:N_BASKET], len(cand)


def run():
    rng = np.random.default_rng(SEED)
    con = _con()
    daily, daily_exh = {}, {}
    month_rows, basket_rows, hits = [], [], {}
    for i in range(6, len(STARTS)):
        d_lo, d_hi = STARTS[i - 6], STARTS[i]
        t_lo = _ts(STARTS[i])
        t_hi = _ts(STARTS[i + 1]) if i + 1 < len(STARTS) else _ts(TAPE_END)
        basket, fam = score_window(con, d_lo, d_hi)
        for c in basket:
            hits[(c["wallet"], c["coin"])] = hits.get((c["wallet"], c["coin"]), 0) + 1
            basket_rows.append({"test_month": STARTS[i][:7], "wallet": c["wallet"], "coin": c["coin"],
                                "score": round(c["score"], 4), "disc_gross6_bp": round(c["sg_gross6"], 2)})
        frozen = {(c["wallet"], c["coin"]) for c in basket}
        mdays, active = {}, set()
        for coin in COINS:
            ws = sorted({w for (w, c) in frozen if c == coin})
            if not ws:
                continue
            e = _pull(con, coin, ws, t_lo, t_hi, censor=False)
            wal = np.asarray(e["wallet"], dtype=object)
            if len(wal) == 0:
                continue
            order, uq, bounds = _groups(e)
            day = np.asarray(e["day"])[order]
            G = np.column_stack([_fcol(e, f"g_{h}")[order] for h in BAND])
            band = np.nanmean(G, axis=1)
            for gi in range(len(uq)):
                s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
                b = band[s:ez]; d = day[s:ez]; m = ~np.isnan(b)
                if not m.any():
                    continue
                active.add((w, coin))
                bb, dd = b[m], d[m]
                for k in np.unique(dd):
                    v = float(bb[dd == k].mean())
                    mdays.setdefault(k, []).append((v, coin))
        for k, vals in mdays.items():
            daily.setdefault(k, []).extend(v for v, _ in vals)
            ex = [v for v, cn in vals if cn != "HYPE"]
            if ex:
                daily_exh.setdefault(k, []).extend(ex)
        mg = float(np.mean([np.mean([v for v, _ in x]) for x in mdays.values()])) if mdays else None
        month_rows.append({"test_month": STARTS[i][:7], "family": fam, "basket": len(basket),
                           "active": len(active), "attrition": len(basket) - len(active),
                           "days": len(mdays), "month_gross_bp": round(mg, 2) if mg is not None else None})
        print(f"{STARTS[i][:7]}: family={fam:,} basket={len(basket)} active={len(active)} "
              f"(attrition {len(basket)-len(active)}) days={len(mdays)} "
              f"gross={mg:+.2f}bp" if mg is not None else
              f"{STARTS[i][:7]}: family={fam:,} basket={len(basket)} — NO trades", flush=True)

    def mbb(series):
        """Circular moving-block bootstrap, block=BLOCK_DAYS, one-sided p vs COST + CI."""
        x = np.asarray(series, float); n = len(x)
        obs = float(x.mean())
        nblk = math.ceil(n / BLOCK_DAYS)
        means = np.empty(B)
        for b_ in range(B):
            st = rng.integers(0, n, size=nblk)
            idx = (st[:, None] + np.arange(BLOCK_DAYS)[None, :]).ravel() % n
            means[b_] = x[idx[:n]].mean()
        p = (1 + int(np.sum(means <= COST))) / (B + 1) if obs > COST else 1.0
        se = float(means.std(ddof=1))
        return obs, p, se

    days = sorted(daily)
    bd = [float(np.mean(daily[k])) for k in days]
    obs, p, se = mbb(bd)
    print(f"\nPRIMARY combined ({len(bd)} days, {len(month_rows)} months): gross={obs:+.2f}bp "
          f"net={obs-COST:+.2f}bp CI_gross[{obs-1.96*se:+.2f},{obs+1.96*se:+.2f}] "
          f"p(net>0)={p:.4g}  [moving-block {BLOCK_DAYS}d]")
    dxe = [float(np.mean(daily_exh[k])) for k in sorted(daily_exh)]
    if dxe:
        obs2, p2, se2 = mbb(dxe)
        print(f"EX-HYPE ({len(dxe)} days): gross={obs2:+.2f}bp net={obs2-COST:+.2f}bp "
              f"CI[{obs2-1.96*se2:+.2f},{obs2+1.96*se2:+.2f}] p(net>0)={p2:.4g}")
    pos = [r for r in month_rows if r["month_gross_bp"] is not None and r["month_gross_bp"] > COST]
    att = sum(r["attrition"] for r in month_rows)
    slots = sum(r["basket"] for r in month_rows)
    rec = sorted(hits.values(), reverse=True)
    print(f"months>cost: {len(pos)}/{len(month_rows)} | deployment attrition: {att}/{slots} slots "
          f"({100*att/max(slots,1):.0f}%) | distinct wallets {len(hits)}, >=3 windows: "
          f"{sum(1 for x in rec if x >= 3)}")
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(basket_rows), OUT / "baskets.parquet")
    pq.write_table(pa.Table.from_pylist(month_rows), OUT / "months.parquet")
    pq.write_table(pa.Table.from_pylist([{"day": int(k), "gross_bp": float(np.mean(daily[k])),
                                          "n": len(daily[k])} for k in days]), OUT / "daily.parquet")
    print(f"-> {OUT}/")


if __name__ == "__main__":
    run()
