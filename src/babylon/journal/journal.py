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
CREATE TABLE IF NOT EXISTS strategies (strategy TEXT PRIMARY KEY, first_seen_ms INTEGER NOT NULL);
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
        self._c.execute(
            "INSERT INTO runs(run_id,started_ms,network,seed,roster,code_hash) VALUES(?,?,?,?,?,?)",
            (run_id, started_ms, network, seed, json.dumps(sorted(roster)), code_hash),
        )
        self._c.commit()

    def _ensure_strategy(self, name: str, now: int) -> None:
        self._c.execute(
            "INSERT INTO strategies(strategy,first_seen_ms) VALUES(?,?) ON CONFLICT DO NOTHING",
            (name, now),
        )

    def record_order(
        self, order: Order, shares: dict[str, Decimal], *,
        run_id: str, tick: int, now: int, wall: int,
    ) -> int:
        """Pre-send: journal the order + its intended share vector in ONE fsync'd
        transaction. Returns order_id. Must complete before the order is sent."""
        c = self._c
        cur = c.execute(
            "INSERT INTO events(run_id,ts_ms,wall_ms,tick,kind,coin,cloid,payload) "
            "VALUES(?,?,?,?,'ORDER',?,?,?)",
            (run_id, now, wall, tick, order.coin, order.cloid,
             json.dumps({"size": str(order.size), "reduce_only": order.reduce_only})),
        )
        seq = cur.lastrowid
        shares_json = json.dumps({s: str(v) for s, v in shares.items()})
        cur = c.execute(
            "INSERT INTO orders"
            "(run_id,seq,cloid,ts_ms,coin,size_e8,price_e8,reduce_only,tif,status,shares) "
            "VALUES(?,?,?,?,?,?,?,?,?,'PENDING',?)",
            (run_id, seq, order.cloid, now, order.coin, to_e8(order.size),
             to_e8(order.price), int(order.reduce_only), order.tif.value, shares_json),
        )
        c.commit()  # fsync (synchronous=FULL) before the caller sends
        return int(cur.lastrowid or 0)

    def record_fill(
        self, *, order_id: int, cloid: str, coin: str, price: Decimal,
        shares: list[tuple[str, Decimal]], run_id: str, tick: int, now: int, wall: int,
        fee: Decimal = Decimal(0), funding: Decimal = Decimal(0),
    ) -> int:
        """Post-fill: append a FILL event + one idempotent fills row per strategy
        share, set the order absolutely FILLED. One transaction. Returns seq."""
        c = self._c
        cur = c.execute(
            "INSERT INTO events(run_id,ts_ms,wall_ms,tick,kind,coin,cloid,payload) "
            "VALUES(?,?,?,?,'FILL',?,?,?)",
            (run_id, now, wall, tick, coin, cloid,
             json.dumps({"price": str(price), "shares": {s: str(v) for s, v in shares}})),
        )
        seq = int(cur.lastrowid or 0)
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
        c.execute(
            "UPDATE orders SET filled_e8=?, status='FILLED' WHERE order_id=?",
            (to_e8(abs(total)), order_id),
        )
        c.commit()
        return seq

    def snapshot(
        self, *, run_id: str, applied_seq: int, ts_ms: int, parts: dict[tuple[str, str], bytes]
    ) -> None:
        """Single-cut snapshot: all component parts at one applied_seq, one txn."""
        c = self._c
        cur = c.execute(
            "INSERT INTO snapshots(run_id,applied_seq,ts_ms) VALUES(?,?,?)",
            (run_id, applied_seq, ts_ms),
        )
        snap_id = int(cur.lastrowid or 0)
        for (component, scope), blob in parts.items():
            c.execute(
                "INSERT INTO snapshot_parts(snap_id,component,scope,state) VALUES(?,?,?,?)",
                (snap_id, component, scope, blob),
            )
        c.commit()

    # --- reads (recovery) ----------------------------------------------------

    def latest_snapshot(self) -> tuple[int, dict[tuple[str, str], bytes]] | None:
        """Latest snapshot by GLOBAL max(applied_seq) across runs → (applied_seq, parts)."""
        row = self._c.execute(
            "SELECT id, applied_seq FROM snapshots ORDER BY applied_seq DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        snap_id, applied_seq = row
        parts = {
            (comp, scope): blob
            for comp, scope, blob in self._c.execute(
                "SELECT component, scope, state FROM snapshot_parts WHERE snap_id=?", (snap_id,)
            )
        }
        return int(applied_seq), parts

    def replay_events(self, after_seq: int) -> list[tuple[int, str, str]]:
        """Events with seq > after_seq, in order → (seq, kind, payload-json)."""
        return [
            (int(seq), kind, payload)
            for seq, kind, payload in self._c.execute(
                "SELECT seq, kind, payload FROM events WHERE seq > ? ORDER BY seq", (after_seq,)
            )
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
