# Arm-T cohort identity census — WHO are these wallets?

**Label: DESCRIPTIVE.** No inference; hypothesis-grade labels only. Built 2026-07-16 by
`cohort_census.py` (seed 20260716, kmeans k=5 on 8 log/z-normalized activity features).
Artifacts: `data/derived/copy_cohort/cohort_census.json`.

**Subject.** All wallets ever selected into **arm T** of the alt-universe cohorts
(`alt_universe_cohorts.json`, 8 folds 202511–202606, 30/fold = 240 memberships,
**145 distinct wallets**). Profiles from the incerto lake (`alt_universe_wallet_coin_day` +
`alt_universe_open_entries`, 202508–202606); forward copy markout joined from
`decay_anatomy_report.json` (arm T, 8h gross dir-signed markout).

Re-selection: 84 wallets selected once, 37 twice, 18 three times, 4 four times, 2 six times.
Majors = {BTC, ETH, SOL}; dust = entry notional < $20.

## Archetype table (cluster medians over 202508–202606)

| # | Archetype | n | sel (med) | total notl | PnL | fees | active d | fills/d | taker | breadth | majors% | med entry $ | dust% | copy mk bp (pooled / wallet-med) | copy n |
|---|-----------|---|-----------|-----------|-----|------|----------|---------|-------|---------|---------|-------------|-------|-----------------------------------|--------|
| 0 | **Micro dust grinder** (tiny taker accounts) | 26 | 1 | $50k | +$116 | $26 | 74 | 11 | 0.98 | 14 | 8% | $23 | 35% | +42.7 / −26.1 | 1,627 |
| 1 | **Aggressive mid-size taker** (majors+alts, liq-prone) | 35 | 1 | $9.2M | +$18.7k | $3.1k | 89 | 55 | 0.69 | 9 | 37% | $839 | 4% | −17.4 / +12.7 | 608 |
| 2 | **Diversified alt grinder** (maker-lean, high breadth) | 33 | 1 | $4.2M | +$2.3k | $1.0k | 229 | 71 | 0.37 | 34 | 10% | $132 | 5% | **+33.4 / +25.6** | **8,844** |
| 3 | **HFT / market-maker bot** (institutional scale) | 12 | 2.5 | $6.3B | +$433k | $101k | 332 | 15,583 | 0.30 | 22 | 61% | $531 | 11% | +16.7 / +5.3 | 381 |
| 4 | **Single-alt specialist** (breadth = 1, mostly HYPE) | 25 | 2 | $1.6M | +$847 | $537 | 169 | 21 | 0.43 | 1 | 0% | $352 | 4% | +6.3 / +10.1 | 374 |
| −1 | **Pure maker / no copyable entries** | 14 | 2 | $168M | +$25.6k | $19 | 199 | 275 | 0.00 | 1 | 100% | — | — | none (0 copy entries) | 0 |

(copy mk pooled = copy_n-weighted mean across the cluster's wallet-folds; wallet-med = median of
per-wallet weighted markouts among wallets that produced ≥1 copy entry.)

### Reading the table
- **Cluster 2 (diversified alt grinder) carries the forward copy markout**: 27/33 wallets produced
  copy entries, 8,844 of the 11,834 total copy entries (75%), pooled **+33 bp**, wallet-median **+26 bp**.
  This is where the arm-T copy signal actually lives.
- **Cluster 3 (HFT bots) is what the selector *persistently* re-picks** (median 2.5 selections;
  includes the $3–10B-notional wallets) — but they contribute almost no copyable entries (381) because
  their fills are maker-flow, not fresh opens. Their capday metric is real PnL, not copyable alpha.
- **Cluster 0 (micro dust)**: wallet-median markout is *negative* (−26 bp) while the pooled number is
  positive (+42.7) — one or two blowup wallets dominate; hypothesis-grade "lottery tickets", not signal.
- **Cluster 1 (aggressive takers)**: the only pooled-negative group (−17 bp); also carries essentially
  all liquidation fills in the cohort (19,107 n_liq). Selected on a hot quarter, mean-reverts.
- **−1 / pure makers** (14 wallets, incl. two 6×-selected): taker share ≈ 0, zero open_entries rows,
  majors-only, ~$168M+ notional — pure market-making bots. **Structurally uncopyable**; they are 14 of
  the 119 NO_COPY_ENTRIES wallet-folds and pure dead weight in a copy book.
- Quadrant totals (240 wallet-folds): NO_COPY_ENTRIES 119, TW_CW 43, TW_CL 27, FWD_INACTIVE 28,
  TL_CL 12, TL_CW 11.

## Part 2 — external attribution

Method: HL info API `vaultDetails` on **all 145** wallets; hypurrscan.io tags API + quoted-address
web search (Google-indexed explorers, X/Twitter, Arkham mentions) on the top-10 by re-selection.
No paid APIs.

### Headline: 12 of 145 cohort wallets are PUBLIC HYPERLIQUID VAULTS
Vaults are 10/61 (16%) of re-selected wallets vs 2/84 (2%) of one-timers — the persistent core is
disproportionately *professionalized, publicly copyable* money:

| Vault wallet | Name | Leader | sel | Archetype | copy mk bp (n) |
|---|---|---|---|---|---|
| 0xa1b6d8ef… | **PF1** | 0xb5e32ad7… | 3 | alt grinder | **+39.1 (821)** |
| 0xae6b807e… | **VaultBot V2** | 0x1d6dcb83… | 3 | single-alt (HYPE) | — (0) |
| 0xd6fa01d5… | VaultBot | same leader | 2 | aggressive taker | — (0) |
| 0xf8a5e3fd… / 0x5338fab0… / 0x58240c3a… | **HYPErQuantum / 2 / 5** | 0x146d2147… (all 3) | 2 each | single-alt | — (0) |
| 0x0e66ea30… | Pump Hunt | 0x2252bdba… | 2 | alt grinder | +25.6 (149) |
| 0xb4de3608… | AlgoTrading.capital [HR] | 0x5cb17bde… | 2 | aggressive taker | −147.0 (98) |
| 0x99c2cec0… | Makrochronios | 0xee50fa61… | 2 | aggressive taker | — (0) |
| 0x1458ab4a… | DCA $ailor | 0x1ca4d75d… | 2 | micro dust | −40.3 (22) |
| 0x565b1c32… | Mad Scientists | 0x77eea13a… | 1 | alt grinder | +83.5 (3) |
| 0x55fb9136… | Safe Volatility Farm | 0x7e5db685… | 1 | single-alt | — (0) |

Two operators run *families* the selector found independently: HYPErQuantum ×3 (one leader),
VaultBot ×2 (one leader) — the effective distinct-entity count is lower than 145.

### Top-10 by re-selection — who they are
| Wallet | sel | Archetype / dominant coins | Attribution |
|---|---|---|---|
| 0x16c95227… | 6 | pure maker; HYPE ($91M), taker 0% | anonymous — no tag anywhere |
| 0xe2990ce0… | 6 | HFT bot; $7.8B notl, BTC/ETH/HYPE, +$2.0M PnL | anonymous (institutional-scale MM) |
| 0x223537ac… | 4 | HFT bot; $3.4B, kPEPE/DOGE/XPL | anonymous |
| 0x6c30f718… | 4 | single-alt; HYPE only, $6M | anonymous |
| 0xccf59517… | 4 | alt grinder; 177 coins, taker 0.95, copy mk **+145 bp** (898) | anonymous — most interesting unlabeled wallet |
| 0xa880d6cc… | 4 | HFT bot; $10.6B, HYPE/BTC/ETH, +$543k | anonymous |
| 0x72795661… | 3 | HFT bot; $6.2B, HYPE-led | anonymous (appears only as an example address in QuickNode's Hyperliquid docs — likely coincidental/prominent flow) |
| 0x581efeac… | 3 | micro dust; $16k total notl, 105 coins | anonymous |
| 0xae6b807e… | 3 | single-alt HYPE | **"VaultBot V2"** public HL vault (~$100k AUM, automated 24/7 perp bot; drawing down at fetch time) |
| 0x0b1ace05… | 3 | pure maker; BTC only, $3.6B, taker 0% | anonymous |

Honest bottom line on attribution: **9 of the top 10 are anonymous** — no hypurrscan tags, no
Arkham/X-indexed mentions, not in the Cryexc community HL address directory. The vault check is the
only attribution channel that produced hard identities.

## Takeaways (hypothesis-grade)

1. **The persistent core is bots, not humans.** Re-selected wallets are dominated by HFT/MM bots,
   pure makers, and public vault strategies. The capday selector finds *real money-makers*, but the
   biggest of them make money in ways a taker-copy book cannot touch (maker flow, 0% taker share).
2. **The copyable signal is concentrated in one archetype** — the diversified alt grinder (cluster 2):
   75% of all copy entries and pooled +33 bp. A paper trader could plausibly *weight* (or gate on)
   this profile: breadth ≥ ~10 coins, taker share 0.2–0.7, 100+ active days, mid-hundreds entry size.
3. **Cheap dead-weight filter:** drop wallets with taker share ≈ 0 / no open entries at selection time
   (14/145, incl. two of the most re-selected). They can never produce a copy entry; removing them
   costs nothing and concentrates the book.
4. **Vaults are a parallel, zero-infrastructure channel:** 12 cohort members are literally public HL
   vaults (PF1: 3× selected, +39 bp on 821 copy entries). If the selector keeps finding them, direct
   vault deposits replicate the strategy without any copy-execution stack — worth a look as a
   benchmark/deployment shortcut.
5. Caveat: all markout splits above are post-hoc descriptive cuts of an already-selected cohort —
   archetype-conditional copying is a *new hypothesis* that needs its own preregistered, walk-forward
   test before any deployment claim.

## Part 3 — markout term structure by archetype (DESCRIPTIVE, 2026-07-16)

**Question (user's thesis):** do HFT/bot wallets drag the pooled markout term structure toward
short horizons, so that ex-HFT the curve peaks later (8–24h)?

**Method:** `termstructure_by_archetype.py` — exact rebuild of `construction_study.py`'s E1 cell
(arm-T cohort alt flat taker opens, gross dir-signed bp vs local asset_ctx mid, ≤90s staleness,
horizons {1h,4h,8h,24h,48h}), each entry tagged with its wallet's census archetype. Robust spec per
cell: winsor p95 |mk| within cell, wallet-folds ≥3 entries, wallet-fold-equal mean; 1000-rep
wallet-cluster bootstrap. Sanity: pooled/all reproduces `construction_report.json` E1 exactly.
Artifact: `data/derived/copy_cohort/termstructure_by_archetype_report.json`.

### All entries — robust bp [95% boot CI]

| slice | 1h | 4h | 8h | 24h | 48h | n(8h) | share |
|---|---|---|---|---|---|---|---|
| **pooled** | +21.8 [+7.1,+39.5] | +18.8 [−9.6,+49.3] | +23.0 [−8.2,+58.6] | +7.2 [−46.8,+62.1] | +10.9 [−63.4,+93.1] | 11,728 | 100% |
| dust | +14.3 [−4.2,+34.3] | +18.6 [−12.9,+44.3] | −1.2 [−33.7,+29.9] | +39.3 [−84.9,+174.5] | +31.6 [−141.8,+280.8] | 1,621 | 13.8% |
| midtaker | +40.0 [−4.6,+104.7] | +38.3 [−57.6,+150.8] | +33.2 [−98.3,+203.4] | −7.1 [−178.5,+187.2] | +46.1 [−98.7,+211.1] | 604 | 5.2% |
| grinder | +25.4 [+2.6,+53.9] | +24.7 [−16.6,+62.8] | +35.2 [−4.5,+74.6] | +38.4 [−37.5,+108.9] | +48.3 [−59.4,+173.3] | 8,766 | 74.7% |
| HFT bot | +3.4 [−23.8,+18.6] | −11.2 [−36.8,+7.4] | +8.9 [−8.4,+24.6] | **−67.1 [−107.1,−9.1]** | **−120.6 [−217.0,−42.9]** | 377 | 3.2% |
| specialist† | −0.1 | −8.0 | −9.8 | −49.7 | −89.5 | 360 | 3.1% |
| pure maker | — | — | — | — | — | 0 | 0% |
| **pooled ex-{HFT,dust}** | +29.6 [+8.0,+57.2] | +31.5 [−12.3,+76.4] | +34.6 [−15.4,+92.1] | +23.3 [−48.9,+92.6] | +46.8 [−46.9,+153.7] | 9,730 | 83.0% |

### ≥$250-notional entries (deployable slice)

| slice | 1h | 4h | 8h | 24h | 48h | n(8h) | share |
|---|---|---|---|---|---|---|---|
| **pooled** | +15.8 [−5.6,+40.2] | +19.9 [−16.5,+56.5] | +39.8 [−1.8,+81.8] | +57.5 [−12.7,+128.6] | +35.1 [−73.2,+159.4] | 2,611 | 100% |
| midtaker | +23.8 [−6.5,+75.1] | +21.7 [−51.2,+117.6] | +26.3 [−61.5,+129.1] | +49.5 [−85.6,+220.7] | +30.0 [−143.8,+287.0] | 374 | 14.3% |
| grinder | +18.0 [−14.5,+47.2] | +28.4 [−30.7,+75.2] | **+65.5 [+33.7,+103.1]** | **+102.0 [+3.9,+203.3]** | +138.3 [−23.5,+309.6] | 1,776 | 68.0% |
| HFT bot | +1.3 [−35.0,+30.2] | −2.2 [−82.8,+70.6] | +2.4 [−94.3,+90.0] | −14.3 [−43.1,+40.9] | −179.0 [−301.5,−19.2] | 195 | 7.5% |
| specialist† | −1.1 | −6.5 | −7.1 | −54.9 | −90.2 | 266 | 10.2% |
| **pooled ex-{HFT,dust}** | +19.6 [−4.8,+47.9] | +26.0 [−21.5,+73.9] | **+50.4 [+5.2,+104.1]** | +72.3 [−7.3,+163.2] | +82.0 [−34.6,+192.9] | 2,416 | 92.5% |

† specialist cells rest on **2 wallets** (4 wallet-folds); their tight CIs are a bootstrap artifact
of a degenerate cluster count, not precision. HFT cells rest on 4–6 wallets. Dust has zero ≥$250
entries by construction.

### Reading

1. **The thesis is directionally supported, but the mechanism is not dilution-by-count.** HFT is only
   3.2% of pooled entries (dust 13.8%) — too few to drag the pooled curve by weight. What HFT entries
   *do* have is strongly negative long-horizon markouts (24h −67, 48h −121, both CIs excluding 0 in
   the all-entries cut): they actively pull the long end down. Removing HFT+dust lifts the long end
   (24h +7.2 → +23.3; 48h +10.9 → +46.8) far more than the short end (1h +21.8 → +29.6).
2. **"Peaks later" holds cleanly only in the ≥$250 slice.** All-entries ex-{HFT,dust} is roughly flat
   +30/+31/+35 across 1h–8h (CIs heavily overlapping — no resolvable peak). In the ≥$250 slice the
   ex-{HFT,dust} curve rises monotonically to 8h–48h (+19.6 → +50.4 → +72.3 → +82.0), with 8h the
   only CI-excluding-0 cell; the pooled ≥$250 curve already peaks at 24h even *with* HFT in.
3. **The late peak is the grinder archetype, full stop.** Grinder is 68–75% of entries, and its ≥$250
   curve is the star: +65.5 [+33.7,+103.1] at 8h and +102.0 [+3.9,+203.3] at 24h — the only archetype
   whose long-horizon cells exclude 0 on the positive side. Specialist and HFT are negative at long
   horizons; the "later peak ex-bots" is really "the grinder's rising curve un-diluted."

### Caveats (all binding)
- **Burned folds** (202511–202606, reused many times) and **post-hoc clusters**: the kmeans labels were
  fit on the same window the markouts come from; archetype-conditional selection is a *new hypothesis*
  requiring its own preregistered walk-forward test. No multiplicity control across the 70 cells shown.
- **Dependent cells**: horizons overlap within an entry, archetypes share coins/months, and the pooled
  vs ex-{HFT,dust} contrast reuses 83–93% of the same entries — CI overlaps cannot be read as tests.
- Cluster wallet counts are tiny outside grinder/midtaker (specialist 2, HFT 4–6 wallets); wallet-cluster
  bootstrap CIs at those counts are unstable and (for specialist) degenerate.
- Gross markout, no costs/lag; winsor limit is cell-specific (807–2,275 bp), so cross-cell level
  comparisons inherit different clipping.

---

## Majors-native K30 book: bot-vs-human decomposition (DESCRIPTIVE, 2026-07-16)

Mirror of the alt archetype decomposition on the **majors-native K30 book** (cached
`data/derived/copy_cohort/majors_native/` selections + entries reused, no rebuild). Census kmeans
labels only cover arm-T wallets, so K30 wallets were classified **directly** with the mechanical bot
criteria over each fold's 3-month formation window (lake `wallet_coin_day`, all coins):
**BOT-LIKE iff fills/day > 1000 OR taker_share < 0.1**, else HUMAN. Script:
`research/studies/copy_cohort/majors_archetype.py` → `data/derived/copy_cohort/majors_archetype_report.json`.

**Classification.** Per fold (BOT/HUMAN of 30): 202511 7/23, 202512 9/21, 202601 10/20, 202602 6/24,
202603 7/23, 202604 7/23, 202605 5/25, 202606 1/29. Where wallets also carry census labels
(157 wallet-folds) the mechanical rule agrees 154/157: all 11 census-`hft` and all 23 census-`puremaker`
wallet-folds classify BOT; 3 disagreements (2 midtaker, 1 grinder → BOT).

**Robust wallet-fold-equal bp (winsor p95 in cell, wf>=3; 1000-rep wallet boot):**

| slice | 1h | 4h | 8h | 24h | 48h | n@1h (wallets) |
|---|---|---|---|---|---|---|
| ALL   | −0.6 [−7.3,+4.4] | +11.6 [−4.9,+26.8] | **+29.0 [+3.1,+55.4]** | +26.3 [−16.1,+70.7] | +19.0 [−40.8,+75.6] | 5,614 (51) |
| HUMAN | −0.6 [−7.5,+5.3] | +11.8 [−4.2,+25.8] | **+29.5 [+3.8,+55.0]** | +27.3 [−18.7,+76.8] | +20.4 [−35.7,+83.1] | 5,378 (48) |
| BOT   | +5.2 | −0.4 | −0.9 | −25.3 | −48.2 (all degenerate CIs) | 236 (3) |

### Read
1. **The majors 24–48h fade is NOT bot-driven.** Unlike alts (where HFT poisoned 24–48h), excluding
   bot-like wallets barely moves the majors curve: HUMAN-only still peaks at **8h (+29.5 vs +28.1
   frozen / +29.0 ALL here)** and still fades into 24h/48h. HUMAN does not peak later or meaningfully
   higher. Reason: bot-like wallets (mostly puremaker/HFT) contribute only **~4% of K30 flat taker
   opens** (236/5,614) — they dominate selection slots in some folds but not the entry stream.
2. **What bot entries there are do fade hard long-horizon** (+5.2 @1h → −48.2 @48h), directionally
   matching the alt HFT story — but only 3 wallets / 1 robust wallet survive the wf>=3 filter, so the
   BOT column is anecdote (degenerate CIs = single-wallet cells), not evidence.
3. **ALL here vs frozen `majors_native_report.json`:** point estimates match within noise (8h +29.0 vs
   +28.1); n differs slightly (5,614 vs 5,655) because this pass drops NULL markouts as NaN while the
   frozen pass's masked-array handling let ~41–405 NULL-markout rows (largest at 48h) through as
   buffer values — same conclusion either way, frozen 48h (+8.4) is mildly diluted vs +19.0 here.

### Caveats (binding)
- **Burned folds** (202511–202606), **post-hoc decomposition** of an already-reported book; no new
  selection, no multiplicity control; horizons overlap within entries and HUMAN reuses ~96% of ALL's
  entries — cells are heavily dependent, CI overlaps are not tests.
- Bot criteria are mechanical thresholds, not the census kmeans; classification is per wallet-fold.
- Gross markout vs asset_ctx mid, no lag/fee haircut; winsor limit is cell-specific.
