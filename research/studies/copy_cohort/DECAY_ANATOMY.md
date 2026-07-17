# DECAY ANATOMY — arm-T cohort: trader persistence × copy markout

**STATUS: DIAGNOSTIC / DESCRIPTIVE.** Reuses the 8 already-consumed validation folds
(202511–202606). This is mechanism attribution for the arm-T copy-markout profile — it is
NOT an effect confirmation, and the feature scan at the bottom is hypothesis-grade
(uncorrected, post-hoc). Code: `research/studies/copy_cohort/decay_anatomy.py`;
artifact: `data/derived/copy_cohort/decay_anatomy_report.json`.

## Setup

- **Cohort**: arm T (top-30 by formation capday t-stat) from
  `data/derived/copy_cohort/alt_universe_cohorts.json` — 240 wallet-folds.
- **TRADER axis**: own forward test-month realized capped PnL/day from lake
  `wallet_coin_day`, same capday formula as selection (day_pnl = Σpnl − Σfee across coins,
  cap factor min(1, 100k/day_notional), ÷ active days). "Won" = > 0.
- **COPY axis**: forward alt 8h gross dir-signed markout (local asset_ctx mid lattice,
  ≤90s staleness — identical spec to `alt_fresh_validate._forward_entries`), raw
  wallet-fold mean over evaluable entries. "Won" = > 0.
  Cross-check: the wf-equal cohort mean here (+35.84 bp) reproduces the validation
  report's raw arm-T point (35.839) exactly.
- **Base rate**: same forward-own-capday persistence over the FULL eligible pool
  (formation nd≥15, sd>0; `informedness/fold=*/pool.parquet`), among wallets with ≥1
  forward active day.

## Quadrant table (240 wallet-folds)

| bucket | n | copy mk mean (bp) | copy mk median (bp) | Σ copy mk (bp) | share of copy drawdown | fwd own capday median ($/d) | form t med | form z med | form nd med | form capday med ($/d) |
|---|---|---|---|---|---|---|---|---|---|---|
| **TW·CW** trader won, copy won | 43 | +140.7 | +63.5 | +6051 | — | +20 | 8.33 | 7.05 | 79 | 27.8 |
| **TW·CL** trader won, copy lost (**wedge**) | 27 | −75.8 | −58.6 | −2047 | **52.7%** | +14 | 8.56 | 7.16 | 79 | 12.0 |
| **TL·CW** trader lost, copy won | 11 | +106.3 | +73.9 | +1169 | — | −158 | 8.04 | 6.84 | 80 | 85.9 |
| **TL·CL** trader lost, copy lost (**curse**) | 12 | −153.4 | −68.4 | −1840 | **47.3%** | −448 | 8.47 | 7.05 | 82 | 81.5 |
| NO_COPY_ENTRIES (fwd-active, no alt flat-opens evaluable) | 119 | — | — | — | — | +11 | 8.43 | 6.82 | 74 | 25.5 |
| FWD_INACTIVE (no forward capday days) | 28 | — | — | — | — | — | 8.00 | 6.02 | 42.5 | 148.3 |

Total copy drawdown (Σ negative wallet-fold means) = −3887 bp; cohort wf-equal copy mean
over the 93 evaluable wallet-folds = **+35.8 bp** (net positive — "drawdown" here is the
negative tail being decomposed, not a net cohort loss).

## Key numbers

1. **Trader persistence (cohort)**: 169/212 fwd-active wallet-folds have positive own
   forward capday → **79.7%** (28/240 inactive forward).
2. **Base rate (full eligible pool)**: 112,858/332,590 pooled fwd-active wallet-folds
   positive → **33.9%** (per-fold 25.3%–39.5%). **t-selection lifts own-PnL persistence
   ~2.35× over base** — the selector finds real traders.
3. **Wedge size**: among trader-WON wallet-folds with copy entries, copy markout mean
   **+57.2 bp** / median **+20.4 bp** — trader-won copying is net *positive*, but 27/70
   (39%) of trader-won wallet-folds still lose on copy (the wedge).
4. **Curse size**: among trader-LOST, copy mean **−29.2 bp** / median **−18.6 bp**.
5. **Drawdown rank**: wedge (TW·CL, −2047 bp, 52.7%) ≈ curse (TL·CL, −1840 bp, 47.3%) —
   an even split. The negative tail is NOT dominated by lucky-wallet regression; half of
   it comes from wallets who kept winning while our 8h-alt-markout copy of them lost.

## Base rate per fold

| fold | eligible pool | fwd-active | persist rate | pool fwd capday median |
|---|---|---|---|---|
| 202511 | 70,950 | 46,091 | 25.3% | −6.7 |
| 202512 | 73,260 | 43,347 | 32.8% | −1.8 |
| 202601 | 66,084 | 43,310 | 31.5% | −2.4 |
| 202602 | 58,247 | 37,788 | 34.9% | −2.1 |
| 202603 | 54,352 | 35,672 | 36.0% | −0.9 |
| 202604 | 56,532 | 38,534 | 39.5% | −0.8 |
| 202605 | 57,870 | 42,059 | 39.4% | −0.6 |
| 202606 | 63,412 | 45,789 | 33.8% | −2.2 |

Cohort persistence beats the base rate in every fold's neighborhood (79.7% pooled vs
33.9% pooled); pool median forward capday is negative in all 8 folds while the cohort's
fwd-active median is positive in TW rows and in the NO_COPY bucket (+11 $/d).

## Ex-ante feature scan — trader-LOST vs trader-WON (hypothesis-grade, uncorrected)

Median difference (lost − won), two-sided permutation p (5000 perms), n = 43 lost / 169 won
(tsplit features cover all arm-T wallet-folds; e_* features where entry panel exists):

| feature | lost med | won med | diff | p |
|---|---|---|---|---|
| form_capday | 46.7 | 25.1 | +21.6 | 0.102 |
| e_entries_per_day | 3.09 | 4.45 | −1.36 | 0.124 |
| f_coin_breadth | 13 | 4 | +9 | 0.135 |
| e_dust_share | 0.293 | 0.200 | +0.093 | 0.142 |
| e_med_notl | 243 | 351 | −108 | 0.339 |
| form_nd | 72 | 78 | −6 | 0.423 |
| form_t | 8.37 | 8.45 | −0.08 | 0.729 |
| (all others) | | | | ≥0.45 |

**No feature clears even nominal 0.05.** Weak, correlated leans (candidate filter,
hypothesis-grade only): future trader-losers had *higher* formation capday LEVEL with the
same t (steeper level → more regression), *wider* coin breadth, *fewer* entries/day, and
*more* dust entries. Formation t/z themselves do NOT separate persisters from
regressors within the cohort — the selector's own score carries no within-cohort dose
signal. Any filter built on these must be preregistered on unseen folds.

## Verdict (2–3 sentences)

t-selected wallets are predominantly **real traders, not lucky regressors**: their own
forward-month capday PnL is positive 79.7% of the time vs a 33.9% eligible-pool base rate
(~2.35×), and even the copy-invisible majority (NO_COPY_ENTRIES bucket) keeps a positive
forward median. The copy shortfall is therefore only about half "winner's curse" —
the drawdown splits ~53% wedge (trader kept winning, our alt-8h-flat-open copy lost)
vs ~47% curse (trader regressed) — so capturing more of the edge is as much a
*copy-construction* problem (entry coverage: 119/240 wallet-folds produce zero evaluable
alt flat-open entries; horizon/instrument mismatch on the rest) as a selection problem.
Net-net the evaluable cohort copy is +35.8 bp wf-equal (positive), and the diagnostic says
the path to more is coverage + wedge reduction, not a better t.
