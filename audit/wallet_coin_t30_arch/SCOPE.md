# Wallet×coin T30 architecture audit scope

Read `audit/AUDIT_PROTOCOL.md`, `audit/00_GROUND_RULES.md`, the assigned role manual under `agents/`, and
`research/studies/copy_cohort/WALLET_COIN_T30_ARCH.md` in full. This is a static, pre-build audit. Do not
load parquet or edit files.

The load-bearing question is whether the design changes only pooled-wallet formation ranking into a
wallet×coin top-30 pair ranking while preserving the audited majors book, and whether it can report the
requested mean/median bp per trade and positive months honestly. Check especially: pair-day versus
wallet-day cap semantics, global top-30 pair multiplicity, filtering entries by exact pair, parity to the
pooled T30/E30 controls, capacity ordering, temporal formation/evaluation boundaries, Efron pool/df,
clustering unit, missing outcomes, adaptive/burned governance, and over-null/over-carry gates.

Return findings to the coordinator with severity, concrete failure path, file/line evidence, and minimal
fix sketch. A clean result is acceptable.
