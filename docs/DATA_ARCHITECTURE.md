# DATA ARCHITECTURE & REPO CLEANUP PLAN

**Status: PLAN ONLY (2026-07-06). No file moves yet.** Execute after the backfill completes and the
restore is validated end-to-end. Goal: one clean system — raw archive-sourced tape, versioned ingest/feature
code, and a queryable per-trader table — with the dead-end sprawl archived, not carried.

> **CRASH-RECOVERY NOTE (2026-07-06).** A mid-ingestion crash wiped the scratchpad that held the
> original `full_backfill.py` **and** the restored 2025-08 tape (both were uncommitted). Neither the
> tape nor its manifest survived (verified: no parquet on disk carries the `block_number`/`event_index`/
> `src_object` fingerprint; nothing data-shaped was written on the crash day). The ingestor has since
> been **rebuilt from RESTORE_PLAN_v1 §1–2** as `research/data/ingest.py` (Phase 1 item below, done) —
> now saved in the repo tree, not a scratchpad, so it survives a crash (commit pending user go). The tape
> itself must be re-streamed
> from S3 (no on-disk checkpoint to resume from). Run venue: **local** (user decision 2026-07-06).
> `hl_hist/` is NOT the tape — it is per-coin asset-context metadata (funding/OI/px), not per-wallet fills.

## 1. Target layout
```
data/                              # gitignored — large; all regenerable from archive + code
  raw/                             # IMMUTABLE, archive-sourced. Never edited in place.
    fills/month=YYYYMM/day=.../    # authoritative restored node_fills tape (from S3 node_fills_by_block)
    bars/coin=.../                 # 5-min close lattice per coin
    manifest.parquet               # ingestion manifest (object → rows, schema, commit)
  derived/                         # REGENERABLE, code-stamped. Safe to delete + rebuild.
    wallet_features/month=YYYYMM/  # the per-(wallet,coin,month) rollup (§3)
  follow/                          # EXISTING live copy-trade paper system state — leave as-is
src/babylon/                       # DEPLOYABLE trading engine — production code ONLY, no research
research/                          # RESEARCH WORKBENCH (Option B) — separate from the shippable package
  data/                            # shared research tooling (VERSIONED)
    ingest.py                      # streaming ingestor (promote scratchpad/full_backfill.py)
    schema.py                      # normalized fill schema + szDecimals + flag helpers (shared w/ gate_a/common)
    bars.py                        # 5-min lattice builder
    features.py                    # builds wallet_features (§3)
  markout_study/                   # the STUDY folded in: gate_a pipeline + discovery specs + latest report
    gate_a/                        # the firewalled Gate-A pipeline
    discovery/                     # frozen specs + audits (keep — audit trail)
    archive/                       # older report_v1..v5, figs_v1..v5, one-off scripts (collapsed here)
```
**Option B rationale:** `src/babylon/` is the thing you'd deploy/trade with; `research/` is the analysis
scaffolding beside it. Research code is never imported into the engine and never shipped. `research/` runs as
its own rootdir (path-add or a light namespace), so imports like `from gate_a.common import …` keep working
after `markout_study/` relocates under it — a physical move, not an import rewrite.

## 2. Two hard rules
- **Raw vs derived.** `raw/` is immutable and archive-sourced — the only precious bytes. Everything in
  `derived/` is a pure function of `raw/` + a code commit, so it can be blown away and rebuilt. Every derived
  parquet carries `code_commit`, `built_at`, `schema_version` columns.
- **Firewall.** `wallet_features` computes **real per-wallet PnL/markout** → it is an **exploratory** research
  tool and must **never** feed the frozen Gate-A pipeline (that stays firewalled on synthetic + nullized data).
  Two lanes, one wall — same discipline we've held.

## 3. `wallet_features` — the per-trader table
> **SUPERSEDED (2026-07-06) by `docs/WALLET_FEATURES_SPEC.md` (v2).** After the 5-agent swarm audit + a
> ChatGPT-schema review, the design moved from a flat `(wallet,coin,month)` summary to a **3-table system**
> (episode base + `(address,coin,cutoff,window)` leakage-safe panels + cross-coin rollup), tiered by data
> dependency (Tier-1 fills-only now; Tier-2 markout blocked on re-ingesting `hl_hist`; Tier-3 cost on L2).
> The table below is kept as the original column sketch; **build from the v2 spec, not this.**

**Grain: one row per `(wallet, coin, month)`.** Atomic unit; roll up to wallet / wallet-coin / wallet-month
freely. Columns (all derivable from the clean tape):

| Group | Columns |
|---|---|
| Identity | wallet, coin, month, first_ts, last_ts |
| Activity | n_fills, n_episodes, active_days, **active_weeks**, avg_hold_ms, median_hold_ms |
| Role | taker_fills, maker_fills, **taker_share**, maker_share (from `crossed`) |
| Volume | volume_usd, buy_volume_usd, sell_volume_usd |
| PnL (price) | **realized_pnl_usd** (Σ `closedPnl`), fees_usd (Σ `fee`), realized_net_usd |
| Unrealized | end_position_qty, avg_cost_basis, end_mark_px, **unrealized_pnl_usd** |
| Directional | long_share, short_share, **short_pnl_usd** (anti-beta tell) |
| Risk / behavior | **max_adverse_excursion_usd**, **adds_while_underwater_pct** (martingale detector), max_position_notional |
| **Informed-trader signals** | **markout_bps_{1h,4h,24h}** (mean signed post-entry return, entry=first 5-min close after fill), **edge_bps** (realized_net / volume), **win_rate** (share of profitable closed episodes), **pnl_per_active_day**, **beta_neut_pnl_usd** (PnL residual after BTC/ETH-beta hedge), n_closed_episodes |
| Flags | flagged_fills (zhash+liq+vault), n_liquidations |
| Provenance | code_commit, built_at, schema_version |

**PnL conventions (state them, don't bury them):**
- `realized_pnl_usd = Σ closedPnl` — **price PnL only**.
- `unrealized_pnl_usd = end_position_qty × (end_mark_px − avg_cost_basis)`, signed by direction;
  **mark = last 5-min close of the month**; `avg_cost_basis` reconstructed from the ledger (running VWAP of
  the open side). Convention pinned so the number is reproducible.
- ⚠️ **Funding is NOT in `node_fills_by_block`.** So neither PnL figure includes funding — this is *price* PnL,
  not full economic PnL. Label it everywhere. (Full economic PnL would need a separate funding feed.)
- The **risk columns are deliberate**: MAE + adds-while-underwater are exactly what unmasked the martingale
  wallet `0xd3e15446`, and short_pnl is the anti-beta tell. Bake in what fooled us so it can't fool us twice.

**Informed-trader signals (the "is this trader skilled?" columns):**
- **markout is the core skill tell** — PnL can be beta/luck, but consistent positive post-entry markout across
  many episodes is edge. `markout_bps_h = mean over the wallet's episodes of dir·(P(entry+h)/P(entry) − 1)·1e4`,
  entry = first 5-min bar close strictly after the fill (needs `data/raw/bars/`, so **features.py depends on
  bars.py**). Report the horizons {1h,4h,24h}; keep n_closed_episodes alongside so a high markout on 2 trades
  is visibly low-N, not mistaken for skill.
- **`edge_bps` and `win_rate`** are volume-normalized skill; **`beta_neut_pnl_usd`** strips the market so a
  wallet that just rode BTC beta doesn't read as informed; **`pnl_per_active_day`** is a consistency proxy.
- ⚠️ **Firewall (repeat):** these markout/PnL aggregates make `wallet_features` the **exploratory** lane. It
  must **never** feed the frozen Gate-A pipeline — Gate-A stays on synthetic + nullized data. Same wall as §2.
- ⚠️ **Winner's-curse guard:** ranking wallets by in-sample markout/PnL is the exact trap the markout study
  already hit (memory `babylon-markout-study`, `babylon-oos-persistence`) — most top-of-table is noise. This
  table is for *querying + hypothesis generation*, not for declaring a wallet informed; any "informed" claim
  still needs OOS persistence + the multiplicity gauntlet, not a single sort on this file.

## 3b. The query story — how you actually use it
The table is Hive-partitioned Parquet at `data/derived/wallet_features/month=YYYYMM/` and is already wired as a
DuckDB view by `research/data/db.py` (`connect()` registers `wallet_features` when the parquet exists). So the
"easy db file" is just:
```python
from research.data.db import connect
con = connect()
con.sql("SELECT wallet, sum(realized_net_usd) pnl, sum(volume_usd) vol, "
        "avg(markout_bps_4h) mo FROM wallet_features WHERE taker_share>0.5 "
        "GROUP BY wallet HAVING sum(n_closed_episodes)>=50 ORDER BY mo DESC")
```
Parquet stays the source of truth (no ETL, rebuildable). `features.py` can **also** emit a single materialized
`data/derived/wallet_features.duckdb` for one-file portability if you want to hand it around — but the view over
Parquet is the default and needs nothing extra.

## 4. Cleanup & migration checklist (sequenced — safety first)
- **Phase 0 (now):** this doc. No moves.
- **Phase 1 — after backfill completes:** promote validated code scratchpad→`research/data/`
  (`ingest.py` ✅ **done** — rebuilt from RESTORE_PLAN §1–2, in-repo, 1-hour gate PASS: 192,284 major
  fills, hard_errors=0, resumable manifest; `schema.py` ✅ done; `bars.py` — still to build); re-stream the
  tape → `data/raw/fills/` (was migrate; the scratchpad copy is gone); build the clean 5-min lattice →
  `data/raw/bars/`. `data/` already in `.gitignore` (anchored `/data/`).
- **Phase 2 — after restore validated end-to-end vs the old tapes:** only then delete the dirty tapes in
  `scratch_conv/` (11 GB) and archive `other_repo_notes/` (3.6 GB, the `his` export). **Do NOT delete before
  validation** — they are the join-validation reference.
- **Phase 3 — study tidy:** relocate `markout_study/`→`research/markout_study/`; collapse `report_v1..v5` +
  `figs_v1..v5` into `research/markout_study/archive/` (keep the latest report + `technical_appendix`; git
  history holds the rest); triage the 99 scripts in `markout_study/src/` — reusable → `research/data/` or
  `gate_a/`, one-offs → `archive/`.
- **Phase 4 — build the table:** implement `features.py`, write `data/derived/wallet_features/`.

**Nothing here is destructive until Phase 2, which is gated on restore validation.** Archive (or lean on git
history), don't hard-delete, the specs/findings/reports — they're the audit trail.

## 4b. Query layer — DuckDB over the Parquet lake
**Pattern: DuckDB as an embedded query engine reading the partitioned Parquet directly — no ETL/ingestion
step.** The Parquet lake stays the source of truth; DuckDB is just the lens. Three small pieces:

**Implemented (2026-07-06) — `research/data/{schema.py, db.py}`, smoke-tested end-to-end.**

1. **Views defined in `schema.py`** (source of truth), e.g. the enriched `fills` view:
   ```sql
   -- leaf-only glob: the `day=*` segment SKIPS the manifest that sits at month=YYYYMM/ level.
   -- A '**' glob instead trips DuckDB's hive check ("key day not found") on the manifest — verified.
   CREATE OR REPLACE VIEW fills_raw AS
     SELECT * FROM read_parquet('data/raw/fills/month=*/day=*/*.parquet', hive_partitioning=true);
   CREATE OR REPLACE VIEW fills AS      -- typed + flagged convenience layer
     SELECT *, TRY_CAST(px AS DECIMAL(38,18)) AS px_d, …,
            abs(TRY_CAST(sz AS DECIMAL(38,6))) * TRY_CAST(px AS DECIMAL(38,6)) AS notional_usd,
            (hash = '0x'||repeat('0',64))                    AS is_zhash,
            (liq_user IS NOT NULL AND lower(liq_user)=lower(wallet)) AS is_liq_origin,
            (dir = 'Net Child Vaults')                        AS is_vault
     FROM fills_raw;
   ```
   `month`/`day` are **INTEGER** partition columns (`WHERE month=202508`, not `'202508'`). Money fields are
   exact **strings** → `TRY_CAST` to DECIMAL on demand (never float); `notional_usd` uses scale-6 operands
   because `DECIMAL(38,18)²` overflows 38 digits — it's a convenience aggregate, exactness lives in `*_d`.

2. **Thin helper — `research/data/db.py`:** `connect()` returns an in-memory DuckDB connection with the views
   registered over `data/raw` + `data/derived`, **skipping any dataset whose Parquet doesn't exist yet** (so it
   works while the tape is still landing). Views recreate fresh each session; nothing is copied into DuckDB —
   the Parquet stays the source of truth. `render_catalog()` emits the SQL for `duckdb` CLI use.

3. **Partition layout** (§1) — `fills` by `month=/day=`, `bars` by `coin=`, `wallet_features` by `month=`.
   **Manifest lives OUTSIDE the partition tree** (`data/raw/fills/_manifest/…`), or the leaf glob must exclude
   it — a manifest inside `month=YYYYMM/` breaks a naive `**` read.

**`features.py` is a hybrid**, and the split is deliberate:
- **DuckDB SQL** for the additive aggregations (volume, `Σ closedPnl`, taker share, counts, active days) —
  fast group-bys straight over `fills`.
- **Python (per wallet-coin ledger walk)** for the path-dependent columns (avg cost basis, unrealized mark,
  MAE, adds-while-underwater) — these need the sequential episode reconstruction from `episodes.py`, which SQL
  can't express cleanly. Join the two, `COPY` back to `data/derived/wallet_features/`.

## 5. Decisions (resolved 2026-07-06)
- **Code home = top-level `research/`** (Option B) — research workbench kept separate from the deployable
  `src/babylon/` engine; `markout_study/` folds in under it.
- **`wallet_features` grain = `(wallet, coin, month)`** — atomic unit; roll up to wallet / wallet-coin /
  wallet-month on demand (no separate stored rollup needed).
