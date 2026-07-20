# NESTED-T FILTER — parity-locked dynamic trader-quality diagnostic

**Status:** selector and comparison architecture frozen before implementation or outcome reads on
2026-07-19 (frozen selector document SHA-256
`c81ba7933d3d58e1f3bb3c73aeb3053865d23004f7502a926a6f03858ae32d2c`). The legacy parity ladder in
§3 was amended later on 2026-07-19 after the hard gate exposed 75 newly supported historical-cache
rows. That parity-only amendment used entry-support/mark data, occurred before any comparative filtered
outcome was calculated or interpreted, and is post-hoc rather than preregistered. Historical folds
202511–202606 are already burned; this study is diagnostic only and cannot promote a deployable rule.

## 1. Question and reason for the rebuild

Does a slowly changing, per-wallet latent mean of majors capped daily PnL improve the rolling top-30
majors copy book without replacing the successful static statistic with a different estimand?

The prior `KF_REL` and adaptive R/Q studies were not nested modifications of the original selector. They
rank-normalized PnL cross-sectionally or divided each wallet by a robust scale, changed eligibility, and
used different execution/accounting. This study therefore starts with hard parity gates. No filtered
return may be interpreted unless the static selector and original Book-B mechanics reproduce first.

## 2. Frozen data and folds

- Formation: the three complete calendar months strictly before each fold.
- Evaluation folds: 202511, 202512, 202601, 202602, 202603, 202604, 202605, 202606.
- Coins: BTC, ETH, SOL, HYPE only for the score and the copied book.
- Daily observation, copied literally from `majors_native._select_top100`:
  `x[i,d] = (sum(pnl)-sum(fee)) * min(1, 100000/sum(notional))` over majors.
  Builder fee is not introduced because the parity target did not subtract it.
- Eligibility: at least 15 active formation days and positive sample variance. There is no recency,
  effective-N, or frozen-wallet exclusion in the comparative family. The global frozen-133 set contains
  wallets learned from future folds and is therefore used only by the explicitly contaminated
  `LEGACY_STATIC_T30` parity arm; it never enters a comparative selector.
- Evaluation entries and midpoint marks copy the historical majors cache rule literally: every flat taker
  open row with notional >= $250; midpoint at-or-before signal and at-or-before signal+8h; both <=90s
  stale. This is a historical-parity diagnostic, not a claim that backward-ASOF is the final live entry
  convention.

## 3. Hard parity ladder

The run must stop before filtered outcomes if any gate fails:

1. `LEGACY_STATIC_T30` must be exactly identical, wallet-for-wallet and order-for-order in every fold, to
   `majors_native._select_top100(... )[:30]`.
2. The independently materialized `filtered_quality` legacy-x panel is the daily reference. That prior
   code path executes the literal `sum(pnl)-sum(fee)` majors grouping and cap separately from this study;
   its saved code/config and source-manifest identity must match the current validated manifest or the run
   fails as stale. A local DuckDB aggregation of that immutable reference supplies the independent summary
   oracle without re-reading the remote three-month lake twice. Before any Efron or filter output, it emits
   and matches the candidate multiset of `(wallet,day,day_pnl,day_notional,x)`, with wallet/day exact and
   floating fields at `atol=1e-9, rtol=1e-12`. Both paths must have exactly one row per wallet/day, strictly
   increasing unique in-window ordinals within wallet, and the same last-observation ordinal. Only after
   daily-row parity, the full eligible wallet multiset and each wallet's nd, mu, sd, and t are compared
   (nd exact; floating fields at the same absolute-plus-relative tolerance); exact top-30/order remains a
   separate hard gate. The candidate path computes daily rows then aggregates in NumPy, so this is not the
   same query serving as its own oracle. Source lineage,
   ordered-roster hash, reference SQL hash, and code/config hashes are recorded; stale legacy caches are
   not the oracle.
3. A constant-R, Q=0 diffuse-prior recursion must reproduce each comparative-pool wallet's ordinary
   t-stat to absolute tolerance 1e-9 and must produce the identical top-30. This is `IDENTITY_Q0_T30`.
4. A clean temporary literal legacy entry query is compared with a separately written current-source
   oracle that follows the complete historical `p0 -> p1 -> p4 -> p8 -> p24 -> p48` ASOF chain. They must
   reproduce the same current finite-entry count and multiset of `(wallet,coin,ts,notional,mk8)` at
   tolerance 1e-10. The old `majors_native` cache is retained as a historical-subset audit rather than
   treated as current truth: the pre-outcome parity run found it was missing 75 newly supported month-end
   rows (33/17/4/21 in 202601/02/03/05) while no cached row disappeared. Every old row must therefore be
   present with the same mark in the fresh current query; additions are enumerated per fold. Duplicate
   `(wallet,coin,ts)` and opposing-direction counts are printed. Because the old cache dropped direction
   and lacks a unique fill id, comparison is multiset-based; an opposing-direction tied row blocks
   accepted-row identity claims rather than being assigned an invented identity.
5. Passing the old-cache subset of the fresh query through fixed $5,000 clips, max one concurrent
   wallet×coin position, $50,000 gross per coin, 8h hold, and 5.5bp cost must reproduce historical Book-B
   accepted rows, skips, and mean net bp to tolerance 1e-10. The full refreshed current query is also
   passed through the same mechanics and reported separately. Both gates run before comparative outcomes
   are loaded.

The report records every parity difference even when zero. A failed gate emits `PARITY_FAILURE`, writes no
comparative verdict, and terminates nonzero.

## 4. Nested filter

For wallet i, estimate one latent mean daily capped PnL:

    x[i,d] = theta[i,d] + epsilon[i,d]
    theta[i,d] = theta[i,d-1] + eta[i,d]

The wallet's base observation variance is its ordinary three-month sample variance `R_i = s_i^2`. The
diffuse-prior scalar recursion treats the first observation as `theta=x` and `P=R`; subsequent calendar
days predict `P <- P + gap*Q` and update with `K=P/(P+R_day)`. After the final observation, P is predicted
through `formation_end_ordinal - last_observation_ordinal`; theta is unchanged under the random walk. The
cutoff score is `theta / sqrt(P)`. With Q=0 and constant R this is algebraically the original t-stat.

The base dynamic speed is expressed as an equivalent steady-state observation half-life:

    K_h = 1 - 2^(-1/h)
    Q_i / R_i = K_h^2 / (1-K_h)

Registered speeds are h=60 days (`KF60`) and the deliberately slower h=120 days (`KF120`). No other
half-life is searched.

## 5. R, blow-up, Efron, and bot variants

All variants use the same daily x, base eligibility, folds, entry engine, sizing, and costs.

- `R_VOL`: for every formation day, sample each major at the first midpoint at/after each UTC five-minute
  target from 00:00 through 23:55, requiring all 288 targets and <=90s target lag. Compute each coin's
  square-root sum of 287 squared log returns, then the root mean square across the four coins. Day d uses
  the most recent valid completed day strictly before d; divide it by the median of the preceding 20 valid
  completed RV days (minimum five; otherwise multiplier 1), square the ratio, and clip the final multiplier
  to [0.5,4]. A day without a prior valid RV uses 1.
- `R_BREADTH`: multiply R by `clip(breadth^(-1/2),0.5,4)`, where daily breadth is the summed majors
  `n_open_flat` (floored at 0.25) divided by `4*notional_HHI`; HHI is the sum of squared exact Decimal
  major-coin notional shares. Zero/invalid day notional is excluded; invalid HHI fails the fold.
- `BLOWUP`: on a day with a recorded liquidation or x <= -$100,000, reset theta to at most -3 daily-PnL
  standard deviations and P to at least R before consuming that day's observation. It is a separate
  diagnostic, not silently applied to the base.
- `ALL`: h=120 plus R_VOL, R_BREADTH, and BLOWUP.
- `BOT500`: a separate pool excludes wallets whose all-coin formation fills per all-coin active day exceed
  500: numerator `SUM(n_fills)` and denominator `COUNT(DISTINCT day)` across every wallet-coin-day row in
  the same three formation months.
  The screen happens before Efron fitting and top-30 selection, and the top 30 are refilled. No taker-share
  rule is added. The unscreened family remains the parity anchor because the published majors winner had
  no bot screen.

Efron is a non-load-bearing wrapper diagnostic only. `STATIC_E30` applies the exact
`informed.t_to_z(t,nd-1)` and `informed.two_groups` implementation to the complete static eligible pool,
requires a finite successful fit, excludes non-positive underlying t scores, then ranks `p_informed`
descending, t descending, wallet ascending. This prevents two-sided local-FDR from selecting extreme
losers. No dynamic Efron arm is interpreted: a Q>0 state score does not have an ordinary active-day
Student-t null law, and this study does not invent one after seeing outcomes.

Registered arms:

- `LEGACY_STATIC_T30`, `STATIC_T30`, `IDENTITY_Q0_T30`, `STATIC_E30`
- `KF60_T30`, `KF120_T30`
- `KF60_R_VOL_T30`, `KF60_R_BREADTH_T30`, `KF60_BLOWUP_T30`
- `KF120_ALL_T30`
- `STATIC_BOT500_T30`, `KF120_ALL_BOT500_T30`

Consensus/opinion gating is excluded.

## 6. Guardrails before outcome interpretation

- Exact 30 unique wallets per arm/fold and deterministic wallet tie-break.
- Report Spearman rank correlation over the full common eligible pool and roster overlap versus the
  matching static control per fold.
- A slow-filter construction warning fires when any KF120 arm overlaps its static control by fewer than
  15/30 wallets in a fold. It does not erase outcomes, but forbids describing that arm as a slight filter.
- Record selected-wallet evaluation entry counts before capacity. Sparse selection is surfaced, not hidden.
- Selection and cache artifacts bind source manifests, code hash, config hash, and exact roster hash.

## 7. Outcomes and inference

For every arm report both:

1. Raw finite 8h gross markout: equal-entry mean/median/hit rate and original registered p95-winsorized,
   wallet-fold-equal point.
2. A comparison book with the historical $5,000 clip, one concurrent wallet×coin position, $50,000 coin
   cap, 8h hold, and 5.5bp cost, but corrected capacity ordering. The complete pre-outcome signal stream is
   cut at one common context-maturity timestamp per fold and sent through capacity before outcome support
   is checked. Unsupported accepted signals reserve their slot until signal+8h and are retained as missing.
   Report support loss overall/per fold/per coin/per wallet, arm-rate imbalance, and analyzed net bp.

`LEGACY_BOOK_B_PARITY` separately reproduces the historical priceable-first book and headline but is never
used for arm inference. Comparative positive or `<+5bp` language additionally requires <=1% overall loss,
<=2% loss in every fold, <=0.5 percentage-point arm imbalance, an all-actual supported comparison, and
registered adverse/favorable bounds assigning missing filtered/control returns respectively to -/+2000bp
and +/-2000bp. Failure yields `MISSINGNESS_UNRESOLVED`.

Primary contrast: `KF120_T30 - STATIC_T30` on comparison-book net bp/accepted supported entry. Secondary
contrasts are `KF60_T30-STATIC_T30`, `KF120_T30-KF60_T30`, each R/blow-up component versus `KF60_T30`,
`KF120_ALL_T30-KF120_T30`, `STATIC_BOT500_T30-STATIC_T30`, and
`KF120_ALL_BOT500_T30-STATIC_BOT500_T30`. `STATIC_E30-STATIC_T30` is a separately labeled memory/lineage
diagnostic and does not enter the filter family. Secondary positive and +5bp-null families use Holm.

Each comparison reuses the exact audited `dynamic_t_book.compare` statistic and RNG mapping with 10,000
draws: one shared union-wallet multinomial multiplicity vector for both arms; one paired moving-block draw
over the fixed 2025-11-01 through 2026-06-30 UTC daily lattice using seven-day blocks, uniform valid block
starts, ceil(calendar-days/7) sampled blocks and truncation to the calendar length; crossed draws multiply
those same wallet and day weights; each arm retains its own weighted denominator. Seeds are 20260719 plus a
fixed registered contrast index. Invalid draws >1% fail inference. The centered crossed-bootstrap noise,
percentile CI, two-sided plus-one p, one-sided +5 null p, MDE80, and power formulas are those in
`dynamic_t_book.compare`. The end-to-end injected control first null-centers each arm by subtracting its
own observed mean, then adds exactly +5bp to every filtered-arm row and passes both centered books through
the ordinary comparison path with the registered seed. Its point must equal +5bp and its crossed lower 95%
CI must exceed zero; this tests recovery of a +5 perturbation without contaminating the control by the
observed delta. An uncentered `net_bp+5` run, if printed, is labeled plumbing identity only. Report per-fold
and per-coin deltas and positive counts. Care effect is +5bp.

For each contrast, wallet contribution is frozen as
`sum(filtered wallet bp)/n_filtered - sum(control wallet bp)/n_control`, which sums to the raw arm-mean
difference. Report contributing-wallet count and the top-five share of total absolute wallet contribution.
Any top-five share above 50% is labeled concentrated and forbids carrying a positive directional point
without an explicit concentration caveat.

Because every fold and design choice is burned, `positive_promotion_eligible=false` and
`method_null_eligible=false` unconditionally. Within-run direction/resolution diagnostics still print CI,
MDE, injected control, cross-unit combination, and construction/missingness checks, but cannot earn formal
positive or null language. Positive framing faces the symmetric multiplicity, dependence, concentration,
and post-hoc gates.

## 8. Required audits and reporting

Before build: independent correctness, statistics, and leakage/firewall architecture audits. After build:
repeat all three on code and tests. After the run: one independent steelman-the-positive pass and a separate
prosecute-the-positive/noise pass. Then update `FINDINGS.md` with the calibrated result, caveats, and artifact
paths before starting another study.
