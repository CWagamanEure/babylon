# Audit findings — Arm B actual-book architecture (2026-07-13)

Three independent static agents (correctness, stats-rigor, firewall-leakage/data-integrity) audited
`ARM_B_BOOK_ARCH.md` against the existing selector, walk-forward, episode-builder, and Arm C book.
No agent loaded Parquet or edited source. **All findings below are accepted into architecture v1.1
before implementation.**

## Critical / high

1. **Future liquidation-outcome filter (CRITICAL, result fabrication).** The proposed forward rule
   inherited `NOT is_liquidation_close`, but that field is set from the eventual closing fill. A real
   follower cannot know it at entry; excluding liquidation-ending episodes can delete future losses.
   Fix: forward membership uses opener-time-known fields only. Liquidation close is ex-post diagnostic.
2. **Longitudinal placebo mismatch (CRITICAL, result fabrication).** Concatenating independently drawn
   monthly placebos does not reproduce persistent real top-100 membership and can narrow the total-book
   null under persistent wallet shocks. Fix: construct sequential placebo paths matching the real
   adjacent-fold retention count plus each fold's composition; report tenure/overlap diagnostics.
3. **Sizing-history outcome leakage (HIGH).** "Clean history" could inherit future close, liquidation,
   or markout-availability predicates. Fix: enumerate at-entry-known history predicates and explicitly
   forbid all eventual-outcome fields.
4. **Registered-vs-implemented Arm B F0 mismatch (HIGH).** The Arm B SQL omitted the registered
   `NOT entry_after_close` and `entry_lag_s <= 90` formation filters. Fix: corrected F0 cohort is a new
   v2 config; legacy as-implemented membership is reproduction-only and cannot be silently conflated.
5. **Wrong/underspecified weighted inference target (HIGH).** Existing `twoway_cluster_ci` is an
   unweighted mean and subtracts iid rather than wallet×week intersection variance. The absolute return
   CI also cannot adjudicate selector enrichment versus matched random. Fix: freeze a ratio-estimator
   influence score with wallet + week − wallet×week variance; separately report the matched-return
   contrast/randomization band and its MDE/positive control.
6. **Daily Sharpe sampling clock (HIGH).** Active-day-only Sharpe compares different clocks and inflates
   sparse books. Fix: common full UTC calendar including zero-P&L days, `ddof=1`, sqrt(365).

## Medium / interpretation

7. **Net dollars confound capital scale.** Keep net$ as economic output, but primary matched inference is
   dollar-weighted net bp; also compare turnover and peak capital. Net$ p-value is descriptive.
8. **Wallet sign independence.** Shared weeks invalidate a bare exact-binomial interpretation. Collapse
   to one aggregate per distinct wallet and label it breadth-only; use the retention-matched randomization
   distribution for formal enrichment.
9. **Repo-wide post-hoc selection.** All p-values on reused months remain exploratory; q50 is only the
   frozen operating point within this follow-up, not a fresh confirmatory test. New data are required to
   establish the effect.
10. **Exit-only curve is not MTM.** Relabel as closed-trade cumulative P&L/drawdown; aggregate simultaneous
    exits and seed from zero. Intrahorizon drawdown is unavailable from endpoint-only marks.
11. **Endpoint availability is future information.** Entry membership cannot require non-null 4h markout.
    Fix: count and size all causal attempted entries; treat missing endpoints as censored outcomes, report
    real/random coverage, and scope return inference to the evaluable subset.
12. **Adjacent retention is insufficient.** Matching only consecutive overlap can rotate the retained core
    and understate persistent-wallet variance. Fix: permute whole real membership trajectories onto eligible
    candidate wallets, preserving the exact tenure histogram and full pairwise overlap matrix.
13. **Trajectory assignment must be exchangeable.** Greedy minimum-cost assignments privilege the observed
    identity and do not justify a rank p-value. Fix: sample the identity-containing feasible assignment set
    with a symmetric constrained-swap chain under a frozen, identity-blind per-fold feature-balance rule;
    require acceptance, uniqueness, multi-chain, and effective-B diagnostics or demote ranks to descriptive.
14. **Unique MCMC states are not independent randomizations.** Ordinary thinned MCMC lacks a finite-sample
    rank-p guarantee without an exact reversible-chain randomization construction. Fix: report return/tail
    autocorrelation ESS, but label all ranks and random bands descriptive regardless; new data adjudicate.
15. **Post-cutoff liquidation leaked into the formation pool.** `_arm_a_sql` and the F7 share used the
    finalized `is_liquidation_close` flag for every pre-cutoff open, including closes after cutoff. Fix:
    liquidation is an exclusion only when `close_ts < cutoff`; forward entry never uses it.
16. **Final hold duration leaked past the cutoff.** F4 read `hold_minutes` finalized at a future close for
    episodes whose 4h formation mark was pre-cutoff. Fix: compute duration as-of cutoff with
    `min(close_ts, cutoff) - open_ts`, censoring still-open positions at the information boundary.
17. **Build-audit diagnostic gaps.** All chains started at identity; Gaussian MDE ignored null skew;
    fold/breadth comparisons were missing; wallet concentration mixed trade-positive and wallet-net
    units. Fixes: independently warmed/dispersed starts with distance gate, empirical q95−q20 MDE,
    fold plus matched wallet/week breadth ranks, and positive-trade PnL aggregated consistently by wallet.
18. **Labeled trajectory slots fabricated sampler uniqueness.** Swapping wallets between identical binary
    trajectory slots changes the assignment tuple but not any fold's book. Fix: canonicalize to sorted
    per-fold membership sets for uniqueness and start-distance gates; require nonzero return variance.

Accepted design also retains the auditors' clean findings: q50 primary/q75 sensitivity hierarchy,
`+1/(B+1)` empirical p correction, explicit post-hoc label, concentration/leave-one-out diagnostics,
and the symmetric over-null/over-carry verdict gate.
