# Efron BOT500 code audit scope

Read the required audit protocol/ground rules and role manual, then
`research/studies/copy_cohort/EFRON_BOT500_ARCH.md`, `efron_bot500.py`, and
`tests/test_efron_bot500.py`. Static/read-only; no outcome reads or edits. Verify full parent lineage,
independent full-pool fills/day parity, pre-fit screened Efron semantics, fit finiteness, deterministic top30,
isolated cache invalidation/atomicity, common cutoff, capacity-before-support, inference/control/bounds,
pending/failure artifacts, and hard-false burned claims. Report verified severity findings or CLEAR.
