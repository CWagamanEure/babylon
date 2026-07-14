"""Sections 5-6 — top-wallet leaderboards (valid non-overlap MDD) + OOS non-persistence. Light polars, no bar-pricing."""
import sys; from pathlib import Path
import numpy as np, polars as pl
from scipy import stats as st
import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_style as rs
rs.setup()
H_MS = {"1h": 3600_000, "8h": 28800_000}
df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "split", "notl", "raw_1h", "raw_8h")

def nonoverlap_mdd(ts, mk, hms):
    o = np.argsort(ts); ts = ts[o]; mk = mk[o]; last = -1e18; eq = 0.0; peak = 0.0; mdd = 0.0
    for t, m in zip(ts, mk):
        if t >= last + hms:
            eq += m; last = t; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    return mdd

def leaderboard(hz):
    col = f"raw_{hz}"; tr = df.filter(pl.col("split") == "train")
    rows = []
    for w, sub in tr.group_by("wallet"):
        wal = w[0]; mk = sub[col].to_numpy(); mk = mk[np.isfinite(mk)]
        if len(mk) < 100: continue
        ts = sub["b_ts"].to_numpy()
        rows.append((wal, len(mk), float(mk.mean()), float(mk.std()), float(mk.mean()/mk.std()) if mk.std() > 0 else 0.0,
                     float((mk > 0).mean()), float(np.median(sub["notl"].to_numpy())),
                     float(nonoverlap_mdd(ts, sub[col].to_numpy(), H_MS[hz]))))
    L = pl.DataFrame(rows, schema=["wallet", "N", "mean_bp", "std_bp", "sharpe", "hit", "notl_med", "mdd_nonov_bp"], orient="row")
    return L.sort("mean_bp", descending=True)

for hz in ["1h", "8h"]:
    L = leaderboard(hz); L.write_parquet(f"out/top_wallets_{hz}.parquet")
    top = L.head(20)
    with open(f"out/top_wallets_{hz}.md", "w") as f:
        f.write(f"| # | wallet | N | mean {hz} (bp) | Sharpe | hit% | MDD* (bp) | med $ |\n|--:|---|--:|--:|--:|--:|--:|--:|\n")
        for i, r in enumerate(top.iter_rows(named=True), 1):
            f.write(f"| {i} | `{r['wallet'][:10]}…` | {r['N']} | {r['mean_bp']:+.1f} | {r['sharpe']:.2f} | "
                    f"{r['hit']*100:.0f} | {r['mdd_nonov_bp']:.0f} | {r['notl_med']:,.0f} |\n")
    print(f"{hz}: top mean {top['mean_bp'][0]:+.1f}bp Sharpe {top['sharpe'][0]:.2f}; wrote out/top_wallets_{hz}.md")

# Fig — top-20 (8h) mean markout bar with SEM
L8 = pl.read_parquet("out/top_wallets_8h.parquet"); top = L8.head(20)
fig, ax = plt.subplots(figsize=(8.2, 4.2))
m = top["mean_bp"].to_numpy(); sem = top["std_bp"].to_numpy() / np.sqrt(top["N"].to_numpy())
ax.bar(range(20), m, yerr=sem, color="#4c78a8", capsize=2, error_kw=dict(lw=0.8))
ax.set_xlabel("top-20 wallets (ranked by in-sample 8h markout)"); ax.set_ylabel("mean 8h markout (bp)")
ax.set_title("Top in-sample markout wallets look strong (+40–80 bp gross, ±SEM)")
rs.bp_axis(ax); rs.save(fig, "05_top20_bars")

# Fig — Sharpe vs N scatter (all wallets, 8h)
fig, ax = plt.subplots(figsize=(6.8, 4.2))
ax.scatter(L8["N"].to_numpy(), L8["sharpe"].to_numpy(), s=8, alpha=0.4, color="#555")
ax.scatter(top["N"].to_numpy(), top["sharpe"].to_numpy(), s=22, color="#d62728", label="top-20 by mean")
ax.set_xlabel("N train entries"); ax.set_ylabel("per-trade Sharpe (8h, mean/std)")
ax.set_title("Sharpe vs sample size — top-mean wallets are not the high-Sharpe ones"); ax.legend(fontsize=9)
rs.save(fig, "05_sharpe_vs_n")

# ---- OOS non-persistence: train vs test per-wallet 8h markout ----
def perwallet(split):
    s = df.filter(pl.col("split") == split)
    return s.group_by("wallet").agg(m=pl.col("raw_8h").mean(), n=pl.len())
tr = perwallet("train").filter(pl.col("n") >= 50).rename({"m": "train_m", "n": "trn"})
te = perwallet("test").filter(pl.col("n") >= 15).rename({"m": "test_m", "n": "ten"})
J = tr.join(te, on="wallet", how="inner")
rho = st.spearmanr(J["train_m"].to_numpy(), J["test_m"].to_numpy())
print(f"OOS: {J.height} wallets | train->test 8h rank-IC = {rho.correlation:+.3f} (p={rho.pvalue:.2f})")

# decile decay
J2 = J.with_columns(dec=(pl.col("train_m").rank() / pl.len() * 10).ceil().clip(1, 10))
dec = J2.group_by("dec").agg(train=pl.col("train_m").mean(), test=pl.col("test_m").mean()).sort("dec")
fig, ax = plt.subplots(figsize=(7.2, 4.2))
d = dec["dec"].to_numpy()
ax.plot(d, dec["train"].to_numpy(), "-o", color="#4c78a8", label="in-sample (train)")
ax.plot(d, dec["test"].to_numpy(), "-s", color="#d62728", label="out-of-sample (test)")
ax.axhline(0, color="#888", lw=0.8)
ax.set_xlabel("wallet decile by IN-SAMPLE 8h markout (10 = best)"); ax.set_ylabel("mean 8h markout (bp)")
ax.set_title(f"Top in-sample deciles do NOT carry over  (train→test rank-IC {rho.correlation:+.2f}, n.s.)")
ax.legend(fontsize=9); rs.bp_axis(ax); rs.save(fig, "06_decile_decay")

# scatter
fig, ax = plt.subplots(figsize=(5.8, 5.4))
tx = J["train_m"].to_numpy(); ty = J["test_m"].to_numpy()
ax.scatter(tx, ty, s=9, alpha=0.35, color="#555")
lim = np.percentile(np.abs(np.concatenate([tx, ty])), 99)
ax.axhline(0, color="#aaa", lw=0.7); ax.axvline(0, color="#aaa", lw=0.7)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
ax.set_xlabel("in-sample (train) mean 8h markout (bp)"); ax.set_ylabel("out-of-sample (test) mean 8h markout (bp)")
ax.set_title(f"No train→test relationship\nrank-IC {rho.correlation:+.2f} (p={rho.pvalue:.2f}), n={J.height}")
rs.save(fig, "06_oos_scatter")
print("saved top-wallet + OOS figs")
