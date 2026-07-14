# Recurrence — training-only vs full-sample permutation

The 121-wallet cohort was selected from the **six training months**. Only the training-only recurrence result may justify that construction; the full 11-month version is exploratory because four of its months are the validation window used elsewhere.

## Permutation null

For each month, top-decile membership is a random subset of that month's eligible wallets (≥8 active days) of the observed slot count, drawn independently across months. This preserves: each month's eligible wallet set; the top-decile slot count per month; each wallet's number of eligible months (a wallet can only be drawn in months it is eligible); and the month structure. Signal = neut_8h monthly wallet mean. 2,000 permutations. Observed = wallets in the top decile in ≥K months.

## Training-only (6 months) — justifies the cohort

| Threshold | Observed | Null mean | p |
|---|--:|--:|--:|
| ≥2 months | 121 | 88.7 | < 0.001 |
| ≥3 months | 27 | 8.3 | < 0.001 |
| ≥4 months | 5 | 0.5 | < 0.001 |

Top-decile recurrence over the training window exceeds the permutation null at every threshold. (The ≥2-month count of 121 equals the cohort size by construction — the cohort is defined as this set — so the test's role is to show that 121 is well above the 89 expected by chance.)

## Full-sample (11 months) — exploratory

| Threshold | Observed | Null mean | p |
|---|--:|--:|--:|
| ≥2 months | 213 | 185.4 | 0.0005 |
| ≥3 months | 72 | 34.9 | < 0.001 |
| ≥4 months | 25 | 5.0 | < 0.001 |

Consistent in direction and significance, but this window overlaps the validation period and is reported as exploratory. Validation-period recurrence is **not** used to justify the training-selected cohort.
