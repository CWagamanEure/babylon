# OOS-Persistence — Refinement v2: ew/vw · top-N · rolling · distributional (post-audit)

**Status:** v2, post-audit (correctness/leak + discipline). Exploratory layer over the audited base +
sweep. The confirmatory grid is already run and is **inconclusive/underpowered (global p=0.40,
MDE≈160 bp/entry) — NOT a disproof of edge**. This layer *describes* structure across new axes and
carries ONE honest, config-selection-corrected headline; nothing here is called "persists" without
passing §6. `[Cx]`=correctness-audit, `[Dx]`=discipline-audit finding. **Date:** 2026-07-04

---

## 0. Why (each axis answers a shape question the null can't)
The base point-estimate `vw_edge` lean (peaking +31–47 bp @24–48h) **sits inside the top-50-random
null band (p95≈45–88 bp) and is NOT established** `[D-M5]`. This layer asks *what it's made of*:
- **ew vs vw evaluation** — per-decision (ew) vs per-dollar (vw) edge. eb was likely mis-scored
  (ranked equal-weight, graded vw). Score BOTH.
- **top-N (K)** — is any lean a small elite diluted by K=50?
- **rolling vs expanding train** — does ranking on RECENT form beat all-history (which dilutes it)?
- **distributional** — is the point-estimate lean a central shift or a fat-tail artifact?

## 1. Axes & reporting (DESCRIPTIVE — no per-cell significance)
Grid: 7 metrics × 12 horizons × FLOOR_TR{30} × **K∈{10,25,50,100,200}** × train∈{expanding,rolling1}
× eval∈{vw,ew}. Per cell report **S_vw and S_ew** + consistency (# folds positive, # coins positive,
n_active, per-fold picks). **No joint-null p per cell.** Output `refine_grid.parquet`.
**Every figure `[D-M1]` MUST carry, or it is not shipped:** (i) a **random-cohort null band** behind
the curve (per-K on K-sweeps — small K has higher selection variance, so a small-K peak is EXPECTED
under noise `[D-M1]`); (ii) **# folds-positive / # coins-positive / n_active annotated at each plotted
point** (this is how the base's six 168h false-positives were caught); (iii) **≥72h horizons greyed
& labeled "censoring-dominated, non-inferential"** `[D-M2]` and excluded from graduation; (iv) the
header "EXPLORATORY — locating structure, not testing significance."

## 2. ew vs vw scoring (dual, active-only, SYMMETRIC) `[C-M1]`
For the train-selected top-K cohort, **active-only** — a pick that does not trade in the test window
is excluded from BOTH scores (never silent-as-0 in one and dropped in the other); attrition reported:
- **vw** (per-dollar): `Σ te_mkusd / Σ te_notl · 1e4` over active picks, accumulated across folds
  (as `real_S`).
- **ew** (per-decision): a **new** scorer `Σ(active per-wallet te_sumw/te_cnt·1e4) / Σ n_active`
  accumulated across folds — do **NOT** reuse `cohort_ew0_bps` (that is silent-as-0 ÷K, asymmetric
  with vw). Name it `cohort_ew_active_bps`, distinct from `ew0` `[C-M4]`. Assert `notl>0` per entry so
  the active sets (`te_cnt>0` ⇔ `te_notl>0`) coincide `[C-M1]`.
- **Cross-fold aggregation `[C-Q1, D-m4]`:** pool all (fold, active-pick) EQUALLY (un-normalized, like
  vw) — the honest fixed-size-copy analogue; the vw−ew gap then isolates the *within-fold* weighting
  (the point of the contrast). Also report mean-of-fold-means as a secondary (fixed-monthly-cadence
  analogue), and # active picks per fold so a dominant fold is visible.
- **ew is NOT the ranking `avg_edge`** — it's an evaluation target; every ranker is scored on both.
  If a ranker is **ew-positive but vw-negative** → real-but-unscalable (a diagnosis, not a null).

**Verbatim ew caveat wherever ew appears `[D-M3, D-most-important]`:** "An ew (per-decision) edge is
size-blind (pitfall #18) and is at best a ZERO-IMPACT CEILING on fixed-size copy — realizable only if
your clip ≤ the liquidity of every copied trade; the small/illiquid trades that drive an ew lean are
exactly the ones whose edge evaporates when copied at a fundable clip or by many followers into the
same thin book. ew-positive is never a deployability green light — vw + fill-level simulation decide."

## 3. Rolling train mode `[C-M2, C-m1..3, C-m5]`
`rolling1`: for test bucket t, TRAIN = **bucket t−1 only**, test = bucket t, **`FIRST_TEST_ROLLING=1`**
(NOT base's 4 — else folds 1–3 silently dropped) → **10 folds (t=1..10)** for 11 buckets w0..w10.
Same seam/purge (`admit = fin & (bucket==t-1) & (pexit<=test_start)`, `pexit=(⌊(b_ts+h)/BAR⌋+2)·BAR`;
leak-clean, seam-audit-confirmed `[C-ruling]`). Per rolling fold, RECOMPUTE on the rolling-purged
slice: `cap_tr` (winsor; None/no-clip guard fires harder on thin months — flag), `field_std`, μ, τ²,
and the τ²≈0 degenerate-skip; nothing cached from the expanding pass `[C-m2,m3]`. Report per-fold pool
size, attrition, scorable fraction; apply the censoring/scorable-fraction stratum per fold `[C-m5]`;
thin folds (esp high-K, thin coins, long-h) skip+flag, never silently average.

## 4. Top-N sweep `[C-M3]`
Compute `order = rank_desc(...)` **once per fold**, take nested prefixes `order[:K]` — do NOT re-rank
per K. Build-time fold gate on **min(K)=10** (`elig.size < 10` skip), not 50, else K=10/25 cohorts are
lost. Score-time **per-K guard: if `order.size < K` skip+flag** — else `order[:200]` on an 80-wallet
pool silently returns the pool average (≈field) mislabeled "K=200", fabricating a false plateau. A
real lean should decay SMOOTHLY in K (against the per-K null band), not spike at a lone K.

## 5. Distributional analysis (descriptive) `[D-M4, D-m1]`
Default cohorts: **top-50 vw_edge** and **top-10 vw_edge** (elite), expanding. Per (coin,horizon), pool
cohort TRAIN vs TEST markout entries (+ field). **Single frozen cap on BOTH windows** (per-split caps
→ mixture artifact). Report **location (mean, median)** headline; **shape (std, IQR, skew,
p5/p25/p75/p95, tail-loss fraction, win rate) as a DISTRIBUTION OVER FOLDS** (pooling over folds mixes
regimes/composition — flag; shape is fold-mixture, not intrinsic) `[D-m1]`. **Every violin MUST show
(i) the turnover-weighted (deployable) location overlaid `[D-M4a]`, (ii) a random-top-50 median/tail
reference band `[D-M4b]`, (iii) ≥72h greyed non-inferential.** Decomposition: median-persists-while-
mean-regresses (→ central edge + growing tail risk) vs collapse-to-field (→ no edge). **Do NOT propose
stops/caps as a fix inline** — a stop fit to the observed tail is in-sample and is a NEW strategy
(changes exits/fills); at most: "MOTIVATES a separately-OOS-validated tail overlay, not a demonstrated
fix" `[D-M4c]`. Output `refine_dist.parquet` + figures. Verbatim caveat: "Descriptive only — no
multiplicity control, no power; a persistent median is size-blind and is NOT evidence of deployable
edge; confirm via the turnover-weighted null."

## 6. Discipline — pre-committed RULE + config-selection-corrected null (the anti-p-hacking core) `[D-B1]`
Exploration is descriptive; the ONE inferential exit is corrected for the ~8,400-cell selection — a
per-config null does NOT (it ignores that the config was *chosen* for looking best). Therefore:
- **Graduation is a DETERMINISTIC, PRE-COMMITTED RULE** (a human judgment cannot be replayed on
  permuted data; a rule can). Pre-registered rule, per target: **graduate the config maximizing the
  fold lower-bound `mean_folds(S) − std_folds(S)`, over the primary family (non-censored horizon,
  K≤50), ties → lowest horizon → smallest K.** Two pre-registered targets: **vw = primary**,
  **ew = lead-secondary** (pre-registered split, not "at most one" ad hoc) `[D-m3]`. **"Majority of
  folds positive" is DROPPED as a selector** (banned fold-tally, pitfall #18) — fold consistency lives
  *inside* the statistic (the `−std_folds` penalty), not in front of it `[D-B1]`.
- **Config-selection-corrected global null (headline):** reuse the sweep's grid-wide permutation null
  (one persistent random score per wallet per coin); in EACH permutation, compute the whole grid's S,
  apply the SAME rule to pick the permuted winner, record its `mean−std` statistic → the null
  distribution of "the winner of an 8,400-cell scan." `p = P(null winner-stat ≥ real winner-stat)`.
  This is the only p that corrects config-selection. Report it as THE number.
- **Only if the graduated config clears that null** does it face the pre-registered **4-step
  kill-gauntlet** (cell label-shuffle · raw-markout kill-test · n_active/cluster inspection · off-grid
  replication). Only a config clearing null AND gauntlet earns the word "suggestive"; deployability
  still needs vw + fill-level simulation `[D-M3]`.

## 7. Reuse, leak, RAM
Reuse `sweep_tables`/`wallet_agg_ext`/`priced_close_ms`/`cohort_vw`/`rank_desc`; ADD: active-only ew
scorer, rolling window builder (FIRST_TEST=1), per-K nested-prefix scorer, config-selection null.
**Leak (audit-confirmed clean, conditional on rolling recompute `[C-m2,m3]`):** ew reads test
aggregates only; rolling μ/τ²/cap_tr/field_std computed strictly on `bucket==t-1` (pre-test); top-N
only resizes the post-ranking cohort; the sole full-sample quantity is `cap_te` (test outcome,
base-ruled non-leak). RAM: markout once per coin (12 horizons); per-(K,train,eval) is cheap
re-aggregation of cached cohorts.

## 8. Pitfall checklist (build must satisfy)
1. ew active-only ÷ n_active, symmetric with vw, distinct from `ew0`; `notl>0` asserted. ✔ §2 `[C-M1]`
2. Rolling `FIRST_TEST=1`, 10 folds, same-seam purge, all train stats recomputed per fold. ✔ §3 `[C-M2,m3]`
3. K-gate on min(K); per-K `order.size<K` skip+flag; rank once/fold, nested prefixes. ✔ §4 `[C-M3]`
4. Every exploratory figure: per-K null band + folds/coins/n_active annotation + ≥72h greyed. ✔ §1/§5 `[D-M1,M2]`
5. ew = zero-impact ceiling caveat verbatim wherever ew appears. ✔ §2 `[D-M3]`
6. Distributional: frozen cap both windows; shape over-folds; vw location + null band on every violin;
   no inline stops-fix. ✔ §5 `[D-M4]`
7. Graduation = deterministic rule (`mean−std`); config-selection-corrected null is the headline;
   fold-tally dropped as selector; then kill-gauntlet. ✔ §6 `[D-B1]`
8. Hope-leaning phrasing purged; base result carried as "inconclusive/underpowered, not no-edge". ✔ §0 `[D-M5]`
9. Base guards inherited (purge, frozen test cap, determinism, cand2-only). ✔

## 9. Resolved decisions
- Q1 ew cross-fold: pool all active picks equally (primary) + mean-of-fold-means (secondary). ✔ `[C-Q1]`
- Q2 rolling = single prior month (recent-form; thinness/noise flagged). ✔
- Q3 graduation = deterministic `mean−std` rule, replayed in the null (not a judgment call). ✔ `[D-B1]`
- Q4 ew confirmatory null draws from the identical FLOOR-eligible active-only pool, same aggregation. ✔ `[D-m2]`
- Q5 distributional cohorts = top-50 + top-10 vw_edge; null band + vw location on every violin. ✔ `[D-M4]`
