"""Tier-1 episode builder — the atomic durable base of the trader-feature system.

WALLET_FEATURES_SPEC v2.1. A **lifecycle** episode (P1, a NEW estimand — NOT the frozen reduce-terminates
markout episode): a continuous span where a (wallet,coin) position is nonzero. OPENS when position goes
flat→nonzero via an INCREASE; only CLOSE (→flat) or FLIP (sign change) terminates; adds & reduces are
intra-episode.

Performance (P: fuse the passes): the exact-integer-tick position arithmetic + INCREASE/REDUCE/CLOSE/FLIP
classification is **vectorized in DuckDB** (all derivable per-row from `start_position`), so the Python walk
only tracks episode boundaries on pre-computed numeric columns — no per-row Decimal. Position math stays
EXACT (DECIMAL(38,18)·10^szd → integer ticks); PnL/fees/notional are float64 (fine for a research feature
table — labelled; the exactness that governs episode boundaries is the tick math, which is exact).

Pass 1 (this module): stream fills ordered by `(wallet, coin, block_number, event_index)` (P4 — block_number
is globally monotonic with time and unique per block; `src_object` is an asserted 1:1 invariant, NOT a sort
key — its S3-key strings sort lexicographically). Each (wallet,coin) is contiguous → whole-history episodes
in one pass. Pass 2 (8h dedup + whole-stream quarantine) is a separate step — not here.

MTM-path columns (MAE, adds_while_underwater) need a price series → reserved NULL (P5). peak_notional is at
EXECUTION price (P5). realized_pnl = Σ closedPnl (authoritative).

⚠ PARTITION CONVENTION (audit 2026-07-07): `month=YYYYMM/episodes.parquet` partitions by the episode's
**FINALIZE month** (the month its terminating CLOSE/FLIP was processed), NOT its open month — an episode
opened Aug and closed Oct lands in `month=202610`. Downstream cutoff/window panels MUST filter on
`open_ts`/`close_ts`, never on the partition key, or every cross-month episode is mis-attributed.

⚠ RESUME LIMITATION (audit 2026-07-07): `build_all_carry` treats a month as committed iff its parquet AND
a schema-matching checkpoint both exist — the checkpoint carries no fingerprint of the carry-in it was
built from. The ONLY safe partial rebuild is deleting the LAST committed month(s). Deleting a MIDDLE month
then crashing before the run reaches its successors can leave those successors falsely "committed" (built
on the stale carry) → silently mis-stitched cross-month episodes. A full rebuild (or a SCHEMA_VERSION bump,
which invalidates all checkpoints) is always safe. TODO: fingerprint the carry-in in each checkpoint.

    python -m research.data.episodes_build 202508      # one month
    python -m research.data.episodes_build all          # whole tape
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from . import schema

REPO_ROOT = Path(__file__).resolve().parents[2]
FILLS_GLOB = str(REPO_ROOT / "data" / "raw" / "fills" / "month=*/day=*/*.parquet")
EPISODES_DIR = REPO_ROOT / "data" / "derived" / "episodes"
DUST_USD = 100.0
EPISODE_SCHEMA_VERSION = "episodes_v1_lifecycle_enriched_2026-07-07"


def _code_commit() -> str:
    """git HEAD (+`-dirty` if the tree is uncommitted) for provenance; 'unknown' outside a repo."""
    import subprocess
    try:
        h = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{h}{'-dirty' if dirty else ''}" if h else "unknown"
    except Exception:
        return "unknown"


def _provenance_meta() -> dict:
    """File-level parquet key/value metadata (NOT per-row — provenance, excluded from any repro hash)."""
    return {b"episode_schema_version": EPISODE_SCHEMA_VERSION.encode(),
            b"source_schema_version": schema.SCHEMA_VERSION.encode(),
            b"code_commit": _code_commit().encode()}


def _with_meta(tbl: pa.Table) -> pa.Table:
    return tbl.replace_schema_metadata(_provenance_meta())

# per-coin tick scale (10^szDecimals) as an integer for exact DECIMAL scaling in SQL
_SCALE_CASE = "CASE coin " + " ".join(f"WHEN '{c}' THEN {10**d}" for c, d in schema.SZD.items()) + " END"
_ZERO_HASH = "0x" + "0" * 64


def _classify_sql(month, wallet_mod: int | None = None) -> str:
    # wallet_mod=N keeps ~1/N of WHOLE wallets (hash split — never splits a (wallet,coin) stream, so
    # episode boundaries are identical to the full run on that subset). For a memory-safe reconcile on
    # an 8GB box; both reconcile paths pass the same value so the carry==whole-tape proof stays valid.
    preds = []
    if month is None:
        pass
    elif isinstance(month, (list, tuple, set)):
        preds.append("month IN (" + ",".join(str(int(m)) for m in month) + ")")
    else:
        preds.append(f"month = {int(month)}")
    if wallet_mod is not None:
        preds.append(f"(hash(wallet) % {int(wallet_mod)}) = 0")
    where = ("WHERE " + " AND ".join(preds)) if preds else ""
    # qb/qa are EXACT integer ticks; cls is the exact transition; money is float64.
    return f"""
    WITH raw AS (
      SELECT wallet, coin, ts, block_number, event_index, tid, crossed,
             ({_SCALE_CASE}) AS scale,
             -- exact ticks in 64-bit DECIMAL(18,6) (majors szd≤5, so 6 decimals is exact; far cheaper than
             -- the 128-bit DECIMAL(38,18) which OOM'd the 85M-row sort). positions never exceed ~1e9 ticks.
             CAST(round(TRY_CAST(start_position AS DECIMAL(18,6)) * ({_SCALE_CASE})) AS BIGINT) AS qb,
             (CASE WHEN side='B' THEN 1 ELSE -1 END)
               * CAST(round(TRY_CAST(sz AS DECIMAL(18,6)) * ({_SCALE_CASE})) AS BIGINT) AS signed_t,
             TRY_CAST(px AS DOUBLE) AS px,
             COALESCE(TRY_CAST(closed_pnl AS DOUBLE), 0) AS cpnl,
             COALESCE(TRY_CAST(fee AS DOUBLE), 0) AS fee_d,
             COALESCE(TRY_CAST(builder_fee AS DOUBLE), 0) AS bfee_d,
             (side = 'B') AS is_buy,
             (hash = '{_ZERO_HASH}'
              OR (liq_user IS NOT NULL AND lower(liq_user) = lower(wallet))
              OR dir = 'Net Child Vaults') AS flagged,
             (liq_user IS NOT NULL AND lower(liq_user) = lower(wallet)) AS liq_origin
      FROM read_parquet('{FILLS_GLOB}', hive_partitioning=true, union_by_name=true) {where}
    ), cl AS (
      SELECT *, qb + signed_t AS qa,
             (abs(signed_t)::DOUBLE / scale) * px AS fill_notional
      FROM raw
    )
    SELECT wallet, coin, ts, block_number, event_index, crossed, flagged, liq_origin, is_buy,
           qb, qa, cpnl, fee_d, bfee_d, fill_notional,
           (abs(qa)::DOUBLE / scale) * px AS notional_after,
           CASE
             WHEN qb = 0 OR sign(signed_t) = sign(qb) THEN 'INCREASE'
             WHEN sign(qa) = sign(qb) AND abs(qa) < abs(qb) THEN 'REDUCE'
             WHEN qa = 0 THEN 'CLOSE'
             ELSE 'FLIP'
           END AS cls
    FROM cl
    -- tid = final tiebreak (spec P4): makes the order provably TOTAL even if a future re-ingest ever broke
    -- the block↔object 1:1 invariant (empirically 0 ties / 0 multi-object blocks across all 11 months,
    -- audit 2026-07-07). Guarantees run-to-run determinism (P11) without relying on the unasserted invariant.
    ORDER BY wallet, coin, block_number, event_index, tid
    """


@dataclass
class _Open:
    open_ts: int
    dir: int
    opener_key: tuple
    opener_flagged: bool
    opener_qualifying: bool
    inherited: bool
    crossed_open: bool
    n_fills: int
    n_adds: int
    n_reductions: int
    initial_notional: float
    total_added_notional: float
    peak_notional: float
    realized_pnl: float
    fees: float
    # --- enriched walk-derived scalars (safe-maximal; irrecoverable without a re-walk) ---
    builder_fees: float          # builder_fee split out of fees (base fee = fees - builder_fees)
    peak_ts: int                 # ts of the fill that set peak_notional (→ build_minutes)
    last_fill_ts: int            # ts of the most recent fill in the episode
    first_reduce_ts: int | None  # ts of the first REDUCE (→ time_to_first_reduce_min); None if never reduced
    n_taker_fills: int           # crossed=true fills within the episode
    n_maker_fills: int
    n_buy_fills: int             # side='B' fills within the episode
    n_sell_fills: int
    n_flagged_fills: int         # zhash/liq-origin/vault fills within the episode
    n_liq_fills: int             # liquidation-origin fills within the episode
    max_fill_notional: float
    min_fill_notional: float
    liq_close: bool = False


@dataclass
class CarryState:
    """A (wallet,coin) position still OPEN at a month boundary — the full accumulator + ledger continuity,
    threaded into the next month so a cross-month position stays ONE episode (per-month + carry-seed build)."""
    open: _Open
    prev_qa: int
    chain_breaks: int


class EpisodeWalker:
    """Feed one (wallet,coin)'s PRE-CLASSIFIED fills in order via start_stream()+feed(); collect episodes."""

    def __init__(self) -> None:
        self.episodes: list[dict] = []
        self._reset()

    def _reset(self) -> None:
        self.cur: _Open | None = None
        self.prev_qa: int | None = None
        self.chain_breaks = 0
        self._wc: tuple | None = None

    def start_stream(self, wallet: str, coin: str) -> None:
        if self.cur is not None:
            self._finalize(None, "OPEN_AT_END")
        self._reset()
        self._wc = (wallet, coin)

    def finish(self) -> None:
        if self.cur is not None:
            self._finalize(None, "OPEN_AT_END")

    def seed(self, wallet: str, coin: str, carry: CarryState | None) -> None:
        """Begin a stream, optionally CONTINUING a position carried from the prior month (same episode).
        Unlike start_stream, it does NOT auto-finalize the previous stream — the carry driver exports it."""
        self._reset()
        self._wc = (wallet, coin)
        if carry is not None:
            self.cur = carry.open
            self.prev_qa = carry.prev_qa
            self.chain_breaks = carry.chain_breaks

    def export_open(self) -> CarryState | None:
        """End the current stream WITHOUT finalizing: if a position is still open, return its carry state
        (to thread into the next month); else None. Clears cur either way."""
        cs = CarryState(self.cur, self.prev_qa, self.chain_breaks) if self.cur is not None else None
        self.cur = None
        return cs

    def feed(self, ts, qb, qa, cls, cpnl, fee_d, bfee_d, fill_notional, na, is_buy, flagged,
             liq_origin, crossed, block, ei) -> None:
        """Positional (no per-row dict — the hot path). Values are SQL-precomputed.
        Opener identity = (block_number, event_index) — globally unique per fill (src_object dropped)."""
        if self.prev_qa is not None and qb != self.prev_qa:
            self.chain_breaks += 1
        self.prev_qa = qa
        key = (block, ei)
        # per-fill record threaded to the accumulator tally (composition/timing/size scalars)
        rec = (ts, crossed, is_buy, flagged, liq_origin, fill_notional, na, bfee_d)

        if self.cur is None:
            if cls == "INCREASE" and qb == 0:
                self._open(ts, 1 if qa > 0 else -1, key, flagged, crossed, fill_notional, na,
                           cpnl, fee_d, rec, inherited=False)
                return
            if qb != 0:
                init = na if na > 0 else fill_notional
                self._open(ts, 1 if qb > 0 else -1, key, flagged, crossed, init, na, 0.0, 0.0,
                           rec, inherited=True, count_fill=False)
                self._apply(cls, cpnl, fee_d, fill_notional, na, rec)
                self._maybe_close(ts, cls, qa, liq_origin, na, key, crossed, rec)
            return

        self._apply(cls, cpnl, fee_d, fill_notional, na, rec)
        self._maybe_close(ts, cls, qa, liq_origin, na, key, crossed, rec)

    def _open(self, ts, dir, key, flagged, crossed, initial, peak, pnl, fees, rec, inherited,
              count_fill=True) -> None:
        self.cur = _Open(
            open_ts=ts, dir=dir, opener_key=key, opener_flagged=flagged,
            opener_qualifying=(not flagged) and initial >= DUST_USD,
            inherited=inherited, crossed_open=bool(crossed),
            n_fills=1 if count_fill else 0, n_adds=0, n_reductions=0,
            initial_notional=initial, total_added_notional=0.0, peak_notional=peak,
            realized_pnl=pnl, fees=fees,
            builder_fees=0.0, peak_ts=ts, last_fill_ts=ts, first_reduce_ts=None,
            n_taker_fills=0, n_maker_fills=0, n_buy_fills=0, n_sell_fills=0,
            n_flagged_fills=0, n_liq_fills=0, max_fill_notional=0.0, min_fill_notional=float("inf"))
        if count_fill:                          # opener fill's composition (inherited opener defers to _apply)
            self._tally(rec)

    def _tally(self, rec) -> None:
        """Per-fill accumulators shared by opener (_open) and subsequent fills (_apply)."""
        ts, crossed, is_buy, flagged, liq_origin, fill_notional, na, bfee_d = rec
        c = self.cur
        c.last_fill_ts = ts
        if na > c.peak_notional:
            c.peak_notional = na
            c.peak_ts = ts
        if crossed:
            c.n_taker_fills += 1
        else:
            c.n_maker_fills += 1
        if is_buy:
            c.n_buy_fills += 1
        else:
            c.n_sell_fills += 1
        if flagged:
            c.n_flagged_fills += 1
        if liq_origin:
            c.n_liq_fills += 1
        if fill_notional > c.max_fill_notional:
            c.max_fill_notional = fill_notional
        if fill_notional < c.min_fill_notional:
            c.min_fill_notional = fill_notional
        c.builder_fees += bfee_d

    def _apply(self, cls, cpnl, fee_d, fill_notional, na, rec) -> None:
        c = self.cur
        c.n_fills += 1
        c.realized_pnl += cpnl
        c.fees += fee_d
        if cls == "INCREASE":
            c.n_adds += 1
            c.total_added_notional += fill_notional
        elif cls == "REDUCE":
            c.n_reductions += 1
            if c.first_reduce_ts is None:
                c.first_reduce_ts = rec[0]      # ts of the first REDUCE
        self._tally(rec)                        # peak/composition/size (peak moved here from _apply)

    def _maybe_close(self, ts, cls, qa, liq_origin, na, key, crossed, rec) -> None:
        if cls == "CLOSE":
            self.cur.liq_close = liq_origin
            self._finalize(ts, "CLOSE")
        elif cls == "FLIP":
            self.cur.liq_close = liq_origin
            self._finalize(ts, "FLIP")
            # residual leg = NEW episode opened by this flip fill (pnl/base+builder fee already booked to the
            # closed leg above → zero the builder_fee in the residual's opener rec so it isn't double-counted).
            # opener_flagged MUST reflect the flip fill's own flag (rec[3]) — if the flip fill is a
            # zhash-TWAP/liq/vault fill the residual was NOT opened by a clean signal; hardcoding False here
            # mislabels it as qualifying and inflates qualifying_open_share (audit 2026-07-07, finding A).
            resid_rec = rec[:7] + (0.0,)
            flip_flagged = rec[3]
            self._open(ts, 1 if qa > 0 else -1, key, flip_flagged, crossed, na, na, 0.0, 0.0, resid_rec,
                       inherited=False)

    def _finalize(self, close_ts, close_kind: str) -> None:
        c = self.cur
        w, coin = self._wc
        hold_min = (close_ts - c.open_ts) / 60000 if close_ts is not None else None
        build_min = (c.peak_ts - c.open_ts) / 60000 if c.peak_ts is not None else None
        first_reduce_min = ((c.first_reduce_ts - c.open_ts) / 60000
                            if c.first_reduce_ts is not None else None)
        total_fees = c.fees + c.builder_fees
        self.episodes.append({
            "wallet": w, "coin": coin, "open_ts": c.open_ts, "close_ts": close_ts,
            "dir": "long" if c.dir > 0 else "short", "close_kind": close_kind,
            "opener_block": c.opener_key[0], "opener_event_index": c.opener_key[1],
            "n_fills": c.n_fills, "n_adds": c.n_adds, "n_reductions": c.n_reductions,
            "n_taker_fills": c.n_taker_fills, "n_maker_fills": c.n_maker_fills,
            "n_buy_fills": c.n_buy_fills, "n_sell_fills": c.n_sell_fills,
            "n_flagged_fills": c.n_flagged_fills, "n_liq_fills": c.n_liq_fills,
            "initial_notional_usd": c.initial_notional, "peak_notional_usd": c.peak_notional,
            "total_added_notional_usd": c.total_added_notional,
            "max_fill_notional_usd": c.max_fill_notional,
            "min_fill_notional_usd": (c.min_fill_notional if c.min_fill_notional != float("inf") else None),
            "hold_minutes": hold_min, "build_minutes": build_min,
            "time_to_first_reduce_min": first_reduce_min, "last_fill_ts": c.last_fill_ts,
            "realized_pnl_usd": c.realized_pnl, "fee_usd": c.fees, "builder_fee_usd": c.builder_fees,
            "fees_usd": total_fees, "realized_net_usd": c.realized_pnl - total_fees,
            "opener_flagged": c.opener_flagged, "opener_qualifying": c.opener_qualifying,
            "inherited_basis": c.inherited, "crossed_open": c.crossed_open,
            "is_liquidation_close": c.liq_close, "chain_breaks_stream": self.chain_breaks,
            "entry_bar_ts": None, "max_adverse_excursion_usd": None, "adds_while_underwater": None,
        })
        self.cur = None


_ARROW = pa.schema([
    ("wallet", pa.string()), ("coin", pa.string()), ("open_ts", pa.int64()), ("close_ts", pa.int64()),
    ("dir", pa.string()), ("close_kind", pa.string()),
    ("opener_block", pa.int64()), ("opener_event_index", pa.int64()), ("n_fills", pa.int64()),
    ("n_adds", pa.int64()), ("n_reductions", pa.int64()),
    ("n_taker_fills", pa.int64()), ("n_maker_fills", pa.int64()),
    ("n_buy_fills", pa.int64()), ("n_sell_fills", pa.int64()),
    ("n_flagged_fills", pa.int64()), ("n_liq_fills", pa.int64()),
    ("initial_notional_usd", pa.float64()),
    ("peak_notional_usd", pa.float64()), ("total_added_notional_usd", pa.float64()),
    ("max_fill_notional_usd", pa.float64()), ("min_fill_notional_usd", pa.float64()),
    ("hold_minutes", pa.float64()), ("build_minutes", pa.float64()),
    ("time_to_first_reduce_min", pa.float64()), ("last_fill_ts", pa.int64()),
    ("realized_pnl_usd", pa.float64()), ("fee_usd", pa.float64()), ("builder_fee_usd", pa.float64()),
    ("fees_usd", pa.float64()),
    ("realized_net_usd", pa.float64()), ("opener_flagged", pa.bool_()), ("opener_qualifying", pa.bool_()),
    ("inherited_basis", pa.bool_()), ("crossed_open", pa.bool_()), ("is_liquidation_close", pa.bool_()),
    ("chain_breaks_stream", pa.int64()), ("entry_bar_ts", pa.int64()),
    ("max_adverse_excursion_usd", pa.float64()), ("adds_while_underwater", pa.int64()),
])


def build_stream(month: str | None, threads: int = 4) -> dict:
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={threads}")
    t0 = time.time()
    reader = con.execute(_classify_sql(month)).fetch_record_batch(300_000)
    walker = EpisodeWalker()
    feed = walker.feed
    cur_w = cur_c = None
    n = 0
    for batch in reader:
        c = batch.to_pydict()
        W, CO, TS, QB, QA, CL = c["wallet"], c["coin"], c["ts"], c["qb"], c["qa"], c["cls"]
        CP, FE, BF, FN, NA = c["cpnl"], c["fee_d"], c["bfee_d"], c["fill_notional"], c["notional_after"]
        IB, FL, LO, CR, BL, EI = (c["is_buy"], c["flagged"], c["liq_origin"], c["crossed"],
                                  c["block_number"], c["event_index"])
        for i in range(len(W)):
            n += 1
            if W[i] != cur_w or CO[i] != cur_c:
                walker.start_stream(W[i], CO[i])
                cur_w, cur_c = W[i], CO[i]
            feed(TS[i], QB[i], QA[i], CL[i], CP[i], FE[i], BF[i], FN[i], NA[i], IB[i], FL[i], LO[i],
                 CR[i], BL[i], EI[i])
    walker.finish()
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    tbl = _with_meta(pa.Table.from_pylist(walker.episodes, schema=_ARROW))
    out = EPISODES_DIR / f"_build_{month or 'all'}.parquet"
    pq.write_table(tbl, out, compression="zstd")
    return {"fills": n, "episodes": len(walker.episodes), "secs": round(time.time() - t0, 1),
            "rate_k_s": round(n / max(time.time() - t0, 1) / 1000), "out": str(out)}


MONTHS = ["202508", "202509", "202510", "202511", "202512", "202601",
          "202602", "202603", "202604", "202605", "202606"]
EPISODES_LAKE = REPO_ROOT / "data" / "derived" / "episodes"   # month=YYYYMM/episodes.parquet (Hive)


def _drain(walker, batch, carry_in, carry_out, seen, state):
    """Feed one record-batch through the walker with per-stream seed(carry)/export at boundaries."""
    c = batch.to_pydict()
    W, CO, TS, QB, QA, CL = c["wallet"], c["coin"], c["ts"], c["qb"], c["qa"], c["cls"]
    CP, FE, BF, FN, NA = c["cpnl"], c["fee_d"], c["bfee_d"], c["fill_notional"], c["notional_after"]
    IB, FL, LO, CR, BL, EI = (c["is_buy"], c["flagged"], c["liq_origin"], c["crossed"],
                              c["block_number"], c["event_index"])
    feed = walker.feed
    n = 0
    for i in range(len(W)):
        n += 1
        if W[i] != state[0] or CO[i] != state[1]:
            if state[0] is not None:                       # close previous stream: export if still open
                cs = walker.export_open()
                if cs is not None:
                    carry_out[(state[0], state[1])] = cs
            wc = (W[i], CO[i])
            walker.seed(W[i], CO[i], carry_in.get(wc))
            seen.add(wc)
            state[0], state[1] = W[i], CO[i]
        feed(TS[i], QB[i], QA[i], CL[i], CP[i], FE[i], BF[i], FN[i], NA[i], IB[i], FL[i], LO[i],
             CR[i], BL[i], EI[i])
    return n


def build_month_carry(con, month, carry_in, threads=2, wallet_mod=None):
    """Build one month seeded by carry_in (open positions from the prior month). Returns
    (n_fills, episodes_list, carry_out). carry_out = streams open at month-end PLUS untouched carry_in
    streams that had no fills this month (they stay open, threaded forward)."""
    con.execute(f"PRAGMA threads={threads}")
    reader = con.execute(_classify_sql(month, wallet_mod)).fetch_record_batch(300_000)
    walker = EpisodeWalker()
    carry_out, seen, state = {}, set(), [None, None]
    n = 0
    for batch in reader:
        n += _drain(walker, batch, carry_in, carry_out, seen, state)
    if state[0] is not None:                                # export the last stream if still open
        cs = walker.export_open()
        if cs is not None:
            carry_out[(state[0], state[1])] = cs
    for wc, cs in carry_in.items():                         # carry untouched still-open streams forward
        if wc not in seen:
            carry_out[wc] = cs
    return n, walker.episodes, carry_out


def _finalize_open_carries(carry):
    """Positions still open at the END of the tape → emit as OPEN_AT_END episodes."""
    w = EpisodeWalker()
    for wc, cs in carry.items():
        w._wc = wc
        w.cur = cs.open
        w.chain_breaks = cs.chain_breaks
        w._finalize(None, "OPEN_AT_END")
    return w.episodes


def _write_month(month, episodes):
    d = EPISODES_LAKE / f"month={month}"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".episodes.parquet.tmp"
    pq.write_table(_with_meta(pa.Table.from_pylist(episodes, schema=_ARROW)), tmp, compression="zstd")
    os.replace(tmp, d / "episodes.parquet")


CHECKPOINT_DIR = EPISODES_LAKE / "_checkpoint"     # per-month carry-seed pickles (resume state, P3)


def _ckpt_path(month) -> Path:
    return CHECKPOINT_DIR / f"carry_after_{month}.pkl"


def _save_checkpoint(month, carry) -> None:
    """Persist the carry dict (open positions threaded into the next month) atomically. Tagged with the
    schema version so a schema bump invalidates it and forces a full rebuild."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CHECKPOINT_DIR / f".carry_after_{month}.pkl.tmp"
    with open(tmp, "wb") as f:
        pickle.dump({"schema": EPISODE_SCHEMA_VERSION, "carry": carry}, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, _ckpt_path(month))


def _load_checkpoint(month):
    """Return the carry dict saved after `month`, or None if absent / corrupt / stale-schema. A corrupt or
    unreadable pickle is treated as 'not committed' → the month is deterministically rebuilt (never crashes
    the resume)."""
    p = _ckpt_path(month)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            blob = pickle.load(f)
    except (pickle.UnpicklingError, EOFError, AttributeError, ValueError, OSError):
        return None
    return blob["carry"] if isinstance(blob, dict) and blob.get("schema") == EPISODE_SCHEMA_VERSION else None


def _parquet_path(month) -> Path:
    return EPISODES_LAKE / f"month={month}" / "episodes.parquet"


def build_all_carry(threads=2):
    """Full-tape episode build, per-month + carry-seed (cross-month positions stay ONE episode).

    RESUMABLE (spec P2/P3): on start, the longest COMMITTED prefix of months is skipped and the walk resumes
    from that month's persisted carry-seed. A month commits only after BOTH its parquet AND its checkpoint
    land (checkpoint written last); to close the stale-commit window on a PARTIAL re-run, each month's
    checkpoint is pre-unlinked before it is rebuilt — so a crash mid-rebuild leaves that month UNCOMMITTED
    (never falsely committed with stale content). A crash mid-month re-runs just that month (deterministic
    → identical output).
    - Force a clean full rebuild: delete data/derived/episodes/month=* AND _checkpoint/.
    - Re-run ONLY the last month (e.g. after the June-30 backfill lands — there is no input fingerprint, so a
      committed month is NOT auto-rebuilt when its fills grow): delete data/derived/episodes/month=<last>/
      (keep _checkpoint/carry_after_<prev>.pkl); resume rebuilds it from the prior month's carry-seed."""
    con = duckdb.connect()
    carry, total, t0 = {}, 0, time.time()
    start = 0                                               # resume: skip the longest committed prefix
    for i, month in enumerate(MONTHS):
        ck = _load_checkpoint(month)                        # single load (committed iff parquet + checkpoint)
        if ck is not None and _parquet_path(month).exists():
            carry = ck                                      # advance the carry to this month's end-state
            start = i + 1
        else:
            break
    if start:
        nxt = MONTHS[start] if start < len(MONTHS) else "DONE (all months committed)"
        print(f"resume: {MONTHS[0]}..{MONTHS[start-1]} already committed "
              f"({len(carry):,} open carried) -> resuming at {nxt}", flush=True)
    for i in range(start, len(MONTHS)):
        month = MONTHS[i]
        _ckpt_path(month).unlink(missing_ok=True)           # invalidate stale commit BEFORE rebuild (finding 1)
        tm = time.time()
        n, eps, carry = build_month_carry(con, month, carry, threads)
        if i == len(MONTHS) - 1:                            # tape end: finalize whatever is still open
            eps = eps + _finalize_open_carries(carry)
            carry = {}
        _write_month(month, eps)
        _save_checkpoint(month, carry)                      # commit AFTER the parquet (crash-safe ordering)
        total += len(eps)
        log_line = (f"  {month}: {n:,} fills -> {len(eps):,} eps  (carry_out={len(carry):,} open)  "
                    f"{time.time()-tm:.0f}s")
        print(log_line, flush=True)
    print(f"=== built {total:,} episodes this run in {time.time()-t0:.0f}s -> {EPISODES_LAKE} ===")
    return {"episodes": total}


def reconcile_carry(months=("202508", "202509"), wallet_mod=16):
    """Prove carry-seed == whole-tape on a small window: build `months` both ways, diff episode-by-episode.
    wallet_mod subsamples WHOLE wallets (hash split) so both paths fit in RAM on an 8GB box while still
    exercising the cross-month carry boundary; pass None for the full (memory-hungry) reconcile."""
    con = duckdb.connect()
    # (a) carry-seed path
    carry, cs_eps = {}, []
    for m in months:
        _, eps, carry = build_month_carry(con, m, carry, threads=2, wallet_mod=wallet_mod)
        cs_eps.extend(eps)
    cs_eps.extend(_finalize_open_carries(carry))
    # (b) whole-tape path: one sort over the same months
    con.execute("PRAGMA threads=2")
    reader = con.execute(_classify_sql(list(months), wallet_mod)).fetch_record_batch(300_000)
    w = EpisodeWalker()
    cur = [None, None]
    for batch in reader:
        c = batch.to_pydict()
        cols = [c[k] for k in ("wallet", "coin", "ts", "qb", "qa", "cls", "cpnl", "fee_d", "bfee_d",
                               "fill_notional", "notional_after", "is_buy", "flagged", "liq_origin",
                               "crossed", "block_number", "event_index")]
        W, CO = cols[0], cols[1]
        for i in range(len(W)):
            if W[i] != cur[0] or CO[i] != cur[1]:
                w.start_stream(W[i], CO[i]); cur[0], cur[1] = W[i], CO[i]
            w.feed(*[col[i] for col in cols[2:]])
    w.finish()
    wt_eps = w.episodes

    def key(e):
        return (e["wallet"], e["coin"], e["open_ts"])

    def val(e):
        # include the enriched walk-derived scalars so the carry==whole-tape proof covers them too
        return (e["close_ts"], e["close_kind"], round(e["realized_pnl_usd"], 4), e["n_fills"],
                e["n_adds"], e["n_reductions"], round(e["peak_notional_usd"], 4),
                e["n_taker_fills"], e["n_maker_fills"], e["n_buy_fills"], e["n_sell_fills"],
                e["n_flagged_fills"], e["n_liq_fills"], e["build_minutes"], e["last_fill_ts"],
                round(e["fee_usd"], 6), round(e["builder_fee_usd"], 6),
                round(e["max_fill_notional_usd"], 4), e["chain_breaks_stream"],
                e["opener_flagged"], e["opener_qualifying"])
    cs_map = {key(e): val(e) for e in cs_eps}
    wt_map = {key(e): val(e) for e in wt_eps}
    only_cs = set(cs_map) - set(wt_map)
    only_wt = set(wt_map) - set(cs_map)
    mismatch = [k for k in (set(cs_map) & set(wt_map)) if cs_map[k] != wt_map[k]]
    ok = not only_cs and not only_wt and not mismatch
    sub = f" [~1/{wallet_mod} wallet subsample]" if wallet_mod else " [ALL wallets]"
    print(f"reconcile {months}{sub}: carry_eps={len(cs_eps):,} whole_tape_eps={len(wt_eps):,}")
    print(f"  only_carry={len(only_cs)} only_wholetape={len(only_wt)} value_mismatch={len(mismatch)}  "
          f"-> {'IDENTICAL ✅' if ok else 'DIFFER ❌'}")
    if not ok:
        for k in list(only_cs)[:3]:
            print(f"   only_carry: {k} -> {cs_map[k]}")
        for k in list(only_wt)[:3]:
            print(f"   only_wt: {k} -> {wt_map[k]}")
        for k in mismatch[:5]:
            print(f"   MISMATCH {k}: carry={cs_map[k]} wt={wt_map[k]}")
    return ok


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "202508"
    if arg == "reconcile":
        reconcile_carry()
    elif arg in ("all", "all_carry"):
        # both route to the memory-safe per-month carry build; build_stream(None) held the WHOLE tape's
        # episodes in one RAM list (OOM + zero output on crash) — never expose it as a full-tape command.
        print(build_all_carry())
    else:
        print(build_stream(arg))   # explicit single month only (test/reconcile helper)
