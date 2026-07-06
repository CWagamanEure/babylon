# Stage I — Powered confirmation of the consensus/order-burst signal (pre-registered)

**Status:** architecture (pre-registration). No results yet. Data on hand: Aug 1 2025 → Jun 30 2026 (entries +
tape). This design spends NO new data; it extracts more power from existing data. A truly out-of-epoch verdict
still requires forward months (Jul 2026+) and is explicitly OUT of scope here.

## 1. The question (unchanged, sharpened)
Stage H found a **live but underpowered** positive: following the cohort *into* dip-buy order-bursts (≥K cohort
entries, same coin+dir, trailing 30-min) and exiting 4–6h earns **~+12–16bp idealized / ~+8bp BTC after real
fills** — but on only ~140 independent bursts the burst-clustered CI **spans zero** (MDE ≈ 56bp ≫ effect). It is
NOT generic crowding (matched-null centers −8bp) and NOT an adverse-fill mirage (dip-buy → favorable fill).
**Stage I asks: with a properly powered design on existing data, does the effect's CI separate from zero — or is
the data genuinely unable to resolve it (→ forward collection is the only path)?** We commit in advance to
reporting whichever answer the data gives, INCLUDING "cannot resolve."

## 2. Estimand (pre-registered)
Per **independent burst** `i`: signed forward return of the burst's direction over horizon h ∈ {4h, 6h}, in two
forms:
- **RAW** `r_i = dir·(P_{t+h}/P_t − 1)` — the deployability leg (what a copier books; net of cost this is the P&L).
- **NEUTRAL** `n_i = dir·[(P_{t+h}/P_t) − (M_{t+h}/M_t)]` where M = a **tradeable** market proxy: the equal-weight
  basket of the OTHER three majors (leave-one-out), priced over the SAME [t, t+h] window — the variance-reduction
  leg (the significance/existence test). This is a REAL hedge (short a basket you can trade), NOT the Stage-F
  coin-day-mean benchmark artifact. We report BOTH; significance is judged on NEUTRAL (lower variance), deployability
  on RAW-net-of-cost.

Aggregate estimand = mean over independent bursts, per coin and pooled, with BTC reported separately (capacity).

## 3. Signal definition (pre-registered — NO re-fitting)
- **Cohort:** rolling/expanding. At each evaluation block, cohort = top-decile wallets by neutralized 24h entry
  edge computed on data strictly **before** the block minus a 1-month embargo. (Primary = rolling cohort so the
  whole timeline is clean-OOS and it tests the *deployable strategy* "pick cohort by past skill, trade their
  bursts." Secondary/robustness = the FIXED Stage-H cohort, evaluated only Mar–Jun, as the exact Stage-H replicate.)
- **Threshold K:** PRE-REGISTERED at **K = 9** (the Stage-H plateau midpoint; K∈{5..9} were equivalent). We do
  NOT re-optimize K on the pooled data. We report a K∈{7,9,11} sensitivity band for transparency but the headline
  is K=9 fixed.
- **Burst = trailing-only** count: ≥K cohort entries, same coin, same sign, within (t−30min, t]. Strictly past —
  no look-ahead (verified in Stage H).
- **Independent-burst de-duplication (critical for honest N):** collapse flagged entries into distinct bursts =
  one burst per (coin, direction) per **non-overlapping 6h block** (so forward windows do not overlap and returns
  are near-independent). One outcome per burst (VWAP of that burst's entries as the reference, or first-trigger).
  N_bursts, not N_entries, is the sample size everywhere.

## 4. Power levers (existing data only)
1. **Variance reduction** via the tradeable-basket NEUTRAL estimand (§2) — cuts per-burst σ that drives MDE≈56bp.
2. **Rolling-cohort walk-forward** — every block from the first with enough history (~Nov 2025) through Jun 2026
   contributes clean-OOS bursts → target ~2–3× the 140 (expect ~300–400 independent bursts).
3. **Coin pooling** with per-coin reporting; BTC weighted for capacity.

## 5. Inference (pre-registered)
- **Point estimate + 95% CI** via **block bootstrap over independent bursts** (resample bursts, clustered by
  coin-week to respect any residual dependence). Report for RAW-net and NEUTRAL, per-coin and pooled.
- **MDE** at the achieved N and variance — reported prominently. If MDE still ≫ plausible effect (~10bp), the
  honest verdict is **"existing data cannot resolve" → forward months required** (anti-ratchet: do not relabel a
  blind test "inconclusive" forever; state the data limit).
- **Cohort-specificity placebo:** ≥300 activity-matched random 178-wallet cohorts through the identical pipeline;
  report the real cohort's percentile and threshold-shopping-corrected p (carry Stage-H method).
- **Walk-forward-block consistency:** the per-block OOS burst-edge sign/size across time — is it steady or
  one-regime? (guards the "few macro events" concentration Stage H flagged).
- **Deployability leg:** RAW net of tape-grounded execution (Stage-H: ~2.8bp crossing + 7bp fees + funding) and a
  capacity estimate; reported separately from the existence/significance leg.

## 6. Pre-registered verdict rules
- **Established-within-epoch (still needs forward test to deploy):** pooled NEUTRAL CI excludes 0 AND matched-null
  percentile ≥95 (corrected p<0.05) AND positive in ≥2/3 walk-forward sub-blocks AND BTC-alone directionally
  consistent.
- **Live-but-underpowered (Stage-H status, unchanged):** positive point estimate, matched-null lean present, but
  CI includes 0 / MDE ≫ effect.
- **Demote toward dead:** matched-null percentile <80 OR sign-flips across walk-forward blocks OR entirely
  carried by <5 bursts (drop-top-5 kills it).
- **Cannot resolve:** MDE ≫ effect even after all power levers → declare the data limit; forward collection is the
  only arbiter. We will not re-run the same blind cut and relabel it.

## 7. Known hazards the build must avoid (for the audit to check)
- Cohort-selection look-ahead in the rolling design (use only pre-block data + embargo).
- Fake N from overlapping bursts (enforce non-overlapping 6h blocks).
- Neutralization must use a TRADEABLE basket over the matched window (not a coin-day-mean benchmark; not a
  future-inclusive mean) — avoid the Stage-F artifact.
- K must stay pre-registered; the K-band is descriptive, not a new argmax.
- Multiple-comparison honesty: horizons {4h,6h} and K-band are reported as a family, not cherry-picked.
- Placebo cohorts matched on activity so "specificity" isn't a turnover artifact.

**Artifacts (planned):** `src/stage_i_powered.py`, `out/stage_i_bursts.parquet`, `out/stage_i_placebo.parquet`.
