"""ROLLING monthly walk-forward (user spec 2026-07-09) — tests the PROCEDURE, not a static wallet list.

Each month M: discovery = trailing L months (neutral eligibility + active in last 30d; max-horizon day-block
bootstrap p vs the 5bp cost hurdle for every eligible wallet-coin); freeze basket = TOP-N by q-rank (NOT strict
per-wallet FDR — the p is a selection score; inference happens once, on the combined forward series); test the
frozen basket during month M only; repeat for every possible M; combine all test months into ONE genuinely
forward daily series.  PRIMARY: combined basket net (gross − 5bp) > 0, day-block bootstrap.
SECONDARY: per-wallet recurrence and per-month stability.  Variants L=3 and L=6 run transparently; the
deployment window is chosen from THESE results.

Leakage geometry: discovery pulls are strictly windowed (close ≤ cutoff, horizon resolves ≤ cutoff — selection
sees nothing past its cutoff). Test-month pulls count entries in [M, M+1); their horizons may resolve into the
first hours of the next month — strictly forward of discovery, no selection leakage.

    python -m research.data.rolling_wf 3     # trailing-3-month variant
    python -m research.data.rolling_wf 6     # trailing-6-month variant
"""
from __future__ import annotations
import math
import sys
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from .markout import HORIZONS, COINS, REPO_ROOT
from .features_markout import ENTRY_LAG_MAX_S
from .family_wf import (_con, _eligible, _pull, _groups, _daysums, _maxstat_p, _fcol,
                        HZ, COST, MIN_EP, MIN_DAYS)

STARTS = ["2025-08-01", "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01",
          "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01", "2026-06-01"]
TAPE_END = "2026-06-29"
N_BASKET = 20
B_RANK = 2_000            # selection-score resolution (ranking only; inference is the combined OOS test)
SEED = 20260709
OUT = REPO_ROOT / "data" / "derived" / "rolling_wf"


def _ts(d):
    return f"epoch_ms(TIMESTAMP '{d}')"


def _pull_test(con, coin, wallets, lo, hi):
    """Test-month pull: entries in [lo,hi); horizon values as stored (may resolve past hi — forward-only)."""
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    g = ", ".join(f"m.raw_markout_{h} AS g_{h}" for h in HZ)
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?)", [(w,) for w in wallets])
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts//86400000 AS day, {g}
      FROM read_parquet('{mk}') m JOIN wl USING(wallet)
      WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi}
        AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S}""").fetchnumpy()


def discover_window(con, lo, hi, rng):
    """One discovery window -> top-N basket [(wallet, coin, horizon, p, gross)] by q-rank."""
    elig = _eligible(con, lo, hi)
    scored = []
    for coin in COINS:
        ws = sorted({w for (w, c) in elig if c == coin})
        if not ws:
            continue
        e = _pull(con, coin, ws, lo, hi)
        if len(np.asarray(e["wallet"])) == 0:
            continue
        order, uq, bounds = _groups(e)
        day = np.asarray(e["day"])[order]
        G = np.column_stack([_fcol(e, f"g_{h}")[order] for h in HZ])
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]
            uday, dsum, dcnt = _daysums(G[s:ez], day[s:ez])
            use = (dcnt.sum(0) >= MIN_EP) & ((dcnt > 0).sum(0) >= MIN_DAYS)
            if not use.any() or len(uday) < MIN_DAYS:
                continue
            p, sel, obs, se = _maxstat_p(dsum, dcnt, use, rng, B_RANK)
            t_obs = float((obs[sel] - COST) / se[sel])
            scored.append((p, -t_obs, w, coin, HZ[sel], float(obs[sel])))
    scored.sort()
    return [(w, c, h, p, g) for (p, _, w, c, h, g) in scored[:N_BASKET]], len(scored)


def run(L):
    rng = np.random.default_rng(SEED)
    con = _con()
    daily = {}          # day -> list of wallet day-means (combined OOS series)
    month_rows, wallet_hits, basket_rows = [], {}, []
    for i in range(L, len(STARTS)):
        d_lo, d_hi = _ts(STARTS[i - L]), _ts(STARTS[i])
        t_lo = _ts(STARTS[i])
        t_hi = _ts(STARTS[i + 1]) if i + 1 < len(STARTS) else _ts(TAPE_END)
        basket, fam = discover_window(con, d_lo, d_hi, rng)
        for (w, c, h, p, g) in basket:
            wallet_hits[(w, c)] = wallet_hits.get((w, c), 0) + 1
            basket_rows.append({"test_month": STARTS[i][:7], "wallet": w, "coin": c, "horizon": h,
                                "disc_p": p, "disc_gross_bp": round(g, 2)})
        # test the frozen basket in month M
        frozen = {(w, c): h for (w, c, h, p, g) in basket}
        mdays, m_eps, active = {}, 0, set()
        for coin in COINS:
            ws = sorted({w for (w, c) in frozen if c == coin})
            if not ws:
                continue
            e = _pull_test(con, coin, ws, t_lo, t_hi)
            wal = np.asarray(e["wallet"], dtype=object)
            if len(wal) == 0:
                continue
            order, uq, bounds = _groups(e)
            day = np.asarray(e["day"])[order]
            G = {h: _fcol(e, f"g_{h}")[order] for h in HZ}
            for gi in range(len(uq)):
                s, ez = bounds[gi], bounds[gi + 1]; w = uq[gi]; h = frozen[(w, coin)]
                v = G[h][s:ez]; mm = ~np.isnan(v)
                if not mm.any():
                    continue
                active.add((w, coin)); m_eps += int(mm.sum())
                vv, dd = v[mm], day[s:ez][mm]
                for d in np.unique(dd):
                    mdays.setdefault(d, []).append(float(vv[dd == d].mean()))
        for d, vals in mdays.items():
            daily.setdefault(d, []).extend(vals)
        mg = float(np.mean([np.mean(v) for v in mdays.values()])) if mdays else float("nan")
        month_rows.append({"test_month": STARTS[i][:7], "family": fam, "basket": len(basket),
                           "active": len(active), "episodes": m_eps, "days": len(mdays),
                           "month_gross_bp": round(mg, 2) if mdays else None})
        print(f"[L={L}] {STARTS[i][:7]}: family={fam:,} basket={len(basket)} active={len(active)} "
              f"eps={m_eps} days={len(mdays)} month_gross={mg:+.2f}bp" if mdays else
              f"[L={L}] {STARTS[i][:7]}: family={fam:,} basket={len(basket)} active=0 — no trades", flush=True)

    # PRIMARY — combined forward series
    days = sorted(daily)
    bd = np.array([float(np.mean(daily[d])) for d in days]); nd = len(bd)
    obs = float(bd.mean())
    boots = np.array([bd[rng.integers(0, nd, nd)].mean() for _ in range(10_000)])
    pA = (1 + int(np.sum(boots <= COST))) / 10_001
    se = float(bd.std(ddof=1)) / math.sqrt(nd)
    print(f"\n[L={L}] PRIMARY combined OOS basket ({nd} forward days across {len(month_rows)} months):")
    print(f"  gross={obs:+.2f}bp  net={obs-COST:+.2f}bp  CI_gross[{obs-1.96*se:+.2f},{obs+1.96*se:+.2f}]  "
          f"p(net>0)={pA:.4g}  MDE={2.8*se:.2f}bp")
    pos_m = [r for r in month_rows if r["month_gross_bp"] is not None and r["month_gross_bp"] > COST]
    print(f"  months with gross > cost: {len(pos_m)}/{len(month_rows)}")
    # SECONDARY — recurrence / stability
    rec = sorted(wallet_hits.values(), reverse=True)
    print(f"[L={L}] SECONDARY recurrence: {len(wallet_hits)} distinct wallets filled "
          f"{sum(rec)} basket slots; selected in >=2 windows: {sum(1 for x in rec if x >= 2)}, "
          f">=3: {sum(1 for x in rec if x >= 3)}, max {rec[0] if rec else 0}")
    out = OUT / f"L{L}"; out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(basket_rows), out / "baskets.parquet")
    pq.write_table(pa.Table.from_pylist(month_rows), out / "months.parquet")
    pq.write_table(pa.Table.from_pylist([{"day": int(d), "basket_gross_bp": float(np.mean(daily[d])),
                                          "n_wallets": len(daily[d])} for d in days]), out / "daily.parquet")
    print(f"-> {out}/ (baskets / months / daily .parquet)")


def live():
    """Deployment step: the frozen L=6 procedure on the trailing window ending at the tape edge ->
    the CURRENT top-20 basket for forward paper-copying (July 2026+)."""
    rng = np.random.default_rng(SEED)
    con = _con()
    lo, hi = _ts("2026-01-01"), _ts(TAPE_END)   # trailing ~6 months, recent-activity enforced vs tape edge
    basket, fam = discover_window(con, lo, hi, rng)
    print(f"LIVE basket (discovery 2026-01-01 .. {TAPE_END}, family={fam:,}, frozen L=6 rules):")
    rows = []
    for r, (w, c, h, p, g) in enumerate(basket, 1):
        rows.append({"rank": r, "wallet": w, "coin": c, "horizon": h, "disc_p": p,
                     "disc_gross_bp": round(g, 2)})
        print(f"  {r:>2}. {w} {c:4s} @{h} gross={g:+.1f}bp p={p:.4g}")
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), OUT / "live_basket.parquet")
    print(f"-> {OUT}/live_basket.parquet  (paper-copy forward; refresh monthly under the same frozen rules)")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "3"
    live() if arg == "live" else run(int(arg))
