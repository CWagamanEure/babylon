# Same-coin direction policy — frozen forensic architecture

**Status:** frozen before reading the new policy's outcomes. The 2025-11 through 2026-06 evaluation folds
are burned. This is a post-hoc execution-policy diagnostic and can never be promoted, called suggestive,
or treated as deployable. A favorable result is always an unresolved descriptive residual even if a
within-run interval excludes zero. Only a powered, construction-safe adverse/no-material-effect result may
earn a narrowly policy-scoped negative; never a method-wide null.

## Question

For the frozen unscreened pooled-wallet Efron top-30 majors strategy, what changes when the book is forbidden
from being simultaneously long and short the same coin?

## Bound inputs

Use the hash-bound `WALLET_E30` rosters and promoted entry artifacts from
`data/derived/copy_cohort/wallet_coin_t30/`. Fail closed on the published report status and governance,
roster/code/dependency hashes, all eight entry and metadata records, common source construction, exact
baseline supported ordered/multiset hashes, funnels, missing counts, and headline arithmetic. Do not refit
or rescore wallets. Consensus opinion trading and the >500-fills/day BOT screen remain excluded.

Both arms independently replay from empty state the identical **complete pre-capacity WALLET_E30 candidate
stream** obtained by applying the saved WALLET_E30 roster mask to all promoted entries. Do not start from
the baseline accepted book: suppression can free capacity for later candidates. Missing-outcome rows remain
candidates and reserve capacity. Require unique `source_id`, `dir_sign` exactly in `{-1,+1}`, and the exact
global candidate key `(ts, wallet, coin, dir_sign, notional, source_id)` ascending. Report and bind the
complete ordered candidate hash and the count of same-timestamp same-coin opposite-direction pairs.

## Arms

1. `VIRTUAL_SLEEVES`: exact audited globally chronological `WALLET_E30` capacity book. Different wallets
   may hold opposite 8-hour sleeves in the same coin. Both sleeves consume gross coin capacity and cost.
2. `ONE_SIDE_PER_COIN`: same complete candidate stream and canonical order. Before processing all entries
   at a timestamp, expire every sleeve with `exit_ts <= entry_ts`; exits therefore precede entries at an
   identical timestamp. Apply mutually exclusive gates in this exact order: (1) skip if wallet×coin is
   already open; (2) skip if any still-open sleeve in the coin has the opposite `dir_sign`; (3) skip if a
   new $5,000 sleeve would exceed $50,000 gross in the coin; otherwise accept. The first canonical row at a
   same-timestamp direction tie therefore fixes the permitted side. Accepted sleeves retain their original
   8-hour expiry. Never inspect `gross_bp` or any future outcome during acceptance.

The one-side arm is a suppression policy, not early close, internal crossing, or latest-signal flipping.
Those policies need intermediate executable prices and are outside this test.

## Accounting and registered outputs

- Fixed $5,000 per accepted sleeve; net outcome is `gross_bp - 5.5bp`.
- PnL is credited on the 8-hour exit UTC day over the full inclusive 2025-11-01 through 2026-06-30 calendar;
  keep zero-PnL days. Sharpe and Sortino use the formulas frozen in
  `POOLED_WALLET_EFRON_TOP30_NOTEBOOK_SPEC.md`.
- Report trades, accepted/missing, total net dollars, net mean/median bp, trade and active-day hit rates,
  profit factor, annualized Sharpe/Sortino, max drawdown dollars and as a share of maximum gross exposure,
  average/maximum gross and absolute-net exposure, positive exit-calendar months, per-entry-fold and
  per-coin points, direction mix, same-coin conflict skips, and mixed-direction time share.
- Define gross exposure as `$5,000 * sum_coin n_open_coin`; absolute-net exposure as
  `$5,000 * sum_coin |sum_open_coin dir_sign|`. Integrate both between entry/exit events across the fixed
  evaluation span, with exits before entries at ties. Report (a) mixed active-coin share =
  `sum_coin_ms 1[long_open>0 and short_open>0] / sum_coin_ms 1[n_open>0]` and (b) any-book mixed wall-time
  share = milliseconds with at least one mixed coin divided by all evaluation milliseconds. Assert both
  mixed measures are zero for `ONE_SIDE_PER_COIN`.
- Primary descriptive contrast: `ONE_SIDE_PER_COIN - VIRTUAL_SLEEVES` total net dollars on the fixed
  horizon. Also report the mean-bp/trade and Sharpe deltas, but neither may replace the primary.
- Let `d_t = daily_net_usd_ONE_SIDE_t - daily_net_usd_VIRTUAL_t` for every one of the 242 fixed calendar
  days and `D=sum(d_t)`. Use NumPy `default_rng(20260722)` (PCG64), 10,000 draws, noncircular overlapping
  seven-day blocks: per draw sample `ceil(242/7)=35` starts uniformly with replacement from integers
  `0..235`, concatenate each `[start,start+7)`, and truncate to 242 indices. The two arms always share the
  same indices. The observed 95% CI is the 2.5%/97.5% percentile interval of resampled raw totals
  `sum(d[index])`. For the null, set `d0=d-mean(d)`, resample totals, subtract their Monte Carlo mean to get
  `noise`, and compute `p=(1+count(|noise|>=|D|))/(10000+1)`. Let
  `critical_pos=q97.5(noise)` and `critical_neg=q2.5(noise)`. Define
  `power_pos(x)=mean(noise+x>critical_pos)` and `power_neg(x)=mean(noise-x<critical_neg)` for nonnegative
  `x`; compute each tail's MDE80 by numerical bisection to $0.01. Inject both
  `d_plus=d0+2500/242` and `d_minus=d0-2500/242`, reuse the identical index matrix, assert their horizon
  points are exactly +$2,500 and -$2,500, and require respectively a percentile lower bound above zero
  and upper bound below zero. For any equivalence/no-material claim bind power as
  `min(power_pos(2500),power_neg(2500))` and MDE80 as `max(MDE80_pos,MDE80_neg)`; both controls must pass.
  An adverse-policy claim must at least pass the negative-tail control, `power_neg(2500)>=80%`, and
  `MDE80_neg<=$2,500`. Favorable direction can never promote because the folds are burned.
- Partition the observed primary dollar delta separately by entry fold and by coin. For each family report
  positive/evaluable/tied units and the exact two-sided Binomial(n, 0.5) sign-test p-value after excluding
  exact ties (`abs(delta)<=1e-12`). Never pool folds and coins or describe them as mutually independent.
- Report missingness rates overall and by fold; inherit <=1% overall, <=2% in every fold, and <=0.5
  percentage-point **overall** arm-rate imbalance gates. Per-fold arm imbalances are diagnostic only.
  Couple missing outcomes by stable `source_id`/full canonical
  identity. For total-dollar A−B bounds, shared accepted missing rows receive the same latent endpoint and
  cancel; only A-exclusive rows take -2000/+2000 net bp and B-exclusive rows take the opposite for
  adverse/favorable constructions. Report common/A-only/B-only counts and ordered hashes and run the full
  paired block inference on adverse and favorable daily constructions. For mean-bp bounds, shared missing
  rows use coefficient `(1/nA-1/nB)`, A-only `1/nA`, B-only `-1/nB`; choose -2000 or +2000 independently
  to minimize/maximize the total coefficient contribution. Also report each arm's absolute ±2,000bp range.

## Gates and framing

- Exact baseline parity, source/hash parity, deterministic candidate ordering, and outcome-blind acceptance
  are mandatory before comparative publication.
- Run an outcome-blind shadow replay after replacing every `gross_bp` with NaN and after replacing it with
  arbitrary deterministic noise; accepted identities and mutually exclusive funnels must match exactly.
- Publish only under `data/derived/copy_cohort/same_coin_direction_policy/report.json`. Before computation,
  atomically publish a non-result marker with `comparative_results_present=false`. On any exception atomically
  publish failure status without comparative fields. A final atomic report must bind architecture SHA, new
  runner SHA, dependency hashes, exact parent report/roster SHAs, every input record, RNG/block spec, complete
  candidate ordered hash, per-arm candidate/accepted/supported ordered and multiset hashes, mutually exclusive
  funnels, daily PnL/exposure hashes, shadow-test hashes, construction checks, and unconditional
  `positive_promotion_eligible=false` / `method_null_eligible=false`. Revalidate every current hash and input
  immediately before final publication; never reuse another study's success cache.
- Before any null/positive statement, report point, interval, MDE/power or injected control, fold/coin sign
  combination, missingness bounds, and construction audit.
- Freeze the materiality margin at +/-$2,500 total net dollars on the fixed horizon. Construct the
  conservative missingness interval as `[adverse-construction lower 95% CI,
  favorable-construction upper 95% CI]`; assert it contains the observed interval. The runner must bind
  these mutually exclusive claim predicates and its final label:
  - `NARROW_POLICY_ADVERSE` only when all missingness-rate, parity, shadow, and construction gates pass,
    the favorable-construction point is negative and its upper 95% CI is below the materiality boundary
    `-$2,500`, and the registered
    negative-tail MDE/power/injection controls pass.
  - `NARROW_POLICY_NO_MATERIAL_EFFECT` only when all of those non-directional gates pass, the entire
    conservative missingness interval lies strictly inside `[-$2,500,+$2,500]`, both tail controls pass,
    `max(MDE80_pos,MDE80_neg)<=$2,500`, and
    `min(power_pos(2500),power_neg(2500))>=80%`.
  - Otherwise the claim is `UNRESOLVED`. The fold and coin sign tests are mandatory reported combination
    checks but are not additional significance gates because neither family consists of exchangeable,
    mutually independent units. Any missingness-rate failure or non-estimable bound forces `UNRESOLVED`.
    These policy-scoped predicates never alter unconditional `positive_promotion_eligible=false` or
    `method_null_eligible=false`.
- Required final label: **burned same-coin execution diagnostic; favorable direction always unresolved and
  never suggestive/candidate/deployable. Only a powered construction-safe adverse/no-material-effect result
  may earn a narrow policy-scoped negative.**
