# Issues & Solutions, Part B — Statistical / Engineering Pitfalls and Our Guards

Scope: the methods-hygiene traps that produced *believable-but-wrong* numbers in the markout /
copy-trade work, and the concrete guard adopted for each. The dangerous failures here were not crashes —
they were clean, plausible edges (e.g. +159 bp/RT) and clean "no edge" zeros that were both artifacts.

Sources: memory `babylon-pitfalls.md`, `babylon-markout-study.md`, `babylon-oos-persistence.md`;
`markout_study/docs/FINDINGS_LEDGER.md`; `/Users/corywagamaneure/bablyon/CLAUDE.md` (the over-nulling / over-carry gate).

---

## FACTS (problem → fix → outcome)

### 1. Survivorship / selection bias
- **Problem.** Selecting the universe on a whole-period *survivor* pool inflates edge — wallets that
  blew up or went quiet are silently dropped, and the survivors look skilled by construction.
- **Fix.** Select the universe using only data through time *k* (rolling / past-only), never frozen;
  gate eligibility on **raw activity**, not on closed-round-trip count (the latter re-introduces a
  survivorship flavor). Hold out leading unobserved-open positions and mark-to-market dangling
  positions at the cutoff. (pitfalls #1, #6, #10, #11; commit fe44463)
- **Outcome.** The headline +159 bp/RT survivor number fell to **~+40–92 bp/RT** on a past-only rolling
  universe. In Stage J, a `nteT≥20` closed-count filter was shown to drop ~40% of wallets and keep
  train-winners (kept +21bp vs dropped −8bp train-median) — i.e. it can *manufacture* positive
  train→test rank correlation. (`babylon-pitfalls.md`; ledger Stage J)

### 2. Winner's-curse / multiple comparisons across ~1,765 in-sample candidates
- **Problem.** Ranking wallets on an in-sample metric and reading the top as "edge" is winner's curse:
  with ~1,765 "stable" in-sample candidates and ~10,000 hypotheses across the whole arc, the survivor
  rate sits **at the ~5% noise floor** — the winners are mostly selection noise, not skill.
- **Fix.** Report only out-of-sample, multiplicity-controlled numbers. Use a **held-out winner's-curse
  measurement** (select each wallet on its best *in-sample* horizon, then score OOS), BH-FDR across the
  cell grid, and a **config-selection permutation null** (permute identities keeping the real
  metric rankings, take the max over the whole config space). Never quote an in-sample figure as a result.
- **Outcome.** Held-out means for the ~1,765 in-sample candidates were **−11 to −48 bp** (mostly
  selection noise). Per-wallet winner's-curse held-out = **−28.7 bp NET pooled OOS**
  (BTC −20 / ETH −36 / SOL −46; `out/eda_winnerscurse.parquet`) → past markout is *anti*-predictive per
  wallet. Of 75 OOS cells, 6 cross raw p<0.05 but **0 survive BH-FDR**; config-selection null p=0.17
  (vw) / 0.26 (ew), both with negative winner stats → **nothing graduates**. Registered as a
  method-scoped NEGATIVE for performance selection specifically.
  (`babylon-markout-study.md`, `babylon-oos-persistence.md`, ledger)

### 3. Look-ahead / lag (leakage)
- **Problem.** Pricing an entry with the candle that *contains* it (or with the wallet's own sub-second
  fill) leaks future information; benchmarking against a window that starts *before* the entry
  manufactures two-sided "skill"; and splits leak when a priced exit crosses the train/test seam.
- **Fix.** Price at the last **fully-closed** candle (`_close_at` / leak-free `_next_bar_close_vec`),
  and price round-trips at the **follower's lagged entry** (candle close at fill_t + lag), not the
  wallet's fill. Only count RTs fully closed **before T0** (`before_ms`). Any counterfactual/benchmark
  must be **measurable-at-entry** (windows start ≥ entry time or are state-matched). Walk-forward splits
  use a **purged/embargoed** design: drop any train entry whose priced 168h exit crosses the test seam,
  measured against the *actual* next-bar-close time `(t//BAR+2)*BAR`, not nominal `b_ts+h`. Freeze
  selection on train-only; drop insufficient-coverage wallets at *evaluation* as attrition (a
  test-activity filter `te_nd≥15` in **selection** silently inflated a positive).
  (pitfalls #2, #4, #5, #16; OOS memory; ledger M1)
- **Outcome.** The backward-peeking "majors-timing" skill (z = +3.86) collapsed to zero on the raw
  copyable quantity — it was benchmark contamination. In M1, moving `te_nd` out of selection changed
  Family B from "+7.9 beats fade" to **+1.5 EW / −2.0 pooled (p=0.44–0.63, 0/12 RW)** — the
  fade-beating was a selection-leak artifact. Kill test adopted as standard: score any selected roster
  on the plain post-fill markout; artifacts collapse there.

### 4. Gross vs net (realistic Hyperliquid cost)
- **Problem.** `sel − field` cancels a constant round-trip cost, so an "edge-over-field" is NOT a
  deployable P&L; and size-blind (equal-weight / median / %-profitable) metrics flatter an edge that
  actually lives in small, unfundable trades. Early work also used an inflated 8–14 bp cost.
- **Fix.** Quote the **selected return net of realistic cost** at the deployed operating point; report
  the **turnover-weighted (capital-weighted)** return and aggregate dollars, not just equal-weight mean.
  Realistic HL round-trip is **~5–6 bp** (fee 3.5–5 bp + half-spread; a scheduled 4h/8h exit can rest as
  a maker), NOT 8–14 bp. Stress-test across cost tables. (pitfalls #3, #18; ledger agent #6)
- **Outcome.** All field-level drifts (BTC/SOL bleed, ETH flat, HYPE +3.5bp@8h hump, SPX/ALT early pop)
  are **below the ~5–6 bp round-trip → not field-level copyable**. The M1 "+3.75bp" basket rode an
  optimistic 5/5/8/8 cost table; at realistic (8/8/10/14) cost it was **+0.20 bp, p=0.50**. The Stage-H
  consensus lead survives cost only because followers dip-buy (favorable fill, real crossing ~2.8bp).
  A Stage-J consistency screen was significant equal-weight (perm p=0.001) but NOT turnover-weighted
  (p=0.08) — the winning trades were too small to fund.

### 5. Polars OOM + tuple-key regression on the 8GB box
- **Problem.** (a) Non-streaming `.collect()` on ~1GB+ parquet OOMs the 8GB Mac (2 crashes; 3.3GB
  tape); polars 1.42 has no partitioned sink. (b) `partition_by(as_dict=True)` in polars 1.x keys by a
  **tuple** `('0x…',)` not the bare string → silent `elig=0`, a clean "no edge" zero. Full-month
  reshapes swap.
- **Fix.** Use `engine="streaming"` / `sink_parquet`, run **one heavy polars/parquet job at a time**,
  pre-split per-wallet once then sweep cheap, and cap batches (BATCH ≤ 150, streaming). `ramguard.sh`
  (`POLARS_MAX_THREADS=3`, abort < 800MB free). **META-GUARD:** validate any pipeline on a
  known-answer single-wallet probe before trusting an aggregate — *especially* a clean zero. Read-only
  audit agents cost ~0 local RAM (models run server-side). (pitfalls #12, #13; markout memory RAM lesson)
- **Outcome.** 7,332,013-row entry build and all stage priced-cohort jobs run locally without OOM;
  the tuple-key regression is caught by the single-wallet probe (`src/probe.py` known-answer fixtures)
  before any aggregate is trusted. OOM was the root cause of the earlier Stage-J crash that had left the
  maker/taker filter unrun.

### 6. Day-block bootstrap + Romano–Wolf for non-independent, overlapping trades
- **Problem.** Trades within a wallet, and overlapping-horizon markouts within a day, are correlated —
  naive per-trade CIs are far too tight, and a "majority of N splits / 8-of-10 months positive" tally
  treats non-independent cohorts as independent trials. A max-over-many-wallets survivor hunt also needs
  a family-wise correction or it manufactures false winners.
- **Fix.** Cluster the resample at the right unit: **wallet-cluster bootstrap** (resample wallets, not
  RTs); **coin-day / day-block bootstrap** for overlapping trades (N_effective = distinct **days**, not
  episodes); **Hansen SPA omnibus → Romano–Wolf stepdown max-t** for the per-wallet survivor family;
  and a **persistent-random-score permutation JOINT null** in place of split-tally counting ("beats
  random" compares to the random *distribution*, never its mean). (pitfalls #8, #18; ledger Stage M/M1/M2)
- **Outcome.** The framework is powered where it can be and honest where it can't: Stage M2 decile
  L-S = **+14.37 day-block [+8.15, +20.12], p<1e-4**; the M1 top-20 basket CI is **±11–17 bp** (a wide,
  not tight, band → underpowered, not zero). Stage M's per-wallet SPA/RW test was shown **blind by
  construction** on the 122-day window (median MDE_RW = 33 bp > care-about; correlation-aware max-t
  hurdle 4.78; the "222 powered wallets" were a BTC β=1 residual-degeneracy artifact) → we did **not**
  build the survivor hunt, avoiding a by-construction over-null.

### 7. The over-nulling gate (point + CI + MDE + cross-unit) and its over-carry mirror
- **Problem.** A recurring bias toward calling underpowered results "null / no effect / dead," which has
  repeatedly buried real signals — because every rigor tool (permutation nulls, FDR, kill-gauntlets)
  targets false positives, so "not significant" is the safe drift. The *mirror* hazard (over-carry) is
  real too: carrying a post-hoc argmax residual that only lives in the uncontrolled descriptive layer
  as a "live positive."
- **Fix.** A null verdict must **earn the word**: it requires all four of (1) point estimate + CI (not a
  p-value; if the CI still admits the care-about effect it is *inconclusive*), (2) a positive-control
  **MDE ≤ care-about** (the pipeline must be *shown* able to recover an injected edge of the relevant
  size), (3) a **cross-independent-unit sign/aggregate test** (coins/folds/wallets leaning the same
  way), and (4) a construction-conservatism check (null band not built against the finding). Anti-ratchet:
  if a design is structurally blind, the obligation is to build a *powered* design, not re-run the blind
  instrument and relabel "inconclusive." Symmetric over-carry guard: a post-hoc-selected, error-controlled-
  layer-silent, deployment-cut-at-chance residual is **DEMOTED to "unresolved residual, direction
  unknown,"** not carried as a positive. Run BOTH a separate-agent "steelman the positive" pass AND a
  "prosecute the positive / null the residual" pass before finalizing. (CLAUDE.md; `babylon-overnulling-gate`)
- **Outcome (both directions exercised).**
  - *Over-null caught:* the baseline OOS null was corrected from "no edge" to **INCONCLUSIVE** —
    point estimates lean positive on 4/5 coins (BTC +31, HYPE +45, SOL +13, SPX +35; ETH −41), none
    significant (min p=0.09), and MDE = **160 bp/entry** means the test is *blind* to any realistic
    single-to-low-double-digit-bp edge. Stage M0 "negative" → "blind"; Stage L DIR-mrev "negative" →
    "inconclusive"; M4 day-capped **+5.87** is carried as a live underpowered positive (window
    MDE ~11–16bp ≫ ~5bp care-about, +5bp injection undetected).
  - *Powered negatives that EARNED the word:* performance-based wallet selection = a **registered
    negative** (winner's-curse −28.7bp OOS; train→eval rank Spearman ≈ 0, a tight null on the
    load-bearing quantity); and the raw directional persistence = **−0.03, a powered/earned null**
    (the *same* pipeline detected the neutralized +0.61, so it is not blindness).
  - *Over-carry caught:* the "24h / small-K coherent positive" was **demoted** to "unresolved
    residual" (24h = argmax of 12 horizons; K=50 breaks it; coins non-independent; lives only in the
    uncontrolled layer). The M2 recurrence "3.2×" transition story was cut to **1.09× (p=0.22)** after
    a shrinkage-collapse bug; the surviving persistence is small-but-real (IC 8h +0.093, fwd-decile
    +4.5), and its +14bp gross is captured by a costless robot fade at the same entries → generic
    reversal, wallet-skill-as-such **not supported**.

---

## FIGURES-TO-MAKE (optional)
- **Winner's-curse fan:** in-sample candidate mean vs OOS held-out mean (the ~1,765 candidates
  collapsing to −11…−48 bp) — the single clearest "selection noise" visual. (from `eda_winnerscurse`)
- **Cost-ladder bar:** the same basket's net edge across cost tables (0 → 5/5/8/8 → 8/8/10/14 bp),
  showing the +3.75 → +0.20 collapse — makes "gross vs net" concrete.
- **MDE vs care-about panel:** per-test positive-control MDE (160 bp baseline, 33 bp Stage-M RW,
  11–16 bp M4) against the ~5 bp care-about line — visualizes "blind by construction."
- **CI-vs-zero forest:** point + CI for the load-bearing quantities (raw persistence −0.03 tight;
  M1 basket ±11–17 wide; M2 decile L-S +14.4 excl-0) — separates *earned* nulls from *inconclusive*.

## GAPS
- Exact commit hashes for the markout_study guards (probe/ramguard) not confirmed here; only the
  copy-trade-era commits (fe44463 eligibility, 9ddf901/11a249d dangling, 11a249d) are on record in
  `babylon-pitfalls.md`.
- The precise *count* behind "~1,765 in-sample candidates" and its selection criteria live in the EDA
  notebook (`notebooks/markout_findings.ipynb`) / `out/eda_winnerscurse.parquet`; not re-derived here
  (RAM rules: no tape scan).
- BBO-cost calibration is deferred — the ~5–6 bp round-trip is a fee + half-spread estimate; `net_exec`
  is an acknowledged **upper bound** until real BBO spreads are joined.
- The Romano–Wolf / SPA machinery is *specified and power-gated* for the per-wallet family but was
  deliberately **not run as a survivor hunt** (blind on 122 days) — resolution is gated on forward
  paper-accrual (Stages M/forward-experiment), not on this historical window.
