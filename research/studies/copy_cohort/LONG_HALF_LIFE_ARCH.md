# LONG HALF-LIFE T-QUALITY — frozen 60-day diagnostic

**Stamped before computing any 60-day roster or outcome: 2026-07-18.** The eight evaluation folds
202511–202606 are already burned. This experiment may reject or retain a candidate for a future sealed
epoch, but it is not new forward evidence.

## Question and single primary choice

Does a **60-calendar-day half-life** improve on the static t-stat selector in these burned folds? There is no
half-life grid. Sixty days was chosen after observing the adverse 21-day result, so this is an adaptive
candidate-ranking diagnostic; it cannot identify *why* 21 days failed and is not multiplicity-independent of
the prior KF/21-day arc.

Primary estimand:

`EW60_T30 net bp per accepted entry − TSTAT_COMMON30 net bp per accepted entry`.

Care-about improvement is +5bp/entry. The primary arm must beat the identical common-pool static t-stat; an
absolute positive EW60 book is insufficient. The direction, crossed 95% CI, MDE80, power at +5bp, eight fold
deltas, and four coin deltas are mandatory.

## What changes and what does not

Only exponential calendar weights change from the completed dynamic-t experiment: half-life 21 → 60 days.
The formation window remains the prior three complete months. Daily observations remain total-fee-net
majors realized PnL scaled down, never up, to a $100k daily turnover budget. The score remains weighted mean
divided by its wallet-specific weighted standard error with Kish effective N; it is not a cross-sectional
rank z-score and makes no Gaussian-return claim.

Eligibility, common-pool construction, active-day and recency requirements, exact top-30 size, deterministic
tie-breaking, HAC construction, formation-only shock reset/quarantine, and copyability/HFT gates remain
byte-for-byte the audited dynamic-t definitions. The static comparator is recomputed from the same common
EW60-rankable pool at each cutoff.

Execution also remains unchanged: collapsed flat-opening majors signals ≥$250; strictly post-signal first
midpoint; $2,500 equal clips; one live wallet×coin; $10k/wallet and $50k/coin caps; 8h; 5.5bp. Unsupported
accepted trades retain capacity. The exact registered May-30 partial-context exception and June cutoff are
unchanged.

## Secondary and multiplicity rules

The four already-defined same-family secondaries are retained without additions: EW-HAC minus static HAC,
shock-reset EW minus EW, copyable EW minus copyable static, and the frozen distinct-other six-hour
smart-consensus EW subset minus its static counterpart. Holm correction is applied to the positive family and
separately to the +5bp method-null family. Consensus is an entry overlay, never part of the selector.

No 42-day, 90-day, blended-score, coin-specific, ex-HYPE, alternative-K, or alternative-horizon result may be
promoted from these folds. Those may be described only after a separately frozen design.

## Inference and verdict gate

Reuse the registered 10,000-draw crossed global-wallet × paired-seven-calendar-day product bootstrap. One-way
wallet/time intervals are diagnostics. Missingness rates and ±2,000bp endpoints remain inside the crossed
bootstrap. The result is `MISSINGNESS_UNRESOLVED` if the overall/fold/imbalance gates fail or favorable and
adverse endpoints do not agree.

Because EW60 was selected after seeing related results on these folds, **neither a formal historical positive
nor a method-scoped null may be earned here**, regardless of the within-run p-value. The result is always a
burned candidate-ranking diagnostic. Its descriptive classification still requires the multiplicity-aware
crossed CI and construction/missingness sensitivity: CI above zero supports a historical positive direction;
to claim the observed effect exceeded the +5bp care threshold, the CI lower bound must exceed +5bp. MDE≤5bp
and ≥80% +5bp positive-control power are reported as the absence/null-resolution diagnostics, not imposed on
an observed positive. If those fail, any absence wording is inconclusive/underpowered. No conclusion may
generalize beyond the burned 202511–202606 folds.

Before the ledger verdict, run independent correctness, steelman-the-positive, and prosecute-the-positive
passes. Preserve the original 21-day artifacts; 60-day outputs live under
`data/derived/copy_cohort/dynamic_t_quality_hl60/`. Implementation must use a frozen `hl60` profile, pass
60 days explicitly through EW, weighted HAC, shock, copyability, and common eligibility, include the profile
and half-life in every cache/report identity, and make the book reject any mismatched roster. The original
21-day directory is immutable for this run.
