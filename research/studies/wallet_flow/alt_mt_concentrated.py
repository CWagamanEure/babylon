"""alt_mt_concentrated — does the alt-complex TIMING signal survive on a POLLABLE cohort (top-N wallets)?

Live deployment can't poll 13,229 wallets hourly (HL REST weight budget → hours per sweep). A deployable version
needs a concentrated cohort of a few hundred MOST-informed wallets that we CAN poll each hour. Question: does the
tilt→forward-neutral-alt-index signal (full-cohort z≈4) hold when we keep only the top-N by TRAIN alignment?
Test N ∈ {150,300,600,1323(top-2%),13229(prod)} at H∈{1,4,8}, placebo vs random same-size cohorts.

    .venv/bin/python -m research.studies.wallet_flow.alt_mt_concentrated
"""
from __future__ import annotations
import functools, warnings
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
HS=(1,4,8); NS=(150,300,600,1323); K=400; SEED=20260710; Wb,MINOBS=720,240


def _spear(a,b):
    m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<30: return np.nan
    ra=np.argsort(np.argsort(a[m])).astype(float); rb=np.argsort(np.argsort(b[m])).astype(float)
    ra-=ra.mean(); rb-=rb.mean(); d=np.sqrt((ra@ra)*(rb@rb)); return (ra@rb)/d if d>0 else np.nan


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_cc'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con,A.UNIV_FORMATION,include_majors=False); coins=list(A.FACTORS)+alts
    panel=A.build_resid(con,coins); A.build_cohort_tables(con,coins); A.register_resid(con,panel)
    hours,ci,N=panel["hours"],panel["ci"],panel["N"]; hmin=int(hours[0])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbc AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbc").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    idx=np.nanmean(R[:,[ci[c] for c in alts]],axis=1)
    idx=idx-rolling_beta(idx,btc,Wb,MINOBS)*btc; idx=idx-rolling_beta(idx,eth_o,Wb,MINOBS)*eth_o
    cs=np.where(np.isfinite(idx),idx,0.0)
    fwH={H:np.array([cs[h+1:h+1+H].sum() if h<N-H else np.nan for h in range(N)]) for H in HS}

    fth=int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0]); emb=fth-A.H*3600000
    q=con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM awb wb
        JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h WHERE wb.mth<{A.TEST_MONTH} AND wb.h<{emb}
        AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*)>={A.MIN_TRAIN_BKT}""").fetchnumpy()
    pool=np.asarray([str(x) for x in q["wallet"]],dtype=object); al=q["al"].astype(float)
    order=np.argsort(-al)                                   # most-aligned first
    widx={w:i for i,w in enumerate(pool)}
    rows=con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.flow<>0 AND wb.mth>={A.TEST_MONTH}").fetchnumpy()
    rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64); rf=rows["flow"].astype(float)
    ho=((rh-hmin)//3600000).astype(int); wo=np.fromiter((widx.get(w,-1) for w in rw),np.int64,len(rw))
    keep=(wo>=0)&(ho>=0)&(ho<N); ho,rf,wo=ho[keep],rf[keep],wo[keep]; pos,neg=rf>0,rf<0
    testh=np.zeros(N,bool); testh[np.unique(ho)]=True

    def tilt(mask):
        sel=mask[wo]
        np_=np.bincount(ho[sel&pos],minlength=N).astype(float); nn=np.bincount(ho[sel&neg],minlength=N).astype(float)
        den=np_+nn; t=np.where(den>0,(np_-nn)/np.maximum(den,1),np.nan); t[~testh]=np.nan; return t

    rng=np.random.default_rng(SEED)
    print(f"pool={len(pool):,}\n\nTOP-N cohort → forward NEUTRAL alt-index timing (informed vs random same-size):")
    for n in NS:
        m=np.zeros(len(pool),bool); m[order[:n]]=True; it=tilt(m)
        line=f"  top-{n:>5}: "
        for H in HS:
            fw=fwH[H]; ici=_spear(it,fw)
            null=np.empty(K)
            for k in range(K):
                mm=np.zeros(len(pool),bool); mm[rng.choice(len(pool),n,replace=False)]=True
                null[k]=_spear(tilt(mm),fw)
            mu,sd=np.nanmean(null),np.nanstd(null); z=(ici-mu)/sd if sd>0 else np.nan
            line+=f"H{H} IC {ici:+.3f} z{z:+.1f}   "
        print(line)


if __name__=="__main__":
    main()
