"""
Stage M, Job M0 — the POWER PRE-CHECK gate (per STAGE_M_ARCHITECTURE §7, corrected for the methodology audit).

Decides: is a copyable per-wallet edge RESOLVABLE from this data under an honest day-block, max-t (Romano-Wolf)
hurdle, or is it BLIND-by-construction? Measures the two levers the design audits flagged as uncertain:
  1. Variance reduction under the CORRECT benchmark. F1: the fade/coin-month benchmarks do NOT reduce variance
     (fade: rho<0 -> INCREASES it; coin-month drift: ~constant -> ~0). The only variance-reducing benchmark is a
     per-episode, DIRECTION-MATCHED market residual: resid = dir*(coin_ret - beta_coin*btc_ret)*1e4. Also test a
     coin-day timing residual (raw - coin-day mean). Report per-entry sigma for each.
  2. The REAL max-t hurdle via a joint day-block bootstrap (preserves cross-wallet correlation), not an
     assumed-independent z. Effective unit = DAY, not episode (F2).
Then MDE_RW = hurdle * per-wallet SE, count wallets that can see 15/25 bp, and a day-clustered positive control
(recovery = survives the max-t hurdle). In-memory on cohort_K_entries + BTC bars. RAM-safe. Deterministic.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; H4 = int(mk.H_MS[5]); COINS = ["BTC", "ETH", "SOL", "HYPE"]
RNG = np.random.default_rng(7)
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)

df = pl.read_parquet("out/cohort_K_entries.parquet")
lk_btc = mk._load_bars()["BTC"]
b_ts = df["b_ts"].to_numpy()
btc_now = mk._next_bar_close_vec(lk_btc, b_ts); btc_fut = mk._next_bar_close_vec(lk_btc, b_ts + H4)
btc_ret = btc_fut / btc_now - 1.0
df = df.with_columns(btc_ret=pl.Series(btc_ret), coin_ret=pl.col("raw_4h") / (pl.col("dir") * BP),
                     day=(pl.col("b_ts") // 86_400_000))

# beta per coin on TRAIN (OLS coin_ret ~ btc_ret) — outcome-independent (uses returns, not skill)
betas = {}
for coin in COINS:
    tr = df.filter((pl.col("coin") == coin) & (pl.col("split") == "train")).select("coin_ret", "btc_ret").drop_nulls()
    x = tr["btc_ret"].to_numpy(); y = tr["coin_ret"].to_numpy()
    betas[coin] = float(np.cov(x, y)[0, 1] / np.var(x)) if np.var(x) > 0 else 1.0
print("coin betas vs BTC (train):", {k: round(v, 2) for k, v in betas.items()})
df = df.with_columns(beta=pl.col("coin").replace_strict(betas, default=1.0))
df = df.with_columns(
    mktresid_4h=pl.col("dir") * (pl.col("coin_ret") - pl.col("beta") * pl.col("btc_ret")) * BP,
    coinday_mean=pl.col("raw_4h").mean().over(["coin", "day"]),
).with_columns(timingresid_4h=pl.col("raw_4h") - pl.col("coinday_mean"))

test = df.filter(pl.col("split") == "test")
BENCHES = ["raw_4h", "neut_4h", "mktresid_4h", "timingresid_4h"]
print("\n=== per-ENTRY sigma by benchmark (test window) — variance reduction check (F1) ===")
sig = {}
for c in BENCHES:
    s = float(test[c].drop_nulls().std()); sig[c] = s
    print(f"    {c:16s}: sigma = {s:6.1f} bp   (reduction vs raw: {100*(1-s/sig['raw_4h']):+.0f}%)")
best = min(BENCHES, key=lambda c: sig[c])
print(f"    -> min-variance benchmark: {best} (sigma {sig[best]:.0f} bp)")

# ---- day-level aggregation on the min-variance benchmark ----
# NOTE: require >=2 entries/day so a wallet-day mean isn't a single-entry point (stabilizes day_sd).
wd = (test.select("wallet", "day", best).drop_nulls()
      .group_by("wallet", "day").agg(m=pl.col(best).mean(), k=pl.len()))
perw = wd.group_by("wallet").agg(n_days=pl.len(), day_mean=pl.col("m").mean(), day_sd=pl.col("m").std())
covered = perw.filter((pl.col("n_days") >= 30) & pl.col("day_sd").is_not_null() & (pl.col("day_sd") > 0))
# F5 FIX: moderate each wallet's day-SD toward the pooled scale (limma-style), prior dof d0=4, then FIXED SE.
s0 = float(covered["day_sd"].median()); d0 = 4.0
covered = covered.with_columns(
    day_sd_mod=((d0 * s0 ** 2 + (pl.col("n_days") - 1) * pl.col("day_sd") ** 2) / (d0 + pl.col("n_days") - 1)).sqrt()
).with_columns(se=pl.col("day_sd_mod") / pl.col("n_days").sqrt())
print(f"\n=== day-level power on '{best}' (wallets with >=30 test days & sd>0: {covered.height}) ===")
print(f"    day-level SD across wallet-days: median {covered['day_sd'].median():.1f} bp  (pooled scale s0={s0:.1f})")
print(f"    per-wallet MODERATED SE:          median {covered['se'].median():.2f} bp  min {covered['se'].min():.2f} bp")

# ---- REAL joint day-block bootstrap max-t hurdle, studentized by the FIXED moderated SE (not recomputed) ----
cov_w = covered["wallet"].to_list()
mu = covered["day_mean"].to_numpy(); se_fix = covered["se"].to_numpy()
sub = wd.join(pl.DataFrame({"wallet": cov_w}), on="wallet", how="inner")
days = np.sort(sub["day"].unique().to_numpy())
day_idx = {int(d): i for i, d in enumerate(days)}; wmap = {w: i for i, w in enumerate(cov_w)}
S = np.zeros((len(cov_w), len(days))); Cnt = np.zeros((len(cov_w), len(days)))
for w, d, m in zip(sub["wallet"], sub["day"], sub["m"]):
    S[wmap[w], day_idx[int(d)]] = m; Cnt[wmap[w], day_idx[int(d)]] = 1
B = 4000; ncov = len(cov_w); ndays = len(days)
maxt = np.empty(B)
for b in range(B):
    pick = RNG.integers(0, ndays, ndays)                                      # resample calendar days jointly
    cnt = Cnt[:, pick].sum(1); m = S[:, pick].sum(1) / np.maximum(cnt, 1)
    t = np.where(cnt >= 20, (m - mu) / se_fix, -np.inf)                        # studentize by FIXED moderated SE
    maxt[b] = t.max()
hurdle = float(np.percentile(maxt, 99))                                        # one-sided FWER 0.01 max-t crit
print(f"\n=== REAL max-t hurdle (joint day-block bootstrap, {ncov} wallets, B={B}) ===")
print(f"    RW/SPA max-t crit @ FWER 0.01 (REAL, correlation-aware): {hurdle:.2f}  (vs assumed-independent z=4.26)")
mde_rw = hurdle * se_fix
print(f"    MDE_RW = hurdle*SE: median {np.median(mde_rw):.1f} bp | best {np.min(mde_rw):.1f} bp")
for thr in [15, 25, 40]:
    print(f"      wallets with MDE_RW <= {thr} bp: {int((mde_rw <= thr).sum())} / {ncov}")

# ---- day-clustered positive control: inject +20bp into one median-coverage wallet ----
med_days = int(covered["n_days"].median())
cand = covered.filter(pl.col("n_days").is_between(med_days - 3, med_days + 3)).sort("se", descending=True)
target = cand["wallet"][0]; ti = wmap[target]
se_t = float(se_fix[ti]); nd_t = int(covered.filter(pl.col("wallet") == target)["n_days"][0])
for inj in [10.0, 20.0]:
    t_obs = (mu[ti] + inj) / se_t
    print(f"    +{inj:.0f}bp into wallet ({nd_t} days, SE {se_t:.1f}bp): t={t_obs:.2f} vs hurdle {hurdle:.2f} "
          f"-> {'RECOVERS' if t_obs > hurdle else 'BLIND'}")

print("\n=== VERDICT ===")
if (mde_rw <= 25).sum() == 0:
    print("BLIND-by-construction at <=25bp: no wallet can resolve a copyable edge under the honest max-t hurdle.")
elif (mde_rw <= 25).sum() < 10:
    print(f"MARGINAL: {int((mde_rw<=25).sum())} best-covered wallets reach <=25bp; the rest blind. Restricted pre-registered test possible.")
else:
    print(f"POWERED for {int((mde_rw<=25).sum())} wallets at <=25bp -> proceed to full SPA/RW harness.")
