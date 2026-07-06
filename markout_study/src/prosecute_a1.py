"""ATTACK 1 — shared-bar / co-trading crowds. Is the 993-wallet persistence N independent
wallets or a few crowds? Effective-N via co-trade clustering; cluster-robust corr CI."""
import sys
from pathlib import Path
import numpy as np, polars as pl
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4
E=pl.read_parquet(SCR/"prosecute_entries.parquet")
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
Wall=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()),on="wallet",how="inner")
COH=Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)).sort("wallet")
cohort=COH["wallet"].to_list(); cidx={w:i for i,w in enumerate(cohort)}; NW=len(cohort)
print(f"cohort {NW} wallets, baseline corr={np.corrcoef(COH['edge'],COH['edge_test'])[0,1]:.3f}")

# --- shared-bar concentration (TRAIN): fraction of cohort entries on bars traded by >=2 cohort wallets
trc=tr.filter(pl.col("wallet").is_in(set(cohort))).with_columns(
    key=pl.col("coin")+"_"+pl.col("bar").cast(pl.Utf8)+"_"+pl.col("dir").cast(pl.Utf8))
kg=trc.group_by("key").agg(nw=pl.col("wallet").n_unique(),ne=pl.len())
shared_e=kg.filter(pl.col("nw")>=2)["ne"].sum(); tot_e=trc.height
print(f"\nSHARED-BAR (coin,5min,dir) concentration in cohort TRAIN entries:")
print(f"  {100*shared_e/tot_e:.1f}% of cohort entries land on a bar-cell also traded by >=1 OTHER cohort wallet")
print(f"  unique bar-cells={kg.height}, entries={tot_e}, max cohort wallets on one cell={kg['nw'].max()}")

# --- build wallet x key incidence (train) and wallet-overlap for co-trade clustering
uk=trc.select("wallet","key").unique()
kmap={k:i for i,k in enumerate(uk["key"].unique().to_list())}
rows=[cidx[w] for w in uk["wallet"].to_list()]
cols=[kmap[k] for k in uk["key"].to_list()]
A=csr_matrix((np.ones(len(rows)),(rows,cols)),shape=(NW,len(kmap)))
deg=np.asarray(A.sum(1)).ravel()  # distinct bar-cells per wallet
O=(A@A.T).toarray()  # shared distinct bar-cells between wallets
# Jaccard
den=deg[:,None]+deg[None,:]-O; den[den==0]=1; J=O/den
np.fill_diagonal(J,0)
for thr in [0.2,0.3,0.5]:
    adj=csr_matrix(J>=thr); ncc,lab=connected_components(adj,directed=False)
    # sizes
    sizes=np.bincount(lab); big=np.sort(sizes)[::-1][:5]
    print(f"\n  co-trade clusters @ Jaccard>={thr}: {ncc} clusters (from {NW} wallets); top sizes {big.tolist()}")
    # collapse each cluster -> pooled meta-wallet edges; corr across clusters
    dfc=COH.with_columns(pl.Series("cl",lab.tolist()))
    # pooled (entry-weighted) edge per cluster from raw entries
    trm=tr.filter(pl.col("wallet").is_in(set(cohort))).join(dfc.select("wallet","cl"),on="wallet").group_by("cl").agg(e=pl.col("neut").mean(),n=pl.len())
    tem=te.filter(pl.col("wallet").is_in(set(cohort))).join(dfc.select("wallet","cl"),on="wallet").group_by("cl").agg(e=pl.col("neut").mean(),n=pl.len())
    m=trm.join(tem,on="cl",suffix="_te")
    rc=np.corrcoef(m["e"],m["e_te"])[0,1]
    print(f"    corr across {m.height} collapsed meta-wallets = {rc:+.3f} (pooled edges), mean test={m['e_te'].mean()*BP:+.1f}bp")

# --- cluster-robust bootstrap of the 993-point corr, clustering by Jaccard>=0.3 community
adj=csr_matrix(J>=0.3); ncc,lab=connected_components(adj,directed=False)
x=COH["edge"].to_numpy()*BP; y=COH["edge_test"].to_numpy()*BP
from collections import defaultdict
byc=defaultdict(list)
for i,l in enumerate(lab): byc[l].append(i)
cl=[np.array(v) for v in byc.values()]
rng=np.random.default_rng(5); bo=[]
for _ in range(3000):
    pick=rng.integers(0,len(cl),len(cl)); sel=np.concatenate([cl[p] for p in pick])
    if sel.size>3: bo.append(np.corrcoef(x[sel],y[sel])[0,1])
lo,hi=np.percentile(bo,[2.5,97.5])
print(f"\n  CLUSTER-ROBUST corr 95% CI (resample {ncc} communities) = [{lo:+.3f},{hi:+.3f}]  point={np.corrcoef(x,y)[0,1]:+.3f}")
# naive wallet-bootstrap CI for contrast
bo2=[np.corrcoef(x[s],y[s])[0,1] for s in (rng.integers(0,NW,NW) for _ in range(3000))]
lo2,hi2=np.percentile(bo2,[2.5,97.5])
print(f"  naive wallet-bootstrap 95% CI = [{lo2:+.3f},{hi2:+.3f}]  (effective N={ncc} vs nominal {NW})")
