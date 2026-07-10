"""alt_confirm — positive control + walk-forward for the alt-breadth cohort (gate pillars 2 & 3).

Before EARNING the negative on the placebo FAIL (informed z=+0.91 vs random OOS), the OVER-NULLING GATE requires:
  (A) POSITIVE CONTROL — the alignment ranking must beat random IN-SAMPLE (on TRAIN). If it can't separate even on
      the data it was fit on, the instrument is dead (→ inconclusive). If it separates in-sample but NOT on TEST,
      that is genuine OOS decay = an earned method-scoped negative (selection doesn't persist).
  (B) WALK-FORWARD — expanding-train / forward-month folds; does informed beat random consistently across folds
      (sign test), or is every fold ≈ random? A cross-independent-unit combination, run BEFORE declaring null.

Reuses alt_flow.py machinery + cached alt_wb/alt_agg.

    .venv/bin/python -m research.studies.wallet_flow.alt_confirm
"""
from __future__ import annotations
import time, functools
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

FOLDS = (202603, 202604, 202605, 202606)
KF = 300
SEED = 20260709


def _pool_alignment(con, before_month, embargo_hour):
    q = con.execute(f"""
        WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid AS a
                   FROM awb wb JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h
                   WHERE wb.mth < {before_month} AND wb.h < {embargo_hour} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*) >= {A.MIN_TRAIN_BKT}""").fetchnumpy()
    return np.asarray([str(x) for x in q["wallet"]], dtype=object), q["al"].astype(float)


def _cells_and_flow(con, month_sql, flow_sql):
    cells = con.execute(f"""SELECT r.coin, r.h, r.fwd_resid, COALESCE(a.ofi,0) ofi
        FROM aresid r LEFT JOIN aagg a ON a.coin=r.coin AND a.h=r.h WHERE {month_sql}""").fetchnumpy()
    ccoin = np.asarray(cells["coin"], dtype=object); ch = cells["h"].astype(np.int64)
    fr = cells["fwd_resid"].astype(float); ofi = cells["ofi"].astype(float)
    cellkey = {(str(c), int(h)): i for i, (c, h) in enumerate(zip(ccoin, ch))}
    rows = con.execute(f"""SELECT wb.wallet, wb.coin, wb.h, wb.flow FROM awb wb WHERE {flow_sql}""").fetchnumpy()
    rw = np.asarray(rows["wallet"], dtype=object); rc = np.asarray(rows["coin"], dtype=object)
    rh = rows["h"].astype(np.int64); rf = rows["flow"].astype(float)
    cell_of = np.fromiter((cellkey.get((str(c), int(h)), -1) for c, h in zip(rc, rh)), np.int64, len(rf))
    return dict(ncell=len(fr), ccoin=ccoin, zy=A._zc(fr, ccoin), zo=A._zc(ofi, ccoin),
                cell_of=cell_of, rw=rw, rf=rf)


def _placebo(D, pool, al, k, seed):
    widx = {w: i for i, w in enumerate(pool)}
    wall_of = np.fromiter((widx.get(str(w), -1) for w in D["rw"]), np.int64, len(D["rf"]))
    keep = (D["cell_of"] >= 0) & (wall_of >= 0)
    cell_of, wall_of, rf = D["cell_of"][keep], wall_of[keep], D["rf"][keep]
    ncell, ccoin, zy, zo = D["ncell"], D["ccoin"], D["zy"], D["zo"]
    ncoh = int(round(A.COHORT_Q * len(pool)))
    def ic(mask_w):
        sel = mask_w[wall_of]
        cflow = np.bincount(cell_of[sel], weights=rf[sel], minlength=ncell)
        return A.partial_ic(zy, A._zc(cflow, ccoin), zo)
    informed = ic(al >= np.quantile(al, 1.0 - A.COHORT_Q))
    rng = np.random.default_rng(seed); null = np.empty(k)
    for i in range(k):
        m = np.zeros(len(pool), bool); m[rng.choice(len(pool), ncoh, replace=False)] = True
        null[i] = ic(m)
    mu, sd = null.mean(), null.std(ddof=1)
    z = (informed - mu) / sd; p = (1 + np.sum(null >= informed)) / (k + 1)
    return informed, mu, sd, z, p


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duckspill'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    coins = list(A.FACTORS) + A.universe(con, A.UNIV_FORMATION, include_majors=False)
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins); A.register_resid(con, panel)
    _log("machinery ready")
    first_test_h = int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0])

    # (A) POSITIVE CONTROL — informed vs random IN-SAMPLE (TRAIN cells, cohort frozen on TRAIN)
    pool, al = _pool_alignment(con, A.TEST_MONTH, first_test_h - A.H*3600000)
    Dtr = _cells_and_flow(con, f"r.month < {A.TEST_MONTH}", f"wb.mth < {A.TEST_MONTH}")
    inf, mu, sd, z, p = _placebo(Dtr, pool, al, 300, SEED)
    print("\n=== (A) POSITIVE CONTROL — in-sample (TRAIN) ===")
    print(f"  informed {inf:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}  "
          f"{'ranking works in-sample (OK)' if p < 0.05 else 'RANKING DEAD EVEN IN-SAMPLE (pipeline blind)'}")

    # (B) WALK-FORWARD — forward-month folds
    print("\n=== (B) WALK-FORWARD folds (informed vs random, TEST month) ===")
    zs = []
    for m in FOLDS:
        emb = int(con.execute(f"SELECT min(h) FROM aresid WHERE month={m}").fetchone()[0]) - A.H*3600000
        pool_m, al_m = _pool_alignment(con, m, emb)
        Dm = _cells_and_flow(con, f"r.month = {m}", f"wb.mth = {m}")
        inf, mu, sd, z, p = _placebo(Dm, pool_m, al_m, KF, SEED + m)
        zs.append(z)
        print(f"  {m}: informed {inf:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}")
    zs = np.array(zs); npos = int((zs > 0).sum())
    # sign test across folds (H0: informed beats random with prob 0.5)
    from math import comb
    p_sign = sum(comb(len(zs), i) for i in range(npos, len(zs)+1)) / 2**len(zs)
    print(f"\n  folds with informed>random: {npos}/{len(zs)}  sign-test p={p_sign:.3f}  "
          f"mean z={zs.mean():+.2f}")
    print(f"  {'consistent OOS lift' if p_sign < 0.05 else 'NO consistent OOS lift across folds'}")


if __name__ == "__main__":
    main()
