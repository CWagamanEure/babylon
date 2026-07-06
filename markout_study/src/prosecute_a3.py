"""ATTACK 3 — maker/passive fills. Entries are taker-only by construction (crossed & ~zhash).
Empirically confirm cohort wallets DO have maker fills (excluded), so edge can't be maker-spread.
Also: cohort vs FIELD test neut (how much does wallet-identification actually add)."""
import sys
from pathlib import Path
import numpy as np, polars as pl
ROOT=Path(__file__).resolve().parents[1]
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP=1e4
E=pl.read_parquet(SCR/"prosecute_entries.parquet")
tr=E.filter(pl.col("split")=="train"); te=E.filter(pl.col("split")=="test")
Wall=tr.group_by("wallet").agg(n=pl.len(),edge=pl.col("neut").mean()).join(
    te.group_by("wallet").agg(n_test=pl.len(),edge_test=pl.col("neut").mean()),on="wallet",how="inner")
COH=Wall.filter((pl.col("n")>=300)&(pl.col("n_test")>=20)); cohort=set(COH["wallet"].to_list())

# --- ATTACK 3: maker fills present in cohort wallets' raw tape (one test month), all EXCLUDED from entries
mon=pl.scan_parquet(ROOT.parent/"scratch_conv/mlscreen/cand2_202604.parquet").filter(
    pl.col("coin").is_in(["BTC","ETH","SOL","HYPE"]) & pl.col("wallet").is_in(cohort)).select("crossed","zhash").collect()
nmaker=(~mon["crossed"]).sum(); ntot=mon.height
print(f"ATTACK 3 (taker-only by construction): cohort raw fills in Apr'26 = {ntot}; "
      f"maker(non-crossed)={nmaker} ({100*nmaker/ntot:.1f}%), wash(zhash)={mon['zhash'].sum()} "
      f"-> entries require crossed & ~zhash, so ALL these are EXCLUDED. Edge cannot be maker-spread.")

# --- Cohort vs FIELD: the real 'wallet identification' premium
field_te=te["neut"].mean()*BP
coh_te=te.filter(pl.col("wallet").is_in(cohort))["neut"].mean()*BP
# random field wallets matched on n_test>=20 (same activity floor)
fieldw=Wall.filter(pl.col("n_test")>=20)
rng=np.random.default_rng(1)
samp=[fieldw.sample(len(cohort),seed=int(s))["edge_test"].mean()*BP for s in rng.integers(0,1e6,50)]
print(f"\nCohort vs FIELD (copyability of wallet SELECTION, gross neut, test):")
print(f"  field all-taker test neut = {field_te:+.2f}bp")
print(f"  random field wallets (n_test>=20, matched size) test neut = {np.mean(samp):+.2f}bp [{np.percentile(samp,2.5):+.2f},{np.percentile(samp,97.5):+.2f}]")
print(f"  cohort (n_train>=300) test neut = {coh_te:+.2f}bp  -> premium over random active wallet = {coh_te-np.mean(samp):+.2f}bp")
