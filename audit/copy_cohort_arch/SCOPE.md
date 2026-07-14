# AUDIT SCOPE — copy_cohort architecture doc (design-stage swarm, 2026-07-12)

The shared rules in `audit/AUDIT_PROTOCOL.md` apply in full (resource safety — never load the
parquet lake wholesale; verify-before-report, two-sided; blast-radius severity; audit-only, no
edits; F#-format findings).

## Target

`research/studies/copy_cohort/COPY_COHORT_ARCH.md` — a design document, no study code exists yet.
You are auditing the DESIGN and its FACTUAL CLAIMS about the repo, not an implementation.

The claim under audit: this design, if built as written, yields a valid, powered (MDE ≤ 5 bp),
multiplicity-controlled walk-forward test of whether a formation-selected wallet cohort has
positive OOS episode-level timing alpha on majors, with dependence handled by an empirically
calibrated clustering level (Stage 0) instead of coin-day collapsing.

## ⚠️ Why this is high-stakes

This arc has been burned in BOTH directions: the edge3 stale-candle artifact (a fake +24–31 bp
positive from look-ahead pricing) and the Stage-A blind instrument (MDE ≈ 160 bp "null" that was
actually no evidence at all). The design leans on prior machinery (episodes_markout lake, Tier-2
μ-baselines, wallet_flow placebo harness) — a wrong factual claim about what that machinery does
becomes a silent design hole.

## Highest-value concerns (each finding needs doc-section + a concrete failure scenario)

1. **Stage-0 → downstream leakage.** Burn-in months 202508–202510 are used to pick (unit, cluster
   level) and are ALSO inside every fold's formation window. Is "calibration, not effect selection"
   actually safe here, or can the unit choice smuggle in an effect-size look (e.g. picking the level
   that maximizes apparent t)? Is the frozen [0.03, 0.07] adoption rule gameable?
2. **Selection-vs-evaluation seam.** Formation membership by `close_ts ≤ cutoff`, forward outcome by
   `open_ts` in month T. Can an episode or its markout window contribute to both sides? What about
   episodes OPEN at the cutoff (close_kind OPEN_AT_END / carry-threaded) — do they leak formation
   information into the forward month, or get silently dropped by both sides?
3. **The placebo match.** Stratified matching on activity × notional quintiles — does matching on
   formation outcomes' correlates make the null too HARD (matching away the very skill signal) or
   still too easy (missing coin-mix / direction-bias correlates)? Is a stratified draw from a
   K=100-vs-pool-size feasible without empty strata?
4. **EB shrinkage arm.** Method-of-moments τ² on formation per fold, n_eff = frozen-cluster count:
   is the shrinkage target (pool mean) itself selection-contaminated? Does shrinking toward the
   pool mean bias the top-K ranking in a way random-cohort placebos don't share?
5. **Power gate realism.** Is an injected +5 bp edge through selection+evaluation on
   formation-internal splits actually a valid MDE for the FORWARD test (different month, different
   regime)? Can the gate pass while the forward test is still blind?
6. **Factual claims vs code** (docs-consistency, data-integrity lenses): every row of the doc's §9
   reuse table; the claimed episodes_markout construction (oracle ASOF, post-fill, ≤90 s staleness,
   horizon set incl. 5m); μ_h(coin, ISO-week) availability at that exact granularity; field names
   (crossed_open, opener_flagged, is_liquidation_close, hold_minutes, initial_notional_usd);
   `cv.walkforward_splits` / `as_of_cutoff_ms` semantics; `stats.py` function inventory; the
   VAULT_SQL predicate; whether markout_5m and markout_4h coexist per episode row (needed for the
   follower-lag estimand as written).
7. **Two-sided discipline.** Also flag OVER-CONSERVATISM: places where the design burns power for
   no calibration benefit (e.g. the "wider of two CIs" rule, the ≥3-forward-episode wallet floor,
   F1–F9 filter values) — a design that cannot pass its own §6 power gate is a defect too.

A clean bill on your lens is a valid result. Report format per protocol into your reply (no files).
