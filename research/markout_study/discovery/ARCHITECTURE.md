# ARCHITECTURE — wallet-discovery experiment (pre-implementation)

**Status:** design only. No code or data until the primary configuration is frozen and the design audit is cleared.

## Objective

Identify mid- to low-frequency wallets whose position-increasing entry episodes predict positive future returns over 1–48 h, and determine whether a diversified walk-forward basket of them remains profitable after latency and costs, and whether the wallet layer adds value over a frozen public market-state strategy.

## Three locked conceptual distinctions (foundations)

1. **Selection exploits cross-sectional heterogeneity, not the universe mean.** A near-zero aggregate markout is a weak prior. The discovery questions are whether the score ranks wallets by next-period return, whether a stable decile gradient exists, whether the selected basket beats the rest of the universe, and whether it clears costs. We already have direct evidence of stable heterogeneity to exploit (rolling adjacent-month rank IC ≈ +0.11, positive in 9 of 10 folds, sign test p = 0.02). The mean is not the estimand.
2. **Absolute profitability and make-or-buy are separate gates.** The mechanical reversal comparator is not free — it needs a trigger, execution, spread, fees, capital, limits, and exits. The comparator is a *frozen, implementable public market-state strategy under matched timestamps, universe, latency, costs, capital constraints, and horizons*. A basket can be profitable (Gate B) yet add nothing over the public signal (Gate C fails) — that is informative, and means the wallet layer is unnecessary, not that the basket loses money.
3. **Information ≠ copyability.** Two scores per wallet: an **information score** (gross post-entry markout from the observable first entry — does the action predict price?) and a **copyability score** (post-latency, cost-adjusted markout under a frozen simulated copy rule — can we monetize it?). Discovery/characterization uses the information score; deployment selection uses the copyability score.

## Pipeline (stage → deliverable)

| Stage | Purpose | Spec doc |
|---|---|---|
| 1 Broad universe | one primary universe + ≤2 sensitivities, as-of each cutoff | this doc §Universe, `CONFIG_FORKS.md` |
| 2 Episode construction | position-building episodes, first-entry primary | `EPISODE_SPEC.md`, `DATA_SCHEMA.md` |
| 3 Frozen horizon bands | mid {1,2,4,8}h, low {8,16,24,48}h; frozen aggregation | `PREREGISTRATION.md` §Bands |
| 4 Wallet-quality estimation | empirical-Bayes shrinkage; reliability = active days | `PREREGISTRATION.md` §Shrinkage |
| 5 Continuous monthly ranking | as-of refit; frozen selection rule; two scores | `PREREGISTRATION.md` §Selection |
| 6 Walk-forward basket eval | two sizings; calendar-time inference | `PORTFOLIO_AND_COST_RULE.md`, `EXPECTED_OUTPUTS.md` |
| 7 Co-primary gates A/B/C | ranking, absolute deployment, make-or-buy | `PREREGISTRATION.md` §Gates |
| 8 Kill rules | finite experiment; no fork-reopening on failure | `STOP_RULES.md` |
| 9 Exit optimization (deferred) | only if A+B clear; frozen fixed-horizon family | `PREREGISTRATION.md` §Exit (deferred) |

## Universe (Stage 1, summary — full forks in CONFIG_FORKS)

Primary coins: BTC, ETH, SOL, HYPE (validated candle pricing). At walk-forward cutoff C, using only fills with `ts < C`: ≥50 position-building episodes, ≥30 active days, ≥4 distinct active months, median episode hold ≥1 h (no upper cap), not flagged liquidation / TWAP-system / wash / bot / mechanical-slicer. **No taker-share cutoff.** Every eligibility variable is computed as-of C from training-only fills (this is the explicit fix for the v6 whole-window eligibility leak; see `LEAKAGE_AUDIT_PLAN.md`).

## Two-score, three-gate logic (Stages 5–7)

```
information score (gross)  ── discovery, decile gradient, archetypes
copyability score (net,    ── deployment selection → basket
  post-latency)                     │
                                    ├── Gate A  ranking validity (IC, gradient, sign)
                                    ├── Gate B  absolute deployment (net > 0, interval excl. 0)
                                    └── Gate C  make-or-buy vs frozen public benchmark
```
Gate B and Gate C are distinct and both pre-registered. See `PUBLIC_BENCHMARK_SPEC.md` for the Gate-C comparator.

## Inference stance

Calendar time (month) is the independent dimension and the **only** headline inference unit (no coin×fold pooling). The Gate-A **verdict is the monthly selected-minus-field (`Δ_relative`) sign test only**; rank IC, deciles, month-block bootstrap and leave-one-out are **descriptive corroboration that cannot change the verdict**. Absolute selected markout (`A_selected`, raw bp) is reported separately and never merges into the verdict. This tape is **locked retrospective evidence, not confirmatory** (extensively explored; confirmation needs backfill or prospective months). Latency/copyability belong only to Gate B; Gate A is pure gross markout. (This overview predates the detailed specs; `GATE_A_FROZEN_CONFIG.md` + `SCORE_AND_OUTCOME_SPEC.md` are authoritative where they differ.)

## Process gates around this experiment

Per project convention: architecture doc → **design audit swarm** (adversarial, read-only) → freeze primary config → build → code audit swarm → run → framing/steelman + prosecute-the-positive audit → findings ledger. Audit swarms are run at the design stage (now, on these documents) and after each subsequent stage; findings recorded before proceeding.
