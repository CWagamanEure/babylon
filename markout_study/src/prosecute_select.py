"""The monetizable test: rank wallets by TRAIN neut, copy the top (this is what r=0.61 implies).
Does top-train-selected wallets' TEST edge beat field, and survive lag+cost+funding?"""
import sys
from pathlib import Path
import numpy as np, polars as pl
ROOT=Path(__file__).resolve().parents[1]
SCR=Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4; COST_BPS={"BTC":8.0,"ETH":8.0,"SOL":10.0,"HYPE":14.0}; H24=24*3_600_000; LAG=15*60_000
E=pl.read_parquet(SCR/"prosecute_entries.parquet")
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
Wall=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()),on="wallet",how="inner")
S=Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)).sort("edge",descending=True)
N=S.height
# funding map
fund=pl.read_parquet(ROOT.parent/"scratch_conv/mlscreen/funding.parquet").filter(pl.col("coin").is_in(["BTC","ETH","SOL","HYPE"])).sort("coin","time")
fmap={c:(fund.filter(pl.col("coin")==c)["time"].to_numpy(),np.concatenate([[0.0],np.cumsum(fund.filter(pl.col("coin")==c)["rate"].to_numpy())])) for c in ["BTC","ETH","SOL","HYPE"]}
def net_of(wset):
    d=te.filter(pl.col("wallet").is_in(wset)).filter(pl.col("neut_lag").is_finite()).select("coin","b_ts","dir","neut_lag").to_dict(as_series=False)
    if not d["coin"]: return np.nan,np.nan,0
    fd=[]
    for c,b,di in zip(d["coin"],d["b_ts"],d["dir"]):
        t,cum=fmap[c]; lo=np.clip(np.searchsorted(t,b+LAG),0,len(cum)-1); hi=np.clip(np.searchsorted(t,b+LAG+H24),0,len(cum)-1)
        fd.append(di*(cum[hi]-cum[lo]))
    fd=np.array(fd); cost=np.array([COST_BPS[c]/BP for c in d["coin"]]); nl=np.array(d["neut_lag"])
    gross=nl.mean()*BP; net=(nl-cost-fd).mean()*BP
    return gross,net,len(nl)
print(f"Wallets with n_train>=300 & n_test>=20: {N}. Ranking by TRAIN neut, copying the top:")
print(f"{'select':16s} {'#w':>4} {'train neut':>10} {'TEST neut':>10} {'test-lag gross':>14} {'NET(lag+cost+fund)':>18}")
for frac,lab in [(0.05,"top 5%"),(0.10,"top 10%"),(0.25,"top 25%"),(0.50,"top 50%"),(1.0,"all (n>=300)")]:
    k=max(3,int(N*frac)); sub=S.head(k); wset=set(sub["wallet"].to_list())
    g,net,ne=net_of(wset)
    print(f"  {lab:14s} {k:>4} {sub['edge'].mean()*BP:>+9.1f}b {sub['edge_test'].mean()*BP:>+9.1f}b {g:>+13.2f}b {net:>+17.2f}b")
# bottom for contrast + spread
bot=S.tail(max(3,int(N*0.10)))
print(f"  {'bottom 10%':14s} {bot.height:>4} {bot['edge'].mean()*BP:>+9.1f}b {bot['edge_test'].mean()*BP:>+9.1f}b")
print(f"\n  TOP-BOTTOM decile TEST-neut spread (gross) = {(S.head(int(N*0.1))['edge_test'].mean()-S.tail(int(N*0.1))['edge_test'].mean())*BP:+.1f}bp")
