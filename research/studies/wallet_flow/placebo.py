"""placebo — the make-or-break check for wallet_flow.

The informed cohort (top-20% by TRAIN alignment = sign(flow)*fwd_resid) showed partial IC +0.030 at 1h,
CI excluding zero, OOS. QUESTION: is that because the ALIGNMENT SELECTION carries information, or just
because ANY basket of big active wallets' net flow predicts (i.e. it's OFI-in-disguise)?

Test: draw many RANDOM cohorts of the SAME size from the SAME eligibility pool (wallets with >=MIN_TRAIN_BKT
active train buckets), freeze each, evaluate its partial-IC on the SAME held-out test panel. If the informed
cohort's partial IC sits inside the random distribution -> the alignment feature adds nothing (prosecute the
positive succeeds; demote). If it sits in the extreme tail -> informedness is a real, selected feature.

Reuses flow.py's leak-disciplined machinery verbatim (same resid, same test panel, same partial_ic).

  .venv/bin/python -m research.studies.wallet_flow.placebo
"""
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import flow
from research.studies.wallet_flow.flow import (
    build_resid, build_wallet_tables, register_resid, test_panel,
    partial_ic, block_boot_stat, _zc, _ols_resid, _spearman,
    TEST_MONTH, MIN_TRAIN_BKT, COHORT_Q, HORIZONS, SCRATCH,
)

K_PLACEBO = 60          # random cohorts per horizon
MAJORS = flow.MAJORS


def _fetch_pool(con):
    """Eligible pool = wallets with >=MIN_TRAIN_BKT active TRAIN buckets, with their TRAIN alignment."""
    q = con.execute(f"""
        WITH j AS (
            SELECT wb.wallet, sign(wb.flow) * r.fwd_resid AS a
            FROM wb JOIN resid r ON wb.coin=r.coin AND wb.h=r.h
            WHERE wb.mth < {TEST_MONTH} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL
        )
        SELECT wallet, avg(a) AS align, count(*) AS nb
        FROM j GROUP BY wallet HAVING count(*) >= {MIN_TRAIN_BKT}
    """).fetchnumpy()
    return np.asarray(q["wallet"], dtype=object), q["align"].astype(float)


def _set_cohort(con, cohort):
    con.register("cohort_src", {"wallet": np.array([str(w) for w in cohort], dtype=object)})
    con.execute("CREATE OR REPLACE TEMP TABLE cohort AS SELECT * FROM cohort_src")
    con.unregister("cohort_src")


def _partial_ic_of_cohort(con, cohort, panel_H_registered_already=True):
    """Freeze `cohort`, build the test panel, return its partial IC | OFI (same recipe as flow.run)."""
    _set_cohort(con, cohort)
    tp = test_panel(con, None)
    coin = np.asarray(tp["coin"], dtype=object)
    y = tp["fwd_resid"].astype(float)
    cflow = tp["cohort_flow"].astype(float)
    ofi = tp["ofi"].astype(float)
    zy = _zc(y, coin); zc = _zc(cflow, coin); zo = _zc(ofi, coin)
    return partial_ic(zy, zc, zo, coin)


def run():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='900MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'")
    con.execute("SET preserve_insertion_order=false")

    print("[1/3] price/residual panel ...")
    panel = build_resid(con)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM fills ORDER BY month").fetchall()]
    print(f"[2/3] wallet flow tables (cached from flow.py run): {months}")
    build_wallet_tables(con, months)

    for H in HORIZONS:
        print(f"\n{'='*70}\nPLACEBO @ horizon h={H} ({H}h)\n{'='*70}")
        register_resid(con, panel, H)
        wallets, align = _fetch_pool(con)
        npool = len(wallets)
        thr = np.quantile(align, 1.0 - COHORT_Q)
        informed = wallets[align >= thr]
        ncohort = len(informed)
        print(f"  eligible pool = {npool:,} wallets; informed cohort (top {COHORT_Q:.0%}) = {ncohort:,}")

        ic_informed = _partial_ic_of_cohort(con, informed)
        print(f"  INFORMED cohort partial IC | OFI = {ic_informed:+.4f}")

        placebo_ics = []
        for s in range(K_PLACEBO):
            rng = np.random.default_rng(1000 + s)
            samp = wallets[rng.choice(npool, size=ncohort, replace=False)]
            placebo_ics.append(_partial_ic_of_cohort(con, samp))
        placebo_ics = np.array([v for v in placebo_ics if np.isfinite(v)])
        mu, sd = placebo_ics.mean(), placebo_ics.std(ddof=1)
        p_hi = float(np.mean(placebo_ics >= ic_informed))          # one-sided empirical p
        lo, hi = np.percentile(placebo_ics, [2.5, 97.5])
        z = (ic_informed - mu) / sd if sd > 0 else np.nan
        print(f"  RANDOM cohorts (n={len(placebo_ics)}): partial IC mean={mu:+.4f} sd={sd:.4f} "
              f"95%band=[{lo:+.4f},{hi:+.4f}]")
        print(f"  --> informed vs random: z={z:+.2f}, empirical one-sided p(random>=informed) = {p_hi:.3f}")
        verdict = ("SELECTION MATTERS (informed in the extreme tail)" if p_hi <= 0.05 else
                   "SELECTION ADDS NOTHING (informed inside random dist) -> demote" if p_hi >= 0.20 else
                   "AMBIGUOUS (informed elevated but not decisive)")
        print(f"  VERDICT: {verdict}")
    con.close()


if __name__ == "__main__":
    run()
