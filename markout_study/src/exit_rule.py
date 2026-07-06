"""
The decisive test of "optimize their exits": a REALIZABLE take-profit + time-stop rule (NO look-ahead),
fit on TRAIN cohort entries, applied OOS on TEST. Walk each entry's dir-signed price path on a 14-step grid
to 12h; exit at the first step markout >= TP, else at the time-stop (last step). Net of round-trip cost.
Also a stop-loss variant. If the best train-fit rule can't clear cost OOS, exit-optimization is dead;
if it can, the user's hypothesis has legs.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, "src")
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT = Path("out"); COINS = ["BTC","ETH","SOL","HYPE"]; BP = 1e4
def _ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
TRAIN_HI=_ms(2026,2,1); TEST_LO=_ms(2026,3,1)
GRID = [15,30,45,60,90,120,150,180,240,300,360,480,600,720]      # minutes
GMS = [m*60_000 for m in GRID]


def fwd(L,t,h):
    e=_next_bar_close_vec(L,t); x=_next_bar_close_vec(L,t+h)
    with np.errstate(all="ignore"): r=x/e-1.0
    r[~(np.isfinite(e)&(e>0)&np.isfinite(x)&(x>0))]=np.nan
    return r


def build(split_lo, split_hi):
    cohort=set(Path("out/cohort_wallets.txt").read_text().split("\n"))
    lk=_load_bars(); mats=[]; costs=[]
    for c in COINS:
        L=lk[c]
        q=pl.scan_parquet(OUT/"entries"/"part_*.parquet").filter((pl.col("coin")==c)&pl.col("wallet").is_in(cohort))
        if split_hi: q=q.filter(pl.col("b_ts")<split_hi)
        if split_lo: q=q.filter(pl.col("b_ts")>=split_lo)
        ec=q.select("b_ts","dir").collect()
        b=ec["b_ts"].to_numpy(); d=ec["dir"].to_numpy().astype(float)
        A=np.column_stack([d*fwd(L,b,h) for h in GMS])*BP
        mats.append(A); costs.append(np.full(b.size,COST_BPS[c]))
    A=np.vstack(mats); cost=np.concatenate(costs)
    fin=np.isfinite(A).all(axis=1)
    return A[fin], cost[fin]


def apply_rule(A, tp, sl):
    """first grid step where markout>=tp (take profit) or <=-sl (stop); else last step (time stop)."""
    n,k=A.shape
    exit_idx=np.full(n,k-1)
    hit=np.zeros(n,bool)
    for j in range(k):
        col=A[:,j]
        trig=(~hit)&((col>=tp)|(col<=-sl))
        exit_idx[trig]=j; hit|=trig
    return A[np.arange(n),exit_idx]


def main():
    Atr,ctr=build(None,TRAIN_HI); Ate,cte=build(TEST_LO,None)
    print(f"train entries={Atr.shape[0]:,}  test entries={Ate.shape[0]:,}  avg cost={ctr.mean():.1f}bp\n")
    # grid-search TP/SL on TRAIN (net of cost), pick best, report OOS on TEST
    tps=[5,8,10,15,20,30,50,1e9]; sls=[10,20,30,50,1e9]     # 1e9 = disabled
    best=None
    for tp in tps:
        for sl in sls:
            net=apply_rule(Atr,tp,sl).mean()-ctr.mean()
            if best is None or net>best[0]: best=(net,tp,sl)
    net_tr,tp,sl=best
    oos=apply_rule(Ate,tp,sl); net_te=oos.mean()-cte.mean()
    lab=lambda v:"off" if v>1e8 else f"{v:.0f}"
    print(f"BEST train-fit rule: take-profit={lab(tp)}bp  stop-loss={lab(sl)}bp")
    print(f"  TRAIN net (of cost {ctr.mean():.1f}): {net_tr:+.2f}bp")
    print(f"  TEST  net (OOS): gross {oos.mean():+.2f}  ->  net(full cost) {net_te:+.2f}bp"
          f"   |  net(maker-exit, half cost) {oos.mean()-cte.mean()/2:+.2f}bp")
    # baseline: best fixed horizon on TRAIN applied OOS
    hstar=int(np.argmax(Atr.mean(0))); base=Ate[:,hstar]
    print(f"\n  baseline best-fixed-horizon ({GRID[hstar]}min): TEST net {base.mean()-cte.mean():+.2f}bp")
    print(f"  buy&hold-to-6h gross {Ate[:,GRID.index(360)].mean():+.2f}bp")


if __name__=="__main__":
    main()
