"""walkforward — robustness of the informed-cohort signal across multiple OOS folds.

flow.py established the informed cohort's partial IC | OFI = +0.030 at 1h on ONE test window (>=202603),
and placebo.py showed the SELECTION (not just big-basket flow) drives it (p=0.033 on that window). Open
question: is +0.030 a STABLE feature or one lucky quarter? This rolls expanding-train / single-month-forward
folds and, in EACH fold, (a) freezes the informed cohort on train-only, (b) measures its partial IC on that
one forward month, (c) re-runs K random same-size cohorts to get informed-vs-random per fold.

Deliverable per horizon: fold-by-fold informed partial IC (sign consistency), and per-fold informed-minus-
random gap (does selection beat random every month, not just pooled?). Reuses flow.py machinery verbatim.

  .venv/bin/python -m research.studies.wallet_flow.walkforward
"""
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import flow
from research.studies.wallet_flow.flow import (
    build_resid, build_wallet_tables, register_resid,
    partial_ic, _zc, _ols_resid, _spearman,
    MIN_TRAIN_BKT, COHORT_Q, HORIZONS, SCRATCH,
)

K_PLACEBO = 40
MAJORS = flow.MAJORS


def _fetch_pool(con, test_month):
    """Eligible pool ranked on TRAIN = every month strictly before test_month."""
    q = con.execute(f"""
        WITH j AS (
            SELECT wb.wallet, sign(wb.flow) * r.fwd_resid AS a
            FROM wb JOIN resid r ON wb.coin=r.coin AND wb.h=r.h
            WHERE wb.mth < {test_month} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL
        )
        SELECT wallet, avg(a) AS align FROM j GROUP BY wallet HAVING count(*) >= {MIN_TRAIN_BKT}
    """).fetchnumpy()
    return np.asarray(q["wallet"], dtype=object), q["align"].astype(float)


def _set_cohort(con, cohort):
    con.register("cohort_src", {"wallet": np.array([str(w) for w in cohort], dtype=object)})
    con.execute("CREATE OR REPLACE TEMP TABLE cohort AS SELECT * FROM cohort_src")
    con.unregister("cohort_src")


def _partial_ic(con, cohort, test_month):
    """Freeze cohort, evaluate partial IC | OFI on the SINGLE forward month test_month."""
    _set_cohort(con, cohort)
    q = con.execute(f"""
        WITH cf AS (
            SELECT wb.coin, wb.h, sum(wb.flow) AS cohort_flow
            FROM wb JOIN cohort c USING(wallet)
            WHERE wb.mth = {test_month} GROUP BY wb.coin, wb.h
        )
        SELECT r.coin, r.fwd_resid, COALESCE(cf.cohort_flow,0) AS cohort_flow,
               COALESCE(agg.ofi,0) AS ofi
        FROM resid r
        LEFT JOIN cf  ON cf.coin=r.coin  AND cf.h=r.h
        LEFT JOIN agg ON agg.coin=r.coin AND agg.h=r.h
        WHERE r.month = {test_month}
    """).fetchnumpy()
    coin = np.asarray(q["coin"], dtype=object)
    y = q["fwd_resid"].astype(float); cflow = q["cohort_flow"].astype(float); ofi = q["ofi"].astype(float)
    zy = _zc(y, coin); zc = _zc(cflow, coin); zo = _zc(ofi, coin)
    return partial_ic(zy, zc, zo, coin), int(np.isfinite(y).sum())


def run():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='900MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'")
    con.execute("SET preserve_insertion_order=false")

    print("[1/2] price/residual panel ...")
    panel = build_resid(con)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM fills ORDER BY month").fetchall()]
    print(f"[2/2] wallet flow tables (cached): {months}")
    build_wallet_tables(con, months)

    # expanding-train / single-month-forward: test each of the last 5 months, train = all prior months
    test_months = months[-5:]
    print(f"\nfolds (expanding train, single forward month): test months = {test_months}")

    for H in HORIZONS:
        print(f"\n{'='*72}\nWALK-FORWARD @ horizon h={H} ({H}h)\n{'='*72}")
        register_resid(con, panel, H)
        rows = []
        for tm in test_months:
            wallets, align = _fetch_pool(con, tm)
            npool = len(wallets)
            if npool < 100:
                print(f"  test {tm}: pool too small ({npool}); skip"); continue
            thr = np.quantile(align, 1.0 - COHORT_Q)
            informed = wallets[align >= thr]; nc = len(informed)
            ic_inf, nobs = _partial_ic(con, informed, tm)
            pl = []
            for s in range(K_PLACEBO):
                rng = np.random.default_rng(7000 + s)
                samp = wallets[rng.choice(npool, size=nc, replace=False)]
                v, _ = _partial_ic(con, samp, tm)
                if np.isfinite(v):
                    pl.append(v)
            pl = np.array(pl)
            pmu, psd = pl.mean(), pl.std(ddof=1)
            p_hi = float(np.mean(pl >= ic_inf))
            rows.append((tm, nobs, npool, nc, ic_inf, pmu, psd, ic_inf - pmu, p_hi))
            print(f"  test {tm}: n={nobs:5d} pool={npool:6d} informed IC={ic_inf:+.4f}  "
                  f"random {pmu:+.4f}±{psd:.4f}  gap={ic_inf-pmu:+.4f}  p(rand>=inf)={p_hi:.3f}")

        if rows:
            ics = np.array([r[4] for r in rows]); gaps = np.array([r[7] for r in rows])
            npos = int((ics > 0).sum()); ngap = int((gaps > 0).sum()); nf = len(rows)
            # sign test vs 50/50 (folds are disjoint forward months -> ~independent)
            from math import comb
            def sign_p(k, n):
                return sum(comb(n, j) for j in range(k, n + 1)) / 2 ** n
            print(f"\n  SUMMARY h={H}: informed IC positive in {npos}/{nf} folds "
                  f"(sign-test p={sign_p(npos, nf):.3f}); mean IC={ics.mean():+.4f}")
            print(f"             informed BEATS random in {ngap}/{nf} folds "
                  f"(sign-test p={sign_p(ngap, nf):.3f}); mean gap={gaps.mean():+.4f}")
    con.close()


if __name__ == "__main__":
    run()
