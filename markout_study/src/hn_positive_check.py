"""Do HIGH-SAMPLE, TRAIN-POSITIVE-markout wallets actually persist OOS? Direct test on the existing
train->test split (wallet_level_persistence.parquet: pooled per-wallet train n, train edge, test edge).
In-memory, tiny. edge is fractional return; *1e4 = bps."""
import numpy as np, polars as pl
from scipy import stats as st
RNG = np.random.default_rng(7)
BP = 1e4
df = pl.read_parquet("out/wallet_level_persistence.parquet")
# need a real test window to judge OOS
df = df.filter((pl.col("n_test") >= 30) & pl.col("edge").is_finite() & pl.col("edge_test").is_finite())
print(f"wallets with train n>=? and n_test>=30: {df.height}\n")

def boot_mean(x, n=3000):
    return np.percentile([RNG.choice(x, x.size, replace=True).mean() for _ in range(n)], [2.5, 97.5])

print("Q: among wallets binned by TRAIN sample size, do the TRAIN-POSITIVE ones stay positive OOS?")
print("   (field has a small positive drift, so the honest signal is train-positive MINUS train-negative)\n")
for lo, hi, lab in [(30,200,"30-200"),(200,500,"200-500"),(500,1000,"500-1000"),(1000,10**9,">=1000")]:
    b = df.filter((pl.col("n") >= lo) & (pl.col("n") < hi))
    if b.height < 20:
        print(f"  train n {lab:9s}: N={b.height} (too few)"); continue
    tr = b["edge"].to_numpy()*BP; te = b["edge_test"].to_numpy()*BP
    pos = tr > 0
    te_pos = te[pos]; te_neg = te[~pos]
    rho = st.spearmanr(tr, te).correlation
    # selected = train-positive: OOS mean test edge + CI + sign
    m = te_pos.mean(); lo_ci, hi_ci = boot_mean(te_pos)
    frac = (te_pos > 0).mean(); sp = st.binomtest(int((te_pos>0).sum()), te_pos.size, 0.5).pvalue
    diff = te_pos.mean() - te_neg.mean()   # skill net of field drift
    mde = 2.8 * te_pos.std()/np.sqrt(te_pos.size)
    print(f"  train n {lab:9s}: N={b.height:5d} ({pos.sum():4d} train-positive) | Spearman(tr,te)={rho:+.3f}")
    print(f"     train-POS wallets OOS test edge = {m:+6.1f}bp CI[{lo_ci:+.1f},{hi_ci:+.1f}] MDE={mde:.1f} | frac>0={frac:.2f} p={sp:.3f}")
    print(f"     train-pos MINUS train-neg OOS (skill net of field drift) = {diff:+6.1f}bp\n")

# The tightest cut: high-N AND train-significant (t_eff), do THOSE persist?
print("Highest-conviction cut: train n>=300 AND train t_eff>=2 (individually 'significant' in-sample):")
hi = df.filter((pl.col("n")>=300) & (pl.col("t_eff")>=2.0))
if hi.height >= 10:
    te = hi["edge_test"].to_numpy()*BP
    m = te.mean(); l,h = boot_mean(te)
    print(f"   N={hi.height} such wallets | OOS test edge = {m:+.1f}bp CI[{l:+.1f},{h:+.1f}] | frac>0={ (te>0).mean():.2f}")
    print(f"   (if these revert to ~0, that IS the winner's curse; if they stay clearly + , that's real skill)")
else:
    print(f"   only {hi.height} wallets clear n>=300 & t_eff>=2 — sign of how rare individual significance is")
