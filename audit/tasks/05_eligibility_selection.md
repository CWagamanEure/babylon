# Audit 05 — Eligibility & selection gating  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/05_selection.md`.

## Scope
Which wallets become eligible, and how the top-N is chosen, is where survivorship sneaks back in
and where the live roster can diverge from the validated rule.

## Read
- `src/babylon/follow/selection.py`, `src/babylon/follow/scheduler.py`, `src/babylon/follow/weights.py`.
- `scripts/edge_sweep.py` eligibility: `len(tr) >= 2 and ter[w].size >= 1`; `top = sorted(...)[:top_n]`.
- Recent commits fe44463 (raw-activity gating), 969299d (rank by Sortino + min_positions 20).

## Adversarial hypotheses to test
1. **Eligibility uses no future/performance info.** Commit fe44463 moved to "raw activity". Verify
   the *live* path gates on pre-T0 raw fill count, not on a closed-RT count or a return statistic.
   A performance gate = survivorship (known #6) — confirm it's gone everywhere, not just one file.
2. **`min(tr) >= 2` in the sweep vs `min_positions 20` live.** The offline sweep validates with
   `len(tr) >= 2`; live uses `min_positions 20`. Different eligibility thresholds → the offline
   edge is NOT the edge of the deployed roster. Quantify how the edge changes with the threshold.
3. **Top-N stability.** `top = sorted(elig, key=-trsk)[:N]`. With noisy `trsk` (few train RTs),
   the top-N is largely noise → winner's-curse: selected test return is biased up by the max-pick.
   Is there any shrinkage/empirical-Bayes on the rank? (Prior audit asked for it.)
4. **Ties & determinism.** `sorted` on equal skills — is the tiebreak deterministic and not
   secretly favoring high-test-return wallets? Non-determinism breaks re-derivability (audit 18).
5. **Kelly/weight roster cap interaction.** Commit 4c05cb4 "poll only top-N by Kelly weight".
   Does the pollable cap change *which* wallets get scored, feeding back into selection (endogenous)?
6. **Heartbeat / liveness gating** (commits 1c9e2a5, 23ddf23): can a transient outage drop a
   wallet from eligibility and bias the surviving set?

## RAM
STATIC.
