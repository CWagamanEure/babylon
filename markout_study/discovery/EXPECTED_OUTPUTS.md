# EXPECTED_OUTPUTS — tables and figures the run will produce

All headline outputs are fold-level (per evaluation month) with month-block inference. Entry-level pooled statistics appear only as descriptive appendices. Empty/placeholder shells are created at design time so the analysis fills known slots (prevents post-hoc output selection).

## Tables

- **T1 Coverage audit** — episodes/wallet, active days, non-overlapping 24h/48h episodes, wallet×coin, wallet×month, universe size per cutoff. (Freezes `[PENDING AUDIT]`.)
- **T2 Power/MDE** — per band × sizing MDE vs cost vs plausible edge; positive-control recovery.
- **T3 Leakage audit** — pass/fail per check per fold.
- **T4 Selection summary** — per cutoff: basket size, turnover, attrition, coin/month concentration.
- **T5 Gate A (verdict)** — per-fold `Δ_relative` (selected−field Yband) + the sign test (F, #positive, k(F), exact p) = the sole ranking verdict. Mid band only.
- **T5b Gate A (absolute, reported separately)** — per-fold `A_selected` = mean over complete selected wallets of `Aband=¼Σ_h Mbar` in raw bp (positive/negative), **plus the selected raw mean at each of 1/2/4/8 h** (so a one-horizon effect can't hide in the band average). Never merged into the verdict.
- **T5c Gate A corroboration (descriptive)** — rank IC by fold; all-ten-decile table + pooled month-equal decile Spearman (sparse months marked "sparse/unavailable"); leave-one-wallet/-coin/-month; **lag-one autocorrelation of `Δ_relative,m` and of the sign sequence** (independence limitation). All descriptive — cannot veto/rescue the verdict. Selected/field activity + 4-of-4 completeness rates reported in the attrition table.
- **T6 Gate B** — basket absolute gross / delayed / cost-adjusted return, per month and pooled month-block CI, both sizings, leave-one-out (wallet/coin/month).
- **T7 Gate C** — basket vs frozen public benchmark per month, difference CI, orthogonal-component decomposition.
- **T8 Robustness grid** — primary vs the ≤2 sensitivities per fork (`CONFIG_FORKS.md`), showing verdict stability.
- **T9 Archetype table** (only if A+B pass) — behavioral classification, no future returns used.

## Figures

- **F1** Decile gradient: next-month Yband by prior-month gross-score (θ̂) decile, mid band; per-month + pooled month-equal decile curve.
- **F2** Rank-IC by fold (bar per month + mean line + sign test).
- **F3** Basket cumulative return, wallet-day sizing, with the frozen public benchmark overlaid (Gate B and C on one axis).
- **F4** Per-coin and per-month decomposition of the basket return (concentration check).
- **F5** Latency sensitivity: basket cost-adjusted return at 5 s / 60 s / 300 s.
- **F6** Cost sensitivity: return at primary / +50% / half schedule.
- **F7** Book utilization / capacity: fraction of signals taken, max concurrent exposure, capital-dropped episodes.

## Headline statement template (filled after run, not before)

> **Locked retrospective (not confirmatory).** Under the frozen Gate-A specification on the mid {1,2,4,8} h band, the selected-minus-field markout (`Δ_relative`) was positive in **[#]/[F]** calendar-month folds (sign-test p = **[p]**, threshold k(F)=**[k]**): **[PASS / FAIL / INCONCLUSIVE]**. Selected wallets' absolute gross markout (`A_selected`) was **[+/− X bp]** (reported separately; does not affect the ranking verdict). Corroboration: rank IC **[Y]**, pooled decile Spearman **[·]** (descriptive only). Because this tape was extensively explored, a PASS is suggestive locked-retrospective evidence, not confirmation; deployment (Gate B) remains sealed.

No headline is written until leakage (T3) and power (T2) audits pass and both post-run audit swarms have reported.
