# PRE-REGISTRATION v2 — revised, post-audit (supersedes PREREGISTRATION.md)

Incorporates the 5-agent design audit (`DESIGN_AUDIT_v1.md`, classified in `AUDIT_CHANGE_CONTROL.md`) and the user's 13 rulings. **Not yet frozen** — items marked **[MEASURE]** need instrumentation/business input before freeze; **[PENDING AUDIT]** are set by the training-only power/accounting audit (justified by reliability/capacity/ops, never by returns — ruling #8). Two phases; **they are never pooled into one headline** (ruling #1).

---

# PHASE A — locked-retrospective mid-frequency validation (11-month tape, now)

## A.0 Status of the Phase-A claim — locked retrospective, NOT confirmatory
This 11-month tape has already been explored extensively, so a positive Gate-A result is a **locked retrospective validation / pilot**, **not** genuinely confirmatory. A confirmatory result would require untouched historical backfill or prospective future months. Gate A asks: can a training-only, shrunk **gross entry-quality** score sort wallets by next-month mid-band **signed gross markout**, so the selected basket beats the non-selected field, under **calendar-month** inference? Two separate outputs (SPEC §10):
- **Relative ranking (the verdict) — `Δ_relative`:** selected-minus-field Yband; the sole PASS/FAIL/INCONCLUSIVE object.
- **Absolute positivity (reported, not the verdict) — `A_selected`:** selected wallets' raw-bp gross markout, reported positive or negative; a PASS with negative absolute is *not* "found positive-markout wallets."
Gross markout is the target because beta timing, reversal, momentum, and coin selection are admissible sources of wallet value; the selected-minus-field contrast removes *some* common movement but is **not** assumed to eliminate systematic exposure. Market-state-adjusted return is a **secondary diagnostic** only (Gate C), never selection-determining. Gate B/C (latency, cost, deployment) stay **sealed** until `DEPLOYMENT_INPUT_FREEZE.md`.

## A.1 Universe (frozen — return-independent eligibility, one simple rule)
BTC, ETH, SOL, HYPE. At each monthly cutoff C, from fills with `ts < C` **and horizon-purged** (A.6), eligibility uses **only return-independent evidence** (all fixed before the locked retrospective run and unchangeable after Gate-A outputs are inspected; the counts audit only *checks feasibility*, it cannot retune them): **≥50 deduplicated episodes; ≥30 active wallet-days; ≥3 active calendar months; ≥J=20 wallet-days at ≥3 of 4 horizons; active in last 30 d; reconciled ledger; not clearly liquidation/system/wash/protocol-TWAP flow.** **Removed from primary** (change 3): episode-count concentration cap, separate effective-N floor, `R_C≥0.05` gate, and audit-optimization over minimum months. **No return- or edge-based quantity enters eligibility or selection.**

**Median hold is not an eligibility variable** (descriptive / sensitivity only). Exclusion targets liquidation/system, protocol-TWAP, wash/self-cross, unreconciled ledger, and unambiguous mechanical slicing — **automated wallets are not excluded merely for being automated**; uncertain slicing is **aggregated into episodes, not excluded** (EPISODE_SPEC §Exclusion; change 7). **Maker-heavy wallets included only after passing the hard ledger-correctness gate (A.2b); otherwise excluded.**

## A.2 Episode construction (frozen — EPISODE_SPEC + audit fixes)
30-min gap; first-entry primary. Fixes now primary: **startpos reconstructed from full pre-C history; quarantine any wallet whose reconstructed position is left-censored (D1); `hold_est_h` = flat→flat lifetime, decoupled from termination (D2); fragments deduped to non-overlapping forward windows for the ≥50 count and every per-episode statistic (D3); min-reduction dust floor + explicit `q≠0`/no-open-episode handling (D4).**

### A.2b Ledger-correctness gate (hard, ruling #3)
Stratified manual + automated audit concentrated on low-taker-share wallets, testing: position reconstruction, open-vs-close classification, maker/taker interaction, direction flips, partial reductions, phantom round trips, and reconciliation against known position paths. Fail ⇒ excluded from the primary until corrected.

## A.3 Estimand & horizons (frozen)
- **Band:** mid {1, 2, 4, 8} h only (single band).
- **Primary information score** (Gate A): the shrunk θ̂ of `SCORE_AND_OUTCOME_SPEC.md` §1–8 — equal-weighted band mean of the four horizons' **gross signed markout**, each standardized by its training-window cross-sectional (across-wallet, coin-pooled, winsorized) SD, then normal–normal EB-shrunk. **Gross** — no benchmark subtraction in the primary target. The **single realized Gate-A outcome** Yband is frozen in SPEC §9. Dimensionless; used only to rank.
- **Secondary diagnostic score:** the same construction on market-state-/benchmark-adjusted return, reported for characterization and Gate C only. Never determines eligibility or selection.
- **Deployable-book return** (Gates B/C, sealed): one representative exit horizon = **4 h**, in raw bp, cost-subtracted. 4 h is chosen as the **central practical holding period of the frozen band, independent of observed returns** — it is *not* claimed historically optimal, and exit optimization is prohibited until the entry system clears Gates A and B. The markout curve is reported at all four horizons; the 4 h rule governs only the initial bounded-book test. (Ranking score ≠ return metric — A2.)

> **§A.4–A.5 are Gate-B/C only (item 17).** Gate A contains **no** latency, spread, slippage, or execution modelling and needs neither measurement; these `[MEASURE]` fields live only here, in `DEPLOYMENT_INPUT_FREEZE.md`, and `PORTFOLIO_AND_COST_RULE.md`, and never gate Gate-A eligibility, score, selection, or verdict. The authoritative Gate-A freeze sheet (`GATE_A_FROZEN_CONFIG.md`) contains no latency/cost at all.

## A.4 Latency **[MEASURE — Gate-B only]** (ruling #5)
Instrument source-event, ingestion, signal-generation, order-submission, expected-fill timestamps; set primary latency to a measured conservative percentile. Until measured: 60 s is **provisional**, 5 s / 300 s are scenario bounds, and **no profitability conclusion may rest solely on the provisional value.**

## A.5 Costs **[MEASURE]** (ruling #6)
Primary cost = decomposed: taker fee tier + expected half-spread/crossing + expected slippage at the frozen copied notional, entry and exit charged separately (the within-bar adverse-fill haircut, A3, lives here). Report gross / fee-only / fee+spread / full. The old {8,8,10,14} bp schedule is retained as a **conservative sensitivity**, not the sole primary.

## A.6 Leakage control (frozen — ruling #10)
**Horizon-matched purge:** a training episode enters a score only if `endpoint_price_ts < C` (8 h at the mid band); no feature uses post-C data; episode construction may not use later fills to redefine a pre-C signal. Mandatory hard tests (LEAKAGE_AUDIT_PLAN): **post-cutoff perturbation invariance** + **physical-access** (rows ≥ C removed → identical as-of-C outputs). 1-month embargo = sensitivity.

## A.7 Shrinkage (frozen)
One normal–normal EB, exactly as `SCORE_AND_OUTCOME_SPEC.md` §6–7: sampling variance V(w,C) by **weekly cluster bootstrap** (one cluster = one active ISO week, all its days/coins/horizons resampled jointly; whole weeks with replacement). **Scoreability floor:** a wallet with **<6 active weeks is unscoreable and cannot be selected** — no population-prior wallet enters the basket. τ̂²_C = max(0, Var_w[Zband] − mean_w V), λ = τ̂²/(τ̂²+V), θ̂ = μ̂_C + λ(Zband − μ̂_C); λV is the posterior variance of the latent effect. **No `R_C≥0.05` gate**: a fold is **unrankable** only if N<N_min=100, the scale is degenerate, or τ̂²≤0 (reported feasibility limit, not residualized).

## A.8 Selection (frozen; return-independent discovery selector)
The Phase-A basket is **top 10% of eligible wallets by the shrunk gross score θ̂ (SPEC §7), min 20 / max 50**. Tie-break by posterior **P(θ_w > μ̂_C)**, exact ties → ascending sha256(address). Gates are the return-independent eligibility of A.1 only — **no return-based concentration gate**, and coin specialists are **not** excluded (specialization may be genuine value; portfolio coin caps live in Gate B). Post-selection, return concentration (largest wallet/month/coin contribution; leave-one-wallet/-month/-coin-out) is a **mandatory descriptive disclosure that does not alter the verdict**. If a fold is unrankable or evaluation-insufficient it is excluded from F (logged). Fixed top-40 = sensitivity.

**Field (canonical, SPEC §11):** the field consists of all wallets that were **eligible, scoreable, assigned a finite θ̂, and in the same frozen ranking cross-section at C, but not selected.** Wallets that cannot be ranked (<6 active weeks, invalid bootstrap, missing training horizons, etc.) enter **neither** the selected group nor the field, and are reported separately in the attrition/accounting table. Rank IC, decile assignments, selected-minus-field, and field completeness/activity reporting **all run over this scored cross-section only.**

**Gate B/C evaluate this exact preselected basket** under measured latency/costs — membership is *never* changed after observing delayed or cost-adjusted returns, so costs cannot retroactively alter who was selected. A basket ranked directly by a (later, measured) copyability score is a **separate, independently pre-registered experiment** and can neither replace nor rescue a failed primary result.

## A.9 Sizing (frozen)
**Only the wallet-day deployable bounded book** (`PORTFOLIO_AND_COST_RULE.md`) can set the deployment number (Gate B/C). Equal-wallet is descriptive only and can never constitute a pass (C5).

## A.10 Inference (frozen — ruling #11; item 1)
**The calendar-month forecasting fold is the ONLY headline inference unit.** Coin×fold pooling is **prohibited** — BTC/ETH/SOL/HYPE within a month are correlated through beta, vol regime, wallet selection, shared timestamps, portfolio capital, and common events; they are not independent Bernoulli trials and cannot manufacture additional confirmatory time observations. Coin decompositions and within-fold wallet permutations are **diagnostic only**.

The equal-wallet **`Δ_relative`** series (SPEC §10) is the **sole ranking verdict** via the monthly sign test. `k(F) = min{ k∈{0,…,F} : P[Binomial(F,0.5) ≥ k] ≤ 0.05 }` for the valid-fold count F (rankable **and** evaluation-sufficient = ≥10 selected & ≥50 field complete), computed & verified **mechanically**. **F<5 ⇒ automatically INCONCLUSIVE** (no rejection possible at α=0.05 below 5 folds). **Not rescued by coin-level pooling.** The binomial p is **exact only conditional on independent monthly signs**; wallet recurrence + expanding windows can induce serial dependence, so **lag-one autocorrelation of `Δ_relative,m` and of the sign sequence are mandatory limitation diagnostics** (they do not alter the verdict). Report every fold, F, #positive, exact p, mean/median, worst fold, leave-one-fold-out, dispersion. No headline inference uses wallet-/episode-level pseudo-replication.

## A.11 Gates
- **Gate A — can the score locate better wallets? (locked retrospective; no latency/costs).** **Verdict = the `Δ_relative` sign test only** (PASS / FAIL / INCONCLUSIVE, GATE_A_FROZEN_CONFIG). **`A_selected`** (raw-bp absolute selected markout) is reported positive-or-negative but **never merges into the verdict**. Rank IC, all-ten-deciles, pooled month-equal decile Spearman, and leave-one-wallet/-coin/-month are **mandatory descriptive corroboration** — related summaries of the same ranking, **not independent confirmations**, and they **cannot veto or rescue** the sign test. The wallet-day bounded-book contrast is a Gate-B bridge, not a substitute.
- **Gate B — can their observable activity form a profitable bounded portfolio? (sealed until inputs frozen).** On the **exact Gate-A-selected basket** (membership never revised after seeing returns): post-latency absolute return, return after frozen costs, bounded-capital **wallet-day** portfolio (this is a *different question* from Gate A — implementable capital rule, hence activity-weighted), month-level inference, concentration diagnostics. Not evaluated until `DEPLOYMENT_INPUT_FREEZE.md` is signed. Confirmatory only if the positive control certifies power; else inconclusive, never null.
- **Gate C — make-or-buy (secondary, sealed).** The same basket vs the **standalone public-strategy benchmark** (SPEC §12-ii — generates its own entries, no wallet timestamps/activity/direction) under matched coins/months/latency/costs/horizon/capital/concurrency/coin-caps/trade-budget. Separately, the **timestamp-matched fade** (SPEC §12-i) is reported as a *diagnostic only* and is explicitly **not** a make-or-buy alternative. Report the benchmark's own signed return; Gate C interpretable only if ≥1 of {basket, benchmark} is profitable; C-pass+B-fail is not evidence for the wallet layer (E2); a Gate-C null is inconclusive unless its MDE is small (E4). Gate C does not adjudicate beta-timing skill — that is Gate A.

## A.12 Public benchmark (frozen — ruling #7; item 8 — two distinct objects)
Two separate objects, never conflated (full spec: `SCORE_AND_OUTCOME_SPEC.md` §12):
- **Gate-C standalone public strategy** — threshold reversal / market-state direction that **generates its own entries** from rules fitted on prior data inside every fold. It does **not** use wallet timestamps, activity, direction, or trade occurrence. Matched on eligible coins, evaluation months, latency, costs, exit horizon, capital, concurrency, coin caps, and comparable trade/risk budget. This is the only object that answers make-or-buy.
- **Diagnostic timestamp-matched benchmark** — a mechanical fade evaluated **at the wallets' own timestamps**; answers only "does wallet direction add value given the wallet supplied the timing." Descriptive; not a make-or-buy alternative.
Market-state regression = serious secondary comparator to the reversal rule (not co-primary — E1 overruled per ruling #7).

## A.13 Positive controls (frozen — ruling #12)
Full spec: `POSITIVE_CONTROL_SPEC.md`. Controls are a **pre-run gate**, run **after** the design is frozen and **before** any real-data Gate-A run — never part of the real-data PASS/FAIL table. The **0-bp world is a nullized base** (four-horizon wallet-day vector permuted across identities within month×coin×direction×day, sparse-stratum fallback hierarchy, applied across train+eval). Injection = **flat per-horizon bp**, applied to train+eval, whole pipeline rerun, calibrated so the expected **raw selected−field effect = 5 bp** (c=2·5). **Point-estimate decision over 1000 frozen-seed sims: require `FP_hat(0)≤0.05` AND `Recovery_hat(5 bp)≥0.80`** (report 95% exact/Wilson CIs as MC-uncertainty diagnostics that do not alter the decision; a near-boundary result is MC-sensitive and is not rerun). If FP fails → pipeline invalid, do not unseal. If recovery fails → underpowered, do not unseal. Only if both pass is the real Gate-A verdict run. Controls **cannot** modify thresholds or re-test the observed result.

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
- **Bands:** 1 locked-retrospective (mid). Low band is Phase B, feasibility-only, not counted in the Phase-A headline.
- **Benchmarks:** 1 primary (walk-forward threshold reversal) + 1 secondary (regression).
- **Total configurations that can touch the Phase-A locked-retrospective claim: 1.** Everything else is labelled robustness, feasibility, or secondary.

# Remaining decisions requiring business/ops input (before freeze)

1. **Latency [MEASURE]** — instrument the copy pipeline; supply the measured conservative-percentile latency.
2. **Costs [MEASURE]** — real taker fee tier, expected half-spread, and the intended **copied notional** (drives the slippage estimate).
3. **Phase-B data** — commission `node_fills_by_block` backfill now, or defer Phase B to forward paper-accrual?
4. **`[PENDING AUDIT]` ratification** — min effective-N, min months, concurrency/coin/wallet caps, exclusion thresholds — approved *after* the power/accounting audit returns, justified by reliability/capacity/ops.
5. **Secondary perp universe** — the clean-data/liquidity/coverage/ledger gates to admit non-majors (later, separate pre-registration).

No analysis code until this revised configuration is approved and frozen.
