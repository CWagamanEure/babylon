# AUDIT FINDINGS — xsec_flow_step0 (6-agent swarm, 2026-07-10)

Swarm: stats-rigor, firewall-leakage, correctness, data-integrity + steelman + prosecutor.
**Verdict: AMBER — real, leak-free, rotation-controlled cross-sectional lean, but modest & of UNRESOLVED economic
origin. NOT the t≈10 headline (demoted); NOT null.** First signal on the line to survive leakage AND the rotation placebo.

## SURVIVED (case FOR — over-null respected)
- **Leak-free (firewall):** all 6 vectors clean — strict-future target, causal betas, correct h-embargo, NO
  contemporaneous impact overlap, NO mechanical target/predictor link (LOO subtraction deflates if anything).
- **Beats rotation-selected placebo 7/7 folds** (the control that killed alt-timing). Beats random placebo.
- **Positive control recovers +0.72** → not blind (MDE ok).
- **Day-block CI excludes 0 at h=4** (V-sim [+0.013,+0.024], V-trail [+0.018,+0.029]); **7/7 folds same-sign**,
  month-block **t≈8** — legitimate cross-independent-unit evidence, NOT a clustering artifact.

## DEMOTED (case AGAINST — over-carry corrected)
- **t=10.8 → t≈8** (stats F1, correctness F2, prosecutor D2): headline t=`IC·√218,572 cells` treats correlated
  coin-hours as IID. Honest = day-block CI / month-block t. `effective_n` 60/60 is a sparsity artifact (not load-bearing).
- **~Half the IC is a base rate, not skill (prosecutor D1, STRONGEST):** P-random = +0.0127 → **skill increment ~+0.010
  @h=4, ~+0.007 @h=24 (marginal).** Base rate = recently-active flow → forward residual, decaying h4→h24 = fingerprint
  of **flow-continuation / own price-impact**, removed by NONE of L1(same-hr crowd)/L2(past mom)/L3(contemp funding).
- **h=24 (deployable horizon) marginal:** V-sim L2 CI includes 0 [-0.001,+0.015]; clears only at L3.
- **Survivorship (leakage F1 MED, data-integrity F1 HIGH):** frozen universe (UNIV_FORMATION=20260301) applied to the 3
  PRE-formation folds (202512/202601/202602 — which were strong) → future liquidity/survival picks the cross-section.
  Fix: per-fold PIT universe, or restrict folds ≥202603.
- **V-trail (headline arm) BUGGY + stale (correctness F1 MED, data-integrity F2):** trailing window closes at the current
  ROW not the current HOUR → same-hour siblings get order-dependent/truncated trailing sets; q_trail numerically wrong for
  mixed-sign hours + autocorrelation-inflated. ⇒ **V-sim is the honest primary.**
- **16-cell argmax, no FDR (stats F4); 30-draw placebo under-resolved, gap has no CI (stats F3).**

## FAILED prosecution angles (honest — did NOT demote)
- L3-funding lift = benign SUPPRESSOR removal, not a leak (prosecutor D5, data-integrity clean). Mechanical
  target/predictor centering link = clean (prosecutor D6, leakage probe). No contemporaneous impact leak (leakage/correctness).

## THE UNRESOLVED QUESTION + decisive test
Is the +0.010 skill increment INFORMATION or own-impact/flow-continuation? No current control separates them.
**DECISIVE TEST (prosecutor, do FIRST):** forward-IC decay + gap-lag decomposition — IC(S_t, resid[t+k]) per future k,
and vs gapped targets [t+g..t+g+h], g∈{1,2,4}. Concentrated at k=1 + dies under 1-2h gap → own-impact (taker-hopeless).
Smooth decay surviving the gap → genuine selection (modest, cost-gated).

## STEELMAN (signal likely UNDERSTATED, not fake)
Rank-IC discards fat-tailed alt magnitude → the **quintile long-short forward-residual RETURN spread (bp/crossing)** is the
deployment number AND where it looks bigger (also the cost gate). Conviction-preserving predictor (don't zero single-name
bets) + ADV-tertile stratification (edge likely in illiquid/meme alts) are the sharpening levers. Sharper wallet-weighting
= likely dead-end (honest).

## NEXT (priority order)
1. **Gap-lag decomposition** (impact vs info) — decisive, cheap, on existing cells.
2. **Honest re-run:** V-sim primary + fix V-trail window; per-fold PIT universe; lead with month-block t / day-block CI;
   report skill increment (IC − P-random) as headline; FDR over 16 cells; non-overlap resample.
3. **Economics: quintile-spread (bp/crossing) vs cost @h=24** — deployability gate. Win condition = COST (Result 8: ~10× sub-cost).
