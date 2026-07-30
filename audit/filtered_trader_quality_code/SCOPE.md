# Filtered trader-quality implementation — pre-run audit scope

Read-only audit under `audit/AUDIT_PROTOCOL.md`; never load parquet or run the data jobs.

Targets:

- `research/studies/copy_cohort/filtered_quality.py`
- `research/studies/copy_cohort/filtered_quality_book.py`
- `tests/test_filtered_quality.py`
- contract: `research/studies/copy_cohort/FILTERED_TRADER_QUALITY_ARCH.md`

The run has not started. Audit cutoff/fee/cap/rank/filter correctness, exact AR(1) gaps, deterministic
rosters, block-collapse and priceability ordering, distinct-other consensus, arm/book parity, wallet/time
bootstrap multiplicity, and whether the report can support only burned-fold candidate ranking. Verify each
finding concretely with file:line; propose fixes but do not edit.
