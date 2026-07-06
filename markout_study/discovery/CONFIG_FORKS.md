# CONFIG_FORKS — degrees-of-freedom control

Every fork in the pipeline, its frozen primary, and at most two pre-registered sensitivities. Anything not here (or beyond two sensitivities) is **exploratory** and cannot set the headline conclusion. Sensitivities are reported as robustness, not as additional chances to pass a gate.

| # | Fork | Primary (frozen) | Sensitivity 1 | Sensitivity 2 |
|---|---|---|---|---|
| 1 | Coin set | BTC, ETH, SOL, HYPE | + next-N liquid perps (if bars exist) | — |
| 2 | Min episodes | 50 | 40 | 75 |
| 3 | Min active days | 30 | 40 | — |
| 4 | Min active months | 4 | 3 | — |
| 5 | Taker-share cutoff | none | ≥ 0.5 (copyability check only) | — |
| 6 | Hold cap | none (median ≥ 1 h) | median ≥ 2 h | — |
| 7 | Episode gap | 30 min | 15 min | 60 min |
| 8 | Episode termination | any reduction OR flip OR >gap | reduction ≥ 50% of peak | — |
| 9 | Entry price for copy | first-bar close after signal+latency | average build VWAP (descriptive) | — |
| 10 | Horizon bands | mid {1,2,4,8}, low {8,16,24,48} | — (bands are the object, not a fork) | — |
| 11 | Band aggregation | equal-wt mean of SD-standardized horizons | area under markout curve | — |
| 12 | Latency | 60 s | 5 s | 300 s |
| 13 | Cost schedule | {8,8,10,14} bp round-trip / episode | +50% (stress) | half (optimistic, reported not headline) |
| 14 | Shrinkage prior | normal–normal, reliability = active days | wider prior (more shrinkage) | — |
| 15 | Wallet×coin pooling | off unless power audit supports | on (if supported) | — |
| 16 | Recency treatment | none (equal-weight history) | exponential half-life = 90 d | — |
| 17 | Liveness rule | active in last 30 d | active in last 45 d | — |
| 18 | Concentration gate | coin ≤ 60% episodes; month ≤ 45% edge | coin ≤ 50% | — |
| 19 | Basket size | top 40 by copyability | top 30 | rank-weighted top 10–20% |
| 20 | Sizing | equal-wallet + wallet-day (both) | wallet-day with tighter caps | — |
| 21 | Public benchmark | frozen threshold reversal (see spec) | market-state regression model | — |
| 22 | Inference | month-block bootstrap + sign test | 5-day moving-block within-fold | — |
| 23 | Embargo | 0 (episodes short) | 1 month | — |

**Rules.** (a) The primary column is frozen before the first evaluation fold. (b) A gate is judged on the primary only; sensitivities show whether the verdict is stable, they do not create additional pass attempts. (c) If the primary fails a gate, the experiment stops (`STOP_RULES.md`) — sensitivities are not promoted to primary. (d) `[PENDING AUDIT]` numbers in `PREREGISTRATION.md` are frozen from the training-only power audit and added to the primary column at freeze time. (e) Total pre-registered configurations that touch the headline: **1 primary + ≤ 2 sensitivities per fork, reported as a robustness grid, not a search.**

## Fork-budget accounting

The purpose of this table is to make the multiple-comparison surface explicit and finite. The headline is a single number from the primary column. The robustness grid (sensitivities) is reported with the count of configurations shown, so a reader can see how many ways the result was stressed and that none were used to manufacture significance.
