"""
REALIZABLE + HARDENED version of the conditional-copy lead. Fix the look-ahead: consensus counts only
cohort entries in the TRAILING (t-30min, t) window (what you'd actually know in real time). Dip-depth
(preceding-1h) is already realizable. Fit the filter thresholds on TRAIN, apply OOS on TEST. Report the
filtered subset's net (drift - cost) at 4/6/8h to guard against horizon cherry-pick.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0,"src")
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT=Path("out"); COINS=["BTC","ETH","SOL","HYPE"]; BP=1e4
def _ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
TRAIN_HI=_ms(2026,2,1); TEST_LO=_ms(2026,3,1); WIN=30*60_000
HZ={"4h":4*3_600_000,"6h":6*3_600_000,"8h":8*3_600_000}


def fwd(L,t,h):
    e=_next_bar_close_vec(L,t); x=_next_bar_close_vec(L,t+h)
    with np.errstate(all="ignore"): r=x/e-1.0
    r[~(np.isfinite(e)&(e>0)&np.isfinite(x)&(x>0))]=np.nan
    return r


def load(lo,hi,cohort,lk):
    MK={k:[] for k in HZ};CONS=[];DIP=[];CST=[]
    for c in COINS:
        L=lk[c];bt=L[0].astype(np.int64);cl=L[1]
        q=pl.scan_parquet(OUT/"entries"/"part_*.parquet").filter((pl.col("coin")==c)&pl.col("wallet").is_in(cohort))
        if hi:q=q.filter(pl.col("b_ts")<hi)
        if lo:q=q.filter(pl.col("b_ts")>=lo)
        ec=q.select("b_ts","dir").sort("b_ts").collect()
        b=ec["b_ts"].to_numpy();d=ec["dir"].to_numpy().astype(float)
        for k,h in HZ.items(): MK[k].append(d*fwd(L,b,h)*BP)
        i=np.clip(np.searchsorted(bt,b),0,bt.size-1);j=np.clip(i-12,0,bt.size-1)
        with np.errstate(all="ignore"): DIP.append(d*(cl[i]/cl[j]-1.0)*BP)
        cons=np.zeros(b.size)                                  # TRAILING-ONLY same-dir count in (t-WIN, t)
        for sgn in (1.0,-1.0):
            idx=np.where(d==sgn)[0];tb=b[idx]
            pos=np.arange(idx.size)
            cons[idx]=(pos - np.searchsorted(tb,tb-WIN)).astype(float)   # earlier same-dir entries within WIN
        CONS.append(cons);CST.append(np.full(b.size,COST_BPS[c]))
    return ({k:np.concatenate(v) for k,v in MK.items()},np.concatenate(CONS),np.concatenate(DIP),np.concatenate(CST))


def netstats(mask,mk,cost,lab):
    out=[]
    for k in HZ:
        d=mk[k][mask];d=d[np.isfinite(d)];c=cost[mask].mean()
        out.append(f"{k}:{d.mean()-c:+5.1f}")
    n=int(mask.sum())
    print(f"  {lab:34s} n={n:6d} ({100*n/mask.size:2.0f}%)  net(drift-cost) {'  '.join(out)}")


def main():
    cohort=set(Path("out/cohort_wallets.txt").read_text().split("\n"));lk=_load_bars()
    mkT,consT,dipT,cstT=load(None,TRAIN_HI,cohort,lk)
    mkE,consE,dipE,cstE=load(TEST_LO,None,cohort,lk)
    print(f"train n={consT.size:,}  test n={consE.size:,}  cost~{cstE.mean():.1f}\n")
    # fit thresholds on TRAIN by maximizing 6h net; simple 1-D scans
    def best_thr(key,mk,cost,side):
        cand=np.quantile(key[np.isfinite(key)],np.linspace(0.5,0.95,10))
        b=None
        for t in cand:
            m=(key>=t) if side=="hi" else (key<=t)
            d=mk["6h"][m];d=d[np.isfinite(d)]
            if d.size<200:continue
            net=d.mean()-cost[m].mean()
            if b is None or net>b[0]:b=(net,t)
        return b[1]
    tc=best_thr(consT,mkT,cstT,"hi"); td=best_thr(dipT,mkT,cstT,"lo")
    print(f"TRAIN-fit: consensus>= {tc:.1f} trailing wallets/30min ; dip<= {td:+.1f}bp (deep-dip buys)\n")
    print("=== TEST (OOS) ===")
    netstats(np.ones(consE.size,bool),mkE,cstE,"ALL entries (copy everything)")
    netstats(consE>=tc,mkE,cstE,f"CONSENSUS>= {tc:.0f} (trailing, realizable)")
    netstats(dipE<=td,mkE,cstE,f"DEEP-DIP<= {td:+.0f}bp")
    netstats((consE>=tc)&(dipE<=td),mkE,cstE,"CONSENSUS & DEEP-DIP")
    # permutation-ish sanity: net of a RANDOM same-size subset (should be ~ALL)
    rng=np.random.default_rng(0);k=int((consE>=tc).sum())
    r=rng.choice(consE.size,k,replace=False);m=np.zeros(consE.size,bool);m[r]=True
    netstats(m,mkE,cstE,"(random same-size subset)")


if __name__=="__main__":
    main()
