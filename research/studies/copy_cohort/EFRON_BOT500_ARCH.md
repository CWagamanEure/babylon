# EFRON BOT500 — exact HFT-screen extension of the majors top-30

**Status:** frozen before implementing or reading this extension's outcomes, 2026-07-19. The evaluation
folds and closely related Efron/static results are already burned. This is a post-hoc diagnostic and cannot
promote a deployable rule or earn a historical method null. Pre-outcome code audits tightened the frozen
design to one global chronological capacity stream and to separate observed- and favorable-construction
power/positive controls; those amendments were registered here before any extension outcome was read.

## Question

Does removing wallets with more than 500 previous all-coin fills per active day **before** the Efron fit
improve the basic majors Efron top-30 copy book?

The exact selector is:

1. Over the three complete months before each fold, aggregate BTC/ETH/SOL/HYPE wallet-day
   `pnl-fee` and total majors notional.
2. Scale daily PnL down to a $100,000 daily-turnover budget:
   `x = pnl * min(1,100000/notional)`.
3. Require at least 15 active days and positive sample variance; compute the ordinary active-day t-stat.
4. For `E30`, transform every eligible t with `informed.t_to_z(t,nd-1)`, fit
   `informed.two_groups` on the complete eligible pool, exclude non-positive t, then rank
   `p_informed` descending, t descending, wallet ascending.
5. For `E_BOT500`, first retain only eligible wallets whose formation
   `SUM(all-coin n_fills)/COUNT(DISTINCT all-coin active day) <= 500`; then independently run the same
   t-to-z and two-groups fit on that screened pool, exclude non-positive t, and select exactly 30.

Both fits must consume exactly their reported eligible multiset and return finite z, `p_informed` for every
member, and finite empirical-null parameters (`mu0`, `sigma0>0`, `pi0`). Any fit warning, exception,
nonfinite member, or silent row loss fails the fold. Record fit population size, parameters, and ordered
input hash before ranking.

Thus the bot screen changes both the Efron fitting population and the selectable population. It is not a
post-ranking deletion, and the top 30 are refilled. No taker-share or other bot rule is added.

## Frozen inputs and parity

- Folds: 202511 through 202606; formation is the three preceding complete months.
- Reuse the lineage-locked daily panels and selector report from the completed nested-t study. Validate
  current source manifests, formation context hashes, panel metadata, selector dependencies, and the frozen
  selector architecture SHA before scoring.
- Recompute unscreened `E30` from each daily panel and require exact ordered-roster identity with the saved
  `STATIC_E30` roster. Independently query the validated formation WCD source for every eligible wallet's
  all-coin `SUM(n_fills)/COUNT(DISTINCT day)` and require exact wallet/value/BOT500-mask equality with the
  panel column; then require the direct-t screened top-30 to reproduce saved `STATIC_BOT500_T30` exactly.
  This full-pool oracle runs before the Efron BOT500 fit, so a stale/corrupt screen cannot self-confirm merely
  because its selected wallets print <=500. Q=0/static and legacy Book-B parity are inherited only after validating the completed
  nested-t book report's success status and full parent chain: the selector report and panel metadata bind
  original selector architecture SHA `c81ba7933d3d58e1f3bb3c73aeb3053865d23004f7502a926a6f03858ae32d2c`;
  the nested book report binds the current amended architecture, current nested-book code, current
  `dynamic_t_book.py` inference code, and its `config.rosters_sha256` equals the byte SHA-256 of the exact
  current selector `rosters.json` reused here.
- Report eligible count, bot-eligible count, excluded count, all selected fills/day values, and exact unique
  top-30 invariants. Any selected BOT500 wallet above 500 fails the run.

## Book and outcomes

Create an isolated entry cache under `data/derived/copy_cohort/efron_bot500`; do not overwrite the nested-t
artifacts. For the union of E30 and E_BOT500 wallets, query current test-month majors flat-taker opens with
notional >=$250. Use the least mature major's context maximum minus 8h as one common cutoff per fold;
midpoints are historical backward-ASOF at signal and signal+8h with <=90s staleness.

Each fold cache has an atomic JSON sidecar and is reusable only on exact equality of: ordered union-wallet
list/hash, ordered arm-roster hash, current evaluation OPE manifest lineage, exact context path/size/SHA
records, per-major maximum timestamps and common cutoff, architecture/code/config hashes, fold, and schema
version. The finalized sidecar also binds the exact entry-Parquet byte size and SHA-256. Build to a temporary
path, re-read OPE lineage and context records after materialization, abort and remove the temporary file on
mutation, then atomically rename data and publish its bound sidecar. Any spec, size, or data-hash mismatch
rebuilds rather than accepting stale rows. This row-identity binding was added post-outcome solely to support
the diagnostic visualization atlas; the locked selector, book, and inference rules are unchanged.

The selector and final book reports are also atomic and bind this architecture/code/config, the full ordered
per-fold arm rosters plus hashes, every reused parent-artifact file SHA, each entry sidecar SHA, and the
current OPE/context lineage. Consumers require the success status and exact current hashes; a run begins by
replacing any older result with a no-results pending status and emits a no-results failure artifact on a
parity exception. The final book report binds both every entry sidecar SHA and every finalized entry-Parquet
SHA/size pair.

Both arms use fixed $5,000 entries, max one concurrent wallet×coin position, $50,000 gross per coin, 8h
hold, and 5.5bp cost. Run one globally chronological capacity stream across all eight folds while applying
the roster belonging to each row's fold; open positions and coin exposure carry across month boundaries.
Allocate capacity before checking outcome support; missing accepted entries retain
their slot. Report raw finite gross equal-entry mean/median/hit rate and the registered p95-winsorized,
minimum-three-entry, wallet-fold-equal point. Report analyzed net bp and missingness overall/per fold/per
coin/per wallet.

The sole registered contrast is `E_BOT500 - E30`. Use the exact `dynamic_t_book.compare` crossed
global-wallet × paired seven-day-block bootstrap on the fixed 2025-11-01 through 2026-06-30 calendar with
10,000 draws and seed 20260720. Report point, wallet/time/crossed 95% CIs, two-sided plus-one p, MDE80,
power at +5bp, per-fold/per-coin deltas and signs, and wallet concentration. Run the null-centered +5bp
injected control. Missingness gates and ±2,000bp adverse/favorable bounds are identical to the nested-t
study: <=1% overall, <=2% each fold, <=0.5 percentage-point arm imbalance.

Care effect is +5bp. Because this is burned/post-hoc, `positive_promotion_eligible=false` and
`method_null_eligible=false` unconditionally. A positive requires the observed and adverse-bound crossed
lower CIs above zero plus the injected control's point within 1e-10 of +5 and injected crossed lower CI
above zero. A method-scoped `<+5bp` diagnostic requires observed and favorable-bound upper CIs below +5;
separately for both the observed and favorable constructions, MDE80<=5, analytical shifted-noise power at
+5 >=80%, and a null-centered +5bp injected control whose point is within 1e-10 of +5 and whose crossed
lower CI is above zero. Observed and favorable MDE, power, and injected-control results are recorded under
distinct names, as are analytical power and empirical injection checks. The <=1%
overall, <=2% every-fold, and <=0.5 percentage-point imbalance gates are mandatory conjuncts for either
directional diagnostic; any rate failure forces `MISSINGNESS_UNRESOLVED` even if a bounded CI passes.
Otherwise report inconclusive; never convert failed power into a null.

## Required completion

Independent correctness, statistics, and leakage audits before and after implementation; focused tests;
then separate steelman-the-positive and prosecute-the-positive passes. Record the result and artifacts in
`FINDINGS.md`. Consensus/opinion trading is excluded.
