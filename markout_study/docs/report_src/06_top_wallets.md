# 06 — Top Markout Wallets Leaderboard (IN-SAMPLE)

**Source:** `out/cohort_K_entries.parquet` (812,616 entries, 1,694 wallets, 4 coins BTC/ETH/HYPE/SOL,
2025-08 → 2026-06, `raw_1h`…`raw_24h` = raw per-entry markout in **bp**, next-bar-close entry convention,
horizon-exit convention per Stage K). Computed with polars, `POLARS_MAX_THREADS=2`, light group-by
aggregation only — **no bar-pricing, no tape scan.**

**IN-SAMPLE definition used here: `split == "train"`** (583,032 entries / 1,694 wallets), i.e. the
chronological train partition of cohort_K (train / 1-month embargo / test). This is deliberately the
same partition Stage M1/M2 rank wallets on — it lets this leaderboard sit next to those results without
introducing a third definition of "in-sample." The full-sample (train+embargo+test pooled) version was
**not** computed; see GAPS.

**Ranking is per-entry (entry-weighted)**, not day-weighted. This matters: Stage M1 found
train→test rank-IC is **+0.16 under day-weighting (equal capital per wallet-day) but −0.055 under
entry-weighting** (a copier who takes every episode captures nothing; the persistence — such as it is —
lives only in day-equal-weighting because wallets over-trade their worse days). **This leaderboard uses
the entry-weighted convention**, i.e. the convention Stage M1 found closer to flat/negative OOS. Read
accordingly (see GAPS).

## Definitions (for reproducibility)

Per wallet *w*, per horizon *h* ∈ {1h, 8h}, over train-split entries with non-null `raw_h`:

- **N** = count of entries.
- **mean_bp** = mean(`raw_h`) — simple entry-weighted average, bp.
- **std_bp** = sample std(`raw_h`), bp.
- **Sharpe** = `mean_bp / std_bp` — **per-trade** Sharpe (not annualized, no √N scaling). This is a
  ratio of the per-entry distribution, not a rate-of-return Sharpe; do not compare directly to
  annualized fund Sharpes.
- **max_dd_bp** — sort the wallet's entries by `b_ts` (entry time) ascending, form the cumulative sum
  of `raw_h` (an equity-curve-style running total of markout in bp, one path per wallet), then
  `max_dd_bp = max(running_cummax − running_cumsum)` over that path, i.e. the largest peak-to-trough
  decline in cumulative bp. This is a **path-order** statistic (order matters) unlike the other columns.
- **hit_rate** = share of entries with `raw_h > 0`.
- **median_notl** = median `notl` (position notional, USD) across the wallet's entries.

**N-floor: N ≥ 100 entries** (on the horizon-specific non-null subset) to appear in either table.
In practice this floor is **non-binding on cohort_K**: the cohort's wallet list already carries a
built-in activity screen — the minimum train-split entry count over all 1,694 wallets is 200 — so all
1,694 wallets clear the N≥100 bar for both horizons (n eligible = 1,694 / 1,694). The floor is stated
because it is the honest gate to apply; it happens the cohort selection already dominates it.

## FACTS

### Table 1 — Top 20 wallets by mean 1h markout (train, entry-weighted, N≥100)

| # | wallet | N | mean_bp | std_bp | sharpe | max_dd_bp | hit_rate | median_notl |
|---|--------|---|---------|--------|--------|-----------|----------|-------------|
| 1 | 0xfe104b72c2e396beda3c0d7208ca0d9ee565ab42 | 202 | 36.63 | 111.03 | 0.330 | 523.0 | 0.594 | 6,882 |
| 2 | 0x9899db38f2a1197c0bb13494a9360a01c45a28cd | 229 | 31.95 | 114.72 | 0.279 | 1,381.2 | 0.620 | 11,718 |
| 3 | 0xfffa6fc6acc3dbe04b175862376f1c5ff88cf9c1 | 200 | 29.76 | 107.35 | 0.277 | 994.4 | 0.590 | 264,450 |
| 4 | 0x413c2724b62975c18b1415650f998a8f0a67886c | 354 | 26.01 | 104.86 | 0.248 | 1,546.5 | 0.590 | 155,613 |
| 5 | 0x032ea2033d2acff67cec78fd447b06c335f2d42c | 301 | 23.19 | 249.46 | 0.093 | 2,809.2 | 0.485 | 3,457 |
| 6 | 0x4b4d11ca40a91d5b21587ef68bdc66d8ad194c0f | 294 | 22.96 | 90.08 | 0.255 | 1,062.6 | 0.551 | 399 |
| 7 | 0x73d30ba3dc4ffd17c28cc2d75d12e50df98f29cf | 210 | 22.29 | 150.69 | 0.148 | 1,416.2 | 0.576 | 4,037 |
| 8 | 0x5727d8ec2a6c0e0f09160398fa05d7522bb86a93 | 495 | 21.19 | 125.56 | 0.169 | 1,641.5 | 0.539 | 2,476 |
| 9 | 0xdfb34089a67eef4dc63d6160a0b6c8b7fdcb2964 | 248 | 20.47 | 122.37 | 0.167 | 1,388.9 | 0.569 | 5,535 |
| 10 | 0xdaf50e499dcaff47f284833920c02cde439b6e4f | 235 | 19.39 | 169.66 | 0.114 | 3,357.6 | 0.557 | 2,299 |
| 11 | 0x3313292de6c21a835f9006d4f89e1e8cbc471640 | 208 | 18.97 | 109.53 | 0.173 | 1,102.7 | 0.548 | 45,241 |
| 12 | 0x7bd5d48610d08cea33686bc8972ec447041cc9a4 | 268 | 18.89 | 112.98 | 0.167 | 1,142.2 | 0.571 | 4,457 |
| 13 | 0x95684d61bda26931c52238193e946fa0dabb43c6 | 200 | 18.49 | 111.83 | 0.165 | 1,102.7 | 0.545 | 11,182 |
| 14 | 0xff2fed9cb48196ec35fd97b290c583e7a63b17b7 | 362 | 18.45 | 95.53 | 0.193 | 1,204.7 | 0.552 | 139,147 |
| 15 | 0x8130398e2269cf05a9482b988c935094e99ee4a8 | 215 | 18.40 | 103.88 | 0.177 | 1,163.7 | 0.563 | 4,996 |
| 16 | 0xa4536787a7a687edae7b9e5d13f82c182f6d06b7 | 254 | 18.39 | 111.66 | 0.165 | 1,714.4 | 0.555 | 67,817 |
| 17 | 0x7fabfcc09d53fc302afcf8bca938d2d64db7c3a0 | 227 | 17.54 | 122.70 | 0.143 | 1,399.8 | 0.546 | 39,985 |
| 18 | 0xfd490cf856122be05ad6255be836e46a41f6d63c | 236 | 17.49 | 72.94 | 0.240 | 1,880.8 | 0.589 | 131,053 |
| 19 | 0x05e66f8373d0364c2501a3ac69727fbb833e5679 | 263 | 17.18 | 87.10 | 0.197 | 704.2 | 0.574 | 191,878 |
| 20 | 0xde60d916a99d51c1bf58d36674492033fe580bbb | 261 | 16.93 | 94.19 | 0.180 | 967.5 | 0.571 | 6,942 |

### Table 2 — Top 20 wallets by mean 8h markout (train, entry-weighted, N≥100)

| # | wallet | N | mean_bp | std_bp | sharpe | max_dd_bp | hit_rate | median_notl |
|---|--------|---|---------|--------|--------|-----------|----------|-------------|
| 1 | 0x5aadb434293b4e1b8fb2e84007e567506fe65a96 | 214 | 132.80 | 371.80 | 0.357 | 4,341.6 | 0.687 | 12,061 |
| 2 | 0xfd490cf856122be05ad6255be836e46a41f6d63c | 236 | 124.23 | 192.79 | 0.644 | 2,967.6 | 0.763 | 131,053 |
| 3 | 0xdfb34089a67eef4dc63d6160a0b6c8b7fdcb2964 | 248 | 83.32 | 249.86 | 0.333 | 2,216.4 | 0.641 | 5,535 |
| 4 | 0x172f5a1147c2b65e88b8d1f14af55c9fa304b639 | 202 | 80.16 | 501.55 | 0.160 | 10,875.2 | 0.515 | 3,225 |
| 5 | 0x1ecc7c22798d83edeb70487c6447440862f92d68 | 200 | 78.86 | 275.94 | 0.286 | 3,030.0 | 0.610 | 25,028 |
| 6 | 0x19bedeac0068e0be958beca80f12cd904b10c4b7 | 204 | 78.26 | 253.77 | 0.308 | 4,633.7 | 0.569 | 536 |
| 7 | 0x996d122d11d49d0357067a96b7d01a13f1468e35 | 318 | 77.08 | 372.95 | 0.207 | 10,029.6 | 0.522 | 2,195 |
| 8 | 0xfffa6fc6acc3dbe04b175862376f1c5ff88cf9c1 | 200 | 73.74 | 268.68 | 0.274 | 3,089.4 | 0.630 | 264,450 |
| 9 | 0x22b6df9a67cffda687d556a1f36954741b5a9370 | 312 | 72.20 | 286.93 | 0.252 | 4,299.3 | 0.619 | 5,279 |
| 10 | 0x9a082414ae6d7cff879d2b7d0c80ad8148725418 | 353 | 70.86 | 290.83 | 0.244 | 2,555.8 | 0.567 | 40,496 |
| 11 | 0x8eb2204b74516ff29337f73252e3f642917557c8 | 340 | 70.59 | 226.60 | 0.312 | 2,833.6 | 0.624 | 1,003 |
| 12 | 0xc0986544922b4b585da4c077f6488e2fbaf043ba | 220 | 69.94 | 415.99 | 0.168 | 6,536.7 | 0.514 | 1,353 |
| 13 | 0xfe104b72c2e396beda3c0d7208ca0d9ee565ab42 | 202 | 64.24 | 268.80 | 0.239 | 2,826.5 | 0.584 | 6,882 |
| 14 | 0x8130398e2269cf05a9482b988c935094e99ee4a8 | 215 | 61.68 | 289.57 | 0.213 | 3,334.7 | 0.567 | 4,996 |
| 15 | 0x596cbe62742c50e33178f02d7722fcaf04dc9f08 | 326 | 61.12 | 190.45 | 0.321 | 3,770.4 | 0.641 | 1,374 |
| 16 | 0x43651e3939fbfeb383133757f3863c2ec165a7ca | 205 | 59.68 | 212.95 | 0.280 | 2,931.1 | 0.673 | 36,601 |
| 17 | 0xb9557960d25a22288c1581d86d3f5e61209d6176 | 407 | 59.65 | 282.11 | 0.211 | 6,300.4 | 0.553 | 5,350 |
| 18 | 0xa7ee1ef02066da392bc51a97456451be18e2cb9d | 205 | 59.58 | 222.34 | 0.268 | 2,382.0 | 0.532 | 6,139 |
| 19 | 0x2fc8193d30751dd7218383f0299a34d4df5115b8 | 205 | 58.22 | 269.26 | 0.216 | 6,049.3 | 0.610 | 907 |
| 20 | 0xcecc2959a1e61e91edcacf5ab33f0c753fac6eed | 221 | 57.56 | 303.42 | 0.190 | 3,621.9 | 0.597 | 493 |

### Cross-checks

- **Overlap between the two top-20 lists: 5/20** (`0xfe104b72…`, `0xfffa6fc6…`, `0xdfb34089…`,
  `0x8130398e…`, `0xfd490cf8…`). Modest but not trivial overlap — consistent with the Stage M2 finding
  that the persistence-like structure has a term shape (rank-IC rises 1h→8h, peaking near 8h), so 1h and
  8h "best" wallets are related but not identical lists.
- **Population-level correlation (all 1,694 eligible wallets, not just top-20):** Pearson r = 0.446,
  Spearman ρ = 0.436 between mean_1h and mean_8h. This is an **in-sample, same-wallet, same-window**
  correlation (shared directional bets contaminate both horizons for the same entries) — it says nothing
  about forward persistence and should not be read as corroborating Stage M2's OOS rank-IC.
- 8h mean_bp values are roughly 3–4× the 1h values for top wallets, and std_bp roughly 2–3×
  correspondingly — both expected under horizon scaling of a directional-markout series (mean and
  variance grow with time-to-exit even without a persistent "edge").

## Reproducibility — exact formulas

```
raw_h = out/cohort_K_entries.parquet[f"raw_{h}"], split == "train", non-null
N          = count(raw_h)
mean_bp    = mean(raw_h)
std_bp     = sample_std(raw_h)                      # ddof=1, polars default
sharpe     = mean_bp / std_bp                        # per-trade, NOT annualized
cum        = cumsum(raw_h) ordered by b_ts asc, per wallet
cummax     = running max of cum
max_dd_bp  = max(cummax - cum)                       # largest peak-to-trough decline, bp
hit_rate   = mean(raw_h > 0)
median_notl= median(notl)
N-floor: N >= 100  (non-binding here; min N over all wallets = 200)
```
Script: `scratch_analysis/top_wallets.py` (POLARS_MAX_THREADS=2, scan_parquet + group_by, no bar
pricing, no tape scan). Outputs: `scratch_analysis/top20_{1h,8h}_train.parquet`.

## Cross-check vs FINDINGS_LEDGER Stage M1/M2

- **This leaderboard is entry-weighted, in-sample, single-window.** It is exactly the construction the
  ledger already warns about: `eda_winnerscurse.parquet` found selecting wallets on their **best
  in-sample horizon** markout gives **−28.7bp NET out-of-sample** (pooled; BTC −20/ETH −36/SOL −46), and
  train→eval wallet-rank Spearman ≈ 0 (0.002–0.05) for straight performance-based ranking (ledger
  "Bottom line," 2026-07-04). **These two top-20 tables should not be presented as "the wallets to
  copy"** — they are a descriptive in-sample snapshot, not a vetted selection.
- Stage M1/M2 use the **same train split** but a **day-weighted** (equal capital per wallet-day)
  ranking, not entry-weighted, because M1 explicitly found the entry-weighted rank-IC is **negative**
  (−0.055) while day-weighted is **+0.16** (p=0.0001, the one genuinely positive OOS lens in the whole
  arc). This leaderboard's entry-weighted ranking is therefore the version M1 found **closer to the
  ranking that does NOT persist OOS**, not the one that does.
- Stage M2's decisive OOS result was **top-decile day-capped GROSS +13.99bp [+5.38,+22.81] at 8h**, but
  **alpha vs. a costless mechanical fade ≈ +1.00bp [−10.75,+13.66] p=0.44 (zero)** — i.e., even the
  ranking method that *does* show OOS persistence produces generic short-horizon reversal, not
  wallet-specific skill. Nothing in this in-sample leaderboard task attempted to net out the fade; these
  tables are raw/gross.
- Net: this table is useful for **descriptive/EDA purposes** (who trades biggest and cleanest in-sample,
  distributional shape of Sharpe/hit-rate/notional across the wallet population) but must be captioned
  in the report as **in-sample only, not a validated ranking, not deployable, and known to be close to
  the ranking convention (entry-weighted) that failed OOS** in this study.

## FIGURES-TO-MAKE

1. **Bar chart, top-20 mean markout (bp)** — one panel each for 1h and 8h, bars ordered by rank, with
   thin error bars = `std_bp / sqrt(N)` (SEM) to visually show how much of the apparent gap between
   rank 1 and rank 20 is inside noise. Annotate the 5 wallets that appear in both top-20 lists.
2. **Sharpe vs. N scatter (all 1,694 eligible wallets, both horizons as two series/colors)** — expect
   the classic small-N-inflates-Sharpe funnel shape; overlay the N=100 floor as a vertical reference
   line and mark the top-20 cutoff wallets to show how much of "top by mean" is actually low-N,
   high-variance wallets riding the funnel edge (table 8h #4 `0x172f5a11…`, std_bp=501.6, is a candidate
   to highlight — high mean, high std, wide max_dd, N=202, right at the floor).
3. **Cumulative markout equity curves** for the top-5 wallets per horizon (the same path used to
   compute `max_dd_bp`), train split only, to make the drawdown numbers legible — several top-8h wallets
   have `max_dd_bp` (2,200–10,900bp) that is a large multiple of their `mean_bp`, i.e. their in-sample
   curve is lumpy/streaky, not steadily compounding.
4. **hit_rate vs mean_bp scatter** — check whether top-ranked wallets are "high hit-rate, small edge per
   win" or "low hit-rate, occasional large win" (both patterns are visible by eye in the tables: e.g.
   1h #2 hit_rate 0.62 vs 1h #5 hit_rate 0.485 despite similar rank).
5. **Venn/overlap diagram or table** of the 1h-top-20 ∩ 8h-top-20 ∩ (if built later) 4h/24h-top-20 sets,
   to visually convey the term-structure point already made in Stage M2 (persistence/ranking shape
   changes with horizon, doesn't collapse to one wallet list).

## GAPS

- **Full-sample (train+embargo+test pooled) version not computed.** Only `split == "train"` was run, to
  match the Stage M1/M2 in-sample convention and avoid quietly blending test-partition entries into a
  "descriptive" table that later gets reused for a decision. If the team wants the full-sample table
  too, it is a cheap re-run of the same script with the `.filter(pl.col("split") == "train")` removed
  (or replaced with `!= "embargo"` if embargo rows should stay excluded).
- **Only 1h and 8h were requested/built**; 2h, 4h, and 24h columns exist in the same parquet
  (`raw_2h`, `raw_4h`, `raw_24h`) and could be added with the identical script for a full term-structure
  leaderboard at near-zero incremental cost.
- **No multiplicity control applied to "top-20."** With 1,694 wallets and only in-sample means compared,
  this is a plain sort, not a test — consistent with the task ("info-gathering," not a new hypothesis
  test), but the report should not let a reader infer "top-20" implies statistical significance. The
  ledger's existing winner's-curse number (−28.7bp OOS for analogous best-in-sample selection) is the
  relevant caution and is already surfaced above.
- **`max_dd_bp` is path-dependent on entry order (`b_ts`) only**, not on overlapping/concurrent
  positions or realized capital at risk — it is a "stacked bp" drawdown of the markout series, not a
  dollar or %-of-capital drawdown. For wallets with large concurrent positions this could understate or
  overstate real capital drawdown; not attempted here (would require notional-weighting the cumulative
  series, a design decision left for whoever owns capital-at-risk reporting).
- **notl (notional) not used as a weight anywhere** — `median_notl` is reported purely descriptively.
  A notional-weighted version of mean_bp/Sharpe (a third weighting scheme beyond day- and entry-weighted)
  was not built; Stage M1 already flags that weighting choice materially flips sign (day +0.16 vs entry
  −0.055), so a third weighting axis is a real, unexplored degree of freedom, not a nitpick.
- **No wallet-clustering / correlated-wallet check** for these specific top-20 lists (some entries in
  the ledger note wallet-clustering caveats elsewhere in the arc, e.g. Stage M2 transition-probability
  section); not re-verified for these two lists specifically.
