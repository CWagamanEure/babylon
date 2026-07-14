"""Prosecute the TOP-selected cohort (top decile by train neut). Is +73-88bp test real distributed
skill or (a) a co-trading crowd, (b) cell-timing, (c) a few concentrated days/bars/fat tails?"""
import sys
from pathlib import Path
import numpy as np, polars as pl
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
SCR=Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4
E=pl.read_parquet(SCR/"prosecute_entries.parquet")
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
Wall=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()),on="wallet",how="inner")
S=Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)).sort("edge",descending=True); N=S.height

for frac,lab in [(0.05,"TOP 5% (49w)"),(0.10,"TOP 10% (99w)")]:
    k=max(3,int(N*frac)); top=S.head(k); ws=set(top["wallet"].to_list())
    tet=te.filter(pl.col("wallet").is_in(ws)); trt=tr.filter(pl.col("wallet").is_in(ws))
    print("="*88); print(f"{lab}: {k} wallets | train {top['edge'].mean()*BP:+.0f}bp | test {top['edge_test'].mean()*BP:+.0f}bp | {tet.height} test entries")
    # (c) FAT-TAIL / concentration
    v=tet["neut"].to_numpy()
    print(f"  [tail] test neut mean={v.mean()*BP:+.1f} median={np.median(v)*BP:+.1f} "
          f"trim5%={np.mean(np.sort(v)[int(.05*len(v)):int(.95*len(v))])*BP:+.1f} %pos={100*np.mean(v>0):.0f}%")
    # % of positive test edge from top-1% entries and top-5 coin-days
    cd=tet.with_columns(cd=pl.col("coin")+"_"+pl.col("day").cast(pl.Utf8)).group_by("cd").agg(s=pl.col("neut").sum()).sort("s",descending=True)
    tot=v.sum(); print(f"  [concentration] top-5 coin-days = {100*cd.head(5)['s'].sum()/tot:.0f}% of total test edge; #coin-days={cd.height}")
    # per-wallet: how many of the k wallets are individually test-positive (distributed skill?)
    pw=tet.group_by("wallet").agg(e=pl.col("neut").mean()); print(f"  [distributed] {100*(pw['e']>0).mean():.0f}% of the {pw.height} wallets are test-positive individually")
    # (a) CROWD within top: effective-N via Jaccard on train bar-cells
    uk=trt.with_columns(key=pl.col("coin")+"_"+pl.col("bar").cast(pl.Utf8)+"_"+pl.col("dir").cast(pl.Utf8)).select("wallet","key").unique()
    wl=sorted(ws); wi={w:i for i,w in enumerate(wl)}; km={kk:i for i,kk in enumerate(uk["key"].unique().to_list())}
    A=csr_matrix((np.ones(uk.height),([wi[w] for w in uk["wallet"]],[km[x] for x in uk["key"]])),shape=(len(wl),len(km)))
    deg=np.asarray(A.sum(1)).ravel(); O=(A@A.T).toarray(); den=deg[:,None]+deg[None,:]-O; den[den==0]=1; J=O/den; np.fill_diagonal(J,0)
    ncc,_=connected_components(csr_matrix(J>=0.3),directed=False)
    # shared-bar fraction of test edge: bars traded by >=2 top wallets
    tk=tet.with_columns(key=pl.col("coin")+"_"+pl.col("bar").cast(pl.Utf8)+"_"+pl.col("dir").cast(pl.Utf8))
    kg=tk.group_by("key").agg(nw=pl.col("wallet").n_unique(),s=pl.col("neut").sum())
    shared_edge=kg.filter(pl.col("nw")>=2)["s"].sum()
    print(f"  [crowd] effective independent wallets (Jaccard>=0.3 clusters) = {ncc}/{k}; "
          f"{100*shared_edge/tot:.0f}% of test edge from bar-cells shared by >=2 top wallets")
    # (b) cell-timing decomposition (contemporaneous field TEST cell means)
    fcm=te.group_by("coin","hour","dir").agg(fcm=pl.col("neut").mean())
    dec=tet.join(fcm,on=["coin","hour","dir"],how="left")
    print(f"  [timing] test edge {dec['neut'].mean()*BP:+.1f} = field-cell-selection {dec['fcm'].mean()*BP:+.1f} + within-cell SKILL {(dec['neut'].mean()-dec['fcm'].mean())*BP:+.1f}bp")
    # cluster-robust CI on test neut by coin-day
    cds=tk.with_columns(cd=pl.col("coin")+"_"+pl.col("day").cast(pl.Utf8))["cd"].to_numpy(); nv=tet["neut"].to_numpy()
    by=defaultdict(list); [by[c].append(i) for i,c in enumerate(cds)]
    cl=[np.array(x) for x in by.values()]; rng=np.random.default_rng(7)
    bo=[np.concatenate([cl[p] for p in rng.integers(0,len(cl),len(cl))]) for _ in range(1500)]; bo=[nv[s].mean()*BP for s in bo]
    print(f"  [robust] test neut 95% CI (cluster=coin-day, {len(cl)} clusters) = [{np.percentile(bo,2.5):+.1f},{np.percentile(bo,97.5):+.1f}]")
