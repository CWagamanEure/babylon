# WALLET×COIN T30 — majors pair-specific rolling selector

**Status:** architecture frozen before implementation or reading this selector's outcomes on
2026-07-19, then tightened before implementation/outcomes in response to independent architecture audits.
The evaluation folds and pooled-wallet majors results are already burned. More importantly, these same
folds were explicitly retired after the earlier hierarchical wallet×coin closing look
(`wallet_coin_selector.py`; `FINDINGS.md` 2026-07-16 addendum 6). The user has explicitly authorized this
forensic rerun, but it is an adaptive reopening of a related family: it cannot establish a deployable rule,
count as fresh OOS validation, become a paper candidate, or receive `suggestive positive` language.

## Question and estimands

Does replacing the pooled-wallet formation statistic with a separate wallet×coin statistic improve the
otherwise identical rolling majors top-30 copy book?

The primary arm is `PAIR_T30`: select the 30 highest ordinary active-day t-stat **wallet×coin pairs**
globally in each fold, then copy each selected wallet only in the selected coin. The primary absolute
descriptives are supported-book net mean/median bp per accepted entry, hit rate, positive evaluation
months, entry/wallet/pair counts, net dollars, per-month and per-coin results, and concentration.

Two controls prevent conflating the requested axis with unrelated changes:

- `WALLET_T30`: ordinary top-30 pooled-wallet t-stat, copying all four majors. The registered relative
  contrast `PAIR_T30-WALLET_T30` is explicitly a **composite deployable construction contrast**: 30
  pair seats with coin restriction versus 30 all-major wallet seats. It does not isolate a pure ranking-
  statistic mechanism because coin restriction, unique-wallet count, candidate flow, coin mix, and
  capacity use also change.
- `PAIR_E30` and `WALLET_E30`: exact Efron/local-FDR wrappers over their respective complete eligible
  pools. `WALLET_E30` must reproduce the saved standard Efron roster exactly in every fold before any
  new outcome is interpreted. `PAIR_E30-WALLET_E30` is a sensitivity matching the previously reported
  best book's selector family. The requested primary remains direct `PAIR_T30`.

No consensus/opinion signal, bot screen, filtering, frozen-wallet exclusion, notional-proportional sizing,
or horizon search is allowed.

## Formation and selection

- Folds: 202511 through 202606. Formation is the three complete calendar months strictly before each fold.
- Coins: BTC, ETH, SOL, HYPE.
- Pair-day primary observation:

      x[w,c,d] = (sum(pnl)-sum(fee)) * min(1, 100000/sum(notional))

  where every sum is within wallet×coin×day. Builder fee is excluded to match the pooled-wallet book.
  This is turnover normalization, not clipping PnL to +/-$100,000.
- Pair eligibility: at least 15 active pair-days and positive sample variance. Score
  `t = mean(x)/(sd(x)/sqrt(nd))`. Rank globally by t descending, wallet ascending, coin ascending; select
  exactly 30 unique pairs. A wallet may occupy multiple seats if multiple coins rank in the top 30; this
  is intentional because the unit being ranked is the pair. Report both seat and unique-wallet counts.
- Pooled controls aggregate all four majors to wallet-day before applying the same $100k normalization,
  require `nd>=15` and positive variance, and rank exactly as the audited nested-t study.
- Efron arms transform every eligible t with exact `informed.t_to_z(t, nd-1)`, independently fit
  `informed.two_groups` to the entire matching eligible pool, exclude non-positive t, and rank
  `p_informed` descending, t descending, wallet ascending, coin ascending. Finite complete fits and ordered
  input hashes are mandatory. `WALLET_E30` must equal the saved E30 roster order; `WALLET_T30` must equal
  the saved static T30 order.
- Comparator parity is a full-pool hard gate, not merely selected-roster equality. Before exposing any
  pair outcome, independently materialize the wallet-day rows and require exact wallet/day equality plus
  numeric parity for PnL, notional, and normalized x; then require ordered eligible wallet, nd, mean, SD,
  t, t-to-z, Efron fit-input hash and fit-parameter parity against the lineage-locked nested/Efron parent
  artifacts. Only after those pass may saved T30/E30 roster identity be checked. Drift outside the top 30
  fails the run even if the final roster happens to be unchanged.
- Pair-pool Efron `p_informed` is a frozen ranking coordinate, not a calibrated literal probability of
  trader skill: pairs from the same wallet are dependent and can enter the fit multiple times. Report
  eligible pairs per unique wallet and selected unique-wallet counts.
- Registered construction sensitivity `PAIR_T30_WALLETDAYCAP` uses the same pair PnL numerator but the
  pooled wallet-day majors notional in the cap multiplier. It is reported separately and cannot replace
  the primary after outcomes are seen.

## Evaluation book

Use the existing immutable majors flat-taker opening-entry and midpoint context sources. For each fold,
query the union of selected wallets, retaining only entries whose `(wallet, coin)` is selected for a pair
arm; wallet controls retain every major for a selected wallet. Requirements:

- source opening notional at least $250;
- historical backward-ASOF midpoint at signal and signal+8h, each no more than 90 seconds stale;
- one common maturity cutoff per fold: the least mature major context maximum minus 8h;
- fixed $5,000 accepted entry;
- at most one concurrent position per wallet×coin;
- $50,000 gross exposure per coin;
- fixed 8h hold and 5.5bp round-trip cost;
- one globally chronological capacity stream across folds, with positions/exposure carried over month
  boundaries; allocate capacity before checking outcome support, and keep unsupported accepted entries as
  missing until their scheduled exit.
- The total candidate order is exactly `(ts, wallet, coin, dir_sign, notional, stable_source_ordinal)`.
  If a source ordinal is unavailable, exact duplicate rows with identical preceding keys and identical
  marks are exchangeable, but any non-identical unresolved tie fails the run. Hash and validate the ordered
  stream; include a simultaneous same-coin cap-collision unit test.

All artifacts live only under a new `data/derived/copy_cohort/wallet_coin_t30/` namespace. Reuse of
`wallet_coin_cache/`, `wallet_coin_selection/`, or any other earlier wallet×coin cache is forbidden. The
formation sources are explicitly the research-lane `alt_universe_wallet_coin_day` partitions; evaluation
is `alt_universe_open_entries` plus exact `_ctx_parts` files. Every cached panel/entry and JSON report must
be atomically published and bind: pre/post `validated_lineage`, architecture/code/dependency hashes, exact
formula/config, ordered full-pool and arm roster/pair hashes, context path/size/SHA records, common cutoff,
and the cached Parquet byte size/SHA. Any mismatch rebuilds or fails closed; no existence-only reuse.

Before exposing pair-arm outcomes, the new union cache must reproduce both audited pooled controls at the
**book** level, not just the roster level. Replay the lineage-bound parent E30 and T30 entry artifacts and
require exact equality of common-cutoff metadata, ordered selected source rows, capacity funnels/skips,
accepted ordered rows, support/missingness cells, raw statistics, supported book hash, net mean/median/hit
rate, and dollars. Also assert every pair-arm candidate is an exact fold-specific selected `(wallet,coin)`
subset, and that adding pair-arm wallets to the union cache does not change either pooled control outcome.
Containment is insufficient: independently query the lineage-bound `alt_universe_open_entries` source for
every fold's selected pairs under the registered majors/notional/common-cutoff rule, attach/preserve its
stable source identity, and require exact ordered multiset equality to the emitted pre-capacity pair stream.
Report explicit missing, extra, and duplicate anti-join counts (all must be zero). No selected-pair source
row may be lost because its wallet is absent from either pooled-control roster.

The primary reporting basis is the supported capacity book. Also report raw finite gross equal-entry
mean/median/hit rate and the existing p95-absolute-winsorized, minimum-three-entry, wallet-fold-equal point.
Because selected pairs can have sparse forward flow, report zero-entry seats and per-fold accepted support.

## Inference and guardrails

The registered contrast is `PAIR_T30-WALLET_T30`. Secondary contrasts and seeds are frozen in this order:

1. `PAIR_E30-WALLET_E30`, seed 20260722;
2. `PAIR_T30_WALLETDAYCAP-WALLET_T30`, seed 20260723;
3. `PAIR_T30-PAIR_T30_WALLETDAYCAP`, seed 20260724 (cap-mechanism diagnostic).

The primary seed is 20260721. Secondary positive and `<+5bp` p-values are Holm-adjusted in separate
families; no secondary may replace the primary. Reuse the audited bootstrap statistic and fixed
2025-11-01 through 2026-06-30 calendar with 10,000 draws.

Run two complete crossed inference families for every observed, all-actual, adverse/favorable, MDE/power,
and injected-control construction: (a) shared union-wallet multinomial multiplicities × paired seven-day
moving blocks and (b) shared union-`wallet|coin` pair multiplicities × paired seven-day moving blocks.
Within each family the two arms use the same calendar-block draws. The wallet and pair families use
deterministic, family-specific block schedules from the same block-generating distribution; sharing exact
block realizations across the two cluster definitions is not required. Both require at least 10 clusters and 10 occupied blocks and <=1% invalid
draws. Bind with the interval envelope `[min(lower), max(upper)]`, `MDE=max`, `power=min`, and p-value=max;
every positive/null/control gate must pass **both**, never whichever interval merely has greater width.
Report both complete families plus the binding envelope, per-fold/per-coin deltas/signs, and top-five wallet
and wallet×coin pair contribution shares. Also report the wallet-only, pair-only, and time-only CIs as
diagnostics; only the crossed envelope binds.

Missingness gates match the nested/Efron studies: <=1% overall, <=2% in every fold, and <=0.5 percentage-
point arm imbalance. Endpoints are **net bp** assigned only to missing capacity-accepted entries; observed
outcomes remain unchanged and 5.5bp cost is never subtracted again. For an `A-B` contrast, adverse-to-A
sets missing A=-2000 and missing B=+2000; favorable-to-A reverses those signs. Each construction uses the
same paired resampling contract.

A positive directional diagnostic requires observed, all-actual, and adverse lower CIs >0 plus centered
+5 recovery under both cluster families and all rate/construction gates. A `<+5bp` method diagnostic
requires observed and favorable upper CIs <+5, MDE80<=5, power>=80%, and separately centered +5 injected
recovery for **both observed and favorable constructions under both cluster families**, plus all rate and
construction gates. Any missingness failure forces `MISSINGNESS_UNRESOLVED`.

For this backward-ASOF entry contract, `primary_supported` means capacity-accepted rows with finite
`gross_bp`; there is no second actual-outcome field. Therefore the named `all-actual` construction is
intentionally identical to the primary supported book, and the report must assert their row hashes match.
It is retained as an explicit identity gate so this study cannot silently drift to a different mask.

Primary supported-book mean, median, and hit rate are all **net of 5.5bp** over supported capacity-accepted
entries; raw candidate summaries are separately labeled gross. Positive months are reported as
`positive/evaluable, evaluable/8`; a zero-supported month is `UNEVALUABLE`, never dropped or counted as
zero. Relative fold contrasts require both arms to be evaluable. Report all eight calendar folds explicitly.

All historical outputs are stamped `BURNED_REOPENED_WALLET_COIN_FORENSIC`, with
`positive_promotion_eligible=false` and `method_null_eligible=false` unconditionally. Absolute positive
means are descriptives only. Because this is a related hypothesis-family reopening after the prior closing
look, the whole-arc multiplicity is not recoverable from this one contrast and any favorable direction is
forced to `unresolved descriptive residual, direction unknown` rather than `suggestive`, `candidate`, or
`live positive`. An adverse point likewise cannot earn a method-wide null without the registered gates.

## Required completion

Independent correctness, statistics, and leakage/firewall architecture audits before implementation.
After implementation, repeat correctness/statistics/leakage audits, run focused tests and exact report
reconciliation, then run separate steelman-the-positive and prosecute-the-positive/noise passes. Finally
record the calibrated result and all artifact paths in `FINDINGS.md` before reporting it.
