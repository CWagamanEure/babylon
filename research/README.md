# `research/` — the analysis workbench

The research lane of Babylon. **Never imported into the deployable engine (`src/babylon/`) and never
shipped.** This is where the Hyperliquid tape is restored, queried, and turned into per-trader features.

> **Firewall (load-bearing).** `research/` computes *real* per-wallet PnL and markout — it is the
> **exploratory** lane. It must **never** feed the frozen Gate-A pipeline in `research/markout_study/gate_a/`
> (that stays on synthetic / nullized data). Two lanes, one wall. See `docs/DATA_ARCHITECTURE.md §2`
> and `docs/WALLET_FEATURES_SPEC.md §7`.

## Package layout

```
research/
  data/       # THE data source — tape, query layer, ingest, episodes, features   (this README's focus)
  lib/        # shared rigor toolkit every study imports: stats/null models, bootstrap CIs,
              #   MDE/power, walk-forward CV, cost model, portfolio backtester
  studies/    # one subdir per strategy investigation, drawing on data/ + lib/    — see studies/README.md
```

`data/` is the shared substrate, `lib/` the shared methodology, `studies/` the actual investigations.
New strategy research goes in `research/studies/<name>/` (copy `studies/_template/`). The rest of this
file documents `data/`.

## How you query the data

DuckDB as an embedded lens over the Parquet lake — **no ETL, no copy**. The Parquet stays the source of
truth; views are recreated fresh each session.

```python
from research.data.db import connect
con = connect()                                    # in-memory DuckDB, views over data/raw + data/derived
con.sql("SELECT coin, count(*) FROM fills WHERE month=202508 GROUP BY coin")
```

Views registered by `connect()` (any whose Parquet doesn't exist yet is silently skipped):

| View             | Grain                              | Notes |
| ---------------- | ---------------------------------- | ----- |
| `fills`          | one row per fill (majors only)     | typed/flagged convenience layer over `fills_raw` |
| `fills_raw`      | raw node_fills contract            | pass-through, `hive_partitioning=true` |
| `asset_ctx`      | per-minute, per-coin (all ~201)    | price / funding / OI reference panel |
| `bars`           | 5-min close lattice per coin       | **glob defined, not built yet** (`bars.py` TODO) |
| `wallet_features`| per (wallet, coin, month)          | **glob defined, not built yet** (`features.py` TODO) |

### Query conventions (do not skip these)
- **Integer partitions.** `WHERE month=202508` and `day=YYYYMMDD` — integers, not strings. They prune
  row groups, so filter on them.
- **Money/size are exact strings**, cast to DECIMAL on demand — **float is never authoritative**. The
  `fills` view exposes `*_d` casts (`px_d`, `sz_d`, `closed_pnl_d`, `fee_d`, …) and `notional_usd`.
- **asset_ctx joins are AS-OF** (`ctx.ts ≤ fill.ts` per coin), never an equi-join. Use `oracle_px` /
  `mark_px`; filter `mid_px > 0` (`mid_px == 0` is HL's no-book sentinel, ~17% of ALT rows, never majors).
- Flag helpers live in `schema.py`: `is_zhash`, `is_liq_origin`, `is_vault` (plus the raw
  `ZHASH_SQL` / `LIQ_ORIGIN_SQL` / `VAULT_SQL` / `NOTIONAL_SQL` predicates).
- `render_catalog()` emits the `CREATE VIEW` SQL as text for `duckdb` CLI use.

## Modules (`research/data/`)

| Module              | Role |
| ------------------- | ---- |
| `schema.py`         | **Source of truth** for the query layer: normalized node_fills + asset_ctx contracts, `DATASET_GLOBS`, DuckDB view SQL, szDecimals, flag predicates. |
| `db.py`             | The query entry point — `connect()` registers the views; `render_catalog()` for CLI. |
| `ingest.py`         | **The only writer of `data/raw/fills/`.** Streaming S3 restore of `node_fills_by_block` → majors fill tape. Idempotent + crash-safe (atomic-rename parts + manifest shards). |
| `ingest_ctx.py`     | **The only writer of `data/raw/asset_ctx/`.** Ingests HL historical asset-context (price / funding / OI). |
| `ledger.py`         | **Neutral shared math** — exact integer-tick position walk + transition classification (INCREASE / REDUCE / CLOSE / FLIP). Deliberately re-implemented (not imported from `gate_a/`) to hold the firewall. |
| `episodes_build.py` | Tier-1 lifecycle-episode builder → `data/derived/episodes/`. See below. |
| `validate.py`       | Replays a restored month against the `RESTORE_PLAN_v1` oracle (fill counts, transition-class splits). |

## Data on disk (`data/` — gitignored, all regenerable)

```
data/
  raw/                                      # IMMUTABLE, archive-sourced — the only precious bytes
    fills/month=YYYYMM/day=YYYYMMDD/hourHH.parquet   # authoritative tape, majors {BTC,ETH,SOL,HYPE}
                                            #   202508 … 202606  (2025-08-01 … 2026-06-30), ~3.5 GB/mo
    fills/_manifest/ + manifest.parquet     # ingest checkpoint (leaf glob day=* skips these)
    asset_ctx/month=YYYYMM/day=…            # per-minute price/funding, all coins, 202508 … 202607
    bars/coin=…                             # 5-min lattice — NOT BUILT YET
  derived/                                  # REGENERABLE, code-stamped — safe to blow away + rebuild
    episodes/month=YYYYMM/episodes.parquet  # Tier-1 episodes (being built)
    episodes/_checkpoint/carry_after_*.pkl  # per-(wallet,coin) carry-seed, one per committed month
    wallet_features/                        # NOT BUILT YET
```

## Ingest / resume

Local, `.venv/bin/python`. Idempotent + crash-safe — **just re-run the same command after any crash**;
it resumes from the manifest.

```bash
python -m research.data.ingest hour 20250801 12      # one object (stage-1 gate)
python -m research.data.ingest month 202508          # one month (~744 objects)
python -m research.data.ingest range 202508 202606   # full window
python -m research.data.ingest manifest              # consolidate shards → manifest.parquet + report
```

Bump `SCHEMA_VERSION` in `schema.py` to force re-ingest on a contract change. Validate a fresh month
against the recorded oracle in `research/markout_study/discovery/RESTORE_PLAN_v1.md`.

## Episodes (`episodes_build.py`)

An **episode** = a (wallet, coin) position lifecycle: opens flat→nonzero (INCREASE), adds/reduces are
intra-episode, and **only a CLOSE (→flat) or FLIP (sign change) terminates it**. (Distinct from the
frozen Gate-A markout episode, which stops at the first qualifying reduce.) It is the atomic, durable
base of the trader-feature system (`docs/WALLET_FEATURES_SPEC.md` Table 1).

```bash
python -m research.data.episodes_build all_carry   # memory-safe per-month build, carry-seed threaded
python -m research.data.episodes_build 202508       # single month
python -m research.data.episodes_build reconcile    # prove carry-seed build == whole-tape on a subsample
```

`all_carry` is the production path: **resumable** (skips the longest committed prefix; a month commits
only after both its parquet and its `carry_after_<month>.pkl` land, checkpoint written last) and
**carry-seed threaded** so a position open across a month boundary stays ONE episode. The in-RAM
full-tape path is deliberately not exposed (OOM risk).

## Not built yet
- `bars.py` — 5-min close lattice from `asset_ctx` → `data/raw/bars/` (unblocks Tier-2 markout).
- `features.py` — the `addr_coin_features` / `addr_features` panels → `data/derived/wallet_features/`.

See `docs/WALLET_FEATURES_SPEC.md` for the full three-table trader-feature design and `docs/DATA_ARCHITECTURE.md` for the overall plan.
