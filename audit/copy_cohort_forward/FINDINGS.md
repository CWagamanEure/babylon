# AUDIT FINDINGS — copy_cohort forward modules (build-stage swarm, 2026-07-12)

Three agents (correctness, firewall-leakage, stats-rigor) against `base.py`, `selectors.py`,
`walkforward.py`, `power_gate.py`, `mu_fold.py` + the `research/lib/stats.py` additions.

**Disposition: all findings accepted; CRITICAL + HIGH + cheap MED/LOWs fixed; power gate re-run.**
Severities: 1 CRITICAL, 1 HIGH, 3 MED, several LOW/NIT.

## Verified-clean (load-bearing)
- **eb_shrink integer-key change ≡ string-composite version, bit-for-bit** (stats-rigor probe).
- base.py markout⋈episodes join is 1:1, collision-free, no fan-out, all fields carried (correctness).
- Temporal seams clean: formation/forward partition on open_ts at the cutoff; per-fold μ censored
  `(t+h)≤cutoff`; formation μ frozen before forward μ overwrites; no episode double-count; cutoff
  arithmetic `as_of_cutoff_ms(last formation month)` correct; lane firewall clean (firewall audit).
- p-value machinery correct: +1/(B+1) corrections, one-sided exact binomial, BH ordering, MDE
  formula, twoway CGM df/floor.

## Fixed
- **[CRITICAL cor] power_gate MDE/planted CGM used wallet-nested `wk_code` as the "week" dimension**
  → understated MDE (blind to cross-wallet week shocks; df collapsed to G_wallet). Fixed to plain
  `week_open`. Re-run: MDE 6.11 → **6.71 bp** (honest; still > 5 care-about). Direction confirms
  the gate STOP is robust.
- **[HIGH stats/cor] pooled arm sign test counted a wallet's 5 fold-echoes as independent**
  (21% vs 5.6% false-positive) → collapse to ONE unit per distinct wallet (avg across its folds).
- [MED] BH arm-p (wallet_week flip) is blind to cross-wallet week shocks → labeled; two-way CI is
  the binding gate. [MED] episode- vs wallet-weighting split → both reported, wallet-equal is the
  economic headline. [MED] planted control noiseless-uniform +5bp is optimistic → noted (selection
  blindness holds a fortiori). [LOW] realized MDE field added to walkforward arm report (§7 RED
  input); NaN-placebo dropped from p_placebo; capture_vs_chance denominator K not N_PLANT; forward
  non-empty assertion; EBShrink.raw_mean docstring corrected.

## Power gate result (post-fix, audit-clean)
- **Evaluation MDE = 6.71 bp > 5 bp care-about** → cannot resolve a 5bp-margin cohort effect.
- **Selection capture at +5bp = 0.04** (≈ chance 0.019); capture>0.5 needs ≈ +80 bp/episode true
  edge. Per-wallet markout selection is blind at the deployable margin (per-episode sd 164bp,
  ~61 scoring eps/wallet → per-wallet SE ≈ 21bp).
- **GATE PASSED = False.** Pre-registered §6 rule: STOP the forward run pending a decision.
