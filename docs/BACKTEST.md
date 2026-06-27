# Backtester — architecture plan (v1, for audit)

## 1. Goal & honest scope

Run the **same strategy code** that paper/live run, over archived L2 history, to:
1. **Iterate fast** — evaluate a signal over months of data in seconds, not days of paper.
2. **Seed priors** — export per-(strategy, coin) `EdgeModel` state to start paper/live warm.
3. **Validate the three-mode bet** — prove a strategy moves between backtest/paper/live by
   swapping only `Executor` + `Clock`, unchanged.

### What a backtest is NOT (locked honesty constraints)
The S3 archive (and our `record` captures) are **L2-only — no trade prints, no funding,
no oracle/mark**. Therefore:
- A backtest **seeds a weak prior; it is not validation.** Numbers are a sanity check and a
  prior, never proof of edge. The CLI/report must say this in words.
- **No funding** is modeled (we can't see it). Perp carry is omitted, not faked. Flagged in
  the report so a funding-sensitive strategy isn't trusted.
- **Fills are an approximation** against the *visible book*, with **no queue/maker model**
  (taker only, same ceiling as `PaperExecutor`) and **no trade-flow** to confirm fills.
- Results are reported through the **same stats layer** as paper (log-growth, max-DD, the
  gate) so the yardstick is identical — but the gate's "real" verdict on backtest data is
  advisory, given the above.

## 2. Design principle — reuse the engine, replace only the driver

`engine._tick()` is the entire pipeline (strategies → sizing → per-strategy risk → net-risk
scale → reconcile → orders → fills → attribute → measure). It is **already decoupled from
the feed** — the WebSocket only appears in `engine.run()`. So the backtester does **not**
re-implement any trading logic. It is a deterministic **driver** that:

- feeds replayed L2 into the same `MarketView`,
- advances a `SimClock` by **event time**,
- calls `engine._tick()` on the **strategy cadence in simulated time**,
- and lets a `BacktestExecutor` fill against the replayed book via a shared `FillModel`.

```
Parquet L2  ──►  L2Replay (k-way merge, event-time order)
                    │  per event: (time_ms, coin, L2Book w/ depth)
                    ▼
        Backtester driver loop ───────────────────────────────┐
          update MarketView(coin, bid, ask)   (book ≤ t only)  │
          set BacktestExecutor.book[coin] = depth              │
          clock.advance_to(t)                                  │
          while t >= next_tick:                                │
              engine._tick()  ──►  BacktestExecutor.submit ────┘  (fills vs held book)
              next_tick += interval_ms
                    │
                    ▼
        engine._perf (PerformanceMonitor) ──► metrics + report + prior export
```

### Why a separate `Backtester` and not a swappable driver inside `run()`
`run()`'s loop is `await asyncio.sleep(interval)` on the **wall clock** — fundamentally the
wrong cadence for replay (we tick on *simulated* time, possibly thousands of ticks/second of
wall time). A separate synchronous driver is cleaner and keeps `run()` untouched. The small
shared piece — the strategy `on_start()` startup sequence — is extracted into an engine
method both call.

## 3. Components (new)

### `data/replay.py` — `L2Replay`
- Reads `{data_dir}/l2Book/{coin}/{day}/*.parquet` for the requested coins + date range.
- **Streaming k-way merge** across coins by the record's own `time` (ascending), so memory is
  bounded by the number of coins, not the history length. Uses `pl.scan_parquet` per
  coin/day, sorted, then a heap-merge of per-coin iterators. Ties broken by a stable
  (coin-order) key for determinism.
- Yields `ReplayEvent(time_ms, coin, book)` where `book` carries top-of-book **and depth**
  (the `bid_px/bid_sz/ask_px/ask_sz` arrays) for the fill model.
- Validates monotonic time; skips thin/cross/empty books (logs a count).

### `engine/clock.py` — reuse `SimClock` (exists)
Advanced only forward via `advance_to`; the driver is the sole writer.

### `execution/fill_model.py` — `FillModel` (shared by paper + backtest)
- **Versioned** (`FILL_MODEL_VERSION`) and pure: `fill(order, book, *, now) -> Fill | None`.
- **Taker, conservative:**
  - Cross the spread (buy lifts ask, sell hits bid).
  - **Walk the book** for size > top level: VWAP across consumed levels → models slippage
    that a top-of-book paper fill hides.
  - If the order exhausts visible depth, **partial-fill** to available size (don't invent
    liquidity) and report the partial.
  - Optional fixed slippage/fee bps add-on (taker fee already handled in edge accounting;
    fee here is the *execution* cost on the fill price).
- `PaperExecutor` is refactored to call the **same** `FillModel` (top-of-book degenerate
  case) so paper and backtest fills agree by construction — single source of truth.

### `execution/backtest.py` — `BacktestExecutor`
- Implements the `Executor` Protocol (`net_position`, `net_positions`, `set_position`,
  `submit`). Holds the **current depth book per coin**, set by the driver before each tick.
- `submit(order, quote, now)` → delegates to `FillModel.fill(order, self._book[coin], now)`;
  updates net position by the (possibly partial) filled size.
- Records realized execution cost for the report.

### `backtest/runner.py` — `Backtester`
- Owns: the constructed `Engine` (with `BacktestExecutor` + `SimClock` + a `NullFeed`),
  the `L2Replay`, the cadence `interval_ms`.
- Loop as in §2. Look-ahead-safe ordering (see §4).
- On completion: flush, compute `engine.performance` metrics, run the gate on each
  strategy's unit-return series, export `EdgeModel` state, return a `BacktestResult`.

### `NullFeed`
A no-op `Feed` satisfying the constructor (never `run()`-d in backtest). Or make `feed`
optional in the engine constructor for backtest. (Decision flagged for audit.)

### `cli.py` — `backtest` command
`babylon backtest --coin BTC --start 20260601 --end 20260607 --fast 10 --slow 30
--interval-ms 2000 --seed 0 [--export-priors path]` → prints the report, optionally writes
the prior-seed file. Prints the **honesty banner** (L2-only, no funding, not validation).

## 4. Correctness — look-ahead bias (the section that matters most)

The cardinal backtest sin is letting a decision at time *T* see data from *> T*. Guards:

1. **MarketView holds only books with `time ≤ T`.** The driver updates `MarketView` strictly
   from events as they are consumed in time order; the tick at `next_tick` runs *after* all
   events with `time ≤ next_tick` and *before* any later event. No future book is visible.
2. **Fills do not use future liquidity.** A tick decided at `T` fills against the book state
   **as of `T`** (the last event ≤ T) — never a later, more-favorable book. This matches
   paper's "fill at the quote you saw," and is the *optimistic* bound; we deliberately make
   the fill model **pessimistic** (cross + walk-the-book slippage + optional bps) so the
   same-instant fill isn't a free lunch.
3. **Cadence is simulated time, not arrival count** — ticking "every K snapshots" would let
   bursty coins tick more; we tick every `interval_ms` of `SimClock` time so cadence is
   uniform and reproducible regardless of data density.
4. **Warmup** — a strategy that needs N bars simply produces no signal until it has seen them
   (it accumulates from ticks); the report notes the warmed-in start so early flat ticks
   don't dilute metrics. Optionally a `--warmup` skip before metrics start accruing.
5. **Partial / no-fill realism** — orders beyond visible depth partial-fill; the reconciler
   re-attempts next tick (it already diffs target vs actual), so no synthetic instant fills.

## 5. Determinism

Same inputs → byte-identical results: seeded `np.random.Generator` (already threaded through
sizing), no wall-clock anywhere in the path (SimClock only), stable tie-break in the merge,
ordered strategy iteration (the sorted-name RNG spawn already landed). A `test` asserts two
runs with the same seed produce identical equity curves + metrics.

## 6. Outputs

- **`BacktestResult`**: per-strategy + account `Metrics`, the gate `GateResult` per strategy,
  fill stats (count, avg slippage bps, partial-fill rate), coins/date range, warmup, and the
  **honesty flags** (no-funding, L2-only).
- **Prior export** (`--export-priors`): per-(strategy, coin) `EdgeModel.to_state()` → JSON,
  loadable by paper/live to start warm (with a provenance stamp: data range, fill-model
  version, "weak prior" tag).
- **Report**: a Rich table + the honesty banner.

## 7. Integration / refactors needed (small)

- Extract the engine **start sequence** (`on_start` fan-out) into `engine.start()` so the
  `Backtester` and `run()` share it.
- Refactor `PaperExecutor` onto the shared `FillModel` (top-of-book case) — keeps paper and
  backtest fills identical; guard with a regression test that paper behavior is unchanged.
- `feed` optional (or `NullFeed`) in the engine constructor for backtest construction.
- No change to `_tick`, sizing, risk, ledger, journal, or stats — all reused as-is.

## 8. Explicitly OUT of scope (this increment)

Funding/carry (no data); trade-flow-confirmed or maker/queue fills (L2-only ceiling); the
promotion lifecycle (separate increment — backtest *feeds* it via priors + the gate but does
not promote); walk-forward / cross-validation harness (future, once single-pass is trusted);
parameter optimization/sweeps (future driver on top of single-run).

## 8b. POST-AUDIT REVISIONS (v1 scope — four-lens swarm)

The audit reshaped v1. Binding decisions:

- **NO partial fills in v1** (all four auditors — Critical). The engine computes the
  share split from the FULL `order.size` before submit and hard-stops on
  `ledger != executor`; a partial both corrupts `_compute_shares` attribution
  (same-sign-first is an unbuilt TODO) and halts the run. v1 `BacktestExecutor`:
  **full-fill-or-no-fill**. Fill fully at walk-the-book VWAP iff the order consumes
  ≤ `max_depth_fraction` of visible depth; otherwise **return None** (no fill) and
  let the reconciler re-attempt. Keeps `_tick` byte-untouched; caps the free
  book-sweep (fill-H3); the "couldn't execute" case is reported honestly.
- **NO prior export to live in v1** (C2 + H1 + H4). Exporting `EdgeModel.to_state()`
  ships a high-precision posterior that dominates the live likelihood, the edge
  series is mid-based/spread-blind (optimistic), and single-pass fast iteration is
  a p-hacking engine. v1 is **report-only**. Prior export is a separate, gated
  step: numerically-weak export (cap n_eff / shrink / sign-only) + a held-out tail
  window + a trial counter stamped on any export.
- **Peek-based, gap-aware tick scheduling** (correctness-C1 = data-H2). Schedule by
  peeking the next event's time: fire every tick with `next_tick < next_event.time`
  BEFORE consuming it. On an inter-event gap > `max_gap_ms` (reuse ~30s), **suppress
  catch-up ticks** — jump `next_tick` to the new event time and mark a discontinuity;
  never replay the empty grid. Feed strategies/edges only on genuinely new books.
- **Per-coin staleness guard** (correctness-H2). Track last-update ms; if
  `now - last_update > max_staleness_ms`, treat the coin as ABSENT (drop from
  `marks`, no signal, no fill) — same as a missing quote.
- **Zero-latency fill kept, with a slippage haircut + loud caveat** (correctness-H1).
  True `T+δ` event-based fill is deferred to v1.1; v1 fills at book@T (as paper does)
  plus a configurable `slippage_bps` haircut, and the report flags zero-latency.
- **Edge series spread charge** (fill-H1). `_update_edges` charges only `TAKER_FEE`
  on turnover and is otherwise mid-to-mid; add the **half-spread on turnover** so the
  edge metric (and any future prior) reflects real round-trip cost. NOTE: this is not
  a double-count — fee lands once each in two distinct series (edge vs ledger PnL)
  consumed by two distinct gates, never summed; the defect was the edge UNDER-charging.
- **Depth-consumption cap + reporting** (fill-H3). `max_depth_fraction` per fill;
  `BacktestResult` reports avg/max fraction-of-visible-depth consumed with a loud
  warning above threshold (large-Kelly configs can't masquerade as realistic).
- **Data layer** (data C1/C2/H1/H3): per-coin source advances **one day-partition at
  a time** (bounded memory); within a coin/day **union-sort all files by `time`** then
  **dedup `(time, ver_num)`** (filenames are wall-clock, partitions are event-day —
  never trust file order; backfill doesn't dedup); total merge key
  `(time, ver_num, coin_index, row_index)` with a row-index fallback since `ver_num`
  is null for live captures; the replay `book` is a **slim float struct** (raw arrays,
  no Decimal/pydantic) for speed; guard null/crossed/empty archive books; day
  enumeration converts `YYYYMMDD`→`YYYY-MM-DD`, gmt, inclusive end, missing-day-safe;
  monotonic assert is `≤` not `<`; 20-level depth is a documented fidelity ceiling.
- **Architecture** (arch-H3/M4/M5/M6): extract a `Feed` Protocol + `NullFeed` (mypy-
  clean, `run()` unguarded); extract `engine.start()` preserving recover→begin_run→
  on_start order; the driver calls `_evaluate_kills` on the snapshot cadence for
  three-mode fidelity; the executor uses its OWN depth book (attribution is
  price-independent — `_compute_shares` never reads price, verified) set atomically
  from the SAME replay event as `MarketView`; the step-5 strategy signals off
  **top-of-book/mid only** (depth lives in the executor, unreachable by strategies by
  design) and is an **aggressive taker** (taker-only inverts the cost sign for passive
  mean-reversion — fill-H2).
- **Honesty banner + report flags**: L2-only, no funding (+ report net-exposure
  coin-hours so the omission is boundable), zero-latency, taker-only, mid-based edge,
  NO prior export, no liquidation/margin model (ruinous paths not terminated),
  selection/multiple-testing caveat. Mark-at-mid saw-tooths short-horizon vol
  (depresses Sharpe) but log-growth/max-DD stay correct — caveat only.

## 9. Build order

1. `FillModel` + refactor `PaperExecutor` onto it (+ regression test paper unchanged).
2. `L2Replay` (streaming merge) + tests on synthetic Parquet.
3. `BacktestExecutor` + `NullFeed` + `engine.start()` extraction.
4. `Backtester` driver + determinism test + a small end-to-end on recorded/synthetic data.
5. One **real** strategy (momentum or mean-reversion on the book) to exercise it on something
   worth measuring.
6. `backtest` CLI + report + prior export.
7. Full suite + mypy + ruff green; commit per step.
