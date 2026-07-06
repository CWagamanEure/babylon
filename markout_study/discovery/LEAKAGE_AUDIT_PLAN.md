# LEAKAGE_AUDIT_PLAN

The prior study's headline leak was whole-window eligibility (taker share, hold, fill count computed over train+test). This experiment fixes it structurally; this plan is the checklist that must pass before any result is reported.

## Invariant: everything used at cutoff C uses only `ts < C`

For every monthly cutoff C, the following are recomputed from training-only fills and must contain **no** information dated ≥ C:

1. **Eligibility** — episode count, active days, active months, median hold, all exclusion flags (liquidation/TWAP/wash/bot). Explicit check: a wallet's eligibility at C must not depend on its future activity or future holding behavior.
2. **Shrinkage fit** — the universe mean, per-band SD used for standardization, prior variance, and each wallet's posterior are estimated on `ts < C` only.
3. **Horizon standardization** — the cross-sectional SD used to standardize each horizon's markout is a training-only statistic, frozen per fold.
4. **Selection** — ranking and gates use only as-of-C scores.
5. **Public benchmark parameters** — any threshold/coefficients in the Gate-C strategy are fit on the first training window and frozen, or refit as-of C from training-only data; never fit on evaluation data.
6. **Cost/latency** — fixed constants, no data dependence.

## Forward-window hygiene

- Entry pricepoints are the first bar strictly after signal (and after signal+latency for copy); no endpoint lies in its own signal bar.
- Markout forward windows may extend past C for episodes near the boundary; those episodes' *outcomes* are evaluation data and must not feed back into selection at C. An episode is assigned to the evaluation month of its signal time, and its forward window is allowed to run into the next month (that is the return being measured), but its outcome never informs any as-of-C eligibility or score.
- Embargo: primary 0 (episodes are short and the entry decision uses no future data); a 1-month embargo is a pre-registered sensitivity to confirm boundary episodes do not drive results.

## Automated checks (must be coded into the pipeline, not just asserted)

- A per-fold assertion that every field feeding selection has max source-ts < C.
- A recomputation test: rebuild eligibility with a deliberately shifted cutoff and confirm membership changes only through genuinely prior information.
- A shuffle control: randomly permute wallet identities within each cutoff and confirm the ranking signal collapses (guards against an accidental identity leak).

## Reporting

The leakage audit result (pass/fail per check, per fold) is a required table in the output. No headline number is reported until all checks pass on all folds. This plan is itself audited by the design swarm.
