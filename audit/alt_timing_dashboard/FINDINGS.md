# AUDIT FINDINGS — alt-timing deployment + OOS dashboard (6-agent swarm, 2026-07-10)

Swarm: stats-rigor, firewall-leakage, correctness, data-integrity + steelman(signal-hiding) + prosecutor(over-carry).
Verdict: **DEMOTE the alt-timing OOS positive to "confounded / inconclusive — rebuild clean before any verdict."**
Gated both ways (CLAUDE.md over-null AND over-carry).

## CONFIRMED DEFECTS (fixed in `alt_timing_dashboard_data.py`; export/follower still to reconcile)
- **F1 (HIGH, correctness) — MAJORS CONTAMINATION of the tilt.** `awb` spans `FACTORS+alts`; `tilt_of`/`fold_tilt`
  counted BTC/ETH votes. The live follower EXCLUDES majors → **backtested signal ≠ deployed signal (parity break).**
  Fix: `AND coin NOT IN ('BTC','ETH')` in tilt pulls.
- **F2 (HIGH, correctness) — score is majors-notional-dominated.** `sign(sum(flow))` over all coins ≈ sign of the
  wallet's BTC/ETH notional (majors dwarf alts). "Timing skill" was ranking majors-flow→alt-rotation predictors,
  not alt-selection skill. Fix: score on alt-only flow (`coin NOT IN ('BTC','ETH')`).
- **F3 (HIGH, data-integrity + correctness, TWO agents) — taker cost charged 2×.** `basket_half_spread_bp` is the
  FULL relative spread; per-crossing cost is HALF (dpos already counts crossings). Over-null hazard: inflates the
  "taker cost wall." Fix: `/2`.
- **F4 (MED, correctness) — OOS Sharpe diluted by pre-test flat hours** (pos=0→gross=0.0 finite, counted). Fix:
  mask Sharpe to test-month hours.
- **F5 (MED, 3 agents) — 1-hour train/test seam leak** in scoring (`hh<ms_cut`, no H-embargo; `freeze_cohort`
  guards it, dashboard dropped it). Immaterial to z but real. Fix: `hh < ms_cut - HOUR`.
- Minor: zero-fill of non-finite index returns dilutes IC (F6 data-integrity); gappy-`diff` spurious returns;
  `_spear` ordinal-tie handling; deployed SMOOTH=8 ≠ headline S_HEAD=1 (F6 correctness).

## THE REFRAME (prosecutor + correctness converge)
The signal exists **only** in the BTC/ETH-neutralized index (raw z=−2.18) → it loads on the **alt-vs-majors
rotation factor**. F1/F2 give the mechanism: the feature is literally built on **majors risk-on/off flow**, the
rotation driver. The random-recent placebo controls baseline rotation exposure but NOT rotation-*loading*.
⇒ **decisive missing control = a ROTATION/momentum-SELECTED placebo** (rank by alignment with PAST index momentum;
if it reproduces the informed IC, "skill" = passive rotation beta). NOW ADDED to the data-prep (`rot_tilt`).

## STATISTICAL OVER-READ (stats-rigor)
- z=3.04 is a **"beats-random-recent-selection"** statistic, NOT IC significance. IC-vs-zero t≈1.7 (inconclusive).
  Fix: emit BOTH `z_vs_random` and `t_vs_zero`.
- gross +1.60 Sharpe is t≈1.2 (CI∋0), net negative — prereg's own PRIMARY metric (net@top-tier) is negative.
  "Monetizable" was over-carry.
- H1/smooth=1 is an **argmax over ~48 configs** (horizon×smooth×cohort), no multiplicity penalty; prereg
  "froze" H1 AFTER seeing it. Clean adjudication = the forward paper window only.
- 4-fold sign test floor = 0.0625 (can't reach 0.05); folds non-independent (expanding train). 202606 fold negative.

## CLEAN (held up)
- No consequential train/test leak: causal rolling betas, recency gate strictly pre-fold, no circular-cohort reuse
  in OOS, matched random-recent placebo. Core arithmetic (position→return alignment, breadth-vote counting,
  trailing smooth, YYYYMM) correct. Determinism sound. Random-recent placebo IS a valid partial rotation control.
- Universe frozen at UNIV_FORMATION=20260301 applied to pre-formation folds = mild look-ahead (optimistic on
  absolute gross, ~cancels in the differential z). To fix in a redeploy: per-fold PIT universe.

## STEELMAN (signal-hiding) — the un-hiding levers (direction kept, in-sample magnitudes discounted)
- TOP: **skill-WEIGHTED breadth over the full recency pool** (not equal-weight top-N) — preserves breadth-power
  while emphasizing skill. = the user's cross-sectional redesign.
- `sign()` discards conviction → proportional sizing. Per-wallet COIN specialization untested (per-alt selection).
  7-name basket captures ~half the 45-name index signal. All-history score blends dead+live eras.

## NEXT (the powered, clean rebuild = the cross-sectional residual-positioning design)
Alt-only, relative/residual positioning (demean across TRADED set; Δq reallocation first), skill-WEIGHTED continuous
consensus, momentum/rotation-neutralized, 24h horizon (cheaper turnover), rotation-selected placebo as the make-or-break
control, IC-vs-zero CI + multiplicity reporting, judged on gross-per-crossing vs cost (maker frontier). See
[[babylon-xsec-statarb]] Result 8 (cross-section = real but ~10× sub-cost) — the win condition is COST, not IC.
