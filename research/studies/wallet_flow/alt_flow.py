"""alt_flow — the alt-breadth wallet-cohort test (the payoff run). Built to ALT_BREADTH_AUDIT_RESPONSE (binding).

Does the informed-cohort signal, on the ~45-name ALT cross-section, produce a POWERED partial IC | OFI and beat
a random same-size cohort — where 4 majors were breadth-starved? (Breadth buys POWER, not gross/crossing.)

Disciplines encoded: alt-sourced flow from `alt_flow` (NOT the majors `fills`); cohort flow = Σ flow_signed over
BOTH crossed, OFI = Σ flow_signed FILTER(crossed=true); factor-neutral residual on BTC+ETH+LOO-alt-index (causal
rolling beta, NaN calendar grid) + a sector-adequacy diagnostic; H-embargo at the train/test seam; DAY-block
bootstrap (slow-drift autocorrelation); drop 2026-05-30 (partial price day); point-in-time universe (alt_universe).

    .venv/bin/python -m research.studies.wallet_flow.alt_flow
"""
from __future__ import annotations
import time, functools
from pathlib import Path
import numpy as np
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow.alt_universe import universe, _daily_adv

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

W = 720; MINOBS = 240; H = 1
TEST_MONTH = 202603
COHORT_Q = 0.20
MIN_TRAIN_BKT = 20
UNIV_FORMATION = 20260301          # form the coin set point-in-time at the TRAIN/TEST boundary
DROP_DAYS = (20260530,)            # asset_ctx genuine archive gap (ends 06:57)
BOOT = 2000
SCRATCH = "/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad"
FACTORS = ("BTC", "ETH")


def _rank(x): return np.argsort(np.argsort(x)).astype(float)
def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 20: return np.nan
    ra, rb = _rank(a[m]), _rank(b[m]); ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra @ ra) * (rb @ rb)); return (ra @ rb) / d if d > 0 else np.nan
def _ols_resid(y, x):
    m = np.isfinite(y) & np.isfinite(x); r = np.full_like(y, np.nan, float)
    if m.sum() < 10: return r
    X = np.column_stack([x[m], np.ones(m.sum())]); b = np.linalg.lstsq(X, y[m], rcond=None)[0]
    r[m] = y[m] - X @ b; return r


def build_resid(con, coins):
    """Hourly factor-neutral forward residual [N,C] for `coins`, neutralized on BTC+ETH+LOO-alt-index (causal),
    on the full hourly calendar grid (NaN when a coin has no price). Drops DROP_DAYS. Returns dict."""
    inlist = "('" + "','".join(coins) + "')"
    drop = " AND day NOT IN (" + ",".join(str(d) for d in DROP_DAYS) + ")" if DROP_DAYS else ""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbars AS
        WITH v AS (SELECT coin, ts, (ts - ts%3600000) AS h, mid_px FROM asset_ctx
                   WHERE coin IN {inlist} AND mid_px>0{drop})
        SELECT coin, h, arg_max(mid_px, ts) AS mid FROM v GROUP BY coin, h""")
    d = con.execute("SELECT coin, h, mid FROM hbars").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64)
    ci = {c: i for i, c in enumerate(coins)}; C = len(coins)
    hmin, hmax = int(ha.min()), int(ha.max())
    hours = np.arange(hmin, hmax + 1, 3600000, dtype=np.int64); N = len(hours)
    rows = ((ha - hmin) // 3600000).astype(int); cols = np.array([ci[str(c)] for c in ca])
    Lp = np.full((N, C), np.nan); Lp[rows, cols] = np.log(d["mid"].astype(float))
    R = np.diff(Lp, axis=0, prepend=np.nan)
    # factor returns: BTC, ETH (ETH orthogonalized to BTC once), + LOO equal-weight ALT index (excl majors/factors)
    bi, ei = ci["BTC"], ci["ETH"]
    rbtc = R[:, bi]; reth = R[:, ei] - rolling_beta(R[:, ei], rbtc, W, MINOBS) * rbtc
    alt_cols = [ci[c] for c in coins if c not in FACTORS]
    Ralt = R[:, alt_cols]
    tot = np.nansum(Ralt, 1); cnt = np.sum(np.isfinite(Ralt), 1)
    resid = np.full((N, C), np.nan)
    for c in range(C):
        if coins[c] in FACTORS: continue
        y = R[:, c]
        loo = np.where(cnt - np.isfinite(y) > 0, (tot - np.where(np.isfinite(y), y, 0.0)) / (cnt - np.isfinite(y)), np.nan)
        r1 = y - rolling_beta(y, rbtc, W, MINOBS) * rbtc
        r2 = r1 - rolling_beta(r1, reth, W, MINOBS) * reth
        resid[:, c] = r2 - rolling_beta(r2, loo, W, MINOBS) * loo
    # forward residual over H (post-bucket): fwd_resid[t] applies to flow known at end of bucket t
    fr = np.full((N, C), np.nan)
    fr[:-H] = resid[H:]
    month = np.array([int(__import__("datetime").datetime.utcfromtimestamp(int(x)/1000).strftime("%Y%m")) for x in hours])
    return dict(hours=hours, month=month, N=N, C=C, coins=coins, ci=ci, fr=fr, resid=resid)


def build_cohort_tables(con, coins):
    """Per (wallet, coin, hour) cohort flow + per (coin,hour) OFI over the ALT universe, cached month-by-month.
    cohort/wallet flow = Σ flow_signed over BOTH crossed; OFI = Σ flow_signed FILTER(crossed). (alt_flow two-sided.)"""
    inlist = "('" + "','".join(coins) + "')"
    wb = Path(SCRATCH) / "alt_wb"; ag = Path(SCRATCH) / "alt_agg"
    wb.mkdir(parents=True, exist_ok=True); ag.mkdir(parents=True, exist_ok=True)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM alt_flow ORDER BY month").fetchall()]
    for m in months:
        pw = wb / f"month={m}.parquet"
        if not (pw.exists() and pw.stat().st_size > 0):
            con.execute(f"""COPY (SELECT wallet, coin, (bucket - bucket%3600000) AS h, {m} AS mth,
                   sum(flow_signed) AS flow
                FROM alt_flow WHERE month={m} AND coin IN {inlist}
                GROUP BY wallet, coin, h) TO '{pw}' (FORMAT PARQUET)""")
            _log(f"alt_wb {m} written")
        pa = ag / f"month={m}.parquet"
        if not (pa.exists() and pa.stat().st_size > 0):
            con.execute(f"""COPY (SELECT coin, (bucket - bucket%3600000) AS h,
                   sum(flow_signed) FILTER (crossed) AS ofi, sum(flow_signed) AS allflow
                FROM alt_flow WHERE month={m} AND coin IN {inlist}
                GROUP BY coin, h) TO '{pa}' (FORMAT PARQUET)""")
            _log(f"alt_agg {m} written")
    con.execute(f"CREATE OR REPLACE VIEW awb AS SELECT * FROM read_parquet('{wb}/month=*.parquet')")
    con.execute(f"CREATE OR REPLACE VIEW aagg AS SELECT * FROM read_parquet('{ag}/month=*.parquet')")


def register_resid(con, panel):
    hours, month, fr, coins = panel["hours"], panel["month"], panel["fr"], panel["coins"]
    co, hh, mo, rv = [], [], [], []
    for i, c in enumerate(coins):
        col = fr[:, i]; g = np.nonzero(np.isfinite(col))[0]
        co += [c]*len(g); hh += hours[g].tolist(); mo += month[g].tolist(); rv += col[g].tolist()
    con.register("rsrc", {"coin": np.array(co, dtype=object), "h": np.array(hh, np.int64),
                          "month": np.array(mo, np.int64), "fwd_resid": np.array(rv, float)})
    con.execute("CREATE OR REPLACE TEMP TABLE aresid AS SELECT * FROM rsrc"); con.unregister("rsrc")


def freeze_cohort(con, first_test_hour_ms):
    """Rank wallets on TRAIN alignment (month<TEST_MONTH) with H-EMBARGO (a train bucket whose forward window
    reaches the test seam is excluded), top COHORT_Q. Returns (cohort ids, pool size)."""
    emb = first_test_hour_ms - H*3600000
    q = con.execute(f"""
        WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid AS a
                   FROM awb wb JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h
                   WHERE wb.mth < {TEST_MONTH} AND wb.h < {emb} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al, count(*) nb FROM j GROUP BY wallet HAVING count(*) >= {MIN_TRAIN_BKT}
    """).fetchnumpy()
    w = np.asarray(q["wallet"], dtype=object); al = q["al"].astype(float)
    if not len(w): return [], 0
    thr = np.quantile(al, 1.0 - COHORT_Q); cohort = w[al >= thr]
    con.register("csrc", {"wallet": np.array([str(x) for x in cohort], dtype=object)})
    con.execute("CREATE OR REPLACE TEMP TABLE acohort AS SELECT * FROM csrc"); con.unregister("csrc")
    return cohort, len(w)


def test_panel(con):
    q = con.execute(f"""
        WITH cf AS (SELECT wb.coin, wb.h, sum(wb.flow) cohort_flow FROM awb wb JOIN acohort c USING(wallet)
                    WHERE wb.mth >= {TEST_MONTH} GROUP BY wb.coin, wb.h)
        SELECT r.coin, r.h, r.fwd_resid, COALESCE(cf.cohort_flow,0) cohort_flow, COALESCE(a.ofi,0) ofi
        FROM aresid r LEFT JOIN cf ON cf.coin=r.coin AND cf.h=r.h
        LEFT JOIN aagg a ON a.coin=r.coin AND a.h=r.h
        WHERE r.month >= {TEST_MONTH}""").fetchnumpy()
    return q


def _zc(v, coin):
    out = np.full_like(v, np.nan, float)
    for c in np.unique(coin):
        m = coin == c; s = np.nanstd(v[m])
        if s > 0: out[m] = (v[m] - np.nanmean(v[m])) / s
    return out


def _day_block_boot(days, y, xc, xo, fn, n=BOOT, seed=0):
    """DAY-block bootstrap (audit F5: single-hour blocks understate slow-drift CIs). Resample whole days."""
    rng = np.random.default_rng(seed); ud = np.unique(days)
    idx = {d: np.nonzero(days == d)[0] for d in ud}; stats = []
    for _ in range(n):
        pick = rng.integers(0, len(ud), size=len(ud))
        sel = np.concatenate([idx[ud[p]] for p in pick])
        stats.append(fn(y[sel], xc[sel], xo[sel]))
    s = np.array([v for v in stats if np.isfinite(v)])
    return (np.percentile(s, [2.5, 97.5]) if len(s) > 10 else (np.nan, np.nan))


def partial_ic(y, xc, xo): return _spear(_ols_resid(xc, xo), y)
def naive_ic(y, xc, xo): return _spear(xc, y)
def ofi_ic(y, xc, xo): return _spear(xo, y)


def run():
    Path(SCRATCH).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'"); con.execute("SET preserve_insertion_order=false")
    _daily_adv(con)
    alts = universe(con, UNIV_FORMATION, include_majors=False)
    coins = list(FACTORS) + alts
    print(f"[1/5] universe @ {UNIV_FORMATION}: {len(alts)} alts + {FACTORS} factors")
    print("[2/5] residual panel ...")
    panel = build_resid(con, coins); _log(f"resid built ({panel['N']} hours, {len(alts)} alts)")
    print("[3/5] cohort tables (alt_flow, month-by-month) ...")
    build_cohort_tables(con, coins); register_resid(con, panel)
    first_test_h = int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={TEST_MONTH}").fetchone()[0])
    cohort, npool = freeze_cohort(con, first_test_h)
    print(f"[4/5] cohort frozen (H-embargo): pool={npool:,}, cohort={len(cohort):,} (top {COHORT_Q:.0%})")
    tp = test_panel(con); _log("test panel built")
    coin = np.asarray(tp["coin"], dtype=object); hours = tp["h"].astype(np.int64)
    days = (hours // 86400000).astype(np.int64)
    y = tp["fwd_resid"].astype(float); cf = tp["cohort_flow"].astype(float); of = tp["ofi"].astype(float)
    zy, zc, zo = _zc(y, coin), _zc(cf, coin), _zc(of, coin)
    n = np.isfinite(y).sum()
    print(f"[5/5] TEST obs (coin,hour): {n:,}; distinct alt coins: {len(np.unique(coin))}")
    ic_ofi = ofi_ic(zy, zc, zo); ci_o = _day_block_boot(days, zy, zc, zo, ofi_ic, seed=1)
    ic_nv = naive_ic(zy, zc, zo); ci_n = _day_block_boot(days, zy, zc, zo, naive_ic, seed=2)
    ic_pt = partial_ic(zy, zc, zo); ci_p = _day_block_boot(days, zy, zc, zo, partial_ic, seed=3)
    print(f"\n  OFI positive-control  IC = {ic_ofi:+.4f}  95%CI [{ci_o[0]:+.4f},{ci_o[1]:+.4f}]")
    print(f"  COHORT naive          IC = {ic_nv:+.4f}  95%CI [{ci_n[0]:+.4f},{ci_n[1]:+.4f}]")
    print(f"  COHORT PARTIAL | OFI  IC = {ic_pt:+.4f}  95%CI [{ci_p[0]:+.4f},{ci_p[1]:+.4f}]  <-- deliverable (day-block)")
    return con, panel, coins, alts, (coin, days, zy, zc, zo, cf, of, y)


if __name__ == "__main__":
    run()
