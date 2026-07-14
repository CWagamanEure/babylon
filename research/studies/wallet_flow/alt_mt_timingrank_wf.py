"""alt_mt_timingrank_wf — walk-forward the TIMING-RANKED cohort (kills the size-argmax / winner's-curse worry).

alt_mt_timingrank: top-N by TRAIN timing score carries the alt-complex signal OOS (top-150 z=5, top-300 z~2). But
that ranked once on all TRAIN. Proper test: for EACH test month, re-rank wallets by timing score on data BEFORE that
month (expanding), take top-N, evaluate that month vs random same-size. If top-300 stays positive fold-by-fold, the
cohort is stable enough to poll + monthly-refresh live.

    .venv/bin/python -m research.studies.wallet_flow.alt_mt_timingrank_wf
"""
from __future__ import annotations
import functools, warnings
import numpy as np
from math import comb
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
HS=(1,4,8); NS=(150,300); FOLDS=(202603,202604,202605,202606); K=300; SEED=20260710; Wb,MINOBS=720,240; MINH=20


def _spear(a,b):
    m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<30: return np.nan
    ra=np.argsort(np.argsort(a[m])).astype(float); rb=np.argsort(np.argsort(b[m])).astype(float)
    ra-=ra.mean(); rb-=rb.mean(); d=np.sqrt((ra@ra)*(rb@rb)); return (ra@rb)/d if d>0 else np.nan


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_trw'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con,A.UNIV_FORMATION,include_majors=False); coins=list(A.FACTORS)+alts
    panel=A.build_resid(con,coins); A.build_cohort_tables(con,coins); A.register_resid(con,panel)
    hours,ci,N=panel["hours"],panel["ci"],panel["N"]; hmin=int(hours[0]); hh=hours.astype(np.int64)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbw AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbw").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    idx=np.nanmean(R[:,[ci[c] for c in alts]],axis=1)
    idx=idx-rolling_beta(idx,btc,Wb,MINOBS)*btc; idx=idx-rolling_beta(idx,eth_o,Wb,MINOBS)*eth_o
    cs=np.where(np.isfinite(idx),idx,0.0)
    fwH={H:np.array([cs[h+1:h+1+H].sum() if h<N-H else np.nan for h in range(N)]) for H in HS}
    fwd1=fwH[1]

    def score_before(m):
        fm=int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={m}").fetchone()[0])
        fin=np.isfinite(fwd1)&(hh<fm)
        con.register("fsrc",{"hms":hh[fin].astype(np.int64),"fwd":fwd1[fin].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
        sc=con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb WHERE mth<{m} GROUP BY wallet,h)
            SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
            WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
        return np.asarray([str(x) for x in sc["wallet"]],dtype=object), sc["score"].astype(float)

    def fold_tilt_arrays(m):
        rows=con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.flow<>0 AND wb.mth={m}").fetchnumpy()
        rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64); rf=rows["flow"].astype(float)
        ho=((rh-hmin)//3600000).astype(int); keep=(ho>=0)&(ho<N)
        return rw[keep], ho[keep], rf[keep]

    rng=np.random.default_rng(SEED)
    results={n:{H:[] for H in HS} for n in NS}
    for m in FOLDS:
        wal,score=score_before(m); order=np.argsort(-score); widx={w:i for i,w in enumerate(wal)}
        rw,ho,rf=fold_tilt_arrays(m)
        wo=np.fromiter((widx.get(w,-1) for w in rw),np.int64,len(rw)); k=wo>=0; ho2,rf2,wo2=ho[k],rf[k],wo[k]
        pos,neg=rf2>0,rf2<0; testh=np.zeros(N,bool); testh[np.unique(ho2)]=True
        def tilt(mask):
            sel=mask[wo2]; np_=np.bincount(ho2[sel&pos],minlength=N).astype(float); nn=np.bincount(ho2[sel&neg],minlength=N).astype(float)
            den=np_+nn; t=np.where(den>0,(np_-nn)/np.maximum(den,1),np.nan); t[~testh]=np.nan; return t
        for n in NS:
            mm=np.zeros(len(wal),bool); mm[order[:n]]=True; it=tilt(mm)
            for H in HS:
                fw=fwH[H]; ici=_spear(it,fw); null=np.empty(K)
                for j in range(K):
                    rmask=np.zeros(len(wal),bool); rmask[rng.choice(len(wal),n,replace=False)]=True; null[j]=_spear(tilt(rmask),fw)
                z=(ici-np.nanmean(null))/np.nanstd(null); results[n][H].append((m,ici,z))
        print(f"fold {m}: scored pool={len(wal):,}  "+"  ".join(
            f"top{n} H1 z{results[n][1][-1][2]:+.1f}" for n in NS))
    print("\n=== WALK-FORWARD timing-ranked cohort (re-ranked per fold), informed vs random ===")
    for n in NS:
        for H in HS:
            zs=np.array([z for _,_,z in results[n][H]]); npos=int((zs>0).sum())
            ps=sum(comb(4,i) for i in range(npos,5))/16
            print(f"  top-{n:>4} H{H}: per-fold z "+" ".join(f"{z:+.1f}" for z in zs)
                  +f" | {npos}/4 pos, sign-p={ps:.3f}, mean z={zs.mean():+.2f}")


if __name__=="__main__":
    main()
