# `markout_study/` — the Hyperliquid trader-markout / wallet-selection edge study

The research directory for one question: does prior trading performance identify traders whose *next*
trades are worth copying? It holds an exploratory analysis arc, a pre-registered clean-room redesign, and
the write-up. Use it as the study's archive and as the source of the frozen specs the `research/`
workbench builds against.

> **Firewall.** The frozen `gate_a/` pipeline runs on synthetic / nullized inputs and must **never**
> consume the real per-wallet tape from `research/`. Two lanes, one wall (see `docs/DATA_ARCHITECTURE.md §2`).

## The three bodies of work

| | What it is |
| --- | --- |
| **`src/`** | The **original exploratory study** — ~99 flat, stage-organized one-off scripts (Stages A–M). Backs the numbered reports. Superseded by the pre-registered redesign. |
| **`discovery/`** | The **pre-registered clean-room redesign** — frozen specs, leakage/power audits, stop rules, change-control. |
| **`gate_a/`** | The **frozen, tested implementation** of that pre-registration. "Gate-A" is the first gate of the frozen retrospective validation (Gate-B = wallet-vs-field, Gate-C = wallet-vs-public-benchmark). |

### `gate_a/` modules
- `common.py` — Gate-A v1.0 frozen constants + exact-decimal helpers (szDecimals, majors, DUST floor,
  30-min episode gap, horizons, seed hash). *Frozen values only — no new degrees of freedom.*
- `episodes.py` — Module 1: exact integer-tick per-(wallet,coin) fill ledger → qualifying signal
  episodes (position-increasing opens) with quarantine rules. No epsilon arithmetic.
- `tests/test_episodes.py` — unit tests for the episode-construction rules.

### `discovery/` key specs
- `PREREGISTRATION_v2.md` — current pre-registration (`PREREGISTRATION.md` is superseded).
- `GATE_A_FROZEN_CONFIG.md` — the frozen v1.0 config (nothing may change during audit).
- `RESTORE_PLAN_v1.md` — approved plan to restore v1.0 from the raw S3 fill archive; **the ingest oracle**
  that `research/data/ingest.py` / `validate.py` reference.
- `IMPLEMENTATION_ARCHITECTURE.md` — maps every frozen rule → code module + tests.
- `LEAKAGE_AUDIT_PLAN.md` — checklist that must pass before any result is reported.
- `POSITIVE_CONTROL_SPEC.md` — controls validating the pipeline's power / false-positive behavior.
- `STOP_RULES.md` — stopping conditions (no fork-looping).
- Plus: `EPISODE_SPEC`, `DATA_SCHEMA`, `SCORE_AND_OUTCOME_SPEC`, `PORTFOLIO_AND_COST_RULE`,
  `PUBLIC_BENCHMARK_SPEC`, `CONFIG_FORKS`, `AUDIT_CHANGE_CONTROL`, `CONTRADICTIONS_CHECKLIST`,
  `FUTURE_ACTIVITY_AND_ATTRITION`, `OPEN_DECISIONS`, `DESIGN_AUDIT_v1`, `DATA_CONTRACT_AUDIT`,
  `EXPECTED_OUTPUTS`, `CHANGELOG_GATE_A_SIMPLIFICATION`, `ARCHITECTURE`, `AUDIT_ONLY_PLAN`,
  `DEPLOYMENT_INPUT_FREEZE`. (Some marked superseded — check each file's header.)

## Directory layout

```
markout_study/
  gate_a/            # frozen, tested Gate-A pipeline (the clean-room re-do)
  discovery/         # pre-registration + frozen specs + audit-design docs
  src/               # 99 flat exploratory one-off scripts (the original study, Stages A–M)
  docs/              # engineering docs, per-version changelogs, FINDINGS_LEDGER.md, report_src/
  out/              # computed artifacts: cohort/stat *.parquet, *.npz, v{4,5,6}.json report bundles
  notebooks/        # findings + report-asset notebooks
  figs/ … figs_v6/   # rendered report figures, one dir per report version (figs=v1, figs_v6=current)
  scratch_analysis/  # ad-hoc scratch experiments
  scripts/           # wallet_forensics.py utility
  report{,_v2..v6}.{md,html,pdf}   # the manuscript, v1→v6 (v6 current)
  technical_appendix.{md,pdf}
  audit/             # (empty placeholder)
```

### `src/` script families (no subdirs — read by prefix)
`cohort_K_*/cohort_M*/cohort_P*` staged cohort tests · `prosecute_*` adversarial attacks ·
`persistence_*` · `consensus_*` · `eda_*` · `fig_*`/`*_figs` figure generators ·
`verify_v*` report checkers · `make_*` notebook builders · `mkcommon.py` shared helpers.

## Reports & the ledger
- **`report_v6.md`** is current (paired `.html`/`.pdf`, figures in `figs_v6/`, numbers in `out/v6.json`).
  v1→v6 is one hardening chain of the same manuscript (`docs/CHANGELOG_v2..v6.md` log the diffs).
- **`docs/FINDINGS_LEDGER.md`** is the accumulating record (Stages A–M plus registered nulls / dead-ends)
  tying `src/` outputs in `out/` to the reports. Per `../CLAUDE.md` it is updated at the end of each stage.

Conclusions live in the reports and the ledger, not here.

## Relationship to `research/`
The `research/` workbench (real per-wallet tape, `episodes_build.py`, the planned wallet-features tables)
is the powered, leakage-safe successor to this study's exploratory `src/` work, and consumes the frozen
specs in `discovery/` (notably `RESTORE_PLAN_v1.md`). It is firewalled from `gate_a/`.
