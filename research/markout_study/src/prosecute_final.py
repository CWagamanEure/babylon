"""Final balance checks on top-decile selection: coin/month concentration, raw-vs-neut,
permutation null (does train-edge selection beat random?), and the ACTUAL wallet PnL sanity."""
import sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np, polars as pl
SCR=Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4
def mstr(ms): return datetime.fromtimestamp(ms/1000,tz=timezone.utc).strftime("%Y-%m")
E=pl.read_parquet(SCR/"prosecute_entries.parquet").with_columns(mon=pl.col("b_ts").map_elements(mstr,return_dtype=pl.Utf8))
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
Wall=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()),on="wallet",how="inner")
S=Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)).sort("edge",descending=True); N=S.height
top=S.head(int(N*0.10)); ws=set(top["wallet"].to_list()); tet=te.filter(pl.col("wallet").is_in(ws))
print(f"TOP 10% = {top.height} wallets, test neut {tet['neut'].mean()*BP:+.1f}bp")
print("\nPER-COIN (test neut, entries):")
for c in ["BTC","ETH","SOL","HYPE"]:
    s=tet.filter(pl.col("coin")==c); print(f"  {c}: {s['neut'].mean()*BP:+7.1f}bp  raw {s['raw'].mean()*BP:+7.1f}bp  (n={s.height})")
print("\nPER-TEST-MONTH (test neut):")
for m in sorted(tet["mon"].unique().to_list()):
    s=tet.filter(pl.col("mon")==m); print(f"  {m}: {s['neut'].mean()*BP:+7.1f}bp (n={s.height}, {s['wallet'].n_unique()} wallets active)")
print(f"\nRAW vs NEUT (top cohort test): raw={tet['raw'].mean()*BP:+.1f}bp neut={tet['neut'].mean()*BP:+.1f}bp "
      f"(neut removes market; both large => not a neutralization artifact)")

# PERMUTATION NULL: shuffle wallet identities between train and test, re-select top decile by (shuffled) train edge
print("\nPERMUTATION NULL — does TRAIN-edge selection beat random wallet selection?")
tr_e=S["edge"].to_numpy(); te_e=S["edge_test"].to_numpy(); k=int(N*0.10)
obs=np.sort(te_e)[::-1]  # not used
# real: top-k by train edge -> their test edge mean
real=te_e[np.argsort(tr_e)[::-1][:k]].mean()*BP
rng=np.random.default_rng(0)
null=np.array([te_e[rng.permutation(N)[:k]].mean() for _ in range(5000)])*BP  # random k wallets
print(f"  top-{k}-by-train test neut = {real:+.1f}bp | random-{k} null mean {null.mean():+.1f} [{np.percentile(null,2.5):+.1f},{np.percentile(null,97.5):+.1f}] | p={np.mean(null>=real):.4f}")
# also permute the train->test LINK (break persistence): shuffle te_e, re-select
null2=np.array([ (lambda p: p[np.argsort(tr_e)[::-1][:k]].mean())(rng.permutation(te_e)) for _ in range(5000)])*BP
print(f"  train->test link broken (shuffle test edges): selected test neut {null2.mean():+.1f} [{np.percentile(null2,2.5):+.1f},{np.percentile(null2,97.5):+.1f}] vs real {real:+.1f} | p={np.mean(null2>=real):.4f}")
