"""11-filter wallet-cohort screen (EXPLORATORY — not a Gate-A verdict). Joins Tier-1 hygiene (Table 2, latest
expanding cutoff) to Tier-2 timing_alpha (Table 2b). Markout filters (3,7,8,10,11) use the GLOBAL market-adjusted
timing_alpha (raw − dir·μ_h(≤C)); to avoid horizon-argmax cherry-picking (over-carry), the markout bars must
hold at ALL 4 primary horizons (consistency), not the best one. Prints a funnel."""
import glob
import duckdb

C = "202606"
con = duckdb.connect(); con.execute("SET enable_progress_bar=false"); con.execute("PRAGMA memory_limit='4GB'")

# Tier-2b markout pivoted wide over the 4 primary horizons, per (wallet,coin)
mk_parts = "data/derived/addr_coin_markout/coin=*/horizon=*/part.parquet"
con.execute(f"""CREATE TEMP TABLE mk AS
  SELECT wallet, coin,
    max(n_weeks) n_weeks, max(n_ep) n_ep,
    {', '.join(f"max(est_g)  FILTER (horizon='{h}') est_{h}"  for h in ['1h','2h','4h','8h'])},
    {', '.join(f"max(lb_g)   FILTER (horizon='{h}') lb_{h}"   for h in ['1h','2h','4h','8h'])},
    {', '.join(f"max(med_g)  FILTER (horizon='{h}') med_{h}"  for h in ['1h','2h','4h','8h'])},
    {', '.join(f"max(h1_g)   FILTER (horizon='{h}') h1_{h}"   for h in ['1h','2h','4h','8h'])},
    {', '.join(f"max(h2_g)   FILTER (horizon='{h}') h2_{h}"   for h in ['1h','2h','4h','8h'])},
    {', '.join(f"max(dropbest_g) FILTER (horizon='{h}') db_{h}" for h in ['1h','2h','4h','8h'])}
  FROM read_parquet('{mk_parts}', hive_partitioning=true) GROUP BY wallet, coin""")

t2 = f"data/derived/addr_coin_features/cutoff={C}/window=expanding/coin=*/part.parquet"
con.execute(f"""CREATE TEMP TABLE base AS
  SELECT t.address AS wallet, t.coin,
    t.n_fills, t.n_active_iso_weeks, t.sum_traded_notional_usd,
    CASE WHEN t.n_fills>0 THEN t.n_flagged_fills::DOUBLE/t.n_fills END AS twap_share,
    CASE WHEN t.n_fills>0 THEN t.n_liq_fills::DOUBLE/t.n_fills END AS liq_share,
    t.top1_grossprofit_share, t.net_realized_pnl,
    mk.* EXCLUDE (wallet, coin)
  FROM read_parquet('{t2}', hive_partitioning=true) t
  JOIN mk ON mk.wallet=t.address AND mk.coin=t.coin""")

# the 11 filters as SQL predicates (markout ones require ALL 4 horizons — consistency, no cherry-pick)
ALL = ['1h','2h','4h','8h']
def allh(expr): return " AND ".join(expr.format(h=h) for h in ALL)
F = [
  ("0. base (Table2 ⋈ markout)",                 "TRUE"),
  ("1. orders (n_fills) >= 250",                 "n_fills >= 250"),
  ("2. active weeks >= 8",                       "n_active_iso_weeks >= 8"),
  ("4. volume >= $1M",                           "sum_traded_notional_usd >= 1e6"),
  ("5. twap/flagged share < 30%",                "twap_share < 0.30"),
  ("6. liquidation share < 10%",                 "coalesce(liq_share,0) < 0.10"),
  ("9. best-episode share < 30%",                "coalesce(top1_grossprofit_share,1) < 0.30"),
  ("11. timing_alpha>0 & CI-LB>0 (all horizons)", allh("est_{h}>0 AND lb_{h}>0")),
  ("8. median timing_alpha > 0 (all horizons)",  allh("med_{h}>0")),
  ("3. timing_alpha>=8bp BOTH halves (all hz)",  allh("h1_{h}>=8 AND h2_{h}>=8")),
  ("10. drop-best-day still >0 (all horizons)",  allh("db_{h}>0")),
  ("7. mean est across horizons > 0 (AUC)",      "(est_1h+est_2h+est_4h+est_8h)/4 > 0"),
]
conds, prev = [], None
print(f"{'FILTER':<46}{'remaining':>10}{'  (drop)':>9}")
for label, cond in F:
    conds.append(cond)
    where = " AND ".join(f"({c})" for c in conds)
    n = con.execute(f"SELECT count(*) FROM base WHERE {where}").fetchone()[0]
    drop = "" if prev is None else f"-{prev-n:,}"
    print(f"{label:<46}{n:>10,}{drop:>9}")
    prev = n

print("\nSurviving cohort (all 11 filters), top by mean timing_alpha:")
where = " AND ".join(f"({c})" for _, c in F)
rows = con.execute(f"""SELECT wallet, coin, n_ep, n_weeks,
    round((est_1h+est_2h+est_4h+est_8h)/4,1) ta_auc, round(lb_4h,1) lb4h,
    round(net_realized_pnl,0) pnl FROM base WHERE {where}
    ORDER BY ta_auc DESC LIMIT 20""").fetchall()
for r in rows: print("  ", r)
print(f"\ntotal surviving:", con.execute(f"SELECT count(*) FROM base WHERE {where}").fetchone()[0])
print("distinct wallets:", con.execute(f"SELECT count(DISTINCT wallet) FROM base WHERE {where}").fetchone()[0])
