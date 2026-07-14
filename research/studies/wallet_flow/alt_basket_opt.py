"""alt_basket_opt — cost-optimized alt-complex timing book: does a TIGHT-spread basket + LOW turnover clear cost?

alt_basket_backtest: gross Sharpe +5.25 (CI excl 0) but NET negative — top-12-ADV basket half-spread 4.49 bp >
break-even 2.2-3.8, because sign(tilt) flips ~hourly (turnover 0.83) yet the signal persists ~8h → we over-trade a
wide-spread basket. Two levers: (1) TIGHT basket (drop wide-spread names), (2) hysteresis/smoothing to cut turnover
(raise break-even). If break-even clears the tight half-spread at maker(0)/top-tier(2.4)/base(4.5) fee → deployable.

    .venv/bin/python -m research.studies.wallet_flow.alt_basket_opt
"""
from __future__ import annotations
import functools, time, warnings
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
Wb, MINOBS = 720, 240; ANN = np.sqrt(24*365)
HS_MAX = 3.0        # only trade names with impact half-spread ≤ this (bp)
NMAX = 12


def _spear(a,b):
    m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<30: return np.nan
    ra=np.argsort(np.argsort(a[m])).astype(float); rb=np.argsort(np.argsort(b[m])).astype(float)
    ra-=ra.mean(); rb-=rb.mean(); d=np.sqrt((ra@ra)*(rb@rb)); return (ra@rb)/d if d>0 else np.nan


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_bo'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con,A.UNIV_FORMATION,include_majors=False); coins=list(A.FACTORS)+alts
    panel=A.build_resid(con,coins); A.build_cohort_tables(con,coins); A.register_resid(con,panel)
    hours,ci,N=panel["hours"],panel["ci"],panel["N"]; hmin=int(hours[0])
    hsr=con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(impact_bid_px+impact_ask_px,0)*2*1e4) hs
        FROM asset_ctx WHERE coin IN ('{"','".join(alts)}') AND impact_bid_px>0 AND impact_ask_px>0
          AND day>={A.UNIV_FORMATION} GROUP BY coin""").fetchall()
    hsm={r[0]:float(r[1]) for r in hsr}
    basket=[c for c in alts if hsm.get(c,99)<=HS_MAX][:NMAX]     # tight AND liquid (alts already ADV-ranked)
    hs_bp=float(np.mean([hsm[c] for c in basket]))
    print(f"TIGHT basket (hs≤{HS_MAX}bp, top {len(basket)}): {basket}")
    print(f"  avg half-spread {hs_bp:.2f} bp | per-coin: "+", ".join(f"{c}:{hsm[c]:.1f}" for c in basket))

    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbo AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbo").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    bask=np.nanmean(R[:,[ci[c] for c in basket]],axis=1)
    bn=bask-rolling_beta(bask,btc,Wb,MINOBS)*btc; bn=bn-rolling_beta(bn,eth_o,Wb,MINOBS)*eth_o
    fwd=np.roll(bn,-1); fwd[-1]=np.nan

    fth=int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0]); emb=fth-A.H*3600000
    q=con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM awb wb
        JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h WHERE wb.mth<{A.TEST_MONTH} AND wb.h<{emb}
        AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*)>={A.MIN_TRAIN_BKT}""").fetchnumpy()
    pool=np.asarray([str(x) for x in q["wallet"]],dtype=object); al=q["al"].astype(float)
    cohort=set(pool[al>=np.quantile(al,0.80)].tolist())
    rows=con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.flow<>0 AND wb.mth>={A.TEST_MONTH}").fetchnumpy()
    rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64); rf=rows["flow"].astype(float)
    ho=((rh-hmin)//3600000).astype(int); inm=np.fromiter((w in cohort for w in rw),bool,len(rw))
    keep=inm&(ho>=0)&(ho<N); ho,rf=ho[keep],rf[keep]
    npos=np.bincount(ho[rf>0],minlength=N).astype(float); nneg=np.bincount(ho[rf<0],minlength=N).astype(float)
    den=npos+nneg; tilt=np.where(den>0,(npos-nneg)/np.maximum(den,1),np.nan)
    testh=np.zeros(N,bool); testh[np.unique(ho)]=True; tilt[~testh]=np.nan
    print(f"\nSANITY tilt→next-hr TIGHT-basket neutral return IC = {_spear(tilt,fwd):+.4f}\n")

    def smooth(S):
        if S<=1: return tilt.copy()
        o=np.array([np.nanmean(tilt[max(0,h-S+1):h+1]) for h in range(N)]); o[~testh]=np.nan; return o
    def hyst(sig,b):
        p=np.zeros(N); cur=0.0
        for h in range(N):
            s=sig[h]
            if np.isfinite(s):
                if s>b: cur=1.0
                elif s<-b: cur=-1.0
            p[h]=cur
        return p

    print(f"config                     | turn/hr | b-even bp | grossSR | net@0 | net@2.4 | net@4.5  (basket hs={hs_bp:.2f})")
    m=np.isfinite(fwd)&testh
    for S in (1,4,8):
        for b in (0.0,0.15,0.3):
            pos=hyst(smooth(S),b); p=np.where(m,pos,0.0); r=np.where(m,fwd,0.0); gross=p*r
            dp=np.abs(np.diff(p,prepend=0.0)); turn=dp[m].mean()
            gsr=gross[m].mean()/gross[m].std()*ANN if gross[m].std()>0 else np.nan
            be=gross[m].mean()/turn*1e4 if turn>0 else np.nan
            def nsr(fee):
                nt=gross-dp*(hs_bp+fee)/1e4; return nt[m].mean()/nt[m].std()*ANN if nt[m].std()>0 else np.nan
            print(f"  smooth={S:>2} deadband={b:.2f}     | {turn:6.3f}  | {be:+7.2f}  | {gsr:+6.2f}  |"
                  f"{nsr(0.0):+6.2f} |{nsr(2.4):+7.2f} |{nsr(4.5):+7.2f}")


if __name__=="__main__":
    main()
