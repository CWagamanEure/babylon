# Fixed-cohort robustness

Validation period only (2026-03-01 to 06-30), 8-hour markout. Cost schedule BTC 8 / ETH 8 / SOL 10 / HYPE 14 bp round-trip per entry. Estimands (formulas in `docs/FIXED_121_ESTIMANDS.md`): A absolute (gross, cost-adjusted), B minus non-cohort field (drift-neutralized, no cost), C minus matched fade. All from `src/verify_v6.py` → `out/v6.json`. Values: point [low, high] p.

## Two questions, two primary weightings

- **Wallet quality — "are the selected wallets generally better than other wallets?"** Primary = **equal-wallet**.
- **Deployable activity — "would following the cohort's observed wallet-days beat the comparable field?"** Primary = **wallet-day** (portfolio rule in `docs/PORTFOLIO_RULE.md`; wallet-day and wallet-coin-day are related activity-weighted estimators, not independent confirmations).

## A–D inference by weighting

| | Equal-wallet | Wallet-day | Wallet-coin-day |
|---|---|---|---|
| A. Absolute gross (p>0) | +4.4 [−3.6, 13.2] p=0.15 | +11.4 [5.2, 18.0] p=0.001 | +12.0 [5.9, 17.9] p<0.001 |
| B. Absolute **cost-adjusted** (p>0) | −5.7 [−13.2, 2.9] p=0.92 | **+1.3 [−5.0, 7.6] p=0.34** | +2.0 [−3.9, 8.0] p=0.25 |
| C. Minus non-cohort field | +4.6 [−4.5, 15.0] p=0.17 | +9.8 [3.7, 15.8] p=0.002 | +10.5 [4.7, 16.4] p=0.001 |
| D. Minus matched fade | −3.9 [−11.8, 3.3] p=0.85 | +4.5 [−6.7, 16.4] p=0.23 | +3.8 [−7.7, 15.6] p=0.29 |

- **Absolute cost-adjusted return is not statistically resolved above zero under any weighting** (p = 0.34 / 0.92 / 0.25). Profitability after assumed costs is not established.
- The field-relative advantage (C) is resolved under the activity-weighted estimators but not under equal-wallet — the effect is concentrated in more active wallet-days rather than broadly established across all selected wallets.
- No incremental value over the matched fade (D) is resolved under any weighting.

## Training-clean subset (13 leak-driven of 121 removed → 108 wallets)

B: equal-wallet +2.0 [−5.2, 9.9] p=0.30; **wallet-day +11.1 [4.3, 17.5] p<0.001**; wallet-coin-day +11.6 [5.2, 17.7] p<0.001. The result is robust to the eligibility leak (Section `ELIGIBILITY_WINDOW_AUDIT.md`).

## Time-series sensitivity for B (wallet-day)

Moving-block bootstrap = overlapping candidate blocks of fixed length over the ordered day list; the last block is truncated to fill exactly N days; cohort, field and their cells resampled jointly; 2,000 draws.

| Method | B (bp) | 95% CI | p |
|---|--:|--:|--:|
| Calendar-day cluster | +9.8 | [+3.4, +15.9] | 0.001 |
| 7-day moving-block | +9.8 | [+2.1, +15.9] | 0.006 |
| 5-day moving-block | +9.8 | [+2.7, +15.7] | 0.004 |

By validation month: Mar +18.0, Apr +10.3, **May −8.2**, Jun +19.2. Leave-one-month-out B: +6.6 / +9.6 / +15.7 / +7.2 (dropping Mar/Apr/May/Jun) — positive in every case. The day-cluster p = 0.001 is mildly optimistic; the moving-block and one-month-out evidence resolve at p ≈ 0.004–0.006 and remain positive, so the effect is not an artifact of one month or of serial dependence, though one of four months is negative.

## Coin decomposition (wallet-day)

| Coin | A gross | B minus field | D minus fade | Active | Wallet-days |
|---|--:|--:|--:|--:|--:|
| BTC | +8.9 [3.5,14.4] | +7.1 [2.0,11.9] | −0.3 [−11.2,11.2] | 72 | 1,785 |
| ETH | +17.1 [9.2,25.1] | +17.0 [8.5,25.8] | +6.8 [−6.8,20.8] | 73 | 1,314 |
| SOL | +15.7 [7.8,24.0] | +13.6 [5.1,22.2] | +2.7 [−13.0,17.7] | 57 | 1,104 |
| HYPE | +8.8 [−6.4,23.2] | +7.5 [−8.4,24.1] | +6.7 [−20.2,37.3] | 74 | 1,608 |

Coin-balanced B (equal weight per coin) = **+11.3**; leave-one-coin-out B = BTC-out +11.9 / ETH-out +8.3 / SOL-out +9.6 / HYPE-out +11.1; excluding SOL, B = **+9.6**. The field-relative advantage is present in all four coins (interval excludes zero for BTC, ETH, SOL; HYPE positive but unresolved) and does **not** depend on SOL — it is a broad wallet-quality-versus-field pattern with ETH strongest, not a single-coin effect. No fade-adjusted coin (D) is resolved.
