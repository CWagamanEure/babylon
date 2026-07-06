# T-stat informed-trader certification — replication spec
For replicating the badge-v2 methodology on another repo/tape. Companion: REPORT.md §5,
CAMPAIGN_LOG.md (full history), badge_v2.py (reference implementation).

## Requirements
1. Fills tape: ts, coin, px, sz, side, taker/maker flag, TWAP/liquidation flag if available.
2. Price bars per coin (5m or finer; finer matters below 4h horizons).
3. >=6 months of data (we used 11).

## Steps
1. DECISION EVENTS: reconstruct positions per wallet x coin; events = position-INCREASING
   taker fills; opening component only on sign flips; exclude TWAP/liquidation fills from
   events but keep them in position reconstruction.
2. POST-FILL PRICING: markout = signed move from close of FIRST bar strictly AFTER the fill
   to first bar after t+24h; skip if no bar within 30min of either endpoint; guard at
   +-5000bp only (no tighter winsorization).
3. DEMEAN: subtract the mean markout of ALL candidates' events in the same (coin, calendar
   month); >=50 events per cell, pooled-month fallback. One constant per cell — computable
   at entry time.
4. POSITIONS: cluster events by (coin, UTC day) -> one observation (mean demeaned markout).
   Drop events whose 24h window crosses a month boundary if rank/evaluate windows will ever
   be adjacent.
5. STATISTIC: per wallet with >=50 positions, t = mean / (std / sqrt(N)).
6. FLIP-NULL (mandatory): per wallet, flip the sign of each calendar-WEEK block of positions
   randomly (+-1), recompute t; ~20 draws/wallet. This null keeps all correlation/overlap/
   fat tails, has zero skill.
7. CERTIFY: empirical FDR = expected null count above T / observed count above T. Check the
   NEGATIVE side at -T: symmetric elevation = artifact, asymmetric = skill. (Ours at T=4:
   57 obs vs ~15 null; negative 19 vs 15.)
8. ENTITY DEDUP among certified: links = co-timed entries (same coin+direction, +-10min,
   >=25% of either wallet) OR daily-PnL corr >=0.7 over >=40 shared days OR exposure cosine
   >=0.95 with corr >=0.5; union-find; count SOURCES not wallets (ours: 57 -> 43).

## Traps — each produced a false discovery for us first
1. Pricing inside the entry's own bar/candle (our original fake edge was 100% this).
2. Benchmarks whose windows can start before the entry (fake two-sided "timing skill",
   z=+3.86, all artifact). Benchmark must be computable at entry time.
3. Winsorizing outcomes (hid blowups; manufactured fake transfer z=+2.7 -> raw z=+0.4).
4. Counting fills as observations (cluster to coin-day minimum).
5. Textbook p-values (residual correlation ~2x variance -> 12x fake tail). Flip-null only.
6. Skipping the negative-side control (free artifact detector).
7. Pooled-market demeaning (coin-camping masquerades as timing; demean per coin-month).
8. Wallets != people (dedup; our 8-wallet cluster = one strategy).
9. Believing single rows (per-wallet FDR floor ~26% at ~1yr of data; the LIST is ~74%
   genuine — deploy baskets, never names).
10. Reusing test months (fix rules first, look once, keep a forward month untouched).

## Sanity anchor
Our eligible field's mean 24h markout: -16bp/entry (median -13). A POSITIVE field mean in
your replication usually means an in-bar pricing leak.
