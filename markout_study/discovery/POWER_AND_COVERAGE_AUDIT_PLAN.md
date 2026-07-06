# POWER_AND_COVERAGE_AUDIT_PLAN

Run on the **training window only**, before the first evaluation fold. Its outputs freeze the `[PENDING AUDIT]` values and decide whether stages/bands are powered enough to keep. It is a gate on the design, not a result.

## A. Coverage tables (descriptive)

For the primary universe, report distributions (median, IQR, p10/p90) of:

1. episodes per wallet (total, and per band);
2. active days per wallet; active months per wallet;
3. **non-overlapping 24 h episodes** and **non-overlapping 48 h episodes** per wallet (episodes spaced ≥ the horizon apart, so forward windows do not overlap);
4. wallet × coin coverage (how many wallets have ≥ N episodes in ≥ 2 coins);
5. wallet × month coverage (episodes per wallet-month; how many wallet-months are empty);
6. universe size at each monthly cutoff (walk-forward feasibility — how many eval folds have ≥ 40 eligible wallets).

## B. Power / MDE analysis

- Per band, per sizing, estimate the **minimum detectable basket return** (MDE) at 80% power given: number of evaluation months, per-month basket-return SD, and the month-block inference. Report MDE in bp and compare to the assumed cost schedule and to a plausible edge (a few bp). If MDE ≫ a few bp for a band/sizing, that band/sizing is **blind by construction** and is reported as inconclusive, not as a null.
- Positive-control injection: inject a synthetic +X bp per-episode edge into a random subset of wallets and confirm the shrinkage + ranking + basket pipeline recovers it at the target horizon and sizing. If a realistic injected edge is not recovered, the instrument is blind and the design is revised before use (this is the powered-design obligation, not a re-run of a blind test).

## C. Freeze decisions produced

- Finalize `[PENDING AUDIT]`: min effective-N (active days) for the reliability gate; the 48 h retention decision (keep only if non-overlapping-48h coverage ≥ target and ≥ target candidate wallets qualify); liquidation/TWAP/wash/bot flag thresholds; whether wallet×coin partial pooling is identifiable (keep off unless per-coin effective N clears a threshold in a sufficient number of wallets).
- Decide the first evaluation month = first cutoff with ≥ 40 eligible wallets and ≥ the minimum coverage; and the number of evaluation folds available given the 11-month ceiling.

## D. Honest limits stated up front

The data is ~11 months and cannot be extended (API ceiling). A monthly walk-forward yields a **small number of evaluation folds** (order 6–9), and the low band (48 h) consumes calendar and will be the thinnest. The hierarchical model's richer effects (wallet×coin, recency) are likely under-identified and are excluded unless the audit shows otherwise. Where a band or sizing is underpowered, the pre-registered outcome is **inconclusive/underpowered**, and the write-up says so rather than reporting a null as evidence of absence. Conversely, an underpowered band does not license opening new forks — the powered bands and the basket-level test carry the headline.
