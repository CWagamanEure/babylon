# CONTRADICTIONS / STALE-LANGUAGE CHECKLIST

Verifies the documents agree after the simplification pass. Authoritative Gate-A set = `GATE_A_FROZEN_CONFIG`, `PREREGISTRATION_v2`, `SCORE_AND_OUTCOME_SPEC`, `EPISODE_SPEC`, `POSITIVE_CONTROL_SPEC`, `AUDIT_ONLY_PLAN`, `FUTURE_ACTIVITY_AND_ATTRITION`, `LEAKAGE_AUDIT_PLAN`.

## A. Key axes — do the authoritative docs agree? (scanned)
| Axis | Frozen value | Agreeing docs | Conflicts |
|---|---|---|---|
| Framing | locked retrospective, not confirmatory | GATE_A_CONFIG, PREREG A.0, ARCHITECTURE, EXPECTED_OUTPUTS, CHANGELOG | none |
| Verdict | `Δ_relative` monthly sign test ONLY | GATE_A_CONFIG, SPEC §10, PREREG A.10/A.11 | none |
| Absolute positivity | `A_selected` raw bp, reported separately | GATE_A_CONFIG, SPEC §9/10, PREREG A.0/A.11 | none |
| Corroboration | rank IC/decile/LOO = descriptive, cannot veto/rescue | GATE_A_CONFIG, SPEC §10, PREREG A.11 | none |
| k(F) | `min{k: P[Binom(F,½)≥k]≤0.05}`, algorithmic | GATE_A_CONFIG, SPEC §10, PREREG A.10 | none |
| Eligibility | 50 ep / 30 days / 3 months / J=20 (≥3/4) / 30-d live / ledger / no system flow | GATE_A_CONFIG, PREREG A.1, AUDIT_ONLY | none |
| Removed gates | concentration cap, effective-N, R_C≥0.05, min-month optimization | SPEC §7b, PREREG A.1/A.7, AUDIT_ONLY, CHANGELOG | none (grep: no live `R_C`/`effective-N` gate) |
| Horizons | train ≥3/4, **eval 4/4** | SPEC §5/§9, GATE_A_CONFIG | none |
| Bootstrap | weekly cluster (1 cluster = 1 ISO week, all days/coins/horizons joint); **<6 weeks ⇒ unscoreable, cannot be selected (no population-prior selection)** | SPEC §6, PREREG A.7, GATE_A_CONFIG | none |
| Eval-sufficiency | **≥10 selected & ≥50 field complete only** (decile density + completeness rate = descriptive, not gates) | GATE_A_CONFIG, SPEC §10, AUDIT_ONLY | none (grep: no `8 deciles`/`50% basket`) |
| Positive control | **pre-run gate** (FP≤0.05 & recovery≥0.80 before unseal); NOT in the real-data table | POSITIVE_CONTROL, GATE_A_CONFIG, SPEC §10, PREREG A.13 | none |
| Threshold status | "fixed before the run, unchangeable after outputs inspected"; audit only rules feasible/infeasible | GATE_A_CONFIG, AUDIT_ONLY, PREREG A.1 | none (grep: no live "a priori" / "resolved by") |
| Absolute object | `A_selected=mean Aband`, **+ raw 1/2/4/8 h reported separately** | SPEC §9/10, GATE_A_CONFIG, EXPECTED_OUTPUTS | none |
| Independence | binomial p exact only under independent signs; **lag-1 autocorr reported, does not alter verdict** | SPEC §10, GATE_A_CONFIG, PREREG A.10, EXPECTED_OUTPUTS | none |
| Entry price | first 5-min close strictly after fill; on-close→next | EPISODE_SPEC, SPEC §1, GATE_A_CONFIG | none |
| Purge | exactly `endpoint_price_ts < C` (no +5 min) | EPISODE_SPEC, SPEC §1, PREREG A.6, LEAKAGE | none (grep: no live `t0+h`) |
| Exclusion | no "bot" exclusion; slicer→aggregate | EPISODE_SPEC, PREREG A.1, CHANGELOG | none |
| Positive control | validate-only, nullized base, flat-per-horizon, train+eval | POSITIVE_CONTROL_SPEC, PREREG A.13, AUDIT_ONLY | none |
| Leakage tests | post-cutoff perturbation + physical-access | LEAKAGE, PREREG A.6, GATE_A_CONFIG | none |
| Median hold | descriptive/sensitivity only | PREREG A.1, GATE_A_CONFIG | none (grep: no live "median hold" in Gate-A set) |
| Latency/cost | Gate-B/C only, absent from Gate A | GATE_A_CONFIG, PREREG §A.4–5 note | none |

## B. Doc-by-doc status
| Doc | Status |
|---|---|
| GATE_A_FROZEN_CONFIG | **Authoritative** — current |
| PREREGISTRATION_v2 | **Authoritative** — current (A.0–A.14 reframed) |
| SCORE_AND_OUTCOME_SPEC | **Authoritative** — current |
| EPISODE_SPEC | **Authoritative** — current |
| POSITIVE_CONTROL_SPEC | **Authoritative** — current |
| AUDIT_ONLY_PLAN | **Authoritative** — current |
| FUTURE_ACTIVITY_AND_ATTRITION | **Authoritative** — current |
| LEAKAGE_AUDIT_PLAN | **Authoritative** — current |
| DEPLOYMENT_INPUT_FREEZE / PORTFOLIO_AND_COST_RULE / PUBLIC_BENCHMARK_SPEC | **Gate-B/C scope** — "copyability"/latency/cost here are correct for Gate B; do not apply to Gate A. Not yet swept for Gate-B wording, but they do not touch the Gate-A verdict. |
| ARCHITECTURE | **Overview** — reframed inference stance + a pointer that the specs are authoritative; the two-score diagram (information vs copyability) still maps to Gate A vs Gate B and is not contradictory. |
| CONFIG_FORKS / EXPECTED_OUTPUTS | **Governance** — EXPECTED_OUTPUTS Gate-A rows/F1/headline updated; CONFIG_FORKS still lists Gate-B-era forks (top-40-by-copyability, taker cutoff) as *sensitivities* — flagged below, not load-bearing for Gate A. |
| OPEN_DECISIONS / DESIGN_AUDIT_v1 / AUDIT_CHANGE_CONTROL | **Historical / audit trail** — provenance records of earlier rounds; intentionally not rewritten. |
| PREREGISTRATION (v1) | **Superseded** by PREREGISTRATION_v2 — kept for provenance; contains old copyability/top-40/two-band language by design. |

## C. Known residual wording to reconcile before build (non-blocking, Gate-B-scoped)
1. `CONFIG_FORKS.md` row 19 ("top 40 by copyability") and row 5 (taker cutoff) — reconcile the **Gate-A** selector to "top-10% by θ̂, min 20/max 50" and mark copyability forks Gate-B only.
2. `PORTFOLIO_AND_COST_RULE.md` / `PUBLIC_BENCHMARK_SPEC.md` — "copyability return" is correct for Gate B; add a one-line "Gate-B only" header so they are not misread as Gate-A.
3. `ARCHITECTURE.md` diagram lines 37/13/47 use "copyability score" for deployment — correct (=Gate B); optional cosmetic relabel.

None of C affects the Gate-A verdict, eligibility, score, or freeze. The eight authoritative Gate-A docs agree on every axis in table A.
