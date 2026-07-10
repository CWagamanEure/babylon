"""alt_sweep — the ANTI-RATCHET powered attempt before finalizing the alt-breadth negative (CLAUDE.md gate).

The pooled placebo used COHORT_Q=0.20 locked from majors. A random 20%-of-pool cohort overlaps the informed
cohort in ~20% of members BY CONSTRUCTION → dilutes the informed-vs-random gap. If the alt edge lives in a SHARP
tail of the most-aligned wallets, a top-5/2/1% cohort (little overlap, concentrated conviction) would separate
where top-20% washes out. This sweep is the "build a powered design, don't re-run the blind instrument" step: if
EVERY sharpness still fails the placebo, the OOS negative is fully earned; if a sharp tail clears, it's a live
underpowered positive to carry. Also runs a conviction-WEIGHTED cohort (all pool wallets, weight = alignment rank).

    .venv/bin/python -m research.studies.wallet_flow.alt_sweep
"""
from __future__ import annotations
import time, functools
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

QS = (0.20, 0.10, 0.05, 0.02, 0.01)
K = 400
SEED = 20260709


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duckspill'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    coins = list(A.FACTORS) + A.universe(con, A.UNIV_FORMATION, include_majors=False)
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins); A.register_resid(con, panel)
    first_test_h = int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0])
    emb = first_test_h - A.H*3600000
    q = con.execute(f"""
        WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid AS a
                   FROM awb wb JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h
                   WHERE wb.mth < {A.TEST_MONTH} AND wb.h < {emb} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*) >= {A.MIN_TRAIN_BKT}""").fetchnumpy()
    pool = np.asarray([str(x) for x in q["wallet"]], dtype=object); al = q["al"].astype(float)
    npool = len(pool); widx = {w: i for i, w in enumerate(pool)}

    cells = con.execute(f"""SELECT r.coin, r.h, r.fwd_resid, COALESCE(a.ofi,0) ofi
        FROM aresid r LEFT JOIN aagg a ON a.coin=r.coin AND a.h=r.h WHERE r.month >= {A.TEST_MONTH}""").fetchnumpy()
    ccoin = np.asarray(cells["coin"], dtype=object); ch = cells["h"].astype(np.int64)
    fr = cells["fwd_resid"].astype(float); ofi = cells["ofi"].astype(float)
    cellkey = {(str(c), int(h)): i for i, (c, h) in enumerate(zip(ccoin, ch))}
    ncell = len(fr); zy = A._zc(fr, ccoin); zo = A._zc(ofi, ccoin)
    rows = con.execute(f"SELECT wb.wallet, wb.coin, wb.h, wb.flow FROM awb wb WHERE wb.mth >= {A.TEST_MONTH}").fetchnumpy()
    rw = np.asarray(rows["wallet"], dtype=object); rc = np.asarray(rows["coin"], dtype=object)
    rh = rows["h"].astype(np.int64); rf = rows["flow"].astype(float)
    cell_of = np.fromiter((cellkey.get((str(c), int(h)), -1) for c, h in zip(rc, rh)), np.int64, len(rf))
    wall_of = np.fromiter((widx.get(str(w), -1) for w in rw), np.int64, len(rf))
    keep = (cell_of >= 0) & (wall_of >= 0)
    cell_of, wall_of, rf = cell_of[keep], wall_of[keep], rf[keep]
    _log(f"pool={npool:,} cells={ncell:,} rows={len(rf):,}")

    def ic_mask(mask_w):
        sel = mask_w[wall_of]
        return A.partial_ic(zy, A._zc(np.bincount(cell_of[sel], weights=rf[sel], minlength=ncell), ccoin), zo)

    print("\n=== COHORT-SHARPNESS SWEEP (partial IC|OFI, TEST; informed vs random same-size) ===")
    rng = np.random.default_rng(SEED)
    for qq in QS:
        ncoh = int(round(qq * npool))
        informed = ic_mask(al >= np.quantile(al, 1.0 - qq))
        null = np.empty(K)
        for i in range(K):
            m = np.zeros(npool, bool); m[rng.choice(npool, ncoh, replace=False)] = True
            null[i] = ic_mask(m)
        mu, sd = null.mean(), null.std(ddof=1); z = (informed - mu)/sd
        p = (1 + np.sum(null >= informed))/(K+1)
        flag = "  <-- clears" if p < 0.05 else ""
        print(f"  top {qq:>4.0%} (n={ncoh:>5,}): informed {informed:+.4f}  random {mu:+.4f}±{sd:.4f}  "
              f"z={z:+.2f}  p={p:.4f}{flag}")

    # conviction-WEIGHTED cohort: signed weight = demeaned alignment rank (uses all pool wallets, no cliff)
    wrank = (np.argsort(np.argsort(al)).astype(float)/(npool-1) - 0.5)   # in [-0.5,+0.5]
    wgt_by_wall = wrank
    sel = np.ones(len(rf), bool)
    cflow_w = np.bincount(cell_of, weights=rf*wgt_by_wall[wall_of], minlength=ncell)
    ic_w = A.partial_ic(zy, A._zc(cflow_w, ccoin), zo)
    # null: shuffle the alignment->wallet assignment
    nullw = np.empty(K)
    for i in range(K):
        perm = rng.permutation(npool)
        nullw[i] = A.partial_ic(zy, A._zc(np.bincount(cell_of, weights=rf*wgt_by_wall[perm][wall_of], minlength=ncell), ccoin), zo)
    muw, sdw = nullw.mean(), nullw.std(ddof=1); zw = (ic_w-muw)/sdw; pw = (1+np.sum(nullw>=ic_w))/(K+1)
    print(f"\n  conviction-weighted (all {npool:,}): IC {ic_w:+.4f}  shuffled {muw:+.4f}±{sdw:.4f}  "
          f"z={zw:+.2f}  p={pw:.4f}{'  <-- clears' if pw<0.05 else ''}")


if __name__ == "__main__":
    main()
