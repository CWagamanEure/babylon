# Audit 13 — Capture markout scheduler  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/13_markout.md`.

## Scope
The MarkoutScheduler min-heap snapshots the book mid at `due = event_time + lag`. Its correctness
under staleness, downtime, and out-of-order due-times determines whether the live score is sharp
or silently corrupted.

## Read
- `src/babylon/follow/capture/markout.py`, `tests/test_capture_markout.py`.
- BookCache references; `docs/LIVE_CAPTURE.md` "MarkoutScheduler", "BookCache freshness contract",
  "drop-on-stale", "late_markout" must-fix.

## Adversarial hypotheses to test
1. **Drop-on-stale correctness.** If the book mid is stale (no recent l2Book update) at due-time,
   the markout must be DROPPED, not taken at a stale price. Find the freshness check — what's the
   staleness threshold, and is it enforced before *every* snapshot? A missing check on one path
   marks at a price minutes old.
2. **`late_markout` elimination.** Prior audit demanded dropping `late_markout` (a due-time that
   passed during downtime, marked at the wrong instant). Confirm the code drops these rather than
   marking at current mid. A `late_markout` taken at restart silently fabricates a price.
3. **Crossed/empty book.** BookCache freshness contract requires crossed/empty validation. Does
   the snapshot reject a crossed (bid>ask) or empty book, or does it compute a garbage mid?
4. **1-ms mid vs TWAP.** Prior audit: "short median/TWAP around t+lag, not a 1-ms mid." Is the
   mark a single instantaneous mid (noisy) or a short window? A 1-ms mid adds variance to every RT.
5. **Aggressing-side mark (commit c59cc94 "aggressing-side").** Verify entry/exit are marked on the
   correct side relative to the wallet's direction — a mid mark understates cost (hand cost detail
   to audit 10, but flag the side convention here).
6. **Heap ordering & due-time monotonicity.** Min-heap by due — what if two events share a due-time,
   or an event is scheduled in the past? Confirm no starvation/reordering that mis-pairs entry/exit.

## RAM
STATIC — read the test rather than running it.
