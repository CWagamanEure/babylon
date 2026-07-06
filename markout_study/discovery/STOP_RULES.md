# STOP_RULES — finite experiment

This experiment has a defined end. It stops at a negative write-up, a positive write-up, or an inconclusive/underpowered write-up. It does not loop by opening new forks after a primary failure.

## Stop and write up a NEGATIVE if, under the primary specification:

1. Neither the mid nor the low band produces a basket that clears **Gate B** (positive post-latency, cost-adjusted return, month-block interval excluding zero, robust to leave-one-out); or
2. **Gate A** is unstable — rank IC or decile gradient sign-inconsistent across folds; or
3. The result vanishes under **calendar-time (fold-level) inference** even if entry-level pooled statistics look significant; or
4. Performance is **dominated by one coin, month, or wallet** (leave-one-out flips the sign, or one month contributes > 45%); or
5. The signal **does not survive the primary latency** (60 s); or
6. **Gate C fails where make-or-buy is the deciding question** — the basket does not beat the frozen public strategy under matched implementation (this is a negative for the *wallet layer*, and is reported as such, distinct from #1's negative for profitability).

## Stop and write up INCONCLUSIVE/UNDERPOWERED if:

- The coverage/power audit shows MDE ≫ a plausible edge for the tested bands/sizings (blind by construction), and the positive-control injection is not recovered. Then the honest statement is "the available 11-month data cannot resolve this," and the design's power requirements are documented for a future, larger dataset — **not** a re-run of the blind instrument.

## Stop and write up a POSITIVE if:

- Gates A and B pass under the primary specification, robust across the pre-registered sensitivities, and the positive-control and leakage audits pass. Gate C is reported to say whether the wallet layer is necessary or whether the cheaper public strategy suffices.

## What is NOT allowed after a primary failure

- Opening new eligibility thresholds, horizon combinations, band aggregations, shrinkage priors, basket sizes, or scoring weights to search for a passing configuration.
- Promoting a sensitivity that happened to pass into the primary.
- Reporting an exploratory configuration as the headline.

If a primary failure genuinely suggests a *different* hypothesis worth testing, that is a **new pre-registration** with its own fork budget and its own out-of-sample data or clearly-labelled exploratory status — not a continuation of this one.

## Required post-run audits (per project convention)

After the run, two independent adversarial audit swarms, distinct from the analysis:

- **Steelman-the-positive** (argue any negative is really a real, underpowered signal — CI, MDE, cross-unit sign test);
- **Prosecute-the-positive** (argue any positive is multiple-comparisons, non-independent folds, one-coin/one-month leakage, or shared with the public benchmark).

Both are run before any verdict is finalized, and their findings are recorded in the findings ledger.
