# Change log — report v6 (one page)

Targeted technical cleanup. No new selectors, horizons, or subgroups. Phase-1 audit and all robustness tables completed before regenerating the PDF; every page visually inspected.

## Production / rendering
- Rebuilt with xelatex + Palatino (main) / Menlo (mono); all ≥ ≤ β ρ ≈ and math symbols render (Latin Modern lacked them). Removed stray `$…$` math that rendered literal dollar signs.
- Fixed the clipped appendix figure (consecutive images now stacked, widths reduced within margins). Summary table not split; page numbers and "Internal Research" footer on every page.
- Removed the BTC 24h significance star (day-cluster [−13.5, 0.0] and 5-day block [−13.0, +0.1] disagree at zero; both shown, no star).

## Leakage (Phase 2)
- Found: majors-fill count, taker share and median hold were computed whole-window (`hold_size_dist.py`); only training-entry count was training-scoped. Recomputed training-only: 1,557/1,694 (91.9%) still qualify; 108/121 recurring wallets clean. Field-relative result robust (clean-108 B wallet-day +11.1 [4.3,17.5] p<0.001). Cohort described as predominantly training-defined, not cleanly historical. `ELIGIBILITY_WINDOW_AUDIT.md`.

## Estimand / inference
- **Two pre-entry conventions named separately** (event-study ordinate "earlier price relative to entry, aligned in trade direction"; regressor "pre-entry return in trade direction"), each with a worked example.
- **Fixed-cohort reframed** as two questions: equal-wallet = wallet quality; wallet-day = deployable activity (wallet-day/wallet-coin-day are related, not independent confirmations). Portfolio rule stated; absolute figures labelled average markout statistics, not capital-constrained returns (`PORTFOLIO_RULE.md`).
- **Absolute inference added** (A gross and cost-adjusted, point/CI/p under all three weightings). Cost-adjusted absolute is **not resolved above zero under any weighting** (p = 0.34 / 0.92 / 0.25) — profitability after costs not claimed.
- **Time-series robustness**: overlapping 7-day and 5-day moving-block (defined correctly), by-month, leave-one-month-out; daily p=0.001 flagged mildly optimistic (moving-block p≈0.004–0.006). `FIXED_COHORT_ROBUSTNESS.md`.
- **Coin decomposition**: field advantage present in all four coins (ETH strongest), coin-balanced +11.3, ex-SOL +9.6 — corrects the prior "SOL-concentrated" framing.
- **Rolling uncertainty** on calendar time: 10 fold ICs, mean +0.11, 9/10 positive, sign test p=0.02, leave-one-month-out stable; decile gradient survives. `ROLLING_TIME_INFERENCE.md`.
- **Benchmark wording**: "execution effects cancel" → "coin, timestamp, horizon, pricing convention and assumed symmetric costs are matched"; explicit note that actual execution need not cancel; no BBO claim.
- **Recurrence interpretation** narrowed (recurs more than random reassignment; not skill/profit/optimal cutoff; ≥2-month is an operational coverage threshold).
- **Behavioral** reported entry-weighted and equal-wallet (agree); each variable given formula/lookback/sign/unit; trailing-extreme distance defined direction-aligned.
- **Removed** the orphan nested-model −0.0003 statistic (npz lacks the CV ICs for an interpretable table).
- Conclusion rewritten to the conservative standard.

## Deliverables
`report_v6.pdf` (14 pp), `report_v6.md`, `figs_v6/` (18), `technical_appendix.{md,pdf}` (3 pp), `docs/{FINAL_AUDIT_V6, ELIGIBILITY_WINDOW_AUDIT, FIXED_COHORT_ROBUSTNESS, ROLLING_TIME_INFERENCE, PORTFOLIO_RULE, CHANGELOG_v6}.md`. Recomputation `src/{eligibility_audit,verify_v6,fig_v6}.py` → `out/{eligibility_train.parquet,v6.json}`.
