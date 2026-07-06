# EXPECTED_OUTPUTS — tables and figures the run will produce

All headline outputs are fold-level (per evaluation month) with month-block inference. Entry-level pooled statistics appear only as descriptive appendices. Empty/placeholder shells are created at design time so the analysis fills known slots (prevents post-hoc output selection).

## Tables

- **T1 Coverage audit** — episodes/wallet, active days, non-overlapping 24h/48h episodes, wallet×coin, wallet×month, universe size per cutoff. (Freezes `[PENDING AUDIT]`.)
- **T2 Power/MDE** — per band × sizing MDE vs cost vs plausible edge; positive-control recovery.
- **T3 Leakage audit** — pass/fail per check per fold.
- **T4 Selection summary** — per cutoff: basket size, turnover, attrition, coin/month concentration.
- **T5 Gate A** — per-fold rank IC, mean/median/sd, sign test, decile-gradient table (both bands).
- **T6 Gate B** — basket absolute gross / delayed / cost-adjusted return, per month and pooled month-block CI, both sizings, leave-one-out (wallet/coin/month).
- **T7 Gate C** — basket vs frozen public benchmark per month, difference CI, orthogonal-component decomposition.
- **T8 Robustness grid** — primary vs the ≤2 sensitivities per fork (`CONFIG_FORKS.md`), showing verdict stability.
- **T9 Archetype table** (only if A+B pass) — behavioral classification, no future returns used.

## Figures

- **F1** Decile gradient: next-month band return by prior-month copyability decile, both bands, fold-level CIs.
- **F2** Rank-IC by fold (bar per month + mean line + sign test).
- **F3** Basket cumulative return, wallet-day sizing, with the frozen public benchmark overlaid (Gate B and C on one axis).
- **F4** Per-coin and per-month decomposition of the basket return (concentration check).
- **F5** Latency sensitivity: basket cost-adjusted return at 5 s / 60 s / 300 s.
- **F6** Cost sensitivity: return at primary / +50% / half schedule.
- **F7** Book utilization / capacity: fraction of signals taken, max concurrent exposure, capital-dropped episodes.

## Headline statement template (filled after run, not before)

> Under the primary specification, the walk-forward [mid/low]-band basket had a cost-adjusted, post-latency return of **X bp/month [CI]** (Gate B: pass/fail), a rank IC of **Y [CI]** across **n** folds (Gate A: pass/fail), and **beat / did not beat** the frozen public reversal strategy by **Z bp [CI]** (Gate C). Verdict: [positive / negative for profitability / negative for the wallet layer / inconclusive-underpowered], stable across [k] pre-registered sensitivities.

No headline is written until leakage (T3) and power (T2) audits pass and both post-run audit swarms have reported.
