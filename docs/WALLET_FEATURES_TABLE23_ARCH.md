# Table 2/3 Tier-1 panel builder — implementation architecture (v2, post 3-agent swarm audit 2026-07-08)

Implements `WALLET_FEATURES_SPEC.md §4-9` Tier-1 (fills-only) over the completed episode lake
(`data/derived/episodes/month=*/episodes.parquet`, 33,794,649 episodes, 40 cols, schema
`episodes_v1_lifecycle_enriched_2026-07-07`) **and** the fills tape (see §4B). **Exploratory lane —
firewalled from Gate-A** (§7). v2 folds in the swarm-audit findings (leakage-F1/F2, rollup-F1..F9, compute-F1..F4).

## 0. What we're building — TWO sources, joined
```
research/data/features.py            # the builder (new; imports episode+fills schema, NOT gate_a/)
data/derived/addr_coin_features/…    # TABLE 2 — one row per (address, coin, as_of_cutoff, window)
data/derived/addr_features/…         # TABLE 3 — one row per (address, as_of_cutoff, window) cross-coin
```
Each Table-2 row is assembled from **two per-cell aggregations joined on (address,coin)**:
- **(A) episode-level** over the episode lake, membership by `close_ts` (§2): PnL, holding, position-building,
  concentration/LOO, persistence.
- **(B) fills-level** over the fills tape, windowed by fill `ts ≤ C` (§4B): raw activity, active-days/weeks/
  months, taker/maker/buy/sell counts, traded volume, `days_since_last_fill`.
  **Why (B) exists (rollup-audit F1/F7):** the episode row exposes only ~5 fill timestamps (open/close/last_fill/
  peak/first_reduce), so `n_active_days` etc. are NOT episode-derivable; and member `last_fill_ts` can both
  understate recency and (for an open episode) exceed C → leak. Fills-level `ts ≤ C` fixes both, and matches P7.

Grounding (lake): 632,089 wallets · 1,254,914 (wallet,coin) pairs · 4 coins (BTC/ETH/SOL/HYPE) · 71,541
OPEN_AT_END · span 2025-08-01 → 2026-06-30. Fills tape: 800,088,474 fills.

## 1. Grain, cutoffs, windows
- **Table 2:** `(address, coin, as_of_cutoff, window_name)`. **Table 3:** `(address, as_of_cutoff, window_name)`.
- **Cutoffs:** `cutoff_ms(M) = first instant of month M+1 (00:00:00.000Z)` (P12). 11 monthly: eom-202508 … eom-202606.
- **Windows:** `{expanding, 90d}`. `window_start = cutoff − window` (expanding ⇒ 0).

## 2. THE leakage-safe membership rule (load-bearing — §1); verified CLEAN by the leakage audit
Episode is a **realized member** of panel `(cutoff C, window W)` iff:
```
close_ts IS NOT NULL  AND  close_ts ≤ C  AND  close_ts > (C − W)
```
- Every field of a closed episode is `≤ close_ts` (P13a — verified: `close_ts` = max ts of the episode, and the
  walk never reads forward), so the single `close_ts ≤ C` filter makes the whole row leak-safe.
- **Open-at-cutoff** (`close_ts IS NULL` OR `close_ts > C`): NOT a realized member; excluded from all realized
  aggregates; counted as `n_open_at_cutoff` via `open_ts ≤ C < (close_ts or +∞)` over **ALL partitions, no prune**
  (a still-open position closes in a FUTURE partition — pruning would miss it). Half-open boundary: `close_ts==C`
  is a member and not open (mutually exclusive, exhaustive — CLEAN).
- ⚠ **Partition-prune is CONSERVATIVE (leakage-F1, empirically confirmed: 20/800M fills have partition-month ≠
  ts-month at boundaries).** Partition = finalize/close month ≈ ts month but NOT provably equal. So the IO-prune
  reads close-months in **`[first, C_month + 1]`** (expanding) / **`[C−W_month − 1, C_month + 1]`** (90d) — one
  month of slack each side — and the exact `close_ts` predicate then governs correctness. NEVER prune to exactly
  `≤ C_month`. (Alternative once proven: add a validate.py assert `month(ts)==partition` and tighten — deferred.)
- **Precondition (leakage-F5):** panels are built ONLY from a full-rebuild lake (or a documented last-month-only
  rebuild) — never a middle-month patch (episode builder's RESUME LIMITATION can mis-stitch `close_ts` otherwise).
  Gate the build on the episode parquet's recorded `episode_schema_version` + `code_commit` (fail if `-dirty`
  mismatch vs a pinned expected value).
- **Pass-2 quarantine (leakage-F2, forward-looking pin):** the whole-history quarantine verdict (P2 "a Sept
  chain-break invalidates Jul/Aug") is NON-walk-forward and MUST NOT gate membership at cutoff C. When Pass-2
  lands, eligibility fed into panel C uses only chain-breaks/dups with `ts ≤ C` (cutoff-relative), never the
  whole-history verdict. For now `n_quarantined = 0` placeholder.

## 3. Additive-components design (§6) — corrected per rollup audit
Store additive base components so Table 3 / window rollups are EXACT; never SUM a ratio/mean/snapshot.
- **Additive (SUM across coins/months):** all `n_*` counts INCLUDING **`n_losses`** (rollup-F5 — do NOT derive as
  `n_closed−n_wins`; break-even episodes exist); `sum_realized_gross`, `sum_fees`, `sum_builder_fees`,
  `sum_realized_net`, `sum_hold_minutes`, `sum_initial_notional`, `sum_added_notional`, `sum_peak_notional`,
  `sum_win_pnl`, `sum_loss_pnl` (both stored → profit_factor exact), `n_wins`, `n_realized` (=CLOSE+FLIP members).
  From the fills pass (§4B): `sum_traded_notional_usd` (true volume, incl exits — rollup-F6; NOT episode
  peak_notional, which is a snapshot), `n_fills`, `n_taker/maker/buy/sell_fills`.
- **Non-additive → recompute from components:** every `_rate`/`_share`/ratio, ratio-of-sums means, `pnl_per_*`,
  `profit_factor`, `payoff_ratio`, `win_rate`, `directional_imbalance`.
- **Non-rollup-able → recompute from the member episode set** (Table 3 re-scans episodes, confirmed feasible):
  medians, percentiles, std, LOO, and **mean-of-ratio** columns like `peak_to_initial_notional_mean`
  (rollup-F9 — `Σ(peakᵢ/initᵢ)/n ≠ Σpeak/Σinit`; compute per-episode then average, never from sums).
- **`n_active_days`/`_iso_weeks`/`_months`:** from the fills pass (§4B), NOT episodes (rollup-F1). Non-additive
  across coins (a day trading BTC+ETH = 1 day) and iso-weeks non-additive across months → Table 3 recomputes
  from distinct calendar units in the fills pass, not by summing Table-2.
- **Snapshot (take LAST/MIN, never sum):** `days_since_last_episode` (from member `close_ts`),
  `days_since_last_fill` (from the §4B fills `max(ts)≤C`); Table 3 = MIN across coins (most recent).

## 4A. Episode-level Tier-1 columns (from the 40-col episode schema)
All realized/PnL carry the **`_price_only` / funding=NULL** label. Pins from the audit:
- **Realized members = CLOSE ∪ FLIP** (`close_ts NOT NULL`). **`episode_win_rate` / `profit_factor` denominator =
  `n_realized` (CLOSE+FLIP), NOT `n_closes`** (rollup-F3 — FLIP episodes realize PnL; using n_closes orphans them).
- **Win rule pinned:** a win = **`realized_net_usd > 0`** (net of fees — the deployable-relevant sign); `==0` is a
  break-even, counted in neither `n_wins` nor `n_losses` (so `n_wins + n_losses + n_breakeven = n_realized`).
- **`n_opens` = count of `inherited_basis=False` episodes; `n_increases` estimand** (rollup-F4): we report
  `n_increase_fills` = Σ `n_adds` + (opens that are true flat→nonzero INCREASEs). Flip-residual opens
  (`inherited_basis=False` but opened by a FLIP fill) are NOT INCREASE-classified → they are excluded from
  `n_increase_fills` by subtracting `n_flips` from the opener count. (Fresh-flat vs flip-residual opens are
  otherwise indistinguishable — documented; add an `open_kind` to the episode schema only if a future need arises.)
- **Concentration on a NON-NEGATIVE base (rollup-F2):** signed-PnL HHI is ill-defined (shares blow up as Σpnl→0).
  Use `episode_grossprofit_hhi` = HHI over `max(realized_net,0)` (winners only), plus `episode_notional_hhi`
  over `peak_notional`. `top_1/5_pnl_share` guarded: NULL unless `Σ max(pnl,0) > 0`.
- **Concentration/fragility:** `pnl_without_best_episode = Σpnl − max(pnl)` (LOO-worst is the identical quantity —
  rollup-F8 — keep ONE; also store `pnl_without_worst_episode = Σpnl − min(pnl)` as the distinct complement).
- Columns (grouped as §4b): position-building (`n_long_episodes`, `long_episode_share`, `directional_imbalance`,
  `n_single_fill_episodes`, `adds_per_episode_{mean,med,p90}`, `build_minutes_{mean,med,p90}`, `flip_rate`,
  initial/peak/added notional `{mean,med,p10,p90}`, `peak_to_initial_notional_mean` [recompute]); holding
  (`hold_minutes_{mean,med,p10,p90}`, `fraction_hold_ge_{1h,4h,8h,24h}`, `n_open_at_cutoff`); realized PnL
  (`realized_gross`, `fees`, `builder_fees`, `net_realized`, `pnl_per_episode`, `episode_pnl_{mean,med}`,
  `win_rate`⚑, `average_win`, `average_loss`, `profit_factor`, `payoff_ratio`, worst/best_episode_pnl);
  mechanical-flow (`n_flagged_opens`, `n_qualifying_opens`, `qualifying_open_share`, `n_liquidation_closes`,
  `n_flagged_fills`, `n_liq_fills`); persistence (expanding only, gate `n_months≥3` else NULL:
  `positive_month_fraction`, `first_half_vs_second_half_pnl`). `funding_*` reserved NULL.

## 4B. Fills-level Tier-1 activity pass (NEW — resolves rollup-F1/F6/F7, leakage-F7; matches P7)
A **separate stateless SQL aggregation over the fills tape**, windowed by fill `ts` (NOT episode membership):
member fills = `ts ≤ C AND ts > (C−W)`, grouped `(wallet, coin)`. Reuses the majors-only tape + the
flagged/liq predicates from `episodes_build._classify_sql` (import the shared predicates, do not duplicate).
Emits: `n_fills, n_taker_fills, n_maker_fills, n_buy_fills, n_sell_fills, n_active_days` (COUNT DISTINCT UTC day),
`n_active_iso_weeks, n_active_months, days_since_last_fill` (= (C − max(ts))/86.4e6), `sum_traded_notional_usd`
(Σ `|sz|·px`), `first_fill_ts, last_fill_ts`. **Definitional note:** activity is windowed by fill-time, so
`n_fills` here (fills in the window) differs from Σ episode `n_fills` (fills in member episodes) — both are kept,
labelled; the fills-level one is the activity/liveness metric, the episode one is the position-building metric.
`n_active_days`/`_iso_weeks` are non-additive across coins → Table 3 recomputes from distinct calendar units here.

## 5. Table 3 cross-coin rollup (§5)
Per (address, cutoff, window), from the SAME per-cell member set across all 4 coins: `wallet_total_coins_traded`,
per-coin `{episode,notional,pnl}_contribution_share`, `wallet_coin_concentration_hhi` **on non-negative base**
(notional or gross-profit — NOT signed pnl, rollup-F2), `wallet_primary_coin` (`arg_max(coin, notional)` with an
explicit coin-name tie-break — compute-F3), `is_coin_specialist` (hhi>τ); SUM of additive components; recomputed
medians/percentiles/HHI/LOO over pooled members; `n_active_days`/`_iso_weeks` from distinct calendar units (§4B);
`days_since_*` = MIN across coins.

## 6. NULL policy & population (§7)
Ratio over zero denominator → **NULL not 0** (win_rate NULL when n_realized=0; profit_factor NULL when Σloss=0;
concentration NULL when non-neg base=0). Carry the N beside every ratio. **Never drop tiny-N rows.** Drop the ≤2
protocol-vault wallets. Flagged fills ARE in PnL/volume, OUT of qualifying-signal denominators — labelled.

## 7. Determinism, firewall, provenance (§7, P11) — corrected per compute audit
- **Firewall:** `research/data/features.py` imports the episode/fills parquet + `schema.py` + the shared
  classify predicates only; MUST NOT import `markout_study/gate_a/*`. Import-graph test asserts it. Tier-1 has
  **no ranking/z/EB columns** (those are §4c shadow-Gate-A = Tier-2), so over-carry surface is minimal.
- **Determinism (compute-F3):** exact `quantile_cont(x,[array])` (deterministic under threads — a pure function of
  the value multiset; do NOT use `approx_quantile`). Every `arg_max` gets an explicit tie-break
  (`wallet_primary_coin`, best/worst-episode); every `list()` gets in-aggregate `ORDER BY` or uses `max(x,k)`.
  Pinned output `ORDER BY (address[,coin], as_of_cutoff, window)` per part (load-bearing under
  `preserve_insertion_order=false`). Tier-1 floats: parallel SUM/AVG is NOT byte-identical run-to-run → ROUND to a
  fixed scale before write and claim **"deterministic to the rounded scale,"** not byte-identical. **Carry-forward
  (P11):** any Tier-2 rank-feeding PnL re-derives from the exact-string tape, NOT these float `realized_*`.
- **Provenance:** file metadata `{feature_schema_version, source=episode_schema_version, code_commit(-dirty)}`;
  `WALLET_FEATURES_SCHEMA_VERSION` constant + bump discipline.

## 8. Compute & memory plan (8 GB box — binding constraint; GO per compute audit with these changes)
- **Engine:** DuckDB. `memory_limit='5GB'`, `threads=2`, `temp_directory='.tmp'`, `preserve_insertion_order=false`.
  **Pre-flight assert ≥ ~20 GB free** on the `.tmp` volume. Cells run **strictly sequential** (never parallelize —
  temp multiplies).
- **CHUNK to bound the holistic-aggregate buffers (compute-F1/F1b — the real OOM risk; `quantile`/`list` buffer
  every per-group value, ~3-5 GB at the full expanding cutoff):**
  - **Table 2 per COIN** (grain is already per-coin — free 4× cut): 4 coins × 22 cells = 88 bounded `GROUP BY
    wallet` queries.
  - **Table 3 per deterministic WALLET-HASH BUCKET** (`sha256(wallet) % 8`, reuse the P11 tie-break hash) — Table 3
    is cross-coin so can't coin-chunk and is the worst cell; 8 buckets × 22 = 176 bounded queries. Buckets union
    losslessly (a wallet's episodes stay in one bucket).
- **Closed forms (keep — avoid holistic cost):** HHI on non-neg base = `Σsᵢ²`, LOO = `Σpnl − max`, top-k =
  `max(pnl,k)`; `stddev` is Welford-streaming (cheap). Only percentiles/medians are genuinely holistic → list-form
  `quantile_cont(x,[0.1,0.5,0.9])` (one buffer serves all its percentiles).
- **Per cell:** hive-prune to the conservative close-month range (§2), apply exact `close_ts`/`ts` predicates,
  aggregate (A) episodes and (B) fills, join on (wallet,coin), write.
- **NO incremental materialization** (compute-F2 — helps only the cheap additive cols, not the holistic peak) and
  **NO single-windowed cumulative query** (compute-F2 — holds all cutoffs' states at once → worse memory).
- **Write:** Hive by `cutoff=YYYYMM/window=…/part.parquet`, each part sorted by `wallet`; atomic tmp+os.replace.
  Emit `data/derived/wallet_features.duckdb` view catalog for drill-down.

## 9. Build order
1. (done) architecture doc → 3-agent swarm audit → **this v2 revision**.
2. Neutral `cutoff/window` + `member_predicate(C,W)` builders; import the shared classify predicates from
   `episodes_build`. Unit-test predicates on hand-built fixtures (cross-month, open-at-cutoff, boundary
   partition-slack, FLIP win-rate, break-even, signed-PnL concentration).
3. Build one cell (one coin × one cutoff × expanding) for Table 2A+2B joined; validate row counts, assert **no
   member has `close_ts > C`**, hand-check a few wallets (incl a flip-heavy and a break-even one).
4. Full 88-cell Table 2 + 176-cell Table 3; determinism (rerun-equality to rounded scale) + firewall import test.
5. Findings-ledger entry. Then Tier-2 (`bars.py` + markout backfill) as a parallel track.

## 10. Resolved open questions
- **active-days derivability:** RESOLVED — from the §4B fills pass, not episodes (rollup-F1).
- **positive_month_fraction in 90d:** gate `n_months ≥ 3` else NULL (§4A).
- **single windowed query:** REJECTED (compute-F2) — per-cell sequential loop, per-coin / per-bucket chunked.
- **signed-PnL HHI:** REPLACED by non-negative-base concentration (rollup-F2).
- **win-rate denominator:** PINNED to CLOSE∪FLIP realized members (rollup-F3); win = `realized_net>0` (§4A).
