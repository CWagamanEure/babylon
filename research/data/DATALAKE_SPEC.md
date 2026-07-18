# incerto-datalake-v1 — Hyperliquid data layout (DRAFT v0.2, surveyed + pending user review)

Destination: `s3://incerto-datalake-v1` (DigitalOcean Spaces, nyc3,
endpoint `https://nyc3.digitaloceanspaces.com`; credentials = `INCERTO_RAW_STORE_S3_*` vars in
`~/incerto/.env` — access verified 2026-07-16). Currently holds CoinGecko data only; this spec designs
the Hyperliquid side. Motivation: local disk is at the wall (3.9GB free of 233GB), which forced the
aggregate-and-discard design for alt ingest; with the lake we keep FULL per-fill data and stop paying
$12.5 re-egress every time a study needs a column we dropped.

## Principles (carried over from the local lake — see docs/DATA_ARCHITECTURE.md)
1. **raw/ is immutable + source-tagged; derived/ is a pure function of raw + code commit.** Every derived
   prefix carries a `_META.json` (schema_version, code_commit, input manifest).
2. **Hive partitioning** `month=YYYYMM/day=YYYYMMDD/` everywhere — DuckDB httpfs globs work unchanged
   against Spaces (`SET s3_endpoint='nyc3.digitaloceanspaces.com'; SET s3_region='nyc3'`).
3. **Exact decimals** — monetary/size columns stay DECIMAL/exact-string in parquet; float never authoritative.
4. **Manifest sidecars** `_manifest/day=YYYYMMDD.json` per day (etag of source object, row_count, bytes,
   schema_version, code_commit) — idempotent resume + drift detection (Reservoir is MUTABLE).
5. **Firewall unchanged:** the lake is a RESEARCH-lane store. Gate-A stays on the local node_fills tape;
   `src/babylon/` never reads the lake. Reservoir-derived data is not block-identified.
6. **Local disk becomes a cache, not the store.** Hot working sets (current study's derived tables) live
   locally; everything else evictable and re-readable from the lake.

## Observed existing convention (surveyed 2026-07-16)
The lake is new (58 objects / ~10MB, first writes 2026-07-15) and is a **raw API-snapshot store**:
`source=coingecko/dataset={asset_platforms,coin_detail,coins_list,coins_markets}/date=YYYY-MM-DD/`
with leaf files `HHMMSS-<contenthash>.json.gz` (append-only event log, one object per API call).
Hive keys are `source=` / `dataset=` / `date=` (ISO date, single level — not month=/day=).

## Proposed layout (conforms to the observed convention)
```
s3://incerto-datalake-v1/
  source=coingecko/...                              # existing — untouched
  source=hyperliquid_reservoir/                     # raw mirror of a third-party bulk source
    dataset=perp_fills/date=YYYY-MM-DD/fills.parquet      # FULL per-fill, ALL wallets/coins (the unlock)
    dataset=perp_fills_manifest/date=YYYY-MM-DD/manifest.json   # source etag, counts, schema_version, commit
  source=hyperliquid_node/                          # OPTIONAL phase-2 mirror of local authoritative data
    dataset=asset_ctx/date=YYYY-MM-DD/ctx.parquet         # per-minute mark/mid/funding/OI (2.8GB total)
    dataset=fills_majors/date=YYYY-MM-DD/…                # 34GB majors tape backup (Gate-A still runs local)
  source=babylon_derived/                           # pure functions of raw + code commit (_META in manifest)
    dataset=alt_universe_wallet_coin_day/date=YYYY-MM-DD/part.parquet
    dataset=alt_universe_open_entries/date=YYYY-MM-DD/part.parquet
    dataset=<study snapshots>/...                         # promoted at freeze points only
```
Deviation from the snapshot-store leaf convention, on purpose: bulk daily datasets use ONE deterministic
file per day (`fills.parquet`, idempotent overwrite + manifest sidecar) rather than `HHMMSS-<hash>` event
files — these are day-complete mirrors, not append-only API events. DuckDB reads either style
(`SET s3_endpoint='nyc3.digitaloceanspaces.com'`; glob `date=*` with hive_partitioning; `date=2025-08*`
selects a month).

## What this changes for the current program
- **Writer = `research/data/lake_reservoir_ingest.py`** (standalone on the droplet; supersedes the local
  `alt_universe_ingest.py` plan): per day → download Reservoir object → (a) write the FULL projected
  per-fill parquet to `source=hyperliquid_reservoir/dataset=perp_fills/` (upload, free inbound), (b) compute
  the two aggregate layers → `source=babylon_derived/`, (c) delete the temp, (d) manifest LAST (status:
  ok|source_missing; source etag post-download; rows_source/rows_dropped_nonperp/ts_min/ts_max accounting;
  schema_version + code_commit keying). Same one pass, same $12.5 AWS egress — but the raw survives, so
  position reconstruction on alts, MAE/MFE, consensus/position-state, and ANY future selector need no re-pull.
- **Column projection for perp_fills (FROZEN v2, audited):** keep wallet(address), coin(base_symbol),
  ts(=epoch_ms(timestamp), instant-based), px, sz, side (source 'buy'/'sell' — NOT normalized to B/A;
  normalize downstream), direction, start_position, crossed, realized_pnl, fee, builder_fee, is_liquidation,
  liquidation_mark_px, liquidation_method, order_id/trade_id/twap_id (UBIGINT), tx_hash.
  Drop: dex, asset_class (filtered ='perp'; drop count recorded per day as rows_dropped_nonperp),
  quote_symbol, fee_token, client_order_id, builder, priority_gas, deployer_fee.
  Estimated ~60-70% of source bytes → ~90-100GB total.
- **Conscious deviations from RESERVOIR_ALT_FILLS_SPEC §0 (recorded per 2026-07-16 audit):** the
  last-2-days-provisional rule is subsumed for the fixed 20250801–20260630 window (every non-force run
  re-HEADs every day; `verify` mode reports drift) — it becomes LIVE again if a trailing-edge daily cron is
  added, which must then force-re-ingest T−1/T−2.
- Local `data/raw/alt_fills` (133-wallet slice) and `alt_flow` (3.6GB) become REDUNDANT once the full raw
  is in the lake → evict locally, freeing ~4.2GB immediately.

## Execution plan (choose one)
| Path | Egress cost | Wall-clock | Notes |
|---|---|---|---|
| A. Local relay (laptop) | $12.5 AWS | download 139GB + upload ~95GB through home pipe — slow (day+) | zero setup |
| B. **DO droplet in nyc3 (recommended)** | $12.5 AWS | hours (DC bandwidth both ways; droplet→Spaces same-region is fast/free) | reuse/resize the basket droplet if it's nyc3, else $6-12 droplet for a day |
| C. AWS EC2 ap-northeast-1 relay | ~$0 AWS-side (same-region S3 read) but ~$9-12 EC2→DO internet egress | hours | only worth it if we re-pull often — we won't, the point of the lake is pull-once |

## Costs (DO Spaces)
Base $5/mo = 250GiB storage + 1TiB outbound. reservoir_fills (~95GB) + asset_ctx (3GB) + derived (~5GB)
fits the base tier. Adding the node_fills_majors mirror (34GB) still fits (~137GB). Reads from the laptop
count against the 1TiB/mo outbound allowance — column-projected DuckDB scans keep this small; hot tables
cached locally anyway.

## Resolved
- ~~Credentials~~ — `INCERTO_RAW_STORE_S3_*` in `~/incerto/.env`, verified working (list/read).
- ~~Existing convention~~ — surveyed above; layout v0.2 conforms (`source=`/`dataset=`/`date=`).
- No `source=hyperliquid*` prefix exists yet — clean namespace.

## Open questions (need user)
1. **Droplet** — user will provide a droplet for the ingest (pending). Needs: nyc3 (same region as the
   bucket), ~2GB RAM (duckdb aggregate at 6GB mem limit is comfortable at 4GB+; can lower), ~5GB scratch
   disk, aws cli, AWS creds for the requester-pays Reservoir read + the Spaces creds. The AWS→droplet
   leg (~139GB) bills $12.5 to our AWS account regardless of where it runs.
2. **Scope of phase 1** — reservoir_fills (~95GB) + alt_universe derived only? Or also asset_ctx (3GB)
   and the 34GB node_fills_majors mirror now?
3. **Ongoing sync** — Reservoir publishes daily with ~1-day lag; add a cron on the droplet to append
   yesterday's object (keeps the lake current for the forward paper-accumulation lever)?

## Serving layer — PostgreSQL (incerto) vs the lake (decided 2026-07-16)

**Split: lake = facts (immutable, big, scanned); Postgres = state (small, current, served).**
- The lake keeps everything analytical: fills, episodes, markouts, wallet_coin_day panels,
  informedness pool tables. DuckDB/httpfs is the query surface; no analytical mirror in Postgres.
- The **incerto** repo owns the Postgres serving layer (TICKET-0034 there): schema `signals` with
  `hl_wallet_scores` (per-wallet-fold informedness: nd/mu/sd/metric/t/z/p_informed + provenance) and
  `hl_cohort_members` (fold × arm × wallet roster: rank, metric, scale, large/fresh flags).
  Promotion = `incerto-hl-promote` CLI (idempotent upserts; reads babylon's
  `informedness/fold=*/pool.parquet` + `alt_universe_cohorts.json`).
- Flow is ONE-DIRECTIONAL: lake → research (babylon) → promotion (incerto) → Postgres → operational
  consumers. Research never reads Postgres as an input (firewall). Babylon may read the `signals`
  tables for ops/dashboards, never for selection/inference.
- Future serving tables (same home, when forward paper-trading arms): live roster, follow journal
  (transactional), run registry. Wallet↔entity bridge to `core.entities` is incerto future work.

## ROLLING OPERATION (activated 2026-07-17)

The lake is no longer a fixed-window snapshot: a daily cron on the nyc1 droplet (`10.116.0.4` via jump
`167.71.29.107`) extends it continuously past the 20250801–20260630 study window (~$0.04/day
requester-pays).

**Daily cron** — `/root/daily_lake_sync.sh` (mirrored in-repo at `research/data/daily_lake_sync.sh`),
crontab `30 6 * * *` (06:30 UTC, after Reservoir's ~1-day-lag publish):
- Ingests **T-1 and T-2 with `--force`** — the trailing-edge provisional rule from
  RESERVOIR_ALT_FILLS_SPEC §0 is now LIVE: Reservoir republishes recent days, so the last two days are
  provisional and must be unconditionally re-ingested (force deletes the manifest first, then re-pulls).
- Ingests **T-3 without force** — etag-keyed catchup; a no-op when the day is already current.
- Logs to `/root/daily_lake_sync.log`; exits nonzero on any failed day.
- Promotion leg (**ACTIVE 2026-07-18**): after the ingest legs, promotes **yesterday's wallet-coin-day
  partition** into the incerto Postgres serving layer via the audited `incerto-hl-promote` CLI
  (TICKET-0063 wrapper `/root/incerto/scripts/hl_promote_daily.sh`, run with no args = `--commit`).
  Idempotent (ON CONFLICT upsert); promotion failure sets rc=1 (alerts) but never rolls back the lake
  sync. Deps: `/root/incerto/.venv` (incerto`[promotion]` + sqlalchemy + `psycopg[binary]`),
  `/root/incerto.env` (owner-provided `INCERTO_DATABASE_URL` + `INCERTO_RAW_STORE_S3_*`),
  `HL_CODE_COMMIT` stamped from `LAKE_CODE_COMMIT`. The **roster promotion (scores + cohorts) stays
  SUPERVISED**: the automated leg does the daily wcd only and stands down on the 1st — a human runs the
  monthly scoring locally, reviews pool/null-fit, then promotes the roster (which also catches up the
  turn-of-month wcd day).
- Ingest code: `/root/lake_reservoir_ingest.py` = deployed copy of
  `research/data/lake_reservoir_ingest.py` (2026-07-17 builder_fee COALESCE fix); `LAKE_CODE_COMMIT`
  in `/root/.lake_env` is stamped from babylon `git describe --always --dirty` at each deploy.

**Monthly scoring runbook (run locally on the 1st of month M, or any day after):**
```
.venv/bin/python -m research.studies.copy_cohort.alt_select --month <M>   # e.g. 202608 on 2026-08-01
# then review pool_size + null_fit vs historical folds before any promotion (supervised)
```
Rolling mode computes formation = 3 calendar months strictly before M by calendar arithmetic and
REFUSES to run if the lake lacks wallet_coin_day partitions for any formation month. Outputs:
`data/derived/copy_cohort/informedness/fold=M/pool.parquet` + a merge-don't-truncate fold update in
`data/derived/copy_cohort/rolling_cohorts.json` (the frozen research `alt_universe_cohorts.json` is
never touched). **Promotion is supervised:** a human sanity-checks the new fold (pool size and null
fit within historical bands, cohort overlap sane) before it is promoted to the incerto serving layer —
no automatic promotion from cron.
