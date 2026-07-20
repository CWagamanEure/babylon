# Pooled-wallet Efron top-30 backtest notebook specification

## Purpose and governance

Produce a compact, executable EDA notebook for the frozen pooled-wallet `WALLET_E30` majors baseline.
The notebook is descriptive only: the 2025-11 through 2026-06 folds are burned, the registered May
missingness gate fails, and neither positive promotion nor a method-null conclusion is permitted. Consensus
opinion trading and the pre-fit >500-fills/day screen are excluded.

## Bound inputs and reconstruction

- Load `data/derived/copy_cohort/wallet_coin_t30/book_report.json`, `rosters.json`, and the eight promoted
  entry Parquets.
- Fail closed on report governance, roster/code/dependency hashes, every entry data/metadata record, the
  supported ordered and multiset hashes, capacity funnels, supported count, missing count, mean, median,
  and total PnL.
- Use the audited `wallet_coin_t30.capacity_book` implementation with the saved `WALLET_E30` rosters.
  Do not refit Efron, rescore wallets, or read outcomes into selection/capacity decisions.

## Performance conventions

- One accepted position is fixed at $5,000; the audited engine enforces one concurrent wallet×coin
  position, $50,000 gross per coin, an 8-hour hold, and 5.5bp cost.
- PnL is `net_bp * 5000 / 10000` and is credited to the 8-hour exit UTC day.
- The daily frame is the complete inclusive 2025-11-01 through 2026-06-30 calendar (242 days); zero-PnL
  days remain in the sample.
- Annualized Sharpe is `mean(daily PnL) / sample_sd(daily PnL) * sqrt(365)`.
- Annualized Sortino is `mean(daily PnL) / sqrt(mean(min(daily PnL, 0)^2)) * sqrt(365)`.
- Drawdown begins from zero equity. Drawdown percent uses maximum realized gross exposure as denominator.
  Exposure includes capacity-accepted entries with missing outcomes because they still reserve capital.
- Headline PnL omits unavailable outcomes. Also report the registered ±2,000 net-bp missing-outcome stress
  over all accepted entries because it can reverse the absolute sign.

## Required EDA

Show the equity and drawdown curves, daily PnL and rolling Sharpe, exit-calendar positive months, entry-fold
and coin breadth, trade-return tails, wallet and direction concentration, consecutive-roster overlap,
exposure, and the capacity funnel. Label entry folds separately from exit-calendar months. Every rendered
interpretation must say **positive descriptive mean, but burned and missingness-unresolved; direction not
established or deployable**.

