"""
PROSECUTE-the-positive audit of Stage E frozen v2 result.
Reproduces baseline, then runs drop-HYPE CI (both clusterings), per-coin slopes,
and the full researcher-DOF sensitivity grid. Everything from out/entries + mkcommon.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, COST_BPS
from mkcommon import _next_bar_close_vec

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]
H24 = 24 * 3_600_000
VOLWIN = 288
FLOOR = 30
SEED = 20260704
R = 5000
BP = 1e4

def _ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1)
TEST_LO = _ms(2026, 3, 1)

def _fwd24(L, t):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + H24)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r

def _keys(ts):
    dt = ts.astype("datetime64[ms]")
    return (dt.astype("datetime64[M]").astype(np.int64),
            dt.astype("datetime64[D]").astype(np.int64),
            dt.astype("datetime64[W]").astype(np.int64))

def build():
    lk = _load_bars()
    grid = {}
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        fwd = _fwd24(L, bt)
        logret = np.zeros(L[1].size); logret[1:] = np.diff(np.log(L[1]))
        rollvol = pl.Series(logret).rolling_std(VOLWIN, min_samples=VOLWIN // 2).to_numpy()
        tv = rollvol[bt < TRAIN_HI]
        thr = {50: np.nanmedian(tv), 70: np.nanpercentile(tv, 70), 80: np.nanpercentile(tv, 80)}
        mk, dk, _ = _keys(bt)
        bg = pl.DataFrame({"m": mk, "d": dk, "f": fwd}).filter(pl.col("f").is_finite())
        gm = bg.group_by("m").agg(pl.col("f").mean()).to_dict(as_series=False)
        gd = bg.group_by("d").agg(pl.col("f").mean()).to_dict(as_series=False)
        # coin-level (whole test-relevant) mean over ALL finite bars
        cmean = float(bg["f"].mean())
        grid[c] = dict(bt=bt, fwd=fwd, rollvol=rollvol, thr=thr,
                       mmean=dict(zip(gm["m"], gm["f"])), dmean=dict(zip(gd["d"], gd["f"])),
                       cmean=cmean)

    ent = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
           .filter(pl.col("coin").is_in(COINS))
           .select("wallet", "coin", "b_ts", "dir", "notl").collect())

    # TRAIN pool with hv props at 3 thresholds
    tr = ent.filter(pl.col("b_ts") < TRAIN_HI)
    prop_rows = []
    for c in COINS:
        e = tr.filter(pl.col("coin") == c)
        if e.height == 0:
            continue
        b = e["b_ts"].to_numpy(); g = grid[c]
        idx = np.clip(np.searchsorted(g["bt"], b), 0, g["bt"].size - 1)
        rv = g["rollvol"][idx]
        cols = {f"hv{p}": (rv > g["thr"][p]).astype(np.float64) for p in (50, 70, 80)}
        prop_rows.append(e.select("wallet", "coin").with_columns(**{k: pl.Series(k, v) for k, v in cols.items()}))
    trd = pl.concat(prop_rows).group_by("wallet", "coin").agg(
        n_train=pl.len(), p50=pl.col("hv50").mean(), p70=pl.col("hv70").mean(), p80=pl.col("hv80").mean())
    pool = trd.filter(pl.col("n_train") >= FLOOR)
    for p in ("p50", "p70", "p80"):
        pool = pool.with_columns(
            ((pl.col(p) - pl.col(p).mean().over("coin")) / pl.col(p).std().over("coin")).alias("z" + p))
    pool = pool.with_columns((pl.col("p50") >= pl.col("p50").quantile(0.75).over("coin")).alias("topq"))

    # TEST entries
    te = ent.filter(pl.col("b_ts") >= TEST_LO).join(
        pool.select("wallet", "coin", "zp50", "zp70", "zp80", "topq", "n_train"),
        on=["wallet", "coin"], how="inner")
    parts = []
    for c in COINS:
        e = te.filter(pl.col("coin") == c)
        if e.height == 0:
            continue
        b = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(np.float64); g = grid[c]
        idx = np.clip(np.searchsorted(g["bt"], b), 0, g["bt"].size - 1)
        raw = d * g["fwd"][idx]
        mk, dk, wk = _keys(b)
        mben = d * np.array([g["mmean"].get(k, np.nan) for k in mk])
        dben = d * np.array([g["dmean"].get(k, np.nan) for k in dk])
        cben = d * g["cmean"]
        parts.append(e.with_columns(
            pl.Series("raw", raw),
            pl.Series("neut_month", raw - mben),
            pl.Series("neut_day", raw - dben),
            pl.Series("neut_coin", raw - cben),
            pl.Series("cw", [f"{c}_{w}" for w in wk])))
    T = pl.concat(parts).filter(pl.col("raw").is_finite() & pl.col("neut_month").is_finite()
                                & pl.col("neut_coin").is_finite())
    return T

def slope_from_stats(n, Sz, Sy, Szz, Szy):
    den = Szz - Sz * Sz / n
    return (Szy - Sz * Sy / n) / den * BP if den > 0 else np.nan

def clustered_ci(T, zcol, ycol, cluster, wcol=None, R=R, seed=SEED):
    """Point est + 95% CI via block bootstrap over `cluster`. wcol=None -> equal weight per entry."""
    rng = np.random.default_rng(seed)
    z = T[zcol].to_numpy().astype(np.float64)
    y = T[ycol].to_numpy().astype(np.float64)
    w = np.ones_like(z) if wcol is None else T[wcol].to_numpy().astype(np.float64)
    # cluster codes
    codes = T[cluster].to_numpy()
    uniq, inv = np.unique(codes, return_inverse=True)
    K = uniq.size
    # per-cluster sufficient stats (weighted)
    def agg(mask_w):
        # mask_w is per-entry weight multiplier
        ww = w * mask_w
        n = np.bincount(inv, weights=ww, minlength=K)
        Sz = np.bincount(inv, weights=ww * z, minlength=K)
        Sy = np.bincount(inv, weights=ww * y, minlength=K)
        Szz = np.bincount(inv, weights=ww * z * z, minlength=K)
        Szy = np.bincount(inv, weights=ww * z * y, minlength=K)
        return n, Sz, Sy, Szz, Szy
    n, Sz, Sy, Szz, Szy = agg(np.ones_like(z))
    point = slope_from_stats(n.sum(), Sz.sum(), Sy.sum(), Szz.sum(), Szy.sum())
    boot = np.empty(R)
    for i in range(R):
        pick = rng.integers(0, K, K)
        boot[i] = slope_from_stats(n[pick].sum(), Sz[pick].sum(), Sy[pick].sum(),
                                   Szz[pick].sum(), Szy[pick].sum())
    lo, hi = np.nanpercentile(boot, [2.5, 97.5])
    return point, lo, hi

def winsor(T, ycol, pct):
    if pct is None:
        return T.with_columns(pl.col(ycol).alias("_y"))
    cap = float(np.nanpercentile(np.abs(T[ycol].to_numpy()), pct))
    return T.with_columns(pl.col(ycol).clip(-cap, cap).alias("_y"))

if __name__ == "__main__":
    import time
    t0 = time.time()
    T = build()
    comp = T.group_by("coin").agg(pl.len()).sort("coin")
    print("built in %.1fs; TEST entries=%d; coin-week clusters=%d" % (
        time.time() - t0, T.height, T["cw"].n_unique()))
    print("coin composition:", dict(zip(comp["coin"], comp["len"])))
    T.write_parquet(OUT / "prosecute_e_test.parquet")
    print("wrote out/prosecute_e_test.parquet")
