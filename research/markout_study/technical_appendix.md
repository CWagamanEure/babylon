---
title: "Technical Appendix — Markout Study"
subtitle: "Number-to-source map, audit trail, and reproducibility"
author: "Quantitative Research — Internal"
date: "2026-07-05 · Version 6 · Internal Research"
geometry: margin=1in
fontsize: 10pt
header-includes:
  - \usepackage{fancyhdr}
  - \pagestyle{fancy}
  - \fancyhf{}
  - \fancyfoot[C]{\thepage}
  - \fancyfoot[L]{\small Internal Research}
  - \fancyfoot[R]{\small Technical Appendix · v6}
  - \renewcommand{\headrulewidth}{0pt}
---

## 1. Number-to-source map

Every headline number maps to the script that produces it and the output it is read from.

| Claim | Value | Script | Output |
|---|---|---|---|
| Universe | 7,332,013 entries / 32,949 wallets | `build_entries.py` | `out/entries/part_*.parquet` |
| Cohort | 1,694 wallets / 812,616 entries | `cohort_K_{define,price}.py` | `out/cohort_K_entries.parquet` |
| Effective sample | 334 days / 179,402 wallet-days / 252,223 wallet-coin-days | `verify_v4.py` | `out/v4.json` |
| Cost schedule | BTC 8 / ETH 8 / SOL 10 / HYPE 14 bp round-trip | `mkcommon.py` (`COST_BPS`) | — |
| Term-structure table + CI | Appendix A | `verify_v2.py` | `out/termstructure_ci.json`, `out/core_markout_table.md` |
| Long/short raw vs neut | BTC 24h raw −23.4/+17.2, neut −0.4/−3.4 | `verify_v4.py` | `out/v4.json` |
| Event study | pre-entry +18 to +33 bp | `pi_compute.py` | `out/eventstudy.json` |
| Conditional pooled slope | −0.058 [−0.108, −0.018], n=590,910 | `verify_v5.py` | `out/v5.json` |
| Size within coin-month | no increase with size | `verify_v4.py` | `out/v4.json` |
| Static ρ (canonical) | Pearson +0.00 / Spearman +0.02, n=936 | `verify_v5.py` | `out/v5.json` |
| Rolling decile / IC | top−field +4.0@4h / +10.3@8h; IC +0.093 [+0.061,+0.126] | `cohort_M2_recurrence.py`, `verify_v4.py` | `out/v4.json` |
| Recurrence train-only | ≥2 121/88.7 · ≥3 27/8.3 · ≥4 5/0.5 (p<0.001) | `verify_v5.py` | `out/v5.json` |
| Recurrence full (exploratory) | ≥2 213/185 · ≥3 72/35 · ≥4 25/5 | `verify_v5.py` | `out/v5.json` |
| Fixed-121 A/B/C × 3 weightings | see report §9 table | `verify_v5.py` | `out/v5.json` |
| 24h day-cluster vs 5-day block | BTC [−13.5,0.0] vs [−13.0,+0.1] | `verify_v5.py` | `out/v5.json` |
| Top-decile gross / cost-adj / fade-adj | +14.0 [+5.4,+22.8] / +7.1 / +1.0 [−10.8,+13.7] p=0.44 | `cohort_M2_deploy.py` | ledger |
| Market-state residual + MDE | −1.3 [−15.6,+13.0] / +5.9 [−5.5,+17.7]; MDE 11–16 | `cohort_M4_residual.py` | ledger |
| Nested incremental IC | −0.0003 | `cohort_P2_freeze_models.py` | `out/cohort_P2_models.npz` |
| Behavioral (dir-aligned medians) | recurring vs rest: signed −73/−11, abs 168/131, stretch 308/199, vol 23/19 | `verify_v5.py` | `out/v5.json` |
| Winner's-curse OOS | −28.7 bp | `oos_persistence.py` | ledger |

## 1b. v6 robustness objects

| Object | Value | Script | Output |
|---|---|---|---|
| Eligibility leak (train-only recompute) | 1,557/1,694 still qualify; 108/121 clean | `eligibility_audit.py` | `out/eligibility_train.parquet` |
| Fixed-121 A/B/C/D × 3 weightings | see report §9 | `verify_v6.py` | `out/v6.json` |
| Absolute cost-adjusted p(>0) | 0.34 / 0.92 / 0.25 | `verify_v6.py` | `out/v6.json` |
| Clean-108 subset B (wallet-day) | +11.1 [4.3,17.5] p<0.001 | `verify_v6.py` | `out/v6.json` |
| B moving-block (7d / 5d) | +9.8 p=0.006 / p=0.004 | `verify_v6.py` | `out/v6.json` |
| B by coin / coin-balanced / ex-SOL | 7.1/17.0/13.6/7.5 · 11.3 · 9.6 | `verify_v6.py` | `out/v6.json` |
| Rolling fold ICs (10) / sign-test | mean +0.11, 9/10 pos, p=0.02 | `verify_v6.py` | `out/v6.json` |
| Behavioral equal-wallet | signed −81/−9, abs 178/133, stretch 314/196 | `verify_v6.py` | `out/v6.json` |

## 2. Audit trail

v6 corrections (eligibility leak, absolute-return inference, weighting reframe, portfolio rule, moving-block, coin decomposition, rolling fold inference, behavioral unit, nested-statistic removal): `docs/FINAL_AUDIT_V6.md`, with supporting tables in `docs/ELIGIBILITY_WINDOW_AUDIT.md`, `docs/FIXED_COHORT_ROBUSTNESS.md`, `docs/ROLLING_TIME_INFERENCE.md`, `docs/PORTFOLIO_RULE.md`. Prior rounds: `docs/FINAL_AUDIT_V5.md`, `docs/FIXED_121_ESTIMANDS.md`, `docs/RECURRENCE_TRAIN_VS_FULL.md`, `docs/CHANGELOG_v2.md`, `docs/CHANGELOG_v4.md`, `docs/FINDINGS_LEDGER.md`.

## 3. Reproducibility

Run order (RAM-safe on an 8 GB box; one heavy job at a time; `POLARS_MAX_THREADS` set to 3 or fewer):

1. `build_entries.py` -> `out/entries/part_*.parquet`
2. `cohort_K_define.py`, `cohort_K_price.py` -> `out/cohort_K_entries.parquet`
3. `cohort_M_freeze.py` -> `out/cohort_M_frozen.{txt,parquet}`
4. `pi_compute.py` (heavy, bar-pricing) -> `out/eventstudy.json`, `out/entry_features.parquet`
5. `verify_v2.py` -> `out/termstructure_ci.json`, `out/core_markout_table.md`
6. `verify_v4.py`, `verify_v5.py` (light) -> `out/v4.json`, `out/v5.json`
7. `fig_v4.py`, `fig_v5.py` -> `figs_v5/*.png`
8. `pandoc report_v5.md --pdf-engine=xelatex -o report_v5.pdf`

Inputs: 5-minute candle closes and cand2 taker fills. No BBO/order-book data is available, so execution-quality markout (fill-to-mid, spread, impact, adverse selection) is not computable and is stated as a limitation.
