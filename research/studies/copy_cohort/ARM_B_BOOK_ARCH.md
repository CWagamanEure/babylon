# Arm B actual-book follow-up — frozen architecture (2026-07-13)

## 1. Question and status

Arm B selects the top 100 eligible wallets each month using the formation-only, EB-shrunk,
coin-week-demeaned realized-PnL-bps score in `selectors.py`. Its existing reported result is a
**wallet-equal 4h markout** of +24.54 bp, CI [1.87, 36.60], not a realized-PnL-at-own-exit return.
The architecture audit found that the old forward population excluded episodes by their eventual
`is_liquidation_close` outcome, which is unavailable at entry. The old result is therefore a lead,
not a valid causal baseline, until remeasured here without that filter.

The audit also found that Arm B's implemented formation SQL omitted its registered F0 filters
(`NOT entry_after_close`, `entry_lag_s <= 90`). The primary cohort here is **Arm B v2**, which applies
the registered F0 rules and starts a new config epoch. The legacy as-implemented cohort is a labeled
reproduction sensitivity only. This entire study is explicitly post-hoc and cannot retroactively
become a pre-registered confirmation.

## 2. Frozen operating point

- **Folds:** 202602–202606 with the original formation cutoffs. Eligibility is v2-causal: Arm A/F7
  may exclude a liquidation-ending formation episode only when its `close_ts < cutoff`; an episode
  that liquidates after the cutoff cannot alter the cutoff pool.
- **Cohort:** top K=100 by corrected Arm B v2 score, reselected formation-only at each monthly cutoff.
  Its formation episodes apply F0. F4 duration is measured as-of cutoff:
  `min(close_ts, cutoff) - open_ts`, so a future close cannot alter eligibility. A no-F0 sensitivity
  on the corrected causal pool is descriptive only; it is not an exact legacy reproduction.
- **Attempted followed entries:** forward opening-taker episodes opened in the test month; require
  `NOT opener_flagged`, `NOT entry_after_close`, `entry_lag_s <= 90`, and positive initial notional.
  **Do not filter entry on `raw_markout_4h`, `is_liquidation_close`, `close_ts`, realized PnL, or any
  other eventual outcome.** Liquidation-ending episodes are an ex-post diagnostic only. A missing 4h
  endpoint is outcome censoring, not a trade that was never attempted: report attempted/evaluable
  counts, clips, turnover, and exposure separately for real and random paths. Return inference is
  complete-case and explicitly conditional on endpoint observability; diagnose differential coverage.
- **Entry/exit:** follower entry is the existing post-fill `entry_bar_ts` price anchor; exit is the
  4h markout endpoint. P&L is recognized at `entry_bar_ts + 4h`, not at entry.
- **Return:** raw direction-signed 4h markout. Coin-week demeaning is a diagnostic only; a real
  long/short book earns raw dollars.
- **Costs:** 2.6 bp round trip (1.3 bp per taker side), charged on every followed clip. This matches
  the Arm C book and deliberately treats the exit as taker.
- **Sizing history:** per `(wallet, coin)`, history membership uses only entry-time-known fields:
  `crossed_open`, `NOT opener_flagged`, `NOT entry_after_close`, `entry_lag_s <= 90`, positive
  `initial_notional_usd`, and `history.entry_bar_ts < current.entry_bar_ts`. It must not require
  `close_ts`, `is_liquidation_close`, realized PnL, any markout, or eventual finalization. The clip
  is the percentile of prior initial notionals; same-timestamp entries cannot size one another.
- **Primary size:** q50. **Secondary sensitivity:** q75. The q50/q75 family is carried from the
  already-built Arm C book; q50 is primary here to avoid selecting the more favorable percentile.
- **Cold start:** an entry with no prior same-coin episode is un-sizeable and excluded; counts and
  notional are reported. A default-clip design is deferred because choosing its value here would
  add another operating-point search.
- **Portfolio:** additive, unlevered position sleeves. Report total gross/net dollars, turnover
  (`sum clip`), dollar-weighted gross/net bp, daily P&L Sharpe (PnL assigned at exit), maximum dollar
  drawdown, median clip, win rate, peak concurrent gross exposure, and return on peak gross capital.
  This is a signal book, not a claim that unlimited concurrent capital was available.
- **Calendar/accounting:** use one fixed UTC calendar for every real/random book, covering all test
  entry days and the final 4h exits; include zero-P&L days; Sharpe uses sample SD (`ddof=1`) and
  `sqrt(365)`. The curve is explicitly **closed-trade cumulative P&L**, not intrahorizon MTM. Aggregate
  simultaneous exits before cumulation and prepend equity zero before closed-trade drawdown.

## 3. Counterfactual and dependence

Construct B>=500 **longitudinal trajectory permutations** from the same eligible pools, increasing B
mechanically if the frozen ESS diagnostic fails. The real
cohort's distinct wallets define binary five-fold membership trajectories (for example `11111` or
`01010`). A state assigns every whole trajectory slot to one distinct candidate wallet that is
eligible in every active fold. The observed real book is the identity state.

Sample states with a symmetric constrained-swap Markov chain: choose a trajectory slot and a wallet
uniformly; replace with an unassigned wallet or swap with its assigned slot; accept only if both
trajectory eligibility constraints hold and every fold remains formation-feature balanced. Balance
is identity-blind and frozen as total-variation distance <= 0.05 for **each** marginal axis
(activity quintile, notional quintile, majority coin, long-share half) versus the real fold. Because
the proposal is symmetric and acceptance is a pure feasibility indicator, the stationary law is
uniform over the connected feasible assignment set; the identity mapping is one feasible state, not
a privileged cost minimum.

Copying the complete trajectory multiset exactly preserves K per fold, the full tenure/run-length
histogram, distinct-wallet count, and every pairwise fold-overlap—not merely adjacent retention.
Use four independently seeded chains, first warm each for >=100,000 proposals to construct dispersed
feasible starts, then use >=50,000 burn-in proposals per chain and thin by >=1,000 proposals. Report
start distance from identity and between starts, acceptance, unique-state fraction, real-wallet
overlap, per-axis balance, between-chain metric means, autocorrelation-based ESS for the return and
tail-indicator series, and dispersed-start construction.
Random wallets are assigned without forward outcomes and use the identical causal sizing/cost rule.
These ordinary MCMC draws do not provide the finite-sample calibration of independent randomizations;
therefore all empirical ranks are **descriptive regardless of diagnostics**, never called p-values.
If acceptance <1%, unique-state fraction <0.9, return ESS <400, chains disagree materially, or any
balance constraint fails, do not interpret even the random band. Also report deployed turnover,
attempted/evaluable coverage, and peak exposure for real and random books.

Primary empirical rank diagnostic:

1. `rank_return = (1 + # random dollar-weighted net bp >= cohort dollar-weighted net bp) / (B + 1)`.

Total net-dollar and Sharpe ranks use the same construction but are descriptive because capital
scale and sparse-return clocks are not the primary edge estimand. Report random medians/p90s and
per-fold real-vs-random direction. The random distribution, not its mean, is the benchmark.

For the cohort's absolute dollar-weighted net-bp estimate, freeze the ratio influence score
`psi_i = clip_i * (net_bp_i - mu) / sum(clip)` and compute the sandwich variance as wallet + exit-week
− wallet×exit-week, with CR1 corrections per component, t critical value at
`min(G_wallet,G_week)-1`, and the existing conservative floor if the combination is non-positive.
Tiny invariants: uniform +5bp shift, global clip rescaling, all-row duplication, and equality to the
unweighted mean when clips are equal.

The **load-bearing enrichment** is real q50 dollar-weighted net bp minus the retention-matched random
counterfactual. Report the point difference versus the random median, the descriptive random band
`[real - q97.5(random), real - q2.5(random)]`, one-sided empirical rank, and the empirical additive
80%-power MDE `q95(random) - q20(random)` (normal MDE is diagnostic only).
Run a +5bp injection through the complete matched comparison and print whether it is detectable.
The absolute CI cannot by itself earn a selector-scoped positive or negative.

Report one aggregate per distinct wallet and per exit-week. Wallet signs are a breadth diagnostic,
not an independent-binomial p-value under shared week shocks; formal breadth enrichment uses the
same retention-matched random paths.

## 4. Verdict discipline and multiplicity

- This follow-up has two sizing looks (q50 primary, q75 secondary). Only q50 dollar-weighted net-bp
  enrichment is the within-study primary operating point. q75, net$, and Sharpe are descriptive and
  cannot upgrade the verdict alone.
- Arm B was selected after a repo-wide search and the q family was motivated by Arm C on these same
  months. Thus the within-study empirical rank is exploratory/descriptive; only genuinely new data can
establish/confirm the effect.
- A positive point estimate with p>0.05 is **underpowered/suggestive**, not null. A method-scoped
  negative requires point estimate + CI, MDE <= 5 bp, cross-unit combination, and a construction
  check showing the matched random band was built at the book level with identical sizing.
- A live positive still faces the full over-carry check: matched-placebo p, concentration by top
  wallet/top trade, leave-one-wallet-out and leave-one-week-out stability, fold breadth, and the
  post-hoc label.
- Before the final interpretation, separate agents must run both the steelman-the-positive and
  prosecute-the-positive passes. Findings are then recorded in `FINDINGS.md` before moving to the
  alt-maker-consensus book.

## 5. Artifacts and order

- Code: `research/studies/copy_cohort/arm_b_book.py`
- Report: `data/derived/copy_cohort/arm_b_book_report.json`
- Equity: `data/derived/copy_cohort/arm_b_book_equity.json`
- Audit: `audit/copy_cohort_arm_b_book/`

Order: architecture audit -> build -> static code audit -> run -> steelman + prosecute -> ledger.
