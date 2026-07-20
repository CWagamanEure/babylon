# FILTERED TRADER QUALITY — architecture and forward-test contract

**Status:** DESIGN ONLY, 2026-07-18; revised after independent statistics, leakage, and correctness audits.
No outcome has been computed under this design. The historical 202511–202606 folds are burned and may be
used only for implementation checks and candidate ranking; a performance claim requires a prospectively
sealed forward preregistration (§3.1).

## 1. Question and decision

Can a causal filter of each wallet's daily, cross-sectionally normalized majors PnL select a rolling
top-30 cohort whose **future copyable majors book** is better than the existing majors-native top-30
selector?

The load-bearing comparison is not whether the filtered score predicts the wallet's own next PnL in
sample. It is the paired forward-book delta:

`KF-REL top-30 @ 8h net bp − capped-PnL t-stat top-30 @ 8h net bp`.

The care-about improvement is **+5 net bp per accepted entry**. The test must also report the filtered
book's absolute net result. This is a selector test; sizing remains equal-dollar and consensus remains a
separate entry gate.

## 2. What the score is—and is not

The score estimates a slowly changing **relative trader-quality state**: how persistently unusual a
wallet's capacity-normalized daily realized PnL is versus the contemporaneously active majors population.
It is not a per-trade edge estimate, a causal skill decomposition, or a license to size in proportion to
the wallet's actual notional.

High scores can still encode beta, coin mix, turnover, risk, or a favorable regime. The design therefore
requires validation on future 8h copy markouts and future capped PnL, plus risk/style diagnostics. Only the
copyable book can promote the selector.

## 3. Data and temporal boundary

- Lane: `research/studies/copy_cohort/` only. Nothing under `src/babylon/` imports this study.
- Formation PnL: authoritative majors fills for `BTC, ETH, SOL, HYPE`; use the existing
  `wallet_coin_day` projection only after manifest/schema provenance checks.
- Copy entries: flat taker opens with `start_position = 0`, notional at least $250.
- At monthly test fold `T`, formation is the three complete calendar months before `T`; evaluation is
  month `T`. No statistic, cross-sectional distribution, filter parameter, eligibility flag, or rank may
  read month `T`.
- Daily scores inside a formation window are retrospective **cutoff-specific formation statistics**. They
  become usable only at that monthly cutoff; they are not represented as live `d+1` scores because the
  cutoff-frozen eligible pool uses later formation-window activity.
- Money/size aggregation remains exact DECIMAL. Conversion to float is allowed only after the wallet-day
  capacity-normalized PnL has been formed.

The monthly cadence is retained for the primary experiment so the selector is the only changed component.
A daily-refresh roster is a separately versioned future arm, not an implicit variant.

### 3.1 Forward-epoch seal

The implementation stage must create `FILTERED_TRADER_QUALITY_PREREG.md` **before the first eligible
forward fill**. It must freeze the exact UTC start, the minimum-six/maximum-twelve-month endpoint rule,
the entry cutoff, code/config hash, calibration interval and artifact hash, roster/output schemas, RNG
seeds, and an outcome embargo. The start is the first full UTC month after code, calibration, and tests are
sealed; it cannot be chosen retroactively. Roster generation may run during the embargo, but evaluation
outcomes and performance reports must not be generated until the registered read date.

At a read date, all entries must have matured through `entry_ts + 8h` plus the ASOF staleness tolerance.
The entry cutoff—not report execution time—defines inclusion. The final eight-hour band is either fully
mature before reading or prospectively excluded from both arms; it is never dropped opportunistically as
"unpriceable."

## 4. Daily observation

For wallet `i`, UTC day `d`, across majors only:

```text
net_pnl_i,d = sum(closed_pnl) - sum(fee) - sum(coalesce(builder_fee, 0))
notional_i,d = sum(abs(size) * price)
x_i,d = net_pnl_i,d * min(1, 100000 / notional_i,d)
```

This is **$100k daily-notional normalization**, matching the economic intent of the existing selector. It
is not a literal `clip(PnL, ±$100k)`. Days with zero notional are absent, not zero-return observations.
The legacy baseline, which excludes separate `builder_fee`, is reproduced as a parity diagnostic; the fair
head-to-head baseline uses the total-fee definition above.

At cutoff `C_T`, form the eligible pool using only the three-month formation window:

- at least 15 majors-active days;
- positive finite within-wallet standard deviation of `x`;
- at least one majors-active day in the final 30 calendar days;
- deterministic wallet-address tie break.

For each formation day, rank that day's `x_i,d` **ascending** among active wallets in the cutoff-frozen
eligible pool (rank 1 = lowest PnL; the largest `z` is best).
Inactive wallets receive no observation. Require at least 200 active eligible wallets on a day; otherwise
the day is logged and skipped for every arm. Convert the average-rank percentile to a bounded normal score:

```text
u_i,d = (average_rank_i,d - 0.5) / N_d
z_i,d = inverse_normal_cdf(u_i,d)
```

This rank-normal transform is primary because it is invariant to the fat-tailed dollar scale and cannot be
dominated by one whale. Median/MAD z-score is reported as a construction diagnostic only; it is not an
additional selectable arm.

## 5. Filter: KF-REL

The primary filter is a scalar calendar-time state model per wallet:

```text
theta_i,d = phi^gap * theta_i,prev + eta_i,d
z_i,d     = theta_i,d + epsilon_i,d
```

`theta` is latent relative quality. Gaps are calendar days. Missing wallet-days trigger prediction/decay
only—never a zero-PnL update or forward fill.

### 5.1 Primary reliability model

Version 1 is deliberately homoskedastic. Raw fill count is not an independence count, and a daily rank of
aggregate PnL is not a sample mean whose error variance is known to scale as `1/n_positions`. The primary
filter therefore does **not** mechanically trust high-turnover wallets more.

For diagnostics, build `n_eff_i,d` from causally reconstructed non-overlapping position episodes closed that
day, collapsing fill splits and overlapping same-wallet/same-coin exposure. Report filter innovations and
future outcomes by `n_eff` bin. A heteroskedastic observation model is a future config epoch only if a
formation-only calibration shows a stable, monotone residual-variance relationship; it is not an outcome-
selected variant of this test.

### 5.2 Exact daily AR(1) parameterization

Because the rank-normal observations have approximately unit cross-sectional variance, parameterize the
stationary model by persistence `phi` and latent signal fraction `lambda`:

```text
Var(theta) = lambda
R = Var(epsilon) = 1 - lambda
Q = daily innovation variance = lambda * (1 - phi^2)
P0 = lambda, theta0 = 0
```

For a `g`-calendar-day observation gap, prediction is exactly:

```text
theta_pred = phi^g * theta_prev
P_pred = phi^(2g) * P_prev + Q * sum(phi^(2k), k=0..g-1)
```

Use the closed-form geometric sum and its `phi → 1` limit. Gaps count UTC date boundaries. Tests must cover
`g = 1`, `g = 2`, and a long gap.

### 5.3 Calibration, state history, and fallback

Fit `(phi, lambda)` by the exact Gaussian innovations likelihood pooled across wallets. The implementation
preregistration freezes the calibration dates, eligible-panel construction, numerical grid, objective,
and lexicographic tie break before fitting. Required bounds are `0 ≤ phi ≤ 0.995` and
`0.01 ≤ lambda ≤ 0.99`; wallet-specific parameters are forbidden.

For the clean forward epoch, fit once on the exact pre-epoch calibration interval and freeze the pair for
the entire epoch. At every monthly cutoff, rebuild each candidate's state from the stationary prior using
only that cutoff's three complete formation months; posterior state is **not** carried from older months.
This keeps the filter's information window identical to `TSTAT30`. Burned historical construction folds may
fit inside their formation windows, but their outputs are candidate-ranking only.

If the likelihood has no finite admissible solution or fewer than 1,000 usable wallet-days, `KF-REL`
deterministically falls back to the registered `EMA30` score for that entire frozen epoch. It does not use a
partly specified alternative Kalman fit, and the fallback is logged before outcomes are generated.

At cutoff, rank eligible wallets by posterior mean `theta_hat_i,C-1`, descending, wallet ascending. Select
exactly 30. Posterior variance is reported but is not a second ranking knob; shrinkage already enters through
the filter update.

## 6. Frozen comparators

Comparators 1–3 use the identical eligible pool, total-fee daily `x`, monthly cutoff, top-30 size, book,
costs, and evaluation code. Comparators 4–5 exist specifically to reconcile legacy semantics.

1. **Primary control — `TSTAT30`:** `mean(x) / (sd(x)/sqrt(n_active_days))`; this is the fair filtered-vs-
   unfiltered comparison in the current majors-native selector family, not literal roster parity.
2. **Benchmark — `EMA30`:** calendar-time EMA of daily rank-normal `z`, with half-life fixed at 21 calendar
   days and missing-day decay. This tests whether Kalman complexity adds value beyond ordinary smoothing.
3. **Noise benchmark — `LASTZ30`:** latest available daily `z`, subject to the same 30-day recency gate.
4. **Legacy parity — `LEGACY_TSTAT30`:** existing `pnl-fee` formula and implementation semantics; diagnostic
   only, to reconcile membership and the prior +29bp research estimate.
5. **Published-strategy parity — `PUBLISHED_MAJORS30`:** call the literal current `majors_native.py`
   selection, including its frozen-133 exclusion and without importing the new recency/day-rank guards.
   This is an economic reconciliation comparator, not the same-input causal control.

Only `KF-REL − TSTAT30` is primary. `KF-REL − EMA30` and `KF-REL − LASTZ30` are secondary and adjusted
together with Holm's method. No half-life grid, filter family sweep, top-K sweep, or horizon sweep is
allowed in the confirmatory epoch.

## 7. Copy-book evaluation

For each frozen monthly top-30 roster:

- copy forward-month majors flat taker opens of at least $250;
- direction mirrors the source wallet;
- fixed $2,500 per accepted entry;
- at most one concurrent position per `(wallet, coin)`;
- $50,000 per-coin gross cap;
- fixed 8h exit on backward-ASOF majors mid prices;
- charge 5.5bp round-trip in the primary net line and separately report all-in paper fills;
- preserve the exact acceptance order across arms and log candidates, concurrency skips, cap skips, and
  unpriceable entries.

Before applying the $250 threshold, block-collapse flat-open source rows by
`(wallet, coin, ts, direction)`, summing notional; if the same `(wallet, coin, ts)` contains conflicting
directions, drop and log that whole ambiguous key. The collapsed tuple is the unique candidate key.
Priceability is checked **before** the acceptance state machine, matching the current book, so an unpriceable
row does not occupy a concurrency slot or coin-cap seat. The total acceptance order is
`(ts ASC, wallet ASC, coin ASC, direction ASC)`.

The **ungated** book is primary because it isolates selector quality. Apply the already frozen 6h
smart-consensus gate as an equal-standing secondary to both `KF-REL` and `TSTAT30`: after constructing each
ungated accepted stream, retain an entry only when at least one **distinct other** top-half-ranked cohort
wallet opened the same coin/direction in `[t-6h,t)`. Reuse `count_consensus` semantics: the confirmation
pool is all of that arm's raw cohort flat opens, with no $250 filter, strictly before the candidate; distinct
wallets are counted and self-repeats never confirm. The gate must be a pure subset after concurrency/cap
acceptance; it may not free capacity and admit replacement entries. No consensus threshold/window tuning is
permitted.

## 8. Outcomes and estimators

### Primary

The load-bearing unit is accepted-entry, capital-weighted net bp—the same unit as the +5bp care threshold.
For arm `a`, with fixed clip `c = $2,500` and accepted-entry net markout `r_j` in bp:

```text
R_a = sum_j(c * r_j) / sum_j(c)
Delta = R_KF-REL - R_TSTAT30
```

Because clips are fixed, `R_a` is the event-weighted mean net bp. Days with no trades contribute no numerator
or denominator; no `0/0` bp is invented. Separately report daily dollar PnL on a common fixed capital
allocation, where inactivity is correctly a zero-dollar return, plus return on average and peak deployed
gross. Wallet-day-equal bp is a robustness estimand, not the verdict quantity.

Inference must preserve both dependence axes:

1. **Wallet-cluster bootstrap:** resample whole wallet identities with multiplicity-preserving pseudo-tags;
   retain all of each draw's entries, months, and arm memberships.
2. **Calendar moving-block bootstrap:** resample paired calendar blocks (minimum 7 days; exact length frozen
   from pre-epoch autocorrelation), retaining every arm entry inside each sampled block.

Each produces a deterministic 10,000-draw percentile 95% CI for `Delta`; the binding interval is the
envelope `[min(lower_wallet, lower_time), max(upper_wallet, upper_time)]`. The design does not treat this
envelope as magically exact two-way theory—it is the conservative adjudication rule. A synthetic persistent-
wallet random-effect coverage test and duplicate-cluster multiplicity test must pass before use. Report
`Delta`, both component CIs, the binding CI, and the descriptive monthly direction count.

### Required secondaries

- Absolute `KF-REL` net book result with the same CI/MDE.
- Filtered-score deciles versus next-month own capped PnL/day and next-month 8h copy markout; report all
  deciles, not only top-vs-bottom.
- Cross-unit combination: monthly paired deltas and BTC/ETH/SOL/HYPE deltas. Adjacent months share rolling
  formation windows and all coins share wallets/regimes, so raw sign counts are descriptive—not exact
  independent-binomial p-values. The wallet and calendar-block CIs above are the calibrated combination;
  individual month/coin cells never adjudicate the strategy alone.
- Turnover, roster overlap, rank correlation, score staleness, posterior uncertainty, and selection churn.
- Concentration: drop-best wallet/month, top-5 wallet PnL share, hit rate, median, p90/p99, max drawdown,
  average/peak gross, and return on peak gross.
- Style/risk diagnostics measured formation-only: notional, active days, independent episodes, coin mix,
  taker share, direction share, and liquidation incidence by score decile.

## 9. Nulls, multiplicity, and positive controls

The persistent-random-score null assigns each eligible wallet one random score for the whole evaluation
arc, preserving wallet activity, entries, costs, and book mechanics. It is rerun through selection and the
book; row-wise shuffles are forbidden. The primary paired comparison is singular; Holm adjustment covers
the two filter benchmarks. All other slices are descriptive unless separately registered.

Before any negative verdict, print the always-pending quartet:

1. primary point estimate and 95% CI;
2. empirical 80%-power MDE, required to be at most the +5bp care-about;
3. monthly and coin direction tables plus the calibrated wallet/time aggregate CIs;
4. construction-conservatism reconciliation showing identical costs, pricing, acceptance semantics, and
   no gate-before-capacity artifact.

### 9.1 MDE and positive controls

Use the same two-sided 95% binding-CI rejection rule (`CI_low > 0`) everywhere; do not mix it with a
one-sided 5% threshold. For empirical power, null-center the observed construction as
`r_KF^0 = r_KF - observed_Delta`, `r_TSTAT^0 = r_TSTAT`, preserve the wallet and calendar dependence, then
add `delta` bp to every `KF-REL` accepted-entry outcome. On the fixed
grid `delta = 0, 0.25, ..., 20bp`, run **two** families of 2,000 deterministic outer pseudo-epochs:

- outer-W resamples whole wallets with multiplicity-preserving tags;
- outer-T resamples synchronized moving calendar blocks with both arms retained.

Each outer sample is analyzed with the registered inner component bootstraps and binding CI; merely changing
inner-bootstrap seeds on one fixed dataset is not a pseudo-epoch. MDE80 is the smallest delta whose Wilson-
lower 95% bound on rejection probability is at least 0.80 in **both** outer families. Seeds, inner/outer
Monte Carlo counts, and block length are frozen in the forward preregistration.

Two controls are separate:

1. **Inference control:** the shift experiment above on the actual accepted streams. At +5bp, its empirical
   rejection rate must have Wilson lower bound at least 0.80 before a no-lift verdict can be earned.
2. **Selector control:** a small synthetic panel with planted persistent wallet states, irregular missingness,
   and corresponding +5bp future outcomes is passed through unchanged `KF-REL`, `TSTAT30`, selection, book,
   and inference code. It must recover the planted ranking direction and positive book delta. This is a code
   correctness control, not evidence about real wallets.

If either fails, the instrument is blind or broken at the effect of interest and the verdict is
**inconclusive**, not no improvement.

## 10. Forward verdicts

Do not read performance before six complete forward months. Continue without interim strategy changes
until both at least six months and at least 60 active arm-days exist; cap the frozen epoch at 12 months.

- **Filtered selector established superior:** paired delta CI-low > 0, absolute `KF-REL` net CI-low > 0,
  ex-HYPE point > 0, and no single month supplies more than 50% of net profit.
- **Method-scoped no material lift:** paired delta CI-high < +5bp **and** MDE ≤ 5bp **and** the +5bp positive
  controls pass, with cross-unit and construction checks printed. This says only that this filtered score
  does not improve this top-30/8h construction materially; it is not "trader quality does not persist."
- **Unresolved, direction stated:** every other non-superior/non-no-lift state, whether the point is positive,
  flat, or negative. If the CI admits +5bp, MDE is too large, or a control/construction check fails, surface
  the point and CI and label the direction without converting it to a null.
- **Available data cannot resolve:** at the 12-month cap, any still-unresolved state receives this final
  label and the experiment stops; it is not restricted to MDE failure.

Any new filter, parameter update, daily roster cadence, alternative K/horizon, or score neutralization
starts a new config epoch.

## 11. Build and verification plan

Proposed research-only files:

```text
research/studies/copy_cohort/filtered_quality.py       # daily panel + causal filters + frozen rosters
research/studies/copy_cohort/filtered_quality_book.py  # identical-arm book and paired inference
tests/research/test_filtered_quality.py                 # tiny synthetic construction tests
data/derived/copy_cohort/filtered_quality/              # versioned panels, rosters, reports
```

Required tests include exact fee/cap arithmetic, ascending rank ties, all-equal/MAD-zero days, exact gap
mean/variance propagation, cutoff-level future-data mutation invariance, filter fallback, deterministic
selection, split-order invariance, episode-count invariance to fill splitting, legacy roster reconciliation,
identical-entry book parity,
priceability-before-acceptance, distinct-other-wallet consensus, gate-as-subset ordering, wallet-bootstrap
multiplicity, persistent-wallet coverage, and both +5bp controls.

Artifacts must record schema versions, source manifests, registration timestamp, epoch entry/read cutoffs,
code/config and calibration hashes (including `-dirty`), fitted filter parameters, skipped-day counts,
roster hash, outcome-embargo status, RNG seeds, and all deviations.
