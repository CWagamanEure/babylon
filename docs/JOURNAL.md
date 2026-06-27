# Babylon — Durable State Journal (design)

The engine's crash-recovery + trade-record layer. Design only; not yet built.

## Why

The exchange knows only the **net** position. It does not know which strategy
owns what, what each EdgeModel has learned, the `cloid → strategy` attribution of
in-flight orders, or the net-risk high-water mark. All of that is in-memory today,
so a restart silently destroys per-strategy PnL attribution and all learning, and
an order in flight during a crash can be double-submitted or mis-attributed. The
journal makes a restart a non-event and yields a queryable trade/PnL history as a
byproduct.

This is the audit's CRITICAL "durable state undesigned" finding (see
`ARCHITECTURE.md` — *Durable state (C1)*).

## Scope: durable vs recomputable

**Durable (must be journaled):**
- fills (the trade record), with the strategy each share is attributed to;
- orders + their `cloid → {strategy: requested_delta}` map, written **before send**;
- per-strategy ledger (position, avg entry, realized PnL);
- EdgeModel state (observed unit returns + prior_strength) per (strategy, coin);
- Net-risk **high-water mark** and **halt-latch** (so a DD kill survives restart);
- run metadata (config/code version, seed, network).

**Recomputable (NOT journaled — rebuilt on boot):**
- rolling indicators (replay from candles/archive),
- dashboard metrics (fold from fills),
- book exposure (recompute from positions).

## Storage choice

**SQLite in WAL mode**, a single file, **separate** from the market-data
`ParquetStore` (different durability needs: that one is high-volume / analytical /
buffered; this is low-volume / transactional / fsync-critical). SQLite gives ACID,
crash-safety, zero ops, and free SQL analytics over the trade history.

- `PRAGMA journal_mode=WAL; synchronous=NORMAL; foreign_keys=ON; busy_timeout=5000;`
- **Money is stored as TEXT** (lossless `Decimal` string), never `REAL` — matches
  the project's Decimal-in-execution rule. Comparisons that need ordering use the
  numeric value, not lexical TEXT (see Open Questions).
- WAL allows the engine (single writer) to write while analytics tools read.

## Schema

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version, ...

CREATE TABLE runs (
  run_id        TEXT PRIMARY KEY,        -- uuid per engine start
  started_ms    INTEGER NOT NULL,
  network       TEXT NOT NULL,
  config_version TEXT,                   -- strategy manifest version
  code_hash     TEXT,                    -- git sha
  seed          INTEGER,
  notes         TEXT
);

-- Append-only event log: source of truth; total order via seq.
CREATE TABLE events (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id   TEXT NOT NULL REFERENCES runs(run_id),
  ts_ms    INTEGER NOT NULL,             -- engine clock (ctx.now)
  wall_ms  INTEGER NOT NULL,             -- wall clock
  tick     INTEGER,                      -- tick index within run
  kind     TEXT NOT NULL,                -- ORDER|FILL|SIGNAL|HALT|RESET|QUARANTINE|EXPOSURE|FUNDING|SNAPSHOT|RECONCILE
  coin     TEXT,
  strategy TEXT,
  cloid    TEXT,
  payload  TEXT NOT NULL                 -- JSON detail
);
CREATE INDEX idx_events_cloid ON events(cloid);
CREATE INDEX idx_events_kind  ON events(kind);

-- Orders: written BEFORE send. cloid is the idempotency key; attribution lets a
-- crash-time in-flight fill be booked to the right strategies on recovery.
CREATE TABLE orders (
  cloid       TEXT PRIMARY KEY,          -- deterministic (coin, quantized target)
  run_id      TEXT NOT NULL REFERENCES runs(run_id),
  seq         INTEGER NOT NULL REFERENCES events(seq),
  ts_ms       INTEGER NOT NULL,
  coin        TEXT NOT NULL,
  size        TEXT NOT NULL,             -- signed net delta (Decimal text)
  price       TEXT,                      -- NULL = marketable/taker
  reduce_only INTEGER NOT NULL,
  tif         TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING|FILLED|PARTIAL|CANCELED|FAILED
  filled_size TEXT NOT NULL DEFAULT '0',
  attribution TEXT NOT NULL              -- JSON {strategy: requested_delta}
);
CREATE INDEX idx_orders_status ON orders(status);

-- Fills: denormalized trade record (queryable), one row per attributed share.
CREATE TABLE fills (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id   TEXT NOT NULL REFERENCES runs(run_id),
  seq      INTEGER NOT NULL REFERENCES events(seq),
  cloid    TEXT REFERENCES orders(cloid),
  ts_ms    INTEGER NOT NULL,
  coin     TEXT NOT NULL,
  strategy TEXT NOT NULL,
  size     TEXT NOT NULL,                -- signed, this strategy's share
  price    TEXT NOT NULL,
  fee      TEXT NOT NULL DEFAULT '0',
  funding  TEXT NOT NULL DEFAULT '0'
);
CREATE INDEX idx_fills_strategy ON fills(strategy);
CREATE INDEX idx_fills_coin_ts  ON fills(coin, ts_ms);

-- Snapshots: periodic full recoverable state, tagged with the journal offset it
-- reflects. Recovery = load latest snapshot, then replay events WHERE seq > this.
CREATE TABLE snapshots (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq    INTEGER NOT NULL,
  ts_ms  INTEGER NOT NULL,
  state  TEXT NOT NULL                   -- JSON: ledger, edges, high_water, halt, ...
);
CREATE INDEX idx_snapshots_seq ON snapshots(seq);

-- Denormalized current positions, refreshed at snapshot time (convenience query).
CREATE TABLE positions (
  strategy   TEXT NOT NULL,
  coin       TEXT NOT NULL,
  size       TEXT NOT NULL,
  entry_px   TEXT NOT NULL,
  realized   TEXT NOT NULL,
  updated_ms INTEGER NOT NULL,
  PRIMARY KEY (strategy, coin)
);
```

## Write path & ordering guarantees

The correctness lives in the *order* of writes around sending an order:

1. Engine builds an order with **deterministic** `cloid` and attribution map `A`.
2. **Journal `orders` row (status=PENDING, attribution=A) and COMMIT (fsync).**
   This happens **before** the order is sent.
3. Send to exchange (or take the paper fill).
4. On fill: in ONE transaction — append a `FILL` event, insert `fills` rows
   (one per attributed strategy share), update `orders.status/filled_size` — COMMIT.
5. Apply to the in-memory ledger.

Each order is its own transaction; a tick may produce several. The
`A`-before-send rule is what lets recovery attribute a fill that landed during a
crash and avoid double-submission (the cloid is idempotent on the exchange).

## Snapshot strategy

Write a full-state snapshot every `N` events or `T` seconds, tagged with the
current `seq`. Snapshots bound replay length; old snapshots/events can be pruned
beyond a retention window. EdgeModel state can be large (up to ~5k observed
returns × strategy × coin) — snapshot it compactly (see Open Questions).

## Recovery flow (boot)

1. Open DB; check `meta.schema_version`; migrate if needed.
2. Load the **latest snapshot** → reconstruct in-memory state (ledger, edges,
   high-water, halt-latch).
3. **Replay** events with `seq > snapshot.seq`, applying each idempotently.
4. **Reconcile with the exchange** (live only): fetch actual positions, open
   orders, and recent fills. For every `orders` row still `PENDING`, resolve by
   `cloid` against the exchange (filled → book it via `A`; absent → safe to
   re-send or cancel). Compare journal-derived net vs exchange net per coin; on
   divergence, log + halt (the engine's invariant assertion).
5. Start a new `runs` row and resume.

## Engine integration

- Journal writes are blocking I/O → run **off the event loop** (`asyncio.to_thread`)
  like the ParquetStore, so they never stall the feed. The pre-send `orders`
  commit is `await`ed before the order is sent (correctness > a few ms latency).
- Per-tick events may be **batched** into one transaction; the pre-send order
  commit is the exception that must be its own synchronous-before-send write.
- Components expose `to_state()` / `from_state()` for snapshot + restore:
  `Ledger`, `BootstrapEdgeModel`, `NetRiskManager` (high-water, halt).
- Single writer (the engine); analytics readers use a separate read-only
  connection (WAL makes this safe).

## Interface sketch

```python
class Journal:
    def __init__(self, path: Path): ...                  # opens WAL, runs migrations
    async def begin_run(self, meta: RunMeta) -> str: ...
    async def record_order(self, order: Order, attribution: dict[str, Decimal]) -> None: ...  # pre-send, fsync
    async def record_fill(self, fill: Fill, *, fee: Decimal, funding: Decimal) -> None: ...
    async def record_event(self, kind: str, payload: dict, **cols) -> int: ...
    async def snapshot(self, state: EngineState) -> None: ...
    def recover(self) -> EngineState | None: ...         # latest snapshot + replay
    def pending_orders(self) -> list[OrderRow]: ...      # for boot reconciliation
```

## Open questions / deferred

- **Decimal ordering in SQL**: TEXT money preserves precision but sorts
  lexically; range/aggregate queries need `CAST(... AS REAL)` or a stored numeric
  shadow column. Pick one (shadow `*_num REAL` columns for analytics?).
- **EdgeModel snapshot size**: serialize the raw observed deque, or compress to
  sufficient statistics? (Affects snapshot cost and exactness of restored edge.)
- **Retention / vacuum**: how long to keep events/snapshots; periodic VACUUM.
- **Multi-run position continuity**: positions carry across runs; confirm the
  recovery loads the latest snapshot across `run_id`s, not just the current run.
- **Schema migrations**: versioning + forward-migration policy.
- **Funding rows**: where funding accrual lands (its own event kind + fills.funding).
```
