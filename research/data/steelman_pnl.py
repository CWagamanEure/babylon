"""Steelman attack #4: does REALIZED-PnL rank persist p1->p2 (the actual copy quantity), where timing_alpha did
not? Per (wallet,coin): sum realized_net_usd for episodes CLOSING in each period; rank-correlate; deployment sim
= select top-decile p1, measure p2. Also per-coin timing persistence. Bounded: one grouped scan of the episode
lake. NOT a separate agent (budget blocked the steelman agent) — independence caveat noted."""
from __future__ import annotations
import numpy as np, duckdb
from .markout import REPO_ROOT

EP = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
SPLIT = "epoch_ms(TIMESTAMP '2026-02-01')"
END = "epoch_ms(TIMESTAMP '2026-06-29')"
con = duckdb.connect(); con.execute("SET enable_progress_bar=false"); con.execute("PRAGMA memory_limit='4GB'")
con.execute("PRAGMA threads=2"); con.execute(f"SET temp_directory='{REPO_ROOT/'.tmp'}'")

con.execute(f"""CREATE TEMP TABLE pnl AS
  SELECT wallet, coin,
    sum(realized_net_usd) FILTER (close_ts < {SPLIT}) p1_pnl,
    count(*)              FILTER (close_ts < {SPLIT}) p1_n,
    sum(realized_net_usd) FILTER (close_ts >= {SPLIT} AND close_ts < {END}) p2_pnl,
    count(*)              FILTER (close_ts >= {SPLIT} AND close_ts < {END}) p2_n
  FROM read_parquet('{EP}', hive_partitioning=true)
  WHERE close_ts IS NOT NULL GROUP BY wallet, coin""")

# require enough activity in both periods
b = con.execute("SELECT p1_pnl, p2_pnl FROM pnl WHERE p1_n>=20 AND p2_n>=20").fetchnumpy()
p1, p2 = np.asarray(b["p1_pnl"], float), np.asarray(b["p2_pnl"], float)
n = len(p1)
r1, r2 = np.argsort(np.argsort(p1)), np.argsort(np.argsort(p2))
rho = float(np.corrcoef(r1, r2)[0, 1])
print(f"REALIZED-PnL rank persistence (wallet-coins active >=20 eps both halves): n={n:,}")
print(f"  Spearman rho(p1_pnl, p2_pnl) = {rho:+.3f}")

# deployment sim: select top-decile p1 pnl, measure p2 pnl
thr = np.quantile(p1, 0.90)
sel = p2[p1 >= thr]
rest = p2[p1 < thr]
m, sd = sel.mean(), sel.std(ddof=1); sem = sd/np.sqrt(len(sel))
print(f"  select TOP-DECILE p1 PnL (n={len(sel):,}): p2 mean PnL = ${m:,.0f} "
      f"[95% CI ${m-1.96*sem:,.0f}, ${m+1.96*sem:,.0f}], median ${np.median(sel):,.0f}, "
      f"frac p2>0 = {100*np.mean(sel>0):.1f}%")
print(f"  vs rest p2 mean ${rest.mean():,.0f} (median ${np.median(rest):,.0f}, frac>0 {100*np.mean(rest>0):.1f}%)")
print(f"  winners->winners: of top-decile p1, {100*np.mean(p2[p1>=thr]>0):.1f}% profitable in p2 "
      f"(base rate {100*np.mean(p2>0):.1f}%)")

# also: does p1>0 predict p2>0 at all? (sign persistence)
pos1 = p1 > 0
print(f"\n  sign persistence: p1-profitable wallets are p2-profitable "
      f"{100*np.mean(p2[pos1]>0):.1f}% vs p1-losing {100*np.mean(p2[~pos1]>0):.1f}%")
