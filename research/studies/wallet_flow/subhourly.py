"""subhourly — does the informed-cohort edge live INSIDE the hour? (the hourly work never looked)

Hourly analysis said the edge is a "lag-0 impulse" (all in the same hour as the signal) — the signature of a
sub-hourly effect blurred at 60-min resolution. Here we re-measure at 1/5/15-min buckets, reusing the FROZEN
hourly cohort (leak-free: cohort ids fixed on hourly TRAIN<202603, evaluated on TEST>=202603).

Two questions:
  (1) INTRA-HOUR DECAY — cohort flow in a fine bucket -> forward factor-neutral residual at 5,10,15,30,60 min.
      Where does the edge peak and die? (A3: forward = strictly POST-bucket, no own-impact contamination.)
  (2) BURST EVENT STUDY — when cohort flow SPIKES in a fine bucket, is the signed forward move big enough that
      ONE round trip (2 crossings ~9-11 bp taker) nets positive? This is the cost equation the hourly book
      couldn't clear (pay a crossing every hour for 1.5 bp) — a fast burst may pay a crossing rarely for more.

Firewalled: reads asset_ctx (per-minute majors mid) + fills. Reuses flow.freeze_cohort for the frozen cohort.
  .venv/bin/python -m research.studies.wallet_flow.subhourly
"""
import datetime as dt
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import flow
from research.studies.wallet_flow.flow import (
    build_resid, build_wallet_tables, register_resid, freeze_cohort, TEST_MONTH, SCRATCH,
)
from research.studies.xsec_statarb.leadlag import rolling_beta

MAJORS = flow.MAJORS
FEE_BP = 4.5
HS = {"BTC": 0.07, "ETH": 0.23, "SOL": 0.28, "HYPE": 0.97}   # half-spreads bp (from asset_ctx impact px)
BETA_W_DAYS = 30


def _rank(x): return np.argsort(np.argsort(x)).astype(float)
def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 20: return np.nan
    ra, rb = _rank(a[m]), _rank(b[m]); ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra @ ra) * (rb @ rb)); return (ra @ rb) / d if d > 0 else np.nan


def build_fine(con, B_min, horizons):
    """Fine factor-neutral residual panel at B-minute buckets; returns hours grid + fwd_resid/fwd_raw per horizon."""
    ms = B_min * 60000
    con.execute(f"""CREATE OR REPLACE TEMP TABLE fbars AS
        WITH v AS (SELECT coin, ts, (ts - ts%{ms}) AS b, mid_px FROM asset_ctx
                   WHERE coin IN {MAJORS} AND mid_px>0)
        SELECT coin, b, arg_max(mid_px, ts) AS mid FROM v GROUP BY coin, b""")
    d = con.execute("SELECT coin, b, mid FROM fbars").fetchnumpy()
    coin = np.asarray(d["coin"], dtype=object); b = d["b"].astype(np.int64)
    ci = {c: i for i, c in enumerate(MAJORS)}
    bmin, bmax = int(b.min()), int(b.max())
    grid = np.arange(bmin, bmax + 1, ms, dtype=np.int64); N = len(grid)
    rows = ((b - bmin) // ms).astype(int); cols = np.array([ci[str(c)] for c in coin])
    Lp = np.full((N, 4), np.nan); Lp[rows, cols] = np.log(d["mid"].astype(float))
    R = np.diff(Lp, axis=0, prepend=np.nan)
    tot = np.nansum(R, axis=1, keepdims=True); cnt = np.sum(np.isfinite(R), axis=1, keepdims=True)
    W = int(BETA_W_DAYS * 24 * 60 / B_min); minobs = W // 3
    beta = np.full((N, 4), np.nan); loo = np.full((N, 4), np.nan)
    for i in range(4):
        loo[:, i] = np.where(cnt[:, 0] - np.isfinite(R[:, i]) > 0,
                             (tot[:, 0] - np.where(np.isfinite(R[:, i]), R[:, i], 0.0)) /
                             (cnt[:, 0] - np.isfinite(R[:, i]).astype(int)), np.nan)
        beta[:, i] = rolling_beta(R[:, i], loo[:, i], W, minobs)
    resid, raw = {}, {}
    for h in horizons:
        fr = np.full((N, 4), np.nan); rw = np.full((N, 4), np.nan)
        fwd_all = Lp[h:, :] - Lp[:-h, :]
        for i in range(4):
            fwd = fwd_all[:, i]
            lf = np.where(np.sum(np.isfinite(fwd_all), 1) - np.isfinite(fwd) > 0,
                          (np.nansum(fwd_all, 1) - np.where(np.isfinite(fwd), fwd, 0.0)) /
                          (np.sum(np.isfinite(fwd_all), 1) - np.isfinite(fwd).astype(int)), np.nan)
            fr[:-h, i] = fwd - beta[:-h, i] * lf
            rw[:-h, i] = fwd
        resid[h] = fr; raw[h] = rw
    month = np.array([(dt.datetime.fromtimestamp(int(x)/1000, tz=dt.timezone.utc).year*100 +
                       dt.datetime.fromtimestamp(int(x)/1000, tz=dt.timezone.utc).month) for x in grid])
    return dict(grid=grid, month=month, N=N, resid=resid, raw=raw, ms=ms)


def cohort_flow_fine(con, B_min, months):
    """Per (coin, B-min bucket) frozen-cohort net signed flow, TEST months only (cohort temp table must exist)."""
    ms = B_min * 60000
    co, bb, fl = [], [], []
    for m in [x for x in months if x >= TEST_MONTH]:
        q = con.execute(f"""
            SELECT f.coin, (f.ts - f.ts%{ms}) AS b,
                   sum(CASE WHEN f.side='B' THEN f.notional_usd ELSE -f.notional_usd END) AS flow
            FROM fills f JOIN cohort c USING(wallet)
            WHERE f.month={m} AND f.is_vault=false
            GROUP BY f.coin, b""").fetchnumpy()
        co.append(np.asarray(q["coin"], dtype=object)); bb.append(q["b"].astype(np.int64))
        fl.append(q["flow"].astype(float))
    return np.concatenate(co), np.concatenate(bb), np.concatenate(fl)


def run():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1200MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'")
    con.execute("SET preserve_insertion_order=false")
    print("[setup] hourly panel + frozen cohort ...")
    panel = build_resid(con)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM fills ORDER BY month").fetchall()]
    build_wallet_tables(con, months)
    register_resid(con, panel, 1)
    cohort, npool = freeze_cohort(con, 1)   # creates temp table `cohort`
    print(f"[setup] frozen cohort = {len(cohort):,} wallets (pool {npool:,}); reused at fine resolution\n")

    for B in (5, 1):
        hz = {5: [1, 2, 3, 6, 12], 1: [1, 2, 3, 5, 10, 15, 30, 60]}[B]
        mins = [h * B for h in hz]
        print(f"{'='*72}\nBUCKET = {B} min   (horizons {mins} min)\n{'='*72}")
        fp = build_fine(con, B, hz)
        co, bk, fl = cohort_flow_fine(con, B, months)
        ci = {c: i for i, c in enumerate(MAJORS)}
        # index cohort flow onto the grid
        gidx = ((bk - fp["grid"][0]) // fp["ms"]).astype(np.int64)
        ok = (gidx >= 0) & (gidx < fp["N"])
        cf = np.zeros((fp["N"], 4))
        ci_col = np.array([ci[str(c)] for c in co])
        cf[gidx[ok], ci_col[ok]] = fl[ok]
        test = fp["month"] >= TEST_MONTH

        # (1) INTRA-HOUR IC DECAY (cohort flow -> forward residual), pooled z within coin
        print("  (1) intra-hour IC decay (cohort flow -> forward RESIDUAL):")
        print(f"      {'horizon':>8} {'IC':>8} {'n':>8}")
        for h, mn in zip(hz, mins):
            fr = fp["resid"][h]
            xs, ys = [], []
            for i in range(4):
                mask = test & (cf[:, i] != 0) & np.isfinite(fr[:, i])
                x = cf[mask, i]; y = fr[mask, i]
                if len(x) > 20:
                    x = (x - x.mean()) / (x.std() + 1e-12); y = (y - y.mean()) / (y.std() + 1e-12)
                    xs.append(x); ys.append(y)
            if xs:
                X = np.concatenate(xs); Y = np.concatenate(ys)
                print(f"      {mn:>6}m {_spear(X, Y):>+8.4f} {len(X):>8,}")

        # (2) BURST EVENT STUDY: top-decile |cohort flow| within coin (test), signed fwd cum return vs cost
        print("\n  (2) burst event study (top-decile |cohort flow| bucket, signed forward move):")
        for scope, coins in (("ALL majors", MAJORS), ("HYPE only", ("HYPE",))):
            print(f"    [{scope}]  {'horizon':>7} {'sRESID':>8} {'sRAW':>8} {'RTcost':>7} {'netRAW':>8} {'n':>7}")
            for h, mn in zip(hz, mins):
                fr = fp["resid"][h]; rw = fp["raw"][h]
                sres, sraw, ns, costs = [], [], 0, []
                for c in coins:
                    i = ci[c]
                    m0 = test & (cf[:, i] != 0)
                    if m0.sum() < 50: continue
                    thr = np.quantile(np.abs(cf[m0, i]), 0.90)
                    ev = m0 & (np.abs(cf[:, i]) >= thr) & np.isfinite(fr[:, i]) & np.isfinite(rw[:, i])
                    if ev.sum() < 10: continue
                    sgn = np.sign(cf[ev, i])
                    sres.append(1e4 * sgn * fr[ev, i]); sraw.append(1e4 * sgn * rw[ev, i])
                    ns += ev.sum(); costs.append(2 * (HS[c] + FEE_BP))
                if not sres: continue
                SR = np.concatenate(sres); RW = np.concatenate(sraw); rt = float(np.mean(costs))
                print(f"    {'':13} {mn:>5}m {SR.mean():>+8.2f} {RW.mean():>+8.2f} {rt:>7.1f} "
                      f"{RW.mean()-rt:>+8.2f} {ns:>7,}")
    con.close()


if __name__ == "__main__":
    run()
