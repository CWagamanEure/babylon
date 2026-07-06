"""
Decisive read of Stage-J Job 1: does TAKER-ONLY realized round-trip persistence turn positive in the
LOW-maker-share stratum, while the mixed/high-maker pool stays flat? (the mixture hypothesis).
In-memory on out/maker_taker_split.parquet (1MB) — no tape, RAM-trivial.

Per CLAUDE.md gate: point estimate + CI + MDE + cross-unit (sign) — not a p-value verdict.
"""
import numpy as np, polars as pl
from scipy import stats as st

RNG = np.random.default_rng(12345)
df = pl.read_parquet("out/maker_taker_split.parquet")
print(f"universe: {df.height} wallets (>=2000 train majors fills)\n")

def boot_spearman(x, y, n=2000):
    """wallet-bootstrap CI for spearman rho."""
    idx = np.arange(x.size)
    rs = np.empty(n)
    for i in range(n):
        s = RNG.choice(idx, idx.size, replace=True)
        rs[i] = st.spearmanr(x[s], y[s]).correlation
    return np.nanpercentile(rs, [2.5, 97.5])

def analyze(sub, label):
    # taker-only train->test edge, both finite, min counts (stats floor was 20)
    m = (sub["ntrT"] >= 20) & (sub["nteT"] >= 20) & sub["trT_vw"].is_finite() & sub["teT_vw"].is_finite()
    s = sub.filter(m)
    n = s.height
    if n < 30:
        print(f"  {label:28s} N={n:5d}  (too few for a powered read)")
        return
    tr = s["trT_vw"].to_numpy(); te = s["teT_vw"].to_numpy()
    trt = s["trT_t"].to_numpy()
    rho = st.spearmanr(tr, te).correlation
    lo, hi = boot_spearman(tr, te)
    mde_rho = 1.96 / np.sqrt(n)                      # ~MDE on a zero-centered spearman
    # top-quartile train cohort (rank by taker t-stat) -> OOS taker vw edge
    q = np.nanpercentile(trt, 75)
    topmask = trt >= q
    top_te = te[topmask]
    top_mean = top_te.mean()
    # wallet-bootstrap CI on the top-quartile OOS mean
    bm = np.array([RNG.choice(top_te, top_te.size, replace=True).mean() for _ in range(2000)])
    tlo, thi = np.percentile(bm, [2.5, 97.5])
    mde_edge = 2.8 * top_te.std() / np.sqrt(top_te.size)
    # cross-wallet sign test: of top-quartile, fraction OOS-positive vs 0.5
    pos = int((top_te > 0).sum()); ntop = top_te.size
    sign_p = st.binomtest(pos, ntop, 0.5).pvalue
    print(f"  {label:28s} N={n:5d} | Spearman(trT,teT)={rho:+.3f} CI[{lo:+.3f},{hi:+.3f}] MDE~{mde_rho:.3f}")
    print(f"  {'':28s}         | top-q OOS taker edge={top_mean:+7.1f}bp CI[{tlo:+.0f},{thi:+.0f}] MDE={mde_edge:.0f}bp | sign {pos}/{ntop} p={sign_p:.3f}")

# ---- maker-share distribution ----
mv = df["mkshare_v"].drop_nulls().to_numpy()
mv = mv[np.isfinite(mv)]
print("mkshare_v (notional maker share) distribution:")
for p in [10,25,50,75,90]:
    print(f"   p{p:02d} = {np.percentile(mv,p):.3f}", end="")
print(f"\n   share >0.5 maker: {(mv>0.5).mean():.1%}   share <0.2 (taker-dominant): {(mv<0.2).mean():.1%}\n")

# ---- full-ledger vs taker-only, pooled ----
print("POOLED (all wallets):")
# full ledger for comparison
mf = (df["ntrF"] >= 20) & (df["nteF"] >= 20) & df["trF_vw"].is_finite() & df["teF_vw"].is_finite()
sf = df.filter(mf)
rf = st.spearmanr(sf["trF_vw"].to_numpy(), sf["teF_vw"].to_numpy()).correlation
print(f"  FULL-ledger  Spearman(trF,teF)={rf:+.3f}  N={sf.height}  (the contaminated mixture number)")
analyze(df, "TAKER-only pooled")

# ---- stratified by maker-share ----
print("\nTAKER-only persistence STRATIFIED by notional maker-share:")
buckets = [("mkshare<0.2 (pure taker)", 0.0, 0.2), ("0.2-0.5", 0.2, 0.5),
           ("0.5-0.8", 0.5, 0.8), (">0.8 (maker-heavy)", 0.8, 1.01)]
for lab, a, b in buckets:
    sub = df.filter((df["mkshare_v"] >= a) & (df["mkshare_v"] < b))
    analyze(sub, lab)

# ---- maker-vs-taker closing PnL: is the full-ledger drag from maker-closing wallets? ----
print("\nMaker- vs taker-closing realized PnL (TEST window, notional-wtd bps):")
d = df.with_columns([
    (pl.col("teMkR") / pl.when(pl.col("teMkN")>0).then(pl.col("teMkN")).otherwise(None) * 1e4).alias("te_mk_bps"),
    (pl.col("teTkR") / pl.when(pl.col("teTkN")>0).then(pl.col("teTkN")).otherwise(None) * 1e4).alias("te_tk_bps"),
])
for lab, a, b in [("high-maker >0.5",0.5,1.01),("low-maker <0.2",0.0,0.2)]:
    sub = d.filter((d["mkshare_v"]>=a)&(d["mkshare_v"]<b))
    mk = sub["te_mk_bps"].drop_nulls().to_numpy(); tk = sub["te_tk_bps"].drop_nulls().to_numpy()
    mk=mk[np.isfinite(mk)]; tk=tk[np.isfinite(tk)]
    if mk.size: print(f"  {lab:18s} maker-closing median={np.median(mk):+6.1f}bp (n={mk.size})  taker-closing median={np.median(tk):+6.1f}bp (n={tk.size})")
