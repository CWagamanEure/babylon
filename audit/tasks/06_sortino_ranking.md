# Audit 06 — Sortino / ranking math & stability  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/06_sortino.md`.

## Scope
Sortino is the ranking statistic. It was already unstable (0→+77 across transitions) and had an
EPS-explosion bug. Verify the fixed version is numerically sound and that ranking on it is not
just ranking noise.

## Read
- `src/babylon/follow/scheduler.py` — `_sortino`.
- `src/babylon/follow/capture/scorer.py` — the live rolling Sortino.
- `scripts/edge_sweep.py` `_skill` (median vs sortino), `convergence_test.py`.
- Commit 9ddf901 (Sortino EPS floor), 969299d (rank by Sortino).

## Adversarial hypotheses to test
1. **Downside-deviation floor.** Confirm the denominator floor is applied *consistently* in both
   `scheduler._sortino` and `capture/scorer`. A different floor (or missing floor) in the live
   scorer reintroduces the explosion → a wallet with zero downside RTs gets +∞ rank.
2. **Small-n Sortino.** With `n=2` RTs (the sweep's eligibility floor), Sortino is essentially
   undefined/wild. Does the code guard `n` before trusting Sortino? Is the rank dominated by
   wallets that happen to have 2 lucky RTs?
3. **Target return / MAR.** Sortino is relative to a target (usually 0). Is downside measured
   below 0, below the mean, or below cost? The choice changes the ranking; verify it matches the
   documented intent and is the same offline and live.
4. **Annualization / scaling.** Any sqrt(n) or annualization factor that differs between wallets
   with different RT counts biases the cross-wallet ranking toward high-frequency wallets.
5. **No CI on the rank (known #8).** Sortino ranking with no CI is unstable. Is empirical-Bayes /
   shrinkage applied to the *rank* (prior audit asked for it), or only to Kelly weights downstream?
   Without rank shrinkage, selection chases noise.
6. **median vs sortino disagreement.** In the sweep, do median-rank and sortino-rank select
   materially different rosters with different test edge? If so the "edge" is rank-statistic
   dependent — flag the instability.

## RAM
STATIC.
