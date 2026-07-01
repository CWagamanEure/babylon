# Audit 14 — Capture ingest / dedup / cursor  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/14_ingest.md`.

## Scope
Ingest normalizes fills, de-dups by tid, and tracks a restart cursor. The prior audit flagged the
unbounded dedup set as a **~3.5 GB/day OOM** — relevant to BOTH correctness and this whole audit's
RAM theme. Verify dedup is bounded AND still correct (no dropped or double-counted fills).

## Read
- `src/babylon/follow/capture/ingest.py`, `tests/test_capture_ingest.py`.
- `docs/LIVE_CAPTURE.md`: "Bounded dedup (last_tid cursor + windowed LRU)", "WS userFills replays
  on resubscribe", "reconnect: backfill userFillsByTime BEFORE truth-up".

## Adversarial hypotheses to test
1. **Bounded dedup correctness.** The fix replaces an unbounded `tid` set with a `last_tid` cursor +
   windowed LRU. Adversarial case: a fill arrives whose `tid` was evicted from the LRU but is older
   than the cursor — is it correctly rejected, or re-ingested (double count)? And a legitimately new
   fill with a tid numerically below the cursor (HL tids aren't guaranteed monotonic across coins?) —
   dropped as a false dup? Pin down the dedup key and the eviction window. **Core check.**
2. **Same-ms pagination (known #14).** Dedup by tid, refetch from `last_t` not `last_t+1`. Confirm
   the cursor logic doesn't drop fills sharing a millisecond at the page boundary.
3. **WS replay on resubscribe.** `userFills` replays history on resubscribe → must pass through the
   bounded LRU before applying. If the LRU window is shorter than the replay depth, replayed fills
   get re-applied → position drift. Compare LRU size to replay depth.
4. **Reconnect ordering.** Must backfill `userFillsByTime` BEFORE truth-up (truth-up restores
   positions, not entry_t/markouts). Verify the order; a truth-up-first path loses entry timestamps.
5. **Cursor durability.** The cursor is persisted to `meta`. On crash between fill-apply and
   cursor-commit, is a fill reprocessed (idempotent via dedup?) or lost? Trace the commit ordering.

## RAM
STATIC. (This task itself is about a memory bug — the unbounded set — so it's thematically central
to why we're being careful.)
