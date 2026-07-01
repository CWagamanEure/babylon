# Audit 12 — Capture stepper (live≡batch parity)  [DYNAMIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/12_stepper.md`.
> DYNAMIC: max 2 dynamic agents at once. You may run ONLY `tests/test_capture_stepper.py`.

## Scope
The "one shared `step(fill)→[events]` stepper" is the foundation: the same code must produce
identical round-trips live and in batch (commit 692b2f2 "fuzz-proven"). If parity breaks, the
live score diverges from the validated batch score silently.

## Read
- `src/babylon/follow/capture/stepper.py` (the whole file).
- `tests/test_capture_stepper.py`.
- `docs/LIVE_CAPTURE.md` engineering must-fix: flips (2 events), adds (size-weighted entry),
  out-of-order (reorder buffer), `unmarkable` flag.

## Adversarial hypotheses to test
1. **Flip (long→short in one fill).** A fill larger than the open position must emit TWO events
   (close + open) with the right entry basis on the new leg. Does the stepper handle the residual
   size correctly, or does it mis-assign the entry price of the new position?
2. **Add (scale-in).** Size-weighted average entry — verify the basis update is `(old_sz*old_px +
   add_sz*add_px)/total`, not last-price or first-price. A wrong basis biases ret_bps.
3. **Out-of-order fills.** The reorder buffer: what window does it tolerate, and what happens to a
   fill that arrives *after* the buffer flushes? Does it corrupt the position or get dropped? This
   is where live (streaming) and batch (pre-sorted) can diverge → parity break.
4. **Exact-zero close (known #15).** Confirm close resets to exact 0 with the causal running-max
   tolerance, identical in the path the test exercises and the path live uses.
5. **`unmarkable` propagation.** Cold-start position → `unmarkable` → must not produce a scored RT.
6. **The fuzz test's coverage.** Read the fuzz test — does it actually exercise flips+adds+OOO
   *combined*, or each in isolation? A parity proof that never combines them isn't a proof. If the
   fuzz is weak, that itself is a finding.

## Allowed probe
Run only this one test file:
```bash
POLARS_MAX_THREADS=2 timeout 180 .venv/bin/pytest tests/test_capture_stepper.py -x -q -p no:cacheprovider 2>&1 | tail -20
```
No fills data needed (the test is synthetic). Check `vm_stat` first.

## RAM
DYNAMIC but synthetic test → light. Do not run the full suite.
