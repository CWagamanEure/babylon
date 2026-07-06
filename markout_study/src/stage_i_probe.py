"""
Pre-build POWER PROBE (independent verification of the architecture-audit verdict). Before committing to the
Stage I build, check the two load-bearing claims myself:
  (1) Is the design underpowered by construction? Measure per-burst sigma -> projected MDE vs the ~8-16bp effect.
  (2) Is the Stage-H RAW +bp mostly majors BETA? Compare RAW vs tradeable-basket-NEUTRAL burst means.
Bursts: fixed cohort, K=9 trailing consensus, greedy non-overlapping 6h blocks per (coin,dir), FIRST-TRIGGER
reference price. NEUTRAL = dir*(coin_ret - equal-weight leave-one-out majors basket over same [t,t+6h]).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, "src")
from mkcommon import _load_bars, _next_bar_close_vec

OUT = Path("out"); COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = _ms(2026, 3, 1); WIN = 30 * 60_000; H6 = 6 * 3_600_000; K = 9; BLOCK = H6


def ratio(L, t, h):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + h)
    with np.errstate(all="ignore"): r = x / e
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def main():
    cohort = set(Path("out/cohort_wallets.txt").read_text().split("\n"))
    lk = _load_bars()
    rows = []
    for c in COINS:
        L = lk[c]
        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet").filter((pl.col("coin") == c))
              .filter(pl.col("wallet").is_in(cohort)).select("b_ts", "dir").sort("b_ts").collect())
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(float)
        # trailing consensus per direction
        cons = np.zeros(b.size)
        for sgn in (1.0, -1.0):
            idx = np.where(d == sgn)[0]; tb = b[idx]
            cons[idx] = (np.arange(idx.size) - np.searchsorted(tb, tb - WIN)).astype(float)
        flag = cons >= K
        # greedy non-overlapping 6h de-dup per (coin,dir): first-trigger reference
        for sgn in (1.0, -1.0):
            ts = b[flag & (d == sgn)]
            last = -1
            for t in ts:
                if t - last < BLOCK:
                    continue
                last = t
                rc = ratio(L, np.array([t]), H6)[0]
                if not np.isfinite(rc):
                    continue
                others = [ratio(lk[o], np.array([t]), H6)[0] for o in COINS if o != c]
                others = [x for x in others if np.isfinite(x)]
                if not others:
                    continue
                bask = float(np.mean(others))
                raw = sgn * (rc - 1.0) * BP
                neut = sgn * (rc - bask) * BP
                rows.append((c, int(t), raw, neut))
    D = pl.DataFrame(rows, schema=["coin", "t", "raw", "neut"], orient="row")
    D = D.with_columns(cw=(pl.col("t") // (7 * 86_400_000)).cast(str) + "_" + pl.col("coin"))

    def rep(sub, lab):
        n = sub.height
        if n < 5:
            print(f"  {lab:16s} n={n:4d}  (too few)"); return
        for col in ("raw", "neut"):
            v = sub[col].to_numpy()
            # coin-week clustered SE
            cl = sub["cw"].to_numpy(); means = [v[cl == u].mean() for u in np.unique(cl)]
            se_iid = v.std() / np.sqrt(n)
            se_cl = np.std([v[cl == u].mean() for u in np.unique(cl)]) / np.sqrt(len(np.unique(cl)))
            mde = 2.8 * se_cl * BP / BP
            print(f"  {lab:16s} {col.upper():5s} n={n:4d} clu={len(np.unique(cl)):3d}  mean={v.mean():+7.1f}  "
                  f"sd={v.std():6.0f}  SE_iid={se_iid:5.1f} SE_clu={se_cl:5.1f}  MDE≈{2.8*se_cl:5.1f}bp")

    print("=== ALL Aug-Jun (in-sample, upper bound on N) ===")
    rep(D, "all")
    print("\n=== TEST Mar-Jun (Stage-H window) ===")
    te = D.filter(pl.col("t") >= TEST_LO)
    rep(te, "test-all")
    for c in COINS:
        rep(te.filter(pl.col("coin") == c), f"test-{c}")


if __name__ == "__main__":
    main()
