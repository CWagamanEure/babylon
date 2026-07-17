# BACKTEST — DESCRIPTIVE BOOK MECHANICS (frozen candidates, burned folds 202511-202606)

**DESCRIPTIVE ONLY.** Burned-fold stamp: all 8 folds (202511-202606) were consumed by the
construction/selection studies; nothing here is out-of-sample and no sizing variant is
crowned by argmax. Frozen specs (no selection/design changes):

- Book A: top-100 by t_stat from informedness pool (frozen-133 excluded), cached ksweep entries (flat taker opens, notl>=$250), alt coins test-month ADV>=$10M, hold 1h, RT 21.5bp (20 fee + 1.5 lag-slip)
- Book B: cached majors_native selections/entries rk<30 (BTC/ETH/SOL/HYPE), hold 8h, RT 5.5bp (4 fee + 1.5 lag-slip)
- Px basis: asset_ctx mid ASOF <=90s both ends (baked into cached mk/mk8); unevaluable dropped
- Position rules: max 1 concurrent per (wallet,coin); max $50k gross per coin; skip beyond cap
- Costs: A RT = 21.5bp, B RT = 5.5bp; gross AND net reported.
- Sizing: S1 fixed $5k/entry; S2 $25k/day per selected wallet split equally across its that-day candidate entries in the book (pre skip rules); S3 $5k * clip(20bp / trailing-30d daily close vol bp, 0.2, 3); >=20 return obs in [D-30,D-1] else factor 1.0
- Archetype gate: formation coin_breadth>=10, taker_share in [0.2,0.7], active days >=100 implemented as >=100 wallet-coin-day rows (literal >=100 distinct days is unsatisfiable in a 90-92 day window: 0 pass)
- Span 2025-11-01..2026-06-30 (242 days; prompt said 244, actual calendar = 242). PnL attributed to entry day (UTC). DD% of peak gross exposure (capital = max gross exposure observed). Hit rate = share of nonzero-PnL days positive.

## Stats (books x sizings)

| row | trades | net PnL $ | gross PnL $ | Sharpe | Sortino | maxDD $ | maxDD % | hit(d) | avg expo $ | max expo $ | net bp/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Book A (K100 liquid-alt @1h) / S1 | 4,011 | -19,215 | +23,904 | -2.18 | -2.84 | 28,473 | 21.09% | 0.386 | 3,453 | 135,000 | -9.6 |
| Book B (K30 majors @8h) / S1 | 1,643 | +10,691 | +15,209 | 1.02 | 1.79 | 9,168 | 20.37% | 0.445 | 11,315 | 45,000 | +13.0 |
| Combined (A+B) / S1 | 5,654 | -8,523 | +39,113 | -0.64 | -0.95 | 15,508 | 10.7% | 0.407 | 14,768 | 145,000 | -3.0 |
| Book A ARCHETYPE-GATED / S1 | 1,281 | -3,157 | +10,614 | -1.04 | -1.65 | 7,092 | 17.73% | 0.422 | 1,103 | 40,000 | -4.9 |
| Book A (K100 liquid-alt @1h) / S2 | 3,683 | -57,264 | +7,040 | -3.99 | -4.94 | 64,585 | 44.29% | 0.339 | 5,150 | 145,833 | -19.1 |
| Book B (K30 majors @8h) / S2 | 1,582 | -29,527 | -23,347 | -2.51 | -3.23 | 31,819 | 34.4% | 0.408 | 15,477 | 92,500 | -26.3 |
| Combined (A+B) / S2 | 5,265 | -86,791 | -16,307 | -4.67 | -5.51 | 90,280 | 51.51% | 0.353 | 20,627 | 175,278 | -21.1 |
| Book A ARCHETYPE-GATED / S2 | 1,281 | -18,529 | +3,624 | -3.27 | -3.87 | 22,770 | 26.02% | 0.422 | 1,774 | 87,500 | -18.0 |
| Book A (K100 liquid-alt @1h) / S3 | 4,068 | -6,276 | +3,339 | -2.49 | -2.94 | 8,975 | 30.95% | 0.386 | 770 | 29,000 | -14.0 |
| Book B (K30 majors @8h) / S3 | 1,643 | +2,138 | +3,042 | 1.02 | 1.79 | 1,834 | 20.37% | 0.445 | 2,263 | 9,000 | +13.0 |
| Combined (A+B) / S3 | 5,711 | -4,138 | +6,381 | -1.28 | -1.68 | 5,535 | 17.3% | 0.427 | 3,033 | 32,000 | -6.8 |
| Book A ARCHETYPE-GATED / S3 | 1,281 | -2,351 | +652 | -2.16 | -2.43 | 3,045 | 30.45% | 0.408 | 241 | 10,000 | -16.8 |

## Monthly PnL — Combined S1

| month | trades | gross $ | net $ |
|---|---|---|---|
| 202511 | 1,365 | +14,071 | +1,789 |
| 202512 | 445 | +772 | -2,652 |
| 202601 | 667 | +5,645 | +363 |
| 202602 | 264 | +1,755 | -355 |
| 202603 | 355 | +2,448 | -248 |
| 202604 | 672 | +4,740 | -1,204 |
| 202605 | 530 | +6,732 | +2,778 |
| 202606 | 1,356 | +2,951 | -8,994 |

## S2 composition (gross mk bp by wallet-day candidate-entry count)

S2 gives $25k/cnt per entry, so single-entry wallet-days get the largest size.

```{
 "A": {
  "1-1": {
   "n": 598,
   "mean_gross_mk_bp": -1.8
  },
  "2-3": {
   "n": 1267,
   "mean_gross_mk_bp": -4.8
  },
  "4-10": {
   "n": 1802,
   "mean_gross_mk_bp": 23.0
  },
  "11-inf": {
   "n": 1214,
   "mean_gross_mk_bp": 38.0
  }
 },
 "B": {
  "1-1": {
   "n": 230,
   "mean_gross_mk_bp": -61.6
  },
  "2-3": {
   "n": 618,
   "mean_gross_mk_bp": -59.7
  },
  "4-10": {
   "n": 2032,
   "mean_gross_mk_bp": -32.7
  },
  "11-inf": {
   "n": 2614,
   "mean_gross_mk_bp": 98.9
  }
 }
}```

## S3 factor diagnostics

```{
 "A": {
  "median": 0.2,
  "share_at_floor_0.2": 0.962,
  "share_fallback_1.0": 0.038
 },
 "B": {
  "median": 0.2,
  "share_at_floor_0.2": 1.0,
  "share_fallback_1.0": 0.0
 }
}```

## Archetype gate diagnostics

```{
 "wallet_folds_pass": 150,
 "literal_days_pass": 0,
 "gated_A_entries": 1653,
 "total_A_entries": 4881
}```

---

# FINAL SLATE BACKTEST (burned folds 202511-202606 — DESCRIPTIVE, not out-of-sample)

**Burned-fold stamp:** all 8 folds were consumed by the construction/selection studies;
no design changes, no sizing sweep (S1 fixed $5k/entry only), nothing here is OOS.

- Book M: majors-native K30 @8h (cached majors_native entries rk<30, mk8, BTC/ETH/SOL/HYPE); RT 5.5bp (4 fee + 1.5 lag-slip) — kept at 5.5bp as in the prior backtest (backtest_book.py Book B) for consistency; the 7bp (4 + 2x1.5) variant is NOT used
- Book G: GATED-ALT @8h — arm-T E1 alt flat taker opens (exact termstructure_by_archetype spec, regenerated with coin/ts and verified against that cache), grinder-archetype wallets only (census kmeans cluster 2, post-hoc pooled labels), notional >= $250, coin ADV >= $10M computed over the fold's FORMATION months from lake wallet_coin_day (trailing, honest — test-month ADV not used); RT 21.5bp (20 + 1.5)
- S1 fixed $5k/entry only; max 1 concurrent per (wallet,coin); $50k gross per coin cap; hold 8h both books
- entry day (UTC); zero-PnL days included; DD% of peak gross expo; span 2025-11-01..2026-06-30 (242 days). Hit rate = share of nonzero-PnL days positive.

## Stats

| row | trades | net PnL $ | gross PnL $ | Sharpe | Sortino | maxDD $ | maxDD % | hit(d) | avg expo $ | max expo $ | net bp/trade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Book M (majors K30 @8h, RT 5.5bp) / S1 | 1,643 | +10,691 | +15,209 | 1.02 | 1.79 | 9,168 | 20.37% | 0.445 | 11,315 | 45,000 | +13.0 |
| Book M ex-BOT (entries dropped, no re-selection) / S1 | 1,591 | +9,030 | +13,405 | 0.86 | 1.51 | 9,173 | 20.39% | 0.429 | 10,957 | 45,000 | +11.3 |
| Book G (GATED-ALT grinder @8h, RT 21.5bp) / S1 | 414 | -8,730 | -4,280 | -2.25 | -2.9 | 8,868 | 25.34% | 0.444 | 2,851 | 35,000 | -42.2 |
| Book G UNGATED (all archetypes, same screens) / S1 | 701 | -12,695 | -5,159 | -2.74 | -3.41 | 12,833 | 21.39% | 0.45 | 4,828 | 60,000 | -36.2 |
| COMBINED (M + G gated) / S1 | 2,057 | +1,961 | +10,930 | 0.17 | 0.27 | 15,516 | 20.69% | 0.442 | 14,167 | 75,000 | +1.9 |

## Monthly net PnL — COMBINED S1

| month | trades | gross $ | net $ |
|---|---|---|---|
| 202511 | 414 | -7,466 | -9,525 |
| 202512 | 231 | -3,724 | -4,848 |
| 202601 | 365 | +6,961 | +4,925 |
| 202602 | 92 | +2,020 | +1,759 |
| 202603 | 199 | +3,079 | +2,060 |
| 202604 | 167 | +3,007 | +2,492 |
| 202605 | 237 | +11,196 | +10,392 |
| 202606 | 352 | -4,142 | -5,294 |

## Gate delta (Book G grinder gate vs ungated)

```{
 "gated_net_usd": -8730.05,
 "ungated_net_usd": -12695.21,
 "gated_net_bp": -42.17,
 "ungated_net_bp": -36.22
}```

## Book G cache verification (regenerated E1 vs frozen termstructure cache)

```[
 {
  "fold": 202511,
  "n_new": 564,
  "n_ref": 564,
  "n_eval_new": 564,
  "n_eval_ref": 564,
  "avg_mk8_new": 0.998023,
  "avg_mk8_ref": 0.998023,
  "match": true
 },
 {
  "fold": 202512,
  "n_new": 4080,
  "n_ref": 4080,
  "n_eval_new": 4062,
  "n_eval_ref": 4062,
  "avg_mk8_new": 29.417598,
  "avg_mk8_ref": 29.417598,
  "match": true
 },
 {
  "fold": 202601,
  "n_new": 1653,
  "n_ref": 1653,
  "n_eval_new": 1640,
  "n_eval_ref": 1640,
  "avg_mk8_new": 29.81372,
  "avg_mk8_ref": 29.81372,
  "match": true
 },
 {
  "fold": 202602,
  "n_new": 1933,
  "n_ref": 1933,
  "n_eval_new": 1916,
  "n_eval_ref": 1916,
  "avg_mk8_new": 70.994591,
  "avg_mk8_ref": 70.994591,
  "match": true
 },
 {
  "fold": 202603,
  "n_new": 874,
  "n_ref": 874,
  "n_eval_new": 865,
  "n_eval_ref": 865,
  "avg_mk8_new": 80.133495,
  "avg_mk8_ref": 80.133495,
  "match": true
 },
 {
  "fold": 202604,
  "n_new": 667,
  "n_ref": 667,
  "n_eval_new": 662,
  "n_eval_ref": 662,
  "avg_mk8_new": 37.025315,
  "avg_mk8_ref": 37.025315,
  "match": true
 },
 {
  "fold": 202605,
  "n_new": 586,
  "n_ref": 586,
  "n_eval_new": 564,
  "n_eval_ref": 564,
  "avg_mk8_new": 19.272324,
  "avg_mk8_ref": 19.272324,
  "match": true
 },
 {
  "fold": 202606,
  "n_new": 1477,
  "n_ref": 1477,
  "n_eval_new": 1455,
  "n_eval_ref": 1455,
  "avg_mk8_new": -32.014141,
  "avg_mk8_ref": -32.014141,
  "match": true
 }
]```

---

# RECONCILIATION — wallet-equal robust stats vs entry-weighted dollar books (burned folds 202511-202606)

**Label: RECONCILIATION.** Explains why two measurements of the same burned data disagree
(K100 liquid-alt @1h robust +15.3 CI>0 and grinder @8h robust +65.5 CI>0 vs negative dollar
books). No new selection; burned-fold stamp applies; the within-day/burstiness variants are
post-hoc conditioning on burned data, not deployable claims. 2000-rep day-block bootstrap,
seed 20260716. Artifact: `data/derived/copy_cohort/reconciliation_report.json`.

## 1. CIs on the final-slate dollar books

| book | n | net bp/tr | boot CI (bp) | net $ | boot CI ($) | p(bp>0) | p(bp>20) |
|---|---|---|---|---|---|---|---|
| Book M (majors K30 @8h, 5.5bp) | 1,643 | +13.0 | [−17.9, +42.1] | +10,691 | [−14,391, +34,589] | 0.78 | 0.30 |
| Book G (gated-alt grinder @8h, 21.5bp) | 414 | −42.2 | [−86.8, +1.4] | −8,730 | [−17,899, +278] | 0.029 | 0.002 |

Book G's −42 is *marginally* indistinguishable from 0 (CI upper edge +1.4) but **firmly
excludes +20** (p=0.002) — the 414-entry cell CAN resolve that the book is not trading the
robust stat's +65 surface. Book M remains an underpowered positive (CI spans 0 and +20 alike).

## 2. Book G by wallet-fold entry count (H-a test)

**H-a refuted as stated:** the dollar book was NOT poisoned by sparse wallet-folds — 99.3%
of accepted entries (411/414, 18/21 wallet-folds) come from wf-count >= 3. The wf>=3 subset
in dollars is −39.4bp net [−82.9, +8.9] (gross −17.9), while the wallet-fold-EQUAL winsorized
gross on those same accepted trades is **+18.4bp**. The stat-vs-dollar gap inside the book is
weighting: one wallet (0xa1b6d8ef…) is 56% of accepted entries across 3 folds at −26..−41bp
gross; equal-weighting dilutes it 3/18, entry-weighting does not.

## 2b. Stage decomposition of the grinder +65.5 → −42 gap

robust wallet-fold-equal gross bp at each stage (entry-weighted raw in parens):

| stage | n entries | robust wf-equal | entry-weighted |
|---|---|---|---|
| 0: full E1 >=\$250 grinder cell (the stat) | 1,776 | **+65.5** | +40.5 |
| 1: + trailing ADV>=\$10M screen | 930 | +54.0 | +13.9 |
| 2: + skip rules (max-1-concurrent/(wallet,coin), 8h) → accepted | 414 | **−3.6** | −20.7 |

**The load-bearing stage is the skip-rule dedup, not the wf>=3 filter and not the ADV screen.**
The robust stat's positive surface lives disproportionately in the 2nd..Nth overlapping entries
inside an 8h hold window — events a 1-position-per-(wallet,coin) book cannot take because it is
already in the position. What the book CAN take (the first entry of each window) has ~zero
wallet-equal gross and negative entry-weighted gross.

## 3. Ex-ante activity-conditioned rebuilds (S1 $5k, same skip rules)

Gate ii: formation (trailing 3mo, lake open_entries) >= 0.5 opens/day. Gate ii-b (trait):
formation share of entries on >=3-entry days >= 0.5. Gate iii: ii + entry taken only after
the wallet already made >=2 candidate entries earlier that UTC day.

| book / variant | n | gross bp | net bp | boot CI (bp) | SR |
|---|---|---|---|---|---|
| K100 alt @1h / (i) all | 4,011 | +11.9 | −9.6 | [−20.8, +0.2] | −2.18 |
| K100 alt @1h / (ii) activity | 3,884 | +13.0 | −8.5 | [−20.0, +2.6] | −1.87 |
| K100 alt @1h / (ii-b) burstiness trait | 3,836 | +11.6 | −9.9 | [−21.1, +0.3] | −2.19 |
| K100 alt @1h / (iii) + within-day | 1,870 | +27.3 | **+5.8** | [−6.7, +17.4] | +1.17 |
| grinder @8h / (i) all | 414 | −20.7 | −42.2 | [−84.3, +4.2] | −2.25 |
| grinder @8h / (ii) activity | 411 | −21.3 | −42.8 | [−85.2, +2.5] | −2.26 |
| grinder @8h / (ii-b) burstiness trait | 395 | −21.4 | −42.9 | [−87.2, +1.3] | −2.31 |
| grinder @8h / (iii) + within-day | 251 | −11.2 | −32.7 | [−96.1, +32.5] | −1.25 |

Burstiness as a WALLET TRAIT does nothing (ii-b ≈ (i) in both books; formation-burstiness vs
forward wallet-fold markout: K100 Pearson −0.01 / Spearman +0.12 on 173 wf; grinder −0.38 /
−0.16 on 21 wf — if anything negative). Burstiness as a DAY-STATE is the only condition that
moves dollars toward the stats: K100 @1h flips −9.6 → +5.8 net (gross +11.9 → +27.3, SR +1.17),
consistent with the S2-composition and decay-anatomy busy-day findings. Its CI still includes 0
(underpowered positive, post-hoc conditioning on burned folds — NOT deployable, registered as
descriptive support for the already-registered activity-conditional forward hypothesis).

## 4. Verdict

The stat-vs-dollar disagreement is **explained, and the gap persists for any implementable
book**: (a) K100 @1h was never a net puzzle — the robust stat is GROSS (+15.3 [+3.6, +28.6])
and does not clear 21.5bp RT any more than the book's +11.9 gross does; stat and book roughly
agree gross. (b) grinder @8h +65.5 describes a surface a dollar book cannot trade: ~half the
gap is entry-vs-equal weighting (one wallet = 56% of entries, negative), and the decisive rest
is that the edge sits in overlapping repeat entries inside the 8h window, removed by the
max-1-concurrent rule (robust stat on tradable accepted entries = −3.6). No ex-ante activity
condition revives either alt book net of 21.5bp with CI > 0. The one live residual: within-day
burst-state conditioning turns the K100 @1h book from CI-excludes-+20-negative to an
underpowered positive (+5.8 [−6.7, +17.4]) — direction consistent, significance absent;
forward paper evidence, not a burned-fold rescue. Alt DOLLAR-book death at these costs stands;
the positive robust stats stand as descriptions of an untradeable (overlap + equal-weight)
surface.


# PYRAMID-ALT — DESCRIPTIVE MECHANICS VERIFICATION (frozen ladder, burned folds)

**STAMP: DESCRIPTIVE MECHANICS VERIFICATION — burned folds 202511-202606; frozen spec PYRAMID_ALT_PREREG.md; no variants, no parameter exploration, nothing tuned from this result; evaluation of the arm is FORWARD ONLY (paper trader).**

Spec: PYRAMID_ALT_PREREG.md lead arm — t_v1 top-100 (frozen-133 + taker<0.1 excluded), liquid
alts (trailing 3-mo formation ADV >= $10M), signals >= $250; ladder WATCH/ENTER/ADD/ADD
($2.5k units, max 3), exit all at last-filled-add + 8h; 21.5bp RT/unit. Deviations (recorded):
no trader-exit hard stop, no maker shadow, entry at next asset_ctx mid (not tape print).

| metric | value |
|---|---|
| units (theses) | 3,668 (1,713; per-thesis 1/2/3 = 595/281/837) |
| gross / net PnL $ | +19,948 / +233 |
| gross / net bp per unit | +21.8 / +0.2 |
| net bp/unit day-block boot CI (2000) | [-27.5, +25.9], P(>0)=0.512 |
| ann Sharpe / Sortino (daily, 242d) | 0.02 / 0.03 |
| max drawdown $ | -14,416 |
| avg / max gross exposure $ | 13,735 / 142,500 |
| units/day; avg hold | 15.16 ; 8.7h |

Funnel: 567,691 eligible signals (5,147 opens + 562,544 adds;
2,814 add-fills deduped into their flat-open) -> 3,049 watches
(1,023 expired) -> units by rung {'1': 1713, '2': 1118, '3': 837}; after-4th ignored
56,596; entry-px misses 9; cap skips book/coin
0/29; flip units 340; exit flags {'0': 1696, '2': 17}
(0=backward<=90s, 1=fwd<=10min, 2=stale-backward, 3=none).

| fold | signals | units | theses | gross $ | net $ | net bp/u |
|---|---|---|---|---|---|---|
| 202511 | 95,813 | 1,073 | 443 | -1,113 | -6,881 | -25.65 |
| 202512 | 63,107 | 444 | 185 | +717 | -1,670 | -15.04 |
| 202601 | 96,043 | 534 | 221 | -217 | -3,087 | -23.12 |
| 202602 | 105,952 | 203 | 84 | +1,909 | +818 | 16.12 |
| 202603 | 75,212 | 278 | 122 | +178 | -1,316 | -18.94 |
| 202604 | 36,842 | 453 | 228 | +14,582 | +12,147 | 107.26 |
| 202605 | 40,840 | 245 | 151 | -2,147 | -3,464 | -56.55 |
| 202606 | 53,882 | 438 | 279 | +6,039 | +3,685 | 33.65 |

Artifact: `data/derived/copy_cohort/pyramid_mechanics_report.json`.


# CONSENSUS-GATED BACKTEST — descriptive book mechanics (burned folds)

**STAMP: DESCRIPTIVE BOOK MECHANICS — burned folds 202511-202606; consensus gate adopted AFTER viewing the consensus decomposition => all numbers EX-POST-CONDITIONED, NOT quotable as forward evidence; only the two pre-named gate variants run (no sweeps).**

Gate variants were named after viewing the consensus decomposition (WALLET_ATTRIBUTION.md grid) — these are the SAME entries re-weighted by an ex-post-chosen condition; the only legitimate use is sizing the forward paper expectation. S1 sizing: $2.5k/unit (alt ladder caps inside sim) and $2.5k/entry majors (wallet_attribution equal-unit convention), max 1 concurrent per (wallet,coin) + $50k/coin cap on majors; costs 21.5bp alt / 5.5bp majors RT.

| row | n (%ungated) | net $ | gross $ | bp/tr | boot CI95 | SR | Sortino | maxDD $ (%maxExp) | hit | avg/max exp $ |
|---|---|---|---|---|---|---|---|---|---|---|
| 1. Pyramid-alt — ungated | 2,319 (100.0%) | +9,487 | +21,951 | +16.4 | [-21.7, +52.8] P>0=0.79 | 1.04 | 1.62 | -5,669 (6.3%) | 0.484 | 8,920 / 90,000 |
| 2. Pyramid-alt — CROWD gate | 1,232 (53.1%) | +11,061 | +17,683 | +35.9 | [-21.1, +91.4] P>0=0.89 | 1.45 | 2.3 | -6,565 (7.29%) | 0.569 | 4,616 / 90,000 |
| 3. Pyramid-alt — SMART gate | 933 (40.2%) | +8,808 | +13,822 | +37.8 | [-36.3, +110.2] P>0=0.84 | 1.24 | 1.91 | -7,959 (8.84%) | 0.561 | 3,496 / 90,000 |
| 4. Majors K30@8h — ungated | 1,643 (100.0%) | +5,346 | +7,605 | +13.0 | [-16.9, +44.0] P>0=0.80 | 1.02 | 1.79 | -4,265 (18.96%) | 0.445 | 5,658 / 22,500 |
| 5. Majors K30@8h — CROWD gate | 1,194 (72.7%) | +5,656 | +7,298 | +18.9 | [-22.2, +58.6] P>0=0.82 | 1.11 | 1.98 | -4,255 (18.91%) | 0.409 | 4,112 / 22,500 |
| 6. Majors K30@8h — SMART gate | 1,074 (65.4%) | +6,360 | +7,836 | +23.7 | [-19.4, +66.5] P>0=0.87 | 1.28 | 2.28 | -4,266 (21.33%) | 0.444 | 3,698 / 20,000 |
| 7. COMBINED — SMART gate | 2,007 | +15,167 | +21,659 | +30.2 | [-7.2, +69.8] P>0=0.94 | 1.89 | 3.12 | -9,166 (8.94%) | 0.521 | 7,194 / 102,500 |

Monthly net PnL, row 7 (COMBINED smart): 202511: -4,510; 202512: -1,964; 202601: +2,350; 202602: +1,153; 202603: +1,793; 202604: +9,898; 202605: +3,890; 202606: +2,557

Majors book funnel (candidates -> skips): B_ungated: 5,494 cand, 3,851 concurrent-skip, 0 cap-skip; B_crowd: 4,354 cand, 3,160 concurrent-skip, 0 cap-skip; B_smart: 3,972 cand, 2,898 concurrent-skip, 0 cap-skip

Artifact: `data/derived/copy_cohort/gated_backtest_report.json`.


# CONSENSUS-GATED BACKTEST — descriptive book mechanics (burned folds) [2026-07-17 AUDIT-FIX RE-PRINT]

**STAMP: DESCRIPTIVE BOOK MECHANICS — burned folds 202511-202606; consensus gate adopted AFTER viewing the consensus decomposition => all numbers EX-POST-CONDITIONED, NOT quotable as forward evidence; only the two pre-named gate variants run (no sweeps).**

Gate variants were named after viewing the consensus decomposition (WALLET_ATTRIBUTION.md grid); the only legitimate use is sizing the forward paper expectation. **Gate ordering (audit fix 2026-07-17):** concurrency/dedup + coin-cap acceptance runs FIRST on the full majors stream; the gated rows (5, 6) are then pure SUBSETS of the ungated book's accepted entries — so the 'same entries' claim now actually holds. The earlier re-print's gated majors rows applied the gate BEFORE acceptance, which is burst-entangled (removing an earlier entry frees the (wallet,coin) slot / cap headroom and admits entries the ungated book skipped) — that prose claimed 'the SAME entries', which was false for book B; the old ordering is retained only as the labeled rows 5b/6b for comparison. Book A's gate was already a pure unit filter on the simulated stream. S1 sizing: $2.5k/unit (alt ladder caps inside sim) and $2.5k/entry majors (wallet_attribution equal-unit convention), max 1 concurrent per (wallet,coin) + $50k/coin cap on majors; costs 21.5bp alt / 5.5bp majors RT. code_commit 1535c74-dirty.

| row | n (%ungated) | net $ | gross $ | bp/tr | boot CI95 | SR | Sortino | maxDD $ (%maxExp) | hit | avg/max exp $ |
|---|---|---|---|---|---|---|---|---|---|---|
| 1. Pyramid-alt — ungated | 2,319 (100.0%) | +9,487 | +21,951 | +16.4 | [-21.7, +52.8] P>0=0.79 | 1.04 | 1.62 | -5,669 (6.3%) | 0.484 | 8,920 / 90,000 |
| 2. Pyramid-alt — CROWD gate | 1,232 (53.1%) | +11,061 | +17,683 | +35.9 | [-21.1, +91.4] P>0=0.89 | 1.45 | 2.3 | -6,565 (7.29%) | 0.569 | 4,616 / 90,000 |
| 3. Pyramid-alt — SMART gate | 933 (40.2%) | +8,808 | +13,822 | +37.8 | [-36.3, +110.2] P>0=0.84 | 1.24 | 1.91 | -7,959 (8.84%) | 0.561 | 3,496 / 90,000 |
| 4. Majors K30@8h — ungated | 1,643 (100.0%) | +5,346 | +7,605 | +13.0 | [-16.9, +44.0] P>0=0.80 | 1.02 | 1.79 | -4,265 (18.96%) | 0.445 | 5,658 / 22,500 |
| 5. Majors K30@8h — CROWD gate (subset of accepted) | 1,114 (67.8%) | +6,740 | +8,272 | +24.2 | [-17.7, +65.1] P>0=0.87 | 1.36 | 2.47 | -4,255 (21.27%) | 0.425 | 3,836 / 20,000 |
| 6. Majors K30@8h — SMART gate (subset of accepted) | 981 (59.7%) | +6,692 | +8,040 | +27.3 | [-19.2, +72.4] P>0=0.89 | 1.42 | 2.59 | -4,239 (21.2%) | 0.445 | 3,378 / 20,000 |
| 5b. Majors K30@8h — CROWD gate-pre-concurrency (burst-entangled) | 1,194 (72.7%) | +5,656 | +7,298 | +18.9 | [-21.9, +58.1] P>0=0.82 | 1.11 | 1.98 | -4,255 (18.91%) | 0.409 | 4,112 / 22,500 |
| 6b. Majors K30@8h — SMART gate-pre-concurrency (burst-entangled) | 1,074 (65.4%) | +6,360 | +7,836 | +23.7 | [-18.3, +67.4] P>0=0.85 | 1.28 | 2.28 | -4,266 (21.33%) | 0.444 | 3,698 / 20,000 |
| 7. COMBINED — SMART gate | 1,914 | +15,499 | +21,863 | +32.4 | [-8.1, +69.0] P>0=0.95 | 1.97 | 3.25 | -8,872 (8.87%) | 0.526 | 6,874 / 100,000 |

Monthly net PnL, row 7 (COMBINED smart): 202511: -4,261; 202512: -1,788; 202601: +2,161; 202602: +1,341; 202603: +1,557; 202604: +10,027; 202605: +3,830; 202606: +2,631

Majors book funnel (candidates -> skips; subset-gate rows have zero skips by construction): B_ungated: 5,494 cand, 3,851 concurrent-skip, 0 cap-skip; B_crowd: 1,114 cand, 0 concurrent-skip, 0 cap-skip; B_smart: 981 cand, 0 concurrent-skip, 0 cap-skip; B_crowd_preconc: 4,354 cand, 3,160 concurrent-skip, 0 cap-skip; B_smart_preconc: 3,972 cand, 2,898 concurrent-skip, 0 cap-skip

Artifact: `data/derived/copy_cohort/gated_backtest_report.json`.
