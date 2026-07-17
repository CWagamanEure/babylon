# Alt-universe fresh-wallet replication — PRE-REGISTRATION (frozen before the all-wallet ingest is run)

Frozen 2026-07-16, BEFORE `alt_universe_ingest.py` has pulled a single day and before any all-wallet
alt PnL or any new cohort's forward return has been computed or viewed. Purpose: the confirmation test
the 2026-07-16 alt validation could not provide — the scale signal on **wallets never seen before**.
Follows ALT_VALIDATION_PREREG.md's discipline; nothing here may be re-tuned after data is seen.

## What the 2026-07-16 result established (and its gap)
Majors-selected LARGE-scale wallets beat SMALL on alt 8h markout in every robust cut (winsor+wf≥3
Δ +87.4 CI [+11.0,+165.3]; median shift perm p=0.004) — but on the SAME 133 wallets that generated the
hypothesis. THIS test closes that gap: new selection, new wallets, pre-registered once.

## Frozen design
**Data.** `alt_universe/wallet_coin_day/` (per-wallet-coin-day exact-DECIMAL pnl/fee/notional aggregates,
all wallets, all perp coins, 20250801–20260630) + `alt_universe/open_entries/` (all flat taker position-
opens). Built by `alt_universe_ingest.py` (streaming, raw deleted). Firewall: research lane only.

**Selection (identical to the frozen capday rule, now on COMPLETE PnL).** Per wallet×day across ALL
coins: `day_pnl = Σ(pnl − fee)` (builder_fee reported separately, excluded — matches majors' Σ(closed_pnl−fee)),
`day_notional = Σ notional`, `cap_pnl_day = day_pnl·min(1, 100_000/day_notional)`; trailing 3 calendar
months ending T−1; active days nd ≥ 15; metric = `Σ cap_pnl_day / nd`; **top-30 monthly**, folds
202511–202606 (same 8 test months).

**Scale classification.** Per selected wallet-fold: median notl of its `open_entries` flat taker opens in
the formation window (ALL coins — the alt-inclusive analogue of the majors rule). LARGE = top half within
fold. No other feature enters selection or classification.

**FRESH-WALLET definition (the point of this test).** A wallet-fold membership is FRESH iff the wallet is
NOT in `frozen_alt_universe.json`'s 133 `distinct_wallets`. Primary analysis uses FRESH memberships only;
overlap with the old 133 is reported descriptively (a high overlap is itself informative but is NOT the test).

**Forward book (identical basis to the 2026-07-16 validation).** The cohort's forward-month flat taker
opens (from `open_entries`), ALT coins only for the primary (majors already tested), 8h gross dir-signed
markout on the asset_ctx mid lattice, ≤90s staleness both ends, wallet-equal.

## PRIMARY hypotheses (both required to be stated up front; H2 is the key one)
- **H1:** μ(FRESH large, alts, 8h gross) > 0
- **H2:** μ(FRESH large) − μ(FRESH small) > 0

**Registered inference (upgraded per the 2026-07-16 prosecution — percentile bootstrap on skewed
wallet-folds is anti-conservative and is NOT the registered test here):**
- Primary estimator: wallet-equal mean, **winsorized at p95 of |mk| within stratum, wallet-folds with
  ≥3 evaluable entries** ("robust spec" — exactly the prosecutor's harshest surviving spec, chosen NOW,
  before data).
- Primary test: paired wallet-cluster bootstrap on the robust spec (H2), 4000 reps, seed 20260716; plus
  wallet-collapsed sign test and median-difference permutation p (both reported; claim requires bootstrap
  CI > 0 AND perm p < 0.05).
- Raw (unwinsorized, all-wf) estimates are REPORTED alongside, never headline.
- Coverage gate (else "underpowered", no verdict): ≥40 FRESH-large evaluable alt entries, ≥3 folds,
  ≥5 FRESH-large wallets.

## SECONDARY (reported, never re-tuned)
1. Same H1/H2 on the FULL new cohort (fresh + repeat) — comparability with 2026-07-16.
2. Overlap census: how many of the new top-30 are in the old 133; rank stability.
3. Notional dose-response (≥$250 / ≥$1k strata) — carried from 2026-07-16, still hypothesis-grade.
4. Majors-selected vs alt-inclusive-selected cohort membership diff — does complete PnL change WHO is picked?
5. Alt-taker cost sensitivity at 20/50/100bp RT (report only).

## Decision rule
- H2 robust-spec clears (CI>0 AND perm p<0.05) on FRESH wallets → the scale signal is REPLICATED on
  unseen wallets; proceed to deployment design (maker/cost path + exit study) as the next registered step.
- H2 directionally positive but not clearing → underpowered-positive; the accumulation levers (longer
  window, forward paper) are next; NO re-tuning of selection/classification.
- H2 ≤ 0 with adequate coverage → the scale signal does not survive fresh selection; report the negative
  honestly (the 2026-07-16 result is then demoted to same-wallet persistence, not a selection signal).

## Cost/scope
One streaming pass over 333 Reservoir days (~139GB egress ≈ $12.5, requester-pays; ~0.5GB peak disk,
retained layer <1GB). Run: `python -m research.studies.copy_cohort.alt_universe_ingest range 20250801 20260630`.

---

# ADDENDUM (frozen 2026-07-16, same day, BEFORE any lake selection/return data viewed)

Registered while the all-wallet lake ingest is still running. As of freezing, the only landed lake data
viewed by anyone is the smoke day 2026-06-01's row counts (no selection, no markout, no per-wallet metric
has been computed or seen). The addendum adds two SELECTOR ARMS to the same fresh-wallet test — the
"informedness" refinements motivated by the luck-vs-skill critique of level statistics (a top-30 of any
LEVEL metric over ~200k wallets is tail-luck-enriched by construction).

## Arm definitions (all share Arm C's frame: CAP=100k, 3-mo trailing window ≤ T−1, nd≥15 active days,
## top-30 monthly, folds 202511–202606, scale classification + forward book identical)

- **Arm C (already registered above):** metric = Σ cap_pnl_day / nd  (level).
- **Arm T (t-stat):** metric = t_w = mean_d(cap_pnl_day) / (sd_d(cap_pnl_day)/√nd) over the window's
  active days (sample sd, ddof=1). Rewards consistency, punishes lottery paths with the same mean.
- **Arm P (posterior informed, two-groups EB / local-FDR):**
  1. p_w = one-sided survival P(T_{nd−1} > t_w) (exact Student-t via regularized incomplete beta);
     z_w = Φ⁻¹(1 − p_w), clipped to [−8, 8].
  2. Pool = ALL eligible wallets that fold (nd≥15). Empirical null by Efron central matching:
     60 equal bins on [−8,8]; fit log f̂ by degree-5 polynomial Poisson-style fit on bin log-counts
     (bins with count>0); fit the null N(μ0,σ0²) by quadratic fit to log f̂ on the central-quartile
     z-range; π0 = min(1, implied-null mass / total mass).
  3. lfdr(z) = clip(π0 · φ((z−μ0)/σ0)/σ0 / f̂(z), 0, 1);  **P_informed(w) = 1 − lfdr(z_w).**
  4. Selection: top-30 by P_informed, ties broken by t_w. (P_informed is also the registered per-wallet
     "probability the wallet is informed" deliverable — table per fold under
     `data/derived/copy_cohort/informedness/`.)

## Hypotheses & inference (per arm, FRESH wallets primary, same robust spec as the main prereg)
- H1_arm: μ(arm cohort FRESH, alts, 8h gross, wallet-equal, winsor-p95, wf≥3) > 0.
- H_T>C / H_P>C (the interesting ones): paired wallet-cluster bootstrap of Δ(arm − Arm C) on the SAME
  fold months (pairing on wallet where cohorts overlap, else independent clusters) — does informedness
  beat the level metric?
- Multiplicity: the FRESH-replication headline remains Arm C + scale (unchanged by this addendum).
  Arm-level H1 significance claims apply BH across the 3 arms. Arm T/P vs C deltas are registered
  secondary hypotheses (directional, >0).
- No parameter of Arms T/P (cap, window, bins, poly degrees, clip range, top-K) may be changed after
  lake data is viewed; any variant explored later is unregistered and must be labeled as such.
