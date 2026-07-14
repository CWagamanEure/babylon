# AUDIT SCOPE — alt-complex-timing deployment + OOS dashboard (2026-07-10)

Run-specific scope note; the shared `audit/AUDIT_PROTOCOL.md` rules ALWAYS hold (resource safety,
verify-before-report, blast-radius severity, no edits, reporting format). You are one of several
independent adversarial auditors of THIS session's work.

## ⚠️ Resource safety for THIS run
A dashboard data-prep pipeline **may be running** (`ps aux | grep alt_timing_dashboard_data` — pid ~70596).
Do NOT disturb it, do NOT rebuild the panel, do NOT load `data/**` parquet (schemas are in code). Reason
over code; tiny no-data numpy probes only. The alt tape schema: `awb` = one row per (wallet, coin, hour)
with signed `flow` + `mth`; `asset_ctx` = per-coin per-minute mid/mark/funding; `alt_flow` = raw
5-min signed-notional tape.

## What was built / the claims under audit
Two-level feature: (L1, monthly) rank wallets by TIMING SKILL = `avg( sign(hourly net flow) × forward
BTC/ETH-neutral alt-index return )`, recency-gate to wallets active in the last 2 months (≥40 alt-hours),
take top-1500. (L2, hourly) size-BLIND breadth vote `tilt = (#net-long − #net-short)/#active` across the
alt universe → smooth → `sign` position on a BTC/ETH-neutral 7-name basket.

**Headline claims to attack (each must survive or fall with a `file:line` + scenario):**
1. **OOS signal is real:** walk-forward (7 folds 202512–202606; re-rank + recency-gate on train-only,
   evaluate held-out month) → H1 IC **+0.0247, z=+3.04** vs random-recent placebo. H4/H8 ~null.
2. **In-sample IC z≈24 is CIRCULAR** (cohort scored on all history) and is correctly demoted to a
   reference — verify the OOS path is genuinely free of that same contamination.
3. **Gross monetizable at matched horizon:** smooth=1 gross Sharpe **+1.60**; taker net NEGATIVE at every
   smoothing (−3.75 to −17.49 @top-tier) → "real signal, taker cost wall."
4. **Recency gate fixes dormancy:** census 44% live / 26% alt-active (top-1500) vs 9% / 2% (old top-150).
5. **Deployment** (`src/babylon/follow/alt_timing_main.py`) faithfully computes the SAME tilt live (paper).

## Files
- `research/studies/wallet_flow/alt_timing_dashboard_data.py`  ← PRIMARY (OOS measurement + book + sweep)
- `research/studies/wallet_flow/export_timing_cohort.py`       (cohort freeze + recency gate)
- `research/studies/wallet_flow/alt_mt_recency.py`             (recency walk-forward z's)
- `research/studies/wallet_flow/alt_flow.py`                   (build_resid, build_cohort_tables, `_spear`)
- `src/babylon/follow/alt_timing_main.py`                      (live follower — tilt parity)
- `notebooks/build_alt_timing_dashboard.py`                    (viz logic)

## ⭐ THE OVER-ARCHING QUESTION (per CLAUDE.md over-null/over-carry gate — run BOTH directions)
The user's explicit worry: **"means, averages, and assumptions hide signals."** Two mandatory opposed passes:
- **STEELMAN / signal-hiding:** where does an AVERAGE / POOL / EQUAL-WEIGHT / NEUTRALIZATION / `sign()` /
  single-horizon / single-basket / fold-mean **destroy or dilute a stronger real signal** that a
  better-resolved estimator would surface? (e.g. breadth equal-weight drowning a sharp sub-cohort;
  LOO-index neutralization deleting real alpha; `sign()` discarding conviction; H1-only; 45-coin pooling;
  7-name basket ≠ where the edge lives; averaging over a strong regime month). Argue the finding is
  BIGGER/realer than measured, with a concrete construction that would show it.
- **PROSECUTOR / over-carry:** is the z=3.04 actually noise? Attack: argmax across the H×N×smooth search
  space (multiplicity), fold non-independence (overlapping expanding train pools), gross +1.60 not
  significant alone, placebo-pool mismatch, the "is it just alt-season?" confound (tilt ≈ a slow
  alt-vs-majors rotation factor, not wallet skill). Argue it should be DEMOTED.
Report which side wins on each specific mechanism, with `file:line` + a paper scenario.
