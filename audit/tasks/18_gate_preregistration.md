# Audit 18 — GO/NO-GO gate & pre-registration integrity  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/18_gate.md`.

## Scope
THE highest-stakes target. The gate (`measure → decide`) is the only thing that can declare an edge
real. A bug here is the one class of CRITICAL that *fabricates* an edge (false GO) rather than just
losing power. The prior audit said this machinery is "hash-chained, read-once, min-n-recomputed,
untouched" — your job is to verify that claim adversarially, not accept it.

## Read
- `src/babylon/stats/gate.py`, `src/babylon/stats/metrics.py`, `src/babylon/stats/decay.py`.
- `src/babylon/follow/measure.py`, `src/babylon/follow/experiment.py`, `src/babylon/follow/oos.py`,
  `src/babylon/follow/walkforward.py`.
- `tests/test_measure.py`, `tests/test_experiment.py`.
- `docs/LIVE_FOLLOW.md` (the pre-registration / decision protocol).

## Adversarial hypotheses to test
1. **Read-once / hash-chain integrity.** Can the GO criterion be evaluated, seen to fail, and
   silently re-evaluated with a tweaked threshold (p-hacking)? Find where the threshold/criterion is
   committed and whether the hash-chain actually prevents post-hoc edits. Try to construct a path
   that reads the outcome before locking the rule.
2. **min-n recompute.** The gate recomputes at a minimum n. Can a favorable early peek trigger a GO
   before n is reached (optional-stopping inflation of the false-positive rate)? Is there alpha-
   spending / a fixed sample plan, or does it test repeatedly as fills accumulate?
3. **Does selection leak into the gate?** Prior audit's load-bearing claim: the gate reads realized
   PAPER fills, not the capture/candle SELECTION score. VERIFY this boundary in code — if any gate
   statistic is computed over the *selected* arm using a selection-time quantity, selection bias
   contaminates the gate → false GO. This is the single most important check in the whole audit.
4. **Multiple-comparisons across arms/transitions.** If the experiment tests several rosters/lags/
   transitions and reports the best, is there a correction? An uncorrected max over arms fakes
   significance.
5. **Determinism / re-derivability of the GO.** Same committed inputs → same decision? Tie to
   audit 16's run_id hash. If the gate's inputs include the non-deterministic capture DB, the GO is
   not re-derivable (and the pre-registration is theater).
6. **Disposition/seam bugs reaching the gate.** Do any of the offline biases (look-ahead, seam,
   disposition) share code with the gate's realized-fill measurement? If the gate reuses
   `_close_at`/`_positions_for` with the same boundary bugs, an offline finding becomes a gate finding.

## RAM
STATIC.
