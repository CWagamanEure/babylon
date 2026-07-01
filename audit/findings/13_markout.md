# Audit 13 — Capture markout scheduler  (agent: 13_capture_markout)

## Summary
I read `src/babylon/follow/capture/markout.py`, `tests/test_capture_markout.py`,
`src/babylon/follow/capture/ingest.py`, `scorer.py`, `stepper.py`, and the `LIVE_CAPTURE.md`
contract. The aggressing-side convention, crossed/empty/locked-book rejection, heap tie-break,
same-ms-flip keying, and the restart `drop_due_before` path are all **correct**. The real
defect is in the `late_markout` elimination (hypotheses #1/#2/#6): the must-fix is only
*half* implemented. The cross-restart variant is dropped (`drop_due_before`), but the
**in-process** late-mark is not — and the reorder buffer, quiet-coin buffering, `flush()`, and
reconnect-backfill make in-process lateness *systematic*, not rare. Plus the documented
"short median/TWAP, not a 1-ms mid" must-fix is unimplemented (BookCache is latest-snapshot-
only). All blast radii are **selection-power** (capture feeds selection only; cannot fake a GO).

## Findings

### F1 — `process_due` marks every due item at the *latest* book with no due-vs-now lateness guard → in-process `late_markout` survives  [HIGH]
- **Where:** `src/babylon/follow/capture/markout.py:105-130` (`process_due`), `:44-48`
  (`BookCache.snap`), `:79` (`staleness_ms=30_000`); interacts with
  `src/babylon/follow/capture/ingest.py:40,68,75,85-89` (reorder buffer + `flush`).
- **Blast radius:** selection-power (capture score → RollScheduler only; the gate reads
  realized paper fills, so no false GO). Also blocks the must-fix #1 determinism/re-derivability
  requirement for any future swap-in.
- **Failure scenario:** `BookCache` keeps **only the latest** snapshot per coin
  (`self._books[coin] = BookSnap(...)`, `:42`) — there is no time-indexed book history, so
  `process_due` can *never* retrieve the book at the true due instant; it always reads the most
  recent book. The only protection is the staleness gate, which compares the book age to `now`
  (`now - b.ts > staleness_ms`, `:46`), **not** the gap between `due` and `now`. The while-loop
  (`:109`) pops *everything* with `due <= now` and marks it at the current book with no
  upper-bound on `now - due`. Concretely:
  - The ingest reorder buffer holds a fill until a fill `lateness_ms` (=2_000 default,
    `ingest.py:40`) newer settles it (`:68,75`). So `on_open`/`on_close` fire ~2 s after the
    fill's exchange time, scheduling `due = entry_t + lag`. **If `lag < 2 s`** (the doc pins
    `lag` to the real detect→enter latency — sub-second to a couple seconds), `due` is *already
    in the past* when scheduled → next `process_due(now)` pops it immediately and marks at
    `book@now`, seconds after the intended instant. Systematic for the whole population, not an
    edge case.
  - On a **quiet coin**, the buffer releases a fill only when the *next* fill arrives — minutes
    later. `due` is then minutes stale; `process_due` still marks it at the fresh-vs-now latest
    book. The staleness gate passes (book is fresh relative to `now`), so the mark is taken
    minutes late and never dropped.
  - `flush()` (`ingest.py:85-89`) at a scoring cutoff releases *all* buffered fills at once;
    their markouts all come due in the past and are marked en masse at the cutoff book.
  - Reconnect backfill (`userFillsByTime`, per doc) feeds old-`entry_t` fills through the same
    path → past-due markouts taken at the current book, violating the "forward-only" invariant.
- **Why it's real (not theoretical):** `drop_due_before` (`:132`) — the *only* late-drop logic —
  is labelled "restart hygiene" and is **not** invoked inside `process_due`. There is no durable
  sampled-mid log (the doc's engineering must-fix: "looked up at its TRUE instant, else
  dropped — never `late_markout`"). So the audit's late-mark must-fix is implemented for the
  cross-restart case only; the in-process case is wide open and the reorder buffer *guarantees*
  a ≥`lateness_ms` lag between event time and scheduling whenever `lag < lateness_ms`.
- **Confidence:** high on the code gap (no due-vs-now check anywhere; BookCache is latest-only).
  Medium on magnitude — the live service loop that drives `process_due(now, book)` is not yet
  built (SHADOW), so the exact `now` it passes is unverified; but for any plausible wall-clock
  `now`, the gap above holds.
- **Fix sketch:** in `process_due`, drop (don't mark) any popped item with `now - due >
  mark_tolerance_ms` (a small value, e.g. ≤ a few hundred ms), OR look the mark up in a durable
  time-indexed mid log at `due` and drop if absent. Pin `mark_tolerance` well below
  `ingest.lateness_ms`, and schedule markouts off a release-time/event-time clock rather than
  wall-clock so the buffer delay doesn't silently consume the budget.

### F2 — Single instantaneous aggressing-touch mark; the documented "short median/TWAP, not a 1-ms mid" is unimplemented  [MED]
- **Where:** `src/babylon/follow/capture/markout.py:39-48` (BookCache stores/returns one snap),
  `:121-122` (mark = single `snap.ask`/`snap.bid`).
- **Blast radius:** selection-power (adds variance to every RT → noisier Sortino → weaker
  ranking; never reaches the gate).
- **Failure scenario:** `BookCache.update` overwrites to a single latest `BookSnap`; `snap`
  returns that one tick. The entry/exit marks are one instantaneous touch each, so every
  `ret_bps` carries the full single-tick microstructure noise of both legs. On thin alts a lone
  bid/ask print can be a transient outlier, directly inflating the downside-deviation tail the
  Sortino is most sensitive to. The doc's engineering must-fix ("BookCache … short median/TWAP
  around t+lag, not a 1-ms mid") is not built — there is no window to median over.
- **Why it's real:** the data structure (`dict[str, BookSnap]`, `:39`) physically cannot hold a
  window; it would need a ring buffer of recent snaps per coin. Confirmed absent.
- **Confidence:** high (structural).
- **Fix sketch:** keep a short ring of recent `(ts,bid,ask)` per coin and mark at the median
  touch over `[due-w, due+w]`; this also gives the durable-instant lookup F1 needs.

### F3 — `staleness_ms` default 30 s is far too loose for a "sharp" forward mark  [LOW]
- **Where:** `markout.py:79` (`staleness_ms: int = 30_000`), enforced at `:46`.
- **Blast radius:** selection-power.
- **Failure scenario:** A book up to 30 s old (vs `now`) is accepted as fresh. A real follower
  at `+lag` (sub-second) would never receive a 30 s-old top-of-book on a thin coin. So on
  illiquid coins — exactly where the followable edge is most fragile — the mark can be 30 s
  stale and still pass, compounding F1 (late) and F2 (single-tick). 30 s is the documented
  cliff; a sharp mark wants ~1–5 s.
- **Why it's real:** it's the active default in both `MarkoutScheduler` and `CaptureScorer`
  (`scorer.py:26`); no caller overrides it in-repo.
- **Confidence:** medium (parameter judgement; the "right" value depends on the live latency
  distribution the doc says to measure but hasn't).
- **Fix sketch:** set staleness from the measured live-fill latency p75, not a 30 s scalar.

### F4 — `CaptureScorer` open-position MTM reads the latest book keyed to `t0` staleness → look-ahead if `t0 < wall-clock`  [LOW]
- **Where:** `src/babylon/follow/capture/scorer.py:38-43` (`book.snap(coin, t0_ms, staleness)`).
- **Blast radius:** selection-power; only manifests on a replay/re-derivation at a historical
  `t0` (not in live-forward, where `t0 ≈ now`).
- **Failure scenario:** BookCache holds only the latest snap. If the scorer is run at a `t0` in
  the past while the live book has advanced, `now - b.ts = t0 - latest_ts` is negative → passes
  the staleness gate (`:46`), and the open-position MTM exit is taken from a book that *post-
  dates* `t0` → look-ahead in the disposition-fix leg. Harmless live-forward; a hazard for the
  determinism/re-derivability the doc's must-fix #1 wants.
- **Why it's real:** same latest-only BookCache; the staleness check does not reject
  future-relative-to-`t0` books (negative age passes `> staleness`).
- **Confidence:** medium.
- **Fix sketch:** the durable time-indexed mid log from F1/F2; reject `b.ts > now` snaps.

## Clean bill — checked and holds up
- **Aggressing-side convention (H5):** entry `ask` for long / `bid` for short (`:121`), exit
  `bid` for long / `ask` for short (`:122`); `ret_bps = d·(exit/entry−1)·1e4` folds the
  round-trip spread in correctly for both directions (verified against the test math). Correct.
- **Crossed/empty/locked/NaN book (H3):** `BookSnap.valid = ask > bid > 0` (`:30`) rejects
  crossed (bid≥ask), one-sided (0), locked (bid==ask), and NaN (IEEE makes the comparisons
  False). A missing coin returns `None` from `snap`. Correct.
- **Stale book drops the *whole* RT, not a half-RT (H1):** `snap is None` pops the rt key
  (`:117`); a later `on_close` for a dropped entry finds `rt is None` and no-ops (`:99`). No
  half-marked round-trip can persist. Correct (with the documented liquidity-bias caveat).
- **Restart `drop_due_before` (H2):** boundary `item[0] < cutoff` (`:138`) keeps a due==cutoff
  item (mark-now) and drops strictly-past ones; an orphaned exit item whose key was popped is
  skipped gracefully by `rt is None` at `:113`. Correct in isolation. (Caller must rebuild the
  heap from durable state *and then* call it — outside this module, unverified.)
- **Heap ordering / mis-pairing (H6):** tuple `(due, seq, …)` with monotonic `seq` (`:82,87`)
  makes `(due,seq)` unique, so ties never compare the string fields and `on_open` always
  precedes its `on_close` (entry seq < exit seq) → entry marked before exit checked. Markouts
  keyed on `(wallet,coin,rid)` not `entry_t`, so same-ms flips don't collide. No starvation /
  no entry-exit mis-pairing. Correct.

## Could not rule out
- The live run loop that calls `process_due(now, book)` is not in the repo (SHADOW), so the
  exact `now` source and any external lateness drop around it are unverified — F1 is argued from
  the module contract. If/when that loop is built, confirm it both passes wall-clock `now` and
  adds the F1 due-vs-now drop.
- Whether the upstream Ingest tags reconnect-backfill round-trips as `source=candle` before they
  reach the scheduler (the scheduler itself has no forward-only guard and defaults
  `FinalRoundtrip.source="live"`, `:75`).
