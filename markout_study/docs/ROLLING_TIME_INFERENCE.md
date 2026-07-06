# Rolling-ranking time-series inference

The dynamic monthly ranking has only ten adjacent-month forecasting folds. Calendar time is the independent dimension; thousands of wallet-month rows must not create artificially narrow uncertainty. All values from `src/verify_v6.py` → `out/v6.json`. Signal: neut_8h monthly wallet mean, wallet-day-weighted, wallets with ≥8 active days in the ranking month.

## Fold-level rank IC (Spearman of month-*m* rank vs month-*(m+1)* markout)

| Forecast month | 09-25 | 10-25 | 11-25 | 12-25 | 01-26 | 02-26 | 03-26 | 04-26 | 05-26 | 06-26 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Rank IC | +0.065 | +0.091 | +0.095 | +0.176 | +0.000 | +0.109 | +0.135 | +0.135 | +0.124 | +0.185 |

- Mean +0.112, median +0.116, standard deviation 0.051, n = 10 folds.
- **Positive in 9 of 10 folds** (one fold 0.000); sign test p = 0.022.
- Leave-one-month-out mean IC ranges **[+0.103, +0.124]** — dropping any single month leaves the mean essentially unchanged; no fold drives the result.
- Resampling / inference unit: adjacent-month folds (calendar time), one fold per month-pair. The sign test and fold dispersion, not a wallet-month-row bootstrap, carry the primary inference.

## Decile gradient

The next-month-markout-by-prior-decile gradient is monotone-increasing on the pooled folds and its shape survives leave-one-month-out: the top decile remains the highest and the bottom deciles remain below the field in every leave-one-month-out pooling. The gradient is a real cross-fold pattern, not a single-month artifact.

## Interpretation

The rolling ranking exhibits modest, temporally consistent one-month-ahead persistence (mean IC ≈ +0.11, 9/10 folds positive, sign test p = 0.02). With ten folds the evidence is suggestive rather than tightly resolved, and it speaks to rank ordering, not to profitability or incremental value over reversal (see the fixed-cohort fade-relative result).
