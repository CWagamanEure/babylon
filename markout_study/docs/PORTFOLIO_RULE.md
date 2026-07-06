# Portfolio rule behind the wallet-day estimator

The wallet-day and wallet-coin-day "returns" are aggregation rules over per-decision markouts, not the output of a capital-constrained backtest. This document states the exact rule and its limits.

## Aggregation (as implemented, `src/verify_v6.py` `daycells`)

- **Cell.** For the wallet-day estimator a cell is one `(wallet, calendar-day)`; for wallet-coin-day it is `(wallet, coin, day)`.
- **Within a cell.** The cell value is the equal-weighted mean of the 8-hour markouts of that cell's scored entries. Multiple entries in the same coin are averaged; opposite-direction entries are each scored in their own direction and then averaged (they can offset within the cell).
- **Across cells.** Each cell receives equal weight; the estimate is the mean over cells. A wallet contributes as many wallet-day cells as it has active days, so the wallet-day estimator is **activity-weighted across days** but equal within a day. The equal-wallet estimator instead gives each wallet one weight (its own validation mean).
- **Cost.** The cost-adjusted variant subtracts the canonical round-trip schedule (BTC 8 / ETH 8 / SOL 10 / HYPE 14 bp) from each entry before aggregation — one round-trip charge per scored decision.

## What the rule does not enforce

- **No capital constraint.** Overlapping 8-hour positions are each scored independently; capital is effectively reused across simultaneous positions rather than shared. There is no one-unit-per-wallet-day capital cap.
- **No coin-exposure cap** and no netting of offsetting positions beyond the within-cell average.
- **No execution model** (fill price, spread, depth, impact, funding).

## Consequence for interpretation

Because capital is not bounded and overlapping positions are not shared, the absolute figures are an **average cost-adjusted markout statistic per decision**, not a strategy return on deployed capital. The report therefore labels the absolute (A) figures as average markout statistics, reserves "field-relative" (B) and "fade-relative" (C) for the comparative estimands, and does not describe the cohort as a deployable copy-trading strategy. A capital-constrained, execution-aware backtest is the object of the proposed prospective test.
