# Top-30 CAP=100k 8h book — audit findings

**Date:** 2026-07-13  
**Target:** `research/studies/copy_cohort/book.py`  
**Headline audited:** q50/q75 +8.7/+23.1 bp and daily Sharpe 1.56/1.96  
**Method:** independent leakage, statistics, correctness/data-contract, steelman, and prosecutor passes;
static trace plus tiny no-data masked-array probes; no Parquet reads.

## Verdict

**The reported Sharpes 1.56/1.96 are invalid. The +8.7/+23.1 bp point estimates are also not causal and
must remain provisional pending a clean rerun. This is not evidence of no edge: the strategy's direction
is unresolved.**

The most immediate Sharpe defect is deterministic and reproduced. One of 217 saved positions has a null
8h markout. DuckDB returns it as a NumPy masked value. Masked reductions omit its P&L, but
`np.bincount(weights=net_usd)` discards the mask and consumes the underlying buffer, which in this path is
the clip notional. The daily series therefore receives a phantom positive P&L. The emitted equity ends in
`null`, while its penultimate value equals reported total net dollars.

Using only the 216 finite saved positions gives these **mechanical diagnostics on the still-leaked sample**:

| construction | q50 Sharpe | q75 Sharpe |
|---|---:|---:|
| active entry days, sqrt(252) | 0.477 | 1.323 |
| full UTC calendar, 8h exit day, sqrt(365), sample SD | 0.372 | 1.072 |

The second row corrects only clock/accounting. It does **not** correct future-liquidation selection,
post-close/stale entries, endpoint coverage, capital, or the null, so 0.372/1.072 are not strategy estimates.

## Confirmed findings

### F1 — Null 8h endpoint fabricates daily P&L through masked-array loss [CRITICAL]

- **Where:** `research/studies/copy_cohort/book.py:71-78,109-145`; endpoint construction at
  `research/data/markout.py:80-99`; `data/derived/copy_cohort/book_equity.json`.
- **Blast radius:** result-fabrication for Sharpe; inconsistent counts, turnover, return denominator,
  equity, and drawdown.
- **Failure path:** the row enters `_build_index` because only clip NaN is tested. Masked `net_usd.sum()`
  ignores it, `clp.sum()` and `n_pos` include it, and `np.bincount` consumes the masked array's hidden
  underlying clip as profit. A tiny synthetic call to `_book` reproduced a near-zero total P&L alongside
  Sharpe 11.22 from one masked endpoint.
- **Evidence in artifact:** 217 counted positions but win rate `107/216`; both equity arrays contain 217
  entries and terminate in `null`; their finite prefix reconciles exactly to +$1,411/+$7,638.
- **Fix:** normalize masked arrays to explicit NaN immediately; separately count attempted, sizeable,
  evaluable, and censored rows; compute every return/P&L/Sharpe array only on explicit evaluable rows.

### F2 — Eventual liquidation outcome selects followed trades [CRITICAL]

- **Where:** `research/studies/copy_cohort/book.py:65-78`; field assignment at
  `research/data/episodes_build.py:307-350`.
- **Blast radius:** result-fabrication/lookahead; changes point estimate, sizes, Sharpe, and null.
- **Failure path:** an entry later liquidated receives `is_liquidation_close=True` only at its future close,
  but `_pull_episodes` deletes it before building the follower ledger. The same global filter changes the
  population of prior same-coin notionals.
- **Fix:** never condition attempted entries or the raw sizing history on eventual close type. Keep
  liquidation as an ex-post diagnostic only.

### F3 — Registered executable-entry guards are omitted [CRITICAL]

- **Where:** `research/studies/copy_cohort/book.py:71-78`; flags created at
  `research/data/markout.py:61-77` and carried by `research/studies/copy_cohort/base.py:48-64`.
- **Blast radius:** result-fabrication; changes point estimate and sizing history.
- **Failure path:** an episode can close before its first post-open oracle tick, yet the book enters at that
  later price. A data gap can likewise create a substantially delayed entry. `book.py` applies neither
  `NOT entry_after_close` nor the frozen `entry_lag_s <= 90` guard.
- **Fix:** apply entry-known F0 consistently to attempted cohort and random entries and sizing histories;
  report guard attrition.

### F4 — Endpoint censoring is not preserved or compared [HIGH]

- **Where:** `research/data/markout.py:61-99`; `research/data/schema.py:61-64`;
  `research/studies/copy_cohort/book.py:71-78`.
- **Blast radius:** point estimate and benchmark construction.
- **Failure path:** the independent context source ends before the fills tape. Entries with no forward entry
  anchor disappear at the ASOF join; entries with a missing 8h endpoint survive as masked rows. The report
  gives no selected-versus-random attempted/evaluable turnover or coverage.
- **Fix:** preserve the causal attempt population, make endpoints nullable, and report matched coverage and
  notional before conditioning return on evaluability.

### F5 — Sharpe/equity use the wrong time and clock [HIGH]

- **Where:** `research/studies/copy_cohort/book.py:124-147`.
- **Blast radius:** Sharpe, equity timing, and drawdown; finite total P&L unchanged.
- **Failure path:** the complete future 8h P&L is credited at entry; zero-P&L calendar days are omitted;
  population SD and sqrt(252) are used for 24/7 crypto; initial equity zero is omitted.
- **Fix:** credit closed-trade P&L at `entry_bar_ts+8h`, use one full UTC calendar with zeros, sample SD and
  sqrt(365), aggregate simultaneous exits, and prepend zero. Build MTM separately if an equity path is claimed.

### F6 — Random-book ranks are not longitudinally exchangeable [HIGH]

- **Where:** `research/studies/copy_cohort/book.py:151-203`.
- **Blast radius:** invalid `p_beat_random_*` interpretation.
- **Failure path:** selected wallets can persist across overlapping formation windows, while every random
  cohort is redrawn independently each month. The paths do not match tenure, serial dependence, formation
  features, turnover, endpoint coverage, or peak exposure. Total-dollar ranks additionally conflate return
  with activity and clip scale.
- **Fix:** use whole-wallet longitudinal paths with formation-known matching and overlap/mixing diagnostics;
  make dollar-weighted net-bp enrichment primary and label MCMC ranks descriptive unless exchangeability is proven.

### F7 — The object is not yet a capital-constrained book [HIGH]

- **Where:** `research/studies/copy_cohort/book.py:118-147,174-176`.
- **Blast radius:** portfolio/accounting interpretation.
- **Failure path:** `deployed_usd = sum(clip)` is gross entry turnover. Overlapping 8h positions are not
  tracked, no capital constraint is imposed, and peak concurrent gross/equity return is absent. “Unlevered”
  and return-on-capital interpretations are therefore unsupported.
- **Fix:** build entry-to-exit exposure intervals, report turnover separately from average/peak concurrent
  gross, and either freeze a capital allocation rule or label the output a sized signal ledger.

### F8 — Concentration, multiplicity, and uncertainty block positive inference [HIGH]

- **Where:** `research/studies/copy_cohort/book.py:36-40,179-203`; generated report/equity.
- **Blast radius:** over-carry/reporting.
- **Evidence:** the largest finite winner is 95.1% of q50 total net and 48.1% of q75 total net; q75 was read
  after q50 and a prior cap/weighting arc; net-dollar ranks are 0.398/0.279 and the unadjusted, invalid-null
  q75 Sharpe rank is 0.060. There is no valid weighted CI, MDE, fold breadth, wallet/week breadth, or
  leave-one-out analysis.
- **Fix:** freeze one primary q/cost/horizon in a new epoch; report concentration, weighted wallet+week CI,
  empirical MDE, fold and cross-unit breadth, and repo-arc multiplicity.

### F9 — Formation fee/tie details can alter membership [MED]

- **Where:** `research/studies/copy_cohort/capday_cohort.py:60-76,96-106`;
  `research/studies/copy_cohort/book.py:50-60`.
- **Blast radius:** selection membership/power.
- **Failure path:** the formation metric subtracts raw `fee` but not separate `builder_fee`; top-30 ordering
  has no explicit wallet-ID tiebreak.
- **Fix:** use total fees, count cast failures, and sort deterministically by `(metric DESC, wallet ASC)`.

## Checks that held

- CAP is exactly $100,000, K is 30, and eligibility is at least 15 active days.
- Formation uses the prior three complete calendar months and stops strictly before the test month.
- The capped-PnL-per-active-day formula is implemented as documented apart from builder fees.
- Within the already-filtered row population, q50/q75 sizing uses strictly earlier same-wallet/same-coin
  timestamps; same-timestamp entries cannot size one another.
- Direction-signed 8h markout and finite-row P&L algebra are correct; 2.6 bp is subtracted once.
- Cohort and random paths call the same sizing/P&L functions; RNG is fixed and empirical ranks use the
  `+1/(B+1)` correction. Those facts do not repair the null mismatch.

## Mandatory dual framing

- **Steelman:** the 216 finite conditional trades genuinely reconcile to positive +$1,411/+$7,638 and
  +8.69/+23.07 bp; both q choices point positive; after clock-only repair q75 remains about 1.07; formation
  cutoff and strict-prior quantile logic otherwise hold. This is a real positive lead worth rerunning.
- **Prosecutor:** the headline Sharpe is mechanically fabricated by null-mask loss, the traded population
  uses future liquidation outcomes and non-executable entries, the null is mismatched, and q50 is essentially
  one-trade residual. None of the quoted headline numbers is valid causal evidence.

**Final label: INVALID HISTORICAL ESTIMATE; STRATEGY DIRECTION UNKNOWN.** A causal rebuild is required.

