# CR<=50 entry filter — frozen forensic architecture

**Status:** frozen before reading filtered-book outcomes. The 2025-11 through 2026-06 folds and the
`CR<=50` idea were supplied after inspection and are burned. A favorable result can only be an unresolved
descriptive residual; it is never fresh, suggestive, a candidate, or deployable. Consensus/opinion trading,
the BOT500 screen, and the one-side-per-coin policy are excluded so this test changes one mechanism only.

## Question and single registered rule

Does the frozen unscreened pooled-wallet Efron top-30 majors book improve when it refuses a copied entry
whose trader notional is more than 50 times that trader's typical notional?

For candidate entry `j` from wallet `w` in evaluation fold `T`, define:

`typical(w,T) = median formation entry notional`

over the same three full calendar months used to form fold `T`, pooling BTC/ETH/SOL/HYPE flat opening-taker
entries for that wallet with notional >=$250. Lowercase every wallet before joining. Read each formation
notional as `DECIMAL(38,10)`, sort exact Decimals, and define the continuous median as the middle value for
odd `n` or the exact arithmetic mean of the two middle values for even `n`; the result therefore has at
most 11 decimal places and is serialized as a canonical plain decimal string. Formation rows come only from
the lineage-validated
`alt_universe_open_entries` lake and therefore already satisfy crossed, `Open Long`/`Open Short`, and
`start_position=0`. Require `ts` strictly before the first instant of `T`; bind the exact three formation
months and source lineage. Define `CR_j = candidate_notional_j / typical(w,T)`. Convert the promoted
candidate's canonical DOUBLE with `Decimal(repr(float(candidate_notional)))` and decide membership by exact
cross multiplication `candidate_decimal <= Decimal(50) * typical_decimal`; never decide with floating
division. The sole filtered rule is `CR_j <= 50`; equality passes. A candidate with no finite positive typical notional passes through and is
reported separately, so the arm changes only rows demonstrably above the registered ratio rather than
silently adding a history-availability screen. Do not update the median with evaluation-fold entries and do
not use any markout, future trade, or outcome in the rule.

There is no cutoff sweep. `50` is the user-specified primary and only threshold.

## Bound inputs and cache

Use the exact hash-bound `WALLET_E30` rosters and promoted evaluation entry artifacts from
`data/derived/copy_cohort/wallet_coin_t30/`. Fail closed on parent status/governance, roster/code/dependency
hashes, all eight entry/meta records, exact baseline supported/capacity hashes, funnels, missing counts, and
headline arithmetic. Do not refit Efron or rescore wallets.

Cache only the small formation-scale table under
`data/derived/copy_cohort/notional_cr50_filter/formation_scales.json`. Each `(fold,wallet)` row must include
the median, formation count, formation months, roster membership, and a hash-bound source-lineage record.
The cache specification binds architecture/runner/dependencies, exact roster-report SHA, majors, $250
floor, estimator, and input object manifest. Enforce exactly 30 distinct lowercase roster wallets and
exactly 30 canonical rows per fold, one per expected roster key, with zero extras/duplicates; write explicit
`n_formation=0` and `typical_decimal=null` rows for zero history.

Before every outcome run—including cache reuse—recompute the complete table from the formation source in
two independent ways: (1) fetch canonical `DECIMAL(38,10)` rows and compute counts/continuous medians in
Python; (2) a separately structured DuckDB grouped `count`/continuous-median query that first widens each
source value to `DECIMAL(38,11)` so an even-sample half-tick remains exactly representable. Require
exact count and canonical-decimal value parity, exact expected key coverage, and an identical ordered-row
hash. Capture source lineage/object manifests before the first query and after the second and fail on any
mutation. Write a new/repaired cache and its metadata through temporary files followed by atomic rename;
the metadata binds the final cache bytes. Revalidate lineage, content oracle, and every cached byte before
outcome computation and again before publication.

## Arms and replay

Both arms begin from empty state and independently replay globally in canonical
`(ts,wallet,coin,dir_sign,notional,source_id)` order:

1. `VIRTUAL_SLEEVES`: the exact parent `WALLET_E30` candidate stream and capacity rules.
2. `CR50`: the same complete candidate stream after applying the outcome-blind `CR<=50` rule before any
   capacity decision. Above-threshold rows never reserve capacity and are not reconsidered later. Remaining
   rows use the unchanged one-open-wallet×coin, $50,000 gross coin cap, fixed $5,000 sleeve, 8-hour expiry,
   and exits-before-entries behavior. Opposite-direction sleeves remain allowed.

Run NaN and deterministic-noise shadows and require identical CR values, kept/rejected source identities,
accepted identities, and funnels. Independently reproduce the unfiltered parent implementation and exact
published hashes/headlines.

## Registered outputs and inference

- Costs remain 5.5bp per accepted supported sleeve. PnL is `net_bp*$5,000/10,000`, credited on the 8-hour
  exit UTC day over the complete 242-day calendar including zero days.
- Primary contrast is `CR50 - VIRTUAL_SLEEVES` total net dollars. Also report accepted/supported/missing,
  total PnL, net mean/median bp, trade and active-day hit rates, profit factor, Sharpe, Sortino, maximum
  drawdown, positive exit months, gross/absolute-net exposure, and deltas.
- Report the full candidate CR distribution; scale coverage; rejected counts by fold, coin, direction, and
  wallet; each rejected row's source identity hash; and per-fold/per-coin book deltas. Define fixed-book
  additive wallet attribution as `contrib_w = CR50 supported net$ for w - baseline supported net$ for w`
  and assert contributions sum to the primary delta. Rank wallets by absolute contribution, report the
  top-five absolute share, and report cumulative fixed-book leave-top-k deltas for `k=1..5` by subtracting
  those ranked contributions. Sort by `(abs(contrib) DESC, wallet ASC)`; define top-five absolute share as
  `sum(abs(contrib) for first five) / sum(abs(contrib) for all wallets)`, or zero when the denominator is
  zero. Do not remove wallets and replay capacity; that is a different estimand. Freeze `top5_abs_share<=0.50`
  as a required breadth gate for a narrow adverse-policy claim. Concentration is diagnostic-only for the
  aggregate no-material/equivalence claim because a tight aggregate interval already bounds policy impact.
- Use the exact paired noncircular seven-day moving-block inference frozen in
  `SAME_COIN_DIRECTION_POLICY_ARCH.md`: 10,000 `default_rng(20260722)` draws, raw-total percentile CI,
  centered-null two-sided p, symmetric positive/negative power, MDE80, and +/-$2,500 injections. Reuse the
  identical block-index matrix across observed and missing constructions.
- Run fold and coin exact two-sided sign tests separately, excluding exact ties and never pooling the two
  non-independent families.
- Apply the inherited missingness gates: <=1% overall in each arm, <=2% in every arm-fold, and <=0.5
  percentage-point overall arm-rate imbalance. Per-fold arm imbalance is diagnostic only.
- Couple missing outcomes by full source identity. Shared accepted missing rows receive one latent endpoint
  and cancel in total-dollar contrast; only arm-exclusive missing rows receive opposing +/-2,000bp endpoints.
  Use coefficient-correct accepted-denominator mean-bp bounds and run full paired inference for adverse and
  favorable constructions.

## Decision and publication

Use the same mutually exclusive $2,500 materiality predicates as the same-coin study, binding controls
conservatively across observed/adverse/favorable constructions:

- `NARROW_POLICY_ADVERSE` only if all construction/missingness gates pass, top-five wallet absolute share is
  <=0.50, the favorable-construction upper CI is below -$2,500, and the binding negative-tail
  MDE/power/injection controls pass.
- `NARROW_POLICY_NO_MATERIAL_EFFECT` only if all gates pass, the conservative missingness interval lies
  strictly inside +/-$2,500, and both binding tail controls pass.
- Otherwise `UNRESOLVED`. A favorable direction is always `UNRESOLVED` under burned governance regardless
  of nominal p-value.

Before computation atomically publish a non-result marker to
`data/derived/copy_cohort/notional_cr50_filter/report.json`. Failure writes contain no comparative fields.
The final atomic report binds an initial execution seal containing architecture/runner/dependency hashes,
parent report/roster and all evaluation artifacts, formation-cache bytes/spec/lineage, candidate/CR/filter/
accepted/supported/funnel/daily/exposure hashes, RNG specification, shadow results, and every gate. Recompute
the complete seal after report assembly immediately before publication and fail if it changed. Force
`positive_promotion_eligible=false` and `method_null_eligible=false` unconditionally.

Required final framing: **burned CR<=50 entry-filter diagnostic; a favorable point is an unresolved
descriptive residual, not established or deployable; a null/negative requires the full CI, MDE/control,
cross-unit, missingness, and construction gates.**
