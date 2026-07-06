"""
Stage M3 — is persistent-wallet ACTIVITY a useful event trigger for the mechanical fade, or does the fade work equally
well without wallet info? Four strategies on the untouched TEST window, all frozen from the M2 deploy instrument:
  A wallet-direction      : copy the wallet's dir at each top-decile wallet event.
  B wallet-triggered fade : mechanical contrarian (-sign trailing-8h) at the SAME timestamps.
  C unconditional fade    : mechanical contrarian at ALL bars (no wallet info).
  D activity-matched fade : mechanical contrarian at NON-wallet timestamps matched on coin x month x tod x tret x vol, same N.
8h horizon, next-bar-close entry, realistic per-coin cost, day-capped at the COIN-DAY level (common unit), joint calendar-day
block bootstrap. Load-bearing: A-B (dir add info?), B-D (wallet activity = good reversal moments?), B-C (improve mechanical?).
NO threshold/horizon/subset/matching optimization after seeing results. One heavy pricing pass. RAM-safe.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; H8 = 8 * 3600 * 1000; COINS = ["BTC", "ETH", "SOL", "HYPE"]
COST = {"BTC": 6.0, "ETH": 6.0, "SOL": 7.0, "HYPE": 9.0}
MIN_TR, MIN_TE = 10, 8; R_MATCH = 20; RNG = np.random.default_rng(0)
def mon_of(ts): return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m")

lookups = mk._load_bars()
df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "split")

def price(lk, ts, dircol=None):
    ent = mk._next_bar_close_vec(lk, ts); ex = mk._next_bar_close_vec(lk, ts + H8); past = mk._next_bar_close_vec(lk, ts - H8)
    with np.errstate(invalid="ignore", divide="ignore"):
        move = ex / ent - 1.0
        fade = -np.sign(ent / past - 1.0) * move * BP           # mechanical contrarian gross (bp)
        wal = (dircol * move * BP) if dircol is not None else None
        tret = ent / past - 1.0
    valid = np.isfinite(move) & np.isfinite(tret)
    return wal, fade, tret, valid

# ---- freeze the persistent top-decile set: rank TRAIN day-weighted GROSS 8h wallet markout (identical to M2 deploy) ----
recs = []
for coin in COINS:
    e = df.filter(pl.col("coin") == coin)
    if e.height == 0: continue
    ts = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float)
    wal, fade, tret, val = price(lookups[coin], ts, d)
    for i in np.where(val)[0]:
        recs.append((e["wallet"][int(i)], coin, int(ts[i] // 86_400_000), e["split"][int(i)], float(wal[i]), float(fade[i]), int(ts[i]), float(d[i])))
E = pl.DataFrame(recs, schema=["wallet", "coin", "day", "split", "wal", "fade", "ts", "dir"], orient="row")
wd = E.group_by("wallet", "split", "day").agg(w=pl.col("wal").mean())
# TRAIN-ONLY selection (NO test-activity condition): rank train day-weighted gross markout, freeze top decile of train-eligible.
trdf = wd.filter(pl.col("split") == "train").group_by("wallet").agg(trw=pl.col("w").mean(), trnd=pl.len()).filter(pl.col("trnd") >= MIN_TR)
topd = set(trdf.filter(pl.col("trw") >= trdf["trw"].quantile(0.90))["wallet"].to_list())
n_test = wd.filter((pl.col("split") == "test") & pl.col("wallet").is_in(list(topd)))["wallet"].n_unique()
print(f"priced {E.height} episodes | TRAIN-eligible {trdf.height} | frozen TRAIN-only top-decile {len(topd)} wallets "
      f"({n_test} with test activity, {len(topd)-n_test} attrition, no replacement)", flush=True)

# ---- A & B events = TEST episodes of the frozen top-decile wallets (GROSS cols wal / fade) ----
ev = E.filter((pl.col("split") == "test") & pl.col("wallet").is_in(list(topd)))
test_days = np.sort(E.filter(pl.col("split") == "test")["day"].unique().to_numpy())
di = {int(x): i for i, x in enumerate(test_days)}; cidx = {c: i for i, c in enumerate(COINS)}; ND = len(test_days)
cost_vec = np.array([COST[c] for c in COINS])

def coinday(frame, col):                                          # GROSS mean per coin-day (day-cap)
    g = frame.group_by("coin", "day").agg(v=pl.col(col).mean())
    M = np.full((4, ND), np.nan)
    for c, dd, v in zip(g["coin"], g["day"], g["v"]):
        if int(dd) in di: M[cidx[c], di[int(dd)]] = v
    return M
Ag = coinday(ev, "wal"); Bg = coinday(ev, "fade")

# ---- C: unconditional fade at ALL test bars + matched-control features (buckets from TRAIN-fitted boundaries ONLY) ----
TRAIN_HI = 1_769_904_000_000                                     # Feb-1 2026 (cohort train/test split boundary)
feat = {}; C_rows = []
lo = int(test_days[0]) * 86_400_000; hi = (int(test_days[-1]) + 1) * 86_400_000
for coin in COINS:
    bar_ts = np.asarray(lookups[coin][0]); close = np.asarray(lookups[coin][1])
    logret = np.diff(np.log(close), prepend=np.log(close[0]))
    csum = np.cumsum(logret ** 2); csum1 = np.cumsum(logret)
    def rollvol(k):                                              # trailing 24-bar (2h) std, vectorized
        k0 = np.maximum(k - 24, 0); n = k - k0 + 1
        s2 = csum[k] - np.where(k0 > 0, csum[k0 - 1], 0.0); s1 = csum1[k] - np.where(k0 > 0, csum1[k0 - 1], 0.0)
        return np.sqrt(np.maximum(s2 / n - (s1 / n) ** 2, 0.0))
    def statef(ts):
        ent = mk._next_bar_close_vec(lookups[coin], ts); past = mk._next_bar_close_vec(lookups[coin], ts - H8); ex = mk._next_bar_close_vec(lookups[coin], ts + H8)
        with np.errstate(invalid="ignore", divide="ignore"):
            move = ex / ent - 1.0; fade = -np.sign(ent / past - 1.0) * move * BP; tret = ent / past - 1.0
        vol = rollvol(np.clip(np.searchsorted(bar_ts, ts), 0, len(close) - 1))
        ok = np.isfinite(move) & np.isfinite(tret) & np.isfinite(vol)
        return ts[ok], fade[ok], tret[ok], vol[ok]
    _, _, tret_tr, vol_tr = statef(bar_ts[bar_ts < TRAIN_HI])    # TRAIN-fitted bucket boundaries (NO test data)
    qtret = np.quantile(tret_tr, [.2, .4, .6, .8]); qvol = np.quantile(vol_tr, [1/3, 2/3])
    ts, fade, tret, vol = statef(bar_ts[(bar_ts >= lo) & (bar_ts < hi)])   # TEST features
    hourb = ((ts // 3_600_000) % 24) // 4; mon = np.array([mon_of(int(t)) for t in ts]); day = ts // 86_400_000
    for n, dd in zip(fade, day):
        C_rows.append((coin, int(dd), float(n)))                 # GROSS
    tqb = np.digitize(tret, qtret); vb = np.digitize(vol, qvol)  # FROZEN train-defined boundaries applied to test
    feat[coin] = dict(ts=ts, fade=fade, tret=tret, day=day, hourb=hourb, mon=mon, tqb=tqb, vb=vb)
Cg = coinday(pl.DataFrame(C_rows, schema=["coin", "day", "fade"], orient="row"), "fade")

# ---- D: activity-matched placebo fade; matched candidate's fade placed on the EVENT's coin-day (preserves matched pairs) ----
walbars = {c: set() for c in COINS}
for c, t in zip(ev["coin"], ev["ts"]): walbars[c].add(int(t) // 300_000)
ev_coin = ev["coin"].to_list(); ev_ts = ev["ts"].to_list(); ev_day = ev["day"].to_list(); ev_fade = np.array(ev["fade"].to_list())
ev_cells = []; ev_atret = np.empty(len(ev_ts))
for idx, (c, t, dday) in enumerate(zip(ev_coin, ev_ts, ev_day)):
    f = feat[c]; k = min(int(np.searchsorted(f["ts"], int(t))), len(f["ts"]) - 1)
    ev_cells.append((c, str(f["mon"][k]), int(f["hourb"][k]), int(f["tqb"][k]), int(f["vb"][k]), int(dday)))
    ev_atret[idx] = abs(f["tret"][k])
pool = {}
for c in COINS:
    f = feat[c]
    for j in range(len(f["ts"])):
        if int(f["ts"][j]) // 300_000 in walbars[c]: continue
        pool.setdefault((c, str(f["mon"][j]), int(f["hourb"][j]), int(f["tqb"][j]), int(f["vb"][j])), []).append(j)
matched_n = sum(1 for cell in ev_cells if cell[:5] in pool)
NE = len(ev_cells); Dg_draws = np.full((R_MATCH, 4, ND), np.nan)
mf_acc = np.full((R_MATCH, NE), np.nan); mtret_acc = np.full((R_MATCH, NE), np.nan)
for r in range(R_MATCH):
    rows = []
    for idx, cell in enumerate(ev_cells):
        cand = pool.get(cell[:5])
        if not cand: continue
        j = cand[RNG.integers(0, len(cand))]; f = feat[cell[0]]
        rows.append((cell[0], cell[5], float(f["fade"][j])))                # matched fade on the EVENT coin-day
        mf_acc[r, idx] = f["fade"][j]; mtret_acc[r, idx] = abs(f["tret"][j])
    Dg_draws[r] = coinday(pl.DataFrame(rows, schema=["coin", "day", "fade"], orient="row"), "fade") if rows else np.full((4, ND), np.nan)
Dg = np.nanmean(Dg_draws, axis=0); matched_fade = np.nanmean(mf_acc, axis=0); matched_atret = np.nanmean(mtret_acc, axis=0)
print(f"wallet events (A/B): {ev.height} | matched cells found: {matched_n}/{ev.height} | C bars: {len(C_rows)}", flush=True)
print(f"  |trailing-8h ret| balance (matching check): events {np.nanmean(ev_atret)*BP:.1f}bp vs matched {np.nanmean(matched_atret)*BP:.1f}bp", flush=True)

# ---- NET = GROSS - per-coin cost (row-wise) ; joint calendar-day block bootstrap ----
def net(M): return M - cost_vec[:, None]
A, B, C, D = net(Ag), net(Bg), net(Cg), net(Dg)
def pooled(M): return float(np.nanmean(M)) if np.isfinite(M).any() else np.nan
NB = 5000
gross = {"A": pooled(Ag), "B": pooled(Bg), "C": pooled(Cg), "D": pooled(Dg)}
pts = {"A": pooled(A), "B": pooled(B), "C": pooled(C), "D": pooled(D)}
boot = {k: np.empty(NB) for k in ["A", "B", "C", "D", "A-B", "B-D", "B-C"]}
mats = {"A": A, "B": B, "C": C, "D": D}
for b in range(NB):
    p = RNG.integers(0, ND, ND); mm = {k: pooled(M[:, p]) for k, M in mats.items()}
    for k in ["A", "B", "C", "D"]: boot[k][b] = mm[k]
    boot["A-B"][b] = mm["A"] - mm["B"]; boot["B-D"][b] = mm["B"] - mm["D"]; boot["B-C"][b] = mm["B"] - mm["C"]
def rep(k, two=False):
    v = boot[k]; p = min(np.mean(v <= 0), np.mean(v >= 0)) * (2 if two else 1)
    return f"[{np.nanpercentile(v,2.5):+.2f},{np.nanpercentile(v,97.5):+.2f}] p={p:.3f}"

print("\n=== gross / net return (bp per coin-day, realistic cost), day-capped, joint day-block bootstrap ===")
for k in ["A", "B", "C", "D"]:
    print(f"  {k}: gross {gross[k]:+.2f}  net {pts[k]:+.2f}  {rep(k)}")
print("\n=== LOAD-BEARING COMPARISONS (net; cost applied identically so cancels in diffs) ===")
print(f"  1. A - B  wallet DIRECTION adds info?            {pts['A']-pts['B']:+.2f} bp  {rep('A-B', two=True)}")
print(f"  2. B - D  wallet ACTIVITY = better reversal moments?  {pts['B']-pts['D']:+.2f} bp  {rep('B-D', two=True)}   <== CENTRAL")
print(f"  3. B - C  wallet activity improves the mechanical?  {pts['B']-pts['C']:+.2f} bp  {rep('B-C', two=True)}")
print(f"\n  Wallet-triggered fade positive IGNORING wallet dir?  B net = {pts['B']:+.2f}  {rep('B')}")

# episode-level matched-pairs B-D (no day-cap asymmetry; day-block bootstrap over EVENT days) — the clean central contrast
from collections import defaultdict
pair = ev_fade - matched_fade; d2i = defaultdict(list)
for i, dd in enumerate(ev_day):
    if np.isfinite(pair[i]): d2i[int(dd)].append(i)
edays = list(d2i.keys()); pair_all = np.array([pair[i] for i in range(NE) if np.isfinite(pair[i])])
bpd = np.empty(NB)
for b in range(NB):
    ds = [edays[k] for k in RNG.integers(0, len(edays), len(edays))]
    bpd[b] = np.mean([pair[i] for dd in ds for i in d2i[dd]])
pp = 2 * min((bpd <= 0).mean(), (bpd >= 0).mean())
print(f"  2b. B - D episode-level matched pairs (cleanest): {pair_all.mean():+.2f} bp "
      f"[{np.percentile(bpd,2.5):+.2f},{np.percentile(bpd,97.5):+.2f}] p={pp:.3f}  (n={len(pair_all)} paired events)")

print("\n=== by COIN (net bp/coin-day) ===")
for c in COINS:
    i = cidx[c]; print(f"  {c:5}: A {np.nanmean(A[i]):+.2f}  B {np.nanmean(B[i]):+.2f}  C {np.nanmean(C[i]):+.2f}  D {np.nanmean(D[i]):+.2f}")
print("=== by MONTH (net bp/coin-day) ===")
for mo in sorted(set(mon_of(int(d) * 86_400_000) for d in test_days)):
    cols = [i for i, d in enumerate(test_days) if mon_of(int(d) * 86_400_000) == mo]
    print(f"  {mo}: A {np.nanmean(A[:,cols]):+.2f}  B {np.nanmean(B[:,cols]):+.2f}  C {np.nanmean(C[:,cols]):+.2f}  D {np.nanmean(D[:,cols]):+.2f}")

fr = ev.group_by("coin", "day").agg(n=pl.len())["n"]
def maxdd(M):
    s = np.nanmean(M, axis=0); s = s[np.isfinite(s)]
    if s.size == 0: return 0.0
    cum = np.cumsum(s); return float((cum - np.maximum.accumulate(cum)).min())
print(f"\n=== capacity / turnover / drawdown ===")
print(f"  A/B events: {ev.height} over {int(np.isfinite(Bg).sum())} coin-days ({fr.mean():.1f}/coin-day, held 8h -> ~{fr.mean()*8/24:.1f}x overlap)")
print(f"  C coin-days {int(np.isfinite(Cg).sum())} vs B {int(np.isfinite(Bg).sum())} (wallet activity covers {100*np.isfinite(Bg).sum()/max(1,np.isfinite(Cg).sum()):.0f}% of coin-days)")
print(f"  max drawdown (cum bp, EW-coin daily): A {maxdd(A):.0f}  B {maxdd(B):.0f}  C {maxdd(C):.0f}  D {maxdd(D):.0f}")
lw = np.array([pooled(net(coinday(ev.filter(pl.col("wallet") != w), "fade"))) for w in topd])
print(f"  B leave-one-wallet-out: min {lw.min():+.2f} max {lw.max():+.2f} (base {pts['B']:+.2f}) range {lw.max()-lw.min():.2f} bp -> not 1-wallet-driven: {lw.max()-lw.min() < abs(pts['B'])+5}")
print("\nNOTE: spread/liquidity matching unavailable (no BBO in bar data) — deferred. Costs identical across A/B/C/D.")
