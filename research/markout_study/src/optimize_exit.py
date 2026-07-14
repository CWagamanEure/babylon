"""
Test the user's hypothesis directly: take the persistent cohort's ENTRIES and OPTIMIZE THE EXIT — can we
clear cost? Gives the idea its absolute best case:
  - a menu of 13 exit horizons; pick the best FIXED horizon (realistic).
  - an ORACLE per-trade exit: each trade exits at its own best horizon with PERFECT FORESIGHT (look-ahead
    upper bound no real rule can beat).
  - net of realistic round-trip cost (COST_BPS), and a maker-exit variant (pay only entry side).
If even the oracle can't clear cost, exit-optimization cannot rescue it.
Cohort TEST entries (OOS), dir-signed mid-to-mid markout, entry at their fill AND at a 15-min follower lag.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, "src")
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT = Path("out"); COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = _ms(2026, 3, 1); LAG = 15 * 60_000
HZ = [("15m",15),("30m",30),("45m",45),("1h",60),("90m",90),("2h",120),("3h",180),
      ("4h",240),("6h",360),("8h",480),("12h",720),("18h",1080),("24h",1440)]
HMS = [m*60_000 for _, m in HZ]


def fwd(L, t, h):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + h)
    with np.errstate(all="ignore"): r = x/e - 1.0
    r[~(np.isfinite(e)&(e>0)&np.isfinite(x)&(x>0))] = np.nan
    return r


def main():
    cohort = set(Path("out/cohort_wallets.txt").read_text().split("\n"))
    lk = _load_bars()
    # per-trade markout matrix M[trade, horizon] (dir-signed), for entry-at-fill and lagged entry
    M = {"fill": [], "lag": []}; costs = []
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        ec = (pl.scan_parquet(OUT/"entries"/"part_*.parquet").filter((pl.col("coin")==c) & (pl.col("b_ts")>=TEST_LO))
              .filter(pl.col("wallet").is_in(cohort)).select("b_ts","dir").collect())
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(float)
        for key, t0 in [("fill", b), ("lag", b + LAG)]:
            cols = [d * fwd(L, t0, h) for h in HMS]
            M[key].append(np.column_stack(cols))
        costs.append(np.full(b.size, COST_BPS[c]))
    cost = np.concatenate(costs)
    for key in ("fill", "lag"):
        A = np.vstack(M[key]) * BP                                  # trades x horizons, in bp
        fin = np.isfinite(A).all(axis=1)                            # keep trades priceable at all horizons
        A = A[fin]; cst = cost[fin]
        colmean = np.nanmean(A, axis=0)
        print(f"\n=== entry = {key.upper()} ({'their fill' if key=='fill' else '15-min follower lag'})  ·  N={A.shape[0]:,} ===")
        print("  gross mid->mid markout by exit horizon (bp):")
        print("   " + "  ".join(f"{hl}:{m:+.1f}" for (hl,_),m in zip(HZ, colmean)))
        h_star = int(np.argmax(colmean))
        gross_best = colmean[h_star]
        # net at best fixed horizon: full round-trip cost, and maker-exit (half cost)
        net_full = gross_best - cst.mean()
        net_maker = gross_best - cst.mean()/2
        print(f"  BEST FIXED horizon = {HZ[h_star][0]}:  gross {gross_best:+.1f}  |  net(full cost {cst.mean():.1f}) "
              f"{net_full:+.1f}  |  net(maker-exit, half cost) {net_maker:+.1f}")
        # ORACLE per-trade exit (perfect foresight = max over horizons for each trade)
        oracle = np.nanmax(A, axis=1).mean()
        print(f"  ORACLE per-trade exit (look-ahead ceiling): gross {oracle:+.1f}  |  net(full) {oracle-cst.mean():+.1f} "
              f" |  net(maker) {oracle-cst.mean()/2:+.1f}")
        # fraction of trades whose ORACLE best even exceeds cost
        print(f"  trades whose PERFECT exit still beats round-trip cost: {100*np.mean(np.nanmax(A,axis=1)>cst):.0f}%")


if __name__ == "__main__":
    main()
