"""alt_breadth_confirm — decisive confirmation of the swarm's strongest thread (agent C: consensus-breadth aggregator).

C found the deployed cohort signal (Σ dollar flow) is whale-dominated + net-cancelling and INCOHERENT with how the
cohort was selected (sign-agreement). Swapping to a consensus-breadth aggregator (#long−#short)/#active on the SAME
cohort ~doubles IC (+0.0058→+0.0112) and flips the load-bearing placebo from FAIL (z=0.9) to CLEAR (z=3.6) at the
PRE-REGISTERED Q=0.20 (no argmax). This script confirms it and runs the two must-pass confounds C flagged:
  1. REPRODUCE breadth IC + placebo z (sanity vs C).
  2. PER-COIN breadth-consistency (E's pillar-3 on breadth): is it breadth-wide, or a few coins like the net agg?
  3. SECTOR-HERDING confound (the never-built F4 control): sector×hour-demean the residual → does breadth survive?
  4. DAY-BLOCK CI on breadth IC (slow-drift autocorrelation).
Everything sub-cost regardless (IC~0.011 → ~0.7 bp gross/crossing); this adjudicates REAL-signal, not deployability.

    .venv/bin/python -m research.studies.wallet_flow.alt_breadth_confirm
"""
from __future__ import annotations
import time, functools
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

K = 500; SEED = 20260710
SECTOR = {
 **{c:"meme" for c in ["PUMP","FARTCOIN","DOGE","kPEPE","TRUMP","PENGU","SPX","kBONK","WIF","MON","CC","SKR"]},
 **{c:"ai" for c in ["TAO","VIRTUAL","VVV","WLD"]},
 **{c:"l1" for c in ["XRP","SUI","BNB","BERA","BCH","ADA","AVAX","DOT","NEAR","APT","LTC"]},
 **{c:"defi" for c in ["AAVE","UNI","LINK","CRV","JUP","ENA","RESOLV","LIT","AXS","ZRO","ARB"]},
 **{c:"priv" for c in ["ZEC","XMR"]}, **{c:"rwa" for c in ["PAXG","STABLE"]},
 **{c:"other" for c in ["WLFI","ASTER","XPL"]},
}


def _sector_demean(y, coin, hour):
    """Subtract the sector×hour mean residual (herding control). coin→sector via SECTOR."""
    sec = np.array([SECTOR.get(str(c), "other") for c in coin], dtype=object)
    key = np.array([f"{s}|{h}" for s, h in zip(sec, hour)], dtype=object)
    out = y.copy()
    order = np.argsort(key, kind="stable"); ks = key[order]
    b = 0
    for i in range(1, len(ks)+1):
        if i == len(ks) or ks[i] != ks[b]:
            idx = order[b:i]; v = y[idx]; m = np.isfinite(v)
            if m.sum() >= 2: out[idx] = v - np.nanmean(v)
            b = i
    return out


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_confirm'"); con.execute("SET preserve_insertion_order=false")
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
    ncoh = int(round(0.20 * npool)); informed = al >= np.quantile(al, 0.80)

    cells = con.execute(f"""SELECT r.coin, r.h, r.fwd_resid, COALESCE(a.ofi,0) ofi
        FROM aresid r LEFT JOIN aagg a ON a.coin=r.coin AND a.h=r.h WHERE r.month >= {A.TEST_MONTH}""").fetchnumpy()
    ccoin = np.asarray(cells["coin"], dtype=object); ch = cells["h"].astype(np.int64)
    fr = cells["fwd_resid"].astype(float); ofi = cells["ofi"].astype(float)
    cellkey = {(str(c), int(h)): i for i, (c, h) in enumerate(zip(ccoin, ch))}
    ncell = len(fr); zy = A._zc(fr, ccoin); zo = A._zc(ofi, ccoin)
    zy_sn = A._zc(_sector_demean(fr, ccoin, ch), ccoin)
    days = (ch // 86400000).astype(np.int64)
    rows = con.execute(f"SELECT wb.wallet, wb.coin, wb.h, wb.flow FROM awb wb WHERE wb.mth >= {A.TEST_MONTH}").fetchnumpy()
    rc = np.asarray(rows["coin"], dtype=object); rh = rows["h"].astype(np.int64); rf = rows["flow"].astype(float)
    rw = np.asarray(rows["wallet"], dtype=object)
    cell_of = np.fromiter((cellkey.get((str(c), int(h)), -1) for c, h in zip(rc, rh)), np.int64, len(rf))
    wall_of = np.fromiter((widx.get(str(w), -1) for w in rw), np.int64, len(rf))
    keep = (cell_of >= 0) & (wall_of >= 0)
    cell_of, wall_of, rf = cell_of[keep], wall_of[keep], rf[keep]
    pos = rf > 0; neg = rf < 0
    _log(f"pool={npool:,} cells={ncell:,} rows={len(rf):,}")

    def net_sig(mask):
        sel = mask[wall_of]; return np.bincount(cell_of[sel], weights=rf[sel], minlength=ncell)
    def breadth_sig(mask):
        sel = mask[wall_of]
        npos = np.bincount(cell_of[sel & pos], minlength=ncell)
        nneg = np.bincount(cell_of[sel & neg], minlength=ncell)
        den = npos + nneg
        return np.where(den > 0, (npos - nneg) / np.maximum(den, 1), 0.0)
    def ic(sig, y): return A.partial_ic(y, A._zc(sig, ccoin), zo)

    rng = np.random.default_rng(SEED)
    def placebo(sigfn, y, k=K):
        inf_ic = ic(sigfn(informed), y); null = np.empty(k)
        for i in range(k):
            m = np.zeros(npool, bool); m[rng.choice(npool, ncoh, replace=False)] = True
            null[i] = ic(sigfn(m), y)
        mu, sd = null.mean(), null.std(ddof=1)
        return inf_ic, mu, sd, (inf_ic-mu)/sd, (1+np.sum(null>=inf_ic))/(k+1)

    print("\n=== (1) REPRODUCE @ pre-registered Q=0.20 (partial IC|OFI, TEST) ===")
    for name, fn in [("net-notional", net_sig), ("consensus-breadth", breadth_sig)]:
        i0, mu, sd, z, p = placebo(fn, zy)
        print(f"  {name:18s}: informed {i0:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}")

    print("\n=== (2) PER-COIN breadth-consistency (informed breadth-IC beats random, per coin) ===")
    bmask_sig = breadth_sig(informed)
    # per-coin: informed breadth IC vs a small per-coin random null
    NR = 120; rng2 = np.random.default_rng(SEED+7)
    randsigs = []
    for _ in range(NR):
        m = np.zeros(npool, bool); m[rng2.choice(npool, ncoh, replace=False)] = True
        randsigs.append(breadth_sig(m))
    beats = 0; npos_coin = 0; ncoins = 0
    for c in np.unique(ccoin):
        cm = ccoin == c
        if np.isfinite(fr[cm]).sum() < 30: continue
        ncoins += 1
        yi = A._zc(fr[cm], ccoin[cm]); oi = zo[cm]
        ii = A.partial_ic(yi, A._zc(bmask_sig[cm], ccoin[cm]), oi)
        rr = [A.partial_ic(yi, A._zc(rs[cm], ccoin[cm]), oi) for rs in randsigs]
        rr = np.array([x for x in rr if np.isfinite(x)])
        if np.isfinite(ii):
            if ii > 0: npos_coin += 1
            if len(rr) and ii > np.median(rr): beats += 1
    from math import comb
    p_sign = sum(comb(ncoins, i) for i in range(beats, ncoins+1))/2**ncoins
    print(f"  coins used: {ncoins};  informed breadth-IC>0: {npos_coin}/{ncoins};  "
          f"informed>random(median): {beats}/{ncoins}  sign-test p={p_sign:.4f}")

    print("\n=== (3) SECTOR-HERDING confound: sector×hour-demeaned residual (F4 control) ===")
    for name, fn in [("net-notional", net_sig), ("consensus-breadth", breadth_sig)]:
        i0, mu, sd, z, p = placebo(fn, zy_sn)
        print(f"  {name:18s}: informed {i0:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}")

    print("\n=== (4) DAY-BLOCK bootstrap CI on breadth IC (informed) ===")
    bsig = breadth_sig(informed)
    ud = np.unique(days); idx = {d: np.nonzero(days == d)[0] for d in ud}
    rng3 = np.random.default_rng(SEED+3); st = []
    for _ in range(2000):
        pick = rng3.integers(0, len(ud), size=len(ud))
        sel = np.concatenate([idx[ud[p]] for p in pick])
        st.append(A.partial_ic(A._zc(fr[sel], ccoin[sel]), A._zc(bsig[sel], ccoin[sel]), zo[sel]))
    st = np.array([v for v in st if np.isfinite(v)]); lo, hi = np.percentile(st, [2.5, 97.5])
    print(f"  breadth partial IC|OFI day-block 95% CI = [{lo:+.4f}, {hi:+.4f}]  (excludes 0: {lo>0})")


if __name__ == "__main__":
    main()
