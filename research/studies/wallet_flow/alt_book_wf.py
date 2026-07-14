"""alt_book_wf — walk-forward the alt-complex TIMING book: kill the config-argmax + in-sample objections.

alt_basket_opt found net-positive configs but they were argmax'd over a 9-cell sweep on TEST. Two clean tests:
  PART A — PRE-REGISTERED config (no argmax): smooth=8h/no-deadband, justified by the signal's IC peak at H=8h
    (established independently in alt_markettiming, NOT from returns); tight basket pre-registered by TRAIN
    liquidity. Report NET Sharpe PER TEST MONTH (202603-06) + pooled day-block CI, at fee ∈ {0,2.4,4.5}.
  PART B — TRUE 3-WAY SPLIT (kills config selection overfit): cohort frozen on months<202512; select (smooth,
    deadband) on VALIDATION 202512-202602 (OOS for the cohort) by net@2.4bp; apply UNCHANGED to TEST 202603-06.
Basket + half-spread pre-registered on TRAIN (day<UNIV_FORMATION) — no look-ahead.

    .venv/bin/python -m research.studies.wallet_flow.alt_book_wf
"""
from __future__ import annotations
import functools, time, warnings, datetime as dt
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0=time.time(); _log=lambda m: print(f"[{time.time()-_T0:6.1f}s] {m}")
Wb, MINOBS = 720, 240; ANN=np.sqrt(24*365); HS_MAX=3.0; NMAX=8
TESTM=(202603,202604,202605,202606); VALM=(202512,202601,202602)


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_wf'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con,A.UNIV_FORMATION,include_majors=False); coins=list(A.FACTORS)+alts
    panel=A.build_resid(con,coins); A.build_cohort_tables(con,coins); A.register_resid(con,panel)
    hours,ci,N=panel["hours"],panel["ci"],panel["N"]; hmin=int(hours[0])
    months=np.array([int(dt.datetime.utcfromtimestamp(int(x)/1000).strftime('%Y%m')) for x in hours])
    days=(hours//86400000).astype(np.int64)
    # basket + half-spread pre-registered on TRAIN (no look-ahead)
    hsr=con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(impact_bid_px+impact_ask_px,0)*2*1e4) hs
        FROM asset_ctx WHERE coin IN ('{"','".join(alts)}') AND impact_bid_px>0 AND impact_ask_px>0
          AND day<{A.UNIV_FORMATION} GROUP BY coin""").fetchall()
    hsm={r[0]:float(r[1]) for r in hsr}
    basket=[c for c in alts if hsm.get(c,99)<=HS_MAX][:NMAX]; hs_bp=float(np.mean([hsm[c] for c in basket]))
    print(f"PRE-REG basket (TRAIN hs≤{HS_MAX}, top {len(basket)}): {basket}  avg hs {hs_bp:.2f} bp")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbw AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbw").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    bk=np.nanmean(R[:,[ci[c] for c in basket]],axis=1)
    bn=bk-rolling_beta(bk,btc,Wb,MINOBS)*btc; bn=bn-rolling_beta(bn,eth_o,Wb,MINOBS)*eth_o
    fwd=np.roll(bn,-1); fwd[-1]=np.nan

    def cohort_tilt(cutoff_m):
        emb=int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={cutoff_m}").fetchone()[0])-A.H*3600000
        q=con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM awb wb
            JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h WHERE wb.mth<{cutoff_m} AND wb.h<{emb}
            AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
            SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*)>={A.MIN_TRAIN_BKT}""").fetchnumpy()
        pool=np.asarray([str(x) for x in q["wallet"]],dtype=object); al=q["al"].astype(float)
        cohort=set(pool[al>=np.quantile(al,0.80)].tolist())
        rows=con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.flow<>0 AND wb.mth>={cutoff_m}").fetchnumpy()
        rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64); rf=rows["flow"].astype(float)
        ho=((rh-hmin)//3600000).astype(int); inm=np.fromiter((w in cohort for w in rw),bool,len(rw))
        keep=inm&(ho>=0)&(ho<N); ho,rf=ho[keep],rf[keep]
        np_=np.bincount(ho[rf>0],minlength=N).astype(float); nn=np.bincount(ho[rf<0],minlength=N).astype(float)
        den=np_+nn; t=np.where(den>0,(np_-nn)/np.maximum(den,1),np.nan)
        th=np.zeros(N,bool); th[np.unique(ho)]=True; t[~th]=np.nan; return t,th

    def smooth(t,S,th):
        if S<=1: return t.copy()
        o=np.array([np.nanmean(t[max(0,h-S+1):h+1]) for h in range(N)]); o[~th]=np.nan; return o
    def hyst(sig,b):
        p=np.zeros(N); cur=0.0
        for h in range(N):
            s=sig[h]
            if np.isfinite(s):
                cur=1.0 if s>b else (-1.0 if s<-b else cur)
            p[h]=cur
        return p
    def netstats(pos,mmask,fee):
        m=mmask&np.isfinite(fwd); p=np.where(m,pos,0.0); r=np.where(m,fwd,0.0); gross=p*r
        dp=np.abs(np.diff(p,prepend=0.0)); net=gross-dp*(hs_bp+fee)/1e4
        sr=net[m].mean()/net[m].std()*ANN if net[m].std()>0 else np.nan
        return sr, net, m
    def dbCI(net,m):
        ud=np.unique(days[m]); idx=[np.nonzero((days==dd)&m)[0] for dd in ud]; rng=np.random.default_rng(7); st=[]
        for _ in range(800):
            s=np.concatenate([idx[i] for i in rng.integers(0,len(ud),len(ud))])
            st.append(net[s].mean()/net[s].std()*ANN if net[s].std()>0 else np.nan)
        st=np.array([v for v in st if np.isfinite(v)]); return np.percentile(st,[2.5,97.5])

    # ---------- PART A: pre-registered smooth=8/db=0, production cohort ----------
    print("\n=== PART A — PRE-REGISTERED config (smooth=8h, no deadband; justified by IC-peak@8h) ===")
    t,th=cohort_tilt(A.TEST_MONTH); pos=hyst(smooth(t,8,th),0.0)
    _log("part A tilt ready")
    for fee,tag in [(0.0,"maker-fee"),(2.4,"top-tier 2.4"),(4.5,"base 4.5")]:
        srs=[]
        for mo in TESTM:
            sr,_,_=netstats(pos,months==mo,fee); srs.append(sr)
        srP,netP,mP=netstats(pos,np.isin(months,TESTM),fee); lo,hi=dbCI(netP,mP)
        print(f"  fee@{tag:>12}: per-month netSR "+" ".join(f"{s:+.2f}" for s in srs)
              +f" | POOLED {srP:+.2f} CI[{lo:+.2f},{hi:+.2f}] excl0={lo>0}")

    # ---------- PART B: 3-way split (cohort<202512, select config on VAL, test OOS) ----------
    print("\n=== PART B — TRUE 3-WAY SPLIT (cohort<202512; config picked on VAL 202512-202602 @2.4bp; test OOS) ===")
    t2,th2=cohort_tilt(202512); _log("part B tilt ready")
    best=None
    for S in (1,4,8,12):
        for b in (0.0,0.15,0.3):
            pos2=hyst(smooth(t2,S,th2),b); sr,_,_=netstats(pos2,np.isin(months,VALM),2.4)
            if np.isfinite(sr) and (best is None or sr>best[0]): best=(sr,S,b)
    _,S,b=best; print(f"  VAL-selected config: smooth={S}, deadband={b:.2f} (val netSR@2.4={best[0]:+.2f})")
    pos2=hyst(smooth(t2,S,th2),b)
    for fee,tag in [(0.0,"maker-fee"),(2.4,"top-tier 2.4"),(4.5,"base 4.5")]:
        srs=[netstats(pos2,months==mo,fee)[0] for mo in TESTM]
        srP,netP,mP=netstats(pos2,np.isin(months,TESTM),fee); lo,hi=dbCI(netP,mP)
        print(f"  fee@{tag:>12}: per-month netSR "+" ".join(f"{s:+.2f}" for s in srs)
              +f" | POOLED {srP:+.2f} CI[{lo:+.2f},{hi:+.2f}] excl0={lo>0}")


if __name__=="__main__":
    main()
