# Dynamic-t quality architecture audit scope — 2026-07-18

Read first: `AGENTS.md`, `audit/AUDIT_PROTOCOL.md`, and your matching `agents/audit-*.md` role manual.

Target: `research/studies/copy_cohort/DYNAMIC_T_QUALITY_ARCH.md`.

Context: this is an explicitly post-hoc burned-fold diagnostic correcting the prior rank-z/KF estimand. Audit
whether the new design actually isolates recency weighting, preserves the t-stat's magnitude/uncertainty,
handles HFT/copyability and blowups without lookahead, maintains identical execution, and can support its
stated inference/governance. Check the MDE formula, common-universe requirements, activity versus outcome
eligibility, consensus ordering, wallet cap, and whether any secondary is accidentally promoted to primary.

No edits and no parquet reads. Return verified findings with file:line, blast radius, and fix sketch.
