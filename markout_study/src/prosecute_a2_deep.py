"""ATTACK 2 decisive: is cohort edge intraday-timing (cell selection) or within-cell skill?"""
import sys
from pathlib import Path
import numpy as np, polars as pl
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4
E = pl.read_parquet(SCR/"prosecute_entries.parquet")
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
Wall=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()),on="wallet",how="inner")
COH=Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)); cohort=set(COH["wallet"].to_list())

# 1) hour-of-day x dir pattern pooled across coins, TRAIN vs TEST (entry-weighted) -- does 21:00-long persist?
print("hour-of-day x dir neut (bp), field, TRAIN vs TEST  (does the intraday pattern persist?)")
for d in [1,-1]:
    trh=tr.filter(pl.col("dir")==d).group_by("hour").agg(tr=pl.col("neut").mean(),ntr=pl.len())
    teh=te.filter(pl.col("dir")==d).group_by("hour").agg(teh=pl.col("neut").mean(),nte=pl.len())
    j=trh.join(teh,on="hour").sort("hour")
    # weighted corr across hours by min count
    x=j["tr"].to_numpy();y=j["teh"].to_numpy()
    print(f"  dir={d:+d}: corr(train hour-neut, test hour-neut) over 24 hours = {np.corrcoef(x,y)[0,1]:+.3f}")
    # show the extreme hours
    peak=j.sort("tr",descending=True).head(3)
    print(f"    top-train hours: "+", ".join(f"h{int(h)}: tr{t*BP:+.0f}/te{te2*BP:+.0f}bp" for h,t,te2 in zip(peak['hour'],peak['tr'],peak['teh'])))

# 2) DECOMPOSITION (contemporaneous, TEST): cohort edge = field-cell-selection + within-cell excess
cell_te=te.group_by("coin","hour","dir").agg(fcm=pl.col("neut").mean())  # field TEST cell mean
tec=te.filter(pl.col("wallet").is_in(cohort)).join(cell_te,on=["coin","hour","dir"],how="left")
sel=tec["fcm"].mean()*BP; tot=tec["neut"].mean()*BP
print(f"\nDECOMPOSITION of cohort TEST edge (contemporaneous cells):")
print(f"  total cohort test neut       = {tot:+.2f}bp")
print(f"  = field cell-selection (timing) {sel:+.2f}bp  (what ANY wallet trading these coin/hour/dir cells earns)")
print(f"  + within-cell EXCESS (skill)    {tot-sel:+.2f}bp")

# 3) does WITHIN-CELL excess persist train->test per wallet? (real skill signal)
cell_tr=tr.group_by("coin","hour","dir").agg(fcm=pl.col("neut").mean())
trx=tr.filter(pl.col("wallet").is_in(cohort)).join(cell_tr,on=["coin","hour","dir"],how="left").with_columns(x=pl.col("neut")-pl.col("fcm"))
tex=te.filter(pl.col("wallet").is_in(cohort)).join(cell_te,on=["coin","hour","dir"],how="left").with_columns(x=pl.col("neut")-pl.col("fcm"))
a=trx.group_by("wallet").agg(e=pl.col("x").mean(),n=pl.len())
b=tex.group_by("wallet").agg(e=pl.col("x").mean(),n=pl.len())
j=a.join(b,on="wallet",suffix="_te").filter((pl.col("n")>=30)&(pl.col("n_te")>=20))
r=np.corrcoef(j["e"],j["e_te"])[0,1]
print(f"\n  WITHIN-CELL-excess persistence (real skill): N={j.height} corr={r:+.3f} mean test excess={j['e_te'].mean()*BP:+.2f}bp")
print(f"  (vs baseline raw-neut persistence corr=+0.615, mean +9.9bp)")

# 4) cohort entry-hour concentration vs field
print(f"\ncohort entry-hour concentration (top hours, % of cohort entries):")
hh=te.filter(pl.col("wallet").is_in(cohort)).group_by("hour").agg(c=pl.len()).sort("c",descending=True).head(5)
tot_e=te.filter(pl.col("wallet").is_in(cohort)).height
print("  "+", ".join(f"h{int(h)}:{100*c/tot_e:.1f}%" for h,c in zip(hh['hour'],hh['c'])))
fh=te.group_by("hour").agg(c=pl.len()).sort("c",descending=True).head(5)
print("  field top hours:  "+", ".join(f"h{int(h)}:{100*c/te.height:.1f}%" for h,c in zip(fh['hour'],fh['c'])))
