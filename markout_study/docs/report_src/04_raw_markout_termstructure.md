# 04 — Raw markout term structure per coin per horizon (headline line-plot)

**Source data.** `out/cohort_K_entries.parquet` (812,616 priced entries; the frozen
`cohort_K` = 1,694 mid-freq copyable-taker wallets — taker_share≥0.70, median hold
∈[1h,24h], n_train≥200 decisions — **not** the full market-wide taker population).
Computed with light polars aggregations (`scan_parquet` + `group_by`/`agg`,
`POLARS_MAX_THREADS=2`); no bar-pricing or tape scan was performed for this note.

**Sign convention.** `raw_Xh = dir · (px(entry + X h) / px_entry − 1) · 1e4` (bp).
Positive = the price moved in the trade's own direction after the fill (favorable
post-fill markout); negative = adverse (the market moved against the position after
entry, i.e. bled).

**Weighting.** These are **entry-weighted ("field") statistics** — every priced entry
in the cohort counts once, regardless of which wallet placed it. This is deliberately
different from the **equal-weight (per-wallet-then-averaged)** "honest skill estimand"
used for the Stage K verdict (`docs/FINDINGS_LEDGER.md` line ~373). The two can and do
disagree in sign/magnitude at some horizons (see Cross-checks below) because a few
high-activity wallets dominate the entry-weighted mean. Both are legitimate; they
answer different questions ("what does the average entry look like" vs "what does the
average wallet look like"). This report's FACTS are the entry-weighted version only.

---

## FACTS

### Table 1 — Per coin × horizon, ALL splits combined (train+test+embargo), field-level

| coin | horizon | mean (bp) | median (bp) | std (bp) | IQR (bp) | N |
|---|---|---:|---:|---:|---:|---:|
| ALL  | 1h  | −0.19 | 0.00   | 93.11  | 75.26  | 812,545 |
| ALL  | 2h  | −0.22 | 0.15   | 126.42 | 103.58 | 812,509 |
| ALL  | 4h  | −0.43 | 0.27   | 168.24 | 143.45 | 812,472 |
| ALL  | 8h  | −0.59 | 0.68   | 224.31 | 202.38 | 812,186 |
| ALL  | 24h | −6.27 | −5.67  | 362.98 | 367.53 | 811,321 |
| BTC  | 1h  | −0.37 | 0.00   | 64.71  | 55.00  | 356,077 |
| BTC  | 2h  | −0.92 | −0.00  | 87.19  | 75.07  | 356,077 |
| BTC  | 4h  | −1.26 | 0.23   | 115.87 | 103.44 | 356,030 |
| BTC  | 8h  | −2.08 | 0.12   | 151.20 | 147.99 | 355,894 |
| BTC  | 24h | −6.37 | −3.22  | 250.18 | 269.62 | 355,371 |
| ETH  | 1h  | 0.00  | −0.00  | 95.22  | 80.20  | 195,851 |
| ETH  | 2h  | −0.05 | 0.11   | 131.70 | 111.17 | 195,840 |
| ETH  | 4h  | −0.16 | 0.29   | 173.60 | 154.26 | 195,839 |
| ETH  | 8h  | −1.09 | 0.92   | 225.88 | 213.20 | 195,786 |
| ETH  | 24h | −7.48 | −8.75  | 362.58 | 416.82 | 195,672 |
| HYPE | 1h  | 0.29  | 0.52   | 131.27 | 140.95 | 125,267 |
| HYPE | 2h  | 1.71  | 0.22   | 178.23 | 196.56 | 125,247 |
| HYPE | 4h  | 1.36  | −1.16  | 240.48 | 261.12 | 125,259 |
| HYPE | 8h  | 2.98  | −0.31  | 331.55 | 372.91 | 125,207 |
| HYPE | 24h | −3.74 | −16.89 | 537.21 | 633.82 | 125,055 |
| SOL  | 1h  | −0.42 | 0.00   | 109.37 | 92.20  | 135,350 |
| SOL  | 2h  | −0.41 | 0.78   | 146.45 | 128.29 | 135,345 |
| SOL  | 4h  | −0.28 | 1.49   | 193.54 | 182.95 | 135,344 |
| SOL  | 8h  | 0.74  | 3.52   | 257.52 | 261.32 | 135,299 |
| SOL  | 24h | −6.58 | −5.44  | 410.94 | 480.53 | 135,223 |

(`ALL` = pooled across BTC/ETH/SOL/HYPE, all entries; this is the "all coins" curve for
the headline plot.)

### Table 2 — Same cells, split by train vs test (embargo excluded; N: train=583,032 / test=168,468 / embargo=61,116)

| coin | split | horizon | mean (bp) | median (bp) | std (bp) | N |
|---|---|---|---:|---:|---:|---:|
| BTC  | train | 1h  | −0.38  | 0.00   | 60.18  | 237,593 |
| BTC  | train | 2h  | −0.98  | 0.10   | 82.13  | 237,593 |
| BTC  | train | 4h  | −1.18  | 0.44   | 110.20 | 237,593 |
| BTC  | train | 8h  | −1.79  | 0.53   | 142.28 | 237,593 |
| BTC  | train | 24h | −9.01  | −3.56  | 220.86 | 237,593 |
| BTC  | test  | 1h  | −0.22  | 0.00   | 58.58  | 86,619 |
| BTC  | test  | 2h  | −0.52  | 0.00   | 79.84  | 86,619 |
| BTC  | test  | 4h  | −0.54  | 0.00   | 101.73 | 86,572 |
| BTC  | test  | 8h  | −1.99  | −0.83  | 131.57 | 86,436 |
| BTC  | test  | 24h | −4.84  | −3.71  | 228.90 | 85,913 |
| ETH  | train | 1h  | −0.04  | 0.24   | 94.47  | 153,563 |
| ETH  | train | 2h  | −0.32  | 0.45   | 131.59 | 153,563 |
| ETH  | train | 4h  | −0.52  | 0.32   | 175.49 | 153,563 |
| ETH  | train | 8h  | −1.51  | 1.22   | 228.33 | 153,563 |
| ETH  | train | 24h | −9.97  | −10.72 | 358.24 | 153,563 |
| ETH  | test  | 1h  | 0.05   | −0.95  | 77.14  | 30,006 |
| ETH  | test  | 2h  | 0.68   | −0.63  | 103.58 | 29,995 |
| ETH  | test  | 4h  | 1.42   | 0.00   | 137.61 | 29,994 |
| ETH  | test  | 8h  | −0.00  | −1.79  | 181.96 | 29,941 |
| ETH  | test  | 24h | 0.22   | −1.73  | 309.59 | 29,827 |
| HYPE | train | 1h  | −0.25  | 0.36   | 131.64 | 81,932 |
| HYPE | train | 2h  | 0.76   | −0.42  | 177.70 | 81,932 |
| HYPE | train | 4h  | 0.32   | −2.04  | 242.96 | 81,932 |
| HYPE | train | 8h  | 2.71   | −0.67  | 338.11 | 81,932 |
| HYPE | train | 24h | −10.51 | −24.08 | 531.14 | 81,932 |
| HYPE | test  | 1h  | 1.35   | 0.95   | 119.15 | 34,709 |
| HYPE | test  | 2h  | 2.58   | 0.47   | 163.57 | 34,689 |
| HYPE | test  | 4h  | 2.25   | −0.23  | 221.55 | 34,701 |
| HYPE | test  | 8h  | 1.87   | 0.35   | 302.99 | 34,649 |
| HYPE | test  | 24h | 2.77   | −1.61  | 528.47 | 34,497 |
| SOL  | train | 1h  | −0.47  | 0.42   | 108.97 | 109,944 |
| SOL  | train | 2h  | −0.50  | 0.89   | 147.96 | 109,944 |
| SOL  | train | 4h  | −0.02  | 1.90   | 195.39 | 109,944 |
| SOL  | train | 8h  | 1.37   | 4.32   | 258.65 | 109,944 |
| SOL  | train | 24h | −9.09  | −5.70  | 403.77 | 109,944 |
| SOL  | test  | 1h  | 0.07   | 0.34   | 85.07  | 17,063 |
| SOL  | test  | 2h  | 2.32   | 1.57   | 110.66 | 17,058 |
| SOL  | test  | 4h  | 3.32   | 1.54   | 146.80 | 17,057 |
| SOL  | test  | 8h  | 3.52   | 3.99   | 189.97 | 17,012 |
| SOL  | test  | 24h | 3.46   | −1.14  | 326.14 | 16,936 |

Field/pooled ("ALL coins") TEST-only, for direct comparability with the Stage K
equal-weight headline number: entry-weighted mean 1h **+0.18** / 2h **+0.62** / 4h
**+0.78** / 8h **−0.28** / 24h **−1.53** bp (N≈167–168k per horizon).

### Read of the shape (descriptive only — no test of significance performed here)
- **BTC**: mean bleeds monotonically negative from 1h to 24h in both splits (deepens
  from ≈ −0.2/−0.4 at 1h to ≈ −5 to −9 at 24h); median stays ≈ 0 through 8h then also
  goes negative at 24h. Classic adverse-selection/bleed shape.
- **ETH**: mean is essentially flat/near-zero through 4h (both splits), a small dip
  by 8h, then a sharp negative drop at 24h (train −9.97, test +0.22 — the two splits
  disagree in sign at 24h, N-driven noise given std ≈ 310–360bp on ~30–150k n).
- **HYPE**: the only coin with a clear **positive hump** — mean rises from ~0 at 1h to
  a peak around 4–8h (train peak +2.71 at 8h; test peak +2.58 at 2h / stays positive
  through 8h at +1.87), then reverses hard to negative (median) or mixed (mean) by 24h.
  Median is consistently more negative than mean at every horizon ≥2h — right-skewed
  distribution (a few large favorable moves pull the mean up while the typical entry
  is flat-to-negative).
- **SOL**: near-flat to mildly negative at 1–2h, turns positive by 4–8h in TEST
  (median climbs to +3.99 at 8h) but not clearly in TRAIN, then bleeds sharply
  negative by 24h in both.
- Dispersion (std, IQR) grows monotonically with horizon in every coin/split — the
  expected sqrt(time)-ish variance growth; HYPE has by far the widest dispersion at
  every horizon (std 131→537 bp, 1h→24h) consistent with it being the highest-vol,
  most illiquid of the four names.

### Cross-checks against other artifacts
1. **`docs/FINDINGS_LEDGER.md` Stage K** (equal-weight, wallet-level, TEST, pooled all
   coins): 1h −0.2 / 2h −0.1 / 4h +0.5 [−0.8,+1.9] / 8h −1.5 / 24h −4.3 bp. This
   report's entry-weighted TEST pooled numbers (1h +0.18 / 2h +0.62 / 4h +0.78 /
   8h −0.28 / 24h −1.53) are **directionally similar in the 1–4h range but diverge
   in sign at 8h and are ~3× smaller in magnitude at 24h.** This is expected and not
   a discrepancy: equal-weight vs entry-weight are different estimators, and the
   entry-weighted mean is dominated by whichever wallets place the most entries.
   Do not merge the two numbers in the report without labeling which weighting each
   is under.
2. **`out/field_by_coin_horizon.parquet`** (from `notebooks/markout_findings.ipynb`,
   the prior, much larger, whole-market-taker field study, N≈0.77M–2.1M per
   coin/horizon vs this cohort's 125k–356k) — a genuinely independent population
   (all takers, not just the 1,694-wallet mid-freq cohort) computed with a different
   pricing pipeline (first 5-min bar close post-fill). Shapes match well:
   - BTC monotonic negative bleed, deepening toward 24h (field: 1h −0.43 → 24h −5.00;
     this cohort: 1h −0.37 → 24h −6.37). Consistent.
   - ETH near-flat/slightly positive at 1h (field +0.07; cohort +0.00) then bleeding
     to strongly negative by 24h (field −6.50; cohort −7.48). Consistent.
   - HYPE positive hump peaking mid-horizon then reversing by 24h (field: 1h +0.49,
     2h +1.76, 4h +2.41, **8h +3.51 (peak)**, 24h −0.33; cohort: 1h +0.29, 2h +1.71,
     4h +1.36, **8h +2.98**, 24h −3.74). Same qualitative hump-then-reversal shape,
     close magnitudes — this is the "HYPE hump" referenced in memory
     (`babylon-markout-study`). Strong cross-validation.
   - SOL: field is monotonic negative throughout (1h −0.40 → 24h −8.21); this cohort
     is closer to flat/slightly positive through 4–8h before bleeding at 24h (1h −0.42,
     8h +0.74, 24h −6.58). Partial divergence in the 4–8h region — plausibly a
     cohort-selection effect (mid-freq copyable takers in SOL may time entries
     differently than the full SOL taker population), worth flagging rather than
     asserting either is wrong.
3. No numbers in `docs/FINDINGS_LEDGER.md` or the notebook directly report `std`/`IQR`
   for cohort_K at these horizons, so the dispersion column here is new (computed for
   this task) and has no existing cross-check.

---

## FIGURES-TO-MAKE

**Fig 1 (headline).** Line plot, x = horizon (categorical, ordered 1h→2h→4h→8h→24h),
y = mean raw markout (bp). One line per coin (BTC, ETH, SOL, HYPE) + one line for the
pooled "ALL coins" curve (heavier/dashed to distinguish it as the aggregate, not a 5th
coin). Zero line at y=0. Use Table 1 (all-splits) as primary; optionally add a toggle
or small-multiple for train-only/test-only using Table 2. Annotate the HYPE hump
(peak ≈ 4–8h) and the BTC/ETH/SOL 24h bleed. Recommend NOT auto-scaling y so tightly
that the 1–4h structure disappears against the 24h swing — consider a broken axis or
a zoomed inset for 1h–8h given the 24h values are 5–10× larger in magnitude, mirroring
the "full-range vs zoom" pattern already used in `markout_findings.ipynb` cells 6/8.

**Fig 2 (dispersion companion).** Either (a) error bars / shaded band of ±1 std (or
IQR) around each line in Fig 1, or (b) a separate small-multiple of std vs horizon per
coin, to show that HYPE's dispersion dominates and that all coins' spread grows with
horizon — contextualizes why the means in Fig 1 are all small relative to the noise.

**Fig 3 (distribution check).** Violin or box plot of the raw markout distribution per
coin at a fixed representative horizon (suggest 4h and 24h as two panels) — median line
visibly below/above 0, to make concrete the mean/median divergence seen in Table 1
(e.g., HYPE's median running more negative than its mean at every horizon ≥2h).

**Fig 4 (optional, train/test agreement check).** Small-multiple line plot (one panel
per coin) with two lines (train vs test) over the same 5 horizons, from Table 2 — makes
visible where the two splits agree (BTC direction, ETH shape) vs disagree (SOL 4–8h,
ETH 24h sign flip), directly supporting the "read of the shape" bullets above.

---

## GAPS

- **This is descriptive only** — no CI, no significance test, no permutation/FDR gate
  was run for this note (out of scope per the task: light aggregation only). Table 1/2
  numbers are point estimates; do not present them as "the edge is X bp" without the
  Stage K equal-weight/CI numbers alongside, which are the ones actually gated for
  significance (see `docs/FINDINGS_LEDGER.md` Stage K).
- **Weighting ambiguity is the single most important caveat for the report writer.**
  Entry-weighted (this doc) and equal-weight-per-wallet (Stage K verdict) numbers
  disagree at 8h and 24h, including a sign flip at 8h (entry-weighted TEST pooled
  −0.28 vs equal-weight TEST pooled −1.5). If the headline plot is entry-weighted,
  say so explicitly in the figure caption — a reader who has seen the Stage K prose
  will otherwise think the numbers conflict.
- **cohort_K is not the full market** — it is the frozen 1,694-wallet mid-freq
  copyable-taker cohort (taker_share≥0.70, 1h–24h median hold, n_train≥200). The
  broader whole-market field numbers live in `out/field_by_coin_horizon.parquet`
  (from an earlier, separate study/pipeline, 12 horizons out to 168h, includes SPX
  and ALT baskets this task didn't touch). If the report wants a "does the true
  field-wide term structure look like this" answer, that parquet is the one to cite,
  not this cohort.
- **Embargo split excluded from Table 2** (61,116 entries) — not analyzed here; if the
  report wants a 3-way split it's one more group_by away but wasn't requested.
- **SOL 4h–8h divergence between train/test** (Table 2) is unexplained here — could be
  real regime difference (TEST window is a documented −10.85% BTC DOWN window per
  Stage K) or could be noise; no test was run to adjudicate. Flag as open, don't
  resolve.
- **No neut_Xh (coin-month drift-stripped) companion table was computed** — the task
  scoped this to `raw_*` only. The `neut_*` columns exist in the same parquet if the
  report later wants a raw-vs-neutralized comparison panel (Stage K already reports a
  handful of neut numbers for context).
