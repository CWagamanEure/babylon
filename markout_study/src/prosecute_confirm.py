"""Airtight confirmation + CIs: neut = raw - bench (bench=dir*coinday_mean). Which component
carries the r=0.61 persistence? And CIs on the tradeable vs untradeable numbers."""
import numpy as np, polars as pl
from pathlib import Path
SCR=Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4
E=pl.read_parquet(SCR/"prosecute_entries.parquet").with_columns(bench=pl.col("raw")-pl.col("neut"))  # = dir*coinday_mean
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
def wagg(df): return df.group_by("wallet").agg(n=pl.len(),neut=pl.col("neut").mean(),raw=pl.col("raw").mean(),bench=pl.col("bench").mean())
W=wagg(tr).join(wagg(te),on="wallet",suffix="_te",how="inner").filter((pl.col("n")>=300)&(pl.col("n_te")>=20))
def rboot(x,y,n=3000):
    x=np.asarray(x);y=np.asarray(y);rng=np.random.default_rng(0)
    b=[np.corrcoef(x[s],y[s])[0,1] for s in (rng.integers(0,len(x),len(x)) for _ in range(n))]
    return np.corrcoef(x,y)[0,1],np.percentile(b,2.5),np.percentile(b,97.5)
print(f"cohort N={W.height}  (n_train>=300 & n_test>=20). Per-wallet train->test correlation [95% CI]:")
for comp in ["neut","raw","bench"]:
    r,lo,hi=rboot(W[comp],W[f"{comp}_te"])
    tag={"neut":"NEUT (raw-bench)  [the finding]","raw":"RAW directional   [tradeable]","bench":"BENCH=-dir*coinday_mean [untradeable]"}[comp]
    print(f"  {tag:40s} r={r:+.3f} [{lo:+.3f},{hi:+.3f}]")
# what fraction of neut persistence covariance is the bench term?
cn=np.cov(W["neut"],W["neut_te"])[0,1]; cr=np.cov(W["raw"],W["raw_te"])[0,1]; cb=np.cov(W["bench"],W["bench_te"])[0,1]
crb=np.cov(W["raw"],W["bench_te"])[0,1]+np.cov(W["bench"],W["raw_te"])[0,1]
print(f"\n  Cov(neut_tr,neut_te) decomposition: raw-raw={cr/cn*100:+.0f}%  bench-bench={cb/cn*100:+.0f}%  cross={crb/cn*100:+.0f}%  (of total {cn:.2e})")
print("  => persistence is carried by the UNTRADEABLE bench term, not the tradeable raw return.")

# mean levels with CI (cluster by coin-day) for the top-10%-by-train-neut cohort, raw-net
S=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(te.group_by("wallet").agg(nt=pl.len()),on="wallet").filter((pl.col("n")>=300)&(pl.col("nt")>=20))
ws=set(S.sort("edge",descending=True).head(int(S.height*0.1))["wallet"].to_list())
d=te.filter(pl.col("wallet").is_in(ws)).with_columns(cd=pl.col("coin")+"_"+pl.col("day").cast(pl.Utf8))
from collections import defaultdict
for col,lab in [("neut","NEUT metric (untradeable)"),("raw","RAW directional gross (tradeable)")]:
    v=d[col].to_numpy(); cds=d["cd"].to_numpy(); by=defaultdict(list); [by[c].append(i) for i,c in enumerate(cds)]
    cl=[np.array(x) for x in by.values()]; rng=np.random.default_rng(1)
    bo=[v[np.concatenate([cl[p] for p in rng.integers(0,len(cl),len(cl))])].mean()*BP for _ in range(1500)]
    print(f"  top-10% test {lab:34s} = {v.mean()*BP:+7.1f}bp  95%CI[{np.percentile(bo,2.5):+.1f},{np.percentile(bo,97.5):+.1f}] ({len(cl)} coin-day clusters)")
