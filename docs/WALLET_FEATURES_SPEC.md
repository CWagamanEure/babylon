# WALLET / TRADER FEATURE SYSTEM — v2 spec

> ## RESOLVED PINS (v2.1 — post 3-agent re-audit, 2026-07-06). These OVERRIDE the body where they conflict.
>
> **Honest framing (read first).** A **Tier-1-only table measures "active / realized-profitable-on-price
> (gross of funding, beta-UNadjusted) / trading-style" — NOT "informed."** Realized PnL & win-rate are
> confounded by market beta, funding (NULL here), and disposition selection. Informedness needs
> market-adjusted markout = Tier-2 (blocked on hl_hist). So Tier-1 ships as a **profile / prefilter** (narrow
> the universe + build the episode foundation markout backfills into), explicitly labelled — a useful prior,
> not a verdict.
>
> **P1 — Episode grain = full LIFECYCLE, a NEW builder (not "extend episodes.py").** The frozen
> `gate_a/episodes.py` terminates at the first qualifying reduce (it only times markout entries). Our episode
> is open → adds → reduce**s** → CLOSE/FLIP. **Only CLOSE or FLIP terminate; reduces are intra-episode.**
> Import the exact-decimal *ledger math* from a neutral module, NOT the reduce-terminates boundary.
> **P2 — Two-pass build (resolves whole-stream quarantine + 8h dedup vs streaming).** Pass 1 = resumable
> streaming walk emits *raw* episodes + carry-seed. Pass 2 = whole-history, over the (small) episode table:
> 8h earliest-wins dedup (direction-aware) + quarantine verdict (a Sept chain-break invalidates Jul/Aug).
> Dedup/quarantine do NOT live in the streaming walk.
> **P3 — Carry-seed (per (wallet,coin), month-end) full field list.** `{end_qty (EXACT int ticks),
> running_vwap_cost, clast (last-increase ts — without it the 30-min GAP_MS test can't fire across a
> boundary), open_ts, opener_src_key, dir, n_fills/n_adds/n_reductions so far, initial_notional,
> total_added_notional, realized_pnl_so_far, fees_so_far, currently_underwater, basis_known, seed_schema_version}`.
> Persist atomically (tmp+os.replace + manifest shard, like ingest); a seed-affecting schema bump forces full
> replay, a seed-neutral bump resumes from month K.
> **P4 — Canonical fill order = `(wallet, coin, src_object, block_number, event_index)`** (+ tid final
> tiebreak). `event_index` resets per source object, so it is NOT globally unique without `src_object`. Assert
> block↔object 1:1. Pin this ONE order in all docs (episodes.py "ts" and EPISODE_SPEC "time" are stale here).
> **P5 — Tier reassignment (MTM-path columns need a price series = Tier-2, NOT fills-only).** Move to Tier-2
> (reserve NULL in the Tier-1 episode table, backfill with markout): `max_adverse_excursion_usd`,
> `adds_while_underwater`, `end_mark`, `unrealized_pnl`. **`peak_notional` STAYS Tier-1 but is pinned to
> EXECUTION price** (`max |qty|·running_VWAP`), not mark-to-market. `avg_cost_basis` stays (ledger VWAP).
> **P6 — VWAP transitions + closedPnl validator (write the equations).** REDUCE: basis unchanged. CLOSE:
> reset. FLIP: residual-leg basis = flip fill px. add-while-same-side: re-average at fill px. **Cross-check /
> recover:** `closedPnl ≟ reduce_qty·(fill_px − basis)·dir` — validate every reduce; invert on the first
> reduce of a carried-in position to RECOVER the inherited basis (`basis_known` false→true).
> **P7 — Split §4b: stateless-SQL vs walk-derived.** SQL-computable per-fill (cheap parallel): `n_fills,
> n_buy/sell, n_taker/maker, per-fill transition class (uses per-row start_position), all flag counts`.
> Walk-derived (need gap/dedup/qualifying-floor state): every `n_*episode*` count, `n_qualifying_*`,
> `n_reductions` (qualifying only). Never compute episode counts by SQL group-by.
> **P8 — Rollup §6 has TWO axes.** cross-MONTH (within a window) vs cross-COIN (Table 3). `n_active_days /
> _iso_weeks / _months` are additive across months but **NOT across coins** (a wallet active in BTC+ETH on one
> day = 1 active day, not 2) → recompute from distinct calendar units for Table 3. Add `entropy / burstiness /
> *_cv` to the "recompute, never merge" list. `days_since_*` across coins = MIN (most recent).
> **P9 — Firewall MECHANIZED (not prose).** (a) `connect_frozen()` in a SEPARATE module that does NOT import
> `schema.DATASET_GLOBS`/`DATA_DIR` — views from an explicit synthetic allow-list only. (b) Import-graph test:
> assert no `gate_a/` module imports `research.data.db` or the real glob constants. (c) Config-hash gate:
> `frozen_config.sha256` sidecar; materialize/observe refuses unless a committed hash exists, matches, and the
> `gate_a/` tree is clean. (d) Dedupe SZD + flag predicates (today duplicated in schema.py & common.py) into
> the neutral module + a cross-lane equality test.
> **P10 — §4c is a SHADOW Gate-A (over-carry guard, pin now even though Tier-2).** Prefix its ranking columns
> `shadow__`; add a physical `leakage_controls_applied=false` column; put the z/EB/percentile block in a
> separate namespace (`addr_coin_shadow_ranking`) that can't be silently joined into an "informed list."
> Reading wallets off it is NOT the frozen verdict.
> **P11 — Determinism for ranking-feeding columns.** Exact-DECIMAL numerator/denominator; then `threads=1` +
> `ORDER BY` pin-key for the float mean/z/EB reduce; ROUND before sorting; tie-break `sha256(addr)` (reuse
> module-9 rule). Own exploratory bootstrap seed constant (NOT the frozen GLOBAL_SEED). `built_at` excluded
> from the reproducibility hash (sidecar).
> **P12 — Cutoff & leakage pins.** `cutoff_ms` = first instant of the next month `00:00:00.000Z` (pin once;
> feeds `boot_seed`); membership half-open `close_ts ≤ cutoff` (incl) `AND > cutoff−window` (excl). **Tier-2
> markout:** per-horizon right-censor — episode contributes horizon h iff `entry_bar_ts + h ≤ cutoff` (this is
> why per-horizon `n_episodes` differ); `entry_bar_ts` = first lattice bar **STRICTLY after** open (frozen
> rule, not "≥"); z/EB cross-section = wallets scoreable AT that (cutoff,window,coin) on ≤cutoff data, τ²
> re-estimated per cross-section, percentile on the SHRUNK posterior, min-evidence `n_wallet_days ≥ J` per
> horizon; open-position mark = last bar `≤ cutoff` (deferred to Tier-2, never faked from fills).
> **P13 — Invariants to state.** (a) For CLOSED members, `close_ts ≤ cutoff` ⟹ the whole open→close life is
> ≤ cutoff ⟹ all realized/path/close fields are leak-safe (the elegant core). (b) No survivorship leak —
> panels rebuilt per-cutoff by filtering `close_ts ≤ C`. (c) A month part is finalized only after all episodes
> with `open_ts ≤ M` have closed or hit tape-end (long-lived opens carried in the seed). (d) Label every PnL
> metric's denominator: **deduped-episodes** vs **all-fills** (wallet ΣclosedPnl ≠ Σ deduped-episode PnL).
> **P14 — Column deltas.** ADD (fills-only, high value): `realized_pnl_sharpe_daily` (to CORE — skill-relevant,
> scale-robust), `taker_open_share` vs `taker_close_share` (entry/exit aggression asymmetry), `n_same_tid_both_sides`
> (integrity-anomaly DQ, IMPLEMENTATION R3), `n_distinct_builders`/`builder_share`. MERGE: the `*_cv` clumpiness
> metrics into `burstiness_index`; `n_flagged/unflagged_increases` into `qualifying_open_share`. CORE fixes:
> `n_active_weeks`→`n_active_iso_weeks`; `episode_win_rate` carries its disposition-selection flag; coin-concentration
> HHI is Table-3-only.
>
> **P15 — StableEdge is the robust PRIMARY markout estimator (median-of-means over weekly blocks).** The
> headline per-horizon edge is `stable_edge_h = median_week( mean_{wallet-coin-day}( M_{d,h} ) )` (+ a 20%
> trimmed-mean variant), NOT the ordinary mean (heavy tails ⇒ one trade/day/week dominates). Store the
> persistence+concentration+floor quartet (`positive_week_fraction`, `markout_without_best_week`,
> `worst_leave_one_week_out_mean`, `weekly_bootstrap_lower_bound`) — the combination is the tell. **Power
> gate:** `n_active_weeks < 6` ⇒ INCONCLUSIVE, never "no edge" (over-null discipline). Full detail in §4c.



**Status: DESIGN (2026-07-06), post 5-agent swarm audit + ChatGPT-schema review. Build after one focused
re-audit of THIS doc.** Supersedes the flat `(wallet,coin,month)` sketch in `DATA_ARCHITECTURE.md §3`.
Goal: a leakage-safe, walk-forward-capable set of tables to characterize traders (informed or not) and
query them fast with DuckDB. **This is the EXPLORATORY lane — it must NEVER feed the frozen Gate-A pipeline**
(same wall as `DATA_ARCHITECTURE §2` / `IMPLEMENTATION_ARCHITECTURE` firewall rules).

## 0. The three tables (episode base + two derived panels)
```
data/derived/
  episodes/month=YYYYMM/…parquet        # TABLE 1 — atomic, durable. One row per dedup episode.
  addr_coin_features/…parquet           # TABLE 2 — one row per (address, coin, cutoff, window). Derived.
  addr_features/…parquet                # TABLE 3 — one row per (address, cutoff, window). Cross-coin rollup.
```
- **Table 1 (episodes) is the foundation** and is computed ONCE from the fills tape. It carries every
  time-stamped, episode-level fact. Because each episode has `open_ts`/`close_ts`, **any `(cutoff, window)`
  panel is a pure aggregation over episodes** — we are never locked into a cutoff schedule, and a summary
  parquet can't anticipate every future question but the episode table can answer them.
- **Tables 2 & 3 are derivations** over the episode table for a chosen set of cutoffs × windows.

## 1. Grain & the leakage-safe panel definition
- Episode grain: **one dedup episode** (position-building lifecycle: first qualifying INCREASE → adds →
  reduces → CLOSE or FLIP-terminate), keyed by `(wallet, coin, open_ts)` with the source-row key of its
  opener for provenance.
- Panel grain: **`(address, coin, as_of_cutoff, lookback_window)`.** An episode is included in a panel iff
  **`close_ts ≤ as_of_cutoff` AND `close_ts > (as_of_cutoff − lookback_window)`** (an episode is dated by
  when it COMPLETES — the user's close-attribution instinct, generalized). Open-at-cutoff episodes are
  excluded from realized/markout aggregates and counted separately (`n_open_at_cutoff`).
- **Leakage rule (load-bearing):** every value in a `(cutoff, window)` row is computed using ONLY episodes
  and prices with timestamp `≤ as_of_cutoff`. No future data. This is what makes the table walk-forward-safe
  and is the discipline the prior markout study lacked. Cutoff-specific fields (z-scores, EB posteriors,
  cross-section percentiles) are computed within the cutoff's cross-section only.
- Default materialized panels: **monthly cutoffs (each month-end UTC) × windows {expanding, 90d}.**
  Regenerable to weekly / {30d,…} from the episode table without re-walking fills.

## 2. Build architecture (from the swarm audit — this is not optional)
- **Two-speed, per-month, resumable** (mirrors `ingest.py`'s manifest/checkpoint):
  - *Path-dependent leg is SEQUENTIAL per `(wallet,coin)` across months.* The ledger (position qty, running
    VWAP cost basis, open-episode state, MAE) is stateful; a per-month-independent walk would fragment every
    cross-month episode and lose cost basis. At each month-end, **checkpoint a per-`(wallet,coin)` carry-seed**
    `{end_qty, running_vwap_cost, open_episode_state, peak_notional}` and seed the next month. Memory is
    O(wallets-with-open-positions), not O(fills).
  - *Streaming, not dict-of-lists.* Drive the walk from a DuckDB `ORDER BY wallet, coin, block_number,
    event_index` cursor (out-of-core, spills to disk), emitting one episode row as the key advances. Holding
    ~1.3B fills as Python objects OOMs (the known polars/tuple-key pitfall) — forbidden.
  - *Order key is `(block_number, event_index)`* — the canonical archive emission order. `ts` alone is NOT a
    total order (ties across blocks; `event_index` resets per source object). Pin this everywhere.
- **Episodes computed once → feature panels aggregate from episodes** (tens of millions of rows), never
  re-walk the 1.3B fills. This is why Table 1 is the key intermediate.
- **Manifest + carry-seed checkpoints** persisted so a `schema_version` bump resumes from month K, not January.

## 3. TABLE 1 — `episodes` (the contract; extend `episodes.py` to emit this)
The current `gate_a/episodes.py` emits only `(open_ts, dir)` and carries no cost basis — this is a **new
builder** (import-only reuse of the frozen ledger math; see §7 firewall). One row per dedup episode:

| Group | Columns |
|---|---|
| Identity | wallet, coin, open_ts, close_ts (null if open at tape end), dir (long/short), opener_src_key |
| Fills | n_fills, n_adds (increases after open), n_reductions, close_kind (CLOSE / FLIP / OPEN_AT_END) |
| Notional | initial_notional_usd, peak_notional_usd, total_added_notional_usd |
| Timing | build_minutes (open→peak), hold_minutes (open→close), entry_bar_ts (first 5-min bar ≥ open, for markout) |
| PnL (price) | realized_pnl_usd (Σ closedPnl of the episode's reducing fills — **authoritative, no basis reconstruction needed**), fees_usd (Σ fee + Σ builder_fee), realized_net_usd |
| Risk path | max_adverse_excursion_usd, adds_while_underwater (count) — **approximate for episodes carried in at tape start (unknown entry basis); flagged `basis_known=false`** |
| Flags | opener_flagged (zhash-TWAP / liq-origin / vault), is_liquidation_close, crossed_open (bool: taker open) |
| Eligibility | quarantined, quarantine_reason (chain-break / dup / missing-startpos), inherited_basis (bool) |
| Provenance | source_schema_version, feature_code_commit (+`-dirty` flag) |

Markout endpoints are **not** stored here (Tier-2, needs independent price); `entry_bar_ts` is reserved so
markout backfills without a re-walk.

## 4. TABLE 2 — `addr_coin_features` (address, coin, cutoff, window)
Aggregations over episodes in the panel. **Tiered by data dependency** — build Tier 1 now.

### 4a. Identity / lineage / eligibility (always)
address, coin, as_of_cutoff, window_name, window_start, window_end, first_fill_ts, last_fill_ts,
first_eligible_episode_ts, last_eligible_episode_ts, feature_schema_version, source_schema_version,
code_commit. **Eligibility, stored per-test so exclusions are explainable:** eligible, scoreable,
quarantined, quarantine_reason, and each gate as its own bool (passes_min_episodes, passes_min_active_days,
passes_min_active_months, passes_active_weeks, passes_liveness, passes_ledger). Data-quality counts:
n_missing_required_fields, n_chain_breaks, n_duplicate_events, start_position_coverage.

### 4b. TIER 1 — fills-only (BUILD NOW)
- **Activity:** n_fills, n_buy_fills, n_sell_fills, n_taker_fills, n_maker_fills, n_increases, n_reductions,
  n_closes, n_flips, n_raw_episodes, n_dedup_episodes, n_suppressed_overlapping_episodes, n_active_days,
  n_active_iso_weeks, n_active_months, days_since_last_fill, days_since_last_episode.
- **Rates (non-additive — recompute on rollup):** fills_per_active_day_{mean,median}, episodes_per_active_day_*,
  episode_frequency_per_calendar_day.
- **Mechanical-flow accounting (accounting, NOT auto-"bad"):** n_twap_fills, twap_fill_share,
  n_forced_liquidation_fills, n_liquidation_counterparty_fills, n_protocol_vault_fills, n_flagged_increases,
  n_unflagged_increases, n_qualifying_signal_opens, qualifying_open_share.
- **Temporal pattern:** {mean,median,p10,p90}_interepisode_minutes, episode_count_{day,week,month}_cv,
  max_{day,week,month}_episode_share, active_day_fraction, weekend/overnight_episode_share,
  hour_of_day_entropy, day_of_week_entropy, burstiness_index.
- **Position-building:** n_long_episodes, long_episode_share, directional_imbalance, n_single_fill_episodes,
  adds_per_episode_{mean,median,p90}, episode_build_minutes_{mean,median,p90}, flip_rate,
  partial_reduction_rate, close_rate; initial/peak/added notional {mean,median,p10,p90},
  notional_per_active_day_*, total_traded_notional, peak_to_initial_notional_mean,
  fraction_episodes_scaled_in, fraction_episodes_flipped.
- **Holding:** n_completed_positions, n_open_at_cutoff, hold_minutes_{mean,median,p10,p90},
  fraction_hold_ge_{1h,4h,8h,24h}, time_in_position_fraction.
- **Realized PnL (price-only, NO funding — label everywhere):** realized_gross_pnl, closed_pnl, fees_paid,
  builder_fees_paid, net_realized_pnl, pnl_per_active_day, pnl_per_episode, pnl_per_dollar_volume;
  episode_pnl_{mean,median}, episode_win_rate (over CLOSED episodes — flag disposition selection),
  average_win, average_loss, profit_factor, payoff_ratio; max_pnl_drawdown, worst/best_{day,week}_pnl.
  **`funding_*` columns reserved as NULL placeholders** (need hl_hist) so a downstream join can't mistake
  absence for zero.
- **PnL concentration / fragility (winner's-curse guard):** top_{1,5}_episode_pnl_share,
  top_{day,week,month}_pnl_share, {episode,day,week,month}_pnl_hhi, loo_worst_{episode,day,week,month}_pnl,
  pnl_without_best_{episode,day,week,month}.
- **Persistence of ACTIVITY/PnL (cross-month):** monthly_pnl_{mean,std,min,max}, positive_month_fraction,
  consecutive_positive_months_max, first_half_vs_second_half_pnl, recent_30d/90d vs expanding.

### 4c. TIER 2 — markout (asset_ctx re-ingested 2026-07-07; → bars.py → backfill)
> **Markout inputs pinned by the 2026-07-07 data-integrity swarm** (price panel = `data/raw/asset_ctx`,
> [[babylon-hl-hist]]): **price = `oracle_px` (or `mark_px`; or `mid_px` filtered > 0)** — `mid_px == 0` is
> HL's no-book sentinel on ~17% of ALT rows (never majors) and would poison returns. **Join = AS-OF** (latest
> `ctx.ts ≤ fill.ts` per coin), NOT a floored-equi-join — ~0.01% of ctx rows carry sub-minute source seconds.
> **Right-censor** any horizon whose endpoint passes the last ctx minute (P12); ctx covers 2025-08-01 ..
> 2026-06-29 (June-30 fills = 2.04M await the lagged archive; re-pull auto-fills). Known partial ctx day:
> 2026-05-30 (7h only). asset_ctx majors verified pristine (0 bad px, 0 inverted spreads, <0.03% vs fills VWAP).

For each horizon `h ∈ {5m,15m,30m,1h,2h,4h,8h,16h,24h,48h}` (primary study uses {1,2,4,8}h), stored with the
naming convention **`metric__aggregation__horizon__window`**. Per horizon:
- Evidence: n_episodes, n_wallet_days, n_weeks.
- Central: mean_bp, median_bp, trimmed_mean_bp, winsor_mean_bp (weightings stored **separately**:
  `__episode`, **`__wallet_day` (PRIMARY for informedness — de-correlates overlapping windows)**, `__notional`).
- Dispersion/shape: std, mad, iqr, p05..p95, hit_rate, downside_mean, expected_shortfall_10, best, worst.
- **StableEdge — the robust PRIMARY edge (median-of-means over weekly blocks; 2026-07 design, P15).**
  Markout is heavy-tailed, so the ordinary mean is dominated by a single trade/day/week. Build the point
  estimate hierarchically to blunt all three: (1) mean over episodes within each wallet-coin-**day**;
  (2) mean of those within each calendar **week**; (3) **`stable_edge_h = median_week(weekly_mean)`** — a
  median-of-means estimator, robust under heavy tails and respectful of temporal dependence (weekly blocks).
  Also store `stable_edge_trim20_h` (20% trimmed mean of the weekly means — retains more magnitude than the
  median). These are the HEADLINE `metric__aggregation__horizon__window` fields; naive `mean_bp` is kept
  only as the FOIL — ordinary-mean ≫ stable_edge ⇒ a lucky block, not an edge.
- **Persistence + concentration + floor (store ALL — the *combination* is the tell, no field alone):**
  `positive_week_fraction`, `positive_month_fraction`; `markout_without_best_week`,
  `top_week_contribution_share`, `worst_leave_one_week_out_mean` (concentration / leave-one-week-out);
  `weekly_markout_iqr`, `weekly_bootstrap_lower_bound` (block bootstrap over weeks → 5–10th-pct floor).
  A wallet is convincing iff ALL of: stable_edge > 0, most weeks positive, edge-without-best-week > 0, and
  the weekly-bootstrap lower bound near/above 0. (Worked contrast: ordinary +12bp but median-weekly +2,
  ex-best-week −1, 52% weeks → lucky period; vs +5 / +4 / +4 / 72% → persistent.)
- ⛔ **POWER GATE (over-null discipline, CLAUDE.md).** Median-of-means is robust ONLY with enough blocks.
  Store `n_active_weeks` beside every stable field; a panel with `n_active_weeks < 6` is **underpowered →
  labelled INCONCLUSIVE, never "no edge"** (its CI cannot exclude the effect we care about). The robust
  estimator must not manufacture false negatives on thin wallets — always surface point-estimate + n_weeks.
- **Uncertainty (weekly cluster bootstrap, NOT fill-level t-stat — fills are correlated):**
  weekly_bootstrap_se, ci_lower, ci_upper, mean_over_se.
- **Market-relative (the actual skill tell):** market_adjusted_markout, coin_beta_adjusted_markout,
  gross_vs_adjusted_difference — computed against hl_hist coin returns; **raw markout alone is a beta sort.**
- Curve shape (information vs impact): markout_curve_auc_1h_8h, slope, monotonicity, sign_consistency,
  peak_horizon, 8h_minus_1h, decay_8h_over_4h, reversal_indicator.
- Decompositions: buy vs sell (buy/sell_markout, hit_rates, asymmetry); maker vs taker (the single most
  discriminating "informed" tell — aggressive vs passive information); size-conditioned (within-wallet
  notional quantiles: small/medium/large markout, markout_size_spearman, large_minus_small).
- Shrinkage/ranking (cutoff-specific, ≤cutoff only): z_{1,2,4,8}, band_score_pre_shrink, sampling_se,
  eb_tau2, eb_lambda, eb_posterior_mean, posterior_probability_above_mean, cross_section_percentile/decile.
  ⚠️ These are Gate-A's OWN quantities — see §7; exploratory only, NOT the frozen verdict.
- Regime/entry-state conditioning (needs hl_hist context): high/low_vol_markout, up/down/range_markout,
  pos/neg_funding_markout, contrarian/momentum_entry_share, entry_return_15m/1h_mean.

### 4d. TIER 3 — cost / deployability (BLOCKED on L2 book archive; Gate-B namespace)
average_spread_at_entry, average_depth_at_entry, average_slippage_for_target_size, estimated_capacity,
post_latency_markout, fee_adjusted_markout, full_cost_adjusted_markout. **Keep gross vs deployable in
separate namespaces** — never conflate.

## 5. TABLE 3 — `addr_features` (address, cutoff, window) — cross-coin rollup
Wallet-level context that a per-coin row can't hold: wallet_total_coins_traded, wallet_total_major_episodes,
coin_episode/notional/pnl/markout_contribution_share (per coin), wallet_coin_concentration_hhi,
wallet_primary_coin, is_coin_specialist, plus wallet-level rollups of the additive components below.

## 6. Rollup semantics (the "roll up freely" claim is FALSE — this is the fix)
Store **additive base components** so weighted-mean/ratio rollups are exact; never SUM a ratio or a snapshot:
- Additive (SUM across coins/months): all counts, sum_hold_minutes, sum_wins, sum_realized_net,
  sum_volume_usd, sum_notional, and per-horizon `markout_sum`, `markout_sumsq`, `n_ep`, `n_wallet_days`.
- Non-additive → **recompute from components**: all `_share`/`_rate`/ratios, means, `pnl_per_*`.
- Non-rollup-able → recompute from episodes: medians, percentiles, std, Sharpe, bootstrap SE, HHI, LOO.
- Snapshot (take LAST, never sum): end_position, avg_cost_basis, end_mark, unrealized_pnl, days_since_*.
- `n_active_iso_weeks` is NOT summable across months (boundary weeks double-count) — recompute from distinct
  weeks over the span. `n_active_days` IS summable (a UTC day can't straddle a month).
Ship a **rollup view / recipe**, not "SELECT SUM(*)".

## 7. Firewall, determinism, provenance (mechanized, from the audit)
- **Separate frozen connection.** The frozen Gate-A lane must NOT call the shared `db.py::connect()` (which
  registers `wallet_features`/real fills into one catalog). Add `connect_frozen(inputs_dir)` that can only see
  synthetic/nullized inputs; add a test asserting the derived tables are absent from any frozen catalog.
- **Import-only on frozen modules.** `features.py` / the episode builder may IMPORT but MUST NOT modify
  anything under `gate_a/`. Better: move the shared ledger/markout/SZD/flag math to a **neutral**
  `research/data/` module both lanes import (single source of truth — today SZD & flags are DUPLICATED in
  `schema.py` and `common.py`; dedupe + cross-check test).
- **Reverse-leakage guard (over-carry).** These tables compute real per-wallet markout, EB posteriors,
  `selected_flag`, cross-section ranks — Gate-A's own machinery. Reading "informed wallets" off this table is
  **exploratory, NOT the frozen leakage-controlled verdict.** The Gate-A frozen config (seed, horizons,
  thresholds) must be git-committed + hash-recorded BEFORE any real markout output is materialized/viewed;
  post-hoc config edits after observing real rankings = firewall breach.
- **Determinism.** Aggregations that feed a ranking accumulate in `Decimal` or single-thread + ordered
  reduce (DuckDB `AVG` is float + non-deterministic parallel order). `SUM(notional)` cast to a scale that
  can't overflow `DECIMAL(38)`. Order key `(block_number, event_index)`. `built_at` excluded from the
  reproducibility hash (sidecar). `WALLET_FEATURES_SCHEMA_VERSION` constant + bump discipline; `code_commit`
  carries a `-dirty` flag under an uncommitted tree.
- **NULL policy.** Ratios over a zero denominator → NULL, not 0 (win_rate NULL when n_closed=0, etc.).
  Carry the N alongside every ratio/mean so low-N is visible. Never drop tiny-N rows (biases the population).
- **Population membership.** Drop the ≤2 protocol vault wallets (wallet-level, not per-fill). Quarantined
  streams still get a row (additive cols populated, episode cols NULL, `quarantine_reason` set), quarantined
  for ALL months. Flagged fills are IN PnL/volume (ledger-updating) but OUT of episode-signal denominators —
  labelled, never silently unioned.

## 8. Query story
Hive-parquet + DuckDB views (`db.py`), **each month's parts sorted by `wallet`** so row-group min/max prunes
wallet lookups. Also emit a single materialized `data/derived/wallet_features.duckdb` as the default
interactive surface for wallet drill-down, plus the `addr_features` rollup so "career stats" don't rescan the
monthly grain. Naming convention `metric__aggregation__horizon__window` throughout.

## 9. Compact CORE subset (build/validate first, then widen)
n_dedup_episodes, n_active_days, n_active_weeks, n_active_months; net_realized_pnl, pnl_per_active_day,
episode_win_rate, profit_factor; top_month_pnl_share, pnl_without_best_month; positive_month_fraction;
directional_imbalance, taker_fill_share; days_since_last_episode; concentration HHI. **(Tier-2 core, after
hl_hist:** markout_mean_bp__wallet_day__{1,2,4,8}h__expanding, markout_median, weekly_bootstrap_se,
eb_posterior_mean, positive_week_fraction, buy_sell_asymmetry, large_minus_small, recent_90d vs expanding.)

## 10. Build order
1. Re-audit THIS spec (focused). 2. Neutral shared ledger module + extend to emit the §3 episode contract.
3. Build `episodes.parquet` (Tier-1) on 2025-08 as it lands; validate. 4. Build `addr_coin_features` +
`addr_features` Tier-1 panels (monthly × {expanding,90d}). 5. (Parallel) user re-ingests hl_hist → `bars.py`
→ backfill Tier-2 markout into episodes + features. 6. Firewall/determinism tests. 7. Findings ledger.
