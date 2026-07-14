# Top-30 CAP=100k 8h book — audit scope

## Headline under audit

The code path in `research/studies/copy_cohort/book.py` reported, for the selected
top-30 CAP=100k cohort followed for 8 hours, q50/q75 net returns of +8.7/+23.1 bp
and daily Sharpes of 1.56/1.96. These numbers are provisional pending this audit.

## Required reading

- `AGENTS.md`, especially the over-null and over-carry gates
- `audit/AUDIT_PROTOCOL.md`
- `audit/00_GROUND_RULES.md`
- `research/studies/copy_cohort/FINDINGS.md`, especially the CAP=100k addendum
- `research/studies/copy_cohort/book.py`
- Every local module/data-builder whose fields or outputs `book.py` relies upon

## Audit boundaries

This is a read-only audit. Do not edit source, findings, or generated artifacts.
Do not load the parquet lake. Static code tracing and tiny synthetic/no-data probes
only, following `audit/AUDIT_PROTOCOL.md`.

The audit must trace the exact result-producing path, including:

1. Formation cutoff, selector construction, cohort ranking, and CAP=100k/top-30 semantics.
2. Forward entry eligibility, episode fields, liquidation handling, timestamps, and 8h prices.
3. Strict-prior q50/q75 sizing and whether any future episode outcome affects inclusion or size.
4. Dollar P&L, costs, turnover, aggregation, equity curve, concurrent capital, and Sharpe.
5. Random-cohort benchmark construction, exchangeability, multiplicity, uncertainty, MDE, and breadth.
6. Survivorship, missing-endpoint/censoring, active-day/calendar-day, dependence, and concentration biases.

Each finding must identify whether it changes the point estimate, only its Sharpe,
only inference, or only reporting. Tie every claim to `file:line`, demonstrate a
concrete failure path, and distinguish confirmed defects from unresolved risks.

