# Eligibility-window audit (Part II leakage check)

The cohort is defined by four eligibility variables. Their computation windows were audited against source (`src/hold_size_dist.py`, `src/cohort_K_define.py`) and recomputed on training data only (`src/eligibility_audit.py` → `out/eligibility_train.parquet`).

## Windows

| Eligibility variable | Previous window | Correct window | Recomputed train-only pass rate | Changed wallets |
|---|---|---|---|---|
| Majors-fill count ≥ 200 | whole (train+test) | training only | 1,694 / 1,694 | 0 |
| Taker share ≥ 0.70 | whole (train+test) | training only | 1,684 / 1,694 | 10 |
| Median hold ∈ [1 h, 24 h] | whole (train+test) | training only | 1,565 / 1,694 | 129 |
| Training entries ≥ 200 | training only ✓ | training only | 1,694 / 1,694 | 0 |

Source: `hold_size_dist.py` line 7 states the hold/size features are "whole-window (train+test)"; `n_train` is training-scoped. So three of four variables used validation-period behavior for inclusion.

## Impact

- Applying the same thresholds to training-only variables, **1,557 of 1,694 (91.9%)** cohort wallets still qualify; **137 (8.1%) were leak-driven inclusions**, almost all through the median-hold filter.
- Of the 121-wallet recurring cohort, **108 are training-clean and 13 are leak-driven**.
- Aggregate Part I is immaterially affected: pooled 8-hour markout is −0.59 bp (full cohort) vs −1.04 bp (training-clean subset).
- The field-relative fixed-cohort result is robust to the leak: restricting the recurring cohort to its 108 training-clean members gives B (wallet-day) = **+11.1 bp [+4.3, +17.5], p < 0.001**, versus +9.8 bp for the full 121 — the leak did not inflate the estimate.

## Statement of scope

Because median hold, taker share and fill count were computed over the whole window, the cohort is **not described as cleanly historical**; it is described as predominantly training-defined (91.9%) with a documented leak whose removal does not change the conclusions. A fully training-only rebuild list is saved (`out/cohort_K_trainonly.txt`) and the robustness of every headline is reported against it.
