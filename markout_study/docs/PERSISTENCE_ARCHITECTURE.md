# OOS Persistence Test — Architecture v2 (post-audit)

**Status:** v2 — revised after a 3-agent audit (look-ahead, statistics, pitfall-regression). Two
BLOCKERS (boundary-bleed purge; dependent-splits verdict statistic) and two required additions
(positive control / MDE; cluster-aware null) are folded in. `[Fx]` tags cite the source finding.
**Date:** 2026-07-04

---

## 0. Goal
Document, with report-grade numbers, the **baseline out-of-sample persistence of naive taker
rankings**: rank wallets by a simple metric on a PAST window; does their deployable edge persist on
a FUTURE window? One verdict per (coin, metric, horizon). This is the null model the later feature
work must beat. Expected result: naive rankings do NOT persist — but the deliverable is the
documented evidence *either way*, and (critically) a **power statement** so a null can't be
dismissed as "too thin to tell." `[stats-B2]`

Out of scope: feature→edge modeling; anything ranking on the future.

---

## 1. Data & reuse
- Source: `out/entries/part_*.parquet` (7.33M taker entries) + `bars_*`. No new data.
- **Reuse the EXACT `markout_stats` per-metric aggregation, windowed** — do NOT re-derive.
  `sharpe = winsorized-mean / RAW-std`; `avg_edge` = winsorized mean; `vw_edge = Σmk_usd/Σnotl`.
  `[pitfall-F1: re-deriving would drift from the full-sample table.]`
- **Markout is entry-intrinsic** (exit price fixed at `b_ts+h`; only the winsor cap is
  window-dependent). Compute raw markout **once per coin** for the 3 horizons, cache `(n,3)`, then
  per split just slice by `b_ts` and apply the split-appropriate cap. Faster, RAM-light, no
  re-pricing drift. `[pitfall-F5, F7]`

---

## 2. Windows & splits (walk-forward, TRUE future, PURGED)
- 11 × ~30-day buckets `w0..w10` by `b_ts`.
- Expanding-train / one-bucket-forward-test: for TEST `t ∈ {w4..w10}`, TRAIN = `w0..w(t-1)`. **7
  splits.** (A rolling fixed-4-bucket train is the robustness variant — less cross-split overlap.
  `[stats-M5]`)
- **PURGE / EMBARGO (BLOCKER fix).** A train entry is admitted to the ranking at horizon `h` **only
  if its PRICED exit bar closes before the test window**: `(floor((b_ts+h_ms)/BAR_MS)+2)·BAR_MS ≤
  T0(test bucket)`. NB the embargo is against the *actually-priced* bar-close time, NOT the nominal
  `b_ts+h_ms` — `_next_bar_close_vec` prices at the close of the first bar starting strictly AFTER
  the endpoint, i.e. up to ~2 bars (~10 min) later, so the nominal test would still admit a
  post-T0-priced entry. `[confirm-item-1]` Otherwise the train entry's exit price is drawn from
  *inside* the test window and the same post-boundary path drives BOTH the train metric AND the test
  edge → manufactured positive persistence. `[look-ahead-BLOCKER-1]` The purge is **horizon-specific**
  (the admitted set differs for 4h/24h/168h); the train winsor cap is recomputed on each horizon's
  **purged** set. If a purged pool has `<100` finite points `winsor_cap` returns None (no clip) —
  guard/flag (bites only thin SPX). `[confirm-estimator-trap]`
- Per coin: BTC, ETH, SOL, HYPE individually (SPX reported only if it clears floors). 168h
  right-censoring bites materially only in the **final split** (w10 has no w11 bars); earlier splits'
  test exits price fine from later buckets. Report scorable fraction; **separate "censored" from
  "inactive."** `[look-ahead-MINOR-2, stats-m1]`

---

## 3. Ranking metrics × horizons (pre-registered)
Rank on TRAIN (purged) at a **fixed** horizon (never re-picked OOS). Five DISTINCT rankings
(`net_exec = vw_edge − constant cost` → identical rank order, so it is a *level readout* on the
vw ranking, not a 6th ranking `[stats-m2]`):

| ranking | train-window definition | role |
|---|---|---|
| **vw_edge** | Σmk_usd/Σnotl·1e4 | deployable — PRIMARY |
| avg_edge | winsorized mean mk_bps | size-blind contrast (#18) |
| sharpe | winsor-mean/raw-std | consistency |
| hit_rate | mean(mk_bps>0) | consistency |
| cum_pnl | Σ mk_usd | magnitude (size-biased, for contrast) |

Horizons {4h, 24h, 168h}. **PRE-REGISTERED PRIMARY CELL = `vw_edge @ 24h`** — the headline; the
rest is a secondary grid, so the report isn't an eyeballed max over the surface. `[look-ahead
tightening]` Winsor: **train metric → train-purged p99 cap**; **test outcome → frozen full-sample
cap** (stable, symmetric, applied identically to cohort AND null — not a leak `[stats-m4, Q4 cleared]`).

---

## 4. Cohort measurement (per split)
Pool = wallets with **≥ FLOOR_TR (=30) purged-train entries** in the coin. Rank descending, **tie-break
ascending wallet-id** `[pitfall-F6]`. Cohorts: **top-50** (+ top-100, top-1% robustness `[stats-m5]`).

**Cohort edge = ACTIVE-ONLY volume-weighted deployable edge** (copy-simulation semantics: you only
place a trade when the picked wallet trades, so a wallet silent in the test window is costless and
weightless — no survivorship because selection is train-only). State this plainly; stop calling it
"=0." `[stats-M4]` Report **EW-with-silent-picks-as-0 separately** (the size-blind reading where the
0-penalty genuinely bites). Also record raw **Σmk_usd, Σnotl, n_active, attrition** — not just bps.
`[pitfall-F4]`

**Within-split CI:** a **cluster-robust bootstrap** on the top-50 cohort edge (resample **clusters**,
not wallets, per pitfall #8). **Co-trade clustering rule (pinned):** two wallets are co-traders if
their (bar, direction) entry sets overlap with **Jaccard ≥ 0.5**; connected components collapse to
one bootstrap unit. Report the cohort's **cluster count** so a clustered win is visible.
`[pitfall-F3, look-ahead-MAJOR-1, stats-M2, confirm-item-4]`

**Thin-split handling:** if a split's purged pool has `< K` eligible wallets, top-K = whole pool =
null top-K → the split gives no discrimination; **skip it and flag** (do not silently average in).
`[confirm-newissue]` **Recompute everything on the per-split purged slice** — never read the
persisted `markout_stats.parquet` rows (its `keep`/`n_eff` are full-sample). `[confirm-estimator-trap]`

**Decile profile:** full 10-decile mean edge + a **monotonic-trend test** (slope of decile-mean-edge
on rank), not a fragile 10-vs-1 contrast. `[stats-M3]`

---

## 5. THE VERDICT STATISTIC — persistent-random-score permutation JOINT null (BLOCKER fix)
"# splits beating random" is a **tally over non-independent trials** (splits share wallets, use
overlapping expanding train, adjacent-month test) — the exact fallacy the registered verdict bans.
`[stats-B1, pitfall #18]` Replace it with a **joint** null:

1. Real statistic `S`: for a (coin, metric, horizon), the **turnover-weighted mean top-50 deployable
   edge across all 7 splits** (one number). `[stats-M5]`
2. Null: assign each wallet ONE persistent random score (same across all 7 splits — preserves the
   wallet-sharing + train-overlap dependence). Rank each split's pool by that score, take top-50,
   measure test edge, aggregate identically → `S_null`. Repeat **R=1000** → joint p = P(`S_null ≥ S`).
3. Persistence verdict for a cell = **joint p < 0.05 AND S > 0.** The **primary cell (vw_edge@24h)
   is pre-registered and protected**; declaring persistence in any **secondary** grid cell requires a
   **Benjamini-Hochberg FDR** control across the ~60 secondary cells (or an explicit expected-FP
   count) — at 5% raw, expect ~3 spurious cells. `[confirm-newissue]` Report the independence FP floor
   (P(≥4/7 at p<.05 | noise, independent) ≈ 1.9e-4/cell) as context. The per-split random baseline
   stays a descriptor only.

**Report the full percentile / lower tail too** (the field is anti-informed ~−14bp/entry, so
anti-persistence must be visible), even though the headline is one-sided. `[stats-m3]`

---

## 6. Power / positive control (REQUIRED — this is a clean-zero deliverable) `[stats-B2, pitfall #13]`
- **Positive control:** add a fixed +Δ bps to a random subset of wallets' per-entry markout
  **pre-winsorization** (so the cap attenuates it as it would a real signal) in **both** train and
  test; confirm the injected set ranks top, the joint null lights up (p<0.05), and the recovered
  cohort edge ≈ Δ (attenuated). `[confirm-item-3]`
- **Negative control (structure-preserving):** **permute wallet labels on the real entries** (keep
  real price paths / entry times), NOT synthetic Gaussian noise — only a structure-preserving null
  can surface a residual seam leak (item-1) in its FP rate. Confirm the joint null's false-positive
  rate is calibrated (~5%). `[confirm-item-3]`
- **MDE:** sweep Δ down to the smallest true top-50 deployable edge detectable at ~80% power in the
  joint null; report it in bps.
- **Interpretation guard (verbatim in the output):** *"This test detects a true top-50 deployable
  persistence edge of ≥ [MDE] bps at ~80% power in the joint permutation null; a null result means
  persistence, if any, is below that bound — NOT that the data is too thin to measure."*

**Spearman is a DIAGNOSTIC ONLY, never the verdict.** It is survivor-conditioned (computed over
≥FLOOR_TE test-active wallets) and can *flatter* (survivors are the committed wallets), while
FLOOR_TE=10 *attenuates* it toward 0 (reliability ~0.15-0.25 → ~40-50% of truth). Report: raw
Spearman, a **split-half reliability** and **disattenuated** value, a **cluster-bootstrap CI**, and a
**FLOOR_TE≥20 robustness subset**. `[stats-M1, M2, look-ahead-MINOR-1]`

---

## 7. Output
`out/persistence_stats.parquet` — per (coin, metric, horizon, split): cohort vw edge (active-only) +
EW-with-0, Σmk_usd, Σnotl, n_active, attrition, censored-vs-inactive counts, decile slope, Spearman
(+reliability/disattenuated), within-split cluster-bootstrap CI.
`out/persistence_verdict.parquet` — per (coin, metric, horizon): joint-null `S`, joint p, verdict,
MDE, plus the primary-cell headline. Plus a controls report (positive/negative/MDE).
Determinism: seeded permutation RNG; sorted reductions; fixed split/tie-break defs.

## 8. Pitfall checklist (code must satisfy)
1. Purged walk-forward — no train markout crosses the test seam; train caps on purged set. ✔ §2
2. Verdict = joint permutation null (dependent-split-safe), not a tally. ✔ §5
3. Positive/negative control + MDE + interpretation guard. ✔ §6
4. Cohort = active-only vw deployable (copy-sim), EW-with-0 secondary; aggregate-$ logged. ✔ §4
5. Cluster-aware CI + cohort cluster diagnostic; null respects wallet identity. ✔ §4/§5
6. Spearman diagnostic-only, disattenuated + reliability + robustness floor. ✔ §6
7. Metric defs reused from markout_stats (no drift); note window-cap level difference. ✔ §1/§3
8. Horizon fixed; single pre-registered primary cell. ✔ §3
9. Right-censoring: separate censored/inactive; report scorable fraction. ✔ §2
10. Deployable AND size-blind both reported. ✔ §4
11. cand2-only source; RAM-safe cached-markout loop; determinism + tie-break. ✔ §1/§7

## 8b. RESULTS (run 2026-07-04, all 5 majors, code audited)
**Verdict: naive rankings do NOT persist out-of-sample.**
- **Primary pre-registered cell (vw_edge@24h):** joint-null p = 0.09 (BTC), 0.15 (SPX), 0.18 (HYPE),
  0.42 (SOL), 0.78 (ETH). None < 0.05. Cohort edges +12 to +45 bp — all inside the top-50-random
  null (p95 ≈ 45–88 bp) and below cost. Spearman ≈ 0 (−0.03 … +0.05) for every coin.
- **Full grid (75 cells):** 6 cross raw p<0.05 & S>0 — **all at 168h**, and **0 survive BH-FDR.**
  Inspected: the 168h cells have only 6–15 active wallets per top-50 pick and are driven by 1–2
  splits (ETH vw@168h: +281 bp from buckets 5–6 alone; final split fully right-censored, 0 active).
  Low-N × right-censoring noise, correctly killed by multiplicity control.
- **Power (BTC primary, controls):** negative control (label-shuffle) FP = 5% (calibrated); positive
  control detects **MDE = 160 bp/entry** at 92% power (0% at ≤80 bp; 100% at ≥320 bp; recovered edge
  saturates ~850 bp at the winsor ceiling). **Interpretation:** the test would catch a persistent
  per-entry edge ≥160 bp; realistic edges are single-to-low-double-digit bp, so naive top-50 ranking
  is **noise-limited** — the 30-entry selection variance swamps any realistic persistence. A null
  here means persistence (if any) is below 160 bp/entry, NOT that the data is too thin.
- **Bottom line for the feature work:** the baseline null model is established. Ranking by raw
  edge/Sharpe/hit/cum is not a viable selector at this evidence depth; a feature must beat this
  (near-zero, noise-limited) baseline to matter.

## 9. Resolved decisions
- Q1 floors: FLOOR_TR=30, FLOOR_TE=10 (cohort) + ≥20 robustness (Spearman); K=50 (+100/1%). ✔
- Q2 expanding-train primary, rolling-4 robustness. ✔
- Q3 active-only vw cohort (copy-sim), EW-with-0 secondary; null byte-identical. ✔
- Q4 test outcome uses frozen full-sample cap (not a leak; stable). ✔
- Q5 top-50 + top-100 + top-1%. ✔
- Q6 per-coin primary; majors-pooled optional. ✔
