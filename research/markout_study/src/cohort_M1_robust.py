"""
Stage M1 — pre-specified robustness battery on the FROZEN patched result. No new strategy, no re-ranking.
Reads out/cohort_M1_ep.parquet (per-episode priced net/alpha for the frozen top-20) + out/cohort_M1_frozen.txt (ev/attr).
Diagnostics (all requested): drop-best-day, leave-one-day-out, cumulative alpha, monthly, token, concentration,
equal-weight-wallet vs wallet-day-pooled basket, frozen-cost vs realistic-cost. RAM-free (tiny frame).
"""
import numpy as np, polars as pl
RNG = np.random.default_rng(0)
COST_FROZEN = {"BTC": 5.0, "ETH": 5.0, "SOL": 8.0, "HYPE": 8.0}
COST_REAL = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0}   # campaign mk.COST_BPS
DELTA = {k: COST_REAL[k] - COST_FROZEN[k] for k in COST_FROZEN}

txt = open("out/cohort_M1_frozen.txt").read().split("\n")
ev = txt[txt.index("EV") + 1: txt.index("ATTR")]
ep = pl.read_parquet("out/cohort_M1_ep.parquet").filter((pl.col("split") == "test") & pl.col("wallet").is_in(ev))
ep = ep.with_columns(net_real=pl.col("net") - pl.col("coin").replace_strict(DELTA, default=0.0),
                     month=((pl.col("day") * 86_400_000) // 86_400_000 % 100000))  # placeholder; real month below
# month label from day index (days since epoch -> YYYYMM)
ep = ep.with_columns(mon=pl.from_epoch(pl.col("day") * 86400, time_unit="s").dt.strftime("%Y-%m"))

def wd_matrix(frame, col):
    wd = frame.group_by("wallet", "day").agg(v=pl.col(col).mean())
    ws = ev; ds = np.sort(wd["day"].unique().to_numpy())
    wi = {w: i for i, w in enumerate(ws)}; di = {int(d): i for i, d in enumerate(ds)}
    M = np.full((len(ws), len(ds)), np.nan)
    for w, d, v in zip(wd["wallet"], wd["day"], wd["v"]):
        M[wi[w], di[int(d)]] = v
    return M, ds

def ew(M):   # equal-weight wallet: mean over wallets of per-wallet nanmean-over-days
    pw = np.array([np.nanmean(M[i]) if np.isfinite(M[i]).any() else np.nan for i in range(M.shape[0])])
    return np.nanmean(pw)
def pooled(M):  # equal-weight wallet-day cell
    return np.nanmean(M)
def boot_ci(M, stat):
    ND = M.shape[1]; bs = np.empty(2000)
    for b in range(2000):
        p = RNG.integers(0, ND, ND)
        with np.errstate(invalid="ignore"): bs[b] = stat(M[:, p])
    return np.nanpercentile(bs, 2.5), np.nanpercentile(bs, 97.5), (bs <= 0).mean()

Mnet, ds = wd_matrix(ep, "net"); Mrealnet, _ = wd_matrix(ep, "net_real"); Mal, _ = wd_matrix(ep, "alpha")
print(f"frozen evaluable wallets: {len(ev)} | test days: {len(ds)}\n")

# 7. equal-weight-wallet vs wallet-day-pooled basket (headline both families)
print("=== [7] basket definition: equal-weight-wallet vs wallet-day-pooled ===")
for name, M in [("A net (frozen cost)", Mnet), ("B alpha vs fade", Mal)]:
    e = ew(M); elo, ehi, ep_ = boot_ci(M, ew); p = pooled(M); plo, phi, pp = boot_ci(M, pooled)
    print(f"  {name:22s}: EW-wallet {e:+.2f} [{elo:+.2f},{ehi:+.2f}] p={ep_:.3f} | pooled {p:+.2f} [{plo:+.2f},{phi:+.2f}] p={pp:.3f}")

# 8. cost sensitivity (A only; B cost-invariant)
print("\n=== [8] cost assumption (Family A; B is cost-invariant) ===")
for name, M in [("frozen 5/5/8/8", Mnet), ("realistic 8/8/10/14", Mrealnet)]:
    e = ew(M); lo, hi, p = boot_ci(M, ew)
    print(f"  A EW-wallet, {name:20s}: {e:+.2f} bp [{lo:+.2f},{hi:+.2f}] p={p:.3f}")

# day-level series (pooled cells per day) for day diagnostics
def daily_series(frame, col):
    g = frame.group_by("day").agg(s=pl.col(col).sum(), n=pl.len()).sort("day")
    return g["day"].to_numpy(), g["s"].to_numpy(), g["n"].to_numpy()
dday, dS, dN = daily_series(ep, "alpha"); dSnet, _ = daily_series(ep, "net")[1], None
_, dSnet, _ = daily_series(ep, "net")
pool_al = dS.sum() / dN.sum(); pool_net = dSnet.sum() / dN.sum()

# 1. remove single best test day (day with largest positive alpha contribution)
print("\n=== [1] remove single best test day (pooled) ===")
worst = np.argmax(dS)   # day contributing most positive total alpha
keep = np.arange(len(dday)) != worst
al_drop = dS[keep].sum() / dN[keep].sum(); net_drop = dSnet[keep].sum() / dN[keep].sum()
print(f"  best day = {int(dday[worst])} contributes {dS[worst]:.0f} bp*cells ({dN[worst]} cells)")
print(f"  B alpha: full pooled {pool_al:+.2f} -> drop-best {al_drop:+.2f} bp | A net: {pool_net:+.2f} -> {net_drop:+.2f}")

# 2. leave-one-day-out (range of pooled alpha)
loo = np.array([np.delete(dS, k).sum() / np.delete(dN, k).sum() for k in range(len(dday))])
print(f"\n=== [2] leave-one-day-out pooled B alpha: min {loo.min():+.2f}  max {loo.max():+.2f}  (full {pool_al:+.2f}) ===")
print(f"  most influential day drop -> {loo.min():+.2f} (day {int(dday[np.argmin(loo)])}); no single day flips the sign: {(loo>0).all()==(pool_al>0)}")

# 3. cumulative test alpha through time
cum = np.cumsum(dS); frac_from_topday = np.abs(dS).max() / np.abs(dS).sum()
print(f"\n=== [3] cumulative pooled alpha path: final {cum[-1]:.0f} bp*cells over {len(dday)} days ===")
q = [int(len(dday)*f) for f in (0.25, 0.5, 0.75, 1.0)]
print("  cum at 25/50/75/100% of days:", [f"{cum[min(i,len(cum)-1)]:.0f}" for i in q], "(steady if monotone-ish, jump if one step dominates)")

# 4. monthly decomposition
print("\n=== [4] monthly decomposition (pooled) ===")
mo = ep.group_by("mon").agg(net=pl.col("net").mean(), alpha=pl.col("alpha").mean(), n=pl.len()).sort("mon")
for r in mo.iter_rows(named=True):
    print(f"  {r['mon']}: A net {r['net']:+.2f}  B alpha {r['alpha']:+.2f}  (n={r['n']})")

# 5. token decomposition
print("\n=== [5] token decomposition (pooled, per coin) ===")
tk = ep.group_by("coin").agg(net=pl.col("net").mean(), alpha=pl.col("alpha").mean(), n=pl.len()).sort("n", descending=True)
for r in tk.iter_rows(named=True):
    print(f"  {r['coin']:5s}: A net {r['net']:+.2f}  B alpha {r['alpha']:+.2f}  (n={r['n']})")

# 6. concentration (abs share)
day_share = np.abs(dS).max() / np.abs(dS).sum()
tok_abs = ep.group_by("coin").agg(a=pl.col("alpha").sum()).with_columns(aa=pl.col("a").abs())
tok_share = tok_abs["aa"].max() / tok_abs["aa"].sum()
print(f"\n=== [6] concentration (abs) ===\n  top-day share {day_share:.2f} | top-token share {float(tok_share):.2f}")

print("\n=== SUMMARY ===")
print(f"  Family B (vs fade) EW-wallet is the load-bearing incremental number; robust across the above? "
      f"pooled {pool_al:+.2f}, drop-best {al_drop:+.2f}, LOO∈[{loo.min():+.2f},{loo.max():+.2f}].")
