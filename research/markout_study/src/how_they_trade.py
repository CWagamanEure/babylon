"""
HOW do the persistent-skill wallets capture their edge, and why can't a copier? Characterize the top-decile
(by TRAIN neutralized edge) cohort's TEST entries:
  1. neutralized + raw markout TERM STRUCTURE across horizons — does the edge appear FAST (intraday
     mean-reversion bounce, uncopyable at lag) or build SLOW (information, copyable)?
  2. contrarian vs momentum signature — do they buy dips / sell rips (enter against the preceding move)?
  3. 15-min follower-lag decay — how much of the edge survives a copier entering 15 min late?
Answers "how are they capturing it if you can't hedge it daily away."
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1); TEST_LO = _ms(2026, 3, 1)
LAG = 15 * 60_000; PRE = 12          # preceding-1h (12x5min) move for contrarian test
HZ = [("5m", 5*60_000), ("15m", 15*60_000), ("30m", 30*60_000), ("1h", 3_600_000),
      ("2h", 2*3_600_000), ("4h", 4*3_600_000), ("12h", 12*3_600_000), ("24h", 24*3_600_000)]


def fwd(L, t, h):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + h)
    with np.errstate(all="ignore"): r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def daymean(day_arr, vals):
    d = pl.DataFrame({"d": day_arr, "v": vals}).filter(pl.col("v").is_finite()).group_by("d").agg(pl.col("v").mean())
    return dict(zip(d["d"].to_list(), d["v"].to_list()))


def main():
    lk = _load_bars()
    # --- select cohort: top decile by TRAIN neutralized 24h edge (n_train>=300, pooled majors) ---
    H24 = 24*3_600_000
    tr_rows = []
    grids = {}
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64); grids[c] = (L, bt)
        f24 = fwd(L, bt, H24); dm24 = daymean(bt // 86_400_000, f24)
        ec = pl.scan_parquet(OUT/"entries"/"part_*.parquet").filter(pl.col("coin") == c).select("wallet","b_ts","dir").collect()
        b = ec["b_ts"].to_numpy(); dd = ec["dir"].to_numpy().astype(float)
        i = np.clip(np.searchsorted(bt, b), 0, bt.size-1)
        neut = dd*(f24[i] - np.array([dm24.get(k, np.nan) for k in (b//86_400_000)]))
        tr_rows.append(ec.with_columns(pl.Series("neut", neut), pl.Series("coin", [c]*ec.height)))
    A = pl.concat(tr_rows)
    tr = A.filter(pl.col("b_ts") < TRAIN_HI).filter(pl.col("neut").is_finite())
    w = tr.group_by("wallet").agg(n=pl.len(), tn=pl.col("neut").mean()).filter(pl.col("n") >= 300)
    thr = w["tn"].quantile(0.90)
    cohort = set(w.filter(pl.col("tn") >= thr)["wallet"].to_list())
    print(f"cohort = top-decile TRAIN-neut wallets: {len(cohort)} (of {w.height} with n_train>=300)\n")

    # --- term structure on TEST entries: cohort vs field ---
    print(f"{'horizon':8s} | {'RAW cohort':>11s} {'RAW field':>10s} | {'NEUT cohort':>12s} {'NEUT field':>11s} | {'NEUT@lag15m':>12s}")
    rows = {c: A.filter((pl.col("coin") == c) & (pl.col("b_ts") >= TEST_LO)) for c in COINS}
    # precompute per coin: b, dir, day, in-cohort mask
    pc = {}
    for c in COINS:
        e = rows[c]; b = e["b_ts"].to_numpy()
        pc[c] = (e, b, e["dir"].to_numpy().astype(float), b // 86_400_000,
                 np.array([w_ in cohort for w_ in e["wallet"].to_list()]))
    for hl, h in HZ:
        cr = fr = cn = fn = cl = 0.0; cw = fw = lw = 0
        for c in COINS:
            L, bt = grids[c]; e, b, dd, day, msk = pc[c]
            fh = fwd(L, bt, h); dm = daymean(bt // 86_400_000, fh)
            i = np.clip(np.searchsorted(bt, b), 0, bt.size-1)
            raw = dd*fh[i]; neut = dd*(fh[i] - np.array([dm.get(k, np.nan) for k in day]))
            # 15-min lagged entry, same horizon
            fl = fwd(L, b + LAG, h); neutl = dd*(fl - np.array([dm.get(k, np.nan) for k in day]))
            def acc(v, m):
                vv = v[m]; vv = vv[np.isfinite(vv)]; return vv.sum(), vv.size
            s, k = acc(raw, msk); cr += s; cw += k
            s, _ = acc(raw, ~msk); fr += s
            s, _ = acc(neut, msk); cn += s
            s, k2 = acc(neut, ~msk); fn += s; fw += k2
            s, k3 = acc(neutl, msk); cl += s; lw += k3
        print(f"{hl:8s} | {cr/cw*BP:>+10.1f} {fr/ (fw or 1)*BP:>+9.1f} | {cn/cw*BP:>+11.1f} {fn/(fw or 1)*BP:>+10.1f} | {cl/(lw or 1)*BP:>+11.1f}")

    # --- contrarian vs momentum: cohort entry dir vs preceding-1h move ---
    print()
    csum = csz = 0
    for c in COINS:
        L, bt = grids[c]; e, b, dd, day, msk = pc[c]
        cl_ = L[1]  # close
        i = np.clip(np.searchsorted(bt, b), 0, bt.size-1); j = np.clip(i-PRE, 0, bt.size-1)
        with np.errstate(all="ignore"): preret = cl_[i]/cl_[j]-1.0
        sgn = np.sign(dd)*np.sign(preret)   # +1 momentum (trade WITH prior move), -1 contrarian
        v = sgn[msk]; v = v[np.isfinite(v)]; csum += v.sum(); csz += v.size
    print(f"contrarian/momentum signature (cohort): mean sign(dir)*sign(prior-1h) = {csum/csz:+.3f}")
    print("   (negative => CONTRARIAN: they enter AGAINST the preceding move / buy dips & sell rips)")


if __name__ == "__main__":
    main()
