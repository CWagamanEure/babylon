# Audit 14 — Capture ingest / dedup / cursor  (agent: capture_ingest)

## Summary
I read `src/babylon/follow/capture/{ingest,stepper,store,markout}.py`, the ingest test, and
`docs/LIVE_CAPTURE.md`. The OOM headline is genuinely fixed: dedup is a bounded `OrderedDict`
LRU (`dedup_window=200_000`), not an unbounded set. But the **`last_tid` cursor half of the
documented design ("last_tid cursor + windowed LRU", LIVE_CAPTURE.md:140) was never built** —
only the LRU exists — and that omission opens two real holes: (F1) on a reconnect replay storm
the global LRU is overrun and the time-only late-guard double-counts the last fill per
(wallet,coin); (F3) same-ms out-of-order stragglers are released out of (time,tid) order.
Separately (F2) **`rid` is not durable across restart** despite the comment claiming it is, so the
store's `(wallet,coin,rid)` PK + `INSERT OR IGNORE` silently drops post-restart round-trips.
Restart-recovery / reconnect-truth-up (hypotheses 4 & 5) is **documented but unimplemented**
(F4). All blast radius is **selection-power only** (capture feeds selection, not the gate), so
nothing here can fake a GO; max severity HIGH.

## Findings

### F1 — Reconnect replay overruns the GLOBAL LRU; time-only late-guard double-counts the last fill per (wallet,coin)  [HIGH]
- **Where:** `src/babylon/follow/capture/ingest.py:45,54-68` (`_seen` LRU + `on_fill`)
- **Blast radius:** selection-power
- **Failure scenario:** The dedup structure `_seen` is a single `OrderedDict[tid]` shared across
  ALL wallets and coins, capped at 200k entries. The documented design (LIVE_CAPTURE.md:140,
  "last_tid cursor + windowed LRU") has a *cursor* that rejects any tid at/below the persisted
  high-water mark regardless of LRU eviction — that half is absent (grep: no `last_tid` anywhere).
  So eviction safety rests entirely on the secondary time-guard at line 62
  `if f.time < self._last_released.get(key, -1)`.
  Now take a full WS reconnect (all ~1,404 Phase-1 subs drop and resubscribe together). HL
  `userFills` replays a recent snapshot per wallet on resubscribe (up to ~2,000 fills each), so the
  burst is ~10^6 fills interleaved — far more than the 200k LRU. Fill `F@(time=T, tid=t)`, wallet
  W coin C, was delivered live pre-drop, applied and released, so `_last_released[(W,C)] = T` (it
  was W's last fill on C before the drop). During the replay burst `t` is pushed near the front of
  the LRU and evicted long before F's replay copy arrives. When the replay of F arrives: `t` is no
  longer in `_seen` → not recognised as a duplicate → falls to the time-guard → `F.time (T) <
  _last_released (T)` is **False** (strict `<`, equal time) → NOT dropped → re-buffered → re-stepped.
  The stepper (stepper.py:85) re-applies the fill: a phantom same-side `Add`, or if it was a close,
  a phantom flip/round-trip → signed position drifts → every subsequent round-trip for (W,C) until
  it next returns to flat is mis-reconstructed → corrupted `ret_bps` feeding the Sortino score.
  This recurs on **every** full reconnect, biased to the most-recently-active wallets (the ones
  whose last fill is exactly at `_last_released`).
- **Why it's real (not theoretical):** Two confirmed code facts combine: (a) `_seen` is keyed on
  `tid` alone and global (line 45), so its effective per-wallet depth is 200k/active-wallets and a
  reconnect burst evicts even seconds-old tids; (b) the only backstop, line 62, uses strict `<` on
  *time only* and `_last_released` stores only `f.time` (line 49,77), so the equal-time case slips
  through. The intended cursor that would make this safe was never implemented.
- **Confidence:** medium-high. The double-count mechanics are fully determined by the code; the one
  unverified input is HL's exact `userFills` resubscribe replay depth/rate vs 200k (the WS client
  isn't in this repo). A probe replaying >200k synthetic tids through `on_fill` with a colliding
  last fill would settle it, but ground rules say static-only — the equality + eviction logic is
  visible without running.
- **Fix sketch:** Implement the missing durable `last_tid` (and per-wallet `last_time`) cursor the
  doc specifies: reject any fill with `tid <= last_tid_for_source` outright, independent of LRU
  membership; and store `_last_released` as a `(time, tid)` tuple compared with the tuple (closes
  the equal-time hole, also fixes F3). Optionally make `_seen` per-wallet or size it ≫ the worst-case
  reconnect burst.

### F2 — `rid` is not durable across restart; store PK + `INSERT OR IGNORE` silently drops post-restart round-trips  [HIGH]
- **Where:** `src/babylon/follow/capture/store.py:30,49` (PK `(wallet,coin,rid)`, `INSERT OR
  IGNORE`); `src/babylon/follow/capture/stepper.py:65,72` (`next_rid` default 0, comment "durable
  across restart"); `src/babylon/follow/capture/ingest.py:74` (`CoinStepper(key[1])` — no
  `next_rid`/`startpos` restored)
- **Blast radius:** selection-power
- **Failure scenario:** `rid` is a per-(wallet,coin) counter from `CoinStepper._next_rid`, default 0.
  Ingest constructs steppers lazily with `CoinStepper(key[1])` — never passing a restored
  `next_rid` — and there is **no persistence** for it (grep: no `meta`/`open_state`/`next_rid` in
  store; store.py only creates the `roundtrips` table). So after any process restart, wallet W coin
  ZEC starts again at `rid=0`. Pre-restart it persisted round-trips with rids 0,1,2,…; post-restart
  the next closed round-trips get rids 0,1,2,… again → primary-key collision on
  `(wallet,coin,rid)` → `INSERT OR IGNORE` **silently discards** the new, legitimately-different
  round-trips. They never enter `roundtrips`, never count in `returns()`/`active_wallets()` → the
  wallet's Sortino is computed on a truncated sample, systematically dropping its earliest
  post-restart trades. The stepper comment "monotonic counter (durable across restart)"
  (stepper.py:72) is aspirational — nothing reads or writes it.
- **Why it's real (not theoretical):** The PK and `INSERT OR IGNORE` are concrete (store.py:30,49);
  the rid reset is concrete (no restore path exists). The documented restart recovery (rebuild from
  `open_state`, resume from `meta` cursor; LIVE_CAPTURE.md:70-77) that would restore `next_rid` is
  **not implemented** — there is no `open_state` or `meta` table. So any naive restart of the (not-
  yet-wired) service hits this.
- **Confidence:** medium. Certain about the collision mechanics; depends on the restart driver
  (unbuilt) reusing `(wallet,coin,rid)` PKs. If a future restart layer restores `next_rid` from a
  persisted max, the bug disappears — but the store as written bakes the collision in.
- **Fix sketch:** Persist `next_rid` per (wallet,coin) (the planned `meta`/`open_state` rows) and
  pass it to `CoinStepper(..., next_rid=restored)` on rebuild; OR make the PK a globally-unique
  surrogate (e.g., autoincrement, or `(wallet,coin,entry_t,exit_t)`), not the resettable counter; OR
  at minimum surface the IGNORE count so silent drops are observable.

### F3 — Same-ms, lower-tid straggler is released out of (time,tid) order instead of dropped  [MED]
- **Where:** `src/babylon/follow/capture/ingest.py:49,62,77` (`_last_released` stores `f.time`
  only; late-guard `f.time < _last_released` with strict `<`)
- **Blast radius:** selection-power
- **Failure scenario:** The stepper requires fills in `(time, tid)` order (heap key is `(time, tid,
  fill)`, line 66). Take fill A `(time=1000, tid=11)` released first → `_last_released[key]=1000`.
  Then fill B `(time=1000, tid=10)` arrives after A's release (a >lateness-ms-late straggler, e.g.
  in a reconnect burst). Correct order is B before A (same time, lower tid). The late-guard
  `B.time(1000) < 1000` is False → B is **not** dropped; it's buffered and, since `watermark −
  lateness ≥ 1000`, released immediately — **after** A. The stepper now sees tid 11 then tid 10,
  violating its ordering precondition → a wrong open/close interleave for that coin. Note the
  symmetric case (same time, *higher* tid late) releases correctly, so this is specifically the
  lower-tid straggler. The design's own intent is to DROP fills too late to order (line 62 comment
  "already past this point → too late"), but the equal-time case is neither dropped nor ordered.
- **Why it's real (not theoretical):** Pure consequence of dropping `tid` from the watermark and
  using strict `<`. Same root as F1. This is the live-path analogue of known-issue #14 (same-ms
  fills), which was only fixed for the offline REST pagination path.
- **Confidence:** medium. Mechanics are certain; frequency depends on how often HL delivers same-ms
  fills out of tid order beyond the 2s lateness window (rare in steady state, more likely in
  reconnect bursts).
- **Fix sketch:** Track `_last_released[key]` as `(time, tid)` and compare the tuple in line 62 —
  drops the lower-tid straggler as late (counted in `dropped_late`) and admits the higher-tid one,
  matching the stepper's `(time,tid)` contract.

### F4 — Restart-recovery / reconnect-truth-up / cursor durability is DOCUMENTED but UNIMPLEMENTED  [LOW / scope-note]
- **Where:** `docs/LIVE_CAPTURE.md:70-77,150-154` vs `src/babylon/follow/capture/` (no WS client,
  no `userFillsByTime` backfill, no `clearinghouseState` truth-up, no `meta` cursor, no `open_state`
  table)
- **Blast radius:** selection-power (and pre-registration determinism if/when wired)
- **Failure scenario:** Hypotheses 4 (reconnect: backfill `userFillsByTime` BEFORE truth-up) and 5
  (cursor durability / crash idempotency) cannot be audited as code because that code does not
  exist. The components built (ingest, stepper, markout, store) are in-memory; `markout.py` has the
  restart hooks `drop_due_before` (132) and `open_marked` (147), but nothing persists or rebuilds
  PositionTracker/cursor state. Consequence: a restart loses all stepper state and the LRU, so on
  resubscribe the replayed snapshot rebuilds positions from flat — any position whose opening fill
  predates the `userFills` replay depth is mis-seeded (first replayed fill is a partial close →
  stepper at pos 0 treats it as an opposite-side OPEN → phantom round-trip with flipped direction;
  the `valid`/`rid==−1` guard at stepper.py:71 only triggers for a *seeded* nonzero startpos, which
  never happens because nothing seeds it). This is known-issue #11 (startPosition mis-seeding)
  reappearing in the live restart path.
- **Why it's real:** It's an absence, confirmed by grep (no `last_tid`/`meta`/`open_state`/
  truth-up). The doc's "Locked invariants" and "Restart recovery" sections are unrealized. Until a
  restart layer exists this is latent, but it is the exact place F1/F2 would bite.
- **Confidence:** high that it's unimplemented; the harm is contingent on how the future service
  wires restart.
- **Fix sketch:** Build the documented restart path (persist `last_tid` cursor + `open_state` incl.
  `next_rid` and signed position; on reconnect backfill `userFillsByTime` from the cursor BEFORE
  `clearinghouseState` truth-up) and seed each rebuilt `CoinStepper` with the restored startpos so
  pre-observed opens get `rid=-1`/`valid=False` rather than phantom round-trips.

## What I checked and could clear
- **OOM is fixed.** Dedup is a bounded LRU (`OrderedDict`, `popitem(last=False)` at
  ingest.py:59-60), capped at `dedup_window`. The per-key state dicts (`_buf`, `_watermark`,
  `_last_released`, `_steppers`) grow only with the number of (wallet,coin) pairs (thousands), not
  with fill volume → no unbounded growth. The ~3.5 GB/day set is gone.
- **No cursor → no numeric false-drop.** Hypothesis 1's "new fill with tid below the cursor dropped
  as a false dup" does NOT occur, precisely because the cursor was never built — dedup is pure LRU
  membership, and HL `tid` is globally unique so keying on `tid` alone has no cross-wallet collision
  (no false drop from that either). The cost of that simplicity is F1.
- **In-window same-ms ordering is correct.** Two same-ms fills both still in the buffer are ordered
  by the `(time, tid)` heap key (ingest.py:66). The break is only the late straggler (F3).
- **Replay (in-window) dedup works.** A resubscribe replay whose tid is still in the LRU is dropped
  (ingest.py:54-57, `dropped_dup`), matching `test_dedup_drops_replayed_tid`. The failure is only
  when the tid has been evicted (F1).
- **Markout keys on `rid`, not `entry_t`** (markout.py:7,91), correctly avoiding same-ms flip
  collisions — but that same `rid` is the non-durable key that drives F2.
