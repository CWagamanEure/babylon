"""
SIGNIFICANCE of the consensus>=9 signal under non-independence + generic-crowding placebo.

Reuses the EXACT consensus definition from conditional_copy2.py (trailing-only same-dir count in
(t-30min, t]) and the leak-free 6h markout via _next_bar_close_vec. TEST = b_ts>=2026-03-01.
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
TEST_LO = _ms(2026, 3, 1); WIN = 30 * 60_000; H6 = 6 * 3_600_000
DAY = 86_400_000; WEEK = 7 * DAY


def fwd(L, t, h):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + h)
    with np.errstate(all="ignore"): r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def build_table(cohort, lk, lo=TEST_LO, hi=None):
    """Per-entry TEST table with consensus count (distinct-wallet, trailing 30min same-dir), 6h markout, cost."""
    parts = []
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        q = pl.scan_parquet(OUT / "entries" / "part_*.parquet").filter(
            (pl.col("coin") == c) & pl.col("wallet").is_in(list(cohort)))
        if hi: q = q.filter(pl.col("b_ts") < hi)
        if lo: q = q.filter(pl.col("b_ts") >= lo)
        ec = q.select("wallet", "b_ts", "dir").sort("b_ts").collect()
        if ec.height == 0:
            continue
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(float)
        w = ec["wallet"].to_numpy()
        mk6 = d * fwd(L, b, H6) * BP
        # consensus (conditional_copy2 def): count of EARLIER same-dir cohort ENTRIES in (t-WIN, t)
        cons = np.zeros(b.size)         # entry-count, excl self
        consd = np.zeros(b.size)        # distinct-wallet count incl self
        for sgn in (1.0, -1.0):
            idx = np.where(d == sgn)[0]
            tb = b[idx]; wb = w[idx]; pos = np.arange(idx.size)
            cons[idx] = (pos - np.searchsorted(tb, tb - WIN)).astype(float)
            for k in range(idx.size):
                lo_i = np.searchsorted(tb, tb[k] - WIN, side="left")
                consd[idx[k]] = len(set(wb[lo_i:k + 1]))
        parts.append(pl.DataFrame({
            "coin": [c] * b.size, "wallet": w, "b_ts": b, "dir": d.astype(int),
            "mk6": mk6, "cons": cons, "consd": consd, "cost": np.full(b.size, COST_BPS[c]),
            "day": b // DAY, "week": b // WEEK}))
    return pl.concat(parts)


def net_subset(df, mask, label=None):
    s = df.filter(mask)
    v = s["mk6"].to_numpy(); ok = np.isfinite(v)
    gross = v[ok].mean(); cost = s["cost"].to_numpy()[ok].mean()
    net = gross - cost
    if label is not None:
        print(f"  {label:32s} n={ok.sum():5d}  gross={gross:+6.1f}  cost={cost:4.1f}  NET={net:+6.1f}")
    return net, ok.sum(), s.filter(pl.col("mk6").is_finite())


def main():
    cohort = set(x for x in Path("out/cohort_wallets.txt").read_text().split("\n") if x)
    print(f"cohort wallets: {len(cohort)}")
    lk = _load_bars()
    df = build_table(cohort, lk)
    df.write_parquet(OUT / "consensus_test_table.parquet")
    print(f"TEST entries (majors): {df.height:,}\n")
    print("=== ENTRY-COUNT consensus (conditional_copy2 def: earlier same-dir entries in window) ===")
    for thr in [5, 7, 8, 9, 10, 12, 15]:
        net_subset(df, pl.col("cons") >= thr, f"cons(entries)>={thr}")
    print("=== DISTINCT-WALLET consensus (incl self) ===")
    for thr in [5, 7, 8, 9, 10]:
        net_subset(df, pl.col("consd") >= thr, f"consd(wallets)>={thr}")
    net_subset(df, pl.col("cons") >= 0, "ALL entries")


if __name__ == "__main__":
    main()
