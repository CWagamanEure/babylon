# capday_book architecture audit — scope

## What is under audit
The ARCHITECTURE ONLY (pre-build), for a clean causal copy-book verifying the user's spec:
top-30 capped-PnL-per-active-day cohort, forward opening-taker follow, dollar-sized, evaluated at
**8h / 24h / 48h / own-exit**. Target doc: `research/studies/copy_cohort/CAPDAY_BOOK_ARCH.md`.

This design supersedes the retracted `book.py` (audit: `audit/copy_cohort_top30_book/FINDINGS.md`, 3
CRITICALs) and ports the leakage-clean accounting of `arm_b_book.py` onto the capday selector.

## Required reading
- `CLAUDE.md` — the over-null AND over-carry gates (both load-bearing here)
- `audit/AUDIT_PROTOCOL.md`
- `research/studies/copy_cohort/CAPDAY_BOOK_ARCH.md` (the target)
- `research/studies/copy_cohort/arm_b_book.py` (the accounting being ported — already audited clean)
- `research/studies/copy_cohort/capday_cohort.py` (`_pool_scores`, `_window_days` — the selector)
- `research/data/markout.py` (the price lattice / markout basis the own-exit sidecar extends)
- `audit/copy_cohort_top30_book/FINDINGS.md` and `audit/copy_cohort_arm_b_book/FINDINGS.md` (prior defects)

## Boundaries
Read-only. No source/data edits. Static reasoning + tiny no-data synthetic probes only; do NOT read the
parquet lake. This is a DESIGN audit — judge whether the *specified* method is sound, not whether code
matches it (no code exists yet).

## Per-role focus
- **stats-rigor:** Is the own-exit estimand well-defined (variable per-episode horizon, exit-day bucketing,
  Sharpe annualization for mixed holds)? Does the two-way wallet×week CI remain valid under own-exit's
  variable exit weeks? Is the verdict taxonomy (§9) correctly symmetric (over-null vs over-carry)? Is the
  4×2 multiplicity handled honestly? Does own-exit reintroduce any selection-on-outcome (exit time is a
  wallet choice — is conditioning the follower's exit on the wallet's realized close_ts a lookahead for the
  FOLLOWER's own P&L? think carefully: the follower learns close_ts only AT close, so exit-at-close is
  causal, but the ENTRY set is fixed at open — confirm no future close info leaks into entry/sizing).
- **firewall-leakage:** Any future data reaching entry/selection? The own-exit sidecar reads `close_ts` — is
  it used only for the EXIT price, never to filter/size entries? Is the F2 liquidation guard truly ex-post?
  Does anything in `research/` here get imported by `src/babylon/` (must not)?
- **data-integrity:** Sidecar key `(wallet,coin,opener_block,opener_event_index)` — is it 1:1 with base
  rows (no fan-out on LEFT JOIN)? Staleness/NULL handling for `close_ts` beyond the lattice or >90s stale?
  Provenance stamping? Does widening base MK_COLS + schema bump risk stale-cache reads?
- **docs-consistency:** Does the arch doc's claimed reuse (`_weighted_twoway_ci`, `_expanding_clips`,
  `_pool_scores`, MCMC sampler) match those functions' actual signatures/behavior? Any capability claimed
  that the cited code doesn't provide (e.g. does the MCMC sampler's feature-balancing generalize to capday
  features as asserted)?

## Deliverable
Each role: findings ranked by blast radius (CRITICAL/HIGH/MED/LOW), each tied to a doc section or file:line,
with a concrete failure path. Distinguish confirmed design flaws from unresolved risks. Write to
`audit/copy_cohort_capday_book/FINDINGS.md` is done by the orchestrator; agents return findings as text.
