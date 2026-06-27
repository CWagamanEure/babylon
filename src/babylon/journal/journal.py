"""SQLite durable journal (paper path). See docs/JOURNAL.md v3.

Durability: WAL + ``synchronous=FULL`` (fsync per commit — the pre-send order
commit must be on stable storage before the order is sent). A kernel ``flock``
refuses a second writer (split-brain → double orders). All DB work runs on the
single owning thread (the caller's, or — in the engine — a dedicated
``max_workers=1`` executor); the connection is created lazily on first use so it
binds to that thread.

Money is stored as **scaled integers** (``*_e8`` = value × 10⁸): exact SQL
``SUM``/``ORDER BY``. NEVER multiply two ``_e8`` columns in SQL (silent int→float
overflow) — notional is computed in Python ``Decimal``. Snapshot *state* blobs
hold exact values (the recovery-critical path); the ``_e8`` columns are the
queryable trade record.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

from babylon.core import Order
from babylon.logging import get_logger

log = get_logger("journal")

SCHEMA_VERSION = "1"
_E8 = Decimal(10**8)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_ms INTEGER NOT NULL, network TEXT,
  seed INTEGER, roster TEXT, code_hash TEXT);
CREATE TABLE IF NOT EXISTS strategies (
  strategy TEXT PRIMARY KEY,
  universe TEXT, budget TEXT, status TEXT NOT NULL DEFAULT 'paper',
  first_seen_ms INTEGER NOT NULL, last_seen_ms INTEGER NOT NULL, manifest TEXT);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  ts_ms INTEGER NOT NULL, wall_ms INTEGER NOT NULL, tick INTEGER,
  kind TEXT NOT NULL CHECK (kind IN
    ('ORDER','FILL','SIGNAL','HALT','RESET','QUARANTINE','EXPOSURE','FUNDING','SNAPSHOT','RECONCILE')),
  coin TEXT, strategy TEXT, cloid TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_events_run_kind ON events(run_id, kind, seq);
CREATE TABLE IF NOT EXISTS orders (
  order_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL REFERENCES events(seq),
  cloid TEXT NOT NULL, ts_ms INTEGER NOT NULL, coin TEXT NOT NULL,
  size_e8 INTEGER NOT NULL, price_e8 INTEGER,
  reduce_only INTEGER NOT NULL CHECK (reduce_only IN (0,1)), tif TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING','SENT','PARTIAL','FILLED','CANCELED','FAILED')),
  filled_e8 INTEGER NOT NULL DEFAULT 0, shares TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_inflight_cloid ON orders(cloid)
  WHERE status IN ('PENDING','SENT','PARTIAL');
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  seq INTEGER NOT NULL REFERENCES events(seq),
  order_id INTEGER REFERENCES orders(order_id), exch_fill_id TEXT,
  ts_ms INTEGER NOT NULL, coin TEXT NOT NULL,
  strategy TEXT NOT NULL REFERENCES strategies(strategy),
  size_e8 INTEGER NOT NULL, price_e8 INTEGER NOT NULL,
  fee_e8 INTEGER NOT NULL DEFAULT 0, funding_e8 INTEGER NOT NULL DEFAULT 0,
  UNIQUE (seq, strategy));
CREATE INDEX IF NOT EXISTS idx_fills_strategy_ts ON fills(strategy, ts_ms);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(run_id),
  applied_seq INTEGER NOT NULL, ts_ms INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_snapshots_applied ON snapshots(applied_seq);
CREATE TABLE IF NOT EXISTS snapshot_parts (
  snap_id INTEGER NOT NULL REFERENCES snapshots(id),
  component TEXT NOT NULL, scope TEXT NOT NULL, state BLOB NOT NULL,
  PRIMARY KEY (snap_id, component, scope));
-- Current per-strategy virtual positions (the netting model attributes each
-- share to a strategy; the exchange holds only the net). Run-agnostic (positions
-- carry across runs); refreshed from the ledger at snapshot time. Source of truth
-- is `fills`; this is the queryable "what does each strat hold now" cache.
CREATE TABLE IF NOT EXISTS positions (
  strategy TEXT NOT NULL REFERENCES strategies(strategy), coin TEXT NOT NULL,
  size_e8 INTEGER NOT NULL, entry_e8 INTEGER NOT NULL, realized_e8 INTEGER NOT NULL,
  applied_seq INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
  PRIMARY KEY (strategy, coin));
"""


def to_e8(d: Decimal | None) -> int | None:
    if d is None:
        return None
    return int((d * _E8).to_integral_value(rounding=ROUND_HALF_EVEN))


def from_e8(i: int | None) -> Decimal | None:
    return None if i is None else Decimal(i) / _E8


@dataclass(frozen=True, slots=True)
class OrderRow:
    order_id: int
    cloid: str
    coin: str
    size: Decimal
    status: str
    shares: dict[str, str]  # strategy -> Decimal-as-str (intent)


class Journal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock_fd: int | None = None

    # --- lifecycle (run on the owning thread) --------------------------------

    def connect(self) -> None:
        """Acquire the writer lock and open/initialise the DB. Idempotent."""
        if self._conn is not None:
            return
        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another writer holds {lock_path}") from exc
        conn = sqlite3.connect(str(self._path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO NOTHING",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._lock_fd is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    @property
    def _c(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    # --- writes --------------------------------------------------------------

    def begin_run(
        self, run_id: str, *, started_ms: int, network: str, seed: int,
        roster: list[str], code_hash: str = "",
    ) -> None:
        with self._c:
            self._c.execute(
                "INSERT INTO runs(run_id,started_ms,network,seed,roster,code_hash) "
                "VALUES(?,?,?,?,?,?)",
                (run_id, started_ms, network, seed, json.dumps(sorted(roster)), code_hash),
            )

    def record_event(
        self, kind: str, payload: dict[str, Any], *, run_id: str, tick: int, now: int,
        wall: int, coin: str | None = None, strategy: str | None = None,
    ) -> int:
        """Journal a non-order/fill state transition (QUARANTINE/HALT/RESET) so the
        latch survives a mid-snapshot-interval crash (replayed in recovery)."""
        with self._c:
            return int(self._c.execute(
                "INSERT INTO events(run_id,ts_ms,wall_ms,tick,kind,coin,strategy,payload) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (run_id, now, wall, tick, kind, coin, strategy, json.dumps(payload)),
            ).lastrowid or 0)

    def _ensure_strategy(self, name: str, now: int) -> None:
        self._c.execute(
            "INSERT INTO strategies(strategy,first_seen_ms,last_seen_ms) VALUES(?,?,?) "
            "ON CONFLICT(strategy) DO NOTHING",
            (name, now, now),
        )

    def register_strategy(
        self, name: str, *, universe: list[str], budget: Decimal, status: str, now: int,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        """Upsert the strategy's identity/allocation/status; bumps last_seen."""
        with self._c:  # commit on success, rollback on error (no orphan-into-next-commit)
            self._c.execute(
                "INSERT INTO strategies"
                "(strategy,universe,budget,status,first_seen_ms,last_seen_ms,manifest) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(strategy) DO UPDATE SET universe=excluded.universe, "
                "budget=excluded.budget, status=excluded.status, "
                "last_seen_ms=excluded.last_seen_ms, manifest=excluded.manifest",
                (name, json.dumps(sorted(universe)), str(budget), status, now, now,
                 json.dumps(manifest or {})),
            )

    def write_positions(
        self, *, applied_seq: int, ts_ms: int,
        rows: list[tuple[str, str, Decimal, Decimal, Decimal]],
    ) -> None:
        """Refresh the per-strategy positions cache from the ledger (strategy, coin,
        size, entry, realized). Upsert — closed positions keep their realized PnL."""
        c = self._c
        with c:
            for strat, coin, size, entry, realized in rows:
                self._ensure_strategy(strat, ts_ms)
                c.execute(
                    "INSERT INTO positions"
                    "(strategy,coin,size_e8,entry_e8,realized_e8,applied_seq,updated_ms) "
                    "VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(strategy,coin) DO UPDATE SET size_e8=excluded.size_e8, "
                    "entry_e8=excluded.entry_e8, realized_e8=excluded.realized_e8, "
                    "applied_seq=excluded.applied_seq, updated_ms=excluded.updated_ms",
                    (strat, coin, to_e8(size), to_e8(entry), to_e8(realized), applied_seq, ts_ms),
                )

    def record_order(
        self, order: Order, shares: dict[str, Decimal], *,
        run_id: str, tick: int, now: int, wall: int,
    ) -> int:
        """Pre-send: journal the order + its intended share vector in ONE fsync'd
        transaction. Returns order_id. Must complete before the order is sent."""
        c = self._c
        shares_json = json.dumps({s: str(v) for s, v in shares.items()})
        with c:  # one fsync'd transaction; rolls back on any error
            seq = c.execute(
                "INSERT INTO events(run_id,ts_ms,wall_ms,tick,kind,coin,cloid,payload) "
                "VALUES(?,?,?,?,'ORDER',?,?,?)",
                (run_id, now, wall, tick, order.coin, order.cloid,
                 json.dumps({"size": str(order.size), "price": str(order.price),
                             "reduce_only": order.reduce_only, "shares": shares_json})),
            ).lastrowid
            order_id = c.execute(
                "INSERT INTO orders"
                "(run_id,seq,cloid,ts_ms,coin,size_e8,price_e8,reduce_only,tif,status,shares) "
                "VALUES(?,?,?,?,?,?,?,?,?,'PENDING',?)",
                (run_id, seq, order.cloid, now, order.coin, to_e8(order.size),
                 to_e8(order.price), int(order.reduce_only), order.tif.value, shares_json),
            ).lastrowid
        return int(order_id or 0)

    def record_fill(
        self, *, order_id: int, cloid: str, coin: str, price: Decimal,
        shares: list[tuple[str, Decimal]], run_id: str, tick: int, now: int, wall: int,
        fee: Decimal = Decimal(0), funding: Decimal = Decimal(0),
    ) -> int:
        """Post-fill: append a FILL event + one idempotent fills row per strategy
        share, set the order absolutely FILLED. One transaction. Returns seq."""
        c = self._c
        payload = json.dumps({"coin": coin, "price": str(price), "fee": str(fee),
                              "funding": str(funding),
                              "shares": {s: str(v) for s, v in shares}})
        with c:  # FILL event + per-strategy rows + order update, all-or-nothing
            seq = int(c.execute(
                "INSERT INTO events(run_id,ts_ms,wall_ms,tick,kind,coin,cloid,payload) "
                "VALUES(?,?,?,?,'FILL',?,?,?)",
                (run_id, now, wall, tick, coin, cloid, payload),
            ).lastrowid or 0)
            total = Decimal(0)
            for strat, size in shares:
                self._ensure_strategy(strat, now)
                c.execute(
                    "INSERT INTO fills"
                    "(run_id,seq,order_id,ts_ms,coin,strategy,size_e8,price_e8,fee_e8,funding_e8) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(seq,strategy) DO NOTHING",
                    (run_id, seq, order_id, now, coin, strat, to_e8(size), to_e8(price),
                     to_e8(fee), to_e8(funding)),
                )
                total += size
            # filled_e8 ACCUMULATES; status PARTIAL until cumulative == order size.
            row = c.execute("SELECT size_e8, filled_e8 FROM orders WHERE order_id=?",
                            (order_id,)).fetchone()
            order_size_e8, prior_filled = (row or (0, 0))
            new_filled = prior_filled + abs(to_e8(total) or 0)
            status = "FILLED" if abs(new_filled) >= abs(order_size_e8) else "PARTIAL"
            c.execute("UPDATE orders SET filled_e8=?, status=? WHERE order_id=?",
                      (new_filled, status, order_id))
        return seq

    def snapshot(
        self, *, run_id: str, applied_seq: int, ts_ms: int, parts: dict[tuple[str, str], bytes]
    ) -> None:
        """Single-cut snapshot: all component parts at one applied_seq, one txn."""
        c = self._c
        with c:
            snap_id = int(c.execute(
                "INSERT INTO snapshots(run_id,applied_seq,ts_ms) VALUES(?,?,?)",
                (run_id, applied_seq, ts_ms),
            ).lastrowid or 0)
            for (component, scope), blob in parts.items():
                c.execute(
                    "INSERT INTO snapshot_parts(snap_id,component,scope,state) VALUES(?,?,?,?)",
                    (snap_id, component, scope, blob),
                )

    # --- reads (recovery) ----------------------------------------------------

    def latest_snapshot(self) -> tuple[int, str, dict[tuple[str, str], bytes]] | None:
        """Latest snapshot by GLOBAL max(applied_seq) across runs →
        (applied_seq, owning run_id, parts). The run_id lets recovery validate the
        fingerprint of the run that OWNS this snapshot (not merely the newest run)."""
        row = self._c.execute(
            "SELECT id, applied_seq, run_id FROM snapshots "
            "ORDER BY applied_seq DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        snap_id, applied_seq, run_id = row
        parts = {
            (comp, scope): blob
            for comp, scope, blob in self._c.execute(
                "SELECT component, scope, state FROM snapshot_parts WHERE snap_id=?", (snap_id,)
            )
        }
        return int(applied_seq), str(run_id), parts

    def replay_events(self, after_seq: int) -> list[tuple[int, str, str]]:
        """Events with seq > after_seq, in order → (seq, kind, payload-json)."""
        return [
            (int(seq), kind, payload)
            for seq, kind, payload in self._c.execute(
                "SELECT seq, kind, payload FROM events WHERE seq > ? ORDER BY seq", (after_seq,)
            )
        ]

    # --- per-strategy attribution queries (current + historical) -------------

    def strategies(self) -> list[dict[str, Any]]:
        rows = self._c.execute(
            "SELECT strategy,universe,budget,status,first_seen_ms,last_seen_ms "
            "FROM strategies ORDER BY strategy"
        ).fetchall()
        return [
            {"strategy": s, "universe": json.loads(u or "[]"), "budget": b,
             "status": st, "first_seen_ms": fs, "last_seen_ms": ls}
            for s, u, b, st, fs, ls in rows
        ]

    def current_positions(self, strategy: str | None = None) -> list[dict[str, Any]]:
        """Current per-strategy holdings (size, entry, realized PnL) — what each
        strat holds right now. Filter by ``strategy`` for one strat."""
        sql = ("SELECT strategy,coin,size_e8,entry_e8,realized_e8,applied_seq "
               "FROM positions WHERE (size_e8 != 0 OR realized_e8 != 0)")
        args: tuple[Any, ...] = ()
        if strategy is not None:
            sql += " AND strategy=?"
            args = (strategy,)
        sql += " ORDER BY strategy, coin"
        return [
            {"strategy": s, "coin": c, "size": from_e8(sz), "entry": from_e8(e),
             "realized": from_e8(r), "applied_seq": seq}
            for s, c, sz, e, r, seq in self._c.execute(sql, args)
        ]

    def fills_for(
        self, strategy: str, *, coin: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """The historical trade record attributed to one strategy (newest first)."""
        sql = ("SELECT f.ts_ms,f.coin,f.size_e8,f.price_e8,f.fee_e8,f.funding_e8,o.cloid "
               "FROM fills f LEFT JOIN orders o ON f.order_id=o.order_id "
               "WHERE f.strategy=?")
        args: list[Any] = [strategy]
        if coin is not None:
            sql += " AND f.coin=?"
            args.append(coin)
        sql += " ORDER BY f.ts_ms DESC, f.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [
            {"ts_ms": ts, "coin": c, "size": from_e8(sz), "price": from_e8(p),
             "fee": from_e8(f), "funding": from_e8(fu), "cloid": cl}
            for ts, c, sz, p, f, fu, cl in self._c.execute(sql, tuple(args))
        ]

    def strategy_summary(self) -> list[dict[str, Any]]:
        """Per-strategy roll-up: status, #fills, current realized PnL, #open coins."""
        rows = self._c.execute(
            "SELECT s.strategy, s.status, s.budget, "
            "  (SELECT COUNT(*) FROM fills f WHERE f.strategy=s.strategy), "
            "  (SELECT COALESCE(SUM(realized_e8),0) FROM positions p WHERE p.strategy=s.strategy), "
            "  (SELECT COUNT(*) FROM positions p WHERE p.strategy=s.strategy AND p.size_e8 != 0) "
            "FROM strategies s ORDER BY s.strategy"
        ).fetchall()
        return [
            {"strategy": s, "status": st, "budget": b, "n_fills": n,
             "realized_pnl": from_e8(rp), "open_coins": oc}
            for s, st, b, n, rp, oc in rows
        ]

    def run_meta(self, run_id: str) -> dict[str, Any] | None:
        row = self._c.execute(
            "SELECT seed, roster FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        return None if row is None else {"seed": row[0], "roster": json.loads(row[1] or "[]")}

    def last_run(self) -> dict[str, Any] | None:
        row = self._c.execute(
            "SELECT run_id, seed, roster FROM runs ORDER BY started_ms DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {"run_id": row[0], "seed": row[1], "roster": json.loads(row[2] or "[]")}
