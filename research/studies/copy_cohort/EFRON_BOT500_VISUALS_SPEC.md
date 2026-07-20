# EFRON BOT500 visual diagnostic atlas

**Status:** frozen before generating or inspecting visualization-derived patterns, 2026-07-19. The
underlying Efron/BOT500 outcomes are already burned and reported. This atlas is descriptive diagnostics;
it cannot promote a selector, establish a new effect, or tune the 500-fill threshold.

## Purpose and immutable inputs

Render the standard majors Efron top-30 (`E30`) and its exact pre-fit `fills/day <= 500` variant
(`E_BOT500`) so distributional, dependence, concentration, selection, and missing-data problems are
visible. Consume only the successful lineage-locked artifacts:

- `data/derived/copy_cohort/efron_bot500/{book_report.json,rosters.json}`;
- its eight immutable `entries/entries_YYYYMM.{parquet,meta.json}` caches;
- the eight parent `nested_t_filter/panels/daily_YYYYMM.{parquet,meta.json}` formation panels.

The generator must validate success statuses, report/roster identity, all input file hashes including the
producer-bound entry-Parquet SHA/size, fold/arm sets, exact report book totals/funnels/missingness/primary
point/concentration, exact selector counts/overlaps and Efron ordered-input hashes, and current visualization
code/spec hashes before publication. Canonical paths are derived from the repo rather than trusted from
serialized absolute paths. It must be read-only with respect to study inputs and use an exact input
allowlist. Consensus/opinion data are excluded.

## Statistical contracts

- Reconstruct the exact globally chronological capacity books with the audited study functions. Capacity
  is allocated before outcome support; missing accepted rows remain visible and are never silently dropped.
- Clearly separate raw candidate-fill outcomes, capacity-accepted supported outcomes, and the registered
  arm contrast. Do not label raw frequency-weighted plots as the registered result.
- Every panel carries a compact schema in its subtitle or legend: row universe, support policy, gross/net
  field, entry/wallet weighting, and denominator. Capacity-accepted missing outcomes appear only as counts;
  they are never filled with zero. Layers compared in one panel use the same gross/net basis.
- Net book plots subtract 5.5bp once and use fixed $5,000 entries. Cumulative PnL is chronological realized
  8h markout PnL, not a simultaneous-capital equity curve; label it accordingly.
- Display the registered point, crossed wallet x paired-7d CI, MDE80, +5bp care effect/power, missingness
  bounds, fold/coin signs, and concentration beside descriptive plots.
- Distribution plots retain full tails or explicitly show clipping thresholds and overflow counts. QQ
  references are visual diagnostics, not Gaussian tests. Histograms use common bins where arms are compared.
  Log axes are labeled. A mandatory estimator ladder puts raw equal-entry gross, each arm's separately
  p95-winsorized wallet-fold-equal raw estimate and threshold, supported capacity net means, and the
  registered contrast side by side so weighting-driven sign reversals cannot be hidden.
- Full-cohort formation t-statistics reproduce the ordinary active-day t-stat on capped daily PnL,
  requiring `nd>=15` and positive sample SD. Z uses the frozen exact Student-t transform. Efron overlays
  use the frozen empirical-null parameters; no refit or threshold tuning is allowed in the renderer.
  Recomputed `(wallet,nd,t,z)` inputs must reproduce each saved ordered-input hash. Only stored top-30
  membership/rank displacement is plotted; full-pool `p_informed` ranks are unavailable and not recreated.
  T/z are labeled frozen selector coordinates, not calibrated skill probabilities. Lag-1 active-day PnL
  dependence is displayed and the atlas explicitly states that the empirical null addresses cross-sectional
  shape, not within-wallet iid/Gaussian calibration.
- Wallet-level return estimates always show sample size. Wallet contribution is the exact contribution to
  the arm mean/contrast, not raw wallet dollars. Fold and coin cells are descriptive dependent units.
- The contribution concentration curve is defined on nonnegative absolute wallet contrast contributions.
  Leave-k sensitivity ranks wallets once by their original absolute contrast contribution, removes the same
  wallets from both arms, and re-denominates each remaining arm mean; it is descriptive and post-hoc.
- Cumulative arm curves are supported net $5k markout PnL timestamped at `signal_ts+8h`, starting from zero;
  drawdown is from the running peak of that markout path and is never called an equity/capital drawdown.
  Show entry counts and a paired seven-day block contrast path beside the shared absolute arm paths. The
  latter uses fixed, non-overlapping seven-day calendar blocks anchored at 2025-11-01 and cumulatively sums
  each occupied block's `mean(E_BOT500 supported net bp) - mean(E30 supported net bp)` with equal block
  weight; it is a dependence diagnostic, not investable cumulative PnL.
- No p-value or visual crossing earns a null. Captions must retain burned/post-hoc, underpowered,
  missingness-unresolved, and non-deployable labels.

## Frozen atlas pages

1. **Executive overview:** dominant `MISSINGNESS_UNRESOLVED`/burned status banner; absolute book means;
   estimator ladder; same-scale observed/adverse/favorable point-and-CI forest with +5 line; MDE80, +5
   power, both injection failures, May rate-gate breach, concentration, and hard-false positive/null
   eligibility; monthly/coin performance; cumulative supported markout PnL and paired block contrast path.
2. **Returns and tail assumptions:** common-bin full and central distributions; empirical CDF/survival;
   normal QQ; and a concentration curve whose explicitly nonnegative mass is each supported entry's
   absolute net-bp magnitude, separately by arm. Include fold and coin boxplots. Show raw and
   capacity-supported layers under the per-panel schema rule; never construct a Lorenz curve on signed
   returns.
3. **Full formation cohort:** per-fold eligible/excluded counts; fills/day log distribution with the fixed
   500 line; t-stat distribution; t versus activity hexbin with roster overlays; active days and
   mean/volatility geometry; major-coin formation-notional mix.
4. **Efron model diagnostics:** z histograms with theoretical N(0,1) and frozen empirical-null overlays;
   empirical-null mu/sigma/pi0 through folds; tail survival versus null; selected-rank t/z/activity; roster
   overlap and stored top-30 rank/membership displacement. These reveal model assumptions but do not
   retrospectively alter them. Gaussian/iid calibration is explicitly disclaimed.
5. **Roster dynamics and cohort composition:** wallet x fold membership heatmap; persistence/churn; selected
   activity distribution; selected active days/t-stat; wallet-direction and coin mix. Highlight all five
   largest absolute contrast contributors mechanically and, separately, the already-registered November
   dominant wallet (`0xa1b6...4f04`) with its 116.75 fills/day and membership; no anecdotal selection.
6. **Execution capacity and missingness:** candidate/accepted/skip funnel by fold; acceptance rates; supported
   and missing accepted counts; fold/coin missingness heatmaps; time-of-day/day-of-week entry mix; arm
   capacity differences.
7. **Wallet dependence and sensitivity:** wallet mean versus entry count; exact wallet contrast
   contributions; cumulative absolute contribution concentration; leave-largest-contributors sensitivity;
   wallet outcome dispersion; roster frequency versus performance.

## Outputs

Write atomically under `data/derived/copy_cohort/efron_bot500/visuals/`:

- one immutable generation directory named from the complete input digest, containing seven high-resolution
  PNG pages;
- one multipage PDF atlas;
- `index.html`, a self-contained navigable rendered report with the PNG bytes embedded and concise
  interpretation/caveat text;
- `visual_manifest.json` binding every input, spec/code hash, output hash, exact reconciliation checks, and
  software versions.

Render the complete generation in a temporary directory, revalidate every input after rendering, watermark
every detached page/PDF page with the same generation digest plus burned/post-hoc, underpowered,
missingness-unresolved, non-deployable status, hash all outputs, atomically rename the generation directory,
then atomically update a small `latest.json` pointer. Never publish a mixed generation or stale page.

Run focused unit tests plus independent correctness, statistics, and data/leakage visual audits before and
after rendering. Record only genuinely new diagnostic observations in `FINDINGS.md`; do not rewrite the
registered performance conclusion from visual inspection.
