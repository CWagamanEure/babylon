"""Deep-dive ATTACK 2 (timing) legitimacy + fixed ATTACK 6 (net, nan-safe)."""
import sys, collections
from pathlib import Path
import numpy as np, polars as pl
ROOT = Path(__file__).resolve().parents[1]
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP = 1e4; COST_BPS = {"BTC":8.0,"ETH":8.0,"SOL":10.0,"HYPE":14.0}; H24=24*3_600_000; LAG=15*60_000

E = pl.read_parquet(SCR / "prosecute_entries.parquet")
tr = E.filter(pl.col("split")=="train"); te = E.filter(pl.col("split")=="test")
Wall = tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()), on="wallet", how="inner")
COH = Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)); cohort=set(COH["wallet"].to_list())

print("="*90,"\nATTACK 2 legitimacy — is the (coin,hour,dir) timing structure real & field-wide (not circular)?\n","="*90)
# field test neut vs cohort test neut
print(f"  FIELD (all test wallets) mean test neut = {te['neut'].mean()*BP:+.1f}bp over {te.height} entries")
print(f"  COHORT test neut = {te.filter(pl.col('wallet').is_in(cohort))['neut'].mean()*BP:+.1f}bp")
# cell means from TRAIN field
cell = E.filter(pl.col("split")=="train").group_by("coin","hour","dir").agg(cm=pl.col("neut").mean(),ncell=pl.len())
print("  Top (coin,hour,dir) cells by train neut (field):")
print(cell.sort("cm",descending=True).head(6).with_columns((pl.col("cm")*BP).round(1)).to_pandas().to_string(index=False))
print("  Bottom:")
print(cell.sort("cm").head(4).with_columns((pl.col("cm")*BP).round(1)).to_pandas().to_string(index=False))
# does the intraday structure PERSIST train->test (proving it's structural, not fit to cohort)?
cell_te = E.filter(pl.col("split")=="test").group_by("coin","hour","dir").agg(cm_te=pl.col("neut").mean())
cj = cell.join(cell_te,on=["coin","hour","dir"])
print(f"  cell(coin,hour,dir) train->test neut corr = {np.corrcoef(cj['cm'],cj['cm_te'])[0,1]:+.3f}  "
      f"(if high, timing structure is real & OOS-stable, not a cohort artifact)")

print("\n"+"="*90,"\nATTACK 6 fixed (nan-safe) — NET copyable edge, cost sensitivity\n","="*90)
tec = te.filter(pl.col("wallet").is_in(cohort)).filter(pl.col("neut_lag").is_finite())
fund = pl.read_parquet(ROOT.parent/"scratch_conv/mlscreen/funding.parquet").filter(
    pl.col("coin").is_in(["BTC","ETH","SOL","HYPE"])).sort("coin","time")
fmap={}
for c in ["BTC","ETH","SOL","HYPE"]:
    s=fund.filter(pl.col("coin")==c); fmap[c]=(s["time"].to_numpy(), np.concatenate([[0.0],np.cumsum(s["rate"].to_numpy())]))
rows=tec.select("coin","b_ts","dir","neut","neut_lag").to_dict(as_series=False)
def fd_(c,b,d):
    t,cum=fmap[c]; lo=np.clip(np.searchsorted(t,b+LAG),0,len(cum)-1); hi=np.clip(np.searchsorted(t,b+LAG+H24),0,len(cum)-1)
    return d*(cum[hi]-cum[lo])
fd=np.array([fd_(c,b,d) for c,b,d in zip(rows["coin"],rows["b_ts"],rows["dir"])])
cost=np.array([COST_BPS[c]/BP for c in rows["coin"]])
neut_lag=np.array(rows["neut_lag"])
for mult,lab in [(1.0,"full COST_BPS (8-14bp, upper bound)"),(0.5,"half cost"),(0.25,"quarter cost")]:
    net=neut_lag-cost*mult-fd
    print(f"  NET @ {lab:38s} = {net.mean()*BP:+6.2f}bp")
# cluster CI at full cost
net=neut_lag-cost-fd
cd=np.array([f"{c}_{b//86_400_000}" for c,b in zip(rows['coin'],rows['b_ts'])])
_,inv=np.unique(cd,return_inverse=True)
idx=collections.defaultdict(list)
for i,k in enumerate(inv): idx[k].append(i)
cl=[np.array(v) for v in idx.values()]
rng=np.random.default_rng(3); bo=[np.concatenate([cl[p] for p in rng.integers(0,len(cl),len(cl))]) for _ in range(1500)]
bo=[net[s].mean() for s in bo]; lo,hi=np.percentile(bo,[2.5,97.5])*BP
print(f"  per-coin NET(full): "+str({c:round(float(net[np.array(rows['coin'])==c].mean()*BP),1) for c in ['BTC','ETH','SOL','HYPE']}))
print(f"  pooled NET(full) {net.mean()*BP:+.2f}bp  95%CI [{lo:+.2f},{hi:+.2f}]  ({len(cl)} coin-day clusters, {len(net)} entries)")
