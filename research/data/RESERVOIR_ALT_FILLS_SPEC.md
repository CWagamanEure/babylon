# Reservoir alt-fills ingest — spec (quick per-wallet fills for ALL coins)

**Purpose.** Unlock the #1 structural lever for `../studies/wallet_flow/` and `../studies/xsec_statarb/`:
per-wallet fills for the **alt** universe (not just BTC/ETH/SOL/HYPE). The wallet-cohort signal is real but
breadth-starved on 4 majors; the reversal book needs cross-sectional dispersion only alts provide. Reservoir
gives the same per-fill contract we already use, as daily parquet — a fast alternative to the ~212 GB raw
`node_fills_by_block` restore.

**FIREWALL (non-negotiable).** This feeds the **research alt lane ONLY**. It is a third-party *derived* source
and is NOT block-identified (no block number; only `timestamp` + `tx_hash`). It therefore does **not** replace
the authoritative `node_fills_by_block` tape that Gate-A needs (block identity / zhash / transitions). Gate-A
stays on the node_fills restore. Reservoir → `research/` only, never `src/babylon` or `markout_study/gate_a`.

---

## 0. BINDING AUDIT COROLLARIES (4-agent swarm, 2026-07-09 — `audit/reservoir_ingest/`)
Swarm verdict: **source is byte-identical to node_fills on the majors overlap** (100% row-level join on
`(wallet, order_id, trade_id)`, every field equal, counts/notional 0.000% gap; both counterparties present,
Σsigned=0 for all 179 coins). Build approved. These corrections are **binding** on the writer:

**Firewall (data-integrity of the majors tape):**
- The alt view is a **separate `alt_fills` view**: add a NEW `schema.py:DATASET_GLOBS['alt_fills']` =
  `raw/alt_fills/month=*/day=*/*.parquet` (leaf-only), built by its OWN typed-cast (do NOT route through
  `fills_views_sql`, do NOT reuse `FILL_COLUMNS`/`STR_DECIMAL_COLS`). Never unioned into `fills`.
- Invariant comment in schema.py next to the `fills` glob: *"`fills` = node_fills majors ONLY; the literal
  `fills/` glob anchor is a firewall boundary; never a `raw/**` recursive glob; alt_fills is separate."*
- Grep-guard (CI/audit): no file under `src/babylon/` or `markout_study/gate_a/` may import
  `research.data.reservoir_ingest` / `research.data.db` or read `data/raw/alt_fills/`.

**Determinism / idempotency (Reservoir is MUTABLE — mass-republished 2026-03-20; node_fills is not):**
- Idempotency keys on the S3 **ETag**, not just SCHEMA_VERSION+commit. `_is_done(day)` also requires
  `shard.etag == head_object(day).ETag` (one cheap HEAD/day). Add a `verify` mode (HEAD all days, report drift,
  no re-download); treat the last ~2 day-partitions as **provisional** (re-HEAD unconditionally).
- **Raw** part keys on **ETag only** (pure fn of the source object); the **derived** step keys on
  SCHEMA_VERSION+commit. (Prevents a code change forcing a full ~$12 re-egress.)
- Manifest shard stores `{object_key, etag, last_modified, size_bytes, schema_version, code_commit, row_count,
  ts_min, ts_max, status}`. Atomic write: part first, done-shard second, `os.replace` (mirror `ingest.py`).
- `ts` = **int64 instant cast** `CAST(timestamp AS TIMESTAMP)::BIGINT`/pyarrow int64 — NEVER `epoch_ms()`/
  `AT TIME ZONE`/session-tz (repo `.venv` has no `pytz`; `epoch_ms` hard-errors). Value is already UTC epoch-ms.
- `order_id`/`trade_id`/`twap_id` are **uint64** → keep UBIGINT or store VARCHAR; never blind `CAST AS BIGINT`
  (overflow). Money casts DECIMAL→DECIMAL(38,18) or DECIMAL→VARCHAR, **never** DECIMAL→DOUBLE.
- Memory: per-day one file, `threads=1`, `memory_limit≈1200MB`, column projection, streaming `COPY`; never a
  global `read_parquet(month=*)` agg.

**Flow construction (because the tape is two-sided):**
- Aggregate signed flow over ALL rows = **identically 0**. The OFI/aggressor signal MUST filter to
  `crossed=true` taker rows, signed by side. Per-wallet cohort flow is fine (one row per wallet per fill).

**Universe (point-in-time):** the derived liquid-alt universe uses a **trailing, per-period re-ranked ADV**
(e.g. 30d window, ~$1–2M/day floor → ~50–66 names), require ≥W days listing history, drop on delist, handle
k-prefixed remaps. NOT a static full-sample top-N (survivorship + future-liquidity leak).

**Validation gate (§5) — majors-only gate is blind to alts; ADD alt-side asserts** (see §5).

**Scope/cost (corrected):** ingest `by_dex/hyperliquid/fills/perp/all` ONLY (siblings liquidations/twap/builder
are subsets → double-count; `global/fills/raw` is 2× all-dex+spot). ~109 GB / **~$12.4** worst-case (~$1 monthly
free tier, ~$0 in ap-northeast-1 EC2). Bulk `aws s3 cp` for the first pull — coin-filtered httpfs saves nothing
(file time-sorted, `coin` has no row-group stats); only column projection helps. No `event_index` → intra-ms
execution order unrecoverable on alts (irrelevant for flow/OFI; scope any chain check to collision-free wallets).

---

## 1. Source (verified 2026-07-09)
- **Bucket:** `s3://hydromancer-reservoir`  **Region:** `ap-northeast-1`  **Requester-pays:** yes  **Format:** Parquet
- **Path (HL perp fills, all coins):** `by_dex/hyperliquid/fills/perp/all/date=YYYY-MM-DD/fills.parquet`
  - one file per day; **~417 MiB/day**; other useful prefixes: `.../fills/perp/liquidations/…`,
    `global/fills/raw/…` (everything incl spot + all dexes). Other HIP-3 dexes under `by_dex/{xyz,cash,hyna,flx,km,vntl}/`.
- **Range:** `date=2025-07-28` … `date=2026-07-08` (daily, ~1-day lag) — **covers our 202508–202606 window in full.**
- **Access confirmed:** creds present (`aws sts get-caller-identity` → user cwagaman); `aws s3 cp … --request-payer
  requester --region ap-northeast-1` works. One day = 6.95M fills / 179 coins / 49k wallets (2026-06-01);
  alts alone = 3.6M fills / 175 coins / 22k wallets. All fields populated on alt rows.

## 2. Schema (27 cols) → our contract
Reservoir already types monetary/size as `DECIMAL(20,10)` (exact to 10 fractional digits). Map:

| Reservoir | our tape field | note |
|---|---|---|
| address | wallet | |
| coin | coin | |
| side | side | 'buy'/'sell' → normalize to B/A to match majors tape |
| price / size | px / sz | keep exact (Decimal or exact-string per [[babylon-conventions]]) |
| direction | dir | e.g. "Close Short", "Short > Long" |
| start_position | start_position | ✅ present — enables position reconstruction |
| realized_pnl | closed_pnl | |
| crossed | crossed | taker flag (order-flow imbalance) |
| fee / builder_fee / deployer_fee | fee / builder_fee / … | |
| timestamp (tz ms) | ts | → epoch ms (UTC) |
| tx_hash / order_id / trade_id | hash / oid / tid | NB no block number (unlike node_fills) |
| is_liquidation / liquidation_mark_px / liquidation_method | liq_* | |
| dex / asset_class / base_symbol / quote_symbol / fee_token / client_order_id / builder / priority_gas / twap_id | carry through | |

**Precision caveat:** DECIMAL(20,10) truncates any px/sz with >10 fractional digits. Validation (§5) must diff
Reservoir px/sz vs the node_fills exact-strings on the majors overlap to confirm no material loss.

## 3. Landing layout
- Writer: `research/data/reservoir_ingest.py` (NEW; separate from node_fills `ingest.py`). Source-tagged.
- Lake: `data/raw/alt_fills/month=YYYYMM/day=YYYYMMDD/fills.parquet` (mirror the existing hive layout so `db.py`
  views union cleanly), with a `source='reservoir'` column + a `_manifest/` shard per day recording
  `SCHEMA_VERSION`+`code_commit`+row counts (idempotent/crash-safe like the node_fills ingest — re-run resumes).
- `raw/` immutable; everything under `derived/` a pure function of it + commit.

## 4. Ingestion mechanics ("quick")
- **Full-window cost ≈ $16** (≈145 GB egress × ~$0.114/GB ap-northeast-1→internet + negligible GETs). Cheap
  enough to pull everything; no need to pre-filter coins.
- **Two modes** (pick per need):
  - (a) **Bulk cp then local process:** `aws s3 cp` each day → DuckDB local. Simple, one egress, ~145 GB local
    (data/ gitignored). Recommended for the first full pull.
  - (b) **Filtered read** via DuckDB httpfs with column projection + `WHERE coin IN (liquid subset)` — cuts
    egress if we only ever want ~50 names + ~9 columns. Test predicate/row-group pushdown on one day first.
- Idempotent: skip a day iff its part exists AND a done-shard records current SCHEMA_VERSION+commit; atomic
  rename. Re-run the same command after any crash. Memory-safe DuckDB (`memory_limit`, `threads=1`, month-by-month).
- Side normalization, ts→epoch-ms, and the liquid-alt universe filter (ADV floor, point-in-time) happen in a
  `derived/` step, not in raw.

## 5. VALIDATION GATE (the firewall against a bad source — required before any alt result)
Cross-reconcile Reservoir vs the **authoritative node_fills majors tape** on the BTC/ETH/SOL/HYPE overlap, per day:
1. **Fill counts** per (coin, day) — must match within tolerance (investigate any >0.5% gap; expect Reservoir
   may include TWAP/builder/ADL sub-fills our tape splits differently — characterize, don't hand-wave).
2. **Signed volume & Σnotional** per (coin, day).
3. **`crossed` ratio** (taker share) per coin — the OFI leg depends on it.
4. **`start_position` chains** — reconstruct running position per wallet from Reservoir and confirm it chains
   (same method as [[babylon-position-reconstruction]]); spot-check exact-string px/sz vs node_fills.
5. **Liquidation counts** per day.
If majors reconcile → trust Reservoir for alts. If not → quantify the discrepancy before using. Record result
in this file (a "GATE RESULT" block, mirroring RESTORE_PLAN's month-gate).

**ALT-SIDE asserts (the majors gate above is BLIND to alt completeness — a dropped alt coin/wallet/shard passes
it green). Run per (coin, day) over ALL coins:**
1. **Two-sided invariant (strongest completeness check):** Σ(signed size)=0 exactly AND maker-count==taker-count
   for every coin. A dropped side on any alt trade breaks it. (Verified holds for all 179 coins on 2026-06-01.)
2. **Unique fill key:** `(address, order_id, trade_id)` has zero duplicates (catches double-ingest/overlap writes).
3. **Precision asserts:** no post-load `price=0`/`size=0`; `max(abs(size|start_position)) < 1e10` (DECIMAL(20,10)
   integer ceiling — a 10B-unit meme position would overflow at Reservoir's own ingest); flag any coin whose min
   price needs >10 fractional digits.
4. **Truncation guard:** per-day `min(ts) < 00:15` and `max(ts) > 23:45` (catches a partial-day file).
Note: node_fills majors reconciliation proves FAITHFULNESS; the two-sided invariant is the only alt COMPLETENESS
proxy we have (no second source for alts).

## DESIGN REVISION — COMPACT 5-MIN FLOW AGGREGATE (2026-07-09; disk = binding constraint)
Local disk had only ~14 GB free; the faithful 109 GB per-fill mirror won't fit (all-coin 6-col projection = 18.6
GB; liquid-subset = 15.8 GB — the high-cardinality `wallet` hex dominates). User chose **compact-projected**.
Landed design: ingest aggregates each day to per **(wallet, coin, 5-min bucket, crossed) signed-notional flow**
→ `data/derived/alt_flow/` (~19 MB/day → **~6.4 GB full window**), download-temp-then-delete. View = `alt_flow`
(SEPARATE from `fills`). Keeps everything the wallet-cohort study needs (re-bucketable ≥5-min flow, taker/maker
split for OFI, two-sided Σ=0). DROPS per-fill px/sz/start_position/liq/fees — Reservoir stays the re-pullable
source of truth for those (no alt position-reconstruction from this lake). `flow_signed` = DOUBLE USD signal
aggregate (asset_ctx convention), not exact-string ledger. Supersedes the faithful-mirror wording in §2–§4/§6.

## GATE RESULT — day 20260601 (2026-07-09, aggregate design) — PASS (faithful to MACHINE PRECISION)
- **Majors reconciliation vs node_fills, same 5-min signed-notional grid: EXACT** — maxAbsΔ=$0.00, maxRelΔ≈1e-14
  (machine epsilon), Σsigned=0 both sides, all 4 majors (576 cells each). The aggregate loses nothing vs the tape.
- **Alt-side ALL PASS** (179 coins): two-sided max|Σ flow_signed|=$0.0000; full-day coverage; 1,257,995 agg rows.
- **Firewall verified:** `fills` view stays 4 majors, no `source`/alt leak; `alt_flow` is a separate view.
- Ingest: ETag `b0a19a7a…-53`, 15.4 MB part, status done. Full-window pull launched (`range 20250801 20260630`).

## 6. Downstream (what it unlocks)
- Re-run `wallet_flow` cohort freeze + book on a **~50-name liquid-alt cross-section** (breadth → gross rises at
  fixed turnover; the code-audit swarm pinned 4-name breadth as the gross cap).
- Re-run `xsec_statarb` reversal with real dispersion; test the wallet-cohort **conditioner** cross-sectionally.
- Per-coin: is the informed-flow edge HL-native-concentrated (HYPE-like) or broad across alts? (the open question).

## 7. Build order (repo flow: this doc → swarm audit → build → validate)
1. **Swarm audit** this spec (data-integrity, firewall-leakage, determinism-repro, docs-consistency).
2. **Stage-1 gate:** one day (DONE — schema + fields + coverage verified 2026-06-01; access + cost confirmed).
3. **Month gate:** ingest 202508, run §5 validation vs node_fills majors; record GATE RESULT.
4. **Full window:** 202508…202606; manifest; then derived liquid-alt universe + panels.
