"""Part I heavy pass: (a) event-study signed price response around entries (per coin, day-block CI);
(b) per-entry trailing-move + realized-vol features for conditional-markout figures. One bar-pricing pass. RAM-safe."""
import sys, json; from pathlib import Path
import numpy as np, polars as pl, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; COINS = ["BTC", "ETH", "SOL", "HYPE"]; H = 3600_000
OFF_H = [-8, -6, -4, -2, -1, -0.5, 0.0, 0.5, 1, 2, 4, 8, 12, 24]     # event-study offsets in hours
OFF = [int(h * H) for h in OFF_H]; RNG = np.random.default_rng(0); NB = 2000
df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "notl", "split", "raw_1h", "raw_8h")
lookups = mk._load_bars()

def rollvol(coin, ts):
    lk = lookups[coin]; bt = np.asarray(lk[0]); cl = np.asarray(lk[1])
    lr = np.diff(np.log(cl), prepend=np.log(cl[0])); c2 = np.cumsum(lr**2); c1 = np.cumsum(lr)
    k = np.clip(np.searchsorted(bt, ts), 0, len(cl)-1); k0 = np.maximum(k-24, 0); n = k-k0+1
    s2 = c2[k]-np.where(k0>0, c2[k0-1], 0.0); s1 = c1[k]-np.where(k0>0, c1[k0-1], 0.0)
    return np.sqrt(np.maximum(s2/n-(s1/n)**2, 0.0))*BP

es = {}; feat_rows = []
for coin in COINS:
    e = df.filter(pl.col("coin") == coin); lk = lookups[coin]
    ts = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float); day = (ts // 86_400_000)
    ent0 = mk._next_bar_close_vec(lk, ts)
    with np.errstate(invalid="ignore", divide="ignore"):
        # event-study matrix: signed return in trade dir from entry pricepoint to entry+offset
        R = np.column_stack([d * (mk._next_bar_close_vec(lk, ts + o) / ent0 - 1.0) * BP for o in OFF])
        # trailing signed returns (dir-adjusted) and abs move
        tr1 = d * (ent0 / mk._next_bar_close_vec(lk, ts - H) - 1.0) * BP
        tr4 = d * (ent0 / mk._next_bar_close_vec(lk, ts - 4*H) - 1.0) * BP
        tr8 = d * (ent0 / mk._next_bar_close_vec(lk, ts - 8*H) - 1.0) * BP
        at8 = np.abs(ent0 / mk._next_bar_close_vec(lk, ts - 8*H) - 1.0) * BP
    vol = rollvol(coin, ts)
    # trailing 24h (288-bar) high/low for direction-aligned stretch: dist below high / above low
    bt = np.asarray(lk[0]); cl = np.asarray(lk[1]); kk = np.clip(np.searchsorted(bt, ts), 0, len(cl)-1)
    rmax = pd.Series(cl).rolling(288, min_periods=1).max().to_numpy(); rmin = pd.Series(cl).rolling(288, min_periods=1).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        dist_hi = (ent0/rmax[kk] - 1.0)*BP    # <=0 : entry below trailing 24h high
        dist_lo = (ent0/rmin[kk] - 1.0)*BP    # >=0 : entry above trailing 24h low
    # --- event study: per-day mean per offset, then day-block bootstrap ---
    udays = np.unique(day); di = {int(x): i for i, x in enumerate(udays)}
    Dsum = np.zeros((len(udays), len(OFF))); Dcnt = np.zeros((len(udays), len(OFF)))
    dayidx = np.array([di[int(x)] for x in day])
    for j in range(len(OFF)):
        col = R[:, j]; m = np.isfinite(col)
        np.add.at(Dsum[:, j], dayidx[m], col[m]); np.add.at(Dcnt[:, j], dayidx[m], 1.0)
    Dmean = np.where(Dcnt > 0, Dsum / np.maximum(Dcnt, 1), np.nan); nd = len(udays)
    out = {}
    for j, oh in enumerate(OFF_H):
        w = Dcnt[:, j]; v = Dmean[:, j]; ok = np.isfinite(v) & (w > 0)
        pt = np.average(v[ok], weights=w[ok]) if ok.any() else np.nan
        bs = np.empty(NB)
        for b in range(NB):
            idx = RNG.integers(0, nd, nd); vv = Dmean[idx, j]; ww = Dcnt[idx, j]; k = np.isfinite(vv) & (ww > 0)
            bs[b] = np.average(vv[k], weights=ww[k]) if k.any() else np.nan
        out[str(oh)] = [float(pt), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))]
    es[coin] = out
    # --- save per-entry features ---
    fe = e.with_columns(trail_1h=pl.Series(tr1), trail_4h=pl.Series(tr4), trail_8h=pl.Series(tr8),
                        atrail8=pl.Series(at8), vol2h=pl.Series(vol),
                        dist_hi=pl.Series(dist_hi), dist_lo=pl.Series(dist_lo))
    feat_rows.append(fe)
    print(f"{coin}: {e.height} entries priced | ES offsets {len(OFF)}", flush=True)

json.dump({"offsets_h": OFF_H, "coins": es}, open("out/eventstudy.json", "w"))
pl.concat(feat_rows).write_parquet("out/entry_features.parquet")
print("saved out/eventstudy.json, out/entry_features.parquet")
for c in COINS:
    print(f"  {c} ES: 0h {es[c]['0.0'][0]:+.1f}  +1h {es[c]['1'][0]:+.1f}  +8h {es[c]['8'][0]:+.1f}  -8h {es[c]['-8'][0]:+.1f}")
