"""
Stage M4 — frozen continuous-control test: does persistent-wallet activity add fade-timing info BEYOND observable market
state (the size of the preceding move, vol, coin, time-of-day)? Fit E[mechanical-fade 8h return | state] on TRAIN
NON-wallet bars only (continuous controls), FREEZE it, apply to TEST top-decile-wallet trigger events. Residual alpha =
realized fade - predicted fade. PRIMARY estimand = day-capped (fixed capital per coin-day); SECONDARY = equal-weight-per-event.
Joint calendar-day block bootstrap. H1: E[day-capped residual] > 0. Wallet list = TRAIN-ONLY top decile (attrition, no
replacement). Controls/model frozen from train; NO tuning after seeing test. Historical window repeatedly inspected ->
even a positive is EXPLORATORY, needs forward confirmation. One heavy pricing pass. RAM-safe.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; H8 = 8 * 3600 * 1000; COINS = ["BTC", "ETH", "SOL", "HYPE"]; TRAIN_HI = 1_769_904_000_000; TEST_LO = 1_772_323_200_000
MIN_TR = 10; RNG = np.random.default_rng(0)
df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "split")
lookups = mk._load_bars()

# ---- frozen TRAIN-ONLY top-decile wallets (same rule as corrected M3) ----
recs = []
for coin in COINS:
    e = df.filter(pl.col("coin") == coin)
    if e.height == 0: continue
    ts = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float)
    ent = mk._next_bar_close_vec(lookups[coin], ts); ex = mk._next_bar_close_vec(lookups[coin], ts + H8)
    with np.errstate(invalid="ignore", divide="ignore"):
        wal = d * (ex / ent - 1.0) * BP
    for i in np.where(np.isfinite(wal) & (ts < TRAIN_HI))[0]:
        recs.append((e["wallet"][int(i)], int(ts[i] // 86_400_000), float(wal[i])))
TR = pl.DataFrame(recs, schema=["wallet", "day", "w"], orient="row")
trdf = TR.group_by("wallet", "day").agg(w=pl.col("w").mean()).group_by("wallet").agg(trw=pl.col("w").mean(), trnd=pl.len()).filter(pl.col("trnd") >= MIN_TR)
topd = set(trdf.filter(pl.col("trw") >= trdf["trw"].quantile(0.90))["wallet"].to_list())
print(f"TRAIN-eligible {trdf.height} | frozen TRAIN-only top-decile: {len(topd)} wallets", flush=True)

# ---- assemble state+fade for TRAIN non-wallet bars (FIT) and TEST wallet events (APPLY) ----
def rollvol_arr(close):
    lr = np.diff(np.log(close), prepend=np.log(close[0])); c2 = np.cumsum(lr ** 2); c1 = np.cumsum(lr)
    def rv(k):
        k0 = np.maximum(k - 24, 0); n = k - k0 + 1
        s2 = c2[k] - np.where(k0 > 0, c2[k0 - 1], 0.0); s1 = c1[k] - np.where(k0 > 0, c1[k0 - 1], 0.0)
        return np.sqrt(np.maximum(s2 / n - (s1 / n) ** 2, 0.0))
    return rv
def state(lk, ts, dircol=None):
    ent = mk._next_bar_close_vec(lk, ts); past = mk._next_bar_close_vec(lk, ts - H8); ex = mk._next_bar_close_vec(lk, ts + H8)
    with np.errstate(invalid="ignore", divide="ignore"):
        move = ex / ent - 1.0; fade = -np.sign(ent / past - 1.0) * move * BP; tret = ent / past - 1.0
        wal = dircol * move * BP if dircol is not None else None
    return move, fade, tret, wal

tr_parts = []; ev_parts = []
for coin in COINS:
    lk = lookups[coin]; bar_ts = np.asarray(lk[0]); close = np.asarray(lk[1]); rv = rollvol_arr(close)
    # TRAIN non-wallet bars (exclude any bar where a top-decile wallet traded in train)
    wev = df.filter((pl.col("coin") == coin) & (pl.col("b_ts") < TRAIN_HI) & pl.col("wallet").is_in(list(topd)))["b_ts"].to_numpy()
    wbar = set((wev // 300_000).tolist())
    tmask = bar_ts < TRAIN_HI
    tbar = bar_ts[tmask]; tbar = np.array([t for t in tbar if int(t) // 300_000 not in wbar])
    _, fade, tret, _ = state(lk, tbar); vol = rv(np.clip(np.searchsorted(bar_ts, tbar), 0, len(close) - 1))
    hour = (tbar // 3_600_000) % 24; ok = np.isfinite(fade) & np.isfinite(tret) & np.isfinite(vol)
    tr_parts.append((coin, tret[ok], vol[ok], hour[ok], fade[ok]))
    # TEST wallet trigger events (top-decile wallets)
    e = df.filter((pl.col("coin") == coin) & (pl.col("b_ts") >= TEST_LO) & pl.col("wallet").is_in(list(topd)))
    ts = e["b_ts"].to_numpy()
    _, fade, tret, _ = state(lk, ts); vol = rv(np.clip(np.searchsorted(bar_ts, ts), 0, len(close) - 1))
    hour = (ts // 3_600_000) % 24; ok = np.isfinite(fade) & np.isfinite(tret) & np.isfinite(vol)
    ev_parts.append((coin, tret[ok], vol[ok], hour[ok], fade[ok], (ts[ok] // 86_400_000)))

# ---- design matrix (continuous controls): frozen spec ----
def design(coin_arr, tret, vol, hour):
    a = np.abs(tret); cols = [np.ones_like(tret), tret, a, a ** 2, vol, vol ** 2, tret * vol, a * vol,
                              np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)]
    for c in COINS[:-1]:                                          # coin dummies + coin x |tret| slopes (HYPE = base)
        d = (coin_arr == c).astype(float); cols += [d, d * a]
    return np.column_stack(cols)
Xtr = np.vstack([design(np.full(len(p[1]), p[0]), p[1], p[2], p[3]) for p in tr_parts])
ytr = np.concatenate([p[4] for p in tr_parts])
beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)                  # FREEZE model on train non-wallet bars
print(f"fit E[fade|state] on {len(ytr)} TRAIN non-wallet bars | test wallet events: {sum(len(p[1]) for p in ev_parts)}", flush=True)

# ---- apply frozen model to TEST wallet events -> residual alpha ----
coin_e = np.concatenate([np.full(len(p[1]), p[0]) for p in ev_parts])
tret_e = np.concatenate([p[1] for p in ev_parts]); vol_e = np.concatenate([p[2] for p in ev_parts])
hour_e = np.concatenate([p[3] for p in ev_parts]); fade_e = np.concatenate([p[4] for p in ev_parts])
day_e = np.concatenate([p[5] for p in ev_parts]).astype(int)
pred_e = design(coin_e, tret_e, vol_e, hour_e) @ beta
resid = fade_e - pred_e
print(f"  mean realized fade {fade_e.mean():+.2f} | mean predicted {pred_e.mean():+.2f} | mean residual {resid.mean():+.2f} bp")
print(f"  |tret| control check: model already conditions on it continuously (events avg |tret| {np.abs(tret_e).mean()*BP:.0f}bp)")

# ---- aggregate: PRIMARY day-capped per coin-day; SECONDARY equal-weight per event; joint day-block bootstrap ----
cidx = {c: i for i, c in enumerate(COINS)}; days = np.sort(np.unique(day_e)); di = {int(x): i for i, x in enumerate(days)}; ND = len(days)
Rmat = np.full((4, ND), np.nan)                                  # coin-day mean residual
from collections import defaultdict
cell = defaultdict(list)
for c, dd, r in zip(coin_e, day_e, resid): cell[(cidx[c], di[int(dd)])].append(r)
for (i, j), v in cell.items(): Rmat[i, j] = np.mean(v)
d2i = defaultdict(list)
for idx, dd in enumerate(day_e): d2i[int(dd)].append(idx)
edays = list(d2i.keys()); NB = 5000
def daycap(M): return float(np.nanmean(M)) if np.isfinite(M).any() else np.nan
prim = daycap(Rmat); sec = float(resid.mean())
bp_prim = np.empty(NB); bp_sec = np.empty(NB)
for b in range(NB):
    p = RNG.integers(0, ND, ND); bp_prim[b] = daycap(Rmat[:, p])
    ds = [edays[k] for k in RNG.integers(0, len(edays), len(edays))]; bp_sec[b] = np.mean([resid[i] for dd in ds for i in d2i[dd]])
def rp(pt, bs):
    return f"{pt:+.2f} bp [{np.nanpercentile(bs,2.5):+.2f},{np.nanpercentile(bs,97.5):+.2f}] one-sided p(>0)={np.mean(bs<=0):.3f}"
print("\n=== TRIGGER RESIDUAL ALPHA (realized fade - state-predicted fade), joint day-block bootstrap ===")
print(f"  PRIMARY   day-capped per coin-day : {rp(prim, bp_prim)}")
print(f"  SECONDARY equal-weight per event  : {rp(sec, bp_sec)}")
# ---- POSITIVE-CONTROL MDE: is the frozen day-capped test even ABLE to detect a care-about residual on this window? ----
se = float(np.nanstd(bp_prim))
print(f"\n=== POSITIVE-CONTROL MDE (day-capped, {ND} test coin-days) ===")
print(f"  bootstrap SE = {se:.2f} bp -> MDE(95%CI excl 0) ~{1.96*se:.1f} bp | MDE(80% power) ~{2.8*se:.1f} bp")
for inj in [5, 10, 15, 20]:                                       # inject a KNOWN residual at every event, re-run frozen test
    Rinj = Rmat + inj; bs = np.array([daycap(Rinj[:, RNG.integers(0, ND, ND)]) for _ in range(2000)])
    lo = np.nanpercentile(bs, 2.5)
    print(f"  inject +{inj:2d} bp -> recovered {daycap(Rinj):+.2f} [{lo:+.2f},{np.nanpercentile(bs,97.5):+.2f}] detected(CI>0)={lo>0}")
print("  -> if MDE >> care-about (~+5bp), the historical window is BLIND by construction => +5.87 is INCONCLUSIVE, not null.")

print("\n=== residual by COIN / MONTH (day-capped) ===")
for c in COINS:
    i = cidx[c]; print(f"  {c:5}: {np.nanmean(Rmat[i]):+.2f} bp")
for mo in sorted(set(datetime.fromtimestamp(int(d) * 86400, tz=timezone.utc).strftime('%Y-%m') for d in days)):
    cols = [i for i, d in enumerate(days) if datetime.fromtimestamp(int(d) * 86400, tz=timezone.utc).strftime('%Y-%m') == mo]
    print(f"  {mo}: {np.nanmean(Rmat[:,cols]):+.2f} bp")
v = "POSITIVE (wallet activity adds timing info beyond observable state)" if np.percentile(bp_prim, 2.5) > 0 else \
    "ZERO/INCONCLUSIVE (wallets identify publicly-observable extreme-move setups; residual CI includes 0)"
print(f"\n=== VERDICT: {v} ===")
print("NOTE: model frozen on TRAIN non-wallet bars; liquidity/spread controls unavailable (no BBO) -> deferred.")
print("      The historical test window has been repeatedly inspected -> even a positive residual is EXPLORATORY and requires FORWARD confirmation.")
