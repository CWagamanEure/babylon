"""
Analyze out/maker_taker_split.parquet (from maker_taker_split.py):
  - taker_share (size-wtd, TRAIN) distribution
  - anomaly wallets: mkshare_v, trF vs trT, teF vs teT
  - persistence Spearman on TAKER-ONLY ledger (trT_vw vs teT_vw) vs FULL ledger (trF_vw vs teF_vw)
  - train-t>=3 selection -> OOS on taker-only
"""
import numpy as np
import polars as pl
from scipy.stats import spearmanr

R = pl.read_parquet("out/maker_taker_split.parquet")
print(f"rows: {R.height}")
print(R.describe())

ANOM = ['0x0ddf9bae2af4b874b96d287a5ad42eb47138a902','0x5fffee2555a15899ad656c1a80f1b35cd0b2c0c1',
        '0xb28cf8649d1cda2975d290f04ea4cc4db7b3828e','0x00c511ab1b583f4efab3608d0897d377c4de47a6',
        '0x95995f302ad58138d791ce49f9f3b1274e80c60a','0xff4cd3826ecee12acd4329aada4a2d3419fc463c',
        '0xb676a78f19227ffe9a97db93263fce675e547dbf','0xe056eebc2c7acfc782d47ebe18ad71735480f72a']

print("\n=== ANOMALY WALLETS: maker share + full vs taker-only ledger ===")
sub = R.filter(pl.col("wallet").is_in(ANOM))
with pl.Config(tbl_cols=30, tbl_rows=20, fmt_str_lengths=14):
    print(sub.select("wallet","trN","mkshare_n","mkshare_v",
                      "ntrF","trF_vw","trF_t","nteF","teF_vw","teF_t",
                      "ntrT","trT_vw","trT_t","nteT","teT_vw","teT_t"))

print("\n=== taker_share (mkshare_v) distribution over full universe ===")
print(R.select(pl.col("mkshare_v").describe()))
tk_share = 1 - R["mkshare_v"].to_numpy()
print(f"median TAKER share (value-wtd): {np.nanmedian(tk_share):.3f}")
print(f"mean   TAKER share (value-wtd): {np.nanmean(tk_share):.3f}")
print(f"frac wallets >50% taker: {np.nanmean(tk_share>0.5):.3f}")
print(f"frac wallets >80% taker: {np.nanmean(tk_share>0.8):.3f}")
print(f"frac wallets <20% taker (i.e. mostly MAKER): {np.nanmean(tk_share<0.2):.3f}")

def sp(a,b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10: return np.nan, m.sum()
    return spearmanr(a[m], b[m]).correlation, m.sum()

print("\n=== PERSISTENCE: FULL ledger (all fills) ===")
xf = R["trF_vw"].to_numpy(); yf = R["teF_vw"].to_numpy()
rho_f, n_f = sp(xf, yf)
print(f"Spearman(trF_vw, teF_vw) = {rho_f:+.3f}  (N={n_f})")

print("\n=== PERSISTENCE: TAKER-ONLY ledger (crossed=True fills only) ===")
xt = R["trT_vw"].to_numpy(); yt = R["teT_vw"].to_numpy()
rho_t, n_t = sp(xt, yt)
print(f"Spearman(trT_vw, teT_vw) = {rho_t:+.3f}  (N={n_t})")

# restrict to wallets with sufficient taker-only sample (>=20 both windows, done in stats() already via NaN)
ntrT = R["ntrT"].to_numpy(); nteT = R["nteT"].to_numpy()
mask_suff = (ntrT >= 20) & (nteT >= 20)
print(f"\nwallets with >=20 taker-only closes both windows: {mask_suff.sum()} / {R.height}")

print("\n=== train-t>=3 selection on TAKER-ONLY ledger -> OOS taker-only vw ===")
trT_t = R["trT_t"].to_numpy()
sel = (trT_t >= 3) & np.isfinite(trT_t) & np.isfinite(yt)
print(f"n selected (trT_t>=3): {sel.sum()}")
if sel.sum() >= 5:
    tv = yt[sel]
    rng = np.random.default_rng(0)
    bs = np.array([rng.choice(tv, tv.size).mean() for _ in range(5000)])
    print(f"OOS taker-only $-vw: {np.nanmean(tv):+.2f}  95%CI [{np.nanpercentile(bs,2.5):+.2f}, {np.nanpercentile(bs,97.5):+.2f}]")

print("\n=== SAME selection (train-t>=3 on FULL ledger) -> compare FULL-OOS vs TAKER-ONLY-OOS ===")
trF_t = R["trF_t"].to_numpy()
selF = (trF_t >= 3) & np.isfinite(trF_t)
print(f"n selected (trF_t>=3): {selF.sum()}")
if selF.sum() >= 5:
    tv_full = yf[selF]
    tv_tk = yt[selF]
    print(f"  FULL-ledger OOS vw (te F):   {np.nanmean(tv_full):+.2f}  (n_finite={np.isfinite(tv_full).sum()})")
    print(f"  TAKER-ONLY OOS vw (te T) for SAME wallets: {np.nanmean(tv_tk):+.2f}  (n_finite={np.isfinite(tv_tk).sum()})")

print("\n=== maker-share correlate: does high maker-share explain the sign flip? ===")
mkshare = R["mkshare_v"].to_numpy()
# correlation of maker share with (trF_vw - trT_vw) sign difference
diff = np.sign(xf) != np.sign(xt)
m2 = np.isfinite(xf) & np.isfinite(xt)
print(f"fraction of wallets where sign(trF_vw) != sign(trT_vw): {np.nanmean(diff[m2]):.3f}  (n={m2.sum()})")
# bucket by maker share
R2 = R.with_columns(mk_bucket=pl.when(pl.col("mkshare_v")<0.2).then(pl.lit("mostly-taker(<20% mk)"))
                     .when(pl.col("mkshare_v")<0.5).then(pl.lit("mixed(20-50% mk)"))
                     .when(pl.col("mkshare_v")<0.8).then(pl.lit("mixed(50-80% mk)"))
                     .otherwise(pl.lit("mostly-maker(>80% mk)")))
for lab, g in R2.group_by("mk_bucket"):
    xf_ = g["trF_vw"].to_numpy(); yf_ = g["teF_vw"].to_numpy()
    xt_ = g["trT_vw"].to_numpy(); yt_ = g["teT_vw"].to_numpy()
    rf,_ = sp(xf_,yf_); rt,_ = sp(xt_,yt_)
    print(f"  {lab[0]:26s} n={g.height:5d}  full-Spearman={rf:+.3f}  taker-only-Spearman={rt:+.3f}  mean trF_vw={np.nanmean(xf_):+.2f} mean trT_vw={np.nanmean(xt_):+.2f}")
