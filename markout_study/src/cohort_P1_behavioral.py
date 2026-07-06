"""
PHASE 1 — descriptive behavioral decomposition (EXPLANATORY ONLY; no significance/subgroup-performance claims).
Compare entry-event market state for three groups on TRAIN (test window kept pristine):
  RECURRING = frozen canonical cohort (out/cohort_M_frozen.txt, 121 wallets, >=2 train-month top-decile)
  ORDINARY  = all other cohort wallets' entries (sampled)
  CONTROL   = random non-wallet train bars (sampled)
Features (available from bars + cohort entries + external funding): signed(in-trade-dir) & absolute trailing returns at
1/2/4/8/24h; speed (1h) & acceleration; distance from trailing-24h high/low; realized vol (2h/8h); time since local
24h extreme; funding rate; trade size (notl); direction bias; position-building proxy (entries per wallet-coin-day).
Deferred (not in this dataset): VWAP dist, volume/OI shocks, liquidations, basis, order-flow imbalance, aggressiveness.
One heavy pricing pass. RAM-safe.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd, polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; COINS = ["BTC", "ETH", "SOL", "HYPE"]; TRAIN_HI = 1_769_904_000_000
LB = {"1h": 3600_000, "2h": 7200_000, "4h": 14400_000, "8h": 28800_000, "24h": 86400_000}
W24 = 288; RNG = np.random.default_rng(0)
FUND = "/Users/corywagamaneure/bablyon/scratch_conv/mlscreen/funding.parquet"

cohort = set(l.strip() for l in open("out/cohort_M_frozen.txt") if l.strip() and not l.startswith("#"))
df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "notl").filter(pl.col("b_ts") < TRAIN_HI)
lookups = mk._load_bars()
try:
    fund = pl.read_parquet(FUND); fund_ok = True
except Exception:
    fund_ok = False
print(f"cohort {len(cohort)} wallets | train entries {df.height} | funding={'yes' if fund_ok else 'NO'}", flush=True)

def bar_state(coin):
    lk = lookups[coin]; bt = np.asarray(lk[0]); cl = np.asarray(lk[1])
    s = pd.Series(cl); rmax = s.rolling(W24, min_periods=1).max().to_numpy(); rmin = s.rolling(W24, min_periods=1).min().to_numpy()
    idx = np.arange(len(cl)); eps = 1e-12
    lasthi = np.maximum.accumulate(np.where(cl >= rmax - eps, idx, -1)); lastlo = np.maximum.accumulate(np.where(cl <= rmin + eps, idx, -1))
    lr = np.diff(np.log(cl), prepend=np.log(cl[0])); c2 = np.cumsum(lr ** 2); c1 = np.cumsum(lr)
    def rv(k, w):
        k0 = np.maximum(k - w, 0); n = k - k0 + 1
        s2 = c2[k] - np.where(k0 > 0, c2[k0 - 1], 0.0); s1 = c1[k] - np.where(k0 > 0, c1[k0 - 1], 0.0)
        return np.sqrt(np.maximum(s2 / n - (s1 / n) ** 2, 0.0))
    fr = None
    if fund_ok:
        fc = fund.filter(pl.col("coin") == coin).sort("time")
        if fc.height:
            ft = fc["time"].to_numpy(); fr = (fc["rate"].to_numpy(), ft)
    return lk, bt, cl, rmax, rmin, lasthi, lastlo, rv, fr

def feats(coin, ts, dir_arr):
    lk, bt, cl, rmax, rmin, lasthi, lastlo, rv, fr = ST[coin]
    ent = mk._next_bar_close_vec(lk, ts); k = np.clip(np.searchsorted(bt, ts), 0, len(cl) - 1)
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for name, h in LB.items():
            past = mk._next_bar_close_vec(lk, ts - h); r = ent / past - 1.0
            out[f"aret_{name}"] = np.abs(r) * BP
            out[f"sret_{name}"] = (dir_arr * r * BP) if dir_arr is not None else np.full_like(r, np.nan)
        r1 = ent / mk._next_bar_close_vec(lk, ts - LB["1h"]) - 1.0; r2 = ent / mk._next_bar_close_vec(lk, ts - LB["2h"]) - 1.0
        out["accel"] = (2 * r1 - r2) * BP                                  # last-hour move minus prior-hour move
        out["dist_hi"] = (ent / rmax[k] - 1.0) * BP                        # <=0: below 24h high
        out["dist_lo"] = (ent / rmin[k] - 1.0) * BP                        # >=0: above 24h low
        out["vol_2h"] = rv(k, 24) * BP; out["vol_8h"] = rv(k, 96) * BP
        out["age_hi_bars"] = (k - lasthi[k]).astype(float); out["age_lo_bars"] = (k - lastlo[k]).astype(float)
        if fr is not None:
            fi = np.clip(np.searchsorted(fr[1], ts) - 1, 0, len(fr[0]) - 1); out["funding_bp"] = fr[0][fi] * BP
        else:
            out["funding_bp"] = np.full_like(ent, np.nan)
    return out

ST = {c: bar_state(c) for c in COINS}
# build the three event sets per coin
def collect(mask_kind):
    acc = {}
    for coin in COINS:
        e = df.filter(pl.col("coin") == coin)
        w = e["wallet"].to_numpy(); ts = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float); notl = e["notl"].to_numpy()
        if mask_kind == "rec":
            m = np.array([x in cohort for x in w])
        elif mask_kind == "ord":
            m = np.array([x not in cohort for x in w])
        if mask_kind in ("rec", "ord"):
            ts_, d_, notl_ = ts[m], d[m], notl[m]
            if mask_kind == "ord" and len(ts_) > 40000:               # sample ordinary for tractability
                s = RNG.choice(len(ts_), 40000, replace=False); ts_, d_, notl_ = ts_[s], d_[s], notl_[s]
        else:                                                          # control: random non-wallet bars
            bt = ST[coin][1]; tb = bt[bt < TRAIN_HI]
            wb = set((ts // 300_000).tolist()); tb = np.array([t for t in tb if int(t) // 300_000 not in wb])
            s = RNG.choice(len(tb), min(15000, len(tb)), replace=False); ts_ = tb[s]; d_ = None; notl_ = None
        f = feats(coin, ts_, d_)
        for kf, v in f.items(): acc.setdefault(kf, []).append(v)
        acc.setdefault("_notl", []).append(notl_ if notl_ is not None else np.full(len(ts_), np.nan))
    return {kf: np.concatenate(v) for kf, v in acc.items()}

G = {"RECURRING": collect("rec"), "ORDINARY": collect("ord"), "CONTROL": collect("control")}
print(f"events: RECURRING {len(G['RECURRING']['aret_8h'])} | ORDINARY {len(G['ORDINARY']['aret_8h'])} | CONTROL {len(G['CONTROL']['aret_8h'])}\n")

def med(a): a = a[np.isfinite(a)]; return np.median(a) if len(a) else np.nan
def mean(a): a = a[np.isfinite(a)]; return np.mean(a) if len(a) else np.nan
order = ["aret_1h","aret_2h","aret_4h","aret_8h","aret_24h","sret_1h","sret_4h","sret_8h","sret_24h","accel",
         "dist_hi","dist_lo","vol_2h","vol_8h","age_hi_bars","age_lo_bars","funding_bp"]
print(f"{'feature':<14}{'RECURRING':>22}{'ORDINARY':>22}{'CONTROL':>22}   (median [mean])")
for kf in order:
    row = ""
    for g in ["RECURRING", "ORDINARY", "CONTROL"]:
        v = G[g].get(kf); row += f"{med(v):>10.1f} [{mean(v):>7.1f}]" if v is not None else f"{'n/a':>22}"
    print(f"{kf:<14}{row}")
# wallet-only traits
print("\n-- wallet-event-only traits --")
for g in ["RECURRING", "ORDINARY"]:
    n = G[g]["_notl"]; d8 = G[g]["sret_8h"]
    print(f"  {g:<10} size notl med ${med(n):>10,.0f}  mean ${mean(n):>10,.0f} | signed-8h-in-dir med {med(d8):+.1f}bp "
          f"(<0 = entered AGAINST the 8h move = contrarian/fade-like)")
# position-building proxy (entries per wallet-coin-day), train
pb = (df.with_columns(day=(pl.col("b_ts") // 86_400_000))
        .group_by("wallet", "coin", "day").agg(n=pl.len())
        .with_columns(rec=pl.col("wallet").is_in(list(cohort))))
for g, lab in [(True, "RECURRING"), (False, "ORDINARY")]:
    s = pb.filter(pl.col("rec") == g)["n"]
    print(f"  {lab:<10} entries per wallet-coin-day: median {s.median():.0f} mean {s.mean():.2f} "
          f"(higher = position-building vs one-shot)")
print("\nEXPLANATORY ONLY. Deferred (not in dataset): VWAP dist, volume/OI shocks, liquidations, basis, order-flow imbalance,"
      " maker/taker aggressiveness — all to be captured in the forward log (Phase 3).")
