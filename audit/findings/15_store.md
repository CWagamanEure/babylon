# Audit 15 — Capture store / SQLite / retention / restart  (agent: capture_store_restart)

## Summary
I read `src/babylon/follow/capture/store.py`, `tests/test_capture_store.py`,
`docs/LIVE_CAPTURE.md` (schema / Restart recovery / Retention), and cross-referenced the
markout/ingest/scorer modules and audit findings 13 & 14. I ran the one allowed probe
(`tests/test_capture_store.py`, 4 passed, 0.31s; `vm_stat` showed ~3 GB free+inactive, safe).
**The store is materially under-built versus its own spec: it implements ONLY the
`roundtrips` table. The `open_state`, `wallets`, and `meta` tables that LIVE_CAPTURE.md §6
makes the entire restart-recovery contract depend on do not exist anywhere.** Consequence: a
restart cannot rebuild PositionTracker, cannot resume the ingest cursor, and cannot restore
`next_rid` — so the documented "drop vs `late_markout`" question (hypothesis 1) is moot
(there is no persisted in-flight state to drop OR mark), and audit 14's `rid`+`INSERT OR
IGNORE` silent-drop (F2) is **confirmed from the store side and is enshrined by a passing
test**. All blast radius is **selection-power only** (capture feeds selection, not the
hash-chained gate), so nothing here can fake a GO. Max severity **HIGH**.

## Findings

### F1 — Spec'd durable state (`open_state`/`wallets`/`meta`) does not exist → restart loses ALL in-flight state; the disposition fix silently disappears post-restart  [HIGH]
- **Where:** `src/babylon/follow/capture/store.py:25-31` (only `CREATE TABLE roundtrips` +
  one index; no other table). Cross-ref `docs/LIVE_CAPTURE.md:50-56` (4 tables required) and
  `:70-77` ("Restart recovery: rebuild PositionTracker from `open_state`… resume Ingest from
  the `meta` cursor").
- **Blast radius:** selection-power (and pre-registration determinism if/when wired).
- **Failure scenario:** All in-flight round-trip state lives in `MarkoutScheduler._rt` /
  `_heap` (in-memory, `markout.py:82-83`) and `FillIngest`'s per-`(wallet,coin)` steppers /
  buffers (`ingest.py:46-49`). Nothing persists them. On any restart:
  1. `MarkoutScheduler._rt` is empty → `open_marked(wallet)` (`markout.py:147`) returns `[]`
     → `CaptureScorer.returns_fn` (`scorer.py:38-46`) falls back to **closed-only** returns.
     The audit's #2 disposition fix (MTM every still-open position at the cutoff) silently
     evaporates exactly after a restart, re-introducing the **+15bp (long-hold) to +122bp
     (7-day warm-up) upward bias** the fix exists to remove — and a restart is most likely
     during the fragile warm-up window. The score regresses without any error or log.
  2. A position OPENED before the restart can never be CLOSED into a round-trip after it:
     `on_close` looks up `self._rt.get((wallet,coin,rid))` and `if rt is None: return`
     (`markout.py:99-100`) — the entry state is gone, so the close is dropped and that
     round-trip is lost entirely (not merely mis-priced), until the (wallet,coin) next flips
     through flat.
  3. `drop_due_before` (`markout.py:132`, the only "restart hygiene") operates on the
     in-memory `_heap`, which is empty after a real restart → it is a no-op on the case it
     was written for. The hypothesis-1 question ("drop, or mark at current mid?") never even
     arises because the due item isn't persisted to be reconsidered.
- **Why it's real (not theoretical):** It is an absence confirmed by reading every line of
  store.py (one table) and by grep across `capture/` (audit 14 F4 independently confirms no
  `open_state`/`meta`/`last_tid`/truth-up exists). Items 1–2 follow directly from the
  in-memory lookups in `markout.py:99,147` and `scorer.py:38`.
- **Confidence:** high that the tables/restore path are absent; the magnitude of the
  disposition regression is the documented +122bp warm-up figure.
- **Fix sketch:** Build the spec'd `open_state(wallet,coin,signed_size,entry_t,entry_mk,
  taker_open,conviction,rid)` and `meta(key,value)` tables; on restart rehydrate
  `MarkoutScheduler._rt` (and re-push entry/exit heap items by `due=t+lag`, applying the
  drop-vs-future split) and seed each `CoinStepper(next_rid=restored, startpos=restored)`.
  Persist `open_state` transactionally alongside the `roundtrips` flush so the two can't
  diverge.

### F2 — `rid` reset on restart + PK `(wallet,coin,rid)` + `INSERT OR IGNORE` silently drops legitimate post-restart round-trips — CONFIRMED from the store side, and a passing test enshrines the drop  [HIGH]
- **Where:** `src/babylon/follow/capture/store.py:30` (`PRIMARY KEY (wallet, coin, rid)`),
  `:49` (`INSERT OR IGNORE`); driven by non-durable `rid` (`stepper.py` counter, default 0;
  `ingest.py:74` `CoinStepper(key[1])` never restores it). `tests/test_capture_store.py:20-28`
  (`test_store_persists_and_dedups_rid`).
- **Blast radius:** selection-power.
- **Failure scenario:** `rid` is a per-(wallet,coin) counter from 0 with no persistence (see
  F1 — no `meta`/`open_state`). Pre-restart, wallet W coin ZEC persists rids 0,1,2,…
  Post-restart the counter restarts at 0, so W's next *legitimately distinct* round-trips get
  rids 0,1,2,… again → PK collision → `INSERT OR IGNORE` **silently discards** them. They
  never reach `roundtrips`, so `returns()`/`active_wallets()` compute the wallet's Sortino on
  a truncated sample biased to drop its earliest post-restart trades. The store layer makes
  this concrete and unobservable: `flush()` ignores `cur.rowcount`/`changes()`, so there is
  no counter of how many inserts were swallowed.
  I confirmed the swallowing behavior directly: `test_store_persists_and_dedups_rid` inserts
  `rid=0, ret=50.0` then `rid=0, ret=99.0`, closes, reopens, and **asserts `count()==1` and
  `returns()==[50.0]`** — i.e. the second, different-payload row is silently dropped and the
  test treats that as correct. The same mechanism that gives in-process replay idempotency
  (hypothesis 3) is exactly the mechanism that eats post-restart data; the store cannot tell
  "same RT replayed" from "different RT, reused rid".
- **Why it's real:** PK and `INSERT OR IGNORE` are concrete (store.py:30,49); the rid reset
  is concrete (no restore path exists, F1); the test demonstrates and locks in the drop. This
  refines/confirms audit 14 F2 from the store side and adds that it is *test-enshrined* and
  *unobservable* (no IGNORE count surfaced).
- **Confidence:** high on the store mechanics and the test behavior (ran it). The realized
  harm is contingent on the not-yet-built restart driver reusing the resettable counter —
  but the store as written bakes the collision in and a naive restart hits it.
- **Fix sketch:** Make the PK a collision-proof surrogate — `INTEGER PRIMARY KEY
  AUTOINCREMENT`, or `(wallet,coin,entry_t,exit_t)` — so distinct round-trips can't alias; OR
  persist+restore `next_rid` per (wallet,coin) (the F1 `meta` rows). At minimum, surface
  `self._db.total_changes`/`cur.rowcount` from `flush()` so silent drops are observable and
  alarmable.

### F3 — Retention prune boundary is internally correct, but nothing couples `before_t` to the active scoring window → a misconfig silently shrinks the sample  [LOW]
- **Where:** `src/babylon/follow/capture/store.py:73-78` (`prune`, `DELETE WHERE exit_t <
  before_t`) vs `:56-63` (`returns`, `exit_t>=lo AND exit_t<hi`).
- **Blast radius:** selection-power.
- **Failure scenario (cleared):** The prune predicate `exit_t < before_t` is the exact
  complement of the retain side of `returns()`'s `exit_t >= lo`: a boundary round-trip at
  `exit_t == before_t` is **kept** by prune and **included** by `returns()` when
  `lo == before_t`. So with `before_t = now − retention` and `retention_days (365) ≫
  train_days`, prune never touches an in-window round-trip, and it provably cannot delete an
  open position (no `open_state` table exists for it to reach — vacuously safe, though only
  because F1's table is missing). Hypothesis 2 ("prune deletes an open state / in-window RT")
  is therefore **refuted for the code as written**.
- **Residual concern:** there is no guard asserting `before_t ≤ (min t0 − train_ms)` ever
  queried; the coupling is purely "operator sets retention ≫ train." If a future config sets
  `roundtrip_retention_days < train_days` (or the nightly job is handed a too-recent
  `before_t`), prune silently deletes round-trips the very next score still needs → smaller n
  → noisier rank. No error, no log of "deleted in-window."
- **Confidence:** high that the boundary arithmetic is correct; the residual is a
  config-coupling gap, not a present bug.
- **Fix sketch:** Have `prune` clamp/assert `before_t ≤ now − max(retention_ms, train_ms)`
  (or derive `before_t` from the scorer's own lower bound), and log the deleted count.

### F4 — Per-batch insert is atomic, but a crash with up to `batch` (500) buffered round-trips loses them with no cursor to replay → bounded silent gap  [LOW]
- **Where:** `src/babylon/follow/capture/store.py:36-54` (`add` buffers; `flush` =
  `executemany` + single `commit`), `:21` (`batch=500`).
- **Blast radius:** selection-power.
- **Failure scenario:** `flush()` does one `executemany` then one `commit` → the batch is
  atomic; a crash mid-`executemany` (pre-commit) commits nothing, so there is **no partial
  round-trip** and **no dangling reference** (there is no `open_state`/FK to dangle to). That
  half of hypothesis 4 is **clean**. BUT the in-memory `self._buf` (up to 500 round-trips,
  ~30 s at the spec'd ~16 rt/s) is lost on crash, and because no ingest cursor is persisted
  (F1) there is no way to know where to resume to re-derive them — and even if re-derived,
  the rid reset (F2) would collide them away. So a crash creates a small, bounded, **silent**
  hole in the per-wallet series. `synchronous=NORMAL`+WAL (`:23-24`) additionally means an OS
  crash can lose the last un-checkpointed *committed* transactions — the standard accepted
  WAL tradeoff, acceptable here, noted for completeness.
- **Confidence:** high on atomicity (single commit) and on the buffer-loss bound.
- **Fix sketch:** Lower `batch` or add a time-based flush so the at-risk window is < a few
  seconds; once F1's `meta` cursor exists, advance it only past flushed round-trips so a crash
  re-derives the lost tail deterministically.

### F5 — Disk/RAM budget is honored; one minor note (no VACUUM after prune)  [NIT / cleared]
- **Where:** `src/babylon/follow/capture/store.py` (whole file).
- **Blast radius:** none (ops).
- **What I checked (hypothesis 5):** The store persists **only** the 12-column `roundtrips`
  rows. It never writes a mid-log and never persists raw fills (the ingest keeps only an
  in-memory buffer) — confirmed by reading every `execute`/`executemany` in the file. RAM is
  bounded: `self._buf` ≤ `batch` (500). So the "per-second mid-log / unbounded fills → disk
  blowup" risk is **absent** — the store cannot accidentally persist either. Minor: `prune`
  issues `DELETE` with no `VACUUM`, so freed pages return to the SQLite freelist (reused), not
  to the OS; with bounded 365-day retention the file reaches a stable high-water mark, so this
  is fine, not a blowup. WAL also grows between auto-checkpoints (default 1000 pages) —
  bounded.
- **Confidence:** high.
- **Fix sketch (optional):** an occasional `PRAGMA wal_checkpoint(TRUNCATE)` / periodic
  `VACUUM` after large prunes if disk high-water matters on the droplet.

## What I checked and could clear
- **Idempotent insert (hypothesis 3):** `INSERT OR IGNORE` on `(wallet,coin,rid)` *is*
  idempotent for an in-process replayed fill that re-derives the **same** rid → no
  double-insert (good). The defect is that the same mechanism can't distinguish that from a
  reused-rid distinct round-trip (F2).
- **Prune cannot delete an open position** — vacuously, because `open_state` doesn't exist
  (F1); boundary arithmetic is exact (F3).
- **Per-batch crash atomicity** — single-commit transaction, no partial/dangling rows (F4).
- **No mid-log / no fills persisted / bounded buffer** — store cannot blow disk or RAM (F5).
- **Could not rule out:** the realized severity of F1/F2 depends on the not-yet-built restart
  driver. A probe is impossible (no service, ground-rules forbid it); the harm is determined
  by static reading of the missing tables + in-memory lookups, which is what I relied on.
