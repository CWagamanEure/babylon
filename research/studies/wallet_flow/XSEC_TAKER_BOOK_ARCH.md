# XSEC TAKER BOOK — architecture (2026-07-10)

## Why (user steer: "we're still missing something that makes this work with TAKER fills")
The decompose D5 cost ladder declared taker-dead — but it evaluated the WORST cell (quintile @ best_h=2,
smallest gross, highest turnover) and used a NAIVE cost model (full round-trip charged every rebalance =
100% turnover assumption). Two corrections make taker plausibly viable and, critically, taker SIDESTEPS the
unresolved maker-fill/adverse-selection gate (a taker order fills for certain at a KNOWN cost):

1. **Cell selection raises gross/crossing above the fixed taker hurdle.** Clean-fold gross/crossing: quintile
   h4 +4.4, decile h4 +7.9 [+2.3,+14.1], mid-dispersion quintile h4 +10.7 [+5.3,+16.2]. Alt taker RT hurdle
   ≈ 4.8–7.6 bp (prior line work). Decile & mid-dispersion clear it at the point estimate.
2. **Name-turnover-aware cost.** V-trail is a PERSISTENT signal (survives the gap) → a name in the top decile
   tends to STAY → you HOLD, not re-cross. Real taker cost = fee × NAME entry/exit rate, far below the
   rebalance-clock full-RT charge. A no-trade band (hysteresis on decile membership) suppresses churn further
   (the lever that rescued Result 9's taker book).

## Estimand — a real long-short book with realistic taker cost, NOT a per-hour spread
Reuse the SAME leak-free panel + V-trail L2 h_train=4 signal as `xsec_flow_decompose.py` (identical cells).
Then SIMULATE a held portfolio:

- **Universe / entry rule per hour t (causal):** rank alts by s_inf[t]. Target book = long top-K, short
  bottom-K (K by decile default = round(0.10·n_active_t) per side; also test quintile/ventile). Optional
  filters (pre-registered): ADV tier ∈ {high, high+mid}; regime ∈ {mid-dispersion only, all}.
- **No-trade band (hysteresis):** a name already held is KEPT until it leaves the top-Q2 (Q2 > Q1, e.g. hold
  top-15% once you're long top-10%). New entries only from top-Q1. This is the turnover knob; sweep the band.
- **Turnover & cost:** at each rebalance step (every REB hours), compute the set of names entered/exited vs the
  held book; taker cost charged ONLY on the traded notional = fee_rt × (Δnames / book_size). fee_rt per name =
  2·(taker_fee + half_spread_alt). half_spread per alt from data if available (asset_ctx mark/oracle or L2);
  else per-ADV-tier constants calibrated to the 4.8–7.6 bp line estimate. Report net under a COST LADDER
  {optimistic 4.8, mid 6.0, pessimistic 7.6, per-alt-measured}.
- **Return:** the book's realized forward return per REB step = mean(s_inf-long fwd resid) − mean(short fwd
  resid) over the hold, using the SAME fwd-residual VALUES (bp) as decompose. Net = gross − turnover·cost.
- **Reporting metric = net bp per HOUR** (not per crossing), so horizon/turnover trade off honestly. Also gross
  SR (day-block) for context.

## Discipline (over-carry — this is a forking-path minefield; the swarm flagged the stacked cell)
- **PRE-REGISTER ONE primary config BEFORE the sweep:** V-trail, L2 (⊥crowd,⊥mom), h_train=4, REB=4h, DECILE,
  no-trade band top-10%/hold-15%, full universe. PRIMARY metric = net-per-hour @6bp taker on CLEAN folds
  (≥202603) with a **coin-block (sector) bootstrap** CI (NOT day-block — coins are the correlated unit).
- Secondaries (directional, pre-stated stronger-expected, reported but NOT the headline): mid-dispersion-only;
  high-ADV subset; quintile/ventile; REB ∈ {2,6,8}; band sweep. Each an explicit extra look → note it.
- **Walk-forward the primary:** expanding train picks nothing (config is frozen); just report per-fold net so
  a single lucky month can't carry it. Sign test over folds.
- Report the naive-cost (full-RT) net alongside turnover-aware net so the improvement from turnover accounting
  is explicit and auditable.
- Positive control inherited (decompose already showed the pipeline recovers +0.72).

## Decision
- **GREEN (taker-deployable):** primary net-per-hour > 0 with coin-block CI excluding 0 on clean folds @≤6bp
  taker, AND per-fold mostly-positive (sign test), AND turnover-aware cost is not the sole reason (naive-cost
  net also ≥ ~0 or close). Then → forward paper test (droplet), no fill model needed.
- **AMBER:** point est positive, CI includes 0 → short-sample/underpowered; report honestly, candidate for
  forward paper (MDE-limited, like Result 9), not a kill.
- **RED (taker earned-negative):** clean-fold net < 0 with CI excluding positive at a realistic (≤6bp) taker →
  taker genuinely dead, fall back to the maker-fill path (the harder gate).

## Reuse / build
`xsec_taker_book.py` imports A/S0/ADJ + reuses decompose's panel+q_trail+run_horizon(h=4,no-placebos)+residualize
to get s_inf per cell, then adds the portfolio simulator (membership, hysteresis, name-turnover cost, coin-block
bootstrap). No new data ingest. Then a focused audit swarm (correctness of the turnover-cost accounting +
over-carry on the pre-registration discipline).
