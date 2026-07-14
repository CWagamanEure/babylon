"""alt_mt_timingrank — isolate the wallets that carry the TIMING signal (user's idea, correct ranking).

Concentrating by CROSS-SECTIONAL alignment killed the timing signal (breadth phenomenon). But that's the wrong
skill — rank wallets instead by TIMING alignment: on TRAIN, does the wallet's hourly directional lean align with
the forward BTC/ETH-neutral alt-INDEX move? Then test whether a POLLABLE top-N by THIS score carries it OOS.
Selection on TRAIN, evaluation on TEST (guards winner's-curse); placebo vs random same-size.

    .venv/bin/python -m research.studies.wallet_flow.alt_mt_timingrank
"""
from __future__ import annotations
import functools, warnings
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
HS=(1,4,8); NS=(150,300,600,1500,4000); K=400; SEED=20260710; Wb,MINOBS=720,240; MINH=20


def _spear(a,b):
    m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<30: return np.nan
    ra=np.argsort(np.argsort(a[m])).astype(float); rb=np.argsort(np.argsort(b[m])).astype(float)
    ra-=ra.mean(); rb-=rb.mean(); d=np.sqrt((ra@ra)*(rb@rb)); return (ra@rb)/d if d>0 else np.nan


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_tr'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con,A.UNIV_FORMATION,include_majors=False); coins=list(A.FACTORS)+alts
    panel=A.build_resid(con,coins); A.build_cohort_tables(con,coins); A.register_resid(con,panel)
    hours,ci,N=panel["hours"],panel["ci"],panel["N"]; hmin=int(hours[0])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbt AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbt").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    idx=np.nanmean(R[:,[ci[c] for c in alts]],axis=1)
    idx=idx-rolling_beta(idx,btc,Wb,MINOBS)*btc; idx=idx-rolling_beta(idx,eth_o,Wb,MINOBS)*eth_o
    cs=np.where(np.isfinite(idx),idx,0.0)
    fwH={H:np.array([cs[h+1:h+1+H].sum() if h<N-H else np.nan for h in range(N)]) for H in HS}
    fth=int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0])

    # per-wallet TRAIN timing score = avg over active TRAIN hours of sign(net alt flow)·fwd1 alt-index return
    fwd1=fwH[1]; hh=hours.astype(np.int64)
    fin=np.isfinite(fwd1)&(hh<fth)                     # TRAIN hours with a defined forward
    con.register("fwdtr_src",{"hms":hh[fin].astype(np.int64),"fwd":fwd1[fin].astype(float)})
    con.execute("CREATE OR REPLACE TEMP TABLE fwdtr AS SELECT * FROM fwdtr_src"); con.unregister("fwdtr_src")
    sc=con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb WHERE mth<{A.TEST_MONTH} GROUP BY wallet,h)
        SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score, count(*) nh
        FROM wh JOIN fwdtr f ON wh.h=f.hms WHERE wh.nf<>0
        GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
    wal=np.asarray([str(x) for x in sc["wallet"]],dtype=object); score=sc["score"].astype(float)
    order=np.argsort(-score); widx={w:i for i,w in enumerate(wal)}
    print(f"timing-scored wallet pool (≥{MINH} TRAIN hrs) = {len(wal):,}")

    rows=con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.flow<>0 AND wb.mth>={A.TEST_MONTH}").fetchnumpy()
    rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64); rf=rows["flow"].astype(float)
    ho=((rh-hmin)//3600000).astype(int); wo=np.fromiter((widx.get(w,-1) for w in rw),np.int64,len(rw))
    keep=(wo>=0)&(ho>=0)&(ho<N); ho,rf,wo=ho[keep],rf[keep],wo[keep]; pos,neg=rf>0,rf<0
    testh=np.zeros(N,bool); testh[np.unique(ho)]=True
    def tilt(mask):
        sel=mask[wo]; np_=np.bincount(ho[sel&pos],minlength=N).astype(float); nn=np.bincount(ho[sel&neg],minlength=N).astype(float)
        den=np_+nn; t=np.where(den>0,(np_-nn)/np.maximum(den,1),np.nan); t[~testh]=np.nan; return t

    rng=np.random.default_rng(SEED)
    print("\nTOP-N by TRAIN TIMING score → forward NEUTRAL alt-index (OOS TEST; informed vs random same-size):")
    for n in NS:
        if n>len(wal): continue
        m=np.zeros(len(wal),bool); m[order[:n]]=True; it=tilt(m); line=f"  top-{n:>5}: "
        for H in HS:
            fw=fwH[H]; ici=_spear(it,fw); null=np.empty(K)
            for k in range(K):
                mm=np.zeros(len(wal),bool); mm[rng.choice(len(wal),n,replace=False)]=True; null[k]=_spear(tilt(mm),fw)
            mu,sd=np.nanmean(null),np.nanstd(null); z=(ici-mu)/sd if sd>0 else np.nan
            line+=f"H{H} IC{ici:+.3f} z{z:+.1f}  "
        print(line)


if __name__=="__main__":
    main()
