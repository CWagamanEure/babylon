# Dynamic-t quality code audit scope — 2026-07-18

Read `AGENTS.md`, `audit/AUDIT_PROTOCOL.md`, your matching role manual, and
`research/studies/copy_cohort/DYNAMIC_T_QUALITY_ARCH.md` first.

Targets:

- `research/studies/copy_cohort/dynamic_t_quality.py`
- `research/studies/copy_cohort/dynamic_t_book.py`
- `tests/test_dynamic_t_quality.py`

This is pre-run. No parquet reads and no edits. Verify architecture parity, especially common selector pools,
weighted/HAC math, exact money, shock reset and causal online quarantine, activity denominators, strict-forward
entry/exit pricing, common context cutoff, deterministic wallet/coin caps, consensus pool/order, crossed
wallet×time resampling, MDE/+5 control, Holm, cache/provenance binding, and fail-closed exact top-30 behavior.
Return protocol-form findings with concrete failure paths and file:line.
