# Badge discovery audit (round 7) — 2026-07-03

## R7-1 [CRITICAL] (existence-stat) Cluster scheme leaves same-day cross-coin and adjacent-day same-coin dependence; a variance inflation factor of ~2 alone reproduces the 12x tail excess

**Mechanism:** Clusters are (coin, UTC day) (existence_t.py:68) but the t-stat treats cluster means as iid: t = mean/(sd/sqrt(N_clusters)) (line 73). Two dependence channels survive: (1) a wallet's same-day entries in DIFFERENT coins are separate clusters yet share market state — daily cross-alt correlation on Hyperliquid perps is routinely 0.3–0.8, so a wallet trading K coins per day has effective N shrunk by roughly (1+(K-1)*rho); (2) the markout horizon (H24, line 16, applied at line 59) EQUALS the cluster width, so an entry at 23:00 on day d and one at 01:00 on day d+1 in the same coin have ~22h-overlapping 24h return windows — adjacent same-coin day-clusters are mechanically serially correlated, and multi-day position campaigns make consecutive clusters share one directional thesis for the coin's whole trend. Month demeaning (line 70) removes only the month-level constant, not day-level or trend-level common shocks. Under zero skill, t is then ~N(0, VIF) rather than N(0,1): P(|t|>3) = 2*Phi_bar(3/sqrt(VIF)) = 1.4% at VIF=1.5 (5.3x null), 3.4% at VIF=2.0 (12.6x), 5.7% at VIF=2.5 (21x).

**Evidence:** existence_t.py:68 `key = (c, int(to[j] // DAY_MS))`; :73 `tstat = v.mean() / (v.std(ddof=1)/np.sqrt(v.size))`; :59 `e24 = _next_bar_close_vec(lk, to + H24)` — 24h window vs 1-day cluster; :70 demeaning by month constant only. Implied field size from the printed null (60.5 = 2*norm_sf(3)*m, :94) is m ≈ 22,400, so 723 |t|>3 = 3.2% of field — indistinguishable from the 3.4% a zero-skill field produces at VIF≈2.

**Effect:** The headline existence numbers — 723 |t|>3 vs 60.5 'expected' (12x) and, via the same broken p-values, the 631 BH discoveries — are fully reproducible by residual dependence at a VIF of ~2 with ZERO per-wallet skill. This mechanism is symmetric, so it does not by itself explain the 2.5:1 sign asymmetry (see coin-selection finding), but it voids the discovery count and the tail-excess ratio as evidence. Fix/diagnostic: cluster at (coin, week) or (wallet-day across all coins), or block-bootstrap wallets' cluster means by calendar day; if the 12x collapses toward ~2-3x the existence claim dies.

---

## R7-2 [MAJOR] (existence-stat) Demeaning by the pooled month field mean lets coin selection masquerade as entry-timing skill and is the natural source of the 2.5:1 positive asymmetry

**Mechanism:** Excess is bps - mmean[month] where mmean pools ALL entries across ALL coins that month (existence_t.py:66, :70, :33). A wallet concentrated long in coins that beat the pooled field that month (trending alts) gets positive 'excess' on every single entry from COIN CHOICE, with zero timing content — and because its clusters all ride the same coin trend, this compounds the dependence in the critical finding. Field-level tilt is not symmetric across wallets: taker volume chases winners (more wallets pile long into coins after they start running), so the population of (wallet, coin-month) exposures is itself tilted toward above-field-mean coins, manufacturing more positive than negative tails. Note prior context: the sealed-test verdict already identified 'ex-majors coin selection' as the sole surviving July candidate — this test's construction cannot distinguish that known effect from the new 'badge' timing claim.

**Evidence:** existence_t.py:65-66 pooled accumulation `msum[mi] += bps; mcnt[mi] += 1` with no coin dimension; :70 `clusters[key] = (s_ + bps - mmean[mi], ...)`. Compare: the transfer test's boundary-guarded markout cells (mlscreen2.py:382-388) have the same pooled-field property.

**Effect:** Part (plausibly most) of the 631 discoveries and specifically the 2.5:1 positive:negative asymmetry can be coin-momentum concentration, not per-entry timing. For the copy-trade purpose this is not automatically fatal — coin selection is copyable IF it persists month-over-month — but it is a different, weaker-persistence alpha class than 'timing badge', and the live paper run's fixed roster is then a momentum-coin bet, not a skill bet. Decisive diagnostic: re-demean per (coin, month) field mean; if discoveries and asymmetry collapse, the badge is coin selection.

---

## R7-3 [MAJOR] (existence-stat) Normal-tail p-values (norm_sf) instead of Student t_{N-1} are anti-conservative and overstate the quoted 12x by roughly 1.6x at the N=50 floor

**Mechanism:** p-values and the null baseline both use the standard normal (existence_t.py:82-84, :94). For a wallet at the minimum N=50 clusters, the correct reference is t_49: P(|t_49|>3) ≈ 0.0043 vs 0.0027 normal — the normal understates tail probability by ~1.6x, in the direction of MORE discoveries and a SMALLER printed null. The '60.5 expected' at line 94 is therefore a floor; the honest null for the actual N-distribution is materially higher (up to ~96 if the field were all N≈50), shrinking '12x' toward ~7-8x before any dependence correction. Secondary: fat-tailed/skewed cluster means make the self-normalized t skew opposite to the data skew at moderate N; with positively skewed crypto markouts (winsorization at ±500bp is symmetric in bps but the demeaned cluster-mean distribution is not), this slightly fattens the NEGATIVE t tail — so it cannot rescue the positive asymmetry, but it further corrupts two-sided calibration.

**Evidence:** existence_t.py:82 `def norm_sf(x): return 0.5*(1 - erf(x/sqrt(2)))`; :84 `ps = np.array([norm_sf(x) for x in arr])`; :94 null printed as `2*norm_sf(3)*len(ts)`; N floor at :71 `len(clusters) >= 50`.

**Effect:** BH runs on systematically too-small p-values, inflating the 631 discovery count, and the headline '723 vs 60.5' ratio is overstated by construction even under independence. Bounded effect (~1.6x at worst, less for high-N wallets) — it cannot make the discovery on its own, but stacked multiplicatively on the VIF≈2 dependence finding it fully accounts for the observed tails. Fix: use scipy.stats.t.sf(t, N-1) per wallet and recompute the null expectation from the N-distribution.

---

## R7-4 [CRITICAL] (transfer-machinery) No coin/direction control anywhere in the transfer test: persistent coin trends x persistent wallet direction can manufacture the 8/8 transfer without wallet skill

**Mechanism:** bps is the wallet's direction-signed markout (d_*(e24/ein-1), badge_transfer.py:63) demeaned by the GLOBAL fill-weighted month mean (line 69), never per-coin. Coin-day clustering (key=(coin,day), line 67) treats successive days of the same coin as independent, so a wallet holding one persistent directional stance in a multi-month trending coin accrues dozens of 'independent' positive clusters -> enormous trailing t -> top-50 roster. Both nulls (unconditional lines 98-101, activity-matched 102-110) draw wallets with field-average coin/direction mix and match nothing about coin exposure. If the trend persists into the score month (crypto trends run for months), the roster's demeaned score is positive in every fold while placebos are ~0.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:63 (signed bps), :69 (global mmean[mi], not per-coin), :67 (coin-day key, cross-day independence assumed), :98-110 (neither null matches coin composition or net direction)

**Effect:** This single mechanism can jointly produce the 12x |t|>3 tail excess (serially-dependent coin-day clusters counted as independent), the 2.5:1 positive asymmetry (momentum-following wallets sit WITH trends more often than against), and 8/8 positive folds with ~+56bp excess -- i.e. the entire headline -- from coin momentum rather than wallet identifiability. The live fixed-roster deploy would then be long trend-persistence, not wallet skill. Minimum falsification: per-coin-month demeaning, or a coin/direction-matched placebo.

---

## R7-5 [MAJOR] (transfer-machinery) The 8 folds are far from independent: nested and 5/6-overlapping rank windows make '8/8 positive, pooled z=+2.74' a correlated statistic misread as 8 confirmations

**Mechanism:** FOLDS (badge_transfer.py:82) are three nested prefixes (rank months {0..1},{0..2},{0..3}) plus five rolling 6-month windows each sharing 5 of 6 rank months with the next. Trailing t changes little between such windows, so consecutive rosters are largely the same 50 wallets; any wallet-level style or coin-exposure persistence (finding 1) correlates fold outcomes. The printed 'pooled z' is np.nanmean(zs) of these correlated fold z's (line 117), presented against an implicit N(0,1) bar.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:82 (fold definition), :117 (pooled z = nanmean). Docstring line 4 also says '9 folds' but 8 are defined -- stale doc.

**Effect:** 8/8 positive is not 2^-8 evidence: under strong roster overlap the effective number of independent looks is ~2-3 (the nested early folds are nearly one look). The pooled z of a mean of correlated z's has std between 0.35 and 1, so +2.74 is between ~2.7 and ~7.7 sigma depending on unmodeled correlation -- the number as printed is uninterpretable, and the fold-count framing overstates replication.

---

## R7-6 [MAJOR] (transfer-machinery) Activity-matched null matches only the BINARY score-month-active count, not activity intensity (score-month cluster count / rank-window N) -- the D3-class confound is only half closed

**Mechanism:** act = wallets with sc_n>=3 (badge_transfer.py:93,102); placebo rosters draw n_act wallets from this binary pool (lines 106-108). Roster wallets are top-t with N>=30 rank clusters and are systematically far more active in the score month (high sc_n) than a median just-active placebo wallet. Any correlation between activity intensity and expected demeaned markout (regime-sensitive high-frequency styles, or the cluster-size composition effect: scores equal-weight coin-days at line 73-74 while mmean is fill-weighted at line 65, so wallets with unusual cluster-size mixes have nonzero expected excess) transfers straight into z2. Note the pure-noise direction is conservative (low-sc_n placebos inflate plc2.std, deflating z2), so the surviving risk is specifically a mean-level intensity confound, not a variance artifact.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:93 (sc_n>=3 validity), :102-110 (binary match), :65 vs :73-74 (fill-weighted demeaning vs cluster-equal-weighted score)

**Effect:** The act-matched z=+3.22 headline does not rule out the activity-persistence placebo confound named in the prereg failure classes; a null matched on sc_n quantiles (or rank-window N deciles) is required before 'act-matched' can be claimed. Cannot by itself explain the raw effect size, but can inflate both pooled z's.

---

## R7-7 [CRITICAL] (pricing-data) Markout is anchored to raw last-trade bar prints with no volume floor, so a badge wallet's own continued execution both prints and moves its own 'exit' price — self-impact scored as skill

**Mechanism:** First, a premise correction: bars are NOT built from the cand2 candidate tape — cmd_bars scans the full month fills.parquet with only the PERP filter (mlscreen.py:53-57), so closes are market-wide. But each close is simply the last trade print of a 5m bar (close=pl.col('px').sort_by(['ts','tid']).last(), mlscreen.py:57) with no volume or participant filter, and in thin alts/hours a candidate wallet's own fills ARE those prints. The scored population is position-INCREASING taker fills (op = comp>0 & crossed & ~zh, badge_transfer.py:53, existence_t.py:55), i.e. wallets running multi-fill accumulation campaigns. ein = next-bar print after the fill, e24 = next-bar print after t+24h (badge_transfer.py:57, mlscreen2.py:168-176). A wallet whose aggressive flow persists over >24h (exactly the high-N, high-t wallets) gets e24 printed while its own buying is still lifting the book: (i) its own taker buys print at the ask, mechanically raising e24/ein for longs (symmetrically, persistent sellers print exits at the bid, raising short markout), and (ii) its own price impact in a thin book is realized as 'markout'. Anti-persistent (round-trip) wallets get the opposite sign, and since aggressive flow is positively autocorrelated in the population, the net is a positive-side excess. Additionally the 30-min gap condition (times[j]-ts<=1_800_000, mlscreen2.py:175) means entry observability itself is conditioned on a print landing soon after the fill — most often the wallet's own follow-up fill.

**Evidence:** mlscreen.py:53-57 (bars = raw last-trade px, no candidate filter, no volume floor); mlscreen2.py:168-176 (_next_bar_close_vec: next-bar print + 30min gap skip); badge_transfer.py:53-63 and existence_t.py:55-64 (scored = position-increasing taker fills, bps = d*(e24/ein-1))

**Effect:** Can manufacture all four headline numbers without any transferable alpha: campaign-style wallets get mechanically positive month-demeaned excess (positive discoveries + 2.5:1 asymmetry), high N_clusters makes small biases hit |t|>3 (12x tail), and because a wallet's execution style persists month-to-month, trailing-t rosters 'transfer' 8/8 folds — the badge partly certifies 'runs multi-day accumulation campaigns in thin coins'. The live paper follower cannot harvest own-impact markout: it buys alongside the campaign, pays the spread the leader's prints embed, and holds the position when the campaign's flow stops — expected live degradation from ~+56bp/entry toward zero or negative.

---

## R7-8 [MAJOR] (pricing-data) Joint entry+exit observability censoring: entries whose coin goes dead within 24h are silently deleted — survivorship inside the scoring itself

**Mechanism:** Both scripts require ok = isfinite(ein) & isfinite(e24) (existence_t.py:60, badge_transfer.py:58); e24 is NaN unless some trade prints within ~30min after t+24h (mlscreen2.py:175). So any entry followed within 24h by liquidity death — terminal crash, delisting, rug, everyone leaving the book — is excluded from scoring rather than marked at its (catastrophic) last price. The coin-level lk[0].size<100 gate (badge_transfer.py:41) computed over all 11 months of bars adds a milder full-period survivorship screen. Because the field month mean is computed from the same censored population, the demeaning absorbs only the average of this bias, not the cross-wallet differential: wallets concentrated in thin/moribund coins (where badge wallets live) have their worst outcomes censored at a much higher rate than liquid-coin wallets, and alt flow is predominantly long, so the censored tail is predominantly negative.

**Evidence:** existence_t.py:59-60 and badge_transfer.py:57-58 (ok requires finite e24); mlscreen2.py:171-176 (30-min print requirement); badge_transfer.py:41 (>=100-bars-over-11-months coin gate)

**Effect:** Directly inflates positive discoveries and the positive:negative asymmetry (left-tail outcomes removed for the long-heavy thin-coin cohort), and since a wallet's coin habitat persists, the same censoring recurs in every score month — contributing to the 8/8 transfer. The live paper run has no such delete button: the follower actually eats the dead-coin/delisting losses the backtest never scored, so live results should undershoot the +56bp/entry estimate even if some real edge exists.

---

## R7-9 [CRITICAL] (selection-effects) The transfer score is winsorized (±500) markout, not raw — the exact kill test that destroyed the majors-timing +3.86 was never applied to the badge

**Mechanism:** badge_transfer.py clips every markout at ±500bp in the one build pass that feeds BOTH the rank-window t and the score-month statistic, so 'next-month clean markout' is actually clipped markout. The majors-timing episode established on this same data that the ±500 clip converts persistent contrarian styles (many small wins, rare knife-catch losses beyond -500) into fake two-sided 'skill', and that style persistence alone delivers all-folds-positive transfer; that signal showed +3.86/9-of-9 and collapsed to +0.64 when rosters were re-scored on RAW markout. The badge selects high-t wallets — mechanically favoring low-variance many-small-wins styles whose left tails are precisely what the clip removes — then validates them on the same clipped statistic. Style persistence propagates the distortion across folds, manufacturing 8/8 without forward edge; the same clip plus the -14bp field mean and equal-weight coin-day clusters (same-day cross-coin alt-beta counted as independent observations, understating sd) inflates existence |t| both tails (12x excess) while shifting the typical wallet's demeaned excess positive (2.5:1 asymmetry) — all skill-free channels.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:63 (np.clip -500,500 applied before both pass-1 field mean and pass-2 rank/score stats), :92 (score = same clipped cluster stats); /Users/corywagamaneure/bablyon/scratch_conv/existence_t.py:64,68-73 (clip; cluster key (coin, UTC-day) — no cross-coin same-day clustering), :82-88 (N(0,1) calibration of dependent-cluster t's); PREREG_WALLET_SCREEN.md:229-247 (majors-timing kill: clip + persistence = 9/9 artifact; kill test = RAW markout re-score)

**Effect:** Can jointly manufacture the 631 FDR discoveries, the 12x tail excess, the 2.5:1 asymmetry, AND the 8/8 transfer. Mandatory pre-July check: re-score all 8(9) fold rosters on unclipped markout; if the pooled z collapses like majors-timing did, the badge is the same artifact class.

---

## R7-10 [MAJOR] (selection-effects) Forking-paths accounting: +2.74/+3.22 exceeds the pure-fishing bar only if folds are independent — and the artifact-inclusive campaign envelope already contains +3.86

**Mechanism:** The badge is ~the 13th signal family on these months (Sep-Dec burned by ~9 configs, Feb-Jun by ~12 families). Pooled z is the arithmetic MEAN of 8 fold z's (np.nanmean), whose null sd is sqrt((1+7ρ)/8): 0.35 if folds independent, ~0.62-0.75 at ρ≈0.3-0.5 (adjacent 6-mo rank windows share 5/6 months; rosters share persistent wallets; expanding folds share all rank data). Expected max over 13 null families ≈ 2.26·σ_p ≈ 0.8-1.7, 95th pct ≈ 0.9-2.0. So +2.74 is NOT reachable by multiplicity alone under a clean null — but that is a two-edged result: the only way a null family reaches +2.74 is via a persistent per-wallet artifact correlating the folds (finding 2's channel), and the campaign's own dead families demonstrate that combined channel reaches +3.86. The prereg's self-assessment ('far beyond observed fishing scale ~1.5-1.9') silently drops the +3.86 artifact from the reference set. Additionally two pooled statistics are reported (+2.74 unconditional, +3.22 act-matched) and the larger is cited, adding a small best-of-2 selection.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:117 (pooled = np.nanmean of fold z's), :82 (5/6-overlapping rank windows); PREREG_WALLET_SCREEN.md:195-227 (family ledger: ~9 early-month configs, ~12 Feb-Jun families, G3 +2.27 'partially selection-inflated'), :234-247 (+3.86 artifact), :268-270 (claimed fishing scale 1.5-1.9)

**Effect:** The honest posterior is: multiplicity discounts the result to the fishing floor (~+1.7-2.0) and the residual +0.7-1.5 is adjudicated ONLY by artifact-vs-skill tests (raw-markout kill test, coin-week clusters) and July forward data — the in-sample z has no remaining calibrated meaning.

---

## R7-11 [MAJOR] (selection-effects) Existence and transfer are two cuts of one markout matrix, not independent confirmations

**Mechanism:** Both scripts consume the identical cand2 parquets, identical tape-derived 5m bars (_load_bars), identical _next_bar_close_vec pricing, identical winsor/month-demean/coin-day-cluster construction; badge_transfer's per-month sufficient stats ARE the existence clusters split by month, and the transfer's score months lie inside the existence test's 11-month certification window. Any single artifact channel — clip truncation, tape-self-referential bar closes (bars built from the candidates' own fills, so a thin-alt specialist's multi-day campaign marks its own day-1 entries up via its day-2+ prints), cross-coin cluster dependence — propagates to BOTH headline numbers simultaneously. The narrative 'existence (631 discoveries) AND transfer (8/8) both confirm signal H' counts one dataset twice.

**Evidence:** /Users/corywagamaneure/bablyon/scratch_conv/existence_t.py:14,24-70 and /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:15,24-75 (identical imports, identical build loop, identical clip/demean/cluster code); /Users/corywagamaneure/bablyon/scratch_conv/mlscreen2.py:116-127,168-176 (bars derived from the same candidate tape; next-bar-close pricing shared)

**Effect:** The evidential structure is one test with two summaries, so the discovery's support is exactly one dataset deep; the only independent instruments are the live paper run (different data path) and July tape — the existence numbers add no confirmation weight to the transfer or vice versa.

---

## R7-12 [MAJOR] (selection-effects) Live paper run seeded with winner's-curse extreme order statistics and a dependence-blind success bar

**Mechanism:** The deployed roster is the top-50 by trailing-11-month guarded t (range 15.0..5.0) — the extreme upper order statistics of a 22,420-wallet field, selected on ALL the months the transfer test scored. Correct for deployment, but it sets expectations from the ~+56bp/entry fold estimate, which is (i) the selected 13th family's estimate, (ii) computed on clipped markouts, and (iii) subject to guaranteed regression to the mean even if H is real. The declared success bar (realized mean bps net positive, bootstrap 5th pct > -5bp after >=300 tranches) bootstraps tranches that cluster by coin-day and cross-coin alt-beta — the same dependence the existence t ignores — so the CI will be too tight, and a marginal pass (+10-20bp) will be misread as confirming the +56bp scale for sizing.

**Evidence:** /Users/corywagamaneure/bablyon/audit/edge3/PREREG_WALLET_SCREEN.md:271-282 (roster spec, t range, +56bp expectation, 300-tranche bootstrap criterion); /Users/corywagamaneure/bablyon/src/babylon/follow/main.py:277-278 and scheduler.py:175-185 (fixed roster taken as-is, no re-ranking); /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:98 (top-50 by t = extreme order statistics)

**Effect:** The paper run can produce a false PASS (dependence-understated CI) or a true-but-small effect misinterpreted at 3-5x its real scale; the success criterion should be restated now with a coin-day-block bootstrap and a pre-committed shrunk effect-size expectation (e.g., +15-25bp) before any tranche is read.

---

## R7-13 [CRITICAL] (deploy-integrity) Fixed-mode manifest fails its own validation (empty train_cutoff_tids): the badge deployment either crashes at the first roll or is running with all asserts stripped

**Mechanism:** scheduler.roll's fixed branch builds the manifest with train_cutoff_tids={} (scheduler.py:181-183), but RunManifest.validate asserts set(roster) == set(edge_weights) == set(train_cutoff_tids) (experiment.py:156-158) and is invoked both by RunManifest.build (experiment.py:169) and Registry.register (experiment.py:275). With a 50-wallet roster and an empty cutoff dict this assertion is unconditionally false. Under a default interpreter the first roll raises AssertionError before any manifest is committed — the fixed run cannot start. The prereg says the run IS live since 2026-07-03, which at HEAD is only possible with python -O / PYTHONOPTIMIZE — and the codebase elsewhere explicitly anticipates -O (harvest.py:186-188 'survives python -O, which strips asserts'). Under -O, every assert-based guard is silently disabled: ExperimentConfig.validate (all 25+ invariants), manifest/registry consistency checks, Results.validate on the gate inputs, and the ledger's entry_fill_px>0 guard.

**Evidence:** /Users/corywagamaneure/bablyon/src/babylon/follow/scheduler.py:181-183; /Users/corywagamaneure/bablyon/src/babylon/follow/experiment.py:156-158,169,275; /Users/corywagamaneure/bablyon/src/babylon/follow/harvest.py:186-188; audit/edge3/PREREG_WALLET_SCREEN.md:271-276 (go-live record)

**Effect:** Either the deployed droplet is not actually running HEAD's fixed path (startup crash), or it runs assert-stripped, meaning the 'immutable manifest preserved' claim and every downstream validation the markout path relied on (config binding, tamper checks, CI sanity, positive-entry-price) are silently inert for the entire badge paper run. This cannot manufacture the offline 631 discoveries, but it un-guards the live validation those numbers now depend on.

---

## R7-14 [CRITICAL] (deploy-integrity) The 14-day auto-reroll silently replaces the badge's flat sizing with tail-aware Kelly computed on the FALSIFIED round-trip signal, zeroing an unknown subset of the 50 wallets mid-run

**Mechanism:** LiveFollowSystem.reroll calls _harvest_notionals unconditionally for any HarvestRunner (live.py:172-176) — there is no fixed-mode branch mirroring build's 'notionals = {w: harvest_base}' (live.py:140-143). _harvest_notionals calls returns_fn per wallet; SelectionAdapter.returns_fn routes ONLY selection_signal=='markout' to markout_returns and everything else — including 'fixed' — to followable_returns (selection.py:70-80), i.e. the round-trip Sortino-era measure (universe-gated, min_hold 1h, 15-min lag) that the campaign measured as NULL. tail_aware_notionals then assigns 0.0 to any wallet with non-positive round-trip trimmed mean or no closed round-trips in the trailing 30 days (scheduler.py:103-112), and ingest_opens drops every open from a wallet with notional<=0 (harvest_runner.py:109-111). locked_config sets roll_cadence_days=14 for all modes (main.py:73), so _roll_loop fires this at T0+14d (~2026-07-17) even though the prereg says roster refresh is 'monthly from the laptop pipeline'. (Under a default interpreter the manifest assert of the previous finding makes the roll fail first and the error is swallowed by _roll_loop's catch — flat sizing survives but reroll fails forever; under -O the swap proceeds silently.)

**Evidence:** /Users/corywagamaneure/bablyon/src/babylon/follow/live.py:140-145,172-176,208-218; /Users/corywagamaneure/bablyon/src/babylon/follow/selection.py:70-80; /Users/corywagamaneure/bablyon/src/babylon/follow/scheduler.py:103-112; /Users/corywagamaneure/bablyon/src/babylon/follow/harvest_runner.py:109-111; /Users/corywagamaneure/bablyon/src/babylon/follow/main.py:73

**Effect:** From day 14 onward, harvests come only from badge wallets that happen to have positive trailing ROUND-TRIP returns — a wallet-selection filter on exactly the signal the badge was built to replace — and are sized heterogeneously by it. The >=300-tranche realized mean that feeds the declared -5bp bootstrap floor becomes a biased mixture of two different experiments, corrupting the badge's independent-provenance validation either direction.

---

## R7-15 [MAJOR] (deploy-integrity) Realized 24h bps omit funding entirely while the success criterion thresholds near zero; the -5bp floor is calibrated for fee/impact but not for the 24h carry or the weak-fold regime

**Mechanism:** A harvest's raw_bps is a pure fill-price ratio (harvest.py:194); PaperExecutor folds only fee (4.5bp), spread crossing, and impact (6bp) into fills (paper.py:27-37, wired at live.py:118-119); FollowRunner.accrue_funding (runner.py:135) has no call sites and HarvestRunner has no funding concept at all — confirmed by grep across the follow/ and execution/ modules. The badge horizon is 24h (main.py:83), 4x the 6h case an earlier audit round already flagged for ~1-25bp one-signed funding drag on crowd-side momentum-alt longs. Separately, the entry semantics differ favorably: the badge marks entry at the NEXT-5m-bar close after the wallet's fill (badge_transfer.py:57 via _next_bar_close_vec, 0-5 min late), while the live run enters on detection (entry_lag_ms=0, experiment.py:76; real latency ~50 wallets x 1.05s throttle ~1 min) — earlier than measured, capturing more of any short-lived drift.

**Evidence:** /Users/corywagamaneure/bablyon/src/babylon/follow/harvest.py:194; /Users/corywagamaneure/bablyon/src/babylon/follow/runner.py:135 (dead code); /Users/corywagamaneure/bablyon/src/babylon/follow/live.py:118-119; /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:57,62-63; audit/edge3/PREREG_WALLET_SCREEN.md:280-282 (declared criterion)

**Effect:** The paper run's 'net of the executor's fee/impact model' mean is systematically inflated relative to any real book (funding is one-signed against the crowd side), so passing the -5bp floor cannot establish net profitability — a false-PASS channel. Conversely, executor cost is ~25-35bp round trip while badge folds ranged +5..+117bp clean, so in a weak-regime month a GENUINE badge prints a negative realized mean and fails the floor — a false-FAIL channel. The criterion discriminates poorly in both directions.

---

## R7-16 [MAJOR] (deploy-integrity) Coverage bias in the harvested sample: universe gate drops 8% of roster entries and the stale-book/30-min-cancel path systematically drops thin-coin and quiet-hour entries

**Mechanism:** ingest_opens silently skips any open in a coin outside alt_universe.txt (harvest_runner.py:114), and L2 books are only subscribed for universe coins (live.py:159), while the badge scored ALL coins with >=100 bars on the candidate tape (badge_transfer.py:41) — the excluded ~8% skew to new/thin listings where 5m-bar markouts (and spreads) are largest, so the live mean is measured on the liquid-coin subset of badge entries, most plausibly a downward bias vs the +56bp/entry headline. Within the universe, _do_entries leaves a tranche PENDING whenever its book is >30s stale (harvest_runner.py:141-143) and due_entries cancels it after 30min (harvest.py:134-139, harvest_max_entry_lag_ms=1_800_000 from main.py:90), so thin coins and low-activity hours are additionally under-sampled (entry_expired). The cap side of (c) is fine: flat $10 tranches (harvest_base_frac=0.01, experiment.py:83) against 20x caps (gross $20k = 2000 concurrent, per-coin $1600 = 160 concurrent, live.py:134-138) makes capped=0 realistic; coverage counters exist (harvest.py:221-229) but the declared -5bp verdict does not condition on them.

**Evidence:** /Users/corywagamaneure/bablyon/src/babylon/follow/harvest_runner.py:114,141-143; /Users/corywagamaneure/bablyon/src/babylon/follow/harvest.py:134-139,221-229; /Users/corywagamaneure/bablyon/src/babylon/follow/live.py:134-138,159; /Users/corywagamaneure/bablyon/scratch_conv/badge_transfer.py:41; audit/edge3/PREREG_WALLET_SCREEN.md:275-277 (123-coin / 92% coverage record)

**Effect:** The paper run measures the badge on a liquidity-and-activity-conditioned subsample of its entries, not the population the +56bp was computed on. If the badge's edge concentrates in thin coins (consistent with 5m-bar self-priced markouts), the live mean under-reads and the run can falsely kill a real signal; the recorded coverage counters mitigate only if the verdict actually reads them, which the declared criterion does not.

---

## R7-17 [MINOR] (deploy-integrity) Resume path rewinds fill cursors to the pre-crash checkpoint, replaying downtime-gap fills as fresh opens; fixed roll has no emptiness/format guard on the roster CSV

**Mechanism:** build() seeds cursors to wall clock on resume (live.py:152, comment 'resume -> from wall clock'), but three lines later runner.from_state restores the watcher checkpoint (live.py:160-162 -> harvest_runner.from_state:299-300 -> watcher.from_state:259-263), overwriting the seed with the pre-crash cursor. Fills that occurred during downtime are then ingested as fresh opens with entry_target in the past: entered up to 30 min late (a 'contaminated window' by the code's own definition, harvest.py:87-89) if downtime <30min, or bulk-cancelled as entry_expired if longer. Separately, the fixed roll computes weights as 1.0/len(roster) with no emptiness check (scheduler.py:179-180 — ZeroDivisionError on an empty CSV), and load_candidates falls back to the FIRST column when no 'w' column exists (main.py:101), so a malformed roster export becomes 50 garbage strings silently polled against the API (zero detection). Casing itself is clean: badge_roster.json addresses are lowercase hex and the watcher attributes fills to the exact query string, so no case-mismatch channel exists at HEAD.

**Evidence:** /Users/corywagamaneure/bablyon/src/babylon/follow/live.py:150-162; /Users/corywagamaneure/bablyon/src/babylon/follow/watcher.py:259-263; /Users/corywagamaneure/bablyon/src/babylon/follow/scheduler.py:179-180; /Users/corywagamaneure/bablyon/src/babylon/follow/main.py:97-102; /Users/corywagamaneure/bablyon/scratch_conv/badge_roster.json (lowercase addresses)

**Effect:** Every restart injects a batch of late-entered tranches whose markout window differs from the badge's next-5m-bar semantics (diluting the measured mean) or a batch of entry_expired cancels (coverage loss), concentrated exactly at operationally messy times; and a roster-export format slip fails silent (zero harvests) rather than loud. Both degrade, without fabricating, the live validation.

---
