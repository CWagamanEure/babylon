# Change log — report v2

## Substantive corrections
- **Markout is not PnL.** Redefined markout as a hypothetical gross signed price return from the post-fill entry to a fixed horizon, excluding costs and any modelled exit. Removed all statements equating it to realized PnL.
- **Observation unit specified.** Stated that an observation is a position-increasing taker decision `(wallet, coin, bar, direction)`, that same-bar opening fills are aggregated, that maker/wash/closing fills are unscored, and that multi-bar position building yields multiple entries. Every result is now labelled by weighting.
- **Forward-decile horizon and type corrected.** The prior "+4.5 bp gross at 8 h" was the 4-hour, neutralized, wallet-day-weighted, rolling-decile figure (+4.4 bp). The 8-hour value is +11.4 bp. Both now reported at their horizons and labelled neutralized, not gross.
- **Rolling decile and fixed 121 cohort separated.** The forward-decile result is attributed only to the dynamic monthly ranking. The fixed 121-cohort was tested independently (validation, neutralized 8 h, wallet-day-weighted: +10.4 bp, n = 93) rather than inheriting the rolling estimate.
- **Validation status.** March–June relabelled as historical / exploratory out-of-sample; stated that it informed later specifications and that forward data is required for confirmation.
- **Cohort threshold explained.** Stated that the ≥2-month threshold (121 wallets) was chosen for breadth/power and that only the ≥3-month subset (28) cleared the chance benchmark; removed any implication that all 121 are established repeat performers.
- **Term-structure significance.** Added day-block confidence intervals; noted that most coin-level structure is within noise and the HYPE hump does not exclude zero.

## Claims softened or clarified
- "wallet direction adds nothing" → "did not improve performance in this specification"
- "the entire edge is the fade" → "no statistically resolved incremental return over the benchmark"
- "the state fully explains the edge" → "observable market-state variables explained most of the estimated advantage"
- "generic reversal" → "consistent with a short-horizon reversal pattern"
- "live underpowered positive" → "a smaller incremental effect remains possible given the interval and resolvable-effect size"
- Removed narrative-diary phrasing and conclusion-bearing section/figure titles.

## Figures removed (from main report; moved to appendix or dropped)
- Overlaid trade-size density → replaced by a per-coin quantile table (appendix).
- Regime composition, hold-time histogram, monthly volume → appendix.
- Violin distributions → replaced by a dispersion quantile table (appendix).
- Anonymous top-20 wallet index bars and Sharpe-vs-N scatter → replaced by a short in-sample reference table (appendix).
- Cohort selection funnel, drift-flip bar, recurrence-vs-luck bar → folded into text/appendix.
- Audit and bug tables → condensed to one appendix table plus a methodology-controls paragraph.

## Figures redesigned (main report, figs_v2/)
- **f1** Term structure with day-block 95% CIs; neutral title; estimator in caption.
- **f2** Raw vs neutralized, pooled.
- **f3** Static ranking: training-vs-validation decile plot and scatter; labelled as static analysis.
- **f4** One-month-ahead rank persistence by horizon (interval plot).
- **f5** Gross, net and benchmark-adjusted returns (forest; estimator/weighting/cost/period/CI in caption).
- **f6** Returns under wallet-direction and fade rules (A/B/C/D forest).
- **f7** Residual after conditioning on market state (interval plot with resolvable-effect annotation, replacing the shaded-MDE chart).
- **f8** Market conditions at recurring-wallet entries (five separate panels with own axes, replacing the shared-axis bar chart).
- **f9** Per-wallet contrarian entry share (ECDF, replacing the overlaid histogram).

## Style
- Descriptive figure titles; interpretation only in body text. Neutral colours, consistent fonts, no all-caps annotations, no conclusions in titles. Each empirical result stated once in the narrative. Bold restricted to headings and a small number of key estimates.
