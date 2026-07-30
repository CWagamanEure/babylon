# Nested-T filter architecture audit scope

Read `audit/AUDIT_PROTOCOL.md`, `audit/00_GROUND_RULES.md`, the assigned role manual under `agents/`, and
`research/studies/copy_cohort/NESTED_T_FILTER_ARCH.md` in full. This is a static, pre-build audit. Do not
load parquet or edit files.

The load-bearing question is whether the architecture truly nests the published majors capped-daily-PnL
t-stat selector and exact historical Book-B mechanics before introducing Q, adaptive R, Efron, blow-up, or
the 500-fills/day screen. Look especially for a parity limit that is only asserted rather than mathematical,
temporal leakage in R inputs or empirical-Bayes fitting, mismatched universes/df, non-comparable accepted
entry books, underpowered-null language, and uncontrolled adaptive multiplicity.

Return findings to the coordinator with severity, concrete failure path, file/line evidence, and minimal fix
sketch. A clean result is acceptable.
