# Phase 1 audit note — verification before rewriting the markout report

Source-code and output verification of the load-bearing claims in `report.md`, prior to producing `report_v2`.
Each item lists the issue, the verified fact, and the correction carried into `report_v2`.

## A. Markout is not realized PnL (wording)

- **Current text:** "each entry's horizon-markout *is* the trade's PnL"; summary "the horizon markout is the trade's PnL."
- **Verified (`mkcommon.markout_ret`, `price_entries`):** markout = `dir · (close(first bar after entry+h) / close(first bar after entry) − 1)`. Both endpoints are strictly post-fill next-bar closes; there is no cost, spread, funding, or actual exit.
- **Correction:** define markout as a **hypothetical gross signed price return from the observed (post-fill) entry to a fixed horizon**. It is not realized PnL. "PnL" is reserved for reconstructed/simulated positions with execution and costs. Sharpe and drawdown derived from the markout series are markout-based statistics, labelled as such.

## B. Observation unit (was under-specified)

- **Verified (`build_entries.py`, `mkcommon.taker_entries`):** one observation = one **position-increasing taker decision**, i.e. a `(wallet, coin, bar, direction)` cell. A fill is scored only if it is taker (`crossed`), non-wash (`~zhash`), and increases `|position|`. Maker, wash, and position-reducing/closing fills are tracked (for correct position/burn-in) but never scored. Same-bar, same-direction opening fills are **clustered into one entry** at the shared next-bar price (summed size). Intrabar reversals are counted per leg.
- **Consequences to state:** partial fills inside one bar → one entry; scaling into a position across several bars → several entries (each weighted once), so entry-weighting up-weights positions built over many bars and high-frequency wallets; a position's closing leg is not an observation.
- **Overlapping horizons:** nearby entries have overlapping forward windows; point estimates average them, and dependence is handled by **calendar-day-block bootstrap** in all inference.
- **Weighting labels (now applied to every result):** term-structure and top-wallet tables = **entry-weighted**; Stage-K skill verdict = **wallet-equal-weighted**; rank-persistence/decile tests = **wallet-day-weighted**; cohort deployability = **wallet-day-capped (equal capital per wallet-day)**.

## C. Rolling decile vs fixed 121-wallet cohort (estimand mismatch — primary correction)

- **Verified (`cohort_M2_recurrence.py` block [2] vs `cohort_M_freeze.py`):** the forward result is produced by ranking wallets **anew each month** (dynamic top decile) and measuring the next month. It is **not** the fixed 121-wallet cohort.
- **Horizon error:** that figure is computed at the **4h** horizon (neutralized, day-weighted): top +5.72 vs field +1.28 = **+4.43 bp [+1.79, +6.75], 9/10 folds**. Recomputed at 8h with the same estimator: **+11.42 bp [+5.26, +17.04]**. The previous draft's "≈+4.5 bp gross at the 8-hour horizon" is wrong on both horizon (4h, not 8h) and on "gross" (these are neutralized, not raw).
- **Fixed 121, tested independently (this audit, validation period, neut 8h, wallet-day-weighted):** cohort mean +10.06 vs field −0.35 = **+10.41 bp (n = 93 with validation activity)**. This is the number to attribute to the 121; it is reported as exploratory (see D) and is not multiplicity-controlled.
- **Correction:** report the rolling-decile persistence and the fixed-121 cohort as **two separately computed analyses**; never attribute the dynamic-decile estimate to the fixed cohort.

## D. Historical validation status

- **Verified (ledger stages M1–M4):** the March–June window was examined repeatedly and informed later specification choices (cohort freeze horizon, cost model, matched-control design).
- **Correction:** label March–June as **historical validation / exploratory out-of-sample**, not untouched or confirmatory. State that only prospective data can confirm.

## E. 121-wallet threshold

- **Verified (`cohort_M_freeze.py` `K_PRIMARY=2`; `cohort_M2_recurrence.py` block [4]):** the cohort is wallets in the top decile in **≥2 of 6 training months** (121 wallets). Recurrence counts vs a binomial chance benchmark: ≥2 months 204 vs 184 expected (**p = 0.059**, does not clear 0.05); ≥3 months 48 vs 35 (**p = 0.017**, clears); ≥4 months 9 vs 5 (p = 0.066).
- **Correction:** state explicitly that **≥2 was chosen for breadth and statistical power** (121 wallets vs 28 at ≥3). Only the ≥3-month threshold cleared the chance benchmark. Do not imply all 121 are individually established repeat performers; the ≥3-month subset (28) is the significance-supported core.

## F. Strength-of-conclusion rewording

| Current | Replaced with |
|---|---|
| "wallet direction adds nothing" | "wallet direction did not improve performance in this specification" |
| "the state fully explains the edge" | "observable market-state variables explained most of the estimated advantage" |
| "the entire edge is the fade" | "no statistically resolved incremental return over the fade benchmark" |
| "not private information" | "no resolved evidence of information beyond observable reversal conditions" |
| "generic reversal" | "consistent with a short-horizon reversal pattern" |
| "LIVE UNDERPOWERED positive" | "a smaller incremental effect remains possible given the confidence interval and MDE" |

## G. Term-structure significance (avoid over-reading movements)

- **Verified (day-block bootstrap, this audit; `out/termstructure_ci.json`):** most coin×horizon entry-weighted means are not distinguishable from zero. Pooled: 1h −0.19 [−1.0, +0.6] … 8h −0.60 [−5.4, +3.9]; only 24h −6.26 [−16.7, +3.6] and **BTC 24h −6.37 [−12.9, −0.3]** are materially negative. The **HYPE 8h hump +2.96 [−6.6, +12.9]** does not exclude zero.
- **Correction:** present the term structure with day-block CIs and describe shape at the coin level as largely within noise except the negative 24h drift; do not treat the HYPE hump as an established effect.

## H. Which wallet set each downstream result uses (kept distinct in v2)

- Alpha-vs-fade, A/B/C/D, and the market-state residual are computed on the **train-ranked top decile** (99 with a since-corrected selection leak; 170 train-only after correction) — not the 121 recurrence cohort.
- Behavioral characterization, the per-wallet fade share, and the nested model use the **121 recurrence cohort**.
- These are related ("high-markout wallets") but distinct sets and are labelled separately.

## Numerical inconsistencies found and fixed

1. Forward-decile stated at 8h; it is 4h (+4.4). 8h value is +11.4. — corrected, both reported at their horizons.
2. Forward-decile called "gross"; it is neutralized, day-weighted. — corrected.
3. Rolling-decile estimate implicitly attributed to the fixed 121. — separated; fixed-121 validation number (+10.4 bp/8h) computed independently.
4. Alpha-vs-fade +1.00 is on the leaked 99-set; audit found the leak non-fatal for a difference-in-differences estimand but the point estimate is not on the clean 170/121 set. — labelled.

No result was altered to improve the narrative; the above are corrections of attribution, horizon, weighting, and wording. All figures for v2 are regenerated with neutral titles, day-block CIs where applicable, and estimator/weighting stated in captions.
