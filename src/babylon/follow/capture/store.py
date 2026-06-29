"""RoundtripStore — durable, batched, retention-pruned SQLite of finalized round-trips.

Phase-1 store (the scale audit: SQLite + WAL + batched commits is plenty for ~16 rt/s;
Phase-2's full-tape volume wants Parquet+DuckDB instead). Batched transactional inserts
(per-commit fsync is the bottleneck, not write speed), `(wallet, exit_t)` index for the
rolling-window Sortino scan, and a nightly prune. Round-trips are tiny (~10 MB/month) so the
retention is generous; raw fills are NOT stored here (the ingest keeps only a live buffer).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from babylon.follow.capture.markout import FinalRoundtrip


class RoundtripStore:
    def __init__(self, path: Path, *, batch: int = 500) -> None:
        self._db = sqlite3.connect(str(path))
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS roundtrips("
            " wallet TEXT, coin TEXT, rid INTEGER, direction INTEGER,"
            " entry_t INTEGER, exit_t INTEGER, entry_mk REAL, exit_mk REAL,"
            " ret_bps REAL, taker_open INTEGER, conviction INTEGER, source TEXT,"
            " PRIMARY KEY (wallet, coin, rid))")
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_wallet_exit ON roundtrips(wallet, exit_t)")
        self._db.commit()
        self._batch = batch
        self._buf: list[FinalRoundtrip] = []

    def add(self, rt: FinalRoundtrip) -> None:
        self._buf.append(rt)
        if len(self._buf) >= self._batch:
            self.flush()

    def add_many(self, rts: list[FinalRoundtrip]) -> None:
        for rt in rts:
            self.add(rt)

    def flush(self) -> None:
        if not self._buf:
            return
        self._db.executemany(
            "INSERT OR IGNORE INTO roundtrips VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r.wallet, r.coin, r.rid, r.direction, r.entry_t, r.exit_t, r.entry_mk,
              r.exit_mk, r.ret_bps, int(r.taker_open), int(r.conviction), r.source)
             for r in self._buf])
        self._db.commit()
        self._buf.clear()

    def returns(self, wallet: str, lo_t: int, hi_t: int) -> np.ndarray:
        """Per-round-trip ret_bps for round-trips CLOSED in [lo_t, hi_t) — the seam-guarded
        train window (lo_t = T0−train, hi_t = T0)."""
        self.flush()
        rows = self._db.execute(
            "SELECT ret_bps FROM roundtrips WHERE wallet=? AND exit_t>=? AND exit_t<?",
            (wallet, lo_t, hi_t)).fetchall()
        return np.array([r[0] for r in rows], dtype=np.float64)

    def active_wallets(self, lo_t: int, hi_t: int, min_n: int) -> list[str]:
        """Wallets with ≥ min_n round-trips closed in [lo_t, hi_t) — the eligible candidate set."""
        self.flush()
        rows = self._db.execute(
            "SELECT wallet FROM roundtrips WHERE exit_t>=? AND exit_t<? "
            "GROUP BY wallet HAVING COUNT(*)>=?", (lo_t, hi_t, min_n)).fetchall()
        return [r[0] for r in rows]

    def prune(self, before_t: int) -> int:
        """Retention: delete round-trips closed before `before_t`. Returns rows deleted."""
        self.flush()
        cur = self._db.execute("DELETE FROM roundtrips WHERE exit_t < ?", (before_t,))
        self._db.commit()
        return cur.rowcount

    def count(self) -> int:
        self.flush()
        return int(self._db.execute("SELECT COUNT(*) FROM roundtrips").fetchone()[0])

    def close(self) -> None:
        self.flush()
        self._db.close()
