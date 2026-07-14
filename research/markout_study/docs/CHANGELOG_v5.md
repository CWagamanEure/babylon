# Change log — report v5 (one page)

Final defensibility pass. No new selectors, horizons, or strategy variants; corrections only. Phase-1 audit completed before regenerating the PDF (`docs/FINAL_AUDIT_V5.md`, `docs/FIXED_121_ESTIMANDS.md`, `docs/RECURRENCE_TRAIN_VS_FULL.md`).

## Estimator / analysis corrections
1. **Costs** — one canonical table (BTC 8 / ETH 8 / SOL 10 / HYPE 14 bp round-trip, per scored entry). "Net" removed; "cost-adjusted under the assumed schedule" throughout; not called a bound; omitted-cost list stated.
2. **Fixed-121 economics** — retracted the invalid step of subtracting cost from the cohort-minus-field difference. Now three estimands: A absolute (gross + cost-adjusted), B minus non-cohort field (drift-neutralized, no cost), C minus matched fade. Field confirmed to exclude the 121.
3. **Fixed-121 weighting** — reported under wallet-day (primary), equal-wallet, and wallet-coin-day (sensitivity). B = +9.8 / **+4.6 (p=0.169)** / +10.5; the advantage is not resolved under equal-wallet. Concentration diagnostics added (SOL-driven; May negative; drop-top-wallet unchanged).
4. **Recurrence** — split into training-only (six months, the cohort-justifying test; ≥2/≥3/≥4 all p<0.001) and full-sample (exploratory).
5. **Event study** — removed the "exhaustion" claim; the normalized curve supports only "prices moved against the eventual trade direction before entry."
6. **Conditional slope** — pooled model with coin + month fixed effects and volatility control, day-cluster inference: −0.058 [−0.108, −0.018]. Per-coin slopes demoted to heterogeneity checks; two-sided CI vs one-sided p stated; no claim each coin is individually established.
7. **Bootstrap** — described as a calendar-day cluster bootstrap that preserves contemporaneous, not serial, dependence; 5-day moving-block reported for 24h (BTC now marginal, interval reaches zero).

## Figure / definition corrections
8. Behavioral panel relabelled: the 175/151/72 values are the **absolute pre-entry 8h move**, not markout.
9. Pullback made direction-aligned ("distance from the relevant trailing extreme"); recurring 308 vs rest 199 bp; long/short available separately.
10. Static correlation reconciled to one canonical analysis: Pearson +0.00 / Spearman +0.02, n=936.
11. Fixed-cohort prose replaced by a 3-weighting × 3-estimand table plus a forest figure.

## Editorial / production
12. Executive summary separates the four objects (aggregate, dynamic ranking, fixed cohort, benchmark-adjusted value); conclusion uses the conservative standard.
13. Number-to-source map and correction log moved to a separate **technical_appendix.pdf**; the main report contains no local paths.
14. Professional metadata (title, author, date, version, "Internal Research"), page numbers (footer), Palatino typesetting via xelatex; no empty trailing pages.
15. Figures enlarged and consistent; "net" removed from all figure labels; error-bar/inference units stated in captions.

## Deliverables
`report_v5.pdf` (14 pp), `report_v5.md`, `figs_v5/`, `technical_appendix.{md,pdf}`, `docs/{FINAL_AUDIT_V5,FIXED_121_ESTIMANDS,RECURRENCE_TRAIN_VS_FULL,CHANGELOG_v5}.md`. Recomputations: `src/verify_v5.py` -> `out/v5.json`; figures `src/fig_v5.py`.
