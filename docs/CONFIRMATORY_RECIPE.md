# RECIPE — exact reproduction of the 21-candidate / 7-OOS wallet list (2026-07-09)

> ⚠️ **SUPERSEDED RUN + KNOWN CODE BUG.** This describes the ORIGINAL (pre-A1/A2) run. Current
> `confirmatory.py` defaults implement amendments A1+A2, and `data/derived/confirmatory/` now holds the
> 83-candidate A1+A2 run (see `WALLET_CANDIDATES_2026-07-09.md`). BOTH runs used code carrying the
> fetchnumpy MaskedArray NULL bug (NULLs read as ~0.0; fixed 2026-07-10 via `_fcol`); numbers were mildly
> attenuated and a rerun with fixed code shifts them slightly — see the certification rerun of 2026-07-10.

Companion to `docs/CONFIRMATORY_PREREG.md` (the frozen protocol). This documents every step, parameter, and
input needed to recreate `data/derived/confirmatory/{candidates,oos_results}.parquet` from scratch.

## 0. Environment
- `.venv/bin/python`; DuckDB `memory_limit='4GB'`, `threads=2`, `temp_directory='.tmp'`; run with `TMPDIR=.tmp`.
- Seeds: discovery `np.random.default_rng(20260709)`; OOS `rng(20260709 + 1)`.
- Coins: BTC, ETH, SOL, HYPE (`schema.SZD` keys). Tape window 2025-08-01 → 2026-06-29.

## 1. Data foundation
1. Fills tape `data/raw/fills/` (S3 node_fills_by_block per `markout_study/discovery/RESTORE_PLAN_v1.md`).
2. Episode lake `data/derived/episodes/month=*/episodes.parquet` via
   `python -m research.data.episodes_build all_carry` — schema `episodes_v1_lifecycle_enriched_2026-07-07`,
   33,794,649 lifecycle episodes (flat→open …adds/reduces… → CLOSE at flat or FLIP at sign change), sort
   `(wallet, coin, block_number, event_index, tid)`, cross-month carry-seed.
3. Price panel `data/raw/asset_ctx/month=*/day=*/ctx.parquet` — per-minute ctx, 478,480 ticks/coin, ~60s
   cadence; price = `oracle_px` (TRY_CAST DOUBLE, non-null, dedup per ts).

## 2. Markout backfill — `python -m research.data.markout all`
Per coin, per episode, excluding `inherited_basis=true`:
- `entry_bar_ts` = first oracle tick STRICTLY after `open_ts` (forward ASOF). `p0` = oracle_px(entry_bar_ts).
- `entry_lag_s = (entry_bar_ts − open_ts)/1000`; `entry_after_close = close_ts IS NOT NULL AND entry_bar_ts ≥ close_ts`.
- Horizons: 5m 15m 30m 1h 2h 4h 8h 16h 24h 48h. `ph_h` = backward ASOF ≤ `entry_bar_ts+h`, valid iff matched
  tick within 90,000 ms (`STALE_MS`), else NULL.
- `raw_markout_h = dir_sign·(ph − p0)/p0·1e4`; `dir_sign = +1 long / −1 short`.
- Output: `data/derived/episodes_markout/coin=*/part-b{0..7}.parquet` (8 wallet-hash buckets, COPY zstd).
  Rows: BTC ~14.0M, ETH 7,540,402, SOL 5,347,750, HYPE 6,664,108.

## 3. μ baseline — `python -m research.data.mu_baseline all`
Per coin, every grid minute t: `fwd_ret_h(t) = (P(t+h) − P(t))/P(t)·1e4` (same ASOF + ≤90s staleness, NULL
otherwise) + `iso_week ('%G%V')` → `data/derived/fwd_returns/coin=*/part.parquet`. Cutoff-free; all period
scoping happens at use time.

## 4. Estimand (identical in both stages), period [lo, hi)
- `μ_h(coin, period)` = avg(fwd_ret_h) over minutes with `fwd_ret_h NOT NULL AND ts ≥ lo AND (ts+h) ≤ hi`.
- Episode inclusion: `entry_bar_ts ∈ [lo,hi)` AND `close_ts ≤ hi` AND `NOT entry_after_close` AND
  `entry_lag_s ≤ 90`; per-horizon value only if `(entry_bar_ts+h) ≤ hi`.
- **timing_alpha_h = raw_markout_h − dir_sign·μ_h(coin, period)** (bp; static direction ≈ 0 by construction —
  NOT a fitted beta regression, just the coin's own drift; at 1–8h the correction is <1bp).
- `day = entry_bar_ts // 86400000` (UTC); `hod = (entry_bar_ts//3600000) % 24`.

## 5. Stage 1 — DISCOVERY (`python -m research.data.confirmatory discover`)
Frozen: horizons {1h,2h,4h,8h}, HYPE-8h excluded; discovery [2025-08-01, 2026-02-01); B=10,000; BH q=0.10;
distinct-day floor 10; care 8bp.

Eligibility (episode lake, `close_ts ∈ [lo,hi)`, GROUP BY wallet,coin, HAVING):
  E1 Σ(n_taker+n_maker fills) ≥ 200 · E2 distinct ISO close-weeks ≥ 8 · E3 Σ(initial+added notional) ≥ $1M ·
  E4 flagged share < 0.30 · E5 liq share < 0.10 · E6 taker share ≥ 0.50 · S2 Σrealized_net_usd > 0;
  keep med_hold = median((close_ts−open_ts)/60000).  → **2,878 wallet-coins**.

Per wallet-coin (numpy on the pulled episode timing_alphas):
  E8 eligible horizons: horizon-minutes {60,120,240,480} ≤ 4×med_hold.
  Per eligible horizon: need ≥5 non-NaN episodes AND ≥10 distinct days; est = plain mean over episodes.
  S1 best_horizon = argmax(est) over eligible horizons (ties → earlier of 1h,2h,4h,8h); require est > 8bp.
  S3 drop-best-day: mean excluding highest day-mean day > 0.
  S4 day-block bootstrap p at best horizon: obs ≤ 0 → p=1; else resample nd days w/ repl 10,000×,
     p = (1+#{boot ≤ 0})/10,001; **p_adj = min(1, p × n_horizons_searched)** (Bonferroni over argmax).
  → **1,467 pass S1–S3**. BH-FDR q=0.10 over p_adj (family=1,467; realized threshold p ≤ 0.0012)
  → **21 CANDIDATES** → `data/derived/confirmatory/candidates.parquet` + `freeze.json`
  (written BEFORE any OOS computation). `disc_est` = in-sample selected mean (winner's-curse-inflated).

## 6. Stage 2 — OOS (`python -m research.data.confirmatory oos`)
OOS [2026-02-01, 2026-06-29); frozen horizon only, no second argmax; OOS-scoped μ.
- Testability (activity-only): ≥5 episodes AND ≥10 distinct OOS days → **7 testable / 14 attrition**.
- Tier B (per-trader): day-block bootstrap H0 mean ≤ 0 (B=10k, seed 20260710); BH q=0.10 → **0 significant**;
  economic filter est > 5bp → **0 confirmed**.
- Tier A (basket, PRIMARY): per-day basket alpha = mean over active traders' day-means; day-block bootstrap
  over 117 pooled days → **+1.41bp CI[−10.81,+13.62] p=0.404 MDE=17.45bp (2.8×day-clustered SE)** →
  **INCONCLUSIVE** (frozen rules: CONFIRMED iff CI-low>0 AND est>5bp; EARNED-NULL iff MDE≤8 AND CI-high<8).
- Style attribution: B=1,000; replace each trader's OOS entries with random grid minutes matched to the
  wallet's own hour-of-day (direction kept), TA grid = fwd_ret_h − μ_h(OOS); p_style = 0.429 →
  not distinguishable from structural footprint.
- Output: `data/derived/confirmatory/oos_results.parquet`.

## 7. Caveats of record
- ⚠️ CONTAMINATION: the whole tape incl. the OOS window was explored before the prereg was written —
  results provisional until the frozen protocol re-runs on July-2026+ (untouched) data. Pre-registered
  amendment for that run: loosen discovery to q=0.20 (or S1–S3 only) to grow the basket → basket MDE near care.
- timing_alpha = post-entry price move net of coin drift; NOT realized profit/fees/funding/copyability
  (adversarial profiling showed markout-positive wallets can be net losers or uncopyable makers).
- Exclusions: inherited_basis (backfill), entry_after_close, entry_lag_s>90, HYPE-8h.
- Session context + audit history: memory `babylon-wallet-features-spec`; audits in the 2026-07-08/09 session.
