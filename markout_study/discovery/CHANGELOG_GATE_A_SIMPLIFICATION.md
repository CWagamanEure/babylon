# CHANGELOG — Gate-A simplification pass (locked-retrospective)

Goal: the simplest statistically defensible **locked retrospective validation/pilot** of whether prior wallet markout predicts next-month wallet markout. This tape is extensively explored, so the result is **not** confirmatory. Every change below, with the doc(s) touched.

### Reframe — "locked retrospective," not confirmatory
"Confirmatory" → "locked retrospective validation/pilot" throughout the Gate-A set. *Docs:* `GATE_A_FROZEN_CONFIG`, `PREREGISTRATION_v2` (A.0, headline/DoF), `ARCHITECTURE` (inference stance), `EXPECTED_OUTPUTS` (headline template).

### 1. Relative ranking separated from absolute positivity
Two outputs: **`Δ_relative,m`** (selected−field Yband) = the verdict; **`A_selected,m`** (raw-bp absolute selected markout) = reported positive/negative, never merged. Added raw equal-weight band markout `Aband = ¼Σ_h Mbar` consistently across 1/2/4/8 h. A PASS with negative `A_selected` is reported as "separates better-from-worse, but selected still negative," **not** "found positive-markout wallets." *Docs:* `SCORE_AND_OUTCOME_SPEC` §9–10, `GATE_A_FROZEN_CONFIG`, `PREREGISTRATION_v2` A.0/A.11.

### 2. Decision rule simplified
Removed "primary passes but corroboration fails ⇒ INCONCLUSIVE." The `Δ_relative` monthly sign test is the **sole** verdict: PASS / FAIL / INCONCLUSIVE. Rank IC, deciles, pooled decile ordering, LOO = mandatory **descriptive** corroboration (explicitly related summaries, not independent confirmations) that cannot veto or rescue. `k(F) = min{k∈{0..F}: P[Binom(F,0.5)≥k] ≤ 0.05}`, algorithmic for all F; no valid k ⇒ inconclusive. *Docs:* `SCORE_AND_OUTCOME_SPEC` §10, `GATE_A_FROZEN_CONFIG` decision table, `PREREGISTRATION_v2` A.10/A.11.

### 3. Eligibility & reliability simplified
One fixed rule: ≥50 dedup episodes, ≥30 active wallet-days, ≥3 active months, ≥J=20 wallet-days at ≥3/4 horizons, active last 30 d, reconciled ledger, no clear system/wash flow. **Removed** from primary: episode-count concentration cap, separate effective-N floor, audit-optimization over min months, and the `R_C≥0.05` gate. Unrankable fold ⇐ N<N_min=100 OR degenerate scale OR τ̂²≤0 OR no meaningful ordering. J=20 fixed (feasibility-checked, **not** optimized on control recovery). *Docs:* `SCORE_AND_OUTCOME_SPEC` §4/5/7b, `PREREGISTRATION_v2` A.1/A.7, `AUDIT_ONLY_PLAN`, `GATE_A_FROZEN_CONFIG`.

### 4. Shrinkage bootstrap → weekly cluster
Replaced i.i.d. active-day resampling with a **weekly cluster bootstrap** within wallet (weeks resampled with replacement; a week carries all its days/coins/horizons jointly; frozen eligibility/horizon sets; B=1000; no redraw-until-success; invalid draws reported). Fallback: <6 active weeks ⇒ population prior (full shrinkage, count-based, not outcome-dependent). *Docs:* `SCORE_AND_OUTCOME_SPEC` §6, `PREREGISTRATION_v2` A.7, `GATE_A_FROZEN_CONFIG`.

### 5. Positive control → validate-only, on a proper null
Controls validate power/false-positive of the **already-frozen** pipeline; they choose nothing. Order: freeze by counts → run null/injection → report recovery@5 bp & FP≤5% → if not, label underpowered (no threshold search). **Nullized base** across all train+eval months (permute the four-horizon wallet-day vector across identities, jointly; sparse-stratum fallback hierarchy month×coin×dir×day → … → month; destroys identity-return persistence before injection). Injection = **flat per-horizon bp**, applied to train+eval, whole pipeline rerun, calibrated so expected **raw selected−field = 5 bp** (`c=2Δ*`); recovery metric = the actual simplified verdict. *Docs:* `POSITIVE_CONTROL_SPEC` (rewritten), `PREREGISTRATION_v2` A.13.

### 6. Conditional outcome tightened
Prominent statement: "Gate A estimates entry quality conditional on a scored wallet producing a next-month qualifying signal with complete 1/2/4/8-h outcomes." Report selected vs field every month: activity rate, four-horizon completeness rate, episode count, active-day count, complete-wallet count. Not deployability evidence (Gate B). *Docs:* `FUTURE_ACTIVITY_AND_ATTRITION`, `SCORE_AND_OUTCOME_SPEC` §10.

### 7. Exclusion logic
Do **not** exclude wallets for being automated/"bot." Target only liquidation/system, protocol-TWAP/system, wash/self-cross, unreconciled ledger, and unambiguous mechanical slicing. Uncertain slicing ⇒ **aggregate into episodes, not exclude**. "bot" category removed. *Docs:* `EPISODE_SPEC` §Exclusion, `PREREGISTRATION_v2` A.1.

### 8. Technical inconsistencies fixed
q1==q99 ⇒ **degenerate cross-section (unrankable)**, not "identity clipping." `λV` relabelled **posterior variance of the latent effect** (worked example). Purge is exactly `endpoint_price_ts < C` (no stray +5 min). Duplicate tie-break text removed (single tie-break: P(θ>μ̂), exact ties → sha256(address)). Stale median-hold removed from universe/architecture (descriptive/sensitivity only). Train = ≥3/4 horizons, **eval = 4/4** — stated consistently. Fill exactly on a 5-min close ⇒ next close (preserved). *Docs:* `SCORE_AND_OUTCOME_SPEC` §4/7/8/9, `EPISODE_SPEC`, `PREREGISTRATION_v2` A.6.

### 9. Audit-only plan reduced
No candidate-grid tournament. Fixed thresholds a priori; the audit only checks feasibility and resolves first-fold / fold-count / counts / J-feasibility / completeness / ledger / exclusion-precision / weekly-bootstrap feasibility. *Docs:* `AUDIT_ONLY_PLAN` (rewritten).

### 10. Final flow locked
Deterministic episodes → simple eligibility → 1/2/4/8-h wallet-day markouts → per-horizon pre-cutoff standardization → equal-weight band score → weekly-cluster reliability → one EB shrinkage → top-10% → evaluate (`Δ_relative`, `A_selected`, rank IC, deciles, liveness) → **verdict = monthly `Δ_relative` sign test only** → locked-retrospective label. *Docs:* `GATE_A_FROZEN_CONFIG`, `PREREGISTRATION_v2`.

## Statistical-flaw flag (as requested)
No change introduces a flaw. One honest **limitation** to surface: with ~4–6 folds, `k(F)` demands near-unanimity (k(5)=5, k(6)=6, k(7)=7), so the sign test is **low-power** — the most likely Gate-A outcome on this tape is INCONCLUSIVE, and even a PASS is locked-retrospective/suggestive. The fold-mean and its dispersion are reported descriptively alongside, but the **sign test remains the sole verdict** per your instruction; we do not substitute a magnitude test.
