# PRE-REGISTRATION — position-copy wallet screen, 8-month confirmation test

Written 2026-07-01, BEFORE any backfilled month (Aug 2025–Jan 2026, Jun 2026) was inspected.
This is the single confirmation look. Any deviation must be recorded in a "Deviations" section
below before results are read.

## Hypothesis
Wallets selected by long-window risk-adjusted position-level PnL (the user's screen) retain
positive FOLLOWER-simulated PnL out of sample, net of realistic copy costs, and beat both the
filtered field and random same-size rosters.

## Data
- HL market tape (both counterparties per fill) from `s3://hl-mainnet-node-data/node_fills_by_block`
  via the ml repo's `backfill_fills.py` + `fills_to_parquet.py`, plus the pre-existing local
  backfill_202602–202605. Jun 2026 comes from backfill_202606 (multiday/fills.parquet is NOT used —
  overlap would double-count).
- Pricing: 5m bars derived from the tape itself (all perps incl. majors). Spot pairs and HIP-3
  markets excluded.
- **Windows: TRAIN = 2025-08-01 .. 2026-03-31 (8 months). TEST = 2026-04-01 .. 2026-06-30.**
  One split. No other splits will be scored.

## Eligibility (causal — computed on TRAIN window only)
Applied to taker, non-zhash order flow within TRAIN: 150–20000 orders, ≥25 active days,
0.5–15 orders/day over the wallet's train span, ≥$500 mean order notional; maker-exit share
of reducing notional ≤30% (train window). Dead wallets stay in the field. No test-window
information may enter eligibility.

## Reconstruction
Both-sides fills (maker fills sign-flipped), per-coin leading-episode drop (fills before first
return-to-flat excluded — startPosition is not available), daily MTM at 5m-bar day closes,
coins with <100 bars excluded. Funding: HL hourly funding accrued on positions where the repo's
HL 1h dataset covers the coin; coverage fraction reported alongside results.

## Selection & metric (THE pre-registered cell — no panel, no sweep)
- Rank eligible wallets by **follower-simulated train Sharpe** (not leader Sharpe):
  every fill re-priced at the next 5m-bar close post-fill (≤30 min gap tolerance), cost =
  per-coin half-spread + 3.0bp fee per side (HL tier-0 taker with HYPE discount ≈ 2.8–4.5;
  3.0 declared here, sensitivity ±: report 1.5 and 4.5 as context, decision at 3.0).
- Roster = top 50. Equal normalized weights (1/train gross |PnL|).

## Decision rule (all three required for PASS)
1. Follower-simulated TEST Sharpe of the roster > 0 with one-sided 95% CI above 0 under a
   day-block bootstrap (block = 5 days) of the roster's daily series.
2. Roster test Sharpe exceeds the 95th percentile of 1,000 random same-size rosters drawn
   from the eligible field (selection-aware placebo).
3. Robustness (reported, must not reverse sign): roster remains net-positive in test when
   (a) the top-|PnL| coin per wallet is excluded, (b) the best single test month is excluded.

FAIL on any condition = the screen does not transfer; write the null. INCONCLUSIVE is not an
outcome: condition 2 unmet = FAIL.

## Declared caveats (accepted, not tunable after the fact)
Maker-execution adverse selection unmodeled (cost sensitivity brackets it); spread proxies
(majors dict + measured alt spreads) not BBO-derived; archive MISS hours logged and reported;
Jul 27–31 2025 partial month excluded.

## Amendments v1.1 (2026-07-01, BEFORE any backfilled month was inspected)
Adopted from the pipeline audit (PIPELINE_AUDIT.md, 23 confirmed findings) — all are
implementation precision, none informed by new data. Implementation: `scratch_conv/mlscreen2.py`.
1. "Order" is defined as a (taker, coin, block-timestamp, side) fill group; same-block distinct
   orders merge (declared convention; biases order counts down for HFT — acceptable, HFT is
   excluded anyway).
2. Follower fill price = close of the FIRST 5m bar strictly AFTER the fill's bar (the containing
   bar's close can be the leader's own print — audit #10/#16); if that bar starts >30 min after
   the fill, the follower skips the fill and the follower's position (used for its carry and
   funding) diverges accordingly — no phantom carry (audit #18).
3. Eligibility additionally requires train gross |PnL| ≥ $50 (weight-floor dominance, audit #23);
   flat train series rank bottom (Sharpe := −1e9). Maker-exit share computed on TRAIN fills only.
4. No wallet-count cap; eligible list is sorted (deterministic). Never-return-to-flat wallet/coins
   are skipped entirely (startPosition unavailable) — declared limitation biasing AGAINST
   buy-and-hold winners, i.e. conservative for the hypothesis.
5. Funding: daily approximation −position_value × Σ(hourly HL rates), applied to leader and
   follower; per-coin coverage reported. Daily closes carry a 2-day staleness bound (delisted →
   NaN, masked) — audit #13.
6. Fee decomposition stored (zero-cost + spread-only + copied notional) so the 3.0bp decision
   cell and the 1.5/4.5 context cells are exact, not interpolated (audit #17).
7. Stats/bars for 2026-02..05 derive from the pre-existing local parquets; multiday unused.
   The 2026-01..2025-08 + 2026-06 months come from the hardened backfill driver
   (double-pass, gzip integrity check, completeness logging — audit #4).
8. The majors-heavy sub-roster and any other slice are EXPLORATORY, not decision inputs.

## Amendments v1.2 (2026-07-02, still BEFORE any test-window data was assembled or read)
User direction: the markout screen (the original project) becomes a declared CO-PRIMARY family
alongside the follower-Sharpe cell. All declared pre-look:
1. **Markout term-structure ladder** per eligible wallet: every position-INCREASING taker fill,
   markout at horizons {1, 2, 4, 8, 12, 24, 48, 72, 168}h; entry AND exit priced at the first
   5m bar strictly after the respective instant. A train entry counts toward a horizon cell only
   if its EXIT lands before the split (no leakage).
2. **Markout co-primary cell:** roster = top-50 by TRAIN dollar markout PnL at 24h (the declared
   center of the mid/low-freq target). Test statistic: the roster's TEST-window 24h markout PnL
   vs 1,000 random same-size rosters — pass bar p97.5 (family of 3 declared horizons: 24h primary,
   72h and 8h reported at p97.5). Equal-weight-per-decision variant reported as diagnostic only.
3. The full ladder is a PROFILE (shape classification: plateau=informed, spike-decay=impact,
   flat=noise); no cell outside the declared three participates in any pass/fail claim.
4. Train-side diagnostics (computed before the look, no test contact): ranking agreement between
   markout-PnL, follower-Sharpe, and monthly-profitability-breadth; term-structure shape
   distribution of each top-50.
5. Any cell that passes gets one confirmation round on fresh data (paper-forward or later months)
   before being reported as an edge.

## Amendments v1.3 (2026-07-02, adopted from pipeline-audit round 3 — PIPELINE_AUDIT_R3.md —
## all BEFORE any test-window read; the backfill was still incomplete at adoption time)
1. **Markout-cell statistic recalibrated (B13, critical):** the test statistic is the roster's
   per-wallet mean test bps, averaged EQUALLY across wallets (not the dollar-PnL sum, whose
   placebo comparison a size-sorted roster beats under a zero-skill null). Dollar PnL is
   reported as descriptive only. Placebos use the same equal-weight statistic.
2. **One roster (B7/B14):** the markout cell uses a single top-50 ranked by TRAIN 24h dollar
   markout PnL, evaluated at 8/24/72h. Eligibility floor ≥30 train entries at 24h is hereby
   declared. The markout cell deliberately has NO maker-exit/$50-gross filters (it measures
   informedness; copyability filters belong to the follower cell).
3. **Straddle purge (B2/B6):** per horizon, train cells require exit before the split AND test
   cells require ENTRY on/after the split; entries straddling the boundary are excluded from both.
4. **Reversal fills (B4):** the scored opening size is the position-increasing COMPONENT
   (sign-flip fills open |new position|, not the full fill size; shrinking flips now counted).
5. **Completeness gate + provenance (B1/B16/B21/B22):** look commands refuse to run unless
   bars/stats/cand2 exist for every declared month; each look writes a manifest (months, config,
   roster). The train-side numbers shown to the user on 2026-07-02 were computed on a TRUNCATED
   window (Oct-Mar train, no Aug/Sep; Oct-anchored positions) and are hereby marked PRELIMINARY;
   all artifacts regenerate from the final pick in order: pick -> extract (all months) ->
   markout/daily -> looks.
6. **Determinism (B3/B10):** all fill sorts and the 5m-bar close carry a tid tiebreaker; bars
   for all months are rebuilt with it before the final chain.
7. **Calendar months (B9/B15/B23):** condition 3b and all monthly reporting use calendar months
   (Apr=30d, May=31d, Jun=30d test), not 30-day blocks.
8. **Report obligations (B8/B17/B19/B20):** the team report must present, alongside pooled bps:
   per-wallet medians, per-side x per-month decomposition, a drift caveat (raw markouts in a
   trending window; the placebo is the drift control), and the explicit statement that the
   plateau shape and monthly-consistency stats are NOT evidence of skill by themselves (they
   match selection-conditioned noise); only the held-out placebo-relative test is.

## Amendments v1.4 (2026-07-02, ~20:00 — BEFORE the single look was run; declares ROUND TWO)
**Rolling walk-forward (user-directed).** Runs AFTER the registered look, on the same data;
design locked now so it cannot be shaped by the look's outcome.
- Folds: rank on a trailing 6 calendar months, score the next calendar month.
  With Aug 2025–Jun 2026: rank Aug–Jan→score Feb; Sep–Feb→Mar; Oct–Mar→Apr; Nov–Apr→May;
  Dec–May→Jun. Five folds.
- Per fold: eligibility (activity band + ≥30 scored 24h entries) computed on that fold's
  ranking window ONLY; roster = top-50 by trailing 24h dollar markout PnL; statistic =
  per-wallet mean 24h test-month bps, equal-weight; 1,000 same-size random-roster placebos
  per fold from that fold's eligible field.
- Entries belong to their ENTRY month; exits may cross the month boundary (declared: this is
  forward-flowing only and cannot leak a score month into its own ranking window).
- Reported: per-fold roster statistic + placebo percentile; roster turnover between folds;
  fold-month BTC return. Success reading (declared): ≥4/5 folds above the placebo median AND
  pooled z = mean_fold[(stat − placebo_mean)/placebo_sd] > 1.64 — NOTED that adjacent folds'
  ranking windows overlap 5 months, so folds are positively dependent and the pooled z is
  approximate; the per-fold pattern is the primary reading.
- Implementation: cmd_markout additionally emits per-calendar-month aggregates
  (markout2m.jsonl) in the same pass; the walk-forward is arithmetic on that file.

## Amendments v1.5 (2026-07-02 evening — BEFORE the registered look and walk-forward ran;
## adopted from pipeline-audit round 5, PIPELINE_AUDIT_R5.md)
1. (D1/D4) Walk-forward month cells: an entry counts toward a month only if its EXIT also lands
   in that month — v1.4's "cannot leak" claim was false as coded (boundary-crossing exits read
   the score month's opening prices into the ranking); now true by construction, symmetrically
   for rank and score months.
2. (D2) Ordering is code-enforced: the walk-forward refuses to run until the registered look's
   manifest exists.
3. (D3) The walk-forward reports TWO nulls per fold: the declared unconditional placebos and
   activity-matched placebos (same count of score-month-active wallets) — the roster's activity
   persistence is a confound the declared null does not control.
4. (D5) Roster turnover and per-fold context are now actually computed (v1.4 promised them).

## Round-6 audit corrections (2026-07-02 night, BEFORE the registered runs; PIPELINE_AUDIT_R6.md)
1. (E1/E2/E3, critical) Signal F's +1.81 was produced by venue_split.py which LACKED the D1
   month-boundary fix, winsorization, and the activity-matched null — all three now applied and
   the H5 test RERUN; H5's status is pending that rerun, and the original +1.81/+1.10 numbers
   are hereby marked unreliable.
   **RERUN RESULT (corrected code, same 3 folds): ex-maj->ex-maj +1.11/+0.58/+1.34, pooled
   +1.01 (activity-matched +0.94); majors->majors +0.38. The artifacts explained ~half of
   +1.81; the venue asymmetry SURVIVES at modest strength, on ~19-26 active roster wallets
   per fold. H5: directionally supported, magnitude soft, July adjudicates.**
2. (E12, critical) ALL exploratory z-scores of 2026-07-02 used only the unconditional placebo;
   the activity-persistence confound may inflate the entire exploratory scoreboard including
   the z~+1.1 baseline. Exploratory results are directional at best; the registered runs (which
   carry both nulls) are the only calibrated instruments.
3. (E6, critical) The crowd-relative preview was leave-one-ENTRY-out (wallets crowded against
   their own fills) — its NEGATIVE result is also unreliable; H6 remains unadjudicated.
4. (E9) Manifests are now invalidated at build start (crash cannot leave a gate-passing stale
   artifact). (E11) Walk-forward manifests now persist per-fold rosters.
5. (E10, recorded as deviation): walk-forward fold fields are intersected with the full-window
   pick universe (cand2 extraction scope) — per-fold eligibility is applied but wallets outside
   the Aug-Mar activity band were never extracted, so fold fields are subsets of the declared
   ones. Direction of bias unknown, presumed second-order; proper fix (per-fold extraction)
   deferred to round 2.

## Amendment v1.6 (2026-07-02 night, BEFORE the registered runs and before any test-window
## read): zhash fills (TWAP slices, liquidations) are EXCLUDED from scored entry events in
## cmd_markout — they are position changes, not decisions (the gap was flagged in audit round 4
## and again in round 6 idea #3; cand2 extraction now carries the zhash column). zhash fills
## REMAIN in position reconstruction and in the follower simulation (a copied position change
## is real regardless of its origin). ~12% of fills are zhash; effect on entry populations
## reported alongside the results.

## Early-months battery (2026-07-03, AFTER the registered verdict; recorded immediately)
Score months Sep/Oct/Nov/Dec 2025 had never been used as score months by any prior test —
genuinely unexamined fold outcomes inside owned data (user's insistence; correct). Expanding
rank windows (1-4 months), eligibility scaled 5*len(window), both nulls. Results:
- A (baseline): pooled -0.01 — dead on virgin months, confirming the registered FAIL.
- F (ex-majors): evaluable Nov/Dec only (short windows starve the floor): +1.20/+2.54,
  pooled +1.87 (act +1.80). F is now POSITIVE IN ALL 10 READINGS ever computed and these two
  were confirmatory in the proper sense (F frozen before these months were examined).
- G (full-position rank, proposed 2026-07-03 after all other results): markout basis +0.20
  (its Feb-Jun pulse did not replicate), same-basis +1.07 driven by one +4.26 Dec fold (crash
  month + turnover-denominator artifact conditions). G: NOT SUPPORTED on virgin months;
  retained on record, not advanced. (Feb-Jun G numbers: +0.62..+0.78 markout basis, +1.65
  dollar basis size-confounded, +1.91 turnover basis with denominator mismatch — spent folds,
  ~10th signal family.)
July 2026 (accruing; incremental pull live) remains the decisive forward test for F.

**G variants addendum (2026-07-03, user pushed back on the G dismissal — correctly):**
The initial G test was raw-dollar rank only. Two a-priori-justified variants were then declared
and run ONCE on the early folds: G2 (full-position Sharpe rank — the user's original other-repo
spec) and G3 (full-position RETURN rank = PnL / scored turnover — the size-free version).
- G2: markout basis −0.31 (dead); same-basis +1.23 (4/4 positive, modest).
- **G3: markout basis +2.27 (act +2.15) on virgin folds; Feb–Jun consistency +1.20 (act
  +1.22). Overall 7/9 folds positive incl. June (+1.42).** Diagnostics: G3∩F roster overlap
  0-1/50 — an INDEPENDENT population (tiny alt specialists: median rank-turnover ~$90k,
  majors-share 6–28%, ~45% return on scored flow) whose next-month entry markouts (clean
  score basis — immune to the rank-side units mismatch) transfer. G3 and F are two
  independent confirmations of the alt-identifiability thesis via disjoint wallets.
- Multiplicity honesty: G3 was conceived today and is ~the 9th config the early folds have
  seen; its virgin-fold number is partially selection-inflated; Feb–Jun folds were burned by
  ~12 families. G3 = SECOND July candidate behind F, not a finding. Declared July items for
  G3: forward confirmation; hybrid leg (rank G3 -> score majors slice) for deployability
  (G3 wallets are majors-thin, capacity small); artifact review of the return denominator
  (full-book PnL over scored-entry turnover).

## Majors-timing episode (2026-07-03, recorded same-day; scripts majors_timing.py/2.py)
Hypothesis (user's hunch: "persistent majors traders are being missed"): benchmark majors
entries against the COIN'S OWN daily counterfactual (not other wallets), certify TWO-SIDED
(long AND short excess both positive — regime-unfakeable). Initial result: pooled z +3.86,
9/9 folds, roster next-month "excess" +88bp/entry — the largest signal ever measured here.
Survived an hour-of-day seasonality control unchanged (+3.85).
**KILLED by same-day adversarial audit + kill test:** the daily counterfactual averages
forward-24h returns from ALL bar starts of the day INCLUDING those before the entry — a
post-move contrarian (dip-buyer/rip-seller) mechanically earns positive excess on BOTH sides
with zero forward drift (the pre-entry move sits inside the baseline's windows but outside
the entry's). T2's min(L,S) selects persistent contrarians; style persistence produced the
9/9 folds. Compounding: the ±500 clip truncates contrarians' knife-catch tail. Kill test
(T2 rosters scored on RAW copyable markout): +0.64 pooled, sign-flipping folds. VERDICT:
artifact. MAJORS CONCLUSION now rests on four independent instruments (raw selection +0.16,
drift-neutral +0.17, timing-excess = artifact, registered look FAIL): no identifiable
majors wallet edge at 24h in position data. The only living route to majors PnL remains the
F hybrid (alt-identified wallets' majors books, +1.10 exploratory). LESSON (add to pitfalls):
any benchmark whose windows can contain PRE-entry price action manufactures two-sided
contrarian "skill"; counterfactuals must be measurable-at-entry.

## SIGNAL H — "the badge" (2026-07-03 night; scripts existence_t.py, badge_transfer.py)
Genesis: user rejected both premature existence nulls ("look at effective positions; a wallet
with 10k positive-markout trades is more likely informed"). Design (Barras-Scaillet-Wermers
family): per entry, winsorized(±500) 24h post-fill markout DEMEANED by that month's field
mean; entries clustered into effective positions (coin x UTC day); per wallet
t = mean(cluster excess)/(sd/sqrt(N)); D1 boundary guard (exit in entry's month).
- EXISTENCE (full 11 months, N>=50 clusters, field 22,420): |t|>3 = 723 wallets vs 60.5
  expected under null (12x); BH-FDR(q=0.10): 631 POSITIVE discoveries (named informed
  traders) vs 257 negative (certified anti-skilled; fade pool). Asymmetry 2.5:1. Top:
  0xccf595… t=+14.9, 1,151 positions, +162bp mean excess.
- TRANSFER (rank by trailing-window t, top-50, score next-month clean markout, both nulls,
  8 folds Oct-Dec+Feb-Jun): +1.5/+2.1/+2.2/+3.0/+3.7/+5.5/+0.8/+3.0 — pooled z=+2.74,
  act-matched +3.22, 8/8 positive incl. June; roster next-month +5..+117bp (mean ~+56bp).
  SURVIVED the D1 boundary-guard correction UNCHANGED (+2.65->+2.74) — first result in
  campaign history to do so.
- Resolves the central paradox: dollar-PnL ranking never selected these wallets (big lucky
  books != high signal-to-noise records). E2's failure was a broken t (fixed sd, fill counts,
  no demeaning, no clustering).
- Remaining dues (declared for the battery): coin-WEEK cluster robustness (multi-day campaign
  dependence inflates rank t), venue/cost profile of badge rosters + follower sim, multiplicity
  discount (~13th family — but act z +3.22 with all folds >= +0.8 is far beyond the campaign's
  observed fishing scale ~1.5-1.9), and JULY forward confirmation as the formal bar.
- **BADGE v2 VERDICT (2026-07-03, audit-hardened rerun; scripts badge_v2.py, PIPELINE_AUDIT_R7.md):**
  Fixes applied: raw outcomes (±5000 guard only, no ±500 winsor), per-COIN-month demeaning
  (timing/allocation decomposition), flip-null (week-block direction randomization preserving
  the full dependence structure), empirical FDR, declared stop-loss variants (-3/-5/-8%,
  next-bar exit, 10bp slippage).
  EXISTENCE: v1's 631 discoveries COLLAPSE — no threshold reaches empFDR 0.10; the "12x" tail
  was ~2.3x once dependence is in the null (R7-1 confirmed quantitatively). BUT a real
  population survives: t>4 = 57 observed vs 15 expected with the NEGATIVE side at null
  (19 vs 15) — asymmetric, dependence-proof: ≈40 genuinely informed wallets exist among 22k;
  individuals are NOT nameable at q=0.10 with 11 months (empFDR floor 0.26).
  TRANSFER: timing-t rosters, RAW scoring: pooled +0.93 (act +1.00) — F-league cohort tilt,
  not v1's +2.74 mirage. STOPS DO NOT RESCUE the tails (-3%: +1.14; -8%: +0.75) — the bad
  months were common-shock gaps, not stoppable bleeds.
  REVISED CLAIM (the one the report ships): informed traders exist on Hyperliquid (~40/22k,
  proven beyond dependence artifacts, tails included); at 11 months of data the PRODUCT is
  the BASKET (t>4 cohort of 57, ~74% expected real, cohort transfer ~+1σ), never the
  individually-certified trader. July + the (stopped, fixed, redeployable) paper harvester
  adjudicate the basket.
  **ENTITY-CLUSTERING STRESS TEST (2026-07-03, user-proposed; thresholds declared pre-run:
  co-timed>=25% at +-10min same coin+dir, OR daily-PnL corr>=0.7 over >=40 shared days, OR
  exposure cosine>=0.95 with corr>=0.5):** 57 wallets -> **43 independent information
  sources** vs ~15 flip-null expected — the tail excess is BROAD, not a few duplicated
  strategies. Found: one 8-wallet coordinated entity (50-87% co-timed, cosine to 0.98 — a
  copy network or multi-wallet whale, all t 4.2-5.5), one 4-wallet PnL-correlated family
  (incl. the top t=6.4 wallet), one triple, two pairs, 38 unlinked singletons. Deploy rule
  recorded in badge_v2_basket.json: one slot per source group -> 43 source-level slots.
- **LIVE PAPER RUN (go-live 2026-07-03 16:31 UTC, user-authorized):** droplet service
  babylon-markout repointed to `--selection fixed` (new mode; roster taken as-is, no internal
  re-ranking; immutable manifest preserved): the 50-wallet badge roster (trailing-11mo guarded
  t, range 15.0..5.0, scratch_conv/badge_roster.json), 24h harvest horizon, flat per-event
  sizing, 123-coin universe covering 92% of roster entries (coverage cap recorded, not
  silent), $1000 paper book, state-dir data/follow/badge_live. Old experiment's journal
  preserved untouched; orphan duplicate poller from 07-01 killed. This is the badge's
  INDEPENDENT-PROVENANCE validation: live detection latency + real books + data path fully
  separate from the S3 pipeline that discovered it. Success criterion (declared now): the
  paper harvests' realized mean bps at 24h, net of the executor's fee/impact model, is
  positive with its bootstrap 5th percentile > -5bp after >=300 harvested tranches; roster
  refresh monthly from the laptop pipeline.

## Deviations (recorded BEFORE the registered runs)
1. (D15) An exploratory "audition" on 2026-07-02 previewed weaker (3-month-rank) versions of
   walk-forward folds 0-1: it scored Feb and Mar rosters against placebos using train-window
   data only. The registered walk-forward's folds 0-1 are therefore not first looks at those
   score months' fold structure (the sealed Apr-Jun window was NOT touched). Interpretation of
   folds 0-1 must carry this caveat; folds 2-4 are unaffected.
2. (D16/D6, corrections to intermediate claims) The "train-halves persistence r=-0.04" compared
   a 61-day to a 122-day window (data began Oct 1); the win-breadth AUC=0.81 was substantially
   label-circular (features spanned the window defining the labels) and is retracted as
   evidence — the causal audition z=+0.49 is the honest estimate for that signal.
3. (D18) Five exploratory accept/reject decisions on 2026-07-02 used <=3 dependent folds with
   multiple signals — they are priors, not findings; only the registered runs adjudicate.

## Frozen taxonomy hypotheses (2026-07-02 evening — for confirmation on data arriving AFTER
## this date, i.e. July 2026 tape; generated from train-side clustering, n small, declared)
- H1: "diversified momentum accumulator" wallets (>=8 coins traded, median entry <$2k,
  maker share <10%, majors-focused, long-tilted momentum entries) transfer out of sample.
- H2: wallets with maker share > 25% of fills in the ranking window do NOT transfer — their
  taker-entry markouts are regime artifacts (liquidity providers crossing in stress). The 25%
  threshold is pinned now; the field is bimodal (~3-6% vs ~50%+) so the rule is
  threshold-insensitive across 15-35%.
  **UPDATE 2026-07-02 late evening (before any registered run): H2 CONTRADICTED by the
  field-wide decile-matched certification test (user-directed): excluded (maker>25%) wallets
  matched on rank-window PnL performed equal-or-BETTER next month (−7.3 / +20.1 / +7.5 bp,
  middle fold CI clear of zero) and better in the top decile in 3/3 folds. The C2 cluster story
  rested on 5 wallets; signal D's audition edge is reinterpreted as top-50 composition luck.
  H2 retained for the record as refuted-at-population-level; the decile-matched exclusion test
  is hereby the REQUIRED certification for any future filter.**
- H4 (declared 2026-07-02 late evening, exploratory, ~7th look at the 3 train folds): maker
  share is a POSITIVE transfer predictor, monotone across bands (matched diffs +0/+1.9/+7.1/
  +6.8/+9.9/+10.0/+31.9bp from pure-taker to 80-100% maker) — "when a market maker crosses the
  spread, listen." NOT a tournament entrant tonight; adjudicated on July+ data alongside H1/H3.
- H3 (low confidence): alt-focused long momentum chasers transfer better than priors suggest.
- Exploratory audition of a maker-cap ranking variant (signal D) on the SAME 3 train-side folds
  as prior signals is DECLARED here before its results were read; it is the 4th signal on those
  folds and its z carries that multiplicity.
- Signal E (declared 2026-07-02 evening, before the tournament ran): EMPIRICAL-BAYES SHRUNK
  ranking — per fold, wallet edge = field_mean + w*(raw − field_mean), w = s2_skill/(s2_skill +
  s2_i/n_i), with s2_skill from the cross-sectional variance decomposition of the fold's rank
  window and n_i = the wallet's rank-window DECISION count (unique entry timestamps — amended
  pre-tournament 2026-07-02 late evening: fill counts inflate confidence ~10-100x for multi-fill
  orders/execution algos; same-order fills share identical next-bar markouts so the collapse is
  lossless). E2 uses the same n_i. Registered look/walk-forward statistics are means and
  therefore inflation-immune; their fill-based >=30 floors stand as declared. Rank by shrunk dollar edge (shrunk bps x notional). Rationale:
  post-maker-cap failures are winner's-curse extremes with thin evidence; shrinkage demotes them
  by construction. The rolling "informed badge" (sequential posterior with earn/lose thresholds)
  is the declared ROUND-2 deliverable built on this estimator, adjudicated on July+ data.
- Signal E2 (declared 2026-07-02 late evening, before the tournament ran): rank by the LOWER
  90% CONFIDENCE BOUND of per-entry edge, mean_bps − 1.645*sd_bps/sqrt(n), computed on the
  fold's rank window (precision-first cousin of E; the user's "P(edge) given effective N").
  Multiplicity ledger: SIX signals now auditioned/declared across shared folds (A/B/C/D/E/E2);
  the tournament winner must beat placebos AND siblings decisively, then confirm on July data.
- H5 (external, from the user's other repo; tested 2026-07-02 night in declared form):
  "selection signal lives ex-majors." SUPPORTED on the 3 exploratory folds: rank-majors->score-
  majors pooled z +0.28 (flat); rank-exmaj->score-exmaj +1.81 (3/3 folds incl. the Jan fold no
  other signal survived); HYBRID rank-exmaj->score-MAJORS +1.10 (3/3) — alt skill generalizes
  to majors, not vice versa (+0.11, unstable). Mechanism: majors markouts are shared regime
  (placebo-cancelling); alt selection is idiosyncratic. Deployable shape: select on ex-majors
  evidence, copy the majors book. Signal F (rank by trailing ex-majors $ markout PnL) is hereby
  the SEVENTH and final declared tournament entrant.
- H6 (user-proposed, 2026-07-02 night, recorded before any test): CROWD-RELATIVE skill
  statistics — compare each entry to matched controls (same coin, same day, same direction,
  other wallets) via hit-rate-vs-crowd and/or median markout-vs-crowd. Two declared roles:
  (a) certification statistic for the round-2 FDR pipeline (robust to fat tails, regime
  cancels at entry level); (b) the candidate solution to MAJORS IDENTIFIABILITY — H5 showed
  majors skill is invisible to raw-PnL ranking because placebos share the regime; matched
  controls cancel the regime per-entry, so genuinely skilled majors traders may become
  measurable. NOT a tournament entrant (menu closed at 7); adjudicated in the July battery.
  Trade-off on record: hit rate is robust but payoff-blind (38/50 of the current roster are
  momentum-style, structurally sub-50% hit with big winners) — certify with crowd-relative
  robust statistics, rank the certified by magnitude.
  **H6 CANONICAL SPEC (user-refined, 2026-07-02 night, recorded pre-test):** contemporaneous
  leave-one-out crowd cells at (coin, side, HOUR) with day-cell fallback where the hour cell
  has <5 crowd entries; two statistics per wallet — trimmed-mean markout excess and hit-rate
  excess vs crowd; each with a lower confidence bound; a wallet is CERTIFIED only when BOTH
  lower bounds are positive (conjunction); certified set ranked by magnitude. Declared
  watch-its: conjunction power cost (short lists expected) and hit-rate bias against momentum
  payoff profiles. Preview on train folds = ~10th exploratory look (direction only); real
  adjudication in the July battery.
