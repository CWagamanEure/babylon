# Nested-T filter code audit scope

Read `audit/AUDIT_PROTOCOL.md`, `audit/00_GROUND_RULES.md`, your assigned `agents/audit-*.md` manual,
`research/studies/copy_cohort/NESTED_T_FILTER_ARCH.md`, then audit these files in full:

- `research/studies/copy_cohort/nested_t_filter.py`
- `research/studies/copy_cohort/nested_t_book.py`
- `tests/test_nested_t_filter.py`
- `tests/test_nested_t_book.py`

Static/read-only: do not load Parquet and do not edit. The independent daily reference is the prior
`filtered_quality` legacy-x materialization; code must fail unless its saved source-manifest matches the
current manifest. Focus on exact daily/static/Q0 parity, time ordering/terminal prediction, pool leakage,
R/shock/bot semantics, top-k ties, capacity-before-outcome, common cutoff, missingness bounds, inference
dictionary contracts, injected control, concentration, Holm, artifact atomicity, and whether any path can
emit a positive/null verdict on burned folds.

Report only verified findings with severity, concrete failure path, file:line, and minimal fix sketch. A
clean audit is acceptable.
