"""alt_basket_backtest — the deployability test for the alt-complex TIMING signal (Result 9).

Signal (informed cohort aggregate directional tilt across all alts, per hour) clears placebo z≈4 predicting the
BTC/ETH-neutralized alt-index return, momentum-independent. But the index was equal-weight-all-45 (microcap-tilted).
Deployability question: trade a LIQUID basket — top-N alts by TRAIN ADV, hedged vs BTC/ETH — timed by the tilt, and
measure GROSS/NET Sharpe with REAL per-name cost (asset_ctx impact half-spread + fee). Does it clear cost?

  position(h) = sign(tilt(h)) [and continuous tilt]; held 1h (also a smoothed lower-turnover variant).
  PnL(h) = position(h) · neutralized-basket-return(h→h+1);  cost(h) = |Δposition| · (half_spread + fee).
  Report: IC sanity, gross ann Sharpe, turnover, break-even bp/side, net @ fee∈{4.5,2.4,0}, per-month, day-block CI.

    .venv/bin/python -m research.studies.wallet_flow.alt_basket_backtest
"""
from __future__ import annotations
import functools, time, warnings
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0=time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")
Wb, MINOBS = 720, 240
NBASK = 12                    # top-N liquid alts to trade
ANN = np.sqrt(24*365)         # hourly → annual


def _spear(a, b):
    m=np.isfinite(a)&np.isfinite(b)
    if m.sum()<30: return np.nan
    ra=np.argsort(np.argsort(a[m])).astype(float); rb=np.argsort(np.argsort(b[m])).astype(float)
    ra-=ra.mean(); rb-=rb.mean(); d=np.sqrt((ra@ra)*(rb@rb)); return (ra@rb)/d if d>0 else np.nan


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_bk'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con, A.UNIV_FORMATION, include_majors=False)     # ranked by TRAIN ADV desc
    basket=alts[:NBASK]; coins=list(A.FACTORS)+alts
    print(f"liquid basket (top {NBASK} by TRAIN ADV): {basket}")
    panel=A.build_resid(con, coins); A.build_cohort_tables(con, coins); A.register_resid(con, panel)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin=int(hours[0])
    # returns matrix
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbk AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbk").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    bask=np.nanmean(R[:,[ci[c] for c in basket]],axis=1)             # equal-weight liquid basket return
    bask_n=bask-rolling_beta(bask,btc,Wb,MINOBS)*btc; bask_n=bask_n-rolling_beta(bask_n,eth_o,Wb,MINOBS)*eth_o
    # per-coin impact half-spread (bp) for the basket, from asset_ctx
    hs=con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(impact_bid_px+impact_ask_px,0)*2*1e4) hs
        FROM asset_ctx WHERE coin IN ('{"','".join(basket)}') AND impact_bid_px>0 AND impact_ask_px>0
          AND day>= {A.UNIV_FORMATION} GROUP BY coin""").fetchall()
    hsm={r[0]:float(r[1]) for r in hs}; hs_bp=float(np.mean([hsm[c] for c in basket if c in hsm]))
    print(f"basket per-side half-spread ≈ {hs_bp:.2f} bp (median impact, TEST); per-coin: "
          + ", ".join(f"{c}:{hsm.get(c,float('nan')):.1f}" for c in basket))

    # frozen cohort tilt across ALL alts (the signal), full TEST
    fth=int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={A.TEST_MONTH}").fetchone()[0]); emb=fth-A.H*3600000
    q=con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM awb wb
        JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h WHERE wb.mth<{A.TEST_MONTH} AND wb.h<{emb}
        AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*)>={A.MIN_TRAIN_BKT}""").fetchnumpy()
    pool=np.asarray([str(x) for x in q["wallet"]],dtype=object); al=q["al"].astype(float)
    cohort=set(pool[al>=np.quantile(al,0.80)].tolist())
    rows=con.execute(f"SELECT wb.wallet,wb.h,wb.flow FROM awb wb WHERE wb.flow<>0 AND wb.mth>={A.TEST_MONTH}").fetchnumpy()
    rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64); rf=rows["flow"].astype(float)
    ho=((rh-hmin)//3600000).astype(int); inmask=np.fromiter((w in cohort for w in rw),bool,len(rw))
    keep=inmask&(ho>=0)&(ho<N); ho,rf=ho[keep],rf[keep]
    npos=np.bincount(ho[rf>0],minlength=N).astype(float); nneg=np.bincount(ho[rf<0],minlength=N).astype(float)
    den=npos+nneg; tilt=np.where(den>0,(npos-nneg)/np.maximum(den,1),np.nan)
    testh=np.zeros(N,bool); testh[np.unique(ho)]=True; tilt[~testh]=np.nan
    _log(f"cohort={len(cohort):,} test hours={testh.sum()}")

    fwd=np.roll(bask_n,-1); fwd[-1]=np.nan                          # basket return over the NEXT hour
    ic=_spear(tilt,fwd)
    print(f"\nSANITY: tilt(h) → next-hour LIQUID-basket neutralized return  IC = {ic:+.4f}")

    months=np.array([int(__import__('datetime').datetime.utcfromtimestamp(int(x)/1000).strftime('%Y%m')) for x in hours])
    days=(hours//86400000).astype(np.int64)

    def backtest(pos, label):
        m=np.isfinite(pos)&np.isfinite(fwd)
        p=np.where(m,pos,0.0); r=np.where(m,fwd,0.0)
        gross=p*r
        dpos=np.abs(np.diff(p,prepend=0.0))
        turn=dpos[m].mean()
        gsr=gross[m].mean()/gross[m].std()*ANN if gross[m].std()>0 else np.nan
        # break-even cost per side (bp): gross mean / turnover, in bp
        be=gross[m].mean()/turn*1e4 if turn>0 else np.nan
        def net_sr(fee):
            cost=dpos*(hs_bp+fee)/1e4; net=gross-cost
            return net[m].mean()/net[m].std()*ANN if net[m].std()>0 else np.nan
        print(f"\n-- {label} --")
        print(f"  gross ann Sharpe {gsr:+.2f} | turnover/hr {turn:.3f} | break-even {be:+.2f} bp/side | "
              f"gross mean {gross[m].mean()*1e4:+.3f} bp/hr")
        print(f"  net Sharpe: @hs+4.5bp {net_sr(4.5):+.2f} | @hs+2.4bp {net_sr(2.4):+.2f} | @hs+0(maker-fee) {net_sr(0.0):+.2f}")
        for mo in (202603,202604,202605,202606):
            mm=m&(months==mo); print(f"    {mo}: gross {gross[mm].mean()*1e4:+.3f} bp/hr (n={mm.sum()})", end="")
        print()
        # day-block bootstrap gross Sharpe CI
        ud=np.unique(days[m]); idx=[np.nonzero((days==dd)&m)[0] for dd in ud]; rng=np.random.default_rng(7); st=[]
        for _ in range(1000):
            s=np.concatenate([idx[i] for i in rng.integers(0,len(ud),len(ud))])
            st.append(gross[s].mean()/gross[s].std()*ANN if gross[s].std()>0 else np.nan)
        st=np.array([v for v in st if np.isfinite(v)]); lo,hi=np.percentile(st,[2.5,97.5])
        print(f"  gross Sharpe day-block 95% CI [{lo:+.2f},{hi:+.2f}] (excl 0: {lo>0})")

    backtest(np.sign(tilt), "sign(tilt), hourly rebalance")
    backtest(tilt, "continuous tilt, hourly rebalance")
    sm=np.array([np.nanmean(tilt[max(0,h-3):h+1]) for h in range(N)])   # 4h-smoothed (lower turnover)
    sm[~testh]=np.nan
    backtest(np.sign(sm), "sign(4h-smoothed tilt), hourly rebalance")


if __name__=="__main__":
    main()
