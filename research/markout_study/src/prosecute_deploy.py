"""DECISIVE deployability: the neut edge is dir*(fwd - coinday_mean). A copier earns the RAW
directional return, NOT the neut (coinday_mean is a non-tradeable within-day benchmark).
Compute honest tradeable net on RAW, test if RAW is even selectable, and characterize the wallets."""
import sys
from pathlib import Path
import numpy as np, polars as pl
sys.path.insert(0,str(Path(__file__).resolve().parent))
from mkcommon import _load_bars,_next_bar_close_vec
ROOT=Path(__file__).resolve().parents[1]
SCR=Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4; COST_BPS={"BTC":8.0,"ETH":8.0,"SOL":10.0,"HYPE":14.0}; H24=24*3_600_000; LAG=15*60_000
E=pl.read_parquet(SCR/"prosecute_entries.parquet")
# add raw_lag (15-min-lag directional, un-neutralized) by recomputing
lk=_load_bars(); rawlag={}
for c in ["BTC","ETH","SOL","HYPE"]:
    L=lk[c]; bt=L[0].astype(np.int64)
    el=_next_bar_close_vec(L,bt+LAG); xl=_next_bar_close_vec(L,bt+LAG+H24)
    with np.errstate(all="ignore"): f=xl/el-1.0
    f[~(np.isfinite(el)&(el>0)&np.isfinite(xl)&(xl>0))]=np.nan; rawlag[c]=(bt,f)
def add_rawlag(df):
    out=[]
    for c in ["BTC","ETH","SOL","HYPE"]:
        s=df.filter(pl.col("coin")==c); bt,f=rawlag[c]
        i=np.clip(np.searchsorted(bt,s["b_ts"].to_numpy()),0,bt.size-1)
        out.append(s.with_columns(pl.Series("raw_lag",s["dir"].to_numpy()*f[i])))
    return pl.concat(out)
tr=E.filter(pl.col("split")=="train"); te=add_rawlag(E.filter(pl.col("split")=="test"))
fund=pl.read_parquet(ROOT.parent/"scratch_conv/mlscreen/funding.parquet").filter(pl.col("coin").is_in(["BTC","ETH","SOL","HYPE"])).sort("coin","time")
fmap={c:(fund.filter(pl.col("coin")==c)["time"].to_numpy(),np.concatenate([[0.0],np.cumsum(fund.filter(pl.col("coin")==c)["rate"].to_numpy())])) for c in ["BTC","ETH","SOL","HYPE"]}
def netcols(d):
    fd=[]
    for c,b,di in zip(d["coin"],d["b_ts"],d["dir"]):
        t,cum=fmap[c]; lo=np.clip(np.searchsorted(t,b+LAG),0,len(cum)-1); hi=np.clip(np.searchsorted(t,b+LAG+H24),0,len(cum)-1); fd.append(di*(cum[hi]-cum[lo]))
    return np.array(fd),np.array([COST_BPS[c]/BP for c in d["coin"]])

Wn=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean(),edge_raw=pl.col("raw").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len()),on="wallet",how="inner")
S=Wn.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)); N=S.height

print("neut - raw = -dir*coinday_mean : is the neut 'edge' tradeable? (top-10%-by-train-NEUT cohort)")
topN=S.sort("edge",descending=True).head(int(N*0.10)); ws=set(topN["wallet"].to_list())
d=te.filter(pl.col("wallet").is_in(ws)).filter(pl.col("raw_lag").is_finite())
dd=d.select("coin","b_ts","dir","raw","neut","raw_lag").to_dict(as_series=False)
fd,cost=netcols(dd)
raw=np.array(dd["raw"]); neut=np.array(dd["neut"]); rl=np.array(dd["raw_lag"])
print(f"  NEUT (untradeable metric)         = {neut.mean()*BP:+7.2f}bp")
print(f"  RAW directional (tradeable, no lag)= {raw.mean()*BP:+7.2f}bp")
print(f"  RAW +15min lag                    = {rl.mean()*BP:+7.2f}bp")
print(f"  RAW - cost - funding (DEPLOYABLE) = {(rl-cost-fd).mean()*BP:+7.2f}bp")
print(f"  per-coin DEPLOYABLE raw-net: "+str({c:round(float((rl[np.array(dd['coin'])==c]-cost[np.array(dd['coin'])==c]-fd[np.array(dd['coin'])==c]).mean()*BP),1) for c in ['BTC','ETH','SOL','HYPE']}))

print("\nIs the RAW directional return even SELECTABLE (select on train raw -> test raw)?")
Sr=Wn.filter((pl.col("n")>=300)&(pl.col("n_test")>=20))
ter=te.group_by("wallet").agg(edge_raw_te=pl.col("raw").mean())
Sr=Sr.join(ter,on="wallet")
r=np.corrcoef(Sr["edge_raw"],Sr["edge_raw_te"])[0,1]
topr=Sr.sort("edge_raw",descending=True).head(int(N*0.10))
print(f"  corr(train raw, test raw) = {r:+.3f} | top-10%-by-train-RAW test raw = {topr['edge_raw_te'].mean()*BP:+.1f}bp "
      f"(vs field raw {te['raw'].mean()*BP:+.1f}bp)")

print("\nWHO are the top-neut wallets? (mean-reversion / two-sided intraday traders => neut>>raw by construction)")
top=te.filter(pl.col("wallet").is_in(ws))
alltop=tr.filter(pl.col("wallet").is_in(ws))
print(f"  long-share={100*(alltop['dir']==1).mean():.0f}% | entries/wallet(train)={alltop.height/len(ws):.0f} "
      f"| trades/day/wallet={alltop.height/len(ws)/(alltop['day'].n_unique()):.1f}")
# how two-sided within a coin-day? fraction of (wallet,coin,day) with BOTH long and short entries
bs=alltop.group_by("wallet","coin","day").agg(nl=(pl.col("dir")==1).sum(),ns=(pl.col("dir")==-1).sum())
print(f"  {100*((bs['nl']>0)&(bs['ns']>0)).mean():.0f}% of (wallet,coin,day) cells have BOTH long & short entries (intraday two-sided)")
