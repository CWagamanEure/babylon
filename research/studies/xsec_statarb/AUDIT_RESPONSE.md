# Audit reconciliation — xsec_statarb design (2026-07-09)

Four-agent adversarial swarm (stats-rigor, data-integrity, firewall-leakage, correctness) on
`ARCHITECTURE.md` v1.0. This doc is **binding**: on any conflict with v1.0, the amendment here wins.
Findings deduped across agents (several were flagged 2–4×). Firewall = CLEAN. No finding kills the study;
several would have **manufactured a false NULL** on a 2–5 bp-vs-15 bp edge — the exact over-null hazard the
repo gate guards. Stage 1 does not start until the BLOCKERS are baked into the spec.

## BLOCKERS — must be in the design before Stage 1 (severity order)

**A1 — Estimand reframe: IC is the powered primary; OOS Sharpe is inconclusive-by-construction.**
[stats-F1, CRITICAL] SE(annualized Sharpe) ≈ 1/√years → 3-mo OOS ⇒ SE≈2.0, 80%-power MDE ≈ **Sharpe 5.6**;
full 11 mo ⇒ MDE ≈ **2.9** — both ≫ a deployable ~1–2. So OOS net Sharpe cannot distinguish a great book
from zero in *either* direction. **Fix:** the confirmatory primary is a properly-decorrelated **rank-IC**
(N = names×periods ≈ thousands); net Sharpe is reported as directional **with CI**, labelled
"inconclusive-by-construction," **never** "no edge." Pre-register the deploy bar as a **number now: net
annualized Sharpe ≥ 1.0** (full-sample block-bootstrap, MDE printed alongside). "Materially >0" is deleted.

**A2 — Signal-sign contradiction (would invert to momentum).** [correctness-F1, HIGH/CRITICAL-in-gate]
§5 `S=−z` (fade) vs §7 "long bottom-quantile S" ⇒ long the coin that just ran up = **momentum**, the opposite
of the hypothesis → a false-null on reversal at the §9 gate. **Fix:** with `S=−z`, **long TOP-quantile S
(the weak coins), short BOTTOM-quantile S (the strong coins).** Add a worked example to the doc
(coin ran up idiosyncratically ⇒ short it) so no build agent re-flips it.

**A3 — Same-bar mid entry fabricates reversion (bounce/stale).** [data-F2, HIGH] Fading the cross-sectional
*extremes* selects the largest recent `mid_px` moves; on alts mid bounces bid↔ask and goes stale (AS-OF
carry) → non-tradable reversion injected into exactly the selected names. Precursor corroborates ("mid
reverts ~1.5 bp more than oracle"). **Fix:** measure signal at t, **enter at t+1 mid** (drop the entry bar,
as the wallet leg already does), require reversal to survive the lag, and report a bid-ask-bounce control.

**A4 — Under-costing: impact spread ≠ cost at %-ADV size.** [data-F3, HIGH] `impact_bid/ask` price a small
fixed notional (~$10–20k); a %-ADV position is 10–25× that and walks deeper. "The ADV cap keeps us near it"
(v1.0 §8) is **false** — unrelated scales. **Fix:** model a **size→cost curve** (impact half-spread up to
the impact notional, book-walk penalty beyond), use the **point-in-time** spread at the rebalance minute
(widest when we trade), not the static 15 bp median.

**A5 — Cost double-count in turnover×spread.** [correctness-F2, HIGH] Turnover `Σ|Δw|` already charges each
crossing once; multiplying by `half-spread×2` (a round trip) double-charges ~2×. **Fix:**
`cost_t = Σ_i (half_spread_i(size) + fee)·|Δw_{i,t}|` — half-spread **once per crossing**; the round trip
emerges across two rebalances. (Interacts with A4: half_spread is size-dependent.)

**A6 — `mid_px==0` no-book sentinel (~17% alt rows) + NULL impact.** [data-F4, HIGH] A return across a
sentinel bar is a ±100% spike that poisons the residual and the PCA covariance; impact spread is missing at
the same no-book minutes. **Fix:** per-bar validity mask (`mid_px>0` AND impact populated) before any
return/residual; sentinel bars = missing (no synthetic return); define the exit/mark rule when the book is
absent at a rebalance (carry + conservative mark, don't silently drop the trade).

**A7 — `day_ntl_vlm` is daily-cumulative → intraday look-ahead.** [ALL FOUR: firewall-F2, data-F1, stats-F6,
correctness-F4] Using the current day's value (or its end-of-day total) at an intraday rebalance leaks future
volume into the universe filter and the %-ADV cap → inflated capacity, understated cost, survivorship-tinged
membership. **Fix:** derive ADV/liquidity from **completed prior UTC days'** end-of-day `day_ntl_vlm` only
(or a rolling trailing-window volume ending at t); validate the reset semantics (monotone-within-day) before
use. State the construction in §3/§7/§8.

**A8 — Wallet-cohort informedness must be strictly point-in-time.** [firewall-F1, HIGH] "Pre-ranked cohort"
is unbound; if informedness is estimated on a span overlapping/after the predicted returns, the cohort is
circular — the exact leak behind the repo's prior false wallet edge (`babylon-wallet-screen-verdict`).
**Fix:** cohort scores computed only on data with `close_ts ≤ t − embargo`, refit walk-forward, **frozen**
before each prediction bar; pre-register the informedness estimator. (Stage 6, but state now.)

**A9 — One static 3-mo holdout reused as a gate across 4 stages.** [stats-F2, HIGH] Stages 3→4→5→7 each
consult the same block → by stage 7 it is no longer OOS; the "joint surface" read scores ~12 near-collinear
L×H cells on that one block. **Fix:** replace the single static holdout with **purged + embargoed
walk-forward / nested CV** (no block is a repeated gate); block-bootstrap the **whole L×H surface jointly**
(cross-cell covariance) rather than cell-by-cell; apply a **deflated-Sharpe / multiplicity haircut** for the
config count. Pre-register a **single (L,H) pair**, not the 12–24h band.

**A10 — IC inference must correct time-overlap AND within-period cross-name dependence.** [stats-F3, HIGH]
Sub-hold rebalancing autocorrelates IC; the ~60 names share factor/PCA noise so effective cross-sectional
N ≪ 60 — a naive √(names×periods) t-stat overstates IC ~2×, and IC is the A1 powered estimand. **Fix:**
rank-IC with a **block bootstrap over time-blocks ≥ hold length that resamples whole cross-sections**
(preserving within-period dependence), or a two-way (period×cluster) cluster-robust SE. Never IID.

**A11 — Require OOS PnL factor-attribution, not just exposure reporting.** [stats-F4, HIGH] Trailing-beta
neutralization drifts OOS; a book residually short-momentum / long-carry / long-illiquidity can post a
positive Sharpe that is a **harvested factor premium**, not reversal alpha. **Fix:** regress realized OOS PnL
on realized factor returns; the **idiosyncratic (intercept/residual) component must be the significant
piece**, else demote the "edge" to a factor premium.

**A12 — Per-leg attribution on factor-neutral returns.** [correctness-F3, HIGH] The book is beta-neutral but
each leg alone is not; over a trending sample raw leg returns fabricate "long works / short doesn't"
asymmetry regardless of alpha — and "both legs contribute" is a pre-registered criterion. **Fix:** evaluate
each leg on its **residual (post-neutralization) return**, using post-neutralization weights (A2/B5).

## SECONDARY — fold into the build (MED; accept as amendments)

- **B1 — PCA leave-one-out level.** [firewall-F3, correctness-F5, data-F8] "Exclude i" only works for the
  **cluster-mean** variant; PCA LOO requires the eigenbasis/covariance recomputed excluding i (else i leaks
  into its own factor → spurious reversion). PCA and cluster-mean are **not** interchangeable (cluster-mean
  factors are collinear → unstable βs). **Prefer cluster-mean LOO** (cheap, clean); if PCA, fix PC sign/order
  vs prior window + shrink. Build the factor panel from the **PIT-eligible set with the A6 mask.**
- **B2 — Over-neutralization can null a real edge.** [stats-F7] Forcing exposure≈0 to noisy small-N PCA
  factors can eat the 2–5 bp residual signal. **A/B residual IC with vs without sector-neutralization on
  TRAIN**; only neutralize to factors that demonstrably clean (not eat) the signal. Choose K by OOS
  persistence. (This is the over-null mirror — treat symmetrically.)
- **B3 — Signal axis explicit.** [stats-F8] Pin: **within-period cross-sectional** rank of the residual; the
  lookback L enters as the **residual accumulation window**, not the standardization set.
- **B4 — Composite construction.** [correctness-F6] Residual/perp-premium/OFI partly measure the same
  dislocation → equal-weight z double-counts. **Orthogonalize each term against already-included terms (or
  IC-weight)**; publish the term-correlation matrix + each term's marginal IC + an explicit **signed-
  convention table** (positive term ⇒ fade-long).
- **B5 — Neutralized-ranking MVP.** [correctness-F7] The projection `w−B(BᵀB)⁻¹Bᵀw` is exactly factor-neutral
  but dollar-neutral **only if a ones-column is in B**, and it ignores the caps. **Fix:** augment B with a
  ones column; after projection **clip to weight/ADV caps and re-project** (or go to the full optimizer).
- **B6 — Four-part gate cross-unit test.** [stats-F9] Cross-*horizon* sign agreement ≈ one observation
  (correlated). Make the gate's independent-unit test **per-coin and per-time-block** sign tests; keep
  cross-horizon as secondary color.
- **B7 — New-listing eligibility.** [data-F5] Eligibility floor = `max(liquidity_history, beta_window +
  buffer)`; exclude until the trailing beta window is populated and betas stabilize.
- **B8 — Delisting settlement.** [data-F6] Force-close the terminal hold at the last **valid** (mask-passing)
  price + a stressed exit cost (or HL settlement/oracle); stress-test the sign (delistings cluster on the
  worst names → directional).
- **B9 — Basis consistency.** [data-F7, correctness] Pin residual/signal, return, and PnL to the **same
  tradable basis** (mid, sentinel-filtered); oracle/mark/premium only as **separate** features, checked for
  collinearity with the mid residual (premium = mark−oracle already overlaps).
- **B10 — Residual out-of-fit.** [correctness-F9] β estimated on `[t−W, t−1]`; `ε_{i,t}=r_{i,t}−β̂·F_t`
  computed out-of-fit (a t-inclusive fit self-attenuates the move → false null).
- **B11 — Report gross AND net together.** [stats-F5, correctness] Never headline "gross vs 2–3× spread"
  alone; pair it with net (funding + turnover- and size-scaled cost at target capacity).
- **B12 — IC definition.** [correctness-F8] IC = **rank-IC (Spearman)** of signal vs forward **residual**
  return over H (not Pearson, not raw return).
- **B13 — OFI term coverage.** [firewall note] §5's order-flow-imbalance term is **fills-derived =
  majors-only**; it cannot be computed on the alt cross-section. Drop it from the alt composite (or gate the
  composite to where fills exist). Consistency gap, not a firewall breach.
- **B14 — Funding hygiene.** [data-F9] Pin funding sign (positive ⇒ longs pay shorts) + hourly cadence on
  mark notional; define "predicted funding" as a **causal premium-implied** quantity (no realized-future
  funding in the signal).

## Credited as sound (auditors verified)
Firewall (header/§1) clean; PIT universe + clean delisting *intent* (§3); LOO concept as the right guard
(§4, modulo B1); neutralization **feasibility** (≈8–18 equality constraints ≪ 50–70 DOF — confirmed
tradable); weight-residualization gives **exact** neutrality (modulo B5 ones-column); multiplicity structure
(§6, modulo A9); overlap inference flagged (§11, modulo A10); gate-first (§9) + four-part null gate matching
the repo over-null gate.

## Net decision
Proceed to Stage 1 with **A1–A12 baked into the spec**. The two structural reframes — **IC-as-primary (not
Sharpe)** and **walk-forward (not a reused static holdout)** — are the biggest changes; the cost/microstructure
cluster (A3–A6) and the unanimous `day_ntl_vlm` fix (A7) are what stand between an honest floor test and a
fabricated one. ARCHITECTURE.md v1.0 stands as the design skeleton; this file governs where they differ.
