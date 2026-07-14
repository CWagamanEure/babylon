# 01 — Dataset Universe & Top-Line EDA

Scope: the raw data universe behind the markout study, the full-tape entry table, and the
Stage-K frozen cohort (the isolated mid-freq copyable-taker cohort that later stages test).
All numbers below are either lifted verbatim from the findings ledger / scripts, or computed
with a light polars aggregation (`POLARS_MAX_THREADS=2`) directly on the already-built,
cohort-sized artifacts (`out/cohort_K_entries.parquet`, `out/cohort_K_features.parquet`,
`out/entries/part_*.parquet` — the last is a 254 MB derived per-entry table, not the raw tape).

---

## FACTS

### A. Raw data sources & date span
- **Fills:** `scratch_conv/mlscreen/cand2_{YYYYMM}.parquet` × 11 monthly shards. Schema:
  `wallet, ts, tid, coin, px, sz, crossed, zhash` (`sz` pre-signed; `crossed`=taker;
  `zhash`=self/wash flag). Source: `docs/ARCHITECTURE.md` §2.
- **Prices:** `scratch_conv/mlscreen/bars_{YYYYMM}.parquet` × 11, 5-min bar close, schema
  `coin, bar, close`. Source: `docs/ARCHITECTURE.md` §2.
- **Date span:** `T0 = 1754006400000` ms = **2025-08-01 00:00 UTC** (`src/mkcommon.py` L37 via
  `mlscreen2.T0`); `ALL_MONTHS` = Aug'25 … Jun'26 (`../scratch_conv/mlscreen2.py` L46-47:
  `TRAIN_MONTHS = [202508..202603]` + `[202604, 202605, 202606]`) — **11 calendar months**,
  confirmed by 11 `cand2_*.parquet` files on disk (202508 through 202606).
- **Splits (frozen, identical across every stage):** TRAIN `ts < 2026-02-01` · EMBARGO = Feb
  2026 · TEST `ts ≥ 2026-03-01`. Source: `docs/STAGE_K_ARCHITECTURE.md` §2, `src/cohort_K_price.py` L17.

### B. Coin scope
- **Primary universe (scored per-wallet):** BTC, ETH, SOL, HYPE, SPX. **Secondary (field-aggregate
  only):** ALT = any coin with ≥500 in-window bars, not one of the 5 majors, pooled per (ALT,
  horizon) cell — never a per-wallet row. Source: `docs/ARCHITECTURE.md` §1.
- **Stage-K / cohort study coin set:** BTC, ETH, SOL, HYPE only (SPX excluded — prior stages
  found it a "degenerate control"). Source: `docs/STAGE_K_ARCHITECTURE.md` §1.

### C. Full entry universe (`out/entries/part_*.parquet`, built by `src/build_entries.py`)
This is the bar-net, post-fill-priced entry table for **every** wallet/coin, before any cohort
filtering — the base population everything downstream draws from.
- **Total: 7,332,013 entries, 32,949 distinct wallets, 273 distinct coins** (computed via
  `pl.scan_parquet('out/entries/part_*.parquet')` group-by, streaming, threads=2; matches the
  ledger's independently-reported "7,332,013 entries" from the position-reconstruction rebuild,
  `docs/FINDINGS_LEDGER.md` L121).
- **Per-major-coin entries / distinct wallets** (full universe, all wallets, whole window):

  | coin | entries | wallets |
  |---|---|---|
  | BTC | 2,130,639 | 27,103 |
  | ETH | 1,039,163 | 24,053 |
  | SOL | 790,404 | 22,028 |
  | HYPE | 771,062 | 19,923 |
  | SPX | 19,402 | 2,081 |

  (computed, this task). Remaining ~2.58M entries / long tail of coins are ALT (e.g. ZEC:
  341,692 entries / 13,370 wallets was the largest single ALT coin observed).
- **Universe used to build the taker/hold features (`out/hold_size_dist.parquet`):** wallets
  with ≥200 fills across BTC/ETH/SOL/HYPE in `cand2_*` → **29,334 wallets** (`out/hold_size_dist.log`
  L2). Of these: **14,225** have `n_copyable ≥ 100` (taker-opened 1–24h round-trips), and
  **12,544** have both `n_copyable ≥ 100` AND `taker_share ≥ 0.70` (`out/hold_size_dist.log`
  L201-202).

### D. Stage-K cohort definition — exact filters (outcome-independent, frozen before any TEST read)
Source: `src/cohort_K_define.py` (Job B), `docs/STAGE_K_ARCHITECTURE.md` §1, ledger L367-369.
Built by inner-joining `out/hold_size_dist.parquet` (taker_share / hold-time / n_copyable, from
a full serial tape pass, whole-window train+test) with `out/wallet_level_persistence.parquet`
(pooled-across-majors 24h-markout counts, TRAIN-only `n`, renamed `n_train`). Filters (ALL must hold):
1. **`taker_share ≥ 0.70`** — crossed-notional share of ALL fills, whole window (`Σ crossed-notional
   / Σ total-notional` per wallet; computed in `src/hold_size_dist.py` from raw `cand2` fills, not
   from the entry table).
2. **`med_hold_h ∈ [1.0, 24.0]`** — median hold time (hours) of taker-**opened** round-trip closes
   (avg-cost ledger; a close only counts if the open-side inventory was >50% taker-notional).
3. **`n_train ≥ 200`** — pooled-across-BTC/ETH/SOL/HYPE count of TRAIN-window (Aug'25–Jan'26)
   finite 24h post-fill markout observations for that wallet (`src/wallet_level_persistence.py`,
   "decisions", NOT raw fills).
- **Coins:** BTC, ETH, SOL, HYPE (SPX excluded).
- Result: **1,694 wallets**, written to `out/cohort_K.txt` (frozen list) + `out/cohort_K_features.parquet`.
- Ledger's one-line summary: "99% taker, median hold 2.5h, median 289 decisions" (`docs/FINDINGS_LEDGER.md` L367-368) —
  confirmed by direct quantile computation (this task, on `out/cohort_K_features.parquet`, N=1,694):

  | feature | p25 | median | mean | p75 | max |
  |---|---|---|---|---|---|
  | `taker_share` | 0.929 | 0.985 | 0.952 | 0.999 | 1.000 (min 0.701, the filter floor) |
  | `med_hold_h` | 1.49 | 2.49 | 4.25 | 5.29 | 23.94 (min 1.00, the filter floor) |
  | `n_train` | 234 | 290 | 344 | 393 | 1,618 (min 200, the filter floor) |
  | `n_copyable` | 224 | 426 | 1,294 | 899 | 68,494 (heavy right tail — a few very high-frequency wallets) |

  By `n_train` sample-size tier (computed, this task): **200–500: 1,466 wallets · 500–1000: 213 ·
  ≥1000: 15.** (STAGE_K_ARCHITECTURE.md §1 calls ≥500 the pre-registered PRIMARY tier, 200–500 secondary/power-context.)

### E. Stage-K priced cohort entries (`out/cohort_K_entries.parquet`, built by `src/cohort_K_price.py`, Job C)
Per-entry markout term structure for the frozen 1,694-wallet cohort only (small, cohort-sized —
not the 7.3M full tape). Computed directly (this task) + cross-checked against `out/cohort_K_price.log`:
- **Shape: 812,616 rows × 18 columns.** Columns: `wallet, coin, b_ts, ym, dir, notl, regime, split,
  raw_1h, neut_1h, raw_2h, neut_2h, raw_4h, neut_4h, raw_8h, neut_8h, raw_24h, neut_24h`.
  - `raw_{h}` = signed post-fill markout return at horizon h, in bp (`dir·(exit_px/entry_px−1)·1e4`).
  - `neut_{h}` = `raw_{h} − dir·(coin-month drift)` — coin-month-mean-forward-return-neutralized
    ("skill" estimand; not deployable per Stage F ban, see `docs/ARCHITECTURE.md` §3 analog / STAGE_K_ARCHITECTURE.md §3).
  - `regime` = BTC-trailing-7-day tag at entry (BULL >+3%, BEAR <−3%, CHOP otherwise; look-ahead-free,
    `src/cohort_K_price.py` L30-35).
  - `split` = train/embargo/test per the frozen date boundaries.
- **Distinct wallets in the priced file: 1,694** (all of `cohort_K.txt` produced ≥1 priceable entry).
- **Date span of priced entries:** 2025-08-01 00:00 UTC → 2026-06-30 23:50 UTC (full 11-month window).
- **Per-coin entries / distinct wallets in the cohort** (computed, this task):

  | coin | entries | wallets |
  |---|---|---|
  | BTC | 356,118 | 1,543 |
  | ETH | 195,859 | 1,455 |
  | SOL | 135,357 | 1,365 |
  | HYPE | 125,282 | 1,237 |

  (per-coin wallet counts sum to 5,600 > 1,694 distinct — most cohort wallets trade ≥2 majors.)
- **Per-split entry counts** (`out/cohort_K_price.log` + confirmed by recompute): train 583,032 /
  embargo 61,116 / test 168,468.
- **Per-month (`ym`) entry counts** (computed, this task): 202508: 91,656 · 202509: 85,856 ·
  202510: 121,381 · 202511: 116,780 · 202512: 94,036 · 202601: 73,323 · 202602 (embargo): 61,116 ·
  202603: 48,043 · 202604: 38,874 · 202605: 37,950 · 202606: 43,601. Entry volume roughly **halves
  from the train window (Aug–Jan, ~73–121k/mo) to the test window (Mar–Jun, ~38–48k/mo)** — cohort
  activity is declining across the sample, not flat.
- **Regime distribution by split** (computed, this task; entry-counts, not wallet-counts):
  train BULL 117,359 / BEAR 219,330 / CHOP 246,343; test BULL 56,217 / BEAR 59,889 / CHOP 52,362;
  embargo BULL 1,954 / BEAR 39,906 / CHOP 19,256. Matches ledger's wallet/month-level regime
  characterization "TRAIN 40B/58Be/80C, TEST 38B/41Be/43C" (`docs/FINDINGS_LEDGER.md` L365, likely
  months-active or distinct-day counts at a coarser unit than these raw entry counts) — the TEST
  window is confirmed BTC-DOWN-dominated (ledger: "TEST is a −10.85% BTC DOWN window").
- **Direction split:** 511,071 long entries (63%) vs 301,545 short (37%) — the cohort is net-long-biased,
  consistent with the "static long-luck vs directional-timing" question Stage K was built to separate
  (`docs/STAGE_K_ARCHITECTURE.md` §0/§4).
- **Entries per wallet (pooled across coin+split), N=1,694 wallets** (computed, this task): min 200
  (filter floor, since `n_train` was the selection variable but counted differently — pooled TRAIN-only
  vs this all-split all-coin count, so the floor lines up by coincidence of wallets near the boundary,
  not identically), p25 281, median 388, mean 480, p75 589, p90 843, p99 1,521, max 2,390.

### F. Winsorization / measurement conventions inherited from the base pipeline (not cohort-specific, but govern every number above)
- Entries = bar-net, taker-only, non-wash position-increasing fills clustered by (bar, direction);
  post-fill pricing via `_next_bar_close_vec` (leak-free: first bar strictly after the fill's bar).
  Source: `docs/ARCHITECTURE.md` §4.2-4.3, `src/mkcommon.py` `taker_entries`.
- `MIN_NOTL = $100` dust floor already applied when `out/entries` was built (`src/build_entries.py` L66,
  `src/mkcommon.py` L35) — the 7.33M/32,949-wallet universe count above is POST-dust-floor.
- Cohort-level markouts (§E) are NOT winsorized in `cohort_K_price.py` (unlike the base
  `markout_stats.parquet` pipeline in `docs/ARCHITECTURE.md` §4.4) — raw/neut columns there are
  unclipped signed bp returns; downstream Stage K/L analysis applies its own bootstrap/clustering.

---

## FIGURES-TO-MAKE

1. **Universe funnel (bar or waterfall chart).**
   Data: 32,949 wallets (full entries universe) → 29,334 (≥200 majors fills) → 12,544 (n_copyable≥100
   AND taker_share≥0.70) → 1,694 (+ med_hold∈[1,24]h + n_train≥200 = final Stage-K cohort).
   Source: `out/entries/part_*.parquet` (computed count), `out/hold_size_dist.log` (29,334 / 14,225 / 12,544),
   `out/cohort_K.txt` (1,694).
   Axes: stage name (x, ordered) vs wallet count (y, log scale recommended given the range).
   Shows: how aggressively the cohort selection narrows the population — useful to preempt "why only
   1,694 of 33k wallets" questions.

2. **Entries-per-wallet distribution, cohort vs full universe (overlaid histogram or ECDF).**
   Data: per-wallet entry counts from `out/cohort_K_entries.parquet` (cohort, N=1,694, computed above)
   vs a comparable count from `out/entries/part_*.parquet` restricted to majors (full universe, N≈29-33k).
   Axes: x = entries per wallet (log scale), y = density or cumulative fraction.
   Shows: the cohort is a high-activity slice, not a random sample — visually motivates the "winner's
   curse fades at high N" framing used in Stage K.

3. **Entry volume over time, cohort (line/area chart, monthly).**
   Data: `out/cohort_K_entries.parquet` group_by `ym` → entry count (see §E monthly figures above),
   split by TRAIN (blue) / EMBARGO (gray) / TEST (orange) shading.
   Axes: x = month (Aug'25 → Jun'26), y = entry count.
   Shows: the ~2x activity decline from train to test window — important caveat for any OOS power
   discussion (test period has fewer observations per wallet than train).

4. **Per-coin composition, cohort vs full universe (grouped/100%-stacked bar).**
   Data: coin × {entries, distinct wallets} for both the full universe (§C table) and the cohort (§E table).
   Axes: x = coin (BTC/ETH/SOL/HYPE), y = share of entries or wallets (%).
   Shows: BTC dominates both universes proportionally (~29-31% of entries in the cohort vs the base ~44%
   of majors' entries), while HYPE/SOL are relatively over-represented in the cohort vs the full universe —
   worth a sentence on whether the taker/hold filters skew coin mix.

5. **Regime × split entry-count heatmap.**
   Data: the 3×3 (split × regime) entry-count table in §E, from `out/cohort_K_entries.parquet`.
   Axes: rows = split (train/embargo/test), columns = regime (BULL/BEAR/CHOP), cell = entry count
   (annotate raw count + % of that split's row).
   Shows: TEST is comparatively BEAR-heavy relative to TRAIN's CHOP-heavy tilt — the regime confound
   the later Stage K tests are built to control for.

6. **Cohort feature scatter: `med_hold_h` vs `n_train` (log-x), colored/sized by `taker_share`.**
   Data: `out/cohort_K_features.parquet`, all 1,694 wallets, 3 columns (`med_hold_h`, `n_train`, `taker_share`).
   Axes: x = n_train (log scale), y = med_hold_h (linear or log, 1-24h range), color/size = taker_share.
   Shows: the shape of the cohort in filter-space — whether high-N wallets cluster at short holds
   (scalper-adjacent) vs spread across the 1-24h band; motivates the n_train tier breakdown (200-500:
   1,466 / 500-1000: 213 / ≥1000: 15) visually.

---

## GAPS

- **No exact reconstruction of `cohort_K_define.py`'s own stdout** (it was not redirected to a log file
  the way `cohort_K_price.py` / `hold_size_dist.py` were) — the n_train-tier breakdown and characterization
  numbers quoted from the ledger were independently recomputed here from `out/cohort_K_features.parquet`
  and match, but the original run's exact printed values (e.g. the hold-floor sensitivity table at
  0.5h/1h/2h) are not preserved anywhere on disk and would need a re-run of `src/cohort_K_define.py` to
  regenerate (cheap — in-memory join, no tape scan — but out of this task's RAM-light-only scope was not
  the blocker; simply wasn't asked for).
- **`n_train` (selection variable, TRAIN-only pooled majors, from `wallet_level_persistence.parquet`)
  vs raw per-wallet entry count in `cohort_K_entries.parquet` (all-split, all-coin, from `cohort_K_price.py`)
  are two different denominators** computed by different scripts at different times — the aggregate split
  totals (train 583,032 / embargo 61,116 / test 168,468, §E) answer the aggregate version, but the
  per-wallet joint distribution (does a wallet's `n_train` selection count correlate with how much TEST
  data it has?) was not computed here — relevant to the OOS power discussion in Stage K, left as a
  follow-up join (`cohort_K_features.parquet.n_train` vs per-wallet TEST-split counts from
  `cohort_K_entries.parquet`).
- **Full-universe per-wallet entries-per-wallet distribution (needed for Figure 2) was not computed** in
  this pass — only the cohort-side distribution was computed. Computing the full-universe (majors-only,
  ~29-33k wallet) equivalent is a cheap follow-up (`pl.scan_parquet('out/entries/part_*.parquet')
  .filter(pl.col('coin').is_in(MAJORS)).group_by('wallet').agg(pl.len())`, streaming, threads=2) but was
  left for whoever builds Figure 2 rather than run speculatively here.
  - Ledger reconciliation caveat carried over from Stage K itself (not this task's finding, but relevant
  to any universe-level report claim): the ledger's regime tag "TRAIN 40B/58Be/80C, TEST 38B/41Be/43C"
  (`docs/FINDINGS_LEDGER.md` L365) is at a different unit (likely wallet-months or distinct trading days)
  than the raw entry-count regime table computed here in §E — I did not chase down the exact unit in
  `cohort_K_analyze.py`; someone writing the regime-methodology section of the final report should trace
  that number's exact definition before citing it alongside the entry-count table.
- **Did not open/verify `docs/COHORT_FORENSICS_ARCHITECTURE.md`** (Stage D typology doc) even though it's
  adjacent — out of this task's scope (Stage K universe, not Stage D/L archetype breakdown), but the "who
  are they" archetype counts (VAULT 17 / TWAP 151 / HEDGER 19 / DIRECTIONAL 587 / MIXED 920, from Stage L,
  `docs/FINDINGS_LEDGER.md` L~399) are a natural companion fact for whichever report section covers cohort
  composition qualitatively, not just quantitatively.
