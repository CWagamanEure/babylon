# Adversarial Quant Audit — INDEX & SAFE LAUNCH PLAN

20 independent auditors over the Babylon copy-trade / followable-edge system. Each agent reads
`audit/00_GROUND_RULES.md` first, then its own `audit/tasks/NN_*.md`, and writes
`audit/findings/NN_*.md`. **Read the ground rules for the RAM rules — they are why this is
split into static and dynamic agents.**

## The roster

| NN | Area | Mode | Primary files |
|----|------|------|---------------|
| 01 | Universe construction & survivorship | STATIC | `other_repo_notes/README.txt`, `scripts/convergence_his.py`, `follow/selection.py` |
| 02 | Look-ahead & seam leakage in pricing | STATIC | `follow/followable.py`, `follow/skill.py` |
| 03 | Follower-lag pricing model | STATIC | `follow/followable.py`, `follow/scheduler.py`, `capture/markout.py` |
| 04 | Market-neutralization & beta | STATIC | `follow/skill.py` (basket), `follow/followable.py` |
| 05 | Eligibility & selection gating | STATIC | `follow/selection.py`, `follow/scheduler.py`, `follow/weights.py` |
| 06 | Sortino / ranking math & stability | STATIC | `follow/scheduler.py` (`_sortino`), `capture/scorer.py` |
| 07 | Bootstrap / confidence intervals | DYNAMIC | `scripts/edge_sweep.py` (`_boot_ci`), `scripts/convergence_test.py` |
| 08 | Coverage / priceability bias | STATIC | `follow/followable.py`, `follow/candles_source.py` |
| 09 | Disposition / MTM-at-cutoff / dangling | STATIC | `capture/stepper.py`, `capture/scorer.py`, `follow/skill.py` |
| 10 | Cost & netting model | STATIC | `scripts/edge_sweep.py`, `sizing/`, `execution/` |
| 11 | startPosition seeding & reconstruction | DYNAMIC | `follow/skill.py`, `capture/stepper.py`, `follow/fills_source.py` |
| 12 | Capture stepper (live≡batch parity) | DYNAMIC | `capture/stepper.py` + `tests/test_capture_stepper.py` |
| 13 | Capture markout scheduler | STATIC | `capture/markout.py` + test |
| 14 | Capture ingest / dedup / cursor | STATIC | `capture/ingest.py` + test |
| 15 | Capture store / SQLite / retention / restart | DYNAMIC | `capture/store.py` + test |
| 16 | Capture scorer & re-derivability | STATIC | `capture/scorer.py` + test, `docs/LIVE_CAPTURE.md` |
| 17 | Reflexivity / reference price | STATIC | `capture/markout.py`, BookCache, `docs/LIVE_CAPTURE.md` |
| 18 | GO/NO-GO gate & pre-registration integrity | STATIC | `stats/gate.py`, `follow/measure.py`, `follow/experiment.py`, `follow/oos.py`, `follow/walkforward.py` |
| 19 | Live execution / paper-fill parity | STATIC | `execution/paper.py`, `execution/fill_model.py`, `follow/live.py`, `tests/test_paper_parity.py` |
| 20 | Engineering: RAM/OOM & polars correctness | DYNAMIC | `follow/fills_source.py`, `scripts/split_his_fills.py`, `scripts/edge_sweep.py` |

15 STATIC, 5 DYNAMIC (07, 11, 12, 15, 20).

## Safe launch sequence (prevents the OOM crash)

Launch in waves. STATIC agents touch no data and can fan out wide; DYNAMIC agents are
serialized so at most 1–2 Python processes ever hold parquet/SQLite data at once.

- **Wave A — all 15 STATIC agents, in parallel.** They only read source and reason. Host RAM
  cost is ~zero regardless of count. (01,02,03,04,05,06,08,09,10,13,14,16,17,18,19)
- **Wave B — DYNAMIC agents, max 2 at a time**, in this order: 12 → 11 → 20 → 07 → 15.
  Each uses only single-wallet files / streaming / its own test file. Wait for a pair to finish
  before launching the next.

If launching by hand via the Agent tool, send Wave A as one batch (multiple tool calls in one
message). For Wave B, send no more than two Agent calls per message and wait for both to
return before the next two.

> A `Workflow` script (`audit/run_audit.workflow.js`, optional) can enforce this: STATIC in a
> `parallel()` barrier, DYNAMIC in a `pipeline()` with a concurrency of 2. Only use it if you
> explicitly opt into orchestration — otherwise hand-launch in the two waves above.

## After all agents report

A synthesis pass (you, the coordinator) reads every `audit/findings/NN_*.md`, dedups, ranks by
blast radius (gate-false-GO first), and writes `audit/SUMMARY.md`. Cross-check any CRITICAL/HIGH
finding against a second agent before believing it — a wrong "we found a fatal bug" is as costly
here as the bugs themselves.
