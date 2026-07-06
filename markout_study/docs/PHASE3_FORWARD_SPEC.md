# Phase 3 — Frozen Forward Nested-Model Specification (pre-registration)

**Frozen 2026-07-05, before any forward data collection.** This document is the pre-registration for the decisive
forward test of the copy-trade thesis. The historical test window (2026-03…06) has been repeatedly inspected across
Stages M1–M4, so **it is NOT admissible as confirmatory evidence**. Only *new* forward data collected after this date
resolves the primary hypothesis. Nothing below (cohort, models, horizon, controls, capital rule, costs) may be tuned
after forward collection begins. Any change voids the pre-registration and starts a new one.

## Why this test exists (the arc, honestly stated)
Wallet *ranking* persists but weakly (bug-corrected rank-IC 8h ≈ +0.09, forward-decile +4.5 bp gross; discrete top→top
transition ×1.09 n.s.). The persistence is **triggered short-horizon reversal**, not demonstrated wallet skill: the
unconditional fade loses net (C = −7 bp), the feature-matched placebo fails (D = −5 bp), wallet *direction* adds nothing
(A−B ≈ 0), and the continuous-control residual is ~0 per-event. **Two things remain genuinely unresolved (not disproven):**
(i) the pre-registered **day-capped wallet-trigger residual +5.87 bp [−5.5,+17.7]**, which the historical window is
**blind to** (MDE ≈ 11–16 bp ≫ the ~5 bp we'd care about); (ii) whether wallet *activity* is a uniquely useful trigger.
Phase 2's in-train cross-fit gives a low prior (M1−M0 incremental CV-IC = −0.0003), but in-sample ≠ forward. This
experiment accrues the independent coin-days needed to settle it.

## Frozen objects
| Object | Frozen value | Artifact |
|---|---|---|
| **Recurring cohort** | 121 wallets, top-decile `neut_8h` (day-weighted) in ≥2 of 6 TRAIN months; STRICT subset 28 (≥3 mo) | `out/cohort_M_frozen.{txt,parquet}` |
| **Per-wallet conviction rank** | mean monthly train percentile `conv` (continuous) | `out/cohort_M_frozen.parquet` |
| **M0 model** (market-state only) | ridge, α=1, standardization frozen; 17 features | `out/cohort_P2_models.npz` |
| **M1 model** (market + wallet) | ridge, α=10, standardization frozen; 22 features (M0 + recurring indicator, conv rank, wallet direction, log size, position-building) | `out/cohort_P2_models.npz` |
| **Horizon / exit** | fixed 8 h from entry, no early exit | — |
| **Entry** | first bar close strictly after signal detection (next-bar-close), realistic detection latency logged | — |
| **Capital rule (PRIMARY)** | fixed capital per coin-day (day-capped); equal-weight-per-event = SECONDARY | — |
| **Coins** | BTC, ETH, SOL, HYPE | — |
| **Costs** | realistic HL round-trip {BTC 6, ETH 6, SOL 7, HYPE 9} bp, applied identically to A/B/C | — |

## Forward data to log (per candidate event, live)
For every recurring-cohort entry detected forward, log: detection timestamp & **detection latency**; **actual BBO** (bid/ask)
at detection and at fill; entry price, exit price (8 h later); **realized spread paid**, fees, **slippage** (fill vs mid);
funding accrued over the hold; **overlapping exposure** (concurrent open positions in the same coin/side); the wallet's
direction, size, conviction rank; and the full market-state feature vector at detection (so M0/M1 predictions are
reproducible). Also log the same market-state vector at a stream of **non-wallet control bars** (for the M0-everywhere leg).

## The three rules (same capital constraint, same frozen 8 h exit, same costs)
- **A — M0 alone.** At each recurring-cohort event, compute M0's predicted 8 h return from market state; trade
  `sign(pred)`, size by the frozen capital rule. Uses **no** wallet information.
- **B — M1.** Identical, but the prediction is M1's (market state **+** wallet features). This is the only leg that sees
  wallet identity/rank/direction/size.
- **C — direct copy.** Trade in the wallet's direction, no model. The naive copy-trade baseline.

## Hypotheses & inference
**PRIMARY — incremental wallet value:**  `net_return(B) − net_return(A)`  (day-capped per coin-day).  H1: > 0.
Costs are applied identically to A and B, so they cancel in the difference; the estimand is the pure incremental value of
wallet information over the market-state model.

**Secondary:** (1) recurring-activity indicator vs none = B vs A restricted to the indicator's contribution; (2) wallet
direction vs market-state direction = C vs A; (3) individual wallet traits vs wallet identity = M1-with-traits vs
M1-with-wallet-dummies (both frozen); (4) performance by coin and by month.

**Inference:** calendar-day **block bootstrap**, resampling whole calendar days jointly across all coins/wallets — trades
are NOT independent (8 h holds overlap ~12×/coin-day; wallets cluster on the same setups). Report point estimate + CI, not
just a p-value. Pre-register a minimum run length: collect until the day-capped test reaches **MDE ≤ 5 bp** (≈ the
care-about size); from the historical SE≈5.8 bp on 122 coin-days, that is on the order of **≥ 250–300 forward coin-days**
(revisit once forward variance is observed — this is a power target, not a stopping rule keyed to the result).

## Decision rules (applied once, at the pre-registered run length)
1. **B beats A materially & significantly** (day-capped `B−A` CI excludes 0, effect ≥ care-about) → wallet information adds
   incremental predictive value. Copy/condition on wallets.
2. **Activity improves A but direction does not** (B−A > 0 via the *indicator*, but C ≤ A) → wallets are useful **timing
   triggers**, not copy targets. Deploy the triggered fade; ignore wallet direction.
3. **B does not beat A** (day-capped `B−A` CI includes 0 with MDE ≤ care-about) → recurring wallets are proxies for
   observable market setups. Method-scoped negative on wallet-copying; deploy (if at all) the market-state model alone.
4. **Neither A nor B clears realistic costs** (both net CIs ≤ 0) → discontinue the trading thesis.

## Guards (both gates)
- A **null (rule 3) is only earned** with the MDE ≤ care-about power target met on forward data; short of that the verdict
  is INCONCLUSIVE, and the +5.87 historical residual is carried as a live underpowered positive, not buried.
- A **positive (rule 1/2) faces** the full false-positive gauntlet: it must survive the day-block CI, replicate across
  coins/months, and clear realistic costs before being called deployable. Post-hoc horizon/cohort/weighting changes are
  forbidden by this pre-registration.
- Liquidity/spread controls, absent in the historical bar data, ARE captured in the forward log (BBO, slippage) and enter
  the net-return legs directly — closing the one gap M4 had to defer.
