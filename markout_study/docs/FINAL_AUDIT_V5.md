# FINAL_AUDIT_V5 — pre-flight verification for report v5

Each issue, its code location, the verified result, and the correction. Recomputations: `src/verify_v5.py` → `out/v5.json`. Cost schedule (canonical): BTC 8, ETH 8, SOL 10, HYPE 14 bp round-trip.

## 1. Transaction-cost consistency
- **Was:** "6–9 bp" prose, a separate BTC/ETH/SOL/HYPE 8/8/10/14 schedule, and figures labelled "net".
- **Fix:** one canonical cost table (8/8/10/14 round-trip, applied per scored entry) used everywhere; term "cost-adjusted under the assumed cost schedule"; "net" removed; upper-bound claim removed; omitted-cost list (latency, size impact, funding, partial execution, capital constraints) stated.

## 2. Fixed-121 economic calculation (bug fixed)
- **Code (`src/verify_v4.py`):** `cost_adj_bp = dpt − 7.0` subtracted a round-trip cost from the **cohort-minus-field difference** — invalid unless long-cohort/short-field. Field was correctly non-cohort (`~coh`), confirmed.
- **Fix (`src/verify_v5.py`):** three separate estimands — A absolute cohort (gross + cost-adjusted), B cohort−non-cohort-field (drift-neutralized, **no cost**), C cohort−matched-fade. Cost is applied only to the absolute return. See `docs/FIXED_121_ESTIMANDS.md`.

## 3. Fixed-121 weighting
- **Concern:** wallet-coin-day weighting rewards the cohort's defining cross-coin breadth.
- **Result:** under the three frozen weightings, B = +9.8 (wallet-day, p=0.001) / **+4.6 (equal-wallet, p=0.169)** / +10.5 (wallet-coin-day, p=0.001); cost-adjusted absolute +1.3 / −5.7 / +2.0. The field-relative advantage is not resolved under equal-wallet weighting — reported prominently.

## 4. Recurrence: training-only vs full
- **Fix:** training-only (6 months) permutation now reported as the cohort-justifying test — ≥2/≥3/≥4 months all p<0.001 vs null (121/27/5 vs 88.7/8.3/0.5). Full 11-month version relabelled exploratory. See `docs/RECURRENCE_TRAIN_VS_FULL.md`.

## 5. Event-study exhaustion claim removed
- **Code (`src/pi_compute.py`):** the event-study curve is `dir·(close(entry+τ)/close(entry) − 1)`, normalised to entry, so it is mechanically 0 at τ=0. Convergence to zero is not evidence of exhaustion.
- **Fix:** "the move had exhausted by entry" / "reverted toward entry" removed; the figure now supports only "prices tended to move against the eventual trade direction before entry." A separately-defined acceleration statistic (last-hour move minus prior-hour move) is described on its own where relevant.

## 6. Conditional-slope inference
- **Fix:** a pooled primary model — `raw_8h ~ trailing 8h move + coin FE + month FE + realized vol`, day-cluster bootstrap — gives slope **−0.058 [−0.108, −0.018]** (two-sided 95% CI excludes zero, n=590,910). Per-coin slopes are reported as heterogeneity checks; stated explicitly that CIs are two-sided 95%, one-sided p-values test H₀: β ≥ 0, there are four coin tests, and BTC is the most uncertain. No claim that every coin is individually established.

## 7. Bootstrap wording
- **Fix:** methodology now states calendar-day clustering preserves contemporaneous cross-wallet/coin dependence but **not** serial dependence across adjacent days; a 5-day non-overlapping moving-block variant addresses serial dependence for 24h outcomes. BTC 24h: day-cluster [−13.5, 0.0] vs 5-day block [−13.0, +0.1]; ALL 24h [−16.5, +3.4] vs [−16.7, +3.6]. BTC 24h interval now reaches zero and is described as marginal rather than resolved.

## 8. Behavioral chart labels
- **Code (`src/cohort_P1_behavioral.py:57`):** the 175/151/72 values are `aret_8h` = **absolute pre-entry 8h move**, not markout.
- **Fix:** panel renamed "Absolute pre-entry 8-hour move"; behavioral figure rebuilt from per-entry features with verified labels.

## 9. Direction-aligned pullback
- **Code (`:61`):** `dist_hi = ent/rmax − 1` = distance below the trailing 24h high — not symmetric for shorts.
- **Fix:** direction-aligned stretch added (`src/pi_compute.py` now saves `dist_hi`,`dist_lo`): long → distance below trailing high, short → distance above trailing low, both as positive distance from the relevant extreme. Recurring cohort 308 bp vs rest 199 bp; long/short reported separately.

## 10. Static-correlation reconciliation
- **Fix:** one canonical analysis (≥30 training & ≥20 validation entries, raw_8h wallet means, n=936): **Pearson +0.00, Spearman +0.02**. The prior "+0.02" and "0.00" were the Spearman and Pearson coefficients of the same analysis; both are now reported together.

## 11. Fixed-cohort result table
- **Fix:** prose replaced by the 3-weighting × 3-estimand table plus concentration diagnostics (by coin SOL-driven; month 05 negative; drop-largest-wallet B = +9.7). In `docs/FIXED_121_ESTIMANDS.md` and report §9.

---

## Before / after

| Item | Before (v4) | After (v5, verified) |
|---|---|---|
| Costs | "6–9 bp" + 8/8/10/14 + "net" | one 8/8/10/14 table; "cost-adjusted under the assumed schedule" |
| Fixed-121 cost | cost subtracted from field-difference (+3.5) | cost only on absolute (A_costadj +1.3 wd); B is cost-free |
| Fixed-121 weighting | single wallet-coin-day (+10.5) | 3 schemes; equal-wallet +4.6 p=0.169 (not resolved) surfaced |
| Recurrence | full 11-month only | train-only (cohort-justifying) + full (exploratory), separated |
| Event study | "move had exhausted by entry" | "moved against the eventual direction before entry" (no exhaustion) |
| Conditional slope | four per-coin one-sided tests | pooled FE model −0.058 [−0.108,−0.018]; per-coin = heterogeneity |
| Static ρ | "+0.02" vs figure "0.00" | one analysis: Pearson +0.00 / Spearman +0.02, n=936 |
| Behavioral label | "\|8h\| markout 175" | "absolute pre-entry 8h move 168"; dir-aligned stretch |

Every main-body number maps to a script/output in the reproducibility package (`docs/NUMBER_SOURCE_MAP.md`).
