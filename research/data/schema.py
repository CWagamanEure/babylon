"""Normalized node_fills schema + DuckDB view definitions for the research workbench.

Source of truth for the fill contract and the query-layer views. The authoritative tape lives at
`data/raw/fills/month=YYYYMM/day=YYYYMMDD/hourHH.parquet` (Hive-partitioned; `month`/`day` are INTEGERS).
Monetary/size fields are stored as EXACT STRINGS and cast to DECIMAL on demand — never float.
Firewall: this is the EXPLORATORY lane (real per-wallet PnL); it must never feed the frozen Gate-A pipeline.
"""
from __future__ import annotations

# 28-column contract (Hive read). Captures EVERY node_fills field — the full liquidation struct
# (liquidatedUser/method/markPx) and both block timestamps (consensus block_time + node local_time).
FILL_COLUMNS = {
    "wallet": "VARCHAR", "coin": "VARCHAR", "ts": "BIGINT",
    "px": "VARCHAR", "sz": "VARCHAR", "side": "VARCHAR",
    "start_position": "VARCHAR", "dir": "VARCHAR", "closed_pnl": "VARCHAR",
    "hash": "VARCHAR", "oid": "BIGINT", "tid": "BIGINT", "cloid": "VARCHAR",
    "crossed": "BOOLEAN", "fee": "VARCHAR", "fee_token": "VARCHAR",
    "liq_user": "VARCHAR", "liq_method": "VARCHAR", "liq_mark_px": "VARCHAR",
    "builder": "VARCHAR", "builder_fee": "VARCHAR",
    "src_object": "VARCHAR", "block_number": "BIGINT",
    "block_time": "VARCHAR", "local_time": "VARCHAR",
    "event_index": "BIGINT", "day": "BIGINT", "month": "BIGINT",
}
STR_DECIMAL_COLS = ("px", "sz", "start_position", "closed_pnl", "fee", "builder_fee", "liq_mark_px")
PARTITION_COLS = ("month", "day")          # integers, used for pruning: WHERE month=202508
SZD = {"BTC": 5, "ETH": 4, "SOL": 2, "HYPE": 2}
MAJORS = tuple(SZD)                          # ("BTC","ETH","SOL","HYPE") — the retained perp universe
DEC = "DECIMAL(38,18)"                       # wide fixed-point; exact, no float

# Ingest provenance (RESTORE_PLAN §2). Bump when the physical fill contract changes so stale parts
# re-ingest. szd-snapshot pins the szDecimals used for downstream exact quantization.
SCHEMA_VERSION = "fills_v2_allfields_szd_2026-07-06"

# The 24 columns physically written per hourly part; `month`/`day` are supplied by the Hive path,
# NOT stored in the file (so a hive_partitioning read yields the full 26-col FILL_COLUMNS contract).
PART_COLUMNS = tuple(c for c in FILL_COLUMNS if c not in PARTITION_COLS)
# Frozen-required fields: any null on a retained major row is fail-loud (abort the object).
REQUIRED_FIELDS = ("wallet", "coin", "ts", "px", "sz", "side", "start_position", "dir", "tid", "hash")

# flag predicates (RESTORE §5b ruling-A) — reusable in ad-hoc queries too
ZHASH_SQL = "hash = '0x' || repeat('0', 64)"
LIQ_ORIGIN_SQL = "liq_user IS NOT NULL AND lower(liq_user) = lower(wallet)"
VAULT_SQL = "dir = 'Net Child Vaults'"
# notional is a convenience column — scale-6 operands keep the product inside DECIMAL(38) (18+18 overflows).
# Exactness when needed comes from the string columns / the *_d casts, not from this aggregate.
NOTIONAL_SQL = "abs(TRY_CAST(sz AS DECIMAL(38,6))) * TRY_CAST(px AS DECIMAL(38,6))"

# ---- asset_ctx contract (Hyperliquid historical asset contexts; per-minute, ALL coins) ----
# Source: s3://hyperliquid-archive/asset_ctxs/{YYYYMMDD}.csv.lz4 (requester-pays, us-east-1). One CSV per
# day, ~201 coins × 1440 min. All 12 raw columns kept — nothing dropped (the ml-research loader dropped
# prev_day_px; we keep it). This is the INDEPENDENT price + only funding source for Tier-2 markout.
# NUMERICS ARE float64 (not exact-decimal strings like the fills tape): asset_ctx is REFERENCE data
# (prices/funding/OI/vol), never summed into an exact position ledger; verified BIT-EXACT to the source
# (the archive values are themselves float64), so float64 loses nothing and keeps the panel queryable.
# `ts` (epoch ms UTC, derived from ISO `time`) is the canonical join key with the fills tape (ms ints too).
# ⚠ JOIN = AS-OF, not equi/floored-equi (audit 2026-07-07). ctx `ts` is epoch-ms UTC, USUALLY minute-aligned
# but ~0.01% of rows (10,165 / 42 days) carry the source snapshot's odd seconds (e.g. :23) — so `fill.ts =
# ctx.ts` matches only fills exactly on a minute, and even a strict floored-equi-join MISSES those odd-second
# snapshots. Downstream markout must AS-OF join: for a fill at T take the latest ctx row with `ctx.ts ≤ T`
# for that coin (most-recent price). Leakage-safe direction (a fill never sees a future price). PRICE COLUMN:
# use oracle_px/mark_px (always > 0 for every coin) or filter mid_px > 0 — `mid_px == 0` is HL's no-book
# sentinel on ~17% of ALT rows (never majors) and would poison returns. COVERAGE: ctx spans 2025-08-01 ..
# 2026-06-29; fills run to 2026-06-30 (June-30 awaits the lagged archive) → RIGHT-CENSOR entries whose
# forward window passes the last ctx minute (spec P12). Known partial source day: 2026-05-30 (418/1440 min).
ASSET_CTX_COLUMNS = {
    "ts": "BIGINT", "time": "VARCHAR", "coin": "VARCHAR",
    "funding": "DOUBLE", "open_interest": "DOUBLE", "prev_day_px": "DOUBLE",
    "day_ntl_vlm": "DOUBLE", "premium": "DOUBLE", "oracle_px": "DOUBLE",
    "mark_px": "DOUBLE", "mid_px": "DOUBLE", "impact_bid_px": "DOUBLE", "impact_ask_px": "DOUBLE",
    "day": "BIGINT", "month": "BIGINT",
}
ASSET_CTX_NUMERIC = ("funding", "open_interest", "prev_day_px", "day_ntl_vlm", "premium",
                     "oracle_px", "mark_px", "mid_px", "impact_bid_px", "impact_ask_px")
# columns physically written per day part; month/day come from the Hive path.
ASSET_CTX_PART_COLUMNS = tuple(c for c in ASSET_CTX_COLUMNS if c not in PARTITION_COLS)
ASSET_CTX_SCHEMA_VERSION = "asset_ctx_v1_allcoins_2026-07-07"

# Leaf-only globs (the `day=*` / `coin=*` segment skips the manifest.parquet that lives one level up —
# a Hive '**' glob would otherwise error on the manifest's missing partition key).
DATASET_GLOBS = {
    "fills": "raw/fills/month=*/day=*/*.parquet",
    "asset_ctx": "raw/asset_ctx/month=*/day=*/*.parquet",
    "bars": "raw/bars/coin=*/*.parquet",
    "wallet_features": "derived/wallet_features/month=*/*.parquet",
}


def fills_views_sql(fills_glob: str) -> str:
    """A raw pass-through view + a typed/enriched `fills` view (DECIMAL casts + flag booleans + notional)."""
    casts = ",\n           ".join(f"TRY_CAST({c} AS {DEC}) AS {c}_d" for c in STR_DECIMAL_COLS)
    return f"""
CREATE OR REPLACE VIEW fills_raw AS
  -- union_by_name: zero-liquidation hours infer liq_user/liq_method as INT32 (all-None) instead of
  -- VARCHAR, so a first-file schema would make month-scoped reads of those months hard-error. (audit A)
  SELECT * FROM read_parquet('{fills_glob}', hive_partitioning=true, union_by_name=true);
CREATE OR REPLACE VIEW fills AS
  SELECT *,
           {casts},
           ({NOTIONAL_SQL}) AS notional_usd,
           ({ZHASH_SQL}) AS is_zhash,
           ({LIQ_ORIGIN_SQL}) AS is_liq_origin,
           ({VAULT_SQL}) AS is_vault
  FROM fills_raw;
"""


def simple_view_sql(name: str, glob: str) -> str:
    return (f"CREATE OR REPLACE VIEW {name} AS "
            f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true, union_by_name=true);")
