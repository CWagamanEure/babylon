# GATE_A_FROZEN_CONFIG — one-page locked-retrospective Gate-A spec — **VERSION 1.0 · FROZEN 2026-07-06**

> **FROZEN v1.0.** No threshold, eligibility rule, estimator, selection rule, outcome definition, or verdict rule may be modified during the audit. The counts-only feasibility audit may only rule each frozen value *feasible-as-written* or *infeasible*. Any alteration requires a separately versioned Gate-A design and restarts the freeze.

> **FROZEN CONSTANT (F1).** `GLOBAL_SEED = 6439d8b356ed63376290c04f7856ab238d15f86781bb362da3f97e2ed2805288` (= `sha256("GATE_A_V1.0_LOCKED_RETROSPECTIVE_2026-07-06")`). All stochastic seeds — weekly cluster bootstrap `int(sha256(GLOBAL_SEED∥w∥C)) mod 2³²` and positive-control sims — derive from this single pinned value. Fixed before any nullized/real run.

**Framing:** this 11-month tape has already been explored extensively, so a positive Gate-A result is a **locked retrospective validation / pilot**, **not** genuinely confirmatory. A confirmatory result would require untouched historical backfill or prospective future months. **All thresholds below are fixed before the locked retrospective run and cannot be changed after the Gate-A outputs are inspected** (not "a priori" — this tape and its specs have already been explored). The counts audit only *checks feasibility*. No latency or costs anywhere in Gate A.

| Item | Frozen value |
|---|---|
| Universe | BTC, ETH, SOL, HYPE |
| Band / horizons | mid {1, 2, 4, 8} h |
| Walk-forward | monthly cutoffs C; evaluate month m after C; **expanding** pre-cutoff training, no recency weighting; first fold + fold count from counts audit (mechanical) |
| Entry price | `entry_price_ts(f)` = first 5-min **close strictly after** the fill (fill exactly on a close → next close); 0–5 min bar lag, **not** latency; `m(e,h)=d·(P(entry+h)/P(entry)−1)·1e4` |
| Purge | `endpoint_price_ts < C` (8 h at the mid band); leakage tests = post-cutoff perturbation invariance + physical-access |
| Episode | deterministic ledger; startpos reconstructed + left-censored quarantined; 30-min gap; flips (residual-only); dust rules + reduction floor `max($100,10% peak)`; 8 h same-wallet/coin dedup, earliest-wins, one set for all uses |
| Wallet-day unit | mean of episode markouts per (wallet, day, horizon) |
| Eligibility (return-independent, fixed) | ≥50 dedup episodes; ≥30 active wallet-days; ≥3 active calendar months; ≥J=20 wallet-days at ≥3/4 horizons; active in last 30 d; reconciled ledger; not clearly liquidation/system/wash/protocol-TWAP flow |
| Median hold | **not an eligibility variable** — descriptive / sensitivity only |
| Standardization | per horizon, across wallets, coin-pooled, winsorized 1/99 (wallet's own value clipped), pre-C; degenerate scale ⇒ fold unrankable |
| Band score | equal-weight mean of present-horizon z (≥3/4 in training; 4/4 in evaluation) |
| Reliability | **weekly cluster bootstrap** within wallet (one cluster = one active ISO week; all its days/coins/horizons move jointly), whole weeks resampled with replacement, B=1000, seed=sha256(GLOBAL∥w∥C), invalid-draw-not-redrawn; **<6 active weeks ⇒ unscoreable, cannot be selected** (no population-prior selection); reliability only, not time-series inference |
| Shrinkage | one normal–normal EB: τ̂²=max(0,Var_w[Zband]−mean_w V); λ=τ̂²/(τ̂²+V); θ̂=μ̂+λ(Zband−μ̂); posterior var of latent effect = λV |
| Selection | top 10% of eligible by θ̂, min 20 / max 50; return-independent; tie-break P(θ_w>μ̂), exact ties → ascending sha256(address) |
| Realized outcome | Yband(w,m)=¼Σ_h s(m−1,h)·Mbar(w,m,h) (scaled, ranking); **Aband(w,m)=¼Σ_h Mbar(w,m,h)** (raw bp, absolute); **defined only with 4/4 horizons**, no zero-fill |
| Field | wallets **eligible, scoreable, assigned a finite θ̂, in the same frozen ranking cross-section at C, but not selected** (SPEC §11). Unscoreable wallets (<6 weeks, invalid bootstrap, missing training horizons, …) enter **neither** selected nor field and are reported separately in attrition. Rank IC, deciles, and selected-minus-field all use this scored cross-section only |
| Inference unit | **calendar month only**; no coin×fold pooling |
| Rankable fold | N ≥ N_min=100 AND non-degenerate scale AND τ̂²>0; else `unrankable`, excluded from F |
| Eval-sufficient fold | **≥10 complete-outcome selected wallets AND ≥50 complete-outcome field wallets**; else excluded from F. (Decile density and selected-completeness rate are **descriptive only**, never fold-validity gates.) |

## Pre-run gate — positive controls (must pass BEFORE any real-data run)
Freeze all rules → run the nullized/injected controls (1000 frozen-seed sims) → the **point-estimate** decision: require **`FP_hat ≤ 0.05` at 0 bp** AND **`Recovery_hat ≥ 0.80` at the frozen 5 bp target** (also report 95% exact/Wilson CIs as MC-uncertainty diagnostics that do **not** change the decision; a near-boundary result is acknowledged MC-sensitive and is **not** rerun). If FP fails → pipeline **invalid**, do not unseal. If recovery fails → **underpowered**, do not unseal. **Only if both pass** is the locked real-data Gate-A result run. Controls validate the frozen pipeline; not a second test of the observed result, never modify thresholds (POSITIVE_CONTROL_SPEC).

## Gate-A verdict — the sole ranking test (real data, only after the pre-run gate passes)
**Primary object `Δ_relative,m`** = selected-complete mean Yband − field-complete mean Yband. Verdict by the monthly sign test only:
- valid-fold count F = rankable (§7b) **and** evaluation-sufficient (≥10 selected & ≥50 field complete) folds;
- **k(F) = min{ k∈{0,…,F} : P[Binomial(F,0.5) ≥ k] ≤ 0.05 }**, computed & verified **mechanically** (not a hard-coded table). **F<5 ⇒ automatically INCONCLUSIVE** (no rejection is possible at α=0.05 below 5 folds).

| Condition | Verdict |
|---|---|
| Δ_relative,m > 0 in ≥ k(F) folds | **PASS** (locked-retrospective positive — not confirmatory) |
| Enough valid folds, threshold not met | **FAIL** |
| Too few valid real-data folds, or >50% unrankable/eval-insufficient | **INCONCLUSIVE** (never "no effect") |

**Absolute positivity `A_selected,m` = mean over complete-outcome selected wallets of Aband(w,m)**, `Aband(w,m)=¼Σ_h Mbar(w,m,h)` raw bp. Reported separately (positive or negative), **plus the selected-wallet raw mean at each of 1/2/4/8 h** so a one-horizon effect cannot hide inside the band average. It **never merges into the verdict**. A PASS with negative A_selected = "ranking separates better-from-worse, but selected wallets' gross markout is still negative" — not "found positive-markout wallets."

**Sign-test independence (mandatory limitation):** the one-sided binomial p is **exact only conditional on independent monthly fold signs**; because wallets recur and the training window expands, serial dependence may reduce the effective evidence. Report lag-one autocorrelation of `Δ_relative,m` and of the sign sequence as limitation diagnostics — they **do not alter** the frozen verdict.

**Mandatory descriptive corroboration** (rank IC, all-ten-deciles, pooled month-equal decile Spearman, leave-one-wallet/-coin/-month): reported every fold, but they are **related summaries of the same ranking — not independent confirmations — and cannot veto or rescue the sign-test verdict.**

## Fixed values CHECKED by the counts audit (feasibility only — not resolved/tuned)
J=20 and N_min=100 are already **frozen**; the audit may only rule each **feasible-as-written** or **infeasible on this dataset** — it may **not** replace a threshold with a different value after seeing counts. Any threshold change requires a **newly versioned design and restarts the freeze**. The audit reports (data-availability only): first feasible fold; candidate-fold count; eligible-wallet counts; J=20 feasibility; N_min=100 clearance; 4/4 completeness; ledger quarantine; exclusion-label precision (≥0.90 else disable/manual); ≥6-week bootstrap feasibility. **None set from wallet rankings or returns.** Latency/cost are Gate-B/C only.
