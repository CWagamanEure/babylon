"""
PHASE 2 — freeze the nested forward models on TRAINING DATA ONLY (no test/forward data touched).
Target y = signed 8h forward COIN return (bp) from next-bar entry (the tradeable quantity the rule acts on; sign -> long/short).
M0 (market-state only): signed trailing returns 1/2/4/8/24h, |8h move|, vol 2h/8h, distance from 24h high/low, acceleration,
    funding, coin dummies, time-of-day (sin/cos). NO wallet identity/activity/direction.
M1 (market-state + wallet): identical market block PLUS recurring-cohort indicator, frozen train conviction rank, wallet
    direction, log trade size, position-building. M1 NESTS M0.
Ridge; alpha chosen by month-block cross-fit (GroupKFold on train month) maximizing CV rank-IC; then refit on all train and
FREEZE (coefficients + standardization + alpha) to out/cohort_P2_models.npz. Report IN-TRAIN cross-fit IC only — the frozen
models are NOT evaluated on the historical test window (that is the forward experiment's job). One heavy pricing pass. RAM-safe.
"""
import sys
from pathlib import Path
import numpy as np, polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; H8 = 28800_000; COINS = ["BTC", "ETH", "SOL", "HYPE"]; TRAIN_HI = 1_769_904_000_000; W24 = 288
LB = {"1h": 3600_000, "2h": 7200_000, "4h": 14400_000, "8h": 28800_000, "24h": 86400_000}
RNG = np.random.default_rng(0); FUND = "/Users/corywagamaneure/bablyon/scratch_conv/mlscreen/funding.parquet"

frz = pl.read_parquet("out/cohort_M_frozen.parquet").select("wallet", "conv", "n_top",
        rec=(pl.col("cohort") != pl.lit("none")).cast(pl.Int8))
df = (pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "notl")
        .filter(pl.col("b_ts") < TRAIN_HI).join(frz, on="wallet", how="left")
        .with_columns(conv=pl.col("conv").fill_null(0.0), rec=pl.col("rec").fill_null(0)))
lookups = mk._load_bars()
try: fund = pl.read_parquet(FUND)
except Exception: fund = None
# cap ordinary rows for tractable fit; keep ALL recurring
rec_df = df.filter(pl.col("rec") == 1); ord_df = df.filter(pl.col("rec") == 0)
if ord_df.height > 160000: ord_df = ord_df.sample(160000, seed=0)
D = pl.concat([rec_df, ord_df])
print(f"train fit rows: {D.height} ({rec_df.height} recurring + {ord_df.height} ordinary) | funding={'yes' if fund is not None else 'NO'}", flush=True)

def coin_arrays(coin):
    lk = lookups[coin]; bt = np.asarray(lk[0]); cl = np.asarray(lk[1])
    import pandas as pd
    s = pd.Series(cl); rmax = s.rolling(W24, min_periods=1).max().to_numpy(); rmin = s.rolling(W24, min_periods=1).min().to_numpy()
    lr = np.diff(np.log(cl), prepend=np.log(cl[0])); c2 = np.cumsum(lr ** 2); c1 = np.cumsum(lr)
    def rv(k, w):
        k0 = np.maximum(k - w, 0); n = k - k0 + 1
        s2 = c2[k] - np.where(k0 > 0, c2[k0 - 1], 0.0); s1 = c1[k] - np.where(k0 > 0, c1[k0 - 1], 0.0)
        return np.sqrt(np.maximum(s2 / n - (s1 / n) ** 2, 0.0))
    fr = None
    if fund is not None:
        fc = fund.filter(pl.col("coin") == coin).sort("time")
        if fc.height: fr = (fc["rate"].to_numpy(), fc["time"].to_numpy())
    return lk, bt, cl, rmax, rmin, rv, fr

MKT = ["sret_1h","sret_2h","sret_4h","sret_8h","sret_24h","amove_8h","vol_2h","vol_8h","dist_hi","dist_lo","accel","funding",
       "isBTC","isETH","isSOL","tod_sin","tod_cos"]
WAL = ["rec","conv","wdir","logsz","posbuild"]
def build(coin, sub):
    lk, bt, cl, rmax, rmin, rv, fr = CA[coin]
    ts = sub["b_ts"].to_numpy(); d = sub["dir"].to_numpy().astype(float); notl = sub["notl"].to_numpy()
    ent = mk._next_bar_close_vec(lk, ts); ex = mk._next_bar_close_vec(lk, ts + H8); k = np.clip(np.searchsorted(bt, ts), 0, len(cl)-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        y = (ex / ent - 1.0) * BP
        f = {}
        for nm, h in LB.items(): f[f"sret_{nm}"] = (ent / mk._next_bar_close_vec(lk, ts - h) - 1.0) * BP
        f["amove_8h"] = np.abs(f["sret_8h"])
        f["vol_2h"] = rv(k, 24) * BP; f["vol_8h"] = rv(k, 96) * BP
        f["dist_hi"] = (ent / rmax[k] - 1.0) * BP; f["dist_lo"] = (ent / rmin[k] - 1.0) * BP
        r1 = f["sret_1h"]; r2 = f["sret_2h"]; f["accel"] = 2 * r1 - r2
        f["funding"] = (fr[0][np.clip(np.searchsorted(fr[1], ts) - 1, 0, len(fr[0])-1)] * BP) if fr is not None else np.zeros_like(ent)
        f["isBTC"] = np.full_like(ent, coin == "BTC"); f["isETH"] = np.full_like(ent, coin == "ETH"); f["isSOL"] = np.full_like(ent, coin == "SOL")
        tod = (ts // 3600_000) % 24; f["tod_sin"] = np.sin(2*np.pi*tod/24); f["tod_cos"] = np.cos(2*np.pi*tod/24)
        f["rec"] = sub["rec"].to_numpy().astype(float); f["conv"] = sub["conv"].to_numpy()
        f["wdir"] = d; f["logsz"] = np.log1p(notl); f["posbuild"] = np.zeros_like(ent)   # posbuild filled below
    month = (ts // 86_400_000 // 30)
    return y, f, month

CA = {c: coin_arrays(c) for c in COINS}
# position-building proxy per wallet-coin-day
pb = df.with_columns(day=(pl.col("b_ts")//86_400_000)).group_by("wallet","coin","day").agg(pbc=pl.len())
D = D.with_columns(day=(pl.col("b_ts")//86_400_000)).join(pb, on=["wallet","coin","day"], how="left")
ys, fs, mos = [], {k: [] for k in MKT+WAL}, []
for coin in COINS:
    sub = D.filter(pl.col("coin") == coin)
    y, f, month = build(coin, sub); f["posbuild"] = sub["pbc"].to_numpy().astype(float)
    ok = np.isfinite(y)
    for kk in MKT+WAL: v = f[kk]; ok &= np.isfinite(v)
    ys.append(y[ok]); mos.append(month[ok])
    for kk in MKT+WAL: fs[kk].append(f[kk][ok])
y = np.concatenate(ys); month = np.concatenate(mos)
X0 = np.column_stack([np.concatenate(fs[k]) for k in MKT])
X1 = np.column_stack([np.concatenate(fs[k]) for k in MKT+WAL])
print(f"assembled {len(y)} rows | M0 dims {X0.shape[1]} | M1 dims {X1.shape[1]}", flush=True)

def standardize(X): mu = X.mean(0); sd = X.std(0); sd[sd == 0] = 1; return (X - mu)/sd, mu, sd
def ridge_fit(Xs, yy, a): return np.linalg.solve(Xs.T@Xs + a*np.eye(Xs.shape[1]), Xs.T@yy)
def ic(pred, yy):
    from scipy.stats import spearmanr; r = spearmanr(pred, yy)[0]; return r if np.isfinite(r) else 0.0
def cvfit(X, yy, groups, name):
    Xs, mu, sd = standardize(X); ug = np.unique(groups); best = (None, -9)
    for a in [1, 10, 100, 300, 1000, 3000, 10000]:
        ics = []
        for g in ug:                                              # month-block cross-fit
            tr = groups != g; te = groups == g
            if te.sum() < 50 or tr.sum() < 100: continue
            b = ridge_fit(Xs[tr], yy[tr], a); ics.append(ic(Xs[te]@b, yy[te]))
        m = np.mean(ics) if ics else -9
        if m > best[1]: best = (a, m)
    a = best[0]; beta = ridge_fit(Xs, yy, a)                       # refit on ALL train, freeze
    print(f"  {name}: frozen alpha={a} | month-block CV rank-IC = {best[1]:+.4f} ({len(np.unique(groups))} folds)")
    return dict(beta=beta, mu=mu, sd=sd, alpha=a, cvic=best[1], feats=(MKT if name=="M0" else MKT+WAL))
print("cross-fit (month-block) to choose complexity, then FREEZE:")
m0 = cvfit(X0, y, month, "M0"); m1 = cvfit(X1, y, month, "M1")
print(f"\n  incremental in-train CV IC (M1 - M0) = {m1['cvic']-m0['cvic']:+.4f}  (in-sample-CV ONLY; NOT confirmatory — forward decides)")
np.savez("out/cohort_P2_models.npz",
         m0_beta=m0["beta"], m0_mu=m0["mu"], m0_sd=m0["sd"], m0_alpha=m0["alpha"], m0_feats=np.array(MKT),
         m1_beta=m1["beta"], m1_mu=m1["mu"], m1_sd=m1["sd"], m1_alpha=m1["alpha"], m1_feats=np.array(MKT+WAL))
print("FROZEN -> out/cohort_P2_models.npz | market-only M0 and market+wallet M1, standardization + ridge alpha frozen from TRAIN.")
print("NOTE: these frozen models are deliberately NOT scored on the historical test window; Phase-3 forward data is the sole confirmatory evaluation.")
