import numpy as np, polars as pl
from pathlib import Path
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP = 1e4
E = pl.read_parquet(SCR / "prosecute_entries.parquet")
tr = E.filter(pl.col("split") == "train"); te = E.filter(pl.col("split") == "test")
trs = tr.group_by("wallet").agg(n=pl.len(), edge=pl.col("neut").mean())
tes = te.group_by("wallet").agg(n_test=pl.len(), edge_test=pl.col("neut").mean())
W = trs.join(tes, on="wallet", how="inner")
print(f"{'n_tr>=':>7} {'n_te>=':>7} {'#w':>6} {'corr':>7} {'wtd_corr(notl?no)':>8}")
for nt in [30, 50, 100, 200, 300, 500, 1000]:
    for ne in [20, 30, 50]:
        s = W.filter((pl.col("n") >= nt) & (pl.col("n_test") >= ne))
        if s.height < 10: continue
        x = s["edge"].to_numpy() * BP; y = s["edge_test"].to_numpy() * BP
        r = np.corrcoef(x, y)[0, 1]
        # spearman
        from scipy.stats import spearmanr
        rs = spearmanr(x, y).statistic
        print(f"{nt:>7} {ne:>7} {s.height:>6} {r:>7.3f} spear={rs:>6.3f} meanTeEdge={y.mean():>+6.1f}bp")
