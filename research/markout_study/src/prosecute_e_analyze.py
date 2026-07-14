import sys
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prosecute_e import clustered_ci, winsor, slope_from_stats, BP
from mkcommon import COST_BPS

OUT = Path(__file__).resolve().parents[1] / "out"
T = pl.read_parquet(OUT / "prosecute_e_test.parquet")

def run(T, zcol="zp50", ycol="neut_month", winsor_pct=99, cluster="cw", wcol=None, label=""):
    Tw = winsor(T, ycol, winsor_pct)
    p, lo, hi = clustered_ci(Tw, zcol, "_y", cluster, wcol=wcol)
    sig = "EXCL0" if lo > 0 else ("spans0" if hi > 0 else "NEG")
    print(f"{label:52s} slope={p:+6.2f}  CI[{lo:+6.2f},{hi:+6.2f}]  {sig}")
    return p, lo, hi

print("="*95)
print("BASELINE REPRODUCTION (zp50, neut_month, winsor p99, coin-week cluster)")
print("="*95)
run(T, label="baseline coin-week")
run(T, cluster="wallet", label="baseline wallet-clustered")

print("\n" + "="*95)
print("PROSECUTE 1 — DROP HYPE (decisive)")
print("="*95)
Tnh = T.filter(pl.col("coin") != "HYPE")
run(Tnh, label="drop-HYPE coin-week")
run(Tnh, cluster="wallet", label="drop-HYPE wallet-clustered")

print("\nper-coin slopes (winsor p99 within pooled, coin-week CI):")
for c in ["BTC","ETH","SOL","HYPE"]:
    run(T.filter(pl.col("coin")==c), label=f"  {c} only")

print("\n" + "="*95)
print("PROSECUTE 2 — RESEARCHER-DOF SENSITIVITY (pooled, coin-week CI)")
print("="*95)
print("-- (a)/(b) winsorization --")
for w,lb in [(None,"no winsor"),(95,"winsor p95"),(99,"winsor p99 (frozen)"),(99.5,"winsor p99.5")]:
    run(T, winsor_pct=w, label=f"  {lb}")
print("-- (c)/(d) neutralization grain --")
for y,lb in [("raw","raw (no neut)"),("neut_coin","coin-level neut"),
             ("neut_month","coin-month (frozen)"),("neut_day","coin-day neut")]:
    run(T, ycol=y, label=f"  {lb}")
print("-- (e) selector vol-threshold (defines high-vol regime) --")
for z,lb in [("zp50","p50/median (frozen)"),("zp70","p70"),("zp80","p80")]:
    run(T, zcol=z, label=f"  vol-thresh {lb}")
print("-- (f) weighting --")
run(T, wcol=None, label="  equal-weight per entry (frozen)")
run(T, wcol="notl", label="  notional-weighted (vw)")

print("\n" + "="*95)
print("DROP-HYPE UNDER DOF (does it EVER exclude 0 without HYPE?)")
print("="*95)
for y,lb in [("raw","raw"),("neut_coin","coin-neut"),("neut_month","month-neut"),("neut_day","day-neut")]:
    run(Tnh, ycol=y, label=f"  drop-HYPE {lb}")
for z,lb in [("zp70","p70"),("zp80","p80")]:
    run(Tnh, zcol=z, label=f"  drop-HYPE vol-thresh {lb}")

print("\n" + "="*95)
print("DEPLOYABLE top-quartile RAW markout (per coin & pooled, drop-HYPE)")
print("="*95)
def qmean(T, col):
    q = T.filter(pl.col("topq"))
    return float(q[col].mean())*BP, q.height
for c in ["BTC","ETH","SOL","HYPE"]:
    m,n = qmean(T.filter(pl.col("coin")==c),"raw")
    print(f"  {c:5s} topq raw={m:+6.1f}bp  n={n:7d}  hurdle={COST_BPS[c]:.0f}")
m,n = qmean(T,"raw"); print(f"  POOL  topq raw={m:+6.1f}bp  n={n}")
m,n = qmean(Tnh,"raw"); print(f"  POOL-noHYPE topq raw={m:+6.1f}bp  n={n}")
