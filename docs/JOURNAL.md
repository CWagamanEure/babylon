# Babylon — Durable State Journal (design v3)

The engine's crash-recovery + trade-record layer. **v3** folds in a *second*
four-lens audit of the v2 design, which caught regressions v2 introduced.

**Build scope — paper path first.** The journal is being built for the **paper**
engine, where it is fully correct and testable: full fills (no partials), no
exchange (recovery is snapshot+replay only), no funding, no orphans. Items that
only arise on the **live** path are marked **[LIVE]** below and are *required
before the live executor*, not before paper.

Engine prerequisites (the journal needs these; valuable on their own):
- **Quantize order sizes** to a lot precision at the reconciler so all booked
  state is exact at ≤8 dp → `*_e8` snapshotting is lossless. Without this,
  rounding N per-strategy positions ≠ rounding the net once → the
  `ledger-net == executor-net` invariant fails on the first post-recovery fill.
- **Split `_attribute`** into `compute_shares(fill_size) → vector` + `apply(vector)`
  so the engine has a share vector to journal (paper: intent == realized).
- **Run-scope the cloid** (counter resets to 0 per process → cross-run collisions).
- **Drop quote-less orders before** the pre-send commit (else PENDING orphans).

## Why

The exchange knows only the **net** position — not which strategy owns what, what
each EdgeModel learned, the order→strategy attribution of in-flight orders, or the
net-risk high-water/halt latches. All of that is in-memory today, so a restart
silently destroys per-strategy PnL attribution and all learning, and an order in
flight during a crash can be double-submitted or mis-attributed. The journal makes
a restart a non-event and yields a queryable trade/PnL history as a byproduct.

## Scope: durable vs recomputable

**Durable (journaled):** fills (attributed to a strategy) · orders + the
**resolved per-strategy share vector** · per-strategy ledger · EdgeModel **observed
returns** + prior_strength · net-risk high-water + halt · **engine quarantine set**
(a safety latch like the halt) · run metadata.

**Recomputable (NOT journaled — rebuilt on boot):** rolling indicators · dashboard
metrics · book exposure · **EdgeModel prior draws** (regenerated from the seed —
only the *observed* deque is durable; this also bounds snapshot size).

## Storage choice & durability

**SQLite in WAL mode**, single file, **separate** from the market-data ParquetStore
(transactional/recovery-critical vs high-volume/analytical).

- `journal_mode=WAL; foreign_keys=ON; busy_timeout=5000; auto_vacuum=INCREMENTAL`.
- **`synchronous=FULL`** (NOT `NORMAL`). In WAL, `NORMAL` does *not* fsync on
  commit — it's corruption-safe but a power-loss can lose the last committed
  transactions, which voids the whole "journal the order *before* sending it"
  guarantee. FULL fsyncs each commit (~ms; the design accepts correctness > a few
  ms). A failed/timed-out pre-send commit means **do not send the order**.
- **Money as scaled integers** (`*_e8` = value × 10⁸, exact for Hyperliquid's
  precision). Integer `SUM`/`ORDER BY` are exact and sortable (no float, no
  lexical-TEXT bug). Cross-products (notional = size×price) are computed in Python
  `Decimal` to avoid 64-bit overflow; SQL aggregates only single columns. The
  engine's own decisions always read `Decimal`, never a derived float.

## Concurrency model

A **single dedicated writer thread** owns the one connection — `ThreadPoolExecutor(max_workers=1)`,
every journal call is `await loop.run_in_executor(self._writer, fn)`. NOT
`asyncio.to_thread` (an arbitrary-thread pool can't safely share a stateful SQLite
connection and breaks WAL's single-writer/transaction continuity). A **kernel file
lock** (`flock`/`fcntl`, acquired at open *before* the recovery read) refuses a
second writer — NOT a time-based heartbeat, which an `fsync`/GC stall can make
declare a live writer dead → split-brain double-orders on real money.
`journal_size_limit` set;
analytics readers use a separate read-only connection and keep transactions short
so checkpoints aren't starved; the pre-send commit **retries on `SQLITE_BUSY` and
blocks the send on failure**.

## Schema

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version, scale

CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, started_ms INTEGER NOT NULL, network TEXT NOT NULL,
  config_version TEXT, code_hash TEXT, seed INTEGER, notes TEXT
);

CREATE TABLE strategies (strategy TEXT PRIMARY KEY, first_seen_ms INTEGER NOT NULL);

-- Append-only event log: source of truth. seq is monotonic + never-reused
-- (AUTOINCREMENT, because we prune) but NOT gap-free → replay is an ordered scan
-- `WHERE seq > X`, never an "expect seq+1" contiguity check.
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  ts_ms INTEGER NOT NULL, wall_ms INTEGER NOT NULL, tick INTEGER,
  kind TEXT NOT NULL CHECK (kind IN
    ('ORDER','FILL','SIGNAL','HALT','RESET','QUARANTINE','EXPOSURE','FUNDING','SNAPSHOT','RECONCILE')),
  coin TEXT, strategy TEXT, cloid TEXT,
  payload TEXT NOT NULL
);
CREATE INDEX idx_events_run_kind ON events(run_id, kind, seq);
CREATE INDEX idx_events_cloid ON events(cloid);

-- Orders. Surrogate order_id is the identity (NOT the cloid — the engine now emits
-- a unique cloid per order, but identity must not depend on that). attribution is
-- the RESOLVED per-strategy share vector, written before send.
CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL REFERENCES events(seq),
  cloid TEXT NOT NULL,                       -- exchange client id (indexed, not unique-by-design)
  ts_ms INTEGER NOT NULL, coin TEXT NOT NULL,
  size_e8 INTEGER NOT NULL,                  -- signed net delta
  price_e8 INTEGER,                          -- NULL = marketable/taker
  reduce_only INTEGER NOT NULL CHECK (reduce_only IN (0,1)),
  tif TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','SENT','PARTIAL','FILLED','CANCELED','FAILED')),
  filled_e8 INTEGER NOT NULL DEFAULT 0,      -- ABSOLUTE cumulative (set, never +=) → replay-safe
  shares TEXT NOT NULL                       -- JSON {strategy: resolved_share_e8}
);
CREATE INDEX idx_orders_cloid ON orders(cloid);
CREATE INDEX idx_orders_status_coin ON orders(status, coin);

-- Fills: one row per attributed strategy share. UNIQUE(seq,strategy) makes replay
-- an idempotent no-op (INSERT … ON CONFLICT DO NOTHING). exch_fill_id preferred
-- when live (survives cross-run replay / partial-fill streams).
CREATE TABLE fills (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL REFERENCES events(seq),
  order_id INTEGER REFERENCES orders(order_id),
  exch_fill_id TEXT,
  ts_ms INTEGER NOT NULL, coin TEXT NOT NULL,
  strategy TEXT NOT NULL REFERENCES strategies(strategy),
  size_e8 INTEGER NOT NULL, price_e8 INTEGER NOT NULL,
  fee_e8 INTEGER NOT NULL DEFAULT 0, funding_e8 INTEGER NOT NULL DEFAULT 0,
  UNIQUE (seq, strategy)
);
CREATE INDEX idx_fills_strategy_ts ON fills(strategy, ts_ms);
CREATE INDEX idx_fills_coin_ts ON fills(coin, ts_ms);
CREATE INDEX idx_fills_run ON fills(run_id);

-- Snapshots: split header + per-component parts so a snapshot only rewrites what
-- changed (ledger far more often than the 5k-deque edges). Tagged with the
-- on-loop last_applied_seq (see Write path).
CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  applied_seq INTEGER NOT NULL,              -- replay events WHERE seq > this
  ts_ms INTEGER NOT NULL
);
CREATE TABLE snapshot_parts (
  snap_id INTEGER NOT NULL REFERENCES snapshots(id),
  component TEXT NOT NULL,                    -- 'ledger'|'edge'|'netrisk'|'engine'
  scope TEXT NOT NULL,                        -- e.g. 'BTC/strat' for edges, '' otherwise
  state BLOB NOT NULL,                        -- compact binary (msgpack / np.tobytes), not JSON
  PRIMARY KEY (snap_id, component, scope)
);
CREATE INDEX idx_snapshots_applied ON snapshots(applied_seq);

-- Pure derived cache of current positions (NOT a source of truth; never read in
-- recovery). Rewritten in the SAME transaction as each snapshot, tagged with seq.
CREATE TABLE positions (
  strategy TEXT NOT NULL, coin TEXT NOT NULL,
  size_e8 INTEGER NOT NULL, entry_e8 INTEGER NOT NULL, realized_e8 INTEGER NOT NULL,
  applied_seq INTEGER NOT NULL,
  PRIMARY KEY (strategy, coin)               -- run-agnostic: positions carry across runs
);
```

## Write path & ordering guarantees

1. Engine forms a tick's orders (each with a unique cloid) and their **resolved**
   per-strategy share vectors (the exact shares `_attribute` will book).
2. **One transaction**: insert all PENDING `orders` rows for the tick (+ an `ORDER`
   event) and **COMMIT with `synchronous=FULL` (fsync)** — *before* any send.
   Batching the tick's orders into one fsync'd commit avoids N serial fsyncs on the
   hot path. A failed commit aborts the sends.
3. Send each order (or take the paper fill).
4. On fill, **one transaction**: append a `FILL` event, `INSERT … ON CONFLICT DO
   NOTHING` the per-strategy `fills` rows, set `orders.filled_e8`/`status`
   **absolutely** — COMMIT.
5. Apply to the in-memory ledger and **advance `last_applied_seq`** (on the loop).

Apply (5) always follows a durable commit (4), so everything ≤ `last_applied_seq`
is both durable and applied — the exact cut recovery needs.

## Snapshots

Taken **on the event loop at a tick boundary** (no in-flight fill): in one
synchronous step (no `await` between) copy ledger/edges/netrisk/quarantine/`_edge_dir`
into a plain struct AND capture `last_applied_seq`, then **serialize + write off the
loop** (writer thread) in one transaction that also rewrites `positions`. Tag with
that `last_applied_seq` — never DB `max(seq)`.

**All components share one `applied_seq` cut (single-cut snapshot).** v2 wrote
edges on a slower cadence with per-component parts, but a single replay cursor
can't serve parts cut at different seqs (it silently drops EdgeModel updates in the
gap, and pruning deletes the events the lagging part still needs). Every snapshot
rewrites all parts at one cut. (Per-component cursors for a slow-edge cadence is a
deferred optimization, not v1.) The prior draw array is NOT serialized — it's
regenerated from the seed; only `_observed` + `prior_strength` are durable.
Encode the edge arrays with `np.ndarray.tobytes()` (releases the GIL), msgpack for
the small structs.

## Recovery (boot, async — before the run loop)

1. Open DB (acquire the file lock first), check `meta.schema_version`, migrate.
2. Load the latest snapshot by **global `MAX(applied_seq)` across all run_ids**
   (positions carry across runs; filtering by current run_id would make every
   prior-run position look like an orphan). **Gate on a roster+seed fingerprint**:
   priors are regenerated from `rng.spawn` by strategy construction order, so if
   the strategy roster/order or `seed` differs from the snapshot's, restored
   observations would sit on a differently-seeded prior — refuse/repair on
   mismatch. Rebuild ledger / edges (observed deque over the re-seeded model) /
   high-water / halt / quarantine / `_edge_dir`.
3. **Replay** events `WHERE seq > applied_seq` (ordered scan). Applies must be a
   strictly **seq-ordered single-consumer** sequence and `last_applied_seq`
   advances only contiguously; skip non-mutating kinds explicitly.
4. **[LIVE] Reconcile with the exchange:** fetch positions, open orders, recent
   `userFills`, and **`userFunding`** (dedupe catch-up by `(coin, fundingTime)`).
   Resolve each `PENDING/SENT` order by cloid via `userFills` (incl. *partial*).
   `exch_fill_id`-dedupe so a journaled-then-also-returned fill isn't double-booked.
   An **orphan** (exchange exposure no ledger explains) is adopted into a synthetic
   **house** ledger — itself a first-class participant in `_attribute` and counted
   in Net Risk's net/gross — and flattened reduce-only. The journal>exchange
   direction writes the per-strategy shortfall into the house ledger and forces
   ledger-net to exchange truth (reduce-only can't fix it alone).
5. **Paper recovery** (no exchange backstop): after snapshot-load + replay,
   **set the paper executor net := `ledger.net_position(coin)`** for every coin —
   a single derivation from the replayed ledger (NOT a separately-snapshotted,
   independently-rounded executor net, which would differ by a ULP and trip the
   invariant; and replay carries fills past the snapshot cut that a snapshot-only
   executor net would miss → double-booking). Mark stale PENDING paper orders
   `FAILED`. Because all booked sizes are lot-quantized (engine prerequisite),
   `ledger.net == executor.net` reproduces exactly. Correctness rests on replay
   determinism — covered by a "crash-after-submit replay == in-tick booking" test.

## Engine integration

- `_tick` becomes **async** so the pre-send commit can be `await`ed; ticks are
  awaited sequentially after the cadence sleep (never reentrant), and awaiting the
  off-loop write actually frees the loop to service the feed.
- `_attribute` is the single producer of shares; it emits the resolved vector to
  `record_order` (pre-send) and `record_fill`. Recovery replays that stored vector
  — it never recomputes attribution from live ledger state (which could diverge via
  a changed scale, a quarantine, or residual ordering).
- `to_state()/from_state()` added to `Ledger`, the `EdgeModel` Protocol + impls
  (rebuild the `deque(maxlen=…)`!), and `NetRiskManager`; the engine snapshots its
  `_quarantined` latch too.
- Conventions: structlog, Decimal/Decimal-as-integer money, off-loop discipline.

## Open / deferred

- Exchange cloid format (128-bit) + the live executor's nonce/signer pairing.
- EdgeModel sufficient-statistic snapshot (vs raw deque) if size demands.
- Retention window + incremental-vacuum cadence; prune only events below the
  oldest retained snapshot, and only *after* that snapshot is durably synced.
- Backup via the SQLite backup API / `VACUUM INTO` (never `cp` a live WAL db).
