"""
Is there a SUBSET of the cohort's entries whose forward drift clears cost? Test two entry-time conditioners
(no look-ahead): (1) CONSENSUS = how many cohort wallets enter the same coin+direction within +/-30min;
(2) DIP-DEPTH = preceding-1h dir-signed return (contrarian => negative = bought a deeper dip).
Report mean 6h dir-signed markout (bp) by bucket vs the ~10bp round-trip cost. If a bucket clears cost,
a filtered/consensus copy has legs; harden train->test after.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, "src")
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT=Path("out"); COINS=["BTC","ETH","SOL","HYPE"]; BP=1e4
def _ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
TEST_LO=_ms(2026,3,1); H6=6*3_600_000; PRE=3_600_000; WIN=30*60_000


def fwd(L,t,h):
    e=_next_bar_close_vec(L,t); x=_next_bar_close_vec(L,t+h)
    with np.errstate(all="ignore"): r=x/e-1.0
    r[~(np.isfinite(e)&(e>0)&np.isfinite(x)&(x>0))]=np.nan
    return r


def buckets(name, key, mk, cost, q=5):
    ok=np.isfinite(key)&np.isfinite(mk); key,mk,cost=key[ok],mk[ok],cost[ok]
    edges=np.quantile(key,np.linspace(0,1,q+1))
    print(f"\n{name}: mean 6h drift by bucket (low->high), vs cost")
    for i in range(q):
        lo,hi=edges[i],edges[i+1]
        m=(key>=lo)&(key<=hi) if i==q-1 else (key>=lo)&(key<hi)
        d=mk[m]; c=cost[m].mean()
        flag="  <-- clears cost!" if d.mean()>c else ""
        print(f"  Q{i+1} [{lo:+.2f},{hi:+.2f}]  n={m.sum():5d}  drift={d.mean():+6.1f}bp  cost={c:.1f}  net={d.mean()-c:+6.1f}{flag}")


def main():
    cohort=set(Path("out/cohort_wallets.txt").read_text().split("\n"))
    lk=_load_bars(); MK=[];CONS=[];DIP=[];CST=[]
    for c in COINS:
        L=lk[c]; bt=L[0].astype(np.int64); cl=L[1]
        ec=(pl.scan_parquet(OUT/"entries"/"part_*.parquet").filter((pl.col("coin")==c)&(pl.col("b_ts")>=TEST_LO))
            .filter(pl.col("wallet").is_in(cohort)).select("b_ts","dir").sort("b_ts").collect())
        b=ec["b_ts"].to_numpy(); d=ec["dir"].to_numpy().astype(float)
        mk=d*fwd(L,b,H6)*BP
        i=np.clip(np.searchsorted(bt,b),0,bt.size-1); j=np.clip(i-12,0,bt.size-1)
        with np.errstate(all="ignore"): dip=d*(cl[i]/cl[j]-1.0)*BP        # dir-signed preceding-1h
        # consensus: # same-dir cohort entries within +/-WIN (same coin)
        cons=np.zeros(b.size)
        for sgn in (1.0,-1.0):
            idx=np.where(d==sgn)[0]; tb=b[idx]
            lo=np.searchsorted(tb,tb-WIN); hi=np.searchsorted(tb,tb+WIN)
            cons[idx]=(hi-lo).astype(float)
        MK.append(mk);CONS.append(cons);DIP.append(dip);CST.append(np.full(b.size,COST_BPS[c]))
    mk=np.concatenate(MK);cons=np.concatenate(CONS);dip=np.concatenate(DIP);cost=np.concatenate(CST)
    print(f"cohort TEST entries: {np.isfinite(mk).sum():,}   overall mean 6h drift={np.nanmean(mk):+.1f}bp (cost~{cost.mean():.1f})")
    buckets("CONSENSUS (crowding)", cons, mk, cost)
    buckets("DIP-DEPTH (preceding 1h, signed)", dip, mk, cost)


if __name__=="__main__":
    main()
