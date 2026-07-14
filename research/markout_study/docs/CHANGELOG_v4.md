# Change log — report v4 (one page)

## Title / scope
- Retitled: "Post-Entry Markouts of Position-Increasing Hyperliquid Taker Decisions." Executive summary now states closing fills are excluded from scoring, same-bar fills are aggregated, sub-hour execution markouts are unavailable, and the shortest horizon is 1h.

## Phase-1 corrections (verified against code; see docs/FINAL_AUDIT_NOTE.md)
1. Pre-entry sign convention: exact formula stated, axis relabelled, long/short worked examples; "signed change over preceding 8h" removed.
2. Long/short: corrected from "no large asymmetry" to raw-asymmetric-at-24h (drift) that shrinks after neutralization; new raw-vs-neut two-row figure.
3. Conditional relationship: fixed-quantile bins + day-cluster CI + pre-specified training linear slope (negative in all four coins, p(≥0) ≤ 0.03); "monotone" dropped for "generally declines".
4. Trade size: recomputed within coin×month; "impact and noise" removed; conclusion limited to "not associated with higher markout".
5. Recurrence: heuristic binomial replaced by a permutation null preserving monthly eligibility and slots (significant at ≥2/≥3/≥4).
6. Fixed-121: full inference added (point, CI, p, cost-adjusted, fade-adjusted, active/attrition, wallet-coin-days, coin concentration); kept separate from static and dynamic rankings.
7. "Net return" → "cost-adjusted under the assumed 6–9 bp schedule"; upper-bound claim removed; omitted costs listed.
8. Bootstrap documented as a calendar-day cluster bootstrap (independent days, 2,000 draws); 5-day block sensitivity for 24h noted.

## Phase-2 additions
- Effective-sample counts (334 calendar days explain wide CIs).
- New figure: next-month markout by prior-month rank decile (4h & 8h) + top-minus-field by month — shows a gradient, not only a top-decile effect.
- Readability: enlarged long/short, static-ranking, and behavioral panels (behavioral now clean grouped bars); consistent widths and coin colors.
- Self-contained PDF: full term-structure table, quantile tables, methodology, number-to-source map, and all figures embedded (no local-path references).

## Phase-3 wording
- Conservative throughout: "no statistically resolved incremental effect", "consistent with reversal exposure", "modest predictive persistence", "remains exploratory". Categorical claims removed.
