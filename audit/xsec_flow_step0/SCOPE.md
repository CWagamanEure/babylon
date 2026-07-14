# AUDIT SCOPE — xsec_flow_step0 (cross-sectional orthogonalized-flow base rate, 2026-07-10)

Shared `audit/AUDIT_PROTOCOL.md` rules ALWAYS hold (resource safety — a build MAY be running, do NOT load
`data/**` parquet or rebuild panels; verify-before-report; blast-radius severity; no edits; format). You are one
of several independent adversarial auditors.

## What was built & the claim
`research/studies/wallet_flow/xsec_flow_step0.py` (spec: `XSEC_FLOW_STEP0_ARCH.md`). Cross-sectional alt-SELECTION
test: target = per-hour cross-sectional RANK of forward BTC/ETH(+LOO)-residual return; predictor = size-blind
RELATIVE (demeaned over the wallet's traded set) reallocation flow, ALT-ONLY; continuous shrunk train-only skill
weights; neutralization LADDER (L0 raw → L1 ⊥crowd → L2 ⊥momentum → L3 ⊥funding); walk-forward 7 folds; TWO placebos
(P-random, P-rotation); day-block bootstrap CI; positive-control injection.

**Headline (L2, momentum-stripped):** h=4 V-trail IC +0.023 (t≈10.8, 7/7 folds), h=4 V-sim +0.018 (t≈8.5),
h=24 V-trail +0.010 (t≈4.7), h=24 V-sim +0.007 (t≈3.1, grazes 0). **Beats BOTH placebos incl. the rotation control**
that killed the prior alt-timing signal. Positive control recovers IC +0.72.

## ⚠️ This just replaced a signal (z=3.04) that a swarm proved was contamination. A big t here is a RED FLAG until
## vetted, not a green light. Attack these, each with `file:line` + a paper scenario:

1. **t-INFLATION via non-independence (TOP concern).** The day-block bootstrap blocks TIME only; same-hour coins are
   cross-sectionally correlated and wallets cluster (shared bots/strategies). The reported effective-N (60/60
   "independent" clusters) is flagged by the builder as optimistic (sparse disjoint supports → near-0 corr by
   non-overlap, not independence). Does the CI/t understate dependence enough to turn t≈10 into t≈2? Estimate the
   real effective N (coins/hour × wallet clusters × fold count).
2. **CONTEMPORANEOUS-IMPACT LEAKAGE.** Does S_{a,t} predict a genuinely FUTURE residual return, or partly reflect its
   own price pressure / a t↔t contemporaneous link that persists into Y? Verify `fwd_sum` is strictly k=1..h future,
   the rank `u` at t uses no ≥t info that also drives S, and the per-hour neutralization doesn't reintroduce
   contemporaneous return. Is h=4 ≫ h=24 a signature of short-horizon impact/reversal rather than selection?
3. **TARGET/PREDICTOR MECHANICAL CORRELATION.** `build_resid` removes BTC+ETH+a LOO-alt-index factor; the target is
   the cross-sectional rank of that residual. Could the demeaned flow predictor be mechanically correlated with the
   LOO-residual rank (e.g. both are cross-sectionally centered over the same alt set) independent of any real edge?
4. **EMBARGO / WALK-FORWARD LEAKAGE.** Train rows use `(mth<m) & (r < ft-h)` to embargo the seam — is it correct for
   BOTH h=4 and h=24 (drop h hours, not 1)? Recency gate strictly pre-fold? Skill score forward-return strictly
   train-only? Causal betas only?
5. **PLACEBO VALIDITY.** Is P-rotation truly zero-forward-info (LAGGED momentum only)? Is P-random the right null
   (weights shuffled among eligibles)? Could a subtly mis-built placebo be too weak, manufacturing "beats placebo"?
6. **V-trail vs V-sim.** V-trail (trailing-24h demean) is denser & stronger — does its trailing window introduce
   autocorrelation/staleness that inflates IC/t vs the purer V-sim? Is the builder's #1 caveat (weights
   frequently-traded coins more) material?
7. **NEUTRALIZATION correctness.** Per-hour cross-sectional `lstsq` residualization of S on [crowd, momentum, funding]
   — right controls, right sign, no rank/scale mismatch? Does L3-funding LIFT (not shrink) IC — is that suspicious?

## Two mandatory opposed passes (over-null / over-carry, per CLAUDE.md)
- **STEELMAN (signal-hiding):** is the edge BIGGER/realer than measured — is it concentrated in a coin/wallet subset
  the pooled IC dilutes? Which construction would sharpen it? Is h=4's strength real information the h=24 pooling buries?
- **PROSECUTOR (over-carry):** is t≈10 an artifact — clustering-inflated, contemporaneous-impact, V-trail staleness,
  or a mechanical target/predictor link? What single control would most cleanly demote it? Argue for DEMOTION.

Report per protocol format, most-severe first, file:line + scenario + confidence. A clean bill is valid — say what
held and what you could not rule out. The win condition for this line is COST (cross-section ~10× sub-cost, Result 8);
statistical GREEN ≠ deployable.
