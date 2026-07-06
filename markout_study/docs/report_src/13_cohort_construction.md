# 13 — Construction of the 121-wallet canonical cohort

Scope: the exact, step-by-step recipe that produces the ONE frozen canonical recurring
top-decile cohort, why each choice was made, the resulting counts, and the recurrence-vs-luck
significance. Sources: `src/cohort_M_freeze.py`, `docs/FINDINGS_LEDGER.md` ("Canonical cohort
freeze", lines 608–612; Stage M2 recurrence, lines 500–529), memory `babylon-markout-study`,
and a light read of `out/cohort_M_frozen.parquet` (1,693 rows).

---

## FACTS — the step-by-step recipe (sourced to `src/cohort_M_freeze.py`)

**Input universe.** `out/cohort_K_entries.parquet` — the priced taker entries of the Stage-K
universe: **1,694 mid-frequency copyable-taker wallets** (taker_share ≥ 0.7 AND median hold
∈ [1h, 24h] AND n_train ≥ 200 decisions; `out/cohort_K.txt` = 1,694 lines). Columns read:
`wallet, coin, b_ts, dir, notl, neut_8h`. No bars are read — everything is reproducible from
the parquet. (`cohort_M_freeze.py:15`)

**Step 1 — TRAIN-ONLY filter.** Keep only entries with `b_ts < TRAIN_HI_MS` where
`TRAIN_HI_MS = 1_769_904_000_000 = 2026-02-01`. This is the train/test boundary: the 6 TRAIN
months are **Aug 2025 → Jan 2026**, **Feb 2026 is an embargo month**, and **test is Mar 2026+**.
No test or embargo data enters the freeze. Each entry is tagged with its calendar `month`
(`%Y-%m`) and integer `day` (`b_ts // 86_400_000`). (`cohort_M_freeze.py:12,16-19`)

**Step 2 — day-weighted signal per wallet-month.** Two-stage average so no single busy day
dominates a wallet's month:
- `wmd`: group by (wallet, month, day) → `d8 = mean(neut_8h)` = that wallet's mean drift-stripped
  8h markout on that day.
- `wm`: group by (wallet, month) → `m8 = mean(d8)` (equal weight per active day) and
  `nd = count of active days`. (`cohort_M_freeze.py:22-23`)

**Step 3 — eligibility gate.** Keep only wallet-months with `nd >= MIN_D = 8` active days.
A wallet-month with < 8 trading days is not ranked (too thin to rank fairly).
(`cohort_M_freeze.py:13,23`)

**Step 4 — per-month top-decile flag + continuous percentile.** For each of the 6 train months
independently:
- threshold `thr = quantile(m8, 1 - DEC)` with `DEC = 0.10` → top 10% of eligible wallets that
  month.
- `top = 1` if `m8 >= thr` (monthly top-decile flag).
- `pctile` = fraction of that month's field the wallet beats (1.0 = best) — a continuous
  within-month rank. (`cohort_M_freeze.py:27-32`)

**Step 5 — recurrence aggregation across the 6 months.** Group by wallet →
`n_elig` (# eligible months), `n_top` (# months in the top decile), `conv = mean(pctile)`
(continuous conviction = average monthly percentile). (`cohort_M_freeze.py:34`)

**Step 6 — behavioral traits (train-only, pre-specified).** Per wallet over all train entries:
`notl_med`, `notl_mean` (trade size), `dir_bias = mean(dir)` (long/short lean), `n_entries`,
`n_days`, `n_coins`. Joined onto the recurrence table. (`cohort_M_freeze.py:36-40`)

**Step 7 — cohort definition and freeze.** A wallet is "recurring" if top-decile in
`>= K` eligible train months:
- **PRIMARY = K_PRIMARY = 2** → the canonical **121-wallet cohort** (top-decile in ≥ 2 of 6).
- **STRICT = K_STRICT = 3** → 28-wallet subset (top-decile in ≥ 3 of 6).
- Label column `cohort` ∈ {strict (n_top≥3), primary (n_top==2), none}.
Sorted by `(n_top, conv)` descending. Written to `out/cohort_M_frozen.parquet` (full table,
1,693 wallets with traits + conviction) and `out/cohort_M_frozen.txt` (the 121 PRIMARY wallet
addresses + a 2-line header). (`cohort_M_freeze.py:13,42-54`)

### Why each choice

- **Why `neut_8h`?** It is the drift-stripped (coin-month-neutralized) 8h markout, already
  computed in the parquet (no bar pricing / RAM blowup). 8h is the empirical peak of the
  persistence term structure (Stage M2 agent #10: 8h rank-IC +0.219 [+0.154,+0.282], monotone
  1h→8h) — the most-detectable horizon. Drift-stripping removes the shared coin move so the
  signal is wallet-relative, not "was long BTC in an up month."
- **Why TRAIN-only?** Leak-free construction. Audit round-3 found the cohort had been silently
  re-derived three different ways downstream (see below); freezing on train-only data — Feb
  embargoed, Mar+ untouched — guarantees the selection can never see the evaluation window.
- **Why day-weighted (Steps 2)?** Wallets over-trade their worse days (Stage M1: entry-weighted
  train→test IC = −0.055 vs day-weighted +0.16). Equal-capital-per-wallet-day is the only
  weighting under which the ranking persists, so the signal must be built that way.
- **Why eligibility ≥ 8 active days?** A monthly rank on < 8 days is dominated by a handful of
  fills; 8 days is the floor at which a wallet-month is a fair sample of behavior.
- **Why recurrence ≥ 2 (not a single-month top-decile or a top-N PnL cut)?** Single-month
  top-decile is mostly luck; requiring the SAME wallet to re-appear in the top decile across
  independent months is a persistence test, which is the property we actually want. The frozen
  top-20-by-PnL basket (Stage M1) was a blind, underpowered instrument; recurrence over the
  whole decile is the powered diagnostic (Stage M2). K=2 is PRIMARY for N (121, usable for
  behavioral/model work); K=3 (28) is the higher-conviction strict subset.
- **Why frozen-to-disk (the "3-conflated-cohorts fix")?** Before the freeze, three different
  "top-decile" sets were floating around and being re-derived inline by different scripts:
  **recurrence-over-all-11-months = 686**, **deploy-path (leaked) = 99**, **train-only = 170**.
  These disagreed and some leaked test data. Writing ONE canonical list to
  `out/cohort_M_frozen.{txt,parquet}` means M-phase, Phase-1 (behavioral), Phase-2 (nested
  models) and Phase-3 (forward spec) all read the identical 121 wallets — no more inline
  re-derivation, no more conflation. (Ledger 609–612)

### Counts from `out/cohort_M_frozen.parquet` (light read, threads=2)

Recurrence funnel (distinct wallets by # top-decile months):

| n_top (top-decile in ≥ K of 6 train months) | wallets |
|---|---|
| ≥ 1 | 496 |
| **≥ 2 = PRIMARY (canonical)** | **121** |
| **≥ 3 = STRICT** | **28** |
| ≥ 4 | 5 |
| ≥ 5 | 0 |

Exact distribution: n_top = 0 → 1,197; 1 → 375; 2 → 93; 3 → 23; 4 → 5. (121 = 93 + 28; the
frozen table holds all 1,693 wallets that were eligible in ≥ 1 train month, with the 1,572
non-recurring labeled `none`.) Funnel: **1,694 universe → 1,693 eligible-≥1-month → 496 (≥1
top-decile) → 121 PRIMARY (≥2) → 28 STRICT (≥3).**

### Cohort trait medians (train-only)

| trait | PRIMARY (121) | STRICT (28) | ALL frozen (1,693) |
|---|---|---|---|
| notl_med (per-wallet median trade $) | $4,053 | $2,737 | $3,945 |
| notl_mean (median) | $6,318 | $4,745 | $6,442 |
| dir_bias (mean; +1=all long) | +0.36 | +0.55 | +0.31 |
| n_entries (median) | 268 | 296 | 290 |
| n_days (median) | 79 | 82 | 69 |
| n_coins (median) | 4 | 4 | 3 |
| conv = mean monthly percentile | 0.73 | 0.80 | 0.50 |

Read: the cohort is small-size (~$4k median trade), moderately long-biased (stronger long-lean
in the strict subset, +0.55), active (~270 entries / ~79 days / 4 coins over train), high
conviction (mean percentile 0.73 vs 0.50 field). Behavioral follow-up (Phase 1) shows these are
aggressive **contrarian faders** (signed 8h return in trade direction median −86 bp vs −12 for
ordinary wallets) — their "edge" is the mechanical short-horizon fade done harder.

### Recurrence vs luck-null (corrected numbers — the significance of the cohort)

From Stage M2 after the James-Stein shrinkage-collapse bug fix (Ledger 505–514; the bug had
inflated counts ~10–22× by flagging 100% of wallets top-decile in 4/11 months):

| threshold | observed recurring | luck-null expected | p |
|---|---|---|---|
| ≥ 4 months | 9 | 5 | 0.066 |
| **≥ 3 months** | **48** | **35** | **0.017** |
| ≥ 2 months | 204 | 184 | 0.059 |

Only the **≥ 3-month cut clears significance (48 vs 35, p = 0.017)**; ≥2 and ≥4 are marginal.
(Pre-fix inflated values were 403 / 686 / 1107.) Note these M2 counts are over all 11 months
and use a slightly different ranking than the frozen file's 6-train-month cut (hence 48 vs the
frozen 28 at ≥3mo), but the qualitative message is identical: recurrence beyond chance is
**small, real, and only clearly significant at the ≥3-month / higher-conviction end.** The
persistence is corroborated (not just by counts) by the load-bearing adjacent-fold rank-IC
(8h +0.093 [+0.061,+0.126], 10/10 folds, p=0.002) and forward top-decile edge +4.48 bp
[+2.17,+7.54]. Over-carry caveat: this is GROSS drift-stripped markout, not net-of-cost and
not vs the mechanical fade — much of it is generic short-horizon reversal, so a recurring
cohort ≠ deployable wallet skill (resolved only by the Phase-3 forward experiment).

---

## FIGURES TO MAKE

1. **Recurrence-count vs luck-null bar chart.** Grouped bars at thresholds ≥2 / ≥3 / ≥4 months:
   observed (204 / 48 / 9) vs luck-null expected (184 / 35 / 5), annotate p = 0.059 / **0.017** /
   0.066. Highlight ≥3mo as the only clearing bar. (Source: Ledger 513–514.) Optionally overlay
   the frozen-file 6-month cut (≥2=121, ≥3=28, ≥4=5) as a second panel and note the
   all-11-months vs 6-train-months distinction.
2. **Construction funnel.** Horizontal funnel: 1,694 Stage-K universe → 1,693 eligible in ≥1
   train month → 496 top-decile in ≥1 month → **121 PRIMARY (≥2 mo)** → 28 STRICT (≥3 mo) → 5
   (≥4 mo). (Source: frozen parquet counts above.)
3. (Optional) **n_top histogram** — bars at n_top = 0/1/2/3/4 (1197 / 375 / 93 / 23 / 5) with
   the ≥2 PRIMARY cut line drawn, showing how steeply recurrence decays.

---

## GAPS / caveats for the write-up

- **48 (M2) vs 28 (frozen ≥3mo) discrepancy.** The frozen file ranks over exactly the **6 train
  months (Aug 2025–Jan 2026)**; the M2 luck-null tally ran over **all 11 months** with a
  shrunk-daily ranking. The two are not the same estimand — the ≥3mo counts differ (48 vs 28)
  for that reason. The report should state which cohort is "canonical" (the 6-train-month frozen
  121/28) and cite the 48-vs-35 p=0.017 as the *significance evidence* for recurrence, not as the
  frozen count. This should be flagged, not smoothed over.
- **The luck-null itself.** I sourced the null expectations (184/35/5) from the ledger; the exact
  null construction (permutation of monthly top-decile labels vs a binomial with per-wallet
  eligibility) lives in `src/cohort_M2_recurrence.py` and was not re-read here — confirm the null
  model before publishing the p-values.
- **No net-of-cost / vs-fade number attaches to the 121 cohort itself.** All construction and
  significance numbers are GROSS drift-stripped markout. The deployability question is explicitly
  deferred to the Phase-3 forward experiment; do not present the 121 cohort as a profitable
  copyable set.
- **Trait medians are train-only descriptive.** `notl_med` is a median-of-per-wallet-medians;
  `dir_bias` is mean(dir) so +0.36 = net-long lean, not a Sharpe. Label axes carefully.
- **conv (continuous conviction rank)** is persisted for the Phase-2/M1 forward model but is not
  itself part of the ≥2-month membership rule; mention it as the continuous companion signal.
