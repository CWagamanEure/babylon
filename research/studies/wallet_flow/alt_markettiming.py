"""alt_markettiming — B's re-frame: is the cohort signal ALT-COMPLEX TIMING, not per-name cross-sectional alpha?

Agent B: the LOO-alt-index neutralization deletes ~40% of the IC and the market-KEPT IC grows to +0.0106 @24h.
Hypothesis: the informed cohort partly predicts the WHOLE alt-complex move, which the per-name factor-neutral target
defines away. That estimand is structurally cheaper to trade (ONE basket long/short vs a 45-name book). Test it:
  SIGNAL  = aggregate cohort directional tilt across all alts per hour, using the COHERENT breadth vote
            (per hour: (#cohort long − #cohort short)/(#active), summed over coins) — the fix from Result 8.
  TARGET  = forward cumulative return of the equal-weight ALT INDEX, BTC/ETH-neutralized (the alt-rotation the LOO
            index removed) — raw index also reported. H ∈ {1,4,8,24} (B: peaks ~24h).
  TEST    = does the FROZEN informed cohort's tilt predict fwd index return, and beat RANDOM same-size cohorts
            (placebo, K)?  Plus the discriminator: OLS beta of fwd-index on tilt, day-block bootstrap t.
Cohort frozen on TRAIN cross-sectional alignment (same as production) → this asks whether the SAME informed wallets
also time the complex. Everything OOS for selection. Reuses alt_flow machinery + cached awb.

    .venv/bin/python -m research.studies.wallet_flow.alt_markettiming
"""
from __future__ import annotations
import time, functools
import numpy as np
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

HORIZONS = (1, 4, 8, 24)
K = 500; SEED = 20260710
Wb, MINOBS = 720, 240


def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30: return np.nan
    ra = np.argsort(np.argsort(a[m])).astype(float); rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean(); d = np.sqrt((ra@ra)*(rb@rb))
    return (ra@rb)/d if d > 0 else np.nan


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_mt'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins); A.register_resid(con, panel)
    hours, ci = panel["hours"], panel["ci"]; N = panel["N"]
    _log("machinery ready")

    # --- ALT INDEX return series (equal-weight alt log-return), BTC/ETH-neutralized (causal) ---
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hb2 AS
        WITH v AS (SELECT coin, ts, (ts - ts%3600000) AS h, mid_px FROM asset_ctx
                   WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
                     AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin, h, arg_max(mid_px, ts) AS mid FROM v GROUP BY coin, h""")
    d = con.execute("SELECT coin,h,mid FROM hb2").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64)
    hmin = int(hours[0]); C = len(coins)
    Lp = np.full((N, C), np.nan)
    rr = ((ha - hmin)//3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok])
    R = np.diff(Lp, axis=0, prepend=np.nan)
    altcols = [ci[c] for c in alts]
    idx_raw = np.nanmean(R[:, altcols], axis=1)                    # equal-weight alt index return
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]
    eth_o = eth - rolling_beta(eth, btc, Wb, MINOBS)*btc
    idx_n = idx_raw - rolling_beta(idx_raw, btc, Wb, MINOBS)*btc
    idx_n = idx_n - rolling_beta(idx_n, eth_o, Wb, MINOBS)*eth_o    # alt-specific complex move
    def fwd_cum(series, H):
        out = np.full(N, np.nan)
        cs = np.where(np.isfinite(series), series, 0.0)
        for h in range(N-H):
            out[h] = cs[h+1:h+1+H].sum()
        return out

    # --- cohort freeze (production: top 20% cross-sectional alignment, H-embargo) ---
    first_test_h = int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0])
    emb = first_test_h - A.H*3600000
    q = con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM awb wb
        JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h
        WHERE wb.mth<{A.TEST_MONTH} AND wb.h<{emb} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*)>={A.MIN_TRAIN_BKT}""").fetchnumpy()
    pool = np.asarray([str(x) for x in q["wallet"]], dtype=object); al = q["al"].astype(float)
    npool = len(pool); widx = {w:i for i,w in enumerate(pool)}
    ncoh = int(round(0.20*npool)); informed = al >= np.quantile(al, 0.80)

    # --- cohort tilt per hour (breadth vote) over TEST hours ---
    rows = con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.mth>={A.TEST_MONTH} AND wb.flow<>0").fetchnumpy()
    rw = np.asarray(rows["wallet"], dtype=object); rh = rows["h"].astype(np.int64); rf = rows["flow"].astype(float)
    hour_of = ((rh - hmin)//3600000).astype(int)
    wall_of = np.fromiter((widx.get(str(w), -1) for w in rw), np.int64, len(rf))
    keep = (wall_of >= 0) & (hour_of >= 0) & (hour_of < N)
    hour_of, wall_of, rf = hour_of[keep], wall_of[keep], rf[keep]
    pos, neg = rf > 0, rf < 0
    test_hmask = np.zeros(N, bool); test_hmask[np.unique(hour_of)] = True
    _log(f"pool={npool:,} test rows={len(rf):,} test hours={test_hmask.sum()}")

    def tilt(mask):
        sel = mask[wall_of]
        npos = np.bincount(hour_of[sel & pos], minlength=N).astype(float)
        nneg = np.bincount(hour_of[sel & neg], minlength=N).astype(float)
        den = npos + nneg
        t = np.where(den > 0, (npos - nneg)/np.maximum(den, 1), np.nan)
        t[~test_hmask] = np.nan
        return t

    rng = np.random.default_rng(SEED)
    print("\n=== ALT-COMPLEX TIMING: cohort tilt(t) → forward alt-index return (TEST) ===")
    print("target = BTC/ETH-neutralized equal-weight alt index, cumulative forward H hours")
    inf_t = tilt(informed)
    for tgt_name, tgt in [("alt-index NEUTRAL", idx_n), ("alt-index RAW", idx_raw)]:
        print(f"\n-- target: {tgt_name} --")
        for H in HORIZONS:
            fwd = fwd_cum(tgt, H)
            ic_inf = _spear(inf_t, fwd)
            null = np.empty(K)
            for k in range(K):
                m = np.zeros(npool, bool); m[rng.choice(npool, ncoh, replace=False)] = True
                null[k] = _spear(tilt(m), fwd)
            mu, sd = np.nanmean(null), np.nanstd(null)
            z = (ic_inf - mu)/sd if sd > 0 else np.nan
            p = (1 + np.sum(null >= ic_inf))/(K+1)
            flag = "  <-- clears" if p < 0.05 else ""
            print(f"  H={H:>2}h: informed IC {ic_inf:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}{flag}")


if __name__ == "__main__":
    main()
