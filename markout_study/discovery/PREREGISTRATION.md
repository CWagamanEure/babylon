# PRE-REGISTRATION — wallet-discovery experiment

Frozen before any data is touched. Values marked **[PENDING AUDIT]** are finalized from the coverage/power audit (`POWER_AND_COVERAGE_AUDIT_PLAN.md`) run on the training window *only*, then frozen; they are not tuned on evaluation data. Anything not listed here is either a pre-registered sensitivity (`CONFIG_FORKS.md`) or exploratory (cannot set the headline).

## 0. Primary hypothesis

There exists a walk-forward wallet-selection rule whose next-month basket, under realistic latency and costs, has an absolute return whose month-block interval excludes zero (Gate B), and — separately — that beats a frozen public market-state strategy under matched implementation (Gate C). We do not assume the sign; the gates decide.

## 1. Universe (frozen)

Coins: {BTC, ETH, SOL, HYPE}. At each monthly cutoff C, using only fills with `ts < C`:

- ≥ 50 position-building episodes;
- ≥ 30 active days (days with ≥1 scored episode);
- ≥ 4 distinct active months;
- median episode hold ≥ 1 h, no upper cap;
- exclusion flags off: liquidation-origin, TWAP/system flow, wash, bot, mechanical-slicer (definitions in `EPISODE_SPEC.md` §Exclusions).

No taker-share cutoff. All variables computed as-of C from training-only fills.

## 2. Episode (frozen — full rules in EPISODE_SPEC.md)

Same wallet/coin/direction; same-direction additions within a 30-min rolling gap extend the episode; the episode terminates at the first of (a) >30-min same-direction gap, (b) any position reduction, (c) direction flip. Signal time = first observable position increase. Primary object = **first-entry markout**; average-build markout produced as descriptive only.

## 3. Horizon bands and aggregation (frozen)

- Mid band: {1, 2, 4, 8} h. Low band: {8, 16, 24, 48} h.
- Frozen aggregation per band: **equal-weighted mean of per-horizon markouts, each standardized by that horizon's training-window cross-sectional SD** (so 48 h does not dominate by magnitude). No horizon weights are tuned.
- Bands are scored and gated **separately**; there is no "best band per wallet."
- 48 h retention rule: the low band is retained only if the coverage audit shows median non-overlapping 48 h episodes per candidate wallet ≥ **[PENDING AUDIT, target ≥ 8]** and ≥ **[PENDING AUDIT, target ≥ 20]** candidate wallets meet it; otherwise the low band caps at 24 h and 48 h is reported descriptively only.

## 4. Scores (frozen)

Per wallet, per band, at each cutoff:

- **Information score** = band-aggregate of **gross** first-entry markout (no latency, no cost). Used for discovery, decile gradient, archetypes.
- **Copyability score** = band-aggregate of markout under the frozen copy rule: entry at the close of the first 5-min bar with `ts ≥ signal + 60 s` detection latency; round-trip cost {BTC 8, ETH 8, SOL 10, HYPE 14} bp applied once per episode. Used for deployment selection and Gates B/C.

Latency assumption 60 s is primary (sensitivities 5 s, 300 s — `CONFIG_FORKS.md`).

## 5. Wallet-quality estimation (frozen)

Empirical-Bayes / normal–normal shrinkage:

- Aggregate episodes to **wallet-day** band-scores first; the wallet's observation set is its wallet-days.
- Estimate wallet mean and its uncertainty; **reliability (effective sample) is the count of active days, not trades**; shrink each wallet toward the universe (per-band) mean with weight increasing in active days.
- Parsimonious model: overall wallet effect + horizon-band effect. **Wallet-by-coin partial pooling is added only if the power audit supports it** (`POWER_AND_COVERAGE_AUDIT_PLAN.md`); wallet-by-coin-by-recency interactions are excluded a priori.
- Reported per wallet: shrunk expected return (both scores), posterior SD, effective N (active days), P(expected return > 0), concentration by coin/month/episode.

## 6. Continuous selection (frozen)

At each month-end, using only prior data: recompute eligibility, rebuild episodes, refit shrinkage, produce both scores. **Primary selection rule:** the **top 40 wallets by copyability score** (low band unless band choice is itself the tested axis — both bands run) subject to gates: reliability (≥30 active days, ≥4 months, effective N ≥ **[PENDING AUDIT]**) and concentration (no single coin > 60% of the wallet's episodes; no single month contributing > 45% of its estimated edge). Ties broken by posterior P(>0). No "top decile twice." One primary rule; the rank-weighted top-10–20% variant is a pre-registered sensitivity.

## 7. Basket evaluation and sizing (frozen — rule in PORTFOLIO_AND_COST_RULE.md)

Two sizings, both reported every month: **equal-wallet** (primary for the wallet-quality reading) and **wallet-day deployable** (primary for the deployment reading; exact capital rule frozen in `PORTFOLIO_AND_COST_RULE.md`). Metrics per `EXPECTED_OUTPUTS.md`. Inference: month is the independent unit; month-block bootstrap + sign test; leave-one-month-out and leave-one-coin-out reported. No entry-level pooled CI as a headline.

## 8. Co-primary gates (frozen thresholds)

- **Gate A — ranking validity.** Next-month rank IC (copyability score vs realized next-month band return, wallet-day): mean IC > 0 with month-block 95% interval excluding 0 **and** sign test positive in ≥ ⌈2/3⌉ folds **and** a monotone-in-direction decile gradient (top-two deciles > bottom-two, no sign inversion in the middle beyond noise).
- **Gate B — absolute deployment value.** Selected basket copyability return (post-latency, cost-adjusted) > 0 with month-block 95% interval excluding 0 under the **wallet-day** sizing, **and** robust to leave-one-out: no single wallet, coin, or month flips the sign, and no single month contributes > 45% of the total.
- **Gate C — make-or-buy.** Basket copyability return minus the frozen public market-state strategy (`PUBLIC_BENCHMARK_SPEC.md`), matched implementation, > 0 with month-block 95% interval excluding 0. Gate C failure ⇒ wallet layer unnecessary, not unprofitable.

A "pass" headline requires A and B. C determines whether the wallet layer is worth its added implementation cost over the public signal; it is reported regardless of A/B outcome.

## 9. Kill rules (see STOP_RULES.md)

Finite experiment. Stop and write up the negative if, under the primary specification: neither band's basket clears Gate B; or Gate A is unstable (IC/gradient sign-inconsistent); or the result vanishes under calendar-time (fold-level) inference; or it is dominated by one coin/month/wallet; or it dies under the primary latency; or it fails Gate C where make-or-buy is the deciding question. **A failed primary specification is not answered by opening new thresholds, horizon combinations, or scoring weights.**

## 10. Exit optimization (deferred)

Not built until Gates A and B clear on entry selection. If they clear: a separate nested walk-forward over a frozen fixed-horizon family {1,2,4,8,16,24,48} h, archetype-level before wallet-specific, preferring stable plateaus over isolated peaks. Not part of this pre-registration's headline.

## 11. What can move the headline

Only the single primary configuration above and the ≤ 2 pre-registered sensitivities per fork in `CONFIG_FORKS.md`. Everything else is exploratory and reported as such. The `[PENDING AUDIT]` values are frozen from a training-only coverage/power audit before the first evaluation fold and never revised on evaluation data.
