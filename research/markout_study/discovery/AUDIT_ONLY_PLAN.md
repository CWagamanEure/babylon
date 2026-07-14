# AUDIT_ONLY_PLAN — counts-only feasibility check (simplified, change 9)

Purpose: confirm the **frozen** Gate-A thresholds are workable on this tape, using **counts, coverage, and correctness only** — never wallet returns, rankings, or outcomes. This is a feasibility check, **not** a threshold-optimizing tournament. Every threshold is **fixed before the locked retrospective run** (below); the audit may only rule each **feasible-as-written** or **infeasible on this dataset** — it may **not** replace a value after seeing counts. Any threshold change requires a **newly versioned design and restarts the freeze**. The audit also reports the two data-availability facts (first feasible fold, candidate-fold count).

## Hard firewall
- No wallet markout ranking, θ̂-vs-Yband relationship, selected-vs-field return, per-wallet realized return, decile-outcome table, or Gate-B/C output.
- Markout values are used **only** to (a) compute the standardization scale σ̂ and (b) run the positive control on the **nullized/injected** base (POSITIVE_CONTROL_SPEC) — never aggregated to a per-wallet ranking or displayed.
- Human inspection is limited to the counts table below.

## Frozen thresholds (fixed before the run — the audit does NOT tune these, only rules feasible/infeasible)
| Threshold | Fixed value | Rationale |
|---|---|---|
| Min deduplicated episodes | 50 | reliability |
| Min active wallet-days | 30 | reliability |
| Min active calendar months | 3 | reliability (expanding window) |
| Per-horizon coverage J | 20 wallet-days, at ≥3 of 4 horizons | data availability |
| Cross-section minimum N_min | 100 wallets | estimator stability |
| Min active weeks (bootstrap) | 6 | dependence-aware reliability |
| Liveness | active in last 30 days | operational |
| Eval-sufficient fold | ≥10 complete-outcome selected AND ≥50 complete-outcome field | estimator stability (decile density / completeness rate are descriptive only) |

## What the audit resolves (data availability only)
1. **First feasible fold** = earliest cutoff meeting every fixed threshold above (mechanical; never moved earlier by hand).
2. **Number of candidate folds** on the 11-month tape.
3. **Eligible wallet counts** per candidate fold (must clear N_min).
4. **Simple J feasibility** — does J=20 at ≥3/4 horizons leave a workable cross-section? (report; if it collapses the universe, report that — do not re-optimize J on returns).
5. **Outcome completeness** — 4-of-4 next-month completeness rates.
6. **Ledger correctness** — startpos reconstruction, quarantine list.
7. **Exclusion-label precision** — ≥0.90 precision vs the labelled set; if unreachable, the flag family is **disabled / sent to manual review**, not run at lower precision.
8. **Weekly-bootstrap feasibility** — active-week distribution vs the 6-week minimum.

## Required output: counts table (rule · rationale · retained — NO performance)
| Item | Value | Retained wallets / folds |
|---|---|---|
| First feasible fold | ⬜ | — |
| Candidate folds | ⬜ | — |
| Eligible wallets / fold | ⬜ | ⬜ |
| J=20 feasibility | ⬜ | ⬜ |
| N_min=100 clearance / fold | ⬜ | ⬜ |
| 4-of-4 completeness rate | ⬜ | ⬜ |
| Ledger quarantine count | ⬜ | ⬜ |
| Exclusion-label precision | ⬜ | ⬜ |
| ≥6-week bootstrap feasibility | ⬜ | ⬜ |

If the fixed thresholds do not leave a workable design (e.g. <N_min wallets, or too few folds for any k(F)), the honest outcome is **INCONCLUSIVE / INFEASIBLE** — not a relaxation of thresholds. Latency/cost stay unresolved (Gate-B/C only), frozen separately in `DEPLOYMENT_INPUT_FREEZE.md`.
