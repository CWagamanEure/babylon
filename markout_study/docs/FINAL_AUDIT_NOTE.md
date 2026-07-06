# FINAL_AUDIT_NOTE — report v4 pre-flight verification

Each issue raised, verified against code, with the correction made. All numbers from `src/verify_v4.py` → `out/v4.json` unless noted. Bootstrap: calendar-day cluster (independent days, 2000 draws), 334 calendar days.

## 1. Pre-entry sign convention (fixed)
- **Code (`src/pi_compute.py:28`):** `R = dir * (close(entry+off)/close(entry) − 1) × 1e4`. At a negative offset this is the *earlier* price expressed relative to the eventual entry price, signed by the trade direction — **not** the realized return over the preceding window.
- **Correction:** axis relabelled "earlier price minus entry price, in trade direction (bp)"; caption and prose state: *positive pre-entry values mean price was higher (for a long) / lower (for a short) before entry than at entry, i.e. price moved against the eventual trade direction as it approached entry.* Long/short worked examples added. The phrase "signed price change over the preceding eight hours" is removed.

## 2. Long-versus-short asymmetry (corrected — prior text was wrong)
- **Verified (v4.json `long_short`, 24h):** raw is strongly asymmetric — BTC long −23.4 / short +17.2, ETH −24.3 / +21.8, SOL −22.6 / +23.3. After coin-month neutralization it shrinks sharply — BTC −0.4 / −3.4, SOL −3.7 / +2.5 (ETH remains −14.1 / +8.2).
- **Correction:** the "no large asymmetry" claim is replaced with: *raw long/short markouts are strongly asymmetric at 24h, consistent with sample-period directional drift; after coin-month neutralization the asymmetry is materially smaller (largest residual in ETH).*

## 3. Pre-entry relationship test (formalized)
- **Verified:** fixed pooled-quantile bins with per-bin counts and day-cluster CIs; a pre-specified linear slope of subsequent 8h markout on the signed pre-entry move, fit on **training only**. Slopes are negative in all four coins: BTC −0.070 [−0.154, +0.002], ETH −0.050 [−0.121, −0.000], SOL −0.051 [−0.109, −0.010], HYPE −0.068 [−0.148, −0.006]; p(slope ≥ 0) = 0.027 / 0.025 / 0.006 / 0.016.
- **Correction:** the relationship is described as a *negative, statistically supported slope* ("subsequent markout generally declines as the pre-entry move turns from against to with the trade"); the word "monotone" is dropped. Bin edges are fixed quantiles chosen before viewing outcomes.

## 4. Trade-size analysis (corrected)
- **Verified:** quintiles formed **within coin and month** on pre-entry notional; equal- and notional-weighted 8h markout by quintile is [+0.4, −0.2, +0.1, −2.3, −1.0] — no increase with size.
- **Correction:** the "impact and noise" language is removed. New wording: *larger entry notional was not associated with higher subsequent decision markout in this specification.* No impact claim is made (candle data cannot measure impact).

## 5. Recurrence null (replaced with permutation null)
- **Verified:** permutation null preserving each month's eligible wallet set and top-decile slot count, resampling top membership within month (2000 permutations), on neut_8h over 11 months. Observed vs null: ≥2 months 213 vs 185.6 (p=0.0005); ≥3 months 72 vs 35.0 (p<0.001); ≥4 months 25 vs 5.0 (p<0.001).
- **Correction:** the heuristic binomial is replaced by this permutation test, which *strengthens* the recurrence result (all three thresholds now clear). Prior binomial numbers are labelled heuristic.

## 6. Fixed-121 cohort (full inference added)
- **Verified:** 121 selected (train-only, ≥2 of 6 months, neut_8h day-weighted); 97 active in validation, 24 attrition (no position-increasing majors entries in the validation window); 5,811 wallet-coin-days over 122 calendar days. Validation difference vs field (neut_8h, wallet-coin-day weighted): **+10.5 bp [+5.0, +16.3], p=0.001**; cost-adjusted (7 bp) **+3.5 bp**. Versus the matched reversal benchmark at the same entries: **−1.1 bp [−14.1, +12.0], p=0.572**. Concentration by coin: BTC +8.1, ETH +18.4, SOL +16.1, HYPE +5.0.
- **Correction:** the result is reported with full inference and kept explicitly distinct from (a) the static training top decile and (b) the dynamic monthly top decile. Its size is close to the mechanical fade and the fade-adjusted difference is not resolved.

## 7. "Net" terminology (replaced)
- **Correction:** every "net return" becomes "cost-adjusted return under the assumed 6–9 bp round-trip schedule." The schedule is no longer called an upper bound. A note lists omitted costs: latency slippage, size-dependent impact, funding, overlapping-capital constraints, incomplete execution.

## 8. Bootstrap documentation (specified)
- **Correction:** methods state the resampling unit (calendar day), that days are drawn independently (a **calendar-day cluster bootstrap**, not a moving-block bootstrap), that wallets and coins are carried with their day, that overlapping 8h/24h horizons are handled by day-clustering, and the draw count (2000). A pre-specified multi-day (5-day) block sensitivity note is added for 24h outcomes.

---

## Before / after headline table

| Item | Before (v3) | After (v4, verified) |
|---|---|---|
| Pre-entry sign | "signed price change over preceding 8h is positive" (ambiguous) | earlier-price-vs-entry in trade direction; positive = moved against eventual direction; formula + long/short examples |
| Long vs short | "similar; no large asymmetry" | raw strongly asymmetric at 24h (drift); neutralized asymmetry materially smaller |
| Trade size | "larger trades contribute impact and noise" | "larger notional not associated with higher decision markout in this specification" (no impact claim) |
| Recurrence | binomial ≥2 p=0.059 (heuristic) | permutation null: ≥2 p=0.0005, ≥3 p<0.001, ≥4 p<0.001 |
| Fixed-121 | +10.4 bp (n=93), no inference | +10.5 [+5.0,+16.3] p=0.001; cost-adj +3.5; fade-adj −1.1 [−14.1,+12.0] p=0.572; 97/121 active |
| Cost wording | "net return"; costs "upper bound" | "cost-adjusted under assumed 6–9 bp schedule"; omitted costs listed |

## Main-body claim → source confirmation
Every main-body number maps to a script/output in `docs/NUMBER_SOURCE_MAP.md` (v4 section). New objects: effective sample, long/short raw+neut, conditional slope, within-coin-month size, permutation recurrence, fixed-121 inference, rolling deciles → all `src/verify_v4.py` → `out/v4.json`; event study → `src/pi_compute.py` → `out/eventstudy.json`.
