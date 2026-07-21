# TAPE CAPDAY + FILTER GRID — majors-tape recreation of the capday top-30 copy strat (v1.1, post-audit)

**Status:** architecture v1.1 — 4-agent swarm audit folded in (stats-rigor S1–S8, correctness C1–C7,
firewall FW1–FW6, data-integrity D1–D7; record at `audit/tape_capday_filter_arch/`). **Lane:** research.
**Folds:** 202511–202606 — **BURNED**; every number is **candidate-ranking / descriptive**, never
confirmatory. Forward paper trader adjudicates (ledger 2026-07-16 "burned folds retired" stands; this is a
*recreation/reconciliation* run against an external repo's claim, stamped as such).

## 1. Question

The user's other repo (incerto = serving layer; claim originated upstream of it) reports that ranking wallets
by **trailing 3-month $100k-capped daily net PnL per active day**, copying the **top-30** the following month,
exiting at a **fixed markout horizon**, is *very successful* **after filters removing traders that drag the
cohort down**. Recreate that family on the **local majors node_fills tape** (`data/raw/fills/`,
BTC/ETH/SOL/HYPE, 202508–202606) under this repo's accounting and inference discipline. Novel leg: selection
features AND entries computed **from the node_fills tape itself** (prior majors runs consumed the Reservoir
lake); dragger filters applied **pre-selection** as a deployable screen (plus a rank-then-screen arm, §3).

## 2. Selection metric — frozen to the incerto-certified definition (`signals_ddl.py capday_stats`)

Per fold month T (8 folds), formation = 3 calendar months strictly before T. Membership is **ts-based**
(`ts < epoch_ms(first day of T)` etc.), partition pruning is an optimization only (FW3: a sub-second
partition boundary spill exists on tape).

- Wallet-day rollup across the 4 majors, **excluding `dir = 'Net Child Vaults'` rows** (C5; matches the
  lake's semantically-zero treatment): `day_pnl = Σ closed_pnl − Σ fee` (USDC; builder_fee EXCLUDED —
  matches incerto `SUM(pnl) − SUM(fee)`; Σ builder_fee among selected wallets reported as a diagnostic C7);
  `day_notional = Σ abs(sz)·px` (C4, lake formula verbatim); active day requires `day_notional > 0`
  (precedent form, D6).
- Day-grain cap by notional scaling: `cap_pnl = day_pnl × LEAST(1, 100000 / day_notional)`.
- metric = `Σ cap_pnl / n_active_days`; eligibility `n_active_days ≥ 15`.
- Rank metric desc, wallet asc tie-break. **Top-30 AFTER the arm's screen** (screen-then-rank = deployable
  construction; a rank-then-screen arm isolates the removal effect, §3/§5).
- Fee-token guard: non-USDC `fee_token` share of Σ|fee| must be ≤0.1% or the build stops (sampled: USDC-only).
- `start_position` flatness test = `TRY_CAST(start_position AS DECIMAL(38,18)) = 0` (D6).

Estimand notes: **majors-native** capday (alt activity invisible on this tape); capday MEAN metric (the
user's words), not the t-stat. Formation PnL includes zhash/liq-origin/vault-**flagged** fills (money is
money) except Net Child Vaults; **entries** exclude flagged opener fills (§4) — both declared with funnel
counts (D5).

## 3. Filter grid — pre-declared, formation-window-only, thresholds frozen from repo precedent (NOT tuned)

| arm | screen (drop wallet if it FAILS) | provenance / frozen details |
|---|---|---|
| F0 | none (baseline capday top-30) | — |
| F1 BOT | fills per active day < 500 | `efron_bot500.py`; fill count excludes Net Child Vaults rows |
| F2 MAKER | formation taker share ≥ 0.10 | **count-weighted**: crossed fills / all fills, denominator excludes Net Child Vaults (C3, frozen here) |
| F3 DUST | median formation flat-open entry notional ≥ $250 | ≥$250 ledger screen at wallet grain; entry definition = §4 |
| F4 LIQ | zero **own** liquidations in formation: no fill with `liq_user IS NOT NULL AND lower(liq_user)=lower(wallet)` | `schema.py LIQ_ORIGIN_SQL` (C1 — the raw liq struct marks BOTH sides; counterparty-side liq fills counted separately as a diagnostic) |
| F5 1DAY | max-day |cap_pnl| ≤ 50% of Σ|cap_pnl|; **Σ|cap_pnl| = 0 → PASS** (FW5) | one-day-wonder axis |
| FALL | conjunction F1∧F2∧F3∧F4∧F5 | the "after filters" strat under test |
| FRTS | rank-then-screen: F0 top-30 minus FALL-screened wallets (cohort ≤ 30, no backfill) | S3 — isolates removal from backfill |

8 arms × horizons {1h, 4h, 8h, 24h} = 32 cells, all declared before any result. **PRIMARY CELL = FALL @ 8h.**
8h is the **repo-standard majors horizon, itself selected on these same burned folds** (S4) — an 8h result is
same-fold-family corroboration, never independent confirmation. Multiplicity (S5): primary family =
FALL−F0 at the 4 horizons with BH within family (8h quoted uncorrected but labeled); the report must print
the whole-grid tally ("k of 32 cells clear 0; expected under global null ≈ m") beside any CI-clearing cell.

## 4. Book construction

- **Entry definition (C2/D2, frozen):** an entry is an **order** (`wallet, coin, oid`) whose **min-ts fill**
  has flat `start_position` (decimal-exact 0), `crossed = TRUE`, `dir IN ('Open Long','Open Short')`, and is
  not zhash/liq-origin/vault-flagged. Entry ts = that first fill's ts; dir_sign from its dir; notional =
  Σ abs(sz)·px over **all same-dir fills of that oid** (maker tail slices of a taker-opened order included —
  the order's true size; mixed-dir oids contribute only their first-dir fills; both mixed cases counted in
  the funnel). `oid IS NULL` fills: keyed by `(block_number, event_index)` as single-fill entries, counted
  in the funnel (expected ≈0; build emits the diagnostic rather than assuming). Entry notional ≥ $250.
- **Markout:** dir-signed gross bp vs asset_ctx `mid_px`: **latest ctx bar ≤ ts** and **latest ctx bar
  ≤ ts+h** (backward ASOF both ends, FW6), staleness ≤ 90s at both ends, else NULL → excluded + funnel.
  Ctx per fold = fold month + first 3 days of next month (`_ctx_parts` shape ONLY — **entries must come
  from `data/raw/fills`; importing `.lake` in this module is forbidden and asserted** FW1).
  Known coverage limits (D1/FW2): ctx ends **2026-06-29** (June 30 fully censored → fold 202606
  right-censored; 202607 ctx dirs are empty) and ctx day 2026-05-30 is partial (418/1440 min) — both
  expected in the missingness table, and the build asserts per-fold ctx part counts against expectation,
  reporting coverage in the funnel.
- **Economics view (secondary):** equal-$1k per entry, net = gross − 2.6bp RT (+5.5bp stress line); daily
  PnL at exit; ann. Sharpe descriptive; CI on mean net bp = the **wider** of day-block and wallet-cluster
  bootstrap (S8).

## 5. Inference — audited robust cell spec + corrected contrast design

- **Per cell:** `majors_native._cell_inference` spec — winsor at p95 |mk| within cell, wallet-fold units ≥3
  evaluable entries, wallet-fold-equal mean, multiplicity-preserving weighted wallet-cluster bootstrap
  (N=4000, `(m@s)/(m@c)`), per-fold means + sign count, seed `default_rng(20260720 + 1000*arm_idx +
  horizon_idx)` (arm_idx 0..7, horizon_idx 0..3 — collision-free).
- **Filter contrast (the claim under test), S1/S2:** for FALL−F0 (and FRTS−F0) at each horizon:
  (a) **common winsor limit** = p95 |mk| of the UNION entry pool per horizon, applied to both arms before
  differencing; unwinsorized delta reported as a sensitivity line; (b) primary interval = **paired t on the
  8 fold-deltas with 7 df**, reported alongside a **wallet-cluster paired bootstrap** (resample wallets from
  the union roster; recompute both arms' wf-equal means honoring each wallet's arm membership); quote the
  **wider**. Exact-binomial sign-test convention stated (8/8 → two-sided p = 0.008 max attainable).
  Delta decomposition (S3): FALL−F0 = removal term (via FRTS−F0) + backfill term (FALL−FRTS), each printed.
- **Power honesty (S6):** cells report boot-se and MDE ≈ 2.8×se; the paired delta reports its OWN se and
  MDE with the 7-df factor ≈ 3.26 (t.975,7 + t.80,7). Care-about = +5bp. Expected MDE ≫ 5bp → verdict
  vocabulary limited a priori to {underpowered positive / underpowered negative / adverse-direction /
  unresolved}; **no NULL, no CONFIRMED** on burned folds. Over-null and over-carry gates apply symmetrically.
- **Dragger diagnostic (S7):** screened-out wallets' forward markout is a **funnel diagnostic only** — no
  CI, no verdict vocabulary, never quoted as validation of a screen.
- **Frozen-133 (FW4):** NOT excluded (fresh recreation); per-fold |top-30 ∩ frozen-133| reported for F0 and
  FALL + each primary cell mean recomputed excluding overlap wallets (sensitivity line, not an arm).

## 6. Leakage / firewall guards

- Formation reads ONLY fills with ts strictly before T (ts-based asserts, FW3). Filters use ONLY
  formation-window fills. Markout endpoints backward-ASOF only.
- No Postgres, no S3/lake reads: incerto supplies *definitions*; all data = local tape + asset_ctx.
  Research lane only.

## 7. Determinism / provenance / caches / access discipline

- All fills reads via `schema.DATASET_GLOBS` / `db.connect()` views or leaf globs with
  **`union_by_name=true`** (D3 — liq columns are all-NULL INT32 in zero-liq hours); integer partition
  predicates (`month = 202511`) (D7).
- Fixed seeds; deterministic ordering everywhere.
- **Cache sha (D4)** over {all arm thresholds, horizons, CAP/ND_MIN/NOTL_MIN/entry rules, fills
  `SCHEMA_VERSION`, per-fold ctx part counts, seed, inference constants}; the sha is in the cache
  **filename**; the report asserts stored-sha == recomputed-sha. Caches under
  `data/derived/copy_cohort/tape_capday_filter/`.
- Report stamps `code_commit`, full config, per-fold funnels (pool → eligible → screened → top-30 →
  entries → evaluable, incl. flagged/NULL-oid/mixed-oid/ctx-censored counts).

## 8. Outputs & verdict template

Report `data/derived/copy_cohort/tape_capday_filter_report.json`: config, per-fold rosters + funnels,
32 cells, FALL−F0 and FRTS−F0 deltas (common-winsor + unwinsorized, both CI families), decomposition,
dragger funnel diagnostics, frozen-133 overlap + sensitivity, equal-$ book (F0@8h, FALL@8h), missingness.
Ledger entry: symmetric verdict; the recreation question answered as "on this tape, with these frozen
screens, descriptive performance X [CI] vs baseline Y — direction label per §5 vocabulary; deployment
adjudication remains with the forward paper trader."
