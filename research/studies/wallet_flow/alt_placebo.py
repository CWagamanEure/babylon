"""alt_placebo — the make-or-break test for the alt-breadth cohort (ALT_BREADTH_AUDIT_RESPONSE §OVER-CARRY-2).

The partial IC|OFI = +0.0058 [-0.0006,+0.0123] narrowly straddles zero vs the null of NO effect. That is the wrong
null for "does the SELECTION do anything" — a random 20% of the same eligible pool has its own baseline IC. So:
draw K random same-size cohorts from the SAME MIN_TRAIN_BKT-eligible pool, recompute partial IC|OFI on TEST for
each, and ask whether the alignment-frozen cohort beats that random distribution (majors gave z=+2.17, p=0.033).

Reuses the cached alt_wb/alt_agg parquet + the alt_flow.py machinery (residual panel rebuilt in ~17s).

    .venv/bin/python -m research.studies.wallet_flow.alt_placebo
"""
from __future__ import annotations
import time, functools
from pathlib import Path
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

K = 500
SEED = 20260709


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duckspill'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); _log(f"resid ({panel['N']}h)")
    A.build_cohort_tables(con, coins); A.register_resid(con, panel)   # views awb/aagg (cached parquet) + aresid
    first_test_h = int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0])

    # eligible pool + each wallet's TRAIN alignment (H-embargo) — the informed cohort is the top COHORT_Q of this
    emb = first_test_h - A.H*3600000
    q = con.execute(f"""
        WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid AS a
                   FROM awb wb JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h
                   WHERE wb.mth < {A.TEST_MONTH} AND wb.h < {emb} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*) >= {A.MIN_TRAIN_BKT}""").fetchnumpy()
    pool = np.asarray([str(x) for x in q["wallet"]], dtype=object); al = q["al"].astype(float)
    npool = len(pool); ncoh = int(round(A.COHORT_Q * npool))
    widx = {w: i for i, w in enumerate(pool)}
    informed_mask = al >= np.quantile(al, 1.0 - A.COHORT_Q)
    _log(f"pool={npool:,} cohort={informed_mask.sum():,}")

    # TEST cells (coin,hour) with a valid fwd_resid + their OFI; pull cohort-flow rows for pool wallets on TEST
    cells = con.execute(f"""SELECT r.coin, r.h, r.fwd_resid, COALESCE(a.ofi,0) ofi
        FROM aresid r LEFT JOIN aagg a ON a.coin=r.coin AND a.h=r.h
        WHERE r.month >= {A.TEST_MONTH}""").fetchnumpy()
    ccoin = np.asarray(cells["coin"], dtype=object); ch = cells["h"].astype(np.int64)
    fr = cells["fwd_resid"].astype(float); ofi = cells["ofi"].astype(float)
    cellkey = {(str(c), int(h)): i for i, (c, h) in enumerate(zip(ccoin, ch))}
    ncell = len(fr)
    zy = A._zc(fr, ccoin); zo = A._zc(ofi, ccoin)

    rows = con.execute(f"""SELECT wb.wallet, wb.coin, wb.h, wb.flow FROM awb wb
        WHERE wb.mth >= {A.TEST_MONTH}""").fetchnumpy()
    rw = np.asarray(rows["wallet"], dtype=object); rc = np.asarray(rows["coin"], dtype=object)
    rh = rows["h"].astype(np.int64); rf = rows["flow"].astype(float)
    cell_of = np.fromiter((cellkey.get((str(c), int(h)), -1) for c, h in zip(rc, rh)), np.int64, len(rf))
    wall_of = np.fromiter((widx.get(str(w), -1) for w in rw), np.int64, len(rf))
    keep = (cell_of >= 0) & (wall_of >= 0)
    cell_of, wall_of, rf = cell_of[keep], wall_of[keep], rf[keep]
    _log(f"test flow rows={len(rf):,} over {ncell:,} cells")

    def ic_for(mask_w):
        sel = mask_w[wall_of]
        cflow = np.bincount(cell_of[sel], weights=rf[sel], minlength=ncell)
        zc = A._zc(cflow, ccoin)
        return A.partial_ic(zy, zc, zo)

    informed_ic = ic_for(informed_mask)
    rng = np.random.default_rng(SEED)
    null = np.empty(K)
    for k in range(K):
        m = np.zeros(npool, bool); m[rng.choice(npool, ncoh, replace=False)] = True
        null[k] = ic_for(m)
        if (k+1) % 100 == 0: _log(f"placebo {k+1}/{K}")
    mu, sd = null.mean(), null.std(ddof=1)
    z = (informed_ic - mu) / sd
    p_hi = (1 + np.sum(null >= informed_ic)) / (K + 1)          # one-sided (informed beats random)
    lo, hi = np.percentile(null, [2.5, 97.5])
    print("\n=== ALT-BREADTH PLACEBO (partial IC|OFI, TEST) ===")
    print(f"  informed cohort IC = {informed_ic:+.4f}")
    print(f"  random null: mean {mu:+.4f}  sd {sd:.4f}  95%band [{lo:+.4f},{hi:+.4f}]  (K={K})")
    print(f"  z = {z:+.2f}   one-sided p (informed>random) = {p_hi:.4f}")
    print(f"  {'PASS' if p_hi < 0.05 else 'FAIL'} the placebo at 0.05 (majors: z=+2.17, p=0.033)")
    np.save(f"{A.SCRATCH}/alt_placebo_null.npy", null)


if __name__ == "__main__":
    main()
