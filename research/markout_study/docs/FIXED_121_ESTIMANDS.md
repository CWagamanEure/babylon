# Fixed-121 cohort — estimands and results

The fixed cohort is the 121 wallets in the training top decile in ≥2 of 6 training months (neut_8h, wallet-day weighting). All results below are **validation period only** (2026-03-01 to 06-30). Cost schedule: BTC 8, ETH 8, SOL 10, HYPE 14 bp round-trip, applied **per scored entry** (one round-trip charge per decision — conservative, since the markout is a one-way price move). Costs exclude latency slippage, size-dependent impact, funding, partial execution and overlapping-capital constraints.

## Formulas

Let `r` = post-fill 8-hour markout (raw, gross price move), `ñ` = drift-neutralized 8-hour markout, `c(coin)` = cost schedule, and `fade = −sign(trailing 8h move) · r` at the identical timestamp.

- **A. Absolute cohort return.** `A_gross = E[r | cohort]`; `A_costadj = E[r − c(coin) | cohort]`. What a copier of the cohort's decisions would capture, gross and after the assumed cost schedule.
- **B. Cohort minus non-cohort field.** `B = E[ñ | cohort] − E[ñ | non-cohort field]`. The comparison field **excludes the 121 wallets**. No cost is applied — this is a relative descriptive measure, not a long-cohort/short-field strategy, so subtracting a round-trip cost from it would be incorrect (the v4 "cost-adjusted +3.5" did exactly that and is retracted).
- **C. Cohort minus matched fade.** `C = E[r | cohort] − E[fade | cohort]`, both at the cohort's own entry timestamps so execution effects cancel. This is the incremental value of trading in the wallet's direction versus a mechanical reversal rule.

Weightings (frozen): **wallet-day** (combine coins within a wallet-day, then equal-weight wallet-days) — primary; **equal-wallet** (each active wallet's validation mean, equal-weighted); **wallet-coin-day** — sensitivity. Bootstrap: calendar-day cluster (day schemes) / wallet cluster (equal-wallet), cohort and field resampled jointly, 2,000 draws.

## Results

| Metric | Wallet-day (primary) | Equal-wallet | Wallet-coin-day (sensitivity) |
|---|--:|--:|--:|
| Selected wallets | 121 | 121 | 121 |
| Active wallets | 97 | 97 | 97 |
| Calendar days | 122 | 122 | 122 |
| Wallet-days | 4,286 | 4,286 | 4,286 |
| Wallet-coin-days | 5,811 | 5,811 | 5,811 |
| **A. Absolute gross** (bp) | +11.4 | +4.4 | +12.0 |
| **A. Absolute cost-adjusted** (bp) | +1.3 | −5.7 | +2.0 |
| **B. Minus non-cohort field** (bp) | **+9.8** | +4.6 | +10.5 |
| B 95% CI | [+3.4, +15.9] | [−4.3, +14.6] | [+4.6, +16.5] |
| B p-value | 0.001 | 0.169 | 0.001 |
| **C. Minus matched fade** (bp) | +4.5 | −3.9 | +3.8 |
| C p-value | 0.25 | 0.16 | 0.26 |

## Reading

- The field-relative difference (B) is positive and resolved under the two day-based weightings (+9.8 / +10.5, p=0.001) but **falls to +4.6 (p=0.169, interval includes zero) under equal-wallet weighting**, which does not reward the cohort's defining cross-coin breadth. The headline is therefore weighting-dependent.
- The absolute cost-adjusted return is small-positive under the day schemes (+1.3 / +2.0) and **negative under equal-wallet (−5.7)**.
- The incremental value over a matched mechanical fade (C) is **not statistically resolved under any weighting** (p = 0.16–0.26).

## Concentration diagnostics (wallet-day, B)

- By coin (cohort neut_8h mean): BTC +2.2, ETH +6.0, **SOL +12.5**, HYPE −2.4 — the field advantage concentrates in SOL.
- By month: 2026-03 +11.0, 04 +4.1, **05 −8.6**, 06 +4.6 — one of four validation months is negative.
- Largest single wallet has a validation mean of +332.7 bp; **excluding it, B = +9.7** (essentially unchanged) — not driven by one wallet.

Diagnostics only; the cohort is not re-selected on validation performance.
