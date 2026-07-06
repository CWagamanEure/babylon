# PRE-REGISTRATION v2 — revised, post-audit (supersedes PREREGISTRATION.md)

Incorporates the 5-agent design audit (`DESIGN_AUDIT_v1.md`, classified in `AUDIT_CHANGE_CONTROL.md`) and the user's 13 rulings. **Not yet frozen** — items marked **[MEASURE]** need instrumentation/business input before freeze; **[PENDING AUDIT]** are set by the training-only power/accounting audit (justified by reliability/capacity/ops, never by returns — ruling #8). Two phases; **they are never pooled into one headline** (ruling #1).

---

# PHASE A — confirmatory mid-frequency experiment (11-month tape, now)

## A.0 What is confirmatory vs reported

- **Confirmatory (the Phase-A claim):** can a training-only, shrunk **gross entry-quality** score sort wallets by next-month mid-frequency **signed gross markout**, and does the selected basket outperform the precisely-defined non-selected field — under **calendar-month fold-level** inference? Gross markout is the primary discovery target because beta timing, reversal exposure, momentum timing and coin selection are economically admissible sources of wallet value. The selected-minus-field contrast removes *some* common movement but is **not** assumed to eliminate systematic exposure (selected and field wallets can differ in coin mix, direction, regime, activity). Residualization is unnecessary because of the **business estimand**, not because systematic exposure is guaranteed to cancel; any systematic component is admissible and then decomposed diagnostically.
- **Diagnostic (secondary, never selection-determining):** market-state-/benchmark-adjusted return, asking whether wallet identity adds information *beyond observable state*. Computed for characterization and Gate C only; it does not set primary eligibility or selection.
- **Sealed until the deployment-input freeze:** the directional deployment book P&L (Gate B) and make-or-buy (Gate C). Their **code is built parametrically now but their outcomes are not inspected or reported** until latency and cost inputs are frozen (see §Execution order + `DEPLOYMENT_INPUT_FREEZE.md`). Provisional 60 s and {8,8,10,14} remain labelled scenarios only.

## A.1 Universe (frozen — return-independent eligibility only)
BTC, ETH, SOL, HYPE (ruling #2). At each monthly cutoff C, from fills with `ts < C` **and horizon-purged** (A.6), eligibility uses **only return-independent evidence**: ≥50 independent episodes, ≥30 active days, ≥4 active months **[AUDIT-ONLY]**, ≥ J eligible wallet-days at ≥3 of 4 horizons (scoreable — SPEC §5, **[AUDIT-ONLY]**), episode-count concentration across days/months below **[AUDIT-ONLY]**, liveness (active in last 30 d). **No return- or edge-based quantity enters eligibility or selection** (item 9).

**Median-hold removed from primary eligibility (item 10):** the estimand is fixed-horizon entry quality, not exit replication, and a realized-hold filter needs future closing information and censoring rules. Holding behavior is reported descriptively *after* selection. The ≥1 h median-hold filter is retained only as a pre-registered **sensitivity**, and if ever used must count only episodes fully closed before C (no artificial hold for censored episodes), with a minimum completed-episode count.

Exclusion flags (liquidation/TWAP/wash/bot) validated with a labelled positive-control set (D5). **Maker-heavy wallets included only after passing the hard ledger-correctness gate (A.2b); otherwise excluded, not flagged (ruling #3).**

## A.2 Episode construction (frozen — EPISODE_SPEC + audit fixes)
30-min gap; first-entry primary. Fixes now primary: **startpos reconstructed from full pre-C history; quarantine any wallet whose reconstructed position is left-censored (D1); `hold_est_h` = flat→flat lifetime, decoupled from termination (D2); fragments deduped to non-overlapping forward windows for the ≥50 count and every per-episode statistic (D3); min-reduction dust floor + explicit `q≠0`/no-open-episode handling (D4).**

### A.2b Ledger-correctness gate (hard, ruling #3)
Stratified manual + automated audit concentrated on low-taker-share wallets, testing: position reconstruction, open-vs-close classification, maker/taker interaction, direction flips, partial reductions, phantom round trips, and reconciliation against known position paths. Fail ⇒ excluded from the primary until corrected.

## A.3 Estimand & horizons (frozen)
- **Band:** mid {1, 2, 4, 8} h only (single confirmatory band).
- **Primary information score** (Gate A): the shrunk θ̂ of `SCORE_AND_OUTCOME_SPEC.md` §1–8 — equal-weighted band mean of the four horizons' **gross signed markout**, each standardized by its training-window cross-sectional (across-wallet, coin-pooled, winsorized) SD, then normal–normal EB-shrunk. **Gross** — no benchmark subtraction in the primary target. The **single realized Gate-A outcome** Yband is frozen in SPEC §9. Dimensionless; used only to rank.
- **Secondary diagnostic score:** the same construction on market-state-/benchmark-adjusted return, reported for characterization and Gate C only. Never determines eligibility or selection.
- **Deployable-book return** (Gates B/C, sealed): one representative exit horizon = **4 h**, in raw bp, cost-subtracted. 4 h is chosen as the **central practical holding period of the frozen band, independent of observed returns** — it is *not* claimed historically optimal, and exit optimization is prohibited until the entry system clears Gates A and B. The markout curve is reported at all four horizons; the 4 h rule governs only the initial bounded-book test. (Ranking score ≠ return metric — A2.)

## A.4 Latency **[MEASURE]** (ruling #5)
Instrument source-event, ingestion, signal-generation, order-submission, expected-fill timestamps; set primary latency to a measured conservative percentile. Until measured: 60 s is **provisional**, 5 s / 300 s are scenario bounds, and **no profitability conclusion may rest solely on the provisional value.**

## A.5 Costs **[MEASURE]** (ruling #6)
Primary cost = decomposed: taker fee tier + expected half-spread/crossing + expected slippage at the frozen copied notional, entry and exit charged separately (the within-bar adverse-fill haircut, A3, lives here). Report gross / fee-only / fee+spread / full. The old {8,8,10,14} bp schedule is retained as a **conservative sensitivity**, not the sole primary.

## A.6 Leakage control (frozen — ruling #10)
**Horizon-matched purge**, not a 1-month embargo: exclude training episodes whose markout window (max 8 h in the mid band) extends beyond C; exclude any feature needing post-C data; episode construction may not use later reductions/fills to redefine a pre-C signal. Automated per-fold assertions on forward-endpoint **bar** timestamps (`t0 + h < C`) + a temporal placebo (B3). 1-month embargo = sensitivity.

## A.7 Shrinkage (frozen)
Normal–normal EB exactly as `SCORE_AND_OUTCOME_SPEC.md` §6–7: sampling variance V(w,C) by wallet-day block bootstrap (captures cross-horizon correlation), method-of-moments τ̂²_C = Var_w[Zband] − mean_w V, λ = τ̂²/(τ̂²+V), θ̂ = μ̂_C + λ(Zband − μ̂_C). Reliability = active wallet-days (enters through V). The audit must report τ̂ vs mean posterior-SD so τ² identifiability is demonstrated, not assumed (A5); if τ² is not identifiable at the ≥30-day floor that is a reported feasibility limit, not grounds to residualize.

## A.8 Selection (frozen — ruling #9; discovery selector, not deployment selector)
The Phase-A confirmatory basket is **top 10% of eligible wallets by the shrunk gross information score θ̂ (SPEC §7), min 20 / max 50** — because latency/costs are unmeasured, a copyability-ranked selector is not yet defined and is **not** the primary. Tie-break by posterior **P(θ_w > μ̂_C)** (SPEC §7). Gates are **return-independent only** (A.1): reliability (active days/months, independent episode count, effective N **[AUDIT-ONLY]**), liveness. **No return-based concentration gate** — the "≤45% of estimated edge / ≤60% of episodes on one coin" hard filters are removed (item 9); coin specialists are *not* excluded (specialization may be genuine value). Portfolio-level coin concentration is controlled at the basket via coin caps (Gate B); wallet-level specialization is reported descriptively. Post-selection, return concentration is **mandatory robustness**: largest wallet / month / coin contribution, and leave-one-wallet-out, leave-one-month-out, leave-one-coin-out. If <20 qualify in a fold, that fold's basket is reported underpowered and excluded from the fold sign test (logged). Fixed top-40 = sensitivity.

**Gate B/C evaluate this exact preselected basket** under measured latency/costs — membership is *never* changed after observing delayed or cost-adjusted returns, so costs cannot retroactively alter who was selected. A basket ranked directly by a (later, measured) copyability score is a **separate, independently pre-registered experiment** and can neither replace nor rescue a failed primary result.

## A.9 Sizing (frozen)
**Only the wallet-day deployable bounded book** (`PORTFOLIO_AND_COST_RULE.md`) can set the deployment number (Gate B/C). Equal-wallet is descriptive only and can never constitute a pass (C5).

## A.10 Inference (frozen — ruling #11; item 1)
**The calendar-month forecasting fold is the ONLY headline inference unit.** Coin×fold pooling is **prohibited** — BTC/ETH/SOL/HYPE within a month are correlated through beta, vol regime, wallet selection, shared timestamps, portfolio capital, and common events; they are not independent Bernoulli trials and cannot manufacture additional confirmatory time observations. Coin decompositions and within-fold wallet permutations are **diagnostic only**.

The equal-wallet selected-minus-field contrast Δ_m (SCORE_AND_OUTCOME_SPEC §10c) is the headline series. Pre-registered sign-test rule = a function of the realized valid-fold count F: Δ_m positive in ≥ k(F) folds, where k(F) is the smallest count with one-sided binomial p (H₀ p=0.5) ≤ 0.05 — k(5)=5, k(6)=6, k(7)=7, k(8)=7, k(9)=8. **If the realized F cannot support rejection at 0.05, the result is inconclusive — it is not rescued by coin-level pooling.** Report **every fold, F, #positive, exact one-sided fold-level binomial p, fold-level mean, median, worst fold, leave-one-fold-out mean, across-fold dispersion.** No headline inference uses wallet- or episode-level pseudo-replication.

## A.11 Gates
- **Gate A — can the score locate better wallets? (confirmatory; needs no latency/costs).** Three independent statistics on the frozen Yband (SPEC §10), all on **individual wallets, equal-weighted**: (i) month-level wallet **rank IC** = Spearman(θ̂, Yband) across wallets — *not* a correlation of 10 decile means; (ii) **decile gradient** — all 10 deciles by prior-data θ̂, top-minus-bottom, monotonic Spearman across the decile index, each month; (iii) **equal-wallet selected-minus-field** Δ_m (SPEC §10c, §11), significant under the calendar-month fold sign test (§A.10) and robust to leave-one-wallet/-month/-coin-out. The wallet-day bounded-book contrast is reported as an operational secondary bridging to Gate B but cannot replace the equal-wallet test.
- **Gate B — can their observable activity form a profitable bounded portfolio? (sealed until inputs frozen).** On the **exact Gate-A-selected basket** (membership never revised after seeing returns): post-latency absolute return, return after frozen costs, bounded-capital **wallet-day** portfolio (this is a *different question* from Gate A — implementable capital rule, hence activity-weighted), month-level inference, concentration diagnostics. Not evaluated until `DEPLOYMENT_INPUT_FREEZE.md` is signed. Confirmatory only if the positive control certifies power; else inconclusive, never null.
- **Gate C — make-or-buy (secondary, sealed).** The same basket vs the **standalone public-strategy benchmark** (SPEC §12-ii — generates its own entries, no wallet timestamps/activity/direction) under matched coins/months/latency/costs/horizon/capital/concurrency/coin-caps/trade-budget. Separately, the **timestamp-matched fade** (SPEC §12-i) is reported as a *diagnostic only* and is explicitly **not** a make-or-buy alternative. Report the benchmark's own signed return; Gate C interpretable only if ≥1 of {basket, benchmark} is profitable; C-pass+B-fail is not evidence for the wallet layer (E2); a Gate-C null is inconclusive unless its MDE is small (E4). Gate C does not adjudicate beta-timing skill — that is Gate A.

## A.12 Public benchmark (frozen — ruling #7; item 8 — two distinct objects)
Two separate objects, never conflated (full spec: `SCORE_AND_OUTCOME_SPEC.md` §12):
- **Gate-C standalone public strategy** — threshold reversal / market-state direction that **generates its own entries** from rules fitted on prior data inside every fold. It does **not** use wallet timestamps, activity, direction, or trade occurrence. Matched on eligible coins, evaluation months, latency, costs, exit horizon, capital, concurrency, coin caps, and comparable trade/risk budget. This is the only object that answers make-or-buy.
- **Diagnostic timestamp-matched benchmark** — a mechanical fade evaluated **at the wallets' own timestamps**; answers only "does wallet direction add value given the wallet supplied the timing." Descriptive; not a make-or-buy alternative.
Market-state regression = serious secondary comparator to the reversal rule (not co-primary — E1 overruled per ruling #7).

## A.13 Positive controls (frozen — ruling #12)
Pre-registered fixed **recovery grid**: cross-sectional spread injections of **{0, 3, 5, 10} bp** (item 12). The **0-bp** simulation estimates false-positive behavior of Gate A; the positive injections estimate recovery power. Also: identity shuffle, timestamp/direction randomization. The grid is **fixed before any real wallet result is seen and never adjusted after.** Controls validate the pipeline; they **cannot** select basket size, shrinkage prior, eligibility thresholds, horizon weighting, or gate definitions.

## A.14 Execution order (frozen)
1. Apply auditor corrections (`AUDIT_CHANGE_CONTROL.md`).
2. Freeze the **Gate-A discovery configuration** (§A.1–A.11 gross-score portions, this doc).
3. Implement the leakage-safe episode + gross-ranking pipeline.
4. **In parallel:** instrument latency and estimate costs (§A.4/A.5 measurables).
5. Run **Gate A**.
6. Freeze `DEPLOYMENT_INPUT_FREEZE.md` from operational measurements — **without consulting any Gate-B/C output.**
7. Only then evaluate **Gate B**, then **Gate C**.
8. Stop/proceed per the pre-registered rules; **no exit optimization** unless Gate A *and* Gate B show sufficient evidence.

**Sealing invariant:** between steps 3 and 6, Gate-B/C code may be built parametrically, but their **outcomes are not inspected, logged to a human-readable report, or used to tune anything.** The provisional 60 s / {8,8,10,14} remain scenario labels only.

---

# PHASE B — low-frequency FEASIBILITY only (not confirmatory on this data)

Band {8, 16, 24, 48} h. On the 11-month tape this is a **feasibility/pilot** analysis: coverage/power audit, descriptive ranking, 48 h reported descriptively (right-censored at tape end). **48 h purge** at fold boundaries. A **confirmatory** low-frequency claim requires the deeper `node_fills_by_block` history (ruling #1). Phase B is never merged with the Phase-A headline.

---

# Sensitivities (≤2 per major fork; strictly one-fork-off-primary, non-compounding — C6)

| Fork | Primary | Sens 1 | Sens 2 |
|---|---|---|---|
| Min active months | 4 [PENDING] | 3 | — |
| Episode gap | 30 min | 15 min | 60 min |
| Episode termination | any reduction OR flip OR >gap | reduction ≥50% peak | — |
| Representative exit (book) | 4 h (band median) | 2 h | 8 h |
| Latency | measured percentile [MEASURE] | 5 s | 300 s |
| Cost | decomposed [MEASURE] | {8,8,10,14} conservative | fee-only |
| Band aggregation | SD-standardized mean | area-under-curve | — |
| Shrinkage prior | normal–normal, reliab=active-days | wider prior | — |
| Basket rule | top 10%, 20–50 | fixed top 40 | top 30 |
| Purge/embargo | horizon-matched (8 h) | 1-month embargo | — |
| Benchmark | walk-forward threshold reversal | market-state regression (secondary) | — |
| Universe | majors | + liquid-perp secondary (gated) | — |

**Robustness classification (item 13).** Before analysis, each sensitivity is tagged: **CS** correctness · **OS** operational · **MS** modelling · **UX** exploratory universe extension. All appear in **one fixed summary table** (T8). A favorable sensitivity may **never** overturn or rhetorically soften a failed primary result; the primary is reported standalone first.

# Degrees-of-freedom count

- **Phase A headline:** exactly **1** primary configuration (all "Primary" cells above + §A.1–A.13).
- **Pre-registered robustness surface:** 12 major forks × ≤2 one-at-a-time sensitivities = **≤ 21 sensitivity runs**, each reported as descriptive robustness, none able to upgrade a primary failure or set the headline.
- **Bands:** 1 confirmatory (mid). Low band is Phase B, feasibility-only, not counted in the Phase-A headline.
- **Benchmarks:** 1 primary (walk-forward threshold reversal) + 1 secondary (regression).
- **Total configurations that can touch the Phase-A confirmatory claim: 1.** Everything else is labelled robustness, feasibility, or secondary.

# Remaining decisions requiring business/ops input (before freeze)

1. **Latency [MEASURE]** — instrument the copy pipeline; supply the measured conservative-percentile latency.
2. **Costs [MEASURE]** — real taker fee tier, expected half-spread, and the intended **copied notional** (drives the slippage estimate).
3. **Phase-B data** — commission `node_fills_by_block` backfill now, or defer Phase B to forward paper-accrual?
4. **`[PENDING AUDIT]` ratification** — min effective-N, min months, concurrency/coin/wallet caps, exclusion thresholds — approved *after* the power/accounting audit returns, justified by reliability/capacity/ops.
5. **Secondary perp universe** — the clean-data/liquidity/coverage/ledger gates to admit non-majors (later, separate pre-registration).

No analysis code until this revised configuration is approved and frozen.
