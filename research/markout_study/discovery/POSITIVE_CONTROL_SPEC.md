# POSITIVE_CONTROL_SPEC — validate power & false-positive of the FROZEN pipeline

Positive controls **validate the power and false-positive behaviour of the already-frozen Gate-A pipeline.** They do **not** choose J, minimum months, N_min, basket size, shrinkage rules, eligibility thresholds, or the verdict. No real wallet identity, ranking, or return association is exposed — outputs are aggregate simulation diagnostics only.

## Execution order — a PRE-RUN GATE, before any real-data Gate-A run
1. **Freeze** all eligibility, score, selection, and verdict rules (counts/coverage/correctness/ops only; AUDIT_ONLY_PLAN.md).
2. Run the **nullized and injected** controls on the frozen pipeline.
3. Require both: **false-positive ≤ 0.05 at 0 bp** and **recovery ≥ 0.80 at the frozen 5 bp target**.
4. If the **false-positive control fails** → the pipeline is **invalid**; **do not unseal Gate A** (fix the pipeline → newly versioned design → restart).
5. If **recovery fails** → the design is **underpowered for the target**; **do not unseal Gate A**.
6. **Only if both pass** is the locked real-data Gate-A result run and reported.

Positive controls **validate the frozen pipeline; they do not modify thresholds and are not a second test of the observed result.** They are **not** part of the real-data PASS/FAIL/INCONCLUSIVE table. The **recovery metric is the actual primary verdict** — a sim "recovers" iff `Δ_relative` passes the monthly sign test (SPEC §10). At 0 bp a pass is a false positive.

## Nullized base (the s=0 world)
The 0-bp world is **not** untouched real data (it may already contain genuine persistence). It is a nullization applied **across all months used by both training and evaluation**: within each stratum, **jointly permute the complete four-horizon wallet-day outcome vector across wallet identities**, moving the four horizons together (never independently).
- **Preserves:** episode/wallet-day counts, active-day/active-week structure, timestamps, coin & direction mix, common market movement, cross-horizon covariance, missing-horizon pattern.
- **Destroys:** persistent wallet-identity ↔ future-return association — genuine identity-return persistence is destroyed **before** any injection.
- **Sparse-stratum deterministic fallback hierarchy:** if a stratum has too few wallet-days to permute (<2 distinct identities), coarsen deterministically: `(month × coin × direction × day)` → `(month × coin × direction)` → `(month × coin)` → `(month)`. The first level with ≥2 identities is used; recorded per stratum.

Pre-injection verification (over sims): monthly rank IC ~ 0, `Δ_relative` ~ 0, sign-test false-positive ≤ 0.05.

## Injection (calibrated to the tested estimand)
On the nullized base, add a **flat per-horizon bp shift** (equal at every horizon) to a wallet's markout at **both training and evaluation observations**, then **rerun the entire ranking → selection → evaluation pipeline**. Latent quantile `u_w ∈ [0,1]` from a seed independent of real outcomes; shift `δ_w = c·(u_w − 0.5)`.
- Expected **selected-top-10% − field raw markout = 0.5·c** (uniform u; verified by simulation). The **5 bp target is on the raw selected-minus-field effect**, so `c = 10 bp`. Scaled Yband stays dimensionless; the target is stated in raw bp.
- Here and throughout, **"field" = the scored-cross-section field (SPEC §11)**: eligible, scoreable, finite θ̂, in the frozen ranking cross-section at C, not selected. Because each sim reruns the whole pipeline, selected and field are formed identically to real data and unscoreable wallets are excluded from both.
- Report at Δ\* ∈ {0, 3, 5, 10} bp raw (c ∈ {0, 6, 10, 20}).
- The effect is **persistent per wallet across all eligible months**; newly-eligible wallets get their deterministic latent rank from the wallet-address seed. Seed = `sha256(GLOBAL_SEED ∥ wallet_address ∥ Δ* ∥ sim_index)`. **1000 sims.**

## Monte Carlo acceptance convention (frozen)
Recovery and false-positive are estimated from the **1000 frozen-seed simulations**. The deterministic decision uses the **point estimates**:
- **FP passes** iff `FP_hat ≤ 0.05`;  **recovery passes** iff `Recovery_hat ≥ 0.80`.
- Also report **exact (or Wilson) 95% binomial confidence intervals** for both estimates.
- A **boundary result is NOT rerun** with new seeds, more simulations, or changed thresholds.
- The CIs are **Monte-Carlo-uncertainty diagnostics** and **do not alter** the frozen point-estimate decision.
Acceptable because seeds, simulation count, and thresholds are all fixed before execution. **A result near either boundary is explicitly acknowledged to be sensitive to Monte Carlo sampling error.**

## Outputs & fallback
- Recovery rate per level; false-positive at 0 bp (with the 95% CIs above); rank-IC / decile recovery as secondary diagnostics.
- **No-pass fallback:** if the frozen design does not reach `Recovery_hat ≥ 0.80` with `FP_hat ≤ 0.05` (point estimates), it is declared **underpowered / invalid** per the execution order — the grid is not enlarged and the threshold is not relaxed.
- Because controls run only on nullized/injected data, outputs **cannot reveal the genuine wallet-return association**, real rankings, or identities.
