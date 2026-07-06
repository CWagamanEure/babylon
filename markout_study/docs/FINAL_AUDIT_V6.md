# FINAL_AUDIT_V6 — pre-flight verification for report v6

Targeted cleanup: no new selectors, horizons, or subgroups. Each issue, code location, verified result, correction. Recomputations `src/verify_v6.py` → `out/v6.json`; eligibility `src/eligibility_audit.py` → `out/eligibility_train.parquet`.

## Phase 1 — PDF production
Report built with `pandoc --pdf-engine=xelatex -V mainfont=Palatino -V monofont=Menlo`; Palatino carries ≥ ≤ β τ ρ and math symbols (Latin Modern lacked them). BTC 24h star removed (day-cluster and 5-day-block intervals disagree at zero — both shown, no star). Page-by-page visual inspection performed before delivery; figures sized within margins, summary table not split, appendix rebalanced.

## Phase 2 — Eligibility leakage (real, mostly immaterial)
`hold_size_dist.py:7` computes taker share, median hold and fill count over the **whole window**; only `n_train` is training-scoped. Recomputed training-only: 1,557/1,694 (91.9%) still qualify; 137 leak-driven (mostly median-hold). Of the 121 recurring wallets, 108 are training-clean. Field-relative B on the clean 108 = +11.1 [+4.3, +17.5] p<0.001 (vs +9.8 full) — robust. Correction: cohort described as predominantly training-defined, not cleanly historical; robustness reported. See `ELIGIBILITY_WINDOW_AUDIT.md`.

## Phase 3 — Two pre-entry conventions named separately
Event-study ordinate `E_τ = dir·(P_{t+τ}/P_t − 1)`, τ<0 → **"Earlier price relative to entry, aligned in trade direction"** (positive = price later moved against the trade into entry). Conditional regressor `R_pre = dir·(P_t/P_{t−8h} − 1)` → **"Pre-entry return in trade direction"** (negative = entered against the preceding move). Both named exactly, each with a worked example; no longer both called "signed pre-entry move."

## Phase 4 — Fixed-cohort weighting reframed
Equal-wallet = wallet-quality question; wallet-day = deployable-activity question. Wallet-day and wallet-coin-day described as related activity-weighted estimators, not independent confirmations. "Does not reward breadth" language removed; replaced with "concentrated in more active wallet-days rather than broadly established across all selected wallets."

## Phase 5 — Portfolio rule stated; absolute figures are markout statistics
Exact wallet-day aggregation documented (`PORTFOLIO_RULE.md`): equal-weight entries within a cell, equal weight per cell, cost per entry, **no capital constraint, no netting of overlapping 8-hour positions, no coin cap**. Because capital is not bounded, absolute figures are labelled average cost-adjusted markout statistics, not strategy returns.

## Phase 6 — Absolute inference added
A gross and A cost-adjusted now carry point, 95% CI, and p(>0) under all three weightings. **Cost-adjusted absolute is not resolved above zero under any weighting** (p = 0.34 wallet-day / 0.92 equal-wallet / 0.25 wallet-coin-day). Profitability after costs is not claimed.

## Phase 7 — Time-series inference strengthened
B (wallet-day) reported under calendar-day cluster (+9.8, p=0.001), 7-day and 5-day **overlapping** moving-block (+9.8, p=0.006 / 0.004), by-month (May negative) and leave-one-month-out (all positive, +6.6…+15.7). Moving-block defined correctly (overlapping blocks, stated length, last block truncated, joint resample). Daily p=0.001 flagged as mildly optimistic relative to weekly/one-month-out. See `FIXED_COHORT_ROBUSTNESS.md`.

## Phase 8 — Coin decomposition
Per-coin A/B/D with CIs and counts; B positive with interval excluding zero for BTC (+7.1), ETH (+17.0), SOL (+13.6), HYPE +7.5 (unresolved). Coin-balanced B +11.3; excluding SOL +9.6. Corrects the earlier "SOL-concentrated" framing: the effect is broad across coins (ETH strongest), not a single-coin artifact.

## Phase 9 — Benchmark wording
"Execution effects cancel" replaced by "coin, timestamp, horizon, pricing convention and assumed symmetric costs are matched"; explicit note that actual execution need not cancel (opposite sides of book, different spread/depth/slippage). No BBO-based execution claim.

## Phase 10 — Recurrence interpretation
States the permutation result establishes only that monthly top-decile membership recurs more than random reassignment among eligible wallets; it does not establish private information, profitability, unique skill, incremental value over reversal, or optimality of the ≥2-month cutoff (described as an operational coverage threshold).

## Phase 11 — Rolling uncertainty
Ten fold-level ICs reported (mean +0.11, median +0.12, sd 0.05, 9/10 positive, sign test p=0.02, leave-one-month-out mean IC [+0.10, +0.12]); calendar time is the inference unit. Decile gradient survives leave-one-month-out. See `ROLLING_TIME_INFERENCE.md`.

## Phase 12 — Behavioral unit
Reported both entry-weighted and equal-wallet (per-wallet median first). Equal-wallet recurring vs rest: signed pre-entry −80.7 vs −9.4, absolute pre-entry 177.7 vs 132.9, stretch 313.9 vs 196.4, vol 22.7 vs 18.7 bp — same conclusion. Each variable now has formula, lookback, sign convention, aggregation unit, and a direction-aligned trailing-extreme definition.

## Phase 13 — Nested statistic removed
The −0.0003 cross-fit IC increment is removed; `out/cohort_P2_models.npz` stores only coefficients, not the cross-validated ICs needed for an interpretable model table, so the orphan statistic is dropped rather than shown.

## Phase 14 — Conclusion
Rewritten to the conservative standard (activity-weighted positive, equal-wallet weaker, concentrated in wallet-days, no resolved fade increment, absolute post-cost profitability not established, exposure-to-reversal reading). Banned phrasings removed.
