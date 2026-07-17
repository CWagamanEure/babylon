# COPY-CONSTRUCTION STUDY — PREREGISTRATION (candidate-construction-ranking only)

**Registered:** 2026-07-16, BEFORE any forward markout of any new entry set or non-8h horizon
was computed.
**Status of the evaluation months: BURNED.** Folds 202511–202606 are the same reused
validation folds as ALT_UNIVERSE_PREREG / V2_BAKEOFF_PREREG / DECAY_ANATOMY. Therefore this
study is **CANDIDATE-CONSTRUCTION-RANKING ONLY** (same standing as V2_BAKEOFF_PREREG): it
ranks copy-construction variants for the live paper trader. It can NEVER be read as
out-of-sample confirmation of any cell, including the best one. No significance claims are
made on any cell; the deployment pick goes to the paper trader for genuinely forward
confirmation.

## Motivation (from DECAY_ANATOMY.md, the registered trigger)
Arm-T selection finds real traders (79.7% own-PnL forward persistence vs 33.9% eligible-pool
base), but the E1 copy construction loses them: **119/240 wallet-folds have ZERO evaluable
alt flat-open entries** (coverage hole), and 39% of trader-won folds still copy-lose at
alt/8h (wedge). Selection is not the lever; construction is.

## Registered questions (primary, in order)
1. **Coverage:** does adding majors flat-opens (E2) and adds (E3) lift the fraction of the
   240 arm-T wallet-folds with ≥1 evaluable entry, relative to E1's 121/240?
2. **Ranking surface:** what is the robust wallet-equal markout at each cell of the fixed
   grid below? Does any (entry set, horizon) cell materially change the book vs the E1/8h
   baseline (known: robust +24.5 bp fresh / raw +35.8 bp full-cohort wf-equal)?

## Fixed grid — no free search
- **Horizons (5):** {1h, 4h, 8h, 24h, 48h}. Fixed in advance; no other horizon may be
  reported.
- **Entry sets (3, nested):**
  - **E1** — alt flat taker opens (baseline, known construction): lake
    `alt_universe_open_entries` (crossed, direction Open Long/Short, start_position = 0),
    coin NOT IN {BTC, ETH, SOL, HYPE}. Identical to `alt_fresh_validate._forward_entries`.
  - **E2** — E1 + majors flat taker opens: same open_entries dataset, ALL coins (the
    open_entries ingest applied no coin filter; it is an exact row-for-row filter of
    Reservoir perp_fills on crossed & Open* & start_position = 0, so no separate majors
    pull is needed — deviation-from-brief note: majors come from open_entries rather than a
    redundant perp_fills re-pull; the rows are identical by construction of
    `alt_universe_ingest.py`).
  - **E3** — E2 + adds: crossed taker fills with direction IN ('Open Long','Open Short')
    AND start_position ≠ 0 (position increases), ALL coins, pulled per fold month from the
    lake `source=hyperliquid_reservoir/dataset=perp_fills` via duckdb httpfs, projecting
    only (wallet, coin, ts, direction), filtered to the fold's 30 cohort wallets. Pull
    cached per fold under `data/derived/copy_cohort/construction/adds/`.
- **Cohort (frozen):** arm T of `data/derived/copy_cohort/alt_universe_cohorts.json`,
  8 folds × 30 wallets = 240 wallet-folds. No selector change of any kind.
- Grid size = 3 × 5 = **15 cells**, all reported; no cell may be added, dropped, or tuned
  after seeing numbers.

## Markout & estimator spec (identical family to alt_fresh_validate)
- Markout: gross dir-signed bp vs local asset_ctx mid lattice (`data/raw/asset_ctx`),
  backward ASOF at entry and at entry+h, staleness ≤ 90s at BOTH ends, px0 > 0.
  dir_sign = +1 for Open Long, −1 for Open Short (adds signed the same way).
  ctx window per fold = fold month + first 3 days of the next month (covers 48h from the
  last entry of the month).
- **Registered headline spec per cell (robust):** winsor at p95 |mk| within the cell, keep
  wallet-folds with ≥3 evaluable entries in that cell, wallet-fold-equal mean of means.
  Raw point reported alongside, never headline.
- Uncertainty: wallet-cluster bootstrap, 4000 reps, base seed **20260716**, per-cell rng
  `default_rng(20260716 + 1000*set_index + horizon_index)` with set order (E1, E2, E3) and
  horizon order (1h, 4h, 8h, 24h, 48h) — deterministic, iteration-order independent.
- Also reported per cell: n entries, n evaluable wallet-folds (of 240) = coverage, n robust
  wallet-folds (≥3 entries), per-fold means of robust wallet-fold means, per-fold coverage.
- **Coverage table (registered primary #1):** per entry set × horizon, # of the 240
  wallet-folds with ≥1 evaluable (finite-markout) entry; headline coverage row quoted at 8h.
- **Sanity anchor (registered):** the raw wf-equal E1/8h full-cohort mean must reproduce
  DECAY_ANATOMY's +35.8 bp (same spec, same data) to ~0.1 bp, else the run is invalid.

## Multiplicity & honesty stamps
- 15 descriptive cells on burned folds. NO per-cell p-values are headlined and no cell is
  called "significant"; CIs are reported as ranking dispersion only. Adjectives allowed:
  "candidate-construction-ranking", "burned-fold". Banned: "confirmed", "validated", "OOS".
- The nested design (E1 ⊂ E2 ⊂ E3) and the shared wallets make cells strongly dependent;
  no cross-cell test is run.
- Decision output: a recommendation of ≤2 (entry set, horizon) constructions for the paper
  trader, preferring (in order) (1) coverage lift with robust point within 10 bp of the best
  cell, (2) shorter horizon at equal showing (capital turnover), (3) per-fold breadth.
  The recommendation is a candidate, not a finding.

## Artifacts
- Code: `research/studies/copy_cohort/construction_study.py`.
- Report: `data/derived/copy_cohort/construction_report.json`.
- Results appended below after the run; any deviation logged there.

---

## LAG-HAIRCUT CELL (registered follow-on, 2026-07-16 — appended BEFORE any lagged result was computed)

**Question:** how much of the E1 front-loaded gross markout survives realistic follower entry
lag (seconds-scale)? Same standing as the parent study: burned folds, candidate-construction
evidence only, no significance claims.

### Registered design (fixed before results)
- **Entry set:** E1 exactly as above (alt flat taker opens of the frozen arm-T cohorts,
  8 folds x 30 wallets; coin NOT IN {BTC, ETH, SOL, HYPE}); trader fill px carried from
  open_entries.
- **Lags (4):** {0s (anchor), 3s, 10s, 30s}. **Horizons (2):** {1h, 4h}. Grid = 8 cells,
  all reported, none may be added/dropped/tuned after seeing numbers.
- **Follower entry px:** the FIRST tape print on the same coin in lake Reservoir perp_fills
  at print_ts >= entry_ts + lag. Tolerance: the print must satisfy print_ts <= entry_ts +
  120s, else the entry is DROPPED for that lag and counted (drop rate reported per lag).
- **Endpoint:** local asset_ctx mid, backward ASOF at entry_ts + horizon (horizon anchored
  at the TRADER's entry_ts, not the follower print), staleness <= 90s, px > 0. Same lattice
  and _ctx_parts window as the parent study.
- **Markout:** dir_sign * (endpoint - follower_entry_px) / follower_entry_px * 1e4 (gross bp).
- **Estimator (identical robust spec):** winsor at p95 |mk| within each (lag, horizon) cell,
  keep wallet-folds with >= 3 evaluable entries in the cell, wallet-fold-equal mean;
  wallet-cluster bootstrap 4000 reps, per-cell rng
  `default_rng(20260716 + 1000*lag_index + horizon_index)` with lag order (0s, 3s, 10s, 30s)
  and horizon order (1h, 4h). Reported per cell: robust bp, 95% CI, P(>0), n entries,
  n robust wallet-folds, drop rate.
- **Slippage decomposition (registered secondary):** dir-signed bp from trader fill px to
  the lag-L first print, slip = dir_sign * (print_px - trader_px) / trader_px * 1e4
  (positive = follower pays worse than the trader). Mean + median per lag, plus the lag-0
  component (trader fill -> first subsequent print = immediate-impact/quantization) reported
  separately from the incremental 3s/10s/30s drift.
- **Sanity anchor:** the lag-0 cell's robust point must land near the parent E1/1h and E1/4h
  cells (+21.8 / +18.8 bp) — material disagreement (>|10| bp) invalidates the print-join, not
  the finding.
- **Mechanics:** entries built locally from lake open_entries; print join runs on the droplet
  (same-region Spaces) over perp_fills projecting (coin, ts, px) only; markout + estimator
  local. Artifacts: `data/derived/copy_cohort/lag_haircut_report.json`, results appended
  below.

---

## K-SWEEP × VENUE (registered 2026-07-16, BEFORE any forward number of this grid was computed)

**Stamp: CANDIDATE-RANKING.** Folds 202511–202606 are the same BURNED validation folds as the
parent study. This section ranks (cohort size K × venue) constructions for the paper trader; it
can NEVER be read as out-of-sample confirmation of any cell. No cell is called significant.

### Fixed grid — no free search
- **K (4):** {10, 30, 50, 100} — top-K by `t_stat` recomputed per fold from
  `data/derived/copy_cohort/informedness/fold=*/pool.parquet` (eligibility nd≥15, sd>0 already
  baked into the pool), AFTER excluding the frozen-133 wallets
  (`data/derived/copy_cohort/frozen_alt_universe.json` → `distinct_wallets`). K sets are nested
  prefixes of one ranking; ties broken by wallet string (deterministic).
- **Venue (2):**
  - **MAJORS** = coin IN {BTC, ETH, SOL, HYPE}.
  - **LIQUID_ALT** = coin NOT IN majors AND coin-month ADV ≥ $10M, ADV computed per coin from
    lake `wallet_coin_day` over the TEST month as
    SUM(CAST(notional AS DOUBLE))/2/COUNT(DISTINCT day). ⚠️ Registered deviation from
    deployability: this is a **mild look-ahead on liquidity** (test-month ADV; a real
    deployment uses trailing ADV). Noted, accepted for ranking purposes.
- Grid = 4 × 2 = **8 cells**, all reported; none may be added, dropped, or tuned after
  seeing numbers.

### Entries, markout, estimator (identical family to the parent study)
- **Entries:** forward-(test-)month flat taker opens from lake `open_entries`
  (source=babylon_derived/dataset=alt_universe_open_entries), notional (`notl`) ≥ $250,
  restricted to the fold's top-K wallets.
- **Markout:** 1h gross dir-signed bp vs LOCAL asset_ctx mid (`data/raw/asset_ctx`), backward
  ASOF at entry and entry+1h, staleness ≤ 90s both ends, px0 > 0 (alt_fresh_validate
  machinery). **Basis = mid**; per `lag_haircut_report.json` a follower pays ≈1–1.6 bp
  slippage at 3–30 s lag — quote the ~1 bp lag haircut alongside, never silently netted.
- **Robust spec (headline):** winsor at p95 |mk| within the cell, keep wallet-folds with ≥3
  evaluable entries, wallet-fold-equal mean of means; raw point alongside, never headline.
- **Uncertainty:** wallet-cluster bootstrap, 4000 reps, per-cell rng
  `default_rng(20260716 + 1000*k_index + venue_index)`, k order (10, 30, 50, 100),
  venue order (MAJORS, LIQUID_ALT) — deterministic, iteration-order independent.
- **Reported per cell:** n entries, n distinct wallets covered (≥1 evaluable entry) + n
  wallet-folds covered of 8K, robust bp + 95% CI + P(>0), per-fold signs (sign of per-fold
  mean of robust wallet-fold means), entries/day (n evaluable entries ÷ 242 calendar days).
- **K-frontier read (registered secondary):** per venue, does the robust point dilute with K
  more slowly than the CI shrinks? Efficient K = the K maximizing robust-point ÷ CI-half-width
  subject to entries/day ≥ 1 (a ranking heuristic, not a test).

### Multiplicity & honesty stamps
- 8 descriptive cells on burned folds; nested K and shared wallets make cells strongly
  dependent; no cross-cell test, no per-cell significance claims. Banned words: "confirmed",
  "validated", "OOS". Allowed: "candidate-ranking", "burned-fold".

### Artifacts
- Code: `research/studies/copy_cohort/ksweep.py`.
- Report: `data/derived/copy_cohort/ksweep_report.json`. Results appended below after the
  run; any deviation logged there.

### RESULTS (run 2026-07-16, all 8 registered cells, no deviations; burned-fold candidate-ranking)

| K | venue | n entries | wallets covered | robust bp (1h gross) | 95% CI | P(>0) | fold signs | entries/day |
|---|-------|-----------|-----------------|----------------------|--------|-------|------------|-------------|
| 10 | MAJORS | 1,524 | 19 | −2.8 | [−25.8, +9.1] | 0.39 | 1/5 | 6.3 |
| 10 | LIQUID_ALT | 666 | 9 | +18.7 | [−16.0, +65.6] | 0.83 | 5/8 | 2.8 |
| 30 | MAJORS | 4,040 | 56 | −2.0 | [−10.0, +4.5] | 0.29 | 4/8 | 16.7 |
| 30 | LIQUID_ALT | 1,154 | 30 | +24.6 | [−3.6, +57.2] | 0.95 | 4/8 | 4.8 |
| 50 | MAJORS | 5,970 | 89 | −4.8 | [−12.3, +1.5] | 0.08 | 3/8 | 24.7 |
| 50 | LIQUID_ALT | 1,794 | 57 | +16.4 | [−3.6, +36.9] | 0.94 | 5/8 | 7.4 |
| 100 | MAJORS | 11,831 | 181 | −0.4 | [−5.6, +4.5] | 0.44 | 4/8 | 48.9 |
| 100 | LIQUID_ALT | 4,944 | 120 | +15.3 | [+3.6, +28.6] | 0.995 | 5/8 | 20.4 |

**K-frontier (registered secondary).** LIQUID_ALT: the robust point dilutes mildly with K
(+18.7 → +24.6 → +16.4 → +15.3) while the CI half-width shrinks ~3.3× (40.8 → 12.5) —
dilution is much slower than power growth; score (point/half-width) rises monotonically-ish
0.46 → 0.81 → 0.81 → 1.23 → **efficient K = 100**. MAJORS: robust point is ≤ 0 at every K
(−4.8 … −0.4); the registered heuristic mechanically returns K=100 (least-negative score),
but the honest frontier read is **no efficient K — do not allocate the MAJORS venue from
this selector** (K=100 MAJORS CI [−5.6, +4.5] is a reasonably tight burned-fold bracket
around zero at 1h gross).

**Honest caveats (registered stamps apply).**
- BURNED folds (202511–202606, reused across the whole study line): candidate-ranking only;
  the K100/LIQUID_ALT CI excluding 0 is NOT an OOS confirmation and is not called
  significant. Deployment pick goes to the paper trader.
- Test-month ADV look-ahead on the LIQUID_ALT membership (mild; deployment uses trailing).
- Gross mid-basis at 1h; subtract ≈1–1.6 bp follower lag slippage (lag_haircut_report.json)
  and taker fees before any net read.
- Coverage is thin: only 18–22% of selected wallet-folds have ≥1 evaluable LIQUID_ALT entry
  (e.g. 173/800 at K=100); raw (un-winsorized) points diverge from robust in small cells
  (K10/LIQUID_ALT raw −38.6 vs robust +18.7 — single blowups dominate raw), so the robust
  spec is load-bearing.
- Nested K + shared wallets ⇒ the 8 cells are strongly dependent; no cross-cell test.

---

## MAJORS-NATIVE SELECTION × HORIZON (registered 2026-07-16, BEFORE any forward number of this grid was computed)

**Stamp: CANDIDATE-RANKING.** Folds 202511–202606 are the same BURNED validation folds as the
parent study and the K-SWEEP. This section ranks (majors-native cohort size K × horizon)
constructions; it can NEVER be read as out-of-sample confirmation of any cell. No cell is
called significant.

**Motivation.** The prior majors-zero (K-SWEEP: robust ≤ 0 at every K, K100 CI [−5.6, +4.5]
at 1h) used a VENUE-BLIND selector: the capped-daily-PnL t-stat is computed across ALL coins,
so alt activity dominates the ranking, and the graded horizon (1h) is alt-appropriate.
Majors may carry slower, venue-specific information. This grid tests venue-MATCHED selection
(t-stat on MAJORS-only capped daily PnL) graded at venue-appropriate horizons out to 48h.

### Fixed grid — no free search
- **Selection (per fold):** from lake `wallet_coin_day`, MAJORS-ONLY (coin IN {BTC, ETH,
  SOL, HYPE}) capped daily PnL series over the 3-month formation window:
  day_pnl = Σ(pnl − fee) over majors coins, day_notional = Σ notional over majors,
  cap_pnl = day_pnl × min(1, 100k / day_notional). Eligibility nd ≥ 15 majors-active days
  AND sd(cap_pnl) > 0; t_stat = mean / (sd / √nd). Frozen-133 wallets
  (`data/derived/copy_cohort/frozen_alt_universe.json` → distinct_wallets) excluded BEFORE
  ranking. Ranking = t_stat desc, wallet asc tie-break (deterministic); K sets are nested
  prefixes of one top-100 ranking.
- **K (2):** {30, 100}.
- **Horizons (5):** {1h, 4h, 8h, 24h, 48h}.
- Grid = 2 × 5 = **10 cells**, all reported; none may be added, dropped, or tuned after
  seeing numbers.

### Entries, markout, estimator (identical family to the K-SWEEP)
- **Entries:** forward-(test-)month MAJORS flat taker opens from lake `open_entries`
  (coin IN {BTC, ETH, SOL, HYPE}), notional (`notl`) ≥ $250, restricted to the fold's
  top-K wallets.
- **Markout:** gross dir-signed bp vs LOCAL asset_ctx mid (`data/raw/asset_ctx`), backward
  ASOF at entry and entry+h, staleness ≤ 90s at BOTH ends, px0 > 0 (alt_fresh_validate
  machinery). Ctx window per fold = fold month + first 3 days of the next month via
  `_ctx_parts` (verified: covers the +48h endpoint of the last entry of every fold month;
  asset_ctx has month=202607 locally). Basis = mid, gross; the ~1–1.6 bp follower lag
  slippage (lag_haircut_report.json) and taker fees are quoted alongside, never netted.
- **Robust spec (headline):** winsor at p95 |mk| within the cell, keep wallet-folds with ≥3
  evaluable entries in the cell, wallet-fold-equal mean of means; raw point alongside,
  never headline.
- **Uncertainty:** wallet-cluster bootstrap, 4000 reps, per-cell rng
  `default_rng(20260716 + 1000*k_index + horizon_index)`, k order (30, 100), horizon order
  (1h, 4h, 8h, 24h, 48h) — deterministic, iteration-order independent.
- **Reported per cell:** n evaluable entries, n distinct wallets covered + n wallet-folds
  covered of 8K, robust bp + 95% CI + P(>0), per-fold signs (sign of per-fold mean of robust
  wallet-fold means), entries/day (n evaluable ÷ 242 calendar days).
- **Overlap (registered descriptive):** per fold, |majors-native top-K ∩ arm-T-30
  (alt_universe_cohorts.json)| and |majors-native top-100 ∩ venue-blind top-100 (K-SWEEP
  ranking, frozen-133 excluded)| — to state how distinct the majors-native cohort is from
  the alt-native cohorts already reported.

### Multiplicity & honesty stamps
- 10 descriptive cells on burned folds; nested K, shared wallets, and overlapping horizons
  make cells strongly dependent; no cross-cell test, no per-cell significance claims.
  Banned words: "confirmed", "validated", "OOS". Allowed: "candidate-ranking", "burned-fold".
- The registered read: is there ANY horizon where majors-native selection shows a positive
  robust point with a CI not centered on ≤0, and how does the K30 vs K100 frontier compare?
  Answered descriptively; the deployment pick (if any) goes to the paper trader.

### Artifacts
- Code: `research/studies/copy_cohort/majors_native.py`.
- Report: `data/derived/copy_cohort/majors_native_report.json`. Results appended below
  after the run; any deviation logged there.

### RESULTS (run 2026-07-16, all 10 registered cells, no deviations; burned-fold candidate-ranking)

| K | horizon | n entries | wallets covered | robust bp (gross) | 95% CI | P(>0) | fold signs | entries/day |
|---|---------|-----------|-----------------|--------------------|--------|-------|------------|-------------|
| 30 | 1h | 5,655 | 51 | −1.1 | [−7.7, +4.1] | 0.35 | 3/8 | 23.4 |
| 30 | 4h | 5,655 | 51 | +10.8 | [−5.8, +25.5] | 0.91 | 4/8 | 23.4 |
| 30 | 8h | 5,655 | 51 | **+28.1** | [+4.0, +54.8] | 0.99 | 5/8 | 23.4 |
| 30 | 24h | 5,655 | 51 | +25.4 | [−15.3, +68.9] | 0.89 | 6/8 | 23.4 |
| 30 | 48h | 5,655 | 51 | +8.4 | [−45.6, +64.6] | 0.62 | 5/8 | 23.4 |
| 100 | 1h | 12,264 | 166 | −0.6 | [−5.1, +3.7] | 0.39 | 3/8 | 50.7 |
| 100 | 4h | 12,264 | 166 | +1.9 | [−6.1, +9.3] | 0.67 | 3/8 | 50.7 |
| 100 | 8h | 12,264 | 166 | +7.3 | [−4.5, +19.4] | 0.89 | 4/8 | 50.7 |
| 100 | 24h | 12,264 | 166 | +6.1 | [−14.6, +27.4] | 0.71 | 5/8 | 50.7 |
| 100 | 48h | 12,264 | 166 | +7.7 | [−21.2, +36.2] | 0.70 | 4/8 | 50.7 |

**Registered read.** (a) At 1h, majors-native selection reproduces the K-SWEEP's venue-blind
majors-zero (K30 −1.1, K100 −0.6, tight-ish CIs around 0) — the prior majors-null was NOT an
artifact of venue-blind selection *at that horizon*. (b) The registered venue-appropriate-horizon
question comes back POSITIVE-LEANING with a hump at 8h: K30/8h robust **+28.1 bp,
CI [+4.0, +54.8], P(>0)=0.99, 5/8 folds > 0, 23 entries/day**; the shape 1h→8h→48h
(−1.1 → +28.1 → +8.4) is a rise-then-fade term structure, with 24h/48h CIs too wide to rank.
(c) K-frontier: K30 dominates K100 at every horizon ≥ 4h (K100/8h = +7.3, CI spans 0) —
majors-native concentration matters; dilution is fast.

**Honest caveats (registered stamps apply).**
- BURNED folds (202511–202606, reused across the whole study line): candidate-ranking only.
  The K30/8h CI excluding 0 is NOT an OOS confirmation and is not called significant.
- 10-cell grid: the best cell is an argmax over 10 strongly dependent cells (same entries,
  nested K, overlapping horizons); no multiplicity correction is applied and none would make
  the cell a claim. It is a candidate for the paper trader.
- 8h ≈ the E1/alt hump horizon already reported (alt robust +24.5 fresh / +35.8 raw at 8h) —
  consistent, but also means the horizon was a-priori-favored by prior burned-fold looks.
- Cohort overlap (registered descriptive): majors-native top-30 shares mean **16.25/30**
  wallets/fold with arm-T-30, and majors-native top-100 shares mean **55.9/100** with the
  venue-blind K-SWEEP top-100 — this is NOT an independent wallet population; the positive
  8h cell partially re-measures the same traders on their majors entries.
- Gross mid-basis: subtract ≈1–1.6 bp follower lag slippage (lag_haircut_report.json) and
  taker fees before any net read; at +28.1 bp gross the 8h cell survives that arithmetic,
  at +7.3 (K100) it is marginal.
- Evaluable-n is identical across horizons within K (staleness rarely binds on majors ctx),
  so horizon cells share exactly the same entry rows — maximal dependence.

---

## WALLET×COIN HIERARCHICAL SELECTOR (closing look) — registered 2026-07-16, BEFORE any forward number of this design was computed

**Stamp: CANDIDATE-RANKING — and the registered CLOSING LOOK of the burned-fold line.**
Folds 202511–202606 are the same BURNED validation folds as every prior section. This is,
explicitly counted, at least the **5th registered burned-fold grid of 2026-07-16 alone**
(after §CONSTRUCTION 15 cells, §LAG-HAIRCUT 8 cells, §K-SWEEP 8 cells, §MAJORS-NATIVE 10
cells) and follows the earlier looks of the line (ALT_UNIVERSE_PREREG validation,
V2_BAKEOFF_PREREG, DECAY_ANATOMY, ZBAND_SEMIFRESH, TSPLIT). Nothing reported below can be
read as out-of-sample confirmation; no cell or book is called significant. **This is the
declared LAST burned-fold look**: after this section, the next evidence on this line must
come from the forward paper trader, not from these folds.

**Motivation.** The pooled-universe t-stat averages away coin-specific edge: majors-native
selection found +28.1 bp @8h (K30) where the venue-blind pooled selector was ≈0 on majors at
every K; the cohort census shows single-coin specialists whose global t is diluted by their
other coins. Hypothesis: selecting (wallet, coin) CELLS — hierarchically shrunk toward the
wallet's global score — and copying each wallet only in its selected coin(s), at the venue's
frozen horizon, beats pooled wallet-level selection on the same burned data.

### Formation (per fold, 202511–202606; 3 calendar months < fold, as everywhere in the line)
- From lake `wallet_coin_day`: per (wallet, coin, day) sum pnl−fee and notional; capping
  stays at the **WALLET-DAY** level so results reconcile with all prior capday studies:
  cap factor = min(1, 100k / wallet_day_notional) with wallet_day_notional summed across ALL
  coins that day, then applied multiplicatively to each coin's (pnl−fee) that day.
- Per cell: nd_wc = coin-active days in formation, mean(cap_pnl_wc), sd(cap_pnl_wc).
- Wallet global score: the EXISTING informedness pool
  (`data/derived/copy_cohort/informedness/fold=*/pool.parquet`, alt_select spec: all-coin
  capped daily PnL, nd ≥ 15, sd > 0) — reused untouched, "as before".

### Hierarchical shrinkage (empirical-Bayes, all constants frozen — no tuning)
- Cell eligibility: nd_wc ≥ 8 AND sd_wc > 0 AND wallet present in the fold's informedness
  pool (nd ≥ 15, sd > 0). t_wc = mean/(sd/√nd_wc).
- z-scale (frozen resolution of the brief's z): the line's existing probit transform
  `informed.t_to_z` — z_wc = Φ⁻¹(1 − p_t(t_wc, df = nd_wc − 1)) clipped ±8; z_w = the pool's
  stored `z` column (same transform on the global t, df = nd − 1). Both are N(0,1)-scale
  under the null, so the mixture is coherent.
- Shrunk score: **z_wc_shrunk = w·z_wc + (1−w)·z_w, w = nd_wc/(nd_wc + τ), τ = 20 (frozen).**
- Selection per fold: exclude frozen-133 wallets
  (`frozen_alt_universe.json → distinct_wallets`) BEFORE ranking; rank all eligible cells by
  z_wc_shrunk desc, tie-break (wallet asc, coin asc) — deterministic; take the **top 300
  cells**; THEN keep only venue-tradeable coins: coin ∈ MAJORS {BTC, ETH, SOL, HYPE} OR
  **trailing** ADV ≥ $10M, ADV computed from lake `wallet_coin_day` over the LAST formation
  month (fold − 1) as SUM(notional)/2/COUNT(DISTINCT day) — **no test-month look-ahead this
  time** (fixes the K-SWEEP's registered ADV deviation). Final selection ≤ 300 cells/fold.

### Forward book (test month = fold)
- Entries: lake `open_entries` flat taker opens, notl ≥ $250, joined on the selected
  (wallet, coin) pairs — each wallet is copied ONLY in its selected coin(s).
- Horizon (frozen per venue, from the prior sections' term structures): **8h for MAJORS
  coins, 1h for alt coins.** Markout: gross dir-signed bp vs local asset_ctx mid, backward
  ASOF at entry and entry+h, staleness ≤ 90s both ends, px0 > 0 (identical machinery).
- **Robust spec (headline):** winsor at p95 |mk| **within venue sub-book** (pooled across
  folds, as prior within-cell winsor); keep wallet-folds with ≥ 3 evaluable entries in that
  venue sub-book; wallet-fold-equal mean of wallet-fold means (the brief's "wallet-equal",
  same estimator as every prior section). Raw point alongside, never headline.
- **Books reported (3):** MAJORS sub-book (@8h), ALT sub-book (@1h), COMBINED = pooled
  wallet-fold-venue robust means across both sub-books (unit = (wallet, fold, venue), each
  venue's winsor/wf≥3 applied first), wallet-fold-equal over those units.
- Uncertainty: wallet-cluster bootstrap, 4000 reps, per-book rng
  `default_rng(20260716 + book_index)`, book order (MAJORS, ALT, COMBINED) = (0, 1, 2) —
  deterministic, iteration-order independent.
- Per book: n entries, n cells with ≥1 evaluable entry, n wallets covered, n robust
  wallet-folds, robust bp + 95% CI + P(>0), raw bp, per-fold signs, entries/day (÷242).
- **Head-to-head (registered comparison, restated not recomputed):** ALT sub-book vs
  K-SWEEP K100/LIQUID_ALT @1h (+15.3, CI [+3.6, +28.6]); MAJORS sub-book vs MAJORS-NATIVE
  K30/8h (+28.1, CI [+4.0, +54.8]). Basis = gross mid; the ~1–1.6 bp lag haircut + taker
  fees quoted alongside, never netted.
- **Specialist census (registered descriptive):** per selected cell, the wallet's formation
  notional share on that coin (Σ notional_coin / Σ notional_all over the 3 formation
  months); **specialist iff share ≥ 0.5** (frozen); also cells-per-wallet distribution and
  majors/alt cell split.

### Multiplicity & honesty stamps
- One registered design, 3 dependent books, on folds burned by ≥5 prior grids today; any
  positive is a candidate-ranking read for the paper trader, nothing more. Banned:
  "confirmed", "validated", "OOS", "significant". The comparison vs the two baselines is
  descriptive (shared wallets, shared months, shared machinery — maximal dependence).
- Deviations from the brief, resolved and frozen BEFORE running: (a) z defined via the
  line's probit t_to_z (the brief left the z-scale unstated); (b) "wallet-equal" implemented
  as wallet-fold-equal with wallet-cluster bootstrap (the line's standard estimator);
  (c) trailing ADV = last formation month (the brief said trailing-formation-month).
- Decision output: what goes on the paper trader — chosen by (1) robust point with CI not
  centered ≤ 0, (2) entries/day ≥ 1, (3) simplicity vs the existing K100/liquid-alt and
  K30/majors-native candidates. A candidate, not a finding.

### Artifacts
- Code: `research/studies/copy_cohort/wallet_coin_selector.py`.
- Report: `data/derived/copy_cohort/wallet_coin_report.json`.
- Selection table (paper-trader input):
  `data/derived/copy_cohort/wallet_coin_selection/fold=*/selected.parquet`
  (wallet, coin, nd_wc, t_wc, z_wc, z_w, w, z_wc_shrunk, venue, horizon_h, adv_trailing,
  notl_share, specialist).
- Results appended below after the run; any deviation logged there.

### RESULTS (run 2026-07-16, all 3 registered books, no deviations; burned-fold candidate-ranking — the CLOSING LOOK)

Selection: 300 cells/fold ranked, 109–198/fold survive the venue rule (trailing-ADV drops
102–191 illiquid cells/fold; illiquidity of top cells is itself informative — the shrunk
score loves thin coins). 1,193 selected cells total: 739 majors (62%), 454 alt (38%).

| book | horizon | n entries | wallets | robust bp (gross) | 95% CI | P(>0) | raw bp | fold signs | e/d |
|------|---------|-----------|---------|-------------------|--------|-------|--------|------------|-----|
| MAJORS sub-book | 8h | 9,201 | 91 | **+2.1** | [−12.0, +15.9] | 0.61 | −2.1 | 4/8 | 38.0 |
| ALT sub-book | 1h | 1,062 | 29 | **+1.6** | [−9.7, +13.5] | 0.62 | +18.3 | 4/8 | 4.4 |
| COMBINED | mixed | 10,263 | 110 | **+2.0** | [−9.2, +12.5] | 0.63 | — | 5/8 | 42.4 |
| baseline: K-SWEEP K100/LIQUID_ALT | 1h | 4,944 | 120 | +15.3 | [+3.6, +28.6] | 0.995 | — | 5/8 | 20.4 |
| baseline: MAJORS-NATIVE K30 | 8h | 5,655 | 51 | +28.1 | [+4.0, +54.8] | 0.99 | — | 5/8 | 23.4 |

**Registered read (descriptive; shared wallets/months/machinery — no test).** Coin-conditioned
hierarchical selection does NOT beat pooled/venue-native selection on the same burned data: all
three books sit at ≈ +2 bp gross with CIs spanning zero, and each sub-book's CI upper bound sits
BELOW its same-venue baseline point (+15.9 < +28.1 majors; +13.5 < +15.3 alt). Fold dispersion
is violent on majors (per-fold means −60.6 … +92.8), and the majors raw point is negative
(−2.1) against robust +2.1 — blowup-dominated. On the registered decision criteria the design
FAILS (1) (CI wide, point ≈ 0) and is dominated on (3) — **it does not go on the paper trader.**

**Specialist census (registered descriptive).** 456/1,193 cells (38%) are specialists
(formation notional share ≥ 0.5); median share 0.21 — the modal selected cell is a
GENERALIST's best coin, not a single-coin specialist. 576/749 wallet-folds contribute 1 cell;
the tail is long (up to 17 cells/wallet-fold — multi-coin generalists whose high global z_w
lifts every coin they touch through the (1−w)·z_w term).

**Honest caveats.** Burned folds; ~5 grids today alone; per the over-nulling gate this is NOT
"coin-conditioning is dead" — it is "THIS shrinkage selector (τ=20, top-300 cells, probit-z
mixture) ranks below both existing candidates on burned data" (a method-scoped ranking, CI
[−9.2, +12.5] combined still admits +12 bp). The mechanism worth remembering: shrinkage toward
the pooled z re-imports exactly the dilution the design tried to escape, and high-nd_wc cells
(the ones w trusts) are disproportionately HFT-ish wallets whose flow the census already showed
is uncopyable. **CLOSING-LOOK STAMP: this line's burned folds are now retired; next evidence =
forward paper trader (K100 liquid-alt @1h, K30 majors-native @8h, vault-deposit ranking).**
