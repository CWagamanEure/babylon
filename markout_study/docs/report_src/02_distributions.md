# 02 — Behavioral Distributions (EDA)

Source: `out/cohort_K_entries.parquet` (frozen entry-level cohort, `docs/STAGE_K_ARCHITECTURE.md`).
n = 812,616 entries, 1,694 wallets, 4 coins (BTC/ETH/HYPE/SOL — MAJORS only). All aggregations computed
with `POLARS_MAX_THREADS=2`, light group-by/quantile ops only (no bar-pricing, no tape scan).

**Cohort-definition note (not a data artifact):** cohort K is pre-filtered to wallets with `n_train ≥ 200`
entries (STAGE_K §1); the entries-per-wallet minimum of 200 seen below is a selection criterion, not an
organic floor — flag this when captioning the histogram so readers don't mistake it for a natural distribution.

---

## FACTS

### 1. Trade size (`notl`, USD notional) — percentiles

**Overall (n=812,616):**

| p1 | p10 | p25 | p50 | p75 | p90 | p99 | mean |
|---|---|---|---|---|---|---|---|
| 125.7 | 405.7 | 1,031.4 | 3,841.6 | 16,336.3 | 77,446.8 | 1,191,900 | 70,999.9 |

Heavy right skew: mean (~$71.0k) is ~18x the median (~$3.84k); p99/p50 ratio ≈ 310x.

**Per coin:**

| coin | p1 | p10 | p25 | p50 | p75 | p90 | p99 | mean | n |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 134.6 | 488.9 | 1,237.3 | 4,386.0 | 19,761.7 | 94,608.0 | 1,549,100 | 89,658.6 | 356,118 |
| ETH | 128.4 | 440.4 | 1,188.3 | 4,305.5 | 20,119.4 | 101,699.1 | 1,991,700 | 93,531.1 | 195,859 |
| HYPE | 114.3 | 294.4 | 749.7 | 2,499.7 | 10,117.6 | 42,709.6 | 446,967.3 | 26,113.0 | 125,282 |
| SOL | 122.5 | 373.4 | 962.1 | 2,906.0 | 11,280.0 | 45,930.3 | 499,103.1 | 30,853.3 | 135,357 |

BTC and ETH tickets run ~1.7-1.9x the median size of HYPE/SOL tickets, and their tails are 3-4x fatter
(p99 for BTC/ETH ≈ $1.5-2.0M vs. $0.45-0.50M for HYPE/SOL). BTC/ETH also carry the bulk of mean notional
via a small number of very large fills (mean/p50 ratio: BTC 20.4x, ETH 21.7x, HYPE 10.4x, SOL 10.6x —
BTC/ETH have a heavier extreme tail relative to their own median than HYPE/SOL do).

### 2. Direction balance (`dir` ∈ {+1 long, −1 short})

**Overall:** dir mean = **0.2578** (i.e., net ~62.9% long / 37.1% short by entry count).
n_long = 511,071, n_short = 301,545 (n=812,616).

**Per coin:**

| coin | dir_mean | n_long | n_short | long share | n |
|---|---|---|---|---|---|
| BTC | 0.1628 | 207,050 | 149,068 | 58.1% | 356,118 |
| ETH | 0.2695 | 124,319 | 71,540 | 63.5% | 195,859 |
| HYPE | 0.4634 | 91,670 | 33,612 | 73.2% | 125,282 |
| SOL | 0.3007 | 88,032 | 47,325 | 65.0% | 135,357 |

Long bias is universal but monotonically stronger moving from BTC (least long-skewed, 58%) → SOL → ETH →
HYPE (most long-skewed, 73%). HYPE stands out as by far the most one-sided coin in this cohort.

### 3. Entries-per-wallet distribution

n_wallets = 1,694 (min entries = 200 by construction, see cohort-definition note above).

| p1 | p10 | p25 | p50 | p75 | p90 | p99 | mean | min | max |
|---|---|---|---|---|---|---|---|---|---|
| 203 | 232 | 281 | 388 | 588.75 | 842.7 | 1,523.17 | 479.7 | 200 | 2,390 |

Right-skewed (mean 479.7 vs median 388); a small set of highly active wallets pushes p99 to ~3.9x the
median.

### 4. Entries-per-wallet-per-day (activity/position-building proxy)

Day = UTC calendar day from `b_ts`. Two complementary cuts:

**(a) Entries per wallet on days the wallet was active** (179,402 wallet-day observations):

| p1 | p10 | p25 | p50 | p75 | p90 | p99 | mean | max |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 1 | 3 | 6 | 10 | 25 | 4.53 | 127 |

Median active day sees only 3 entries; the distribution is strongly right-skewed (mean 4.53), consistent
with position-building via multiple smaller adds on a subset of days rather than one entry per day.

**(b) Active days per wallet** (over the ~11-month window, n=1,694 wallets):

| p1 | p10 | p25 | p50 | p75 | p90 | p99 | mean | max |
|---|---|---|---|---|---|---|---|---|---|
| 29 | 49 | 68 | 97 | 136 | 177 | 240.07 | 105.9 | 300 |

Median wallet is active on 97 distinct days; most wallets (p10-p90: 49-177 days) trade on a sizable
minority-to-half of the ~330 calendar days spanned by the data (see §5).

### 5. Temporal distribution — entries by month (`ym`)

Window: 202508 (Aug 2025) – 202606 (Jun 2026), 11 months.

| ym | n entries | Σ notl (USD) |
|---|---|---|
| 202508 | 91,656 | 1.081e10 |
| 202509 | 85,856 | 7.469e9 |
| 202510 | 121,381 | 7.468e9 |
| 202511 | 116,780 | 6.602e9 |
| 202512 | 94,036 | 5.274e9 |
| 202601 | 73,323 | 4.472e9 |
| 202602 | 61,116 | 3.700e9 |
| 202603 | 48,043 | 3.941e9 |
| 202604 | 38,874 | 2.520e9 |
| 202605 | 37,950 | 2.323e9 |
| 202606 | 43,601 | 3.120e9 |

Entry count roughly halves from the Oct 2025 peak (121,381) to the May 2026 trough (37,950), with a
partial rebound in June 2026 (43,601). Aggregate notional declines even faster and more monotonically
(from 1.08e10 in Aug 2025 to 2.32e9 in May 2026, a ~4.6x drop) — later months feature both fewer AND
smaller entries.

**Entries by ym × coin (count), full breakdown:**

| ym | BTC | ETH | HYPE | SOL |
|---|---|---|---|---|
| 202508 | 22,699 | 38,369 | 12,688 | 17,900 |
| 202509 | 26,921 | 23,326 | 15,857 | 19,752 |
| 202510 | 49,142 | 29,964 | 18,792 | 23,483 |
| 202511 | 56,110 | 26,560 | 14,648 | 19,462 |
| 202512 | 46,360 | 20,943 | 10,543 | 16,190 |
| 202601 | 36,361 | 14,401 | 9,404 | 13,157 |
| 202602 | 31,865 | 12,282 | 8,626 | 8,343 |
| 202603 | 26,520 | 8,934 | 7,020 | 5,569 |
| 202604 | 21,545 | 8,033 | 5,594 | 3,702 |
| 202605 | 17,942 | 5,710 | 10,615 | 3,683 |
| 202606 | 20,653 | 7,337 | 11,495 | 4,116 |

**Notable composition drift (flag for narrative, not just a chart caption):** BTC's share of monthly entry
count climbs steadily from 24.8% (Aug 2025) to 47.4% (Jun 2026), while ETH's share falls from 41.9% to
16.8% and SOL's from 19.5% to 9.4% over the same window. HYPE dips then partially recovers late (10,615
and 11,495 entries in the last two months vs. a low of 5,594 in Apr 2026 — the only coin with a late-window
uptick, likely coincident with HYPE's continued listing/liquidity growth). This means later months (esp.
Apr-Jun 2026) are increasingly BTC/HYPE-dominated and thinner overall — any month-over-month or regime
comparison should control for/disclose this shift rather than treat the panel as coin-composition-stable.

### 6. Coin share of volume vs. count

| coin | n (count) | Σ notl (USD) | count share | notl share |
|---|---|---|---|---|
| BTC | 356,118 | 3.193e10 | 43.82% | 55.34% |
| ETH | 195,859 | 1.832e10 | 24.10% | 31.75% |
| HYPE | 125,282 | 3.272e9 | 15.42% | 5.67% |
| SOL | 135,357 | 4.176e9 | 16.66% | 7.24% |

Total: n=812,616, Σnotl = $5.770e10. BTC and ETH punch above their entry-count weight in volume terms
(BTC +11.5pp, ETH +7.6pp notl-share vs count-share), while HYPE and SOL punch below (HYPE −9.7pp, SOL
−9.4pp) — consistent with §1's finding that BTC/ETH tickets run larger and have fatter tails.

### 7. Regime-tag distribution

`regime` = BTC trailing-7d trend classification (BULL/BEAR/CHOP), tagged per UTC day and applied
cohort-wide (`src/cohort_K_price.py`) — i.e. this is a market-regime label, not a per-wallet or per-coin
state.

**Overall:**

| regime | n | pct |
|---|---|---|
| BEAR | 319,125 | 39.27% |
| CHOP | 317,961 | 39.13% |
| BULL | 175,530 | 21.60% |

BULL is the minority regime by entry count (~1/5 of entries); BEAR and CHOP are almost exactly split at
~39% each.

**Regime × coin:**

| coin | BEAR | BULL | CHOP |
|---|---|---|---|
| BTC | 143,113 | 79,155 | 133,850 |
| ETH | 74,664 | 42,087 | 79,108 |
| HYPE | 49,971 | 25,937 | 49,374 |
| SOL | 51,377 | 28,351 | 55,629 |

Regime mix is close to proportionally stable across coins (~40/22/38 BEAR/BULL/CHOP split per coin, no
coin wildly over/under-represented in any one regime) — i.e., the regime tag does not appear confounded
with coin composition.

### 8. Split distribution (TRAIN/TEST/embargo)

| split | n | pct |
|---|---|---|
| train | 583,032 | 71.75% |
| test | 168,468 | 20.73% |
| embargo | 61,116 | 7.52% |

(Included because it interacts directly with the temporal panel in §5 — the embargo slice is presumably
the most recent months and should be checked against the composition-drift finding above before combining
train/test EDA figures.)

---

## FIGURES-TO-MAKE

1. **Notional size histogram (log-x)** — histogram/density of `notl` on a log10 x-axis, overall and
   faceted by `coin` (4 small multiples). Source: §1 percentiles above, or re-bin `notl` with
   `pl.col("notl").log10()` into ~30 bins. X: log10(USD notional). Y: entry count or density. Caption
   should note the p50/mean gap (heavy right skew) and the BTC/ETH vs HYPE/SOL tail difference.

2. **Direction balance bar chart** — grouped bar, x=coin (+ "Overall"), two bars per group (% long, %
   short) or a single diverging bar centered at 50%. Source: §2 table. Order coins by long-share (BTC →
   SOL → ETH → HYPE) to visually foreground the monotonic long-skew story.

3. **Entries-per-wallet histogram** — histogram of `n_entries` per wallet (linear or log-x, right tail is
   long so log-x recommended), n=1,694 wallets. Source: group_by(wallet).count() on `cohort_K_entries`.
   Annotate the x-axis floor at 200 with a note "cohort selection floor, not organic."

4. **Entries-per-active-wallet-day histogram** — histogram of entries-per-(wallet,day) among the 179,402
   active wallet-days. Source: §4(a). Likely needs a log-y axis given the p50=3, max=127 spread.

5. **Active-days-per-wallet histogram** — histogram of distinct active days per wallet (n=1,694). Source:
   §4(b). Complements #4 — pair them as a 2-panel figure ("how many days active" vs "how much per active
   day").

6. **Monthly entry-count and volume time series** — dual-axis or two-panel line/bar chart, x=`ym`
   (Aug 2025–Jun 2026, 11 points), one series = entry count, one series = Σ notl. Source: §5 table.
   This is the chart that should carry the composition-drift caveat.

7. **Stacked area/bar of coin share by month** — x=`ym`, stacked bars (or 100%-stacked area) of entry count
   share by coin, to visualize the BTC-share-climbing / ETH+SOL-share-falling drift described in §5.
   Source: §5 ym×coin table, normalize each month's row to 100%.

8. **Coin share: count vs. notional (paired bar or Marimekko)** — grouped bar per coin with two bars
   (count share %, notional share %), or a single Marimekko/treemap. Source: §6 table. This is the chart
   that visualizes "BTC/ETH punch above their weight in $ terms."

9. **Regime distribution bar/pie** — simple bar (BEAR/CHOP/BULL counts and %). Source: §7 overall table.
   Optionally a stacked-by-coin version of the regime×coin table to show the near-uniform coin mix within
   regime (supports the "not confounded" note).

10. **(Optional) Split composition over time** — stacked bar of train/test/embargo share by `ym`, to let
    readers see visually where the embargo/test slices fall relative to the composition drift in #7.
    Source: cross of §5 ym and §8 split (not yet computed — quick group_by(['ym','split']).len() if wanted).

---

## GAPS

- **#10 above (split × ym cross-tab) was not computed** — flagged as optional; a single more group_by
  would confirm whether "embargo" = the tail months (Apr-Jun 2026) where BTC/HYPE composition dominates,
  which matters for interpreting any train-vs-test EDA comparison done elsewhere in the report.
- **No wallet-level notional distribution** (i.e., total $ traded per wallet) was computed — only
  entries-per-wallet (count). If the team wants a "whale vs. small wallet" cut by dollars, that is a
  separate `group_by(wallet).agg(notl.sum())` query, not done here (still light/in-scope if needed later).
- **Percentiles use polars' default `linear` interpolation** — noted explicitly in each table header;
  fine for descriptive EDA, but flag if any downstream figure needs a specific quantile convention to
  match other sections of the report.
- **`notl` is USD notional per entry, not signed by direction** — the direction (§2) and size (§1)
  distributions are reported separately; a signed-notional (long positive / short negative) view was
  not computed here since it wasn't in the requested list, but could be added trivially
  (`notl * dir`) if the team wants a single "net directional flow" figure.
- Did not cross entries-per-wallet (§3) against coin (i.e., whether the same wallets that are prolific
  overall concentrate in one coin) — out of scope for this behavioral-distributions pass; would belong
  with a wallet-concentration/HHI section if the team wants it.
