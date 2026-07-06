# Change log — report v3

## Reframing
- Restructured into Part I (aggregate Hyperliquid taker markouts) and Part II (search for informed wallets). Part I is now a complete standalone markout analysis that answers the baseline assignment before any wallet ranking; Part II retains the v2 wallet experiment, shortened.
- Opening states two linked questions and clarifies the metric is a post-fill decision markout, not realized PnL and not a full execution-quality markout.

## New Part I content (descriptive; no new selectors or strategy searches)
- Data/markout methodology section with observation-unit and adjusted-measure definitions.
- Core markout summary table: mean, 95% day-block CI, median, hit rate, standard deviation, N by coin and horizon.
- Event-study figure: signed price response −8h to +24h around entries, per coin, day-block CI (new compute, `pi_compute.py`).
- Coin×horizon markout heatmap with CI-excludes-zero marks.
- Long-versus-short term structure (small multiples).
- Subsequent 8h markout conditional on the signed pre-entry move (new compute), establishing the reversal pattern at the aggregate level before the wallet cohort.
- Markout by entry notional (equal- vs notional-weighted).
- Monthly coin×month 8h markout heatmap.
- Distribution interval plot and quantile tables (replacing violins); markout by volatility quintile and time of day (appendix).
- Explicit execution-analysis limitation listing the fill-to-mid / spread / impact / adverse-selection figures that require BBO data and are not produced here.

## Part II (retained, condensed)
- Cross-wallet heterogeneity, static vs rolling persistence, recurring-wallet characterization, benchmark/copyability/forward test — all carried over from v2 with unchanged estimates.
- Dynamic monthly top-decile and fixed 121-cohort kept explicitly separate; the fixed-cohort validation figure (+10.4 bp/8h) is the independently computed one.

## Figures
- Main body: event study, coin×horizon heatmap, long/short, conditional-on-move, notional buckets, monthly heatmap, static persistence, rolling persistence, behavioral conditions.
- Moved to appendix: term-structure line plot, raw-vs-neutralized, distribution/volatility/time-of-day, contrarian-share ECDF, A/B/C/D, residual, wallet table, funnel/hold-time/regime.

## Unchanged
- No wallet selectors optimized; no strategy definitions changed; Part II headline estimates identical to v2. New numbers documented in the number-to-source map.
