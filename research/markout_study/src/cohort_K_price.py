"""
Stage K, Job C: per-entry markout TERM STRUCTURE for the frozen cohort (out/cohort_K.txt), so we can read
their edge at their TRUE holding horizon (~2-4h) instead of only 24h. Reuses mkcommon pricing (consistent
with how entry_px was built). Adds: coin-month drift strip (neut = raw - dir*coin_month_mean_return) and a
BTC trailing-7d regime tag (BULL/BEAR/CHOP). Cohort-only -> small output. RAM-safe (entries+bars, no tape).
"""
import sys, glob
from pathlib import Path
from datetime import datetime, timezone
import numpy as np, polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

MAJORS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
HZ = {"1h": 3, "2h": 4, "4h": 5, "8h": 6, "24h": 8}      # indices into mkcommon.H_MS / HORIZONS
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI, TEST_LO = ms(2026, 2, 1), ms(2026, 3, 1)
cohort = set(l.strip() for l in open("out/cohort_K.txt") if l.strip())
print(f"cohort: {len(cohort)} wallets", flush=True)
lookups = mk._load_bars()

# ---- BTC trailing-7d regime, per UTC day ----
bt, bc = lookups["BTC"]
day = (bt // 86_400_000)
dclose = {}
for dd, cc in zip(day, bc):
    dclose[int(dd)] = float(cc)                          # last close wins (bars sorted) -> daily close
days = sorted(dclose)
dc = {d: dclose[d] for d in days}
def regime_of(b_ts):
    d = int(b_ts // 86_400_000)
    c0 = dc.get(d); c7 = dc.get(d - 7)
    if not c0 or not c7: return "CHOP"
    r = c0 / c7 - 1
    return "BULL" if r > 0.03 else ("BEAR" if r < -0.03 else "CHOP")

def ym_of(b_ts):
    dt = datetime.fromtimestamp(b_ts / 1000, tz=timezone.utc); return dt.year * 100 + dt.month

rows = []
for coin in MAJORS:
    lk = lookups[coin]
    e = (pl.scan_parquet(sorted(glob.glob("out/entries/part_*")))
         .filter((pl.col("coin") == coin) & pl.col("wallet").is_in(cohort))
         .select("wallet", "b_ts", "dir", "entry_px", "notl").collect())
    if e.height == 0:
        print(f"  {coin}: 0 cohort entries"); continue
    b_ts = e["b_ts"].to_numpy(); d = e["dir"].to_numpy(); epx = e["entry_px"].to_numpy(); notl = e["notl"].to_numpy()
    raw = mk.markout_ret(lk, b_ts, d, epx)               # (n,12) returns, NaN where unpriceable
    yms = np.array([ym_of(t) for t in b_ts])
    # coin-month drift per horizon: mean forward return over the coin's OWN bar grid that month
    bar_ts, _ = lk
    bar_ym = np.array([ym_of(t) for t in bar_ts])
    drift = {}                                           # (ym, hlabel) -> mean return
    for m in np.unique(yms):
        bmask = bar_ym == m
        if bmask.sum() < 20: continue
        bts = bar_ts[bmask]
        ent = mk._next_bar_close_vec(lk, bts)
        for hl, hi in HZ.items():
            ex = mk._next_bar_close_vec(lk, bts + int(mk.H_MS[hi]))
            rr = ex / ent - 1.0
            fin = np.isfinite(rr)
            drift[(int(m), hl)] = float(rr[fin].mean()) if fin.any() else 0.0
    regs = np.array([regime_of(t) for t in b_ts])
    split = np.where(b_ts < TRAIN_HI, "train", np.where(b_ts >= TEST_LO, "test", "embargo"))
    for i in range(e.height):
        rec = [e["wallet"][i], coin, int(b_ts[i]), int(yms[i]), int(d[i]), float(notl[i]), regs[i], split[i]]
        for hl, hi in HZ.items():
            r = raw[i, hi]
            rec.append(float(r * BP) if np.isfinite(r) else None)
            dr = drift.get((int(yms[i]), hl), 0.0)
            rec.append(float((r - d[i] * dr) * BP) if np.isfinite(r) else None)
        rows.append(rec)
    print(f"  {coin}: {e.height} cohort entries priced", flush=True)

cols = ["wallet", "coin", "b_ts", "ym", "dir", "notl", "regime", "split"]
for hl in HZ: cols += [f"raw_{hl}", f"neut_{hl}"]
R = pl.DataFrame(rows, schema=cols, orient="row")
R.write_parquet("out/cohort_K_entries.parquet")
print(f"\nwrote {R.height} entries -> out/cohort_K_entries.parquet")
print(R.group_by("split").agg(pl.len()).sort("split"))
