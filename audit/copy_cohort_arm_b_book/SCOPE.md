# Audit scope — Arm B actual-book architecture (2026-07-13)

Read `audit/AUDIT_PROTOCOL.md` first. This is a STATIC, read-only architecture audit: do not load
Parquet and do not edit files.

Target: `research/studies/copy_cohort/ARM_B_BOOK_ARCH.md`, checked against the existing implementation
contracts in `selectors.py`, `walkforward.py`, `book.py`, `base.py`, `COPY_COHORT_ARCH.md`, and
`FINDINGS.md`.

Claim under audit: the design validly converts the existing Arm B wallet-equal 4h markout result into
a causal dollar-sized follower book with identical matched random-cohort books, honest dependence,
power, multiplicity, and concentration diagnostics.

Highest-value failure modes:

1. Any mismatch between the existing Arm B cohort/outcome and the proposed book population.
2. Sizing leakage, especially same-timestamp entries, future histories, or histories conditioned on
   eventual closure/markout availability.
3. A random-book construction that is not exchangeable with the real cohort, or that accidentally
   widens/narrows the null through membership overlap or inconsistent sizing-history coverage.
4. Dollar P&L/equity errors: PnL timestamp, cost basis, concurrency, turnover denominator, drawdown,
   Sharpe, or an implicit capital assumption.
5. Invalid weighted two-way CI/MDE or sign-test units; failure to price cross-wallet calendar shocks.
6. Over-conservatism that discards a real sized-book edge, and over-carry paths that let a concentrated,
   post-hoc q75/Sharpe result become a deployment claim.

Return findings to the coordinator only, using the protocol's file:line, concrete-failure-scenario
format. A clean bill is valid. Do not create a findings file; the coordinator will consolidate.
