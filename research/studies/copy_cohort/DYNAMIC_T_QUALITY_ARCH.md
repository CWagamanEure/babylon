# Dynamic t-quality selector — frozen diagnostic architecture

Date frozen: 2026-07-18, after inspection of the failed rank-z/KF result and therefore **post hoc**.
Historical folds 202511–202606 are burned and may diagnose construction only. They cannot create forward
evidence or authorize deployment.

## 1. Question and failure being corrected

Can recency weighting and explicit uncertainty improve the rolling majors-native top-30 selector without
changing the successful estimand?

The failed `KF_REL` experiment changed two things at once: it replaced capacity-normalized daily PnL with a
cross-sectional percentile and replaced the wallet-specific t-stat with a homoskedastic posterior mean. The
new primary changes only time weighting. It preserves PnL magnitude, wallet-specific dispersion, and effective
sample size.

## 2. Formation tape and folds

- Burned evaluation folds: 202511, 202512, 202601, 202602, 202603, 202604, 202605, 202606.
- Formation for fold T: the three complete calendar months strictly before T.
- Source: lake `alt_universe_wallet_coin_day`; majors are BTC, ETH, SOL, HYPE.
- Forward entries: lake `alt_universe_open_entries` in T only.
- Formation and outcome caches fail unless every requested calendar day has exactly one status-`ok` manifest
  and its required WCD/OPE object. They are lineage-bound to each consumed object's ETag, size, and
  last-modified value; the full upstream manifest fields (including schema/code version); exact code/config
  hashes; rosters; context files; and common outcome cutoffs.
- Every fold roster records its exact panel-cache-spec and formation-lineage hashes. The book recomputes the
  current selector spec and refuses a stale roster. Derived objects are re-HEADed after materialization, and
  context files are SHA-256 hashed before and after materialization, so a mid-run mutation fails closed.
- Frozen-133 exclusion is not applied to the fair all-wallet primary. The literal published majors roster is
  retained as a reconciliation diagnostic.

## 3. Daily measurement

For wallet i and active majors day t:

```
net_pnl_it = sum(pnl) - sum(fee) - sum(coalesce(builder_fee, 0))
day_notional_it = sum(notional)
x_it = net_pnl_it * min(1, 100000 / day_notional_it)
```

The $100k operation scales large-turnover days down and never scales small wallets up. It is a turnover-budget
normalization, not a literal PnL clip and not a claim that turnover equals economic exposure. No daily
cross-sectional rank transform is used.

Common primary rankable pool at the cutoff:

- at least 15 finite active majors days;
- positive sample variance of x;
- at least one active majors day in the last 30 calendar days;
- finite positive EW variance and EW `n_eff >= 8` under the frozen weights below;
- at least 30 eligible wallets, otherwise fail the fold.

This intersection changes the unrestricted historical TSTAT universe. Therefore `TSTAT_COMMON30` is the fair
primary control and literal unrestricted `TSTAT30` is retained as a reconciliation arm. No result may attribute
a common-pool change to recency weighting.

## 4. Frozen selectors

The primary selectors use the exact common primary pool; the HAC selectors use their common HAC-valid
intersection. The two COPY selectors use one identical post-shock copyability pool. Shock and literal
diagnostics are labeled as different pools. Every arm uses the deterministic `score desc, wallet asc` tie-break
and must contain exactly 30 unique wallets or the fold fails.

### A. `TSTAT_COMMON30` — load-bearing control

```
score_i = mean(x_i) / (sd(x_i) / sqrt(n_i))
```

This is the equal-calendar-weight, total-fee version of the successful selector.

### B. `EW_T30` — primary corrected selector

Calendar-age weight at the fold cutoff:

```
w_it = 2 ** (-age_days / 21)
n_eff_i = sum(w)^2 / sum(w^2)
mu_w_i = sum(w*x) / sum(w)
var_w_i = sum(w*(x-mu_w)^2) / (sum(w) - sum(w^2)/sum(w))
score_i = mu_w_i / sqrt(var_w_i / n_eff_i)
```

The common pool already requires `n_eff >= 8` and positive finite weighted variance. This is an IID dynamic
t-like ranking heuristic, intentionally matching the successful t-stat's uncertainty convention; it is not a
fat-tail-robust estimator and makes no claim of exact Gaussian sampling theory. All uncertainty on the trading
outcome is cluster/bootstrap based.

### C. `HAC_T30` and `EW_HAC_T30` — serial-dependence secondary

Within the primary pool, form one common HAC-valid intersection where both static and EW Newey-West variances
are finite and positive; require at least 30 wallets and use that exact pool for both HAC arms. Report its size
and overlap with the primary pool so the secondary cannot attribute a pool change to weighting. Re-rank by the
static or EW mean divided by a frozen 7-calendar-day Bartlett/Newey-West standard error. Build a complete
calendar grid; inactive days contribute zero influence, not zero PnL. For
daily influence `a_t = w_t*(x_t-mu)/sum(w)`, use:

```
var_mean = sum(a_t^2) + 2*sum_{h=1..7} (1-h/8)*sum_t(a_t*a_{t-h})
score = mu / sqrt(var_mean)
```

This pair diagnoses whether serially dependent active days, which Kish `n_eff` alone does not correct, change
the recency conclusion.

### D. `EW_T_SHOCK30` — registered blowup-handling secondary

A formation-day shock is either:

- `n_liq > 0`; or
- `x <= -$10,000`, an economically fixed 10% loss on the $100k normalization budget.

For a wallet with a shock, discard reputation before the most recent shock but **retain the shock day** when
computing the EW t-score. If `cutoff_ordinal - shock_ordinal <= 30`, quarantine the wallet and make it
ineligible. For an older shock, recompute all validity rules on the retained shock-day-and-after window:
`n>=8`, `n_eff>=8`, finite positive static and EW variance, and last observation within 30 days. This prevents
a fat-tail-resistant method from dismissing a genuine failure as mere noise. The shock arm is secondary
because it changes more than time weighting.

During the test month, the same shock definition creates a causal online quarantine for shock/copyability
arms. A day-D WCD shock becomes actionable only after UTC day D closes: reject entries on days D+1 through
D+30 inclusive. Earlier same-day entries are never removed with completed-day information.

### E. `EW_T_COPY30` — registered copyability/HFT secondary

Apply the shock rule and require formation-only raw activity:

- majors `sum(n_open_flat) >= 5`;
- `sum(all-coin n_fills) / count(distinct all-coin active day) <= 1,000`;
- `sum(all-coin n_taker) / sum(all-coin n_fills) >= 0.10`.

Missing, zero-denominator, or nonfinite activity inputs are ineligible.

The 1,000-fill and 0.10 taker thresholds pre-exist in `majors_archetype.py`. This is not a claim that every
bot is bad; it is a separate copyability arm. `TSTAT_COPY30`, using the identical gate but static t-score, is
required so copyability is not credited to filtering. Both COPY arms use the identical most-recent-shock
retained observations, 30-day formation quarantine, common post-reset validity pool, formation activity gate,
and test-month online quarantine; only equal versus EW time weights differ.

### F. diagnostics

- `TSTAT30`: literal unrestricted total-fee TSTAT reconciliation arm.
- `PUBLISHED_MAJORS30`: literal pre-existing selector/reconciliation arm.
- The old `KF_REL`, rank-z EMA, and LASTZ arms are not re-searched. Their prior artifact remains the diagnosis.

## 5. Entry book — identical across arms

- Test-month majors flat-position taker opens only.
- Collapse split rows by `(wallet, coin, block timestamp, direction)` before the $250 threshold.
- Drop and count conflicting-direction keys.
- Candidate notional >= $250.
- Aggregate authoritative daily money and block-collapsed notional as DuckDB `DECIMAL(38,12)`. Because DuckDB
  decimal division returns a floating value, form daily x from the exact decimal sums with Python `Decimal`,
  then convert the completed x to float for scoring. Convert block notional to float only after the exact
  $250 comparison.
- Execution entry is the first context midpoint **strictly after** the signal, within 90 seconds. Scheduled
  exit is eight hours after the execution-entry timestamp; execution exit is the first context midpoint at or
  after that scheduled time, within 90 seconds. The signal-time/pre-signal midpoint is never an entry price.
- Require every context file for folds 202511–202605 plus next-month days 1–3. The registered final fold
  202606 requires exactly June 1–29 and no July context. Record major/day endpoint coverage, partial days,
  and gaps; do not impute them. The pre-run checks found isolated 102–128 second holes and one partial
  May-30 context day ending 06:57 UTC. Fail-closing the whole fold would discard later causally executable
  May-31 trades, while right-censoring May at that boundary would change the registered month. Compute one
  common candidate-time outcome-support
  mask: at a collapsed ambiguity-free signal timestamp, all four majors must each have a first strictly
  forward midpoint within 90 seconds and a first exit midpoint at/after that major's execution-entry plus
  eight hours within 90 seconds. A signal is outside support if any major fails. Compute this identically
  across arms, but apply it only after the causal capacity book is frozen: an accepted unsupported trade is
  excluded from outcome estimation and never backfilled. It may not affect roster membership, entry/capacity
  decisions, or consensus. Report context gaps and common-support exclusions. Let
  `ctx_max_coin` be each major's final context timestamp and set the common signal cutoff to
  `min_coin(ctx_max_coin) - 8h - 180s`, covering both maximum entry and exit quote delays. Apply
  `signal_ts <= cutoff` before arm membership and count exclusions.
  The exact cutoff and context hash are frozen in every fold sidecar; 202606 may use its shorter common cutoff.
- A threshold-passing signal without a research-context entry quote within 90 seconds is not called a live
  nonexecution: the source fill proves the venue traded. Reserve its capacity from the earliest possible time
  `signal_ts`, hold it through `signal_ts + 90s + 8h + 90s`, mark its outcome genuinely unpriced, and
  never backfill. These reservations enter the same missingness rate and bounded-return gates. The partial-day
  endpoint exception is exact and singular: 2026-05-30 must have 418 rows per major, begin 00:00 UTC, and end
  06:57 UTC; all other required major/day endpoints remain fail-closed.
- Fixed $2,500 per accepted position signal; never size by source-wallet fill/notional.
- One concurrent position per `(wallet, coin)`.
- Total concurrent source-wallet exposure <= $10,000 across coins.
- Total concurrent coin exposure <= $50,000.
- Hold 8 hours; subtract 5.5bp round-trip cost.

Equal sizing is per collapsed accepted position signal, not raw fill. The wallet cap prevents a high-frequency
source from creating uncontrolled simultaneous concentration; it does not make entry observations independent.

Construction order is frozen:

1. apply common signal cutoff;
2. exact block-collapse, ambiguity drop/log, and exact $250 threshold;
3. find the actual-coin strictly-forward execution entry; if research entry context is absent within 90
   seconds, sort/reserve it at `signal_ts` so no later trade can overtake it, use the conservative expiration
   `signal_ts+90s+8h+90s`, and flag the outcome genuinely unpriced;
4. apply the arm's already-causal online quarantine state;
5. sort executed candidates by `(execution_entry_ts, signal_ts, wallet, coin, direction)`;
6. expire capacity at the precommitted conservative time `execution_entry_ts + 8h + 90s`; outcome
   availability or actual exit timestamp never frees capacity;
7. check/log wallet-coin concurrency, then $10k wallet-gross cap, then $50k coin-gross cap;
8. freeze accepted capacity trades;
9. apply the all-four-major outcome-support mask to accepted trades only, without backfilling; the remaining
   trades form the estimand and must also pass the defensive actual-coin exit-price check.

## 6. Consensus is an overlay, not the selector

The primary selector comparison is ungated.

Registered secondary: keep an already accepted entry only if at least one **distinct other** top-half-ranked
wallet in the same arm emitted the same coin and direction in `[t-6h, t)`. The source wallet cannot confirm
itself. Consensus is computed from pre-acceptance, block-collapsed qualifying signals and applied as a pure
subset after normal book acceptance. The confirmation pool is every ambiguity-free, common-cutoff-passing
block-collapsed signal from a roster wallet, including signals below $250 and without requiring priceability,
outcome support, or acceptance. A confirmer's future eight-hour data availability never changes a target
trade's consensus state.

Only `EW_T30` versus `TSTAT_COMMON30` smart subsets is load-bearing for this overlay. Other smart books are
descriptive.

## 7. Estimands and inference

Primary:

```
mean net bp among frozen accepted-capacity trades passing all-four outcome support (EW_T30)
- mean the same support-conditioned quantity for TSTAT_COMMON30
```

Care-about improvement: +5bp/accepted entry.

Secondaries, Holm-adjusted as one family of four:

1. `EW_HAC_T30 - HAC_T30`;
2. `EW_T_SHOCK30 - EW_T30`;
3. `EW_T_COPY30 - TSTAT_COPY30`;
4. `EW_T30_SMART - TSTAT_COMMON30_SMART`.

Report for every absolute book and comparison:

- point estimate, entries, wallets, dollars, hit rate, median and tails;
- diagnostic multiplicity-preserving wallet-cluster percentile CI;
- diagnostic paired moving 7-calendar-day-block percentile CI; sample the union of calendar blocks once and
  apply the same multiplicities to both arms, zero-filling days without an arm entry;
- load-bearing crossed wallet×time product-weight percentile CI: independently draw global-wallet
  multiplicities and paired 7-day-block multiplicities, weight every row by their product, and recompute both
  ratio means. This pigeonhole-style distribution captures persistent wallet and calendar-shock variation;
- per-fold and per-coin deltas plus direction summaries. These units share wallets, formation windows, and
  market beta, so their signs are descriptive—not an exact independent sign test;
- drop-best-wallet, drop-best-fold, ex-HYPE, top-five-wallet PnL share;
- all construction funnels and common-cutoff coverage.

The wallet and crossed bootstraps sample the union of global wallet identities once per draw and apply
identical multiplicities to both ratio means. Use 10,000 deterministic draws. The crossed distribution is the
sole decision distribution; one-way distributions are construction diagnostics. Center crossed empirical
noise `E = D - mean(D)` and estimate positive-side 80%-power MDE:

```
critical = quantile(E, 0.975)
crossed_MDE80 = critical - quantile(E, 0.20)
```

The explicit +5bp control passes only if crossed empirical power at +5bp is >=80%. The crossed CI, MDE, and
power are load-bearing; if the control fails, no method-scoped null can be earned. A positive promotion also
requires a positive crossed CI, while disagreement with either one-way diagnostic must be surfaced.

All time and crossed draws use the single frozen calendar lattice from 2025-11-01 through the registered
202606 common-cutoff day, including leading, trailing, and interior zero-entry days. Each compared arm must
contain at least 10 distinct wallets and entries in at least 10 distinct fixed seven-day calendar blocks.
Bootstrap draws are never retried or silently conditioned: if more than 1% have a zero arm denominator, the
comparison is `SPARSE_NOT_ESTIMABLE` with point estimates only, and cannot enter promotion or null verdicts.

Outcome-support missingness is load-bearing governance, not a cosmetic funnel. For every comparison report
accepted-capacity and excluded counts/rates by arm, fold, coin, wallet, UTC hour, and realized context-gap
day. The comparison is `MISSINGNESS_UNRESOLVED`—with no positive promotion and no method-scoped null—if any
arm loses more than 1% of accepted-capacity trades overall, more than 2% in any populated fold, or if the
two arms' overall exclusion rates differ by more than 0.5 percentage point. These thresholds are frozen
before the amended run. Unsupported trades remain in capacity accounting but have unknown outcome; they are
never assigned a zero return or replaced by later trades.

Rate gates alone do not control tail bias. Freeze a ±2,000bp eight-hour missing-return envelope and compute
a partial-identification interval for each comparison by assigning every genuinely unpriced accepted EW trade
the adverse endpoint and every genuinely unpriced control trade the favorable endpoint, then reversing the
assignments. Also compute the comparison on every accepted-capacity trade whose actual signal coin has an
observable valid 90-second entry/exit, even when an unrelated major caused all-four support failure. Report
the mean excluded actual-coin outcome and the excluded-outcome mean required to erase both zero and the +5bp
care effect. Recompute the all-actual-coin estimate and both ±2,000bp partial-identification endpoints inside
every load-bearing crossed wallet×time draw. A positive claim requires the common-support crossed CI lower
bound, all-actual-coin crossed CI lower bound, and the 2.5th percentile of the adverse bounded endpoint all
to exceed zero. A method-scoped null requires the common-support MDE gate plus the common-support CI upper
bound, all-actual-coin CI upper bound, and the 97.5th percentile of the favorable bounded endpoint all below
+5bp. Otherwise the comparison is `MISSINGNESS_UNRESOLVED`. Any surviving conclusion is explicitly
conditional on the ±2,000bp stress envelope, which is not a claim that larger eight-hour moves are impossible.

For the four secondaries, use the crossed distribution `D` to compute a two-sided centered-bootstrap p-value as
`(1 + count(abs(E) >= abs(observed_delta))) / (B+1)`. Apply deterministic monotone Holm step-down ordering by
`(raw_p, comparison_name)` and report raw p plus adjusted q. A positive promotion requires adjusted q<=.05,
positive direction, and a positive crossed CI; ordinary 95% CIs remain descriptive, not simultaneous.
Method-null claims for the four secondaries form a separate multiplicity family. For each comparison, test
`H0: improvement >= +5bp` one-sided in the common-support, all-actual-coin, and favorable bounded-endpoint
crossed distributions; use the maximum of the three p-values as a conservative intersection-union p-value.
Apply deterministic Holm adjustment across the four such p-values. A secondary method-null flag requires
adjusted null q<=.05 in addition to the MDE and all missingness-sensitivity gates.

The aggregate wallet- and time-cluster procedures are the cross-unit combination. Because folds and coins are
dependent, no exact fold/coin sign p-value may earn a positive or null. The burned diagnostic cannot earn a
global null regardless; a forward null still requires the full gate in `AGENTS.md`.

## 8. Controls and governance

Before trusting a real result:

- deterministic unit tests for weighted mean/variance, effective N, exact top-30, shock reset/quarantine,
  copyability gate, split-fill invariance, wallet/coin caps, and consensus distinct-other logic;
- tests for common-pool mutation and literal-TSTAT reconciliation, short rosters, exact-money $250 boundaries,
  next-month and truncated-final-fold context, and strictly-post-signal entry execution before capacity;
- exact partial-day exception test for 2026-05-30 plus a full 2026-05-31: endpoint shortfall is recorded,
  missing-entry signals reserve proxy capacity/no-backfill, May-31 trades remain eligible, any other partial
  day fails, and the common cutoff still uses final per-major context maxima;
- no-backfill tests proving that changing outcome-support/exit availability cannot change accepted indices or
  consensus, unsupported accepted trades retain capacity, capacity expires only at entry+8h+90s, and
  `accepted_capacity = support_estimand + support_excluded + defensive_exit_failure`;
- online shock day boundaries, funnel conservation, missingness rate/bounded-sensitivity gates, and
  cache-dependency mutation;
- synthetic end-to-end selector control where a recent persistent standardized edge is recovered by EW_T;
- synthetic blowup control where a previously strong wallet is quarantined/reset;
- +5bp inference control under the load-bearing crossed wallet×time product-weight resampling, with one-way
  wallet and time diagnostics. Draws are never retried; the frozen invalid-draw-rate gate fails inference;
- independent correctness, statistical-rigor, and leakage audits before run;
- independent steelman-positive and prosecute-positive audits after run.

Historical output status is always `POST-HOC BURNED DIAGNOSTIC; NOT FORWARD EVIDENCE`. A positive may nominate
one frozen forward selector only after multiplicity, concentration, controls, and construction checks. A null
requires point/CI, MDE <=5bp, cross-unit combination, and construction conservatism; otherwise the result is
inconclusive/underpowered with its point direction surfaced.
