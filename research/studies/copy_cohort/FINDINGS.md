# copy_cohort — findings ledger

Study: powered wallet-cohort copyable-markout persistence test on majors.
Design: `COPY_COHORT_ARCH.md` (v1.1). Audit trail: `audit/copy_cohort_arch/`.

---

## 2026-07-12 — Design stage (no results yet)

**Question.** Can a formation-selected wallet cohort show positive OOS episode-level timing alpha
at a copyable horizon (4h), powered at the ~5 bp follower-economics care-about?

**Method.** Arch doc v1.0 written (episodes as observations, Stage-0 empirical dependence
calibration replacing coin-day collapsing, EB-shrunk two-arm selectors [timing-residual markout /
realized PnL], 5-fold expanding walk-forward vs matched random cohorts, planted-control power gate).
Design-stage 4-agent audit swarm (stats-rigor, firewall-leakage, docs-consistency, data-integrity).

**Result.** 1 CRITICAL + 4 HIGH + 9 MED design defects found and ALL folded into v1.1 — headline:
the "wider of two one-way cluster CIs" rule undercovers (80% at nominal 95%, probed) → replaced
with two-way CGM; `close_ts ≤ cutoff` membership leaks post-cutoff prices through the markout
window and straddle-week μ → window censor `entry_bar_ts + h < cutoff`; the uniform-injection
power gate cannot test selection → planted skilled-sub-population control; wallet-level sign-flip
calibration circularity fixed; ~19–21% `entry_after_close` degenerate episodes now excluded (F0).
Clean bills: lane firewall, EB-shrinkage validity, Stage-0 effect-leakage safety, verdict taxonomy,
prior-findings register.

**Caveats.** No data has been analyzed for effect size; every number above is about test validity,
not the finding. Frozen-but-untested risks called out by the audit for Stage 0/build to resolve:
placebo stratification may be too fine for the realized pool (fallback pre-registered), pooled
week-cluster count (~22) is marginal for bootstrap coverage (t with G−1 df adopted).

**Artifacts.** `COPY_COHORT_ARCH.md` (v1.1), `audit/copy_cohort_arch/SCOPE.md`,
`audit/copy_cohort_arch/FINDINGS.md`.

**Next.** Order of work §10: lib additions + `mu_fold.py` + Stage 0 → code audit → run Stage 0 →
freeze (unit, cluster); then selectors/walk-forward build; then the §6 power gate (hard STOP if
unpowered); only then the forward run.

---

## 2026-07-12 — Stage 0 COMPLETE: frozen (unit, cluster) = (episode, wallet_week)

**Question.** Which (observation unit, SE-cluster level) gives honest inference on episode timing
alpha — is coin-day-style collapsing necessary, or does clustering reclaim the sample?

**Method.** Burn-in 202508–202510 only (3.91M scoreable episodes / 209k wallets after episode-level
ARCH-§3 filters; y = 4h timing-residual markout, sd 160.6 bp). Non-circular flip calibration
(wallet-level flips, CR0-clustered pooled t at each finer level, identical sign matrix across
levels, n_perm=10k) on TWO populations (≥10-ep and ≥30-ep wallets); Moulton SE-inflation table;
two-way CGM coverage sims. Code swarm-audited before the run (2 HIGH determinism, 3 MED fixed —
`audit/copy_cohort_stage0/FINDINGS.md`); panel deterministic + provenance-stamped (b177578+dirty).

**Result (decisional).**
- Episode-level iid inference is decisively MISCALIBRATED: rejection 0.167 / 0.182 (both
  populations) at nominal 0.05 — real within-wallet dependence, treating fills/episodes as iid is
  invalid.
- `wallet_coin_day` AND `wallet_week` both calibrate on both populations (0.048–0.056, Wilson CIs
  ⊂ [0.03, 0.07]). Frozen rule (coarsest below wallet, both populations) → **ADOPT wallet_week**.
- Moulton SE-inflation: wallet_week 1.387 vs whole-wallet 1.415 — within-wallet dependence
  saturates by the week scale; the power cost of the coarser choice vs wallet_coin_day (1.347) is
  ~3%. **The user's original instinct is confirmed: coin-day sample-collapsing was unnecessary —
  episodes + wallet-week cluster-robust SEs keep the full sample at ~1.4× iid SE.**
- Cross-wallet time dependence is REAL and survives μ-subtraction: coin_week Moulton 7.28 (tiny
  per-pair ICC 0.0007 × huge clusters), coin-hour ICC 0.083 essentially unchanged by μ-subtraction
  (0.0829→0.0827) — intra-week common moves are untouched by the coin-week baseline. The §5.5
  two-way (wallet × week) CGM inference at the cohort stage is therefore load-bearing, not
  belt-and-braces.
- Two-way CGM CI coverage validated (audit-S1 deliverable): 0.949 (forward dims), 0.938 (per-fold
  dims), 0.951 (heavy-tailed sizes) — all ≥ the 93% gate; the REJECTED wider-of-two rule measured
  at 0.92, wallet-only at 0.60/0.36 — confirming both the S1 fix and that week-dimension dependence
  dominates the error budget.
- Supporting: overlapping-markout-window pairs corr +0.068 vs −0.006 non-overlapping (54.6% of
  consecutive same-wallet-coin pairs overlap) — the mechanical dependence channel is confirmed but
  modest; per-wallet rungs mildly over-reject at finer levels (0.072/0.080), consistent with the
  pooled ladder.

**Caveats.** Calibration population applies episode-level filters only (registered choice);
descriptive ICCs computed on busy groups (singletons excluded); burn-in regime only — the frozen
choice is a calibration property, not a guarantee for structurally different future regimes.

**Artifacts.** `data/derived/copy_cohort/stage0_report.{json,md}`, `stage0_y.parquet` +
`_STAGE0_META.json`; code `research/studies/copy_cohort/{stage0_dependence,mu_fold}.py`,
`research/lib/stats.py` (twoway_cluster_ci, eb_shrink, cluster sign-flip, t_ppf).

**Next.** §10 step 3: selectors panel + matched-placebo walk-forward + planted-control power gate →
code audit → §6 power gate (STOP if unpowered) → forward run + steelman/prosecute → verdict.

---

## 2026-07-12 — Selectors/walk-forward/power-gate BUILT + audited; POWER GATE FAILS at 5bp

**Method.** Built base table (33.6M-row markout⋈episodes, one-time; per-fold reads a local slice —
fixed a 65-min/fold blowup traced to np.unique on 42-char wallet strings → integer codes, now
16s/fold). selectors.py (F1–F8 eligibility + EB-shrunk markout / realized-PnL arms), walkforward.py
(matched-placebo WF, two-way CGM, wallet sign test, BH), power_gate.py (MDE + planted-cohort
selection control). 3-agent code audit (correctness, firewall, stats-rigor): 1 CRITICAL
(power-gate CGM used wallet-nested week code → understated MDE), 1 HIGH (pooled sign test counted
fold-echoes as independent), MED/LOWs — ALL FIXED. eb_shrink integer path verified bit-identical.

**Result — the §6 power gate FAILS at the 5bp care-about, on BOTH axes (audit-clean):**
- **Evaluation MDE = 6.71 bp > 5 bp.** The pooled two-way (wallet×ISO-week) CGM CI on a K=100
  cohort can't resolve a 5bp-margin cohort effect. (Formation-side estimate on one fold; the
  realized pooled 5-fold MDE may be somewhat tighter.)
- **Selection blind at 5bp.** Planted-cohort control (validated by a capture-vs-edge curve):
  capture at +5bp/episode = 0.04 ≈ chance (0.019); reliable (>0.5) capture needs ≈ **+80 bp/episode
  true edge**. Cause: per-episode markout sd = 164 bp, ~61 scoring episodes/wallet → per-wallet SE
  ≈ 21 bp, so a 5bp per-wallet edge is ~0.03σ of a single trade — invisible to per-wallet ranking.
  (The planted +5bp is noiseless-uniform, i.e. optimistic — real selection is ≤ this.) This is the
  same wall as Stage A (MDE 160bp/entry), now quantified for the cohort design.

**Interpretation (unresolved — decision pending).** A FAILED gate here means "cannot certify a
result AT the 5bp deployment margin," NOT "no effect exists." Two facts complicate the pre-registered
STOP: (a) with MDE 6.71 > 5 the §7 rules can't even earn a clean RED negative — a null forward
result would be INCONCLUSIVE, not "no edge"; (b) the one-fold smoke showed a POSITIVE — cohort
forward markout +30bp vs matched-placebo median +11bp (+19bp enrichment, ≫ MDE), which stopping
would suppress (the over-null hazard the gate itself forbids). The +19bp survives coin+direction
matching in that one fold but must face the full 5-fold matched placebo + follower-lag haircut.
The realized-PnL arm (Arm B) has independent prior support (P0 taker Spearman +0.453 OOS) and the
capture curve was markout-only. **Decision surfaced to user: honor STOP vs run-and-interpret vs
redesign-for-power.**

**Artifacts.** `data/derived/copy_cohort/{base/, power_gate_report.json}`; code
`research/studies/copy_cohort/{base,selectors,walkforward,power_gate}.py`;
`audit/copy_cohort_forward/FINDINGS.md`.

---

## 2026-07-12 — FORWARD RUN + verdict: markout-selection INCONCLUSIVE; realized-PnL-selection = AMBER live positive

> **CORRECTION (2026-07-17 audit, code fixed, NOT re-run):** `walkforward._wallet_equal_bootstrap_ci`'s
> wallet-resample leg collapsed duplicate wallet draws (see "AUDIT-FIX RE-PRINT" at the ledger's end);
> synthetic probe shows its nominal-95% wallet-only CIs cover only ~84%. The wallet-only legs below
> (e.g. Arm B [13.1, 36.0]) are UNDERSTATED (~30% too narrow). The Arm B binding CI quoted here was the
> WEEK-BLOCK leg ([1.87, 36.60]), whose resample was not affected by the collapse bug, so the AMBER
> verdict stands, but a widened wallet leg could make wallet-only binding on a re-run — treat the exact
> CI edges as stale until walkforward is re-run with the fixed code.

User elected to run the forward walk-forward despite the power-gate STOP (the gate tests 5bp-margin
power; the study's claim is cohort-existence, and the smoke showed a positive that stopping would
suppress — the over-null hazard). Ran 5-fold matched-placebo WF, then BOTH mandatory adversarial
passes (steelman + prosecute, separate agents), then computed the decisive missing number: the
two-way CI on the FROZEN economic estimand (wallet-equal mean), which neither the episode-weighted
two-way CI nor the sign test targets.

**The adjudicating measurement (wallet-equal = the per-decision quantity a follower copies; binding CI
= wider of wallet-resample and ISO-week-block-resample, so cross-wallet week shocks are priced in):**
- **Arm A (timing-residual markout @4h): point +1.88 bp, CI [−7.53, +13.02] — INCLUDES 0.** The
  episode-weighted two-way CI that excluded 0 (+14.3 [5.0, 23.7]) was an EPISODE-WEIGHTING ARTIFACT —
  a few hyperactive wallets, not the typical selected wallet. On the copyable per-decision estimand
  the markout arm shows nothing. Sign p=0.0019 was likewise episode/calendar-driven.
- **Arm B (realized-PnL bps): point +24.54 bp, CI [1.87, 36.60] — EXCLUDES 0 (positive)** even under
  the conservative week-block resample (wallet-only CI [13.1, 36.0]). Sign p=0.0006 on 111 distinct
  wallets. The mirror weighting pattern of Arm A: the PnL edge lives in the typical selected wallet's
  per-decision realized PnL, diluted (not created) by episode-weighting.

**VERDICTS (over-null AND over-carry gates applied symmetrically):**
- **Arm A markout selection → INCONCLUSIVE (not "no effect").** Frozen estimand +1.88 [−7.5, +13.0]
  admits effects we'd care about, so underpowered-inconclusive, not null (MDE 13.3 > care-about 5).
  But it earns a **method-scoped demotion from "live positive":** per CLAUDE.md over-carry, the
  significance lived only in the re-weighted descriptive layer while the error-controlled layer on the
  frozen estimand includes 0, and per-wallet selection at 5bp is a tight null (planted capture 0.04).
  ⇒ **markout ranking does not identify a copytradeable cohort.**
- **Arm B realized-PnL selection → AMBER (live positive, NOT deployable).** Frozen estimand +24.5 bp,
  conservative CI excludes 0, sign p=0.0006, and independently corroborated by the P0 taker-PnL rank
  persistence (Spearman +0.453 OOS, +17 bp). This is the strongest OOS copy-cohort lead the line has
  produced on the copyable quantity. NOT GREEN/deployable: only **3/5 folds beat placebo** (carried by
  202602 + 202606; 202604 negative — fails the pre-registered ≥4/5), CI lower bound (+1.87) is below
  the 5bp care-about, **Arm-B selection power at 5bp is UNTESTED** (the planted control was
  markout-only), and a residual leverage/hold-time/direction style tilt is **not excluded** (placebo
  matches coin + long-share-half only; realized PnL demeaned by coin-week only).

**Direct answer to the original question:** a copytradeable positive-markout cohort selected by
per-wallet MARKOUT ranking is NOT identifiable here — per-decision markout skill at the deployable
margin is buried under ~164 bp/trade noise. But selecting on REALIZED PnL surfaces a real,
conservatively-significant per-wallet lead (+24.5 bp, CI excludes 0), consistent with the prior
+0.453 persistence. The copy-cohort signal, to the extent it exists, is a realized-PnL phenomenon,
not a markout one.

**Next (powered redesign for Arm B — the anti-ratchet obligation, not more of the same):** (1) a
planted-cohort power gate for the PnL arm (is Arm-B selection powered at 5bp?); (2) tighten the
placebo to continuous long-share + leverage + hold-time to kill the style-tilt confound; (3) extend
the window so folds aren't 2-of-5 regime-driven; (4) follower-lag + cost haircut on the Arm-B cohort
(does +24.5 bp gross survive a real copier's entry lag and fees?). Only then a deployment claim.

**Artifacts.** `data/derived/copy_cohort/walkforward_report.json` (both arms, wallet_equal_ci);
steelman/prosecute passes recorded in this session; `audit/copy_cohort_forward/FINDINGS.md`.

---

## 2026-07-12 — Arm C: capped-PnL-per-active-day selector (validate user's other-repo edge)

**Question.** Reproduce a copy-trade edge the user found in another repo: rank wallets by *capped realized
PnL per ACTIVE DAY* over a trailing 3 months, take top-30 (monthly roll, data ≤ T−1), and copy their
forward OPENING TAKER positions with a ~8h markout exit. Does the cohort's forward 8h markout beat a
random draw from the same eligibility pool? Code: `capday_cohort.py` (`run` + `powered`). Majors only —
per-fill `closed_pnl` exists ONLY on node_fills majors (Reservoir dropped it). CAP_DAILY swept
{100k,500k,1M,5M} (user: value unknown, sweep). Selection VERIFIED faithful to spec (correctness audit:
fee sign, cap-applied-per-day, per-active-day metric, window all correct) and LEAKAGE-CLEAN (watertight
walk-forward boundary). Selection is REAL: top-30 have ~$2.67M median window realized PnL, ~27 active days,
29/30 real taker-openers; forward participation ≈ pool (~50%).

**Result — NOT a reproduction of a deployable edge; NOT a hard zero either (honestly labeled).**
- **Per-decision (wallet-equal, the anti-over-carry headline) = null-to-negative.** Cohort forward 8h
  markout is ≤ the random-pool draw at ALL four caps (cohort−random = −33/−4/−5/−26 bp at 100k/500k/1M/5M;
  we-folds-beat-random 1/4/3/2 of 8; sign p ≥ 0.64). Neutralized wallet-equal residual is NEGATIVE
  (−2.2 bp @500k, −6.4 bp @1M). The load-bearing "does the selector identify per-decision skill" quantity
  shows nothing. The eligibility pool itself (any ≥15-active-day wallet) earns +4–5 bp forward — the
  cohort's absolute positive is mostly that baseline, not selection.
- **Episode-equal (literal copy-every-trade follower) = underpowered wide-CI positive, DEMOTED, not carried.**
  Raw sweep showed +17/+15 bp vs random +3.7/+3.6 (5/8 folds) at 500k/1M — but that is the argmax of a
  4-cap × 2-weighting sweep (unadj sign p=0.363 → ≈0.83 cap-corrected), rides 2 ADJACENT non-independent
  folds (202601/202602, overlapping 3-mo windows) with n=3–60 episodes, and inverts/vanishes at 100k/5M.
  The **powered redesign** (anti-ratchet obligation — built, not deferred): coin×entry-week field-NEUTRALIZED,
  episode-level, POOLED across all 8 folds, cluster-bootstrap CI. Point estimate stays positive
  (+9.99 bp @500k / +7.30 bp @1M; net of 2.6 bp round-trip cost +7.4/+4.7) but the CI **includes zero both
  ways**: cluster-by-wallet [−23.1,+40.1]/[−18.1,+31.2], cluster-by-coin×week [−16.1,+35.2]/[−16.6,+31.2].

**Direct answer.** The selector picks genuinely profitable wallets, but a fixed-8h-exit copy of their
opening TAKER majors positions does NOT reproduce as a per-decision edge, and the copy-every-trade estimand
— though a positive point estimate (~+7–10 bp neutralized) — cannot be separated from zero even pooled +
neutralized + correctly clustered. Same power wall as Arm A (MDE 160 bp) / Arm B (needs ~+80 bp/episode):
with only ~54 forward-active cohort-wallet-months and ~164 bp/trade markout sd, the majors data at hand
CANNOT resolve a single-digit-bp per-position edge. This is the "available data cannot resolve this"
terminus for the markout-exit framing, NOT a re-run of the blind instrument. Consistent with the study's
prior lesson: any copy-cohort signal is a REALIZED-PNL/hold/leverage phenomenon (Arm B AMBER), not a
per-position markout one — and a fixed-8h markout exit does not capture it.

**What would still resolve it (honest levers, none run):** (1) evaluate at the wallets' OWN exit / a longer
horizon (24–48h) not a fixed 8h — these are position-traders, 8h truncates (needs markout rebuild >8h);
(2) forward-tradeability screen in selection to lift the 2–14/30 participation and N; (3) alts, where these
wallets are more active and the edge may live — but selection needs alt closed_pnl (Reservoir dropped it →
re-pull/reconstruct); (4) the dollar-PnL follower with the user's q50/q75-per-coin sizing clip (the
episode-weighted $ book may pay even where per-position bps can't clear zero — but that is a $-PnL claim,
not a markout claim, and inherits the same non-independence caveat).

**Artifacts.** `data/derived/copy_cohort/capday_cohort_report.json` (sweep, wallet+episode-equal, random
baselines), `data/derived/copy_cohort/capday_powered_report.json` (neutralized pooled cluster-bootstrap),
`data/derived/copy_cohort/capday_base.parquet` (8.8M wallet-days). Correctness + leakage audits and
steelman/prosecute passes recorded this session.

### 2026-07-12 addendum — RUN THE BOOK (not markout-averaging), CAP=100k (`book.py`)

**User correction (both valid):** (1) the intended cap is **100k**, not 500k/1M; (2) averaging per-position
markout bps is NOT running the book — a real follower SIZES each entry and the PORTFOLIO's dollar P&L /
equity curve is the result. Built the actual book: top-30 @100k, follow forward opening-taker entries, size
each at the **q50/q75 percentile of the wallet's PRIOR opening notionals in that coin** (expanding,
leakage-safe), exit 8h, net of 2.6bp round-trip; benchmarked vs 200 random-30 cohorts with the same sizing.

**The correction is validated — the book looks materially better than the markout average, but is thin,
concentration-driven, and not yet significant vs random:**
- **Equal-weighted net markout ≈ −0.3 bp (flat)** — matches the earlier "no per-position edge." But the
  **dollar-weighted, q-sized book is POSITIVE: +8.7 bp (q50) / +23.1 bp (q75) net** (gross +11.3/+25.6),
  **daily Sharpe 1.56 / 1.96** vs random-cohort Sharpe median ~0.78. So dollar-weighting by the q-clip flips
  a flat average into a positive book — exactly the user's point.
- **But it does NOT clear the random-cohort book** run with the identical sizing rule: p(beat random net$)
  = 0.398 (q50) / 0.279 (q75); p(beat random Sharpe) = 0.144 (q50) / **0.060 (q75, marginal, post-hoc best-of-2)**.
  Cohort net$ ($1,411 / $7,638 total over 8 mo) sits below the random p90 ($7.4k / $16.1k).
- **Thin + fragile:** only **217 positions / 44 wallets** over 8 months (@100k selects low-frequency small
  traders; 22/239 dropped as un-sizeable), median clip $3.7k/$8.8k, **win rate exactly 0.50** → the positive
  is carried by a few large winning clips (concentration = the over-carry mechanism), not breadth.

**Read:** suggestive-positive, UNDERPOWERED — not dead, not confirmed. The book method is the right lens and
it beats random on the point estimates (Sharpe ~2×, net$ 4–14× the random median), but N=217 can't push
  p<0.05 and the q75 Sharpe p=0.06 is post-hoc. The thinness is the binding constraint. To resolve: hold to
the wallet's OWN exit / longer horizon (bigger moves, more $/trade), include ALTS (need alt closed_pnl
re-pull — where these wallets trade far more), don't drop un-sizeable entries (default clip), and treat q as
pre-registered not best-of. Artifacts: `book_report.json`, `book_equity.json`, `book.py`.

**2026-07-13 dedicated audit swarm — historical estimate invalid, strategy unresolved:** independent
leakage, statistics, correctness/data-contract, steelman, and prosecutor passes found that **1.56/1.96 are
not valid Sharpes**. One of 217 rows has a null 8h markout: masked P&L reductions omit it, but
`np.bincount` consumes the masked buffer's underlying clip as phantom daily profit. The 216 finite saved
rows mechanically give active-entry-day Sharpes 0.477/1.323 and full-calendar 8h-exit-day diagnostics
0.372/1.072; these are still leaked and are NOT corrected strategy estimates. The book also (i) deletes
entries using their eventual `is_liquidation_close`, (ii) omits `NOT entry_after_close` and
`entry_lag_s<=90`, (iii) lacks matched endpoint coverage and a capital ledger, and (iv) compares against
independently redrawn monthly random paths that do not preserve real-wallet persistence. The finite
+$1,411/+$7,638 conditional ledger is real, but +8.7/+23.1bp is non-causal and concentration-driven.
**Retract the historical estimate as evidence; do not call the strategy null. Direction is unknown until a
causal rerun.** Full audit: `audit/copy_cohort_top30_book/FINDINGS.md`.

---

## 2026-07-13 — Arm B v2 actual 4h follower book (causal rebuild; top-100)

**Question.** Does the old Arm-B lead survive when we stop averaging wallet markouts and run the actual
dollar-sized portfolio: top-100 selected on formation realized-PnL bps, causal q50 prior-same-coin clips
(q75 sensitivity), 4h follower exit, 2.6bp round-trip cost, and a longitudinal matched-random book?

**Pre-run audit found that the old +24.54bp Arm-B result was not a valid causal baseline.** Two finalized
episode fields leaked beyond the cutoff: forward entries were deleted by their *eventual*
`is_liquidation_close`, and F4 eligibility read final `hold_minutes` for positions that closed after the
formation cutoff. Arm-B formation also omitted its registered F0 freshness predicates. Arm B v2 fixes all
three: liquidation is usable in formation only when `close_ts < cutoff` and never filters a forward entry;
hold duration is censored as-of cutoff; F0 applies. The old +24.54 [1.87,36.60] is therefore **retracted as
a causal result** (a lead that motivated this rebuild, not evidence carried into the verdict).

**Actual book, net of 2.6bp (3,337 evaluable positions, 137 wallets, 23 exit weeks; 99.79% endpoint
coverage):**

- **q50 primary:** +1.97bp absolute, two-way wallet×week CI **[−6.00,+9.93]**; +$2,080 on $10.58M
  evaluable turnover; corrected full-calendar daily Sharpe **0.49**; peak concurrent gross $138k.
- **q75 sensitivity:** +1.84bp, CI **[−6.90,+10.58]**; +$4,133 on $22.47M; Sharpe **0.45**. More clip
  capital increases dollars but slightly dilutes return, so q75 is not a confirmation.
- The point is not one-trade fragile: q50 top trade = 1.46% and top wallet = 12.28% of positive PnL;
  leave-one-wallet net return stays **+0.39 to +3.26bp** and leave-one-week **+0.32 to +3.72bp**.

**Matched longitudinal book (1,000 whole-trajectory paths; formation-feature TV≤5%; ranks are
descriptive, not finite-sample p-values):**

- q50 random median −3.29bp → observed enrichment **+5.26bp**, descriptive band **[−6.33,+16.74]**,
  rank 0.180. q75 enrichment +5.32bp, band [−6.66,+16.88], rank 0.181.
- q50 fold enrichment: +8.43, +7.09, −8.11, +15.12, −0.27bp → **3/5** beat the matched median.
  Wallet/week breadth ranks are 0.501/0.471 (chance-like): the lean is payoff magnitude, not breadth.
- Sampler construction passed: 1,000 unique economic paths, ~22% acceptance, return/tail ESS 797/805,
  chain-mean spread 0.124 null SD, median real-wallet overlap 2%/fold. Coverage real 99.79% vs random
  99.90%; the band is not manufactured by endpoint missingness. Primary bp normalizes real's higher
  turnover ($10.60M vs random $8.12M); net-dollar ranks remain descriptive.

**Point estimate + CI + MDE + cross-unit check (the always-pending null gate):** enrichment +5.26bp;
band [−6.33,+16.74]; empirical 80%-power MDE **14.43bp > 5bp care-about**; fold breadth 3/5 and
wallet/week breadth ranks ≈chance. The apparent “+5bp injection rank 0.046” adds 5bp *on top of the already
observed +5.26bp lean* and is not standalone 5bp power; do not use it against the MDE.

**Mandatory dual adversarial framing:**

- **Steelman:** positive absolute and matched point estimates survive q50/q75, every leave-one-wallet cut,
  every q50 leave-one-week cut, 3/5 folds, causal v2, near-complete coverage, and a conservatively
  constructed longitudinal random book. Best positive framing: credible underpowered enrichment lead.
- **Prosecutor (binding under the explicit over-carry rule):** this target was chosen after a repo-wide
  hunt on reused months; neither absolute nor matched interval resolves direction; MDE is ~3× the target;
  breadth is chance; q75 is the same trades; no error-controlled positive survives the whole arc.

**VERDICT: UNRESOLVED POST-HOC RESIDUAL, DIRECTION UNKNOWN — not a live edge, not a null, not deployable.**
The positive point estimate (+5.26bp enrichment; +1.97bp absolute book) is recorded and must not be buried,
but the available reused data cannot determine whether it is real. A null/negative is not earned because
the intervals admit worthwhile positives and MDE≫5. A positive is not earned because the controlled layer
does not resolve direction. Freeze v2/q50/4h/costs and adjudicate only on genuinely new OOS data; to reach
MDE≤5 under sqrt-N scaling needs roughly 8× the independent information.

**Artifacts.** `ARM_B_BOOK_ARCH.md`, `arm_b_book.py`,
`data/derived/copy_cohort/{arm_b_book_report.json,arm_b_book_equity.json}`,
`audit/copy_cohort_arm_b_book/{SCOPE,FINDINGS}.md`. Architecture swarm, build audit, steelman, prosecutor,
and construction-conservatism pass completed this session.

---

## 2026-07-14 — CAPDAY BOOK: clean causal top-30/8h book + 24h/48h/own-exit levers → NO copyable edge

**Question.** The user's exact spec: rolling **top-30 by capped-PnL-per-active-day** (CAP=$100k, monthly roll,
majors), copy the cohort's forward **opening-taker** entries, dollar-sized by leakage-safe prior-notional
q50 clips, exit at **8h** — is the edge real? Plus the two levers the ledger kept flagging: longer horizons
(24h/48h) and the wallets' **own exit**. Motivated by the retracted `book.py` headline (+8.7/+23.1 bp,
Sharpe 1.56/1.96), which the 2026-07-13 audit found INVALID (F1 masked-array Sharpe fabrication, F2
liquidation lookahead, F3 non-executable entries — all three re-confirmed by reading `book.py` this session).

**Method.** New leakage-clean causal book `capday_book.py`, porting `arm_b_book.py`'s audited accounting onto
the capday selector. Full pre-registered protocol: arch doc (`CAPDAY_BOOK_ARCH.md` v1.1) → 4-agent
architecture audit (A1–A17 folded) → own-exit **markout sidecar** (`markout.py` close-mode: forward-ASOF at
`close_ts`, ≤90s, `close_bar_ts≥entry_bar_ts` guard, 1:1 key tripwire; `episodes_markout_close`, 32M rows) →
base v2 (+24h/48h, provenance-guarded `open_base`) → build → 4-agent **code audit** (1 HIGH: balancing-
feature cutoff off by one month leaked the test month into the MATCHED-RANDOM benchmark only — FIXED + A9
assert + re-run; 7 MED fixed) → run 4 horizons × {q50,q75} over **8 walk-forward folds** (202511–202606) →
separate **steelman + prosecutor** passes. Cohort estimate/CI were unaffected by the C1 leak; only the
descriptive random benchmark changed (8h rank 0.088→0.186, folds 7/8→5/8 — the leak was conservative).

**Result (PRIMARY = 8h q50; 24h/48h/own-exit are pre-registered SECONDARY LEADS, never headline).**
The three views of the SAME 8h trade set disagree in sign — and only the non-copyable one is positive:
- **dollar-weighted net +16.66 bp**, two-way wallet×week CI **[−10.2, +43.5] — includes 0**; win rate 0.49;
  top wallet = **26%** of positive PnL; daily Sharpe 1.17; leave-one-wallet min +7.8, leave-one-week min +8.5.
- **per-episode −3.07 bp**; **WALLET-EQUAL (the copyable per-decision co-primary) −7.23 bp**, CI [−55.8, +41.3]
  (n=46 wallets) — negative point, wide CI.
- vs matched-random: rank 0.186, 5/8 folds — **but `random_band_interpretable=False`** (return-ESS 67 ≪ 400
  gate), so the ranks/folds are DESCRIPTIVE-only, not admissible. MDE **53 bp ≫ 5 bp** care-about.
- Secondary leads under a CONSISTENT weighting are worse: wallet-equal −7.2 / −34.1 / −83.5 bp at 8h/24h/48h
  (monotone decay); dollar-weighted own-exit −0.6 bp. Own-exit's +112 bp wallet-equal is a handful of
  multi-month buy-and-holds (evaluable hold p90 ≈ **17 days**, 9.5% censored, 20 open at data end, true bound
  **[−315, +244]**) — not a copyable taker signal on any executable horizon.

**⚠️ VERDICT CORRECTED 2026-07-14 (over-null self-audit, prompted by the user's lever).** The first-pass
verdict below the line ("method-scoped NO-SUPPORT") was an OVER-NULL and is RETRACTED. The corrected verdict:

**CORRECTED VERDICT — UNDERPOWERED POSITIVE (direction positive), not deployable, not significant, not
disproven.** The 8h q50 dollar book — *the user's actual sized-portfolio estimand* — is **+16.7 bp, se 13.1,
CI [−10.2, +43.5]**, and is **leave-one-wallet robust (min +7.8 after dropping the 26% wallet)** and
leave-one-week robust (min +8.5). By the over-null gate's own criterion 1 (its example CI = [−5,+45]) with
MDE 53 ≫ 5 care-about, this is the textbook **INCONCLUSIVE/underpowered-POSITIVE** — surface the positive
direction, do not bury it.

**The over-null I made (recorded so it isn't repeated):** I made **wallet-equal (−7.2, se 24.1, CI
[−55.8,+41.3])** the "load-bearing copyable quantity" and used its negative *point* to demote the dollar book
via the "tight null on the load-bearing quantity dominates a downstream lean" clause. That clause REQUIRES a
tight null; wallet-equal here is the *least* precise estimand in the analysis (se 24.1 — ~2× the dollar
book's 13.1), its sign is noise, and I let it outrank a more-precise positive. I also mis-called the dollar
book "over-carry" when its leave-one-out (min +7.8) *passes* the actual concentration test, and I inverted
the estimand (the user runs a SIZED book → dollar-weighted IS the strategy, not a "flattering artifact").
Tested & falsified en route: coin×week field-neutralization does NOT tighten the CI (se 12.9→12.8, point
+16.7→+18.9) — beta is not the inflator, so "missing neutralization" is NOT the fix.
- It does **not** earn a hard powered NEGATIVE either: MDE 53 ≫ 5, and wallet-equal is too wide to be a tight
  null. So it is genuinely unresolved on SIGNIFICANCE — but the DIRECTION is positive and robust.
- **The binding constraint is forward FOLLOWABILITY, not selection.** 240 cohort-memberships = **133 distinct
  selected wallets** (59 re-selected across folds); of these only **53 (~40%) open any followable opening-taker
  entry in their test month**, and **46** are sizeable (219 evaluable episodes). Two self-addressable power
  leaks: (a) **23 un-sizeable entries were DROPPED** (53→46 wallets) — the earlier book.py note said "don't
  drop, default clip"; defaulting recovers them immediately; (b) the ~40% participation ceiling is the deeper
  limit. So the wide CI is a thin-copyable-surface problem, not evidence selection failed — the 133 selected
  wallets are, by construction, profitable.

### (superseded first-pass framing, kept for the audit trail — do not cite as the verdict)
- The first pass argued the over-carry rule "forces demotion" of the +16.7: size-weighted only, disagrees in
  sign with the per-decision estimators, CI includes 0, fails an (uninterpretable) matched-random,
  concentration-carried. This over-weighted a noise-dominated wallet-equal and under-weighted the LOO
  robustness — the over-null corrected above.
- **Direct answer (corrected):** the selector picks genuinely profitable wallets, and the SIZED dollar book
  copying their 8h opening-taker entries shows a **positive, leave-one-out-robust +16.7 bp/trade** — an
  underpowered POSITIVE lead on the estimand the user actually trades, not a demonstrated null. It is not yet
  significant (CI includes 0 at n=46 wallets) and not deployable, but the direction is positive and survives
  dropping the biggest wallet/week. The prior lineage's "data can't resolve at single-digit bp" power wall
  still binds on SIGNIFICANCE (MDE 53 ≫ 5) — but the honest label is underpowered-positive, and the
  anti-ratchet obligation is to POWER it (below), not to call it no-support.

**What would still resolve it (honest levers; the anti-ratchet obligation is a POWERED design, not a re-run):**
(1) forward paper-deploy the frozen 8h q50 book from 2026-07 and accumulate wallet-weeks (point est +16.7,
missing only N); (2) pool for N across more coins/wallets + market-neutralize the markout to push MDE from 53
toward the ~17 bp signal; (3) an uncensored own-horizon design (fixed max-hold = wallet median, not the
double-truncated own-exit) to test whether the edge lives at the wallets' natural horizon; (4) alts, where
these wallets are more active (needs alt `closed_pnl` re-pull). None run.

**Artifacts.** `CAPDAY_BOOK_ARCH.md` (v1.1), `capday_book.py`, `markout.py` (close-mode sidecar), `base.py`
(v2 + `open_base`/`open_close_sidecar`), `data/derived/copy_cohort/{capday_book_report.json,
capday_book_equity.json}`, `data/derived/episodes_markout_close/`, `audit/copy_cohort_capday_book/{SCOPE,
FINDINGS}.md` (architecture + code audit + resolutions). Steelman + prosecutor passes (separate agents)
recorded this session.

## 2026-07-14 — CAPDAY BOOK, Steps 1–3 (user's research program: why does the CI include 0?)

The user directed a structured program to resolve whether the wide CI is a selection problem, a fragility
(tail) problem, or a sizing problem, with an explicit anti-overfit stance and equal-standing over-null/
over-carry gates. Four instruments built and run on the SAME leakage-clean 8h q50 book (`capday_book._book`).

**Step 1 — contribution diagnostics (`capday_diag.py`).** The CI-includes-0 is CONCENTRATED, not broad:
median wallet +3.1bp, worst-5-of-46 wallets = 72% of gross loss, remove-worst-5 lifts +16.7→+42.6bp; blowups
IDIOSYNCRATIC (entry crash-corr to field −0.016). Necessary condition for a fragility filter met; sufficiency
(ex-ante predictability) deferred to Step 3.

**Step 2 — shrunk-8h-markout selection (`capday_markout_select.py`).** The user's highest-suspicion lever
(align selection with the 8h target, EB-shrink). FALSIFIED as a lift: LCB(λ=1) book −3.9bp CI[−14.8,+7.1],
pure shrunk-mean(λ=0) −1.4bp CI[−18.1,+15.3]; both pick a DISJOINT high-frequency population (32–50 entries/
wallet vs capped-PnL's ~5; cohort overlap 0/30 every fold) and both are near-zero/negative with tight CIs
(n=3.9k–6k). Powered method-scoped NEGATIVE for shrunk-8h-markout selection on majors@8h — the copyable edge
lives in the low-frequency large-position cohort, orthogonal to markout ranking.

**Step 3a — blowup anatomy, unit = wallet-fold (`capday_anatomy.py`) + conditioning controls
(`capday_sizecurve.py` Part 1).** First-pass verdict ONE_TRADE_TAIL was OVERSTATED and is withdrawn after the
user's conditioning correction: (a) blowup recurrence is UNMEASURABLE (5 of 6 blowup wallets appear in only
one fold; IID-expected recur≥2 = 0.03) — zero recurrence is not evidence of non-recurrence; (b) worst-entry-
share ≥70% is mechanically forced at n≤2 and uninformative; (c) BUT conditioned on n=2, blowups over-index on
"worst entry = the larger clip" (1.0 vs 0.42 for ordinary n=2 folds) — a real, if tiny-N, size association.
Winner mirror: top-3 wallet-folds = 48% of positive PnL (the +16.7 is concentration-carried, same tail that
makes the losses).

**Step 3b/c — containment + SIZE-RESPONSE curve + frozen α-sizing curve (`capday_caps.py`,
`capday_sizecurve.py`).** No sizing transform robustly improves the risk-adjusted book:
- Equalizing DESTROYS the edge (equal-per-entry +16.7→−3.1, equal-per-walletfold −10.6) → size carries real
  information; full equalization throws away the strategy's only edge.
- SIZE-RESPONSE (within-wallet clip percentile → OOS net bp, wallet-clustered) is NON-MONOTONE with every
  bucket CI including 0; the LARGEST-clip bucket (p90–100) is the mildly POSITIVE one (+16.7 wal). So "extreme
  relative size is harmful" is NOT supported — the big trades carry the edge, not the damage.
- α-curve (copy = notlᵅ·median¹⁻ᵅ): a mean-vs-robustness tradeoff, not a free win. α=1 (copy actual size)
  +31.7bp CI[−5.7,+69.2] but FRAGILE (2/8 folds+, top-3 winners 70%, worst-fold −$2079); α=0–0.25 (compress
  to typical size) more fold-robust (5/8, best worst-fold at α=0.25) at LOWER mean (+14–17). Caps on ACTUAL
  size HURT (leave-top-3-winners-out −36/−49bp) — opposite sign to the earlier median-base pool-cap that
  helped, i.e. the cap "win" is parameterization-dependent noise, not a robust size law.

**Verdict (both gates).** Wallet-level prediction (Steps 2, 3a) AND size-based containment (Step 3c) both fail
to produce a robust lift. The +16.7bp baseline is a genuine but UNDERPOWERED positive; the binding constraint
is POWER (46 wallets, 8 folds — every CI straddles 0), not a missing selection or sizing rule. This is the
anti-ratchet terminus for the majors line: the powered designs were built and none clears. Levers that add
real N (not more search on these 46 wallets): forward paper-accumulation of wallet-weeks; pooling across coins
via alts (needs alt `closed_pnl`). Artifacts: `capday_{diag,markout_select,anatomy,caps,sizecurve,fragility}.py`,
`data/derived/copy_cohort/capday_{diag,markout_select,anatomy,caps,sizecurve}_report.json`.

## 2026-07-14 — Steps 3d–3e: sizing thread CLOSED + BETWEEN-WALLET SCALE = first positive selection lead

**Step 3d — definitive within-wallet relative-size test (`capday_sizetest.py`).** Equal wallet budget, r =
entry_notl/strict-prior-median, g(r)=min(r^α,3), exposure-normalized, PAIRED wallet-cluster bootstrap, walk-
forward α. Result: relative clip size is NOT a usable sizing signal at this N — no α beats equal-budget paired
(α=1 Δ −7.2bp [−38,+34], P(Δ>0)=0.32), and the WF-selected α is WORSE (−14.3bp). Also: under equal budget even
α=0 is −3.1bp → the headline +16.7 was the median-NOTIONAL (capacity) weighting, not within-wallet conviction.
Per the user's pre-registered criterion (WF-selected rule must fail), this EARNS the method-scoped negative for
the SIZING lever. Base per-decision edge is flat-to-negative & underpowered on equal exposure (not a hard zero).

**Consensus feasibility on majors (probe).** Synchronized-entry consensus is majors-infeasible: of 243 in-test
cohort opening-taker entries (53 wallets, 4 coins), ≥2 distinct wallets agree (same coin/dir) for only 7%/12%
of entries at ±1h/±4h, ≥3 essentially never; 24 non-overlapping 24h consensus clusters total. The cohort is too
sparse on majors for a breadth/consensus signal → needs alts (density) OR a position-STATE definition (below).

**Step 3e — BETWEEN-wallet SCALE test (`capday_betascale.py`). FIRST POSITIVE SELECTION LEAD.** The +16.7 dying
under equal budget is NOT proof wealth was accidental — typical wallet scale may IDENTIFY the informed/institution-
like wallets. Test: fixed formation weight w_i ∝ scale_i^β (scale = wallet-fold strict-prior median opening
notional), EQUAL within-wallet, exposure-normalized, β∈{0,.25,.5,1}, paired + WF. Result (opposite to α):
scale-tilt HELPS — paired Δ vs β=0: β=.25 +5.9 [−10,+22] P(Δ>0)=0.75, β=.5 +8.5 [−20,+39] P=0.71; WF-selected β
ADAPTIVE +19.5bp vs baseline −15.9 → Δ +35.4bp (WINS, mirror of α's −14.3). **Scale QUARTILES** (equal-weight/
wallet-fold, wallet-clustered): Q1 $26–769 −23.8 / Q2 $848–2846 −53.3 / Q3 $3k–9k +3.0 / Q4 $9k–100k **+32.6** —
only the large-scale quartile is positive, small-scale negative. Direction consistent across 3 independent views
(paired Δ, WF selection, quartile monotone large>small). **VERDICT: underpowered POSITIVE lead for a BETWEEN-
wallet scale selection axis** (all CIs still include 0; n=219, 14 wf/quartile; β reverts at 1.0; WF 7 folds) —
suggestive not established. Reframes the study: the tradable refinement is SELECT LARGER-SCALE WALLETS, not copy
their sizes (α, rejected) and not predict fragile wallets (3a, no signal). Next (user order): active-POSITION-
STATE consensus (shared view ≠ synchronized entry), MAE/MFE + source-wallet exit, then alts. Artifacts:
capday_{sizetest,betascale}.py + _report.json.

## 2026-07-14 — Step 3f: FROZEN entry rule = scale-only (scale × consensus interaction, constrained)

Per the user (freeze WHO/WHEN to copy before exits or alts; formation-known vars only, no tuning). 2×2 =
wallet scale (LARGE=top-half prior-median notional within fold) × position-state consensus (≥1 other selected
wallet already HOLDING same coin+dir at entry). Sizing wallet-equal, exit 8h, BTC/ETH/SOL core vs HYPE separate.

RESULT (CORE, wallet-equal 8h net bp): large+consensus −121 (n=1/wf1 — DEGENERATE) | large+solo +52.6 (n24/wf4)
| small+consensus +22.8 (n86/wf22) | small+solo −17.6 (n61/wf28). **The primary Δ (does consensus help LARGE
wallets) is NOT ESTIMABLE — large+consensus n=1**, because LARGE-scale wallets are position INITIATORS not
confirmers (they enter solo/first, +52.6, and essentially never arrive after another cohort wallet is holding).
Informative secondaries: **consensus RESCUES small wallets** (small+cons +22.8 vs small+solo −17.6, Δ +40.4
P(Δ>0)=0.85 — small solo = the junk cell); scale main effect large−small +39.9 P(Δ>0)=0.75 (reconfirms 3e).
HYPE: large+cons again n=1 (degenerate); small-rescue NEGATIVE (−54.8) → HYPE structurally different, quarantined.

**FROZEN DECISION (per user's pre-registered rule: interaction unresolved → freeze the SIMPLER scale-only
rule).** Candidate entry rule = **top-half-scale wallets of the capped-PnL top-30 cohort, BTC/ETH/SOL, fixed
within-wallet (wallet-equal) sizing, 8h exit.** The two live secondary leads — "large wallets LEAD" and
"consensus rescues SMALL wallets" — are NOT tuned further on majors (that is the forbidden consensus-tuning);
they become HYPOTHESES for ALT external validation, where cells won't be degenerate (large+consensus was n=1
only because majors is sparse; on alts these wallets co-hold constantly). NEXT: alts as an EXTERNAL VALIDATION
set for the frozen scale-only rule (+ the two carried hypotheses) — NOT more majors dev, NOT MAE/MFE yet.
Artifact: capday_interaction.py, capday_interaction_report.json.

## 2026-07-16 — ALT EXTERNAL VALIDATION of the frozen scale-only rule: DIRECTIONAL REPLICATION (robust-positive, raw-spec magnitudes retracted)

**Question.** Does the majors-frozen entry rule (top-half-scale wallets of the capped-PnL top-30) show
positive copyable 8h markout on the SAME wallets' ALT entries (H1), and does LARGE out-rank SMALL (H2)?
Prereg: `ALT_VALIDATION_PREREG.md` (frozen 2026-07-14, before any alt return was viewed).

**Data unlock (feasibility probe finding).** The ledger's standing claim "Reservoir dropped alt closed_pnl"
was WRONG about the source — Reservoir has `realized_pnl` + `start_position` (zero nulls); only our retained
flow AGGREGATE dropped them. The frozen-cohort per-fill alt lake was already landed (`alt_ingest.py`, 333
days, 20.2M fills, 133 wallets, 202 coins; 61% of the cohort's fills are alts). The stale one-day smoke
`alt_episodes` part was rebuilt for all 11 months → 3,846 opening-taker alt entries (start_position=0,
crossed, ≤90s ctx staleness), 2,495 evaluable in-test, 717 after cohort-month membership (258 LARGE /
459 SMALL, 25 LARGE wallets, 8 folds). ~11× majors' 219 evaluable episodes; asset_ctx covers 79/79 entry coins.

**Result (validator print vs adjudicated).** Validator: H1 +196.9bp boot CI [+22.7,+347.4] P=0.99; H2
Δ+125.7 CI [−113.3,+363.1] P=0.80, 6/8 folds. Mandatory steelman + prosecutor passes (separate agents,
independent re-derivations — `audit/copy_cohort_alt_validation/FINDINGS.md`) CONVERGED:
- **Raw magnitudes RETRACTED as quotable:** 2/3 of the +197 headline lives in singleton/doubleton
  wallet-folds; raw H2 is carried by ONE +3074bp POPCAT entry (drop it → Δ+9.6, P=0.47); percentile
  bootstrap on 26 skewed clusters is anti-conservative (honest H1 wallet-level p≈0.05–0.13).
- **The directional signal SURVIVES every knife (prosecutor's own harshest spec):** winsor-p95 + wf≥3 →
  H2 **+87.4bp CI [+11.0,+165.3] P=0.987**, H1 +108.8 CI [+38.8,+174.9]; median shift LARGE +42.5 vs
  SMALL −12.8 (perm p=0.004); entry MW p=0.0044; survives dropping the POPCAT wallet entirely
  (+81.8 CI [+3.4,+165.7]) and dropping fold 202511 (H2 +92.6, P=0.965). Breadth: 17/25 LARGE wallets
  positive vs 13/33 SMALL; win rate 58.5% vs 47.1%.
- **Internal control:** SMALL stratum through the identical pipeline = −29.5bp — kills pipeline-bias and
  "alts drifted up" stories. Mark quality clean (lags ≤60s, no stale fallbacks, no dupes).
- **Dose-response (post-hoc, ex-ante variable):** the signal is STRONGEST at copyable notionals —
  ≥$1k entries +295 mean, 12/15 wallet-folds positive (p=0.018); notional Q4 +187/+93. Dust critique backfires.

**VERDICT (both gates).** DIRECTIONAL REPLICATION of the scale signal on a genuinely disjoint return
series — robust-positive, underpowered at the raw registered spec. The prereg's "not driven by 1 wallet"
clause fails on the RAW spec (POPCAT), so no clean "externally validated" stamp; all robust
(non-preregistered) specs clear with CIs excluding 0. Quotable: LARGE−SMALL ≈ +85–100bp gross; H1 core
≈ +70–110bp. Caveats: same wallets/new returns (not a fresh-wallet replication); gross edge ≈ one
realistic alt taker round-trip (20–100bp) → economically marginal as-is; per-coin sign only 6/10.

**Next (per prereg decision rule + economics):** (1) exit/cost path — the gross edge needs either maker
execution or the ≥$250–1k notional screen (where it is strongest) to clear alt taker costs; MAE/MFE +
own-exit study now justified on alts (N is there: 2.5k episodes); (2) fresh-wallet replication + N: the
all-wallet Reservoir aggregate pass (~$12 egress) to run capday selection on alt+majors PnL — new wallets,
one-shot test of the frozen rule; (3) carried hypotheses ("large lead solo", "consensus rescues small")
testable on alts where cells aren't degenerate — needs the alt holdings/position-state build.

**Artifacts.** `data/derived/copy_cohort/{alt_episodes/ (rebuilt, 11 months), capday_alt_validation_report.json}`,
`audit/copy_cohort_alt_validation/FINDINGS.md` (both adversarial memos), `alt_episodes.py` (unchanged),
`capday_alt_validate.py` (unchanged).

## 2026-07-16 — ALT-UNIVERSE FRESH-WALLET VALIDATION (all-wallet lake, arms C/T/P): registered NEGATIVE for capday selection; Arm T = underpowered positive

Ran the frozen ALT_UNIVERSE_PREREG (+addendum) on the completed all-wallet lake (334/334 days, 0 errors):
alt_select over ~54–73k eligible wallets/fold (real-data empirical null μ0=−0.64 σ0=1.40 π0=0.964),
8 folds, arms C (capday level) / T (t-stat) / P (EB posterior), then alt_fresh_validate on FRESH wallets
(97–100% disjoint from the old 133). Both mandatory adversarial passes run (separate agents; memos in
session artifacts; both reproduced the headline independently from the lake).

**REGISTERED HEADLINE (Arm C + scale): NEGATIVE, adequate coverage — the capday recipe does NOT
generalize.** H1 fresh −6.9bp CI[−127,+84]; H2 scale Δ−4.8 P=0.45; only 152 fresh entries in 8 months
(level-selected wallets are barely followable). Per the prereg's own decision rule: **the 2026-07-16
same-wallet alt result is DEMOTED to wallet persistence — the 133 wallets may be individually good, but
the selector that found them does not mint new ones.** H2-scale also reverses inside arm T (small > large)
→ the scale lead is likely a proxy the t-stat captures better; scale-only rule should not be carried.

**Arm P (max-consistency EB posterior): NEGATIVE** (−14.2bp, P(>0)=0.09, n=18.3k) — extreme consistency
selects quasi-HFT/dust profiles whose edge is not copyable at 8h (the markout study's oldest lesson).

**Arm T (t-stat of capped daily PnL): UNDERPOWERED POSITIVE (the prereg's middle branch, which was frozen
before data and therefore governs).** Robust +24.5bp CI[−3.0,+51.2]; NOT significant after registered BH
across 3 arms (one-sided p 0.036→0.11) — no significance claim. But: LOO-positive 56/56 wallets;
symmetric-trim stable (~+20 core); Wilcoxon on the registered unit p=0.026 (unadj); 11.8k fresh entries
(first FOLLOWABLE cohort, ~49/day); same-pipeline C/P controls null-to-negative (kills artifact stories);
**pre-stated notional dose-response replicates on fresh wallets with CIs excluding zero: ≥$250 +41.0
[+8.8,+73.0] (n=2,641), ≥$1k +99.1 [+11.6,+179.2]** — same shape as the 133-wallet study. Prosecutor's
strongest surviving points (recorded): best-of-3 argmax under null ≈ +14.7 expected (observed 0.56 se
above); wallet-collapsed sign = chance; folds 5/8; notional-weighted pooled book +12.6 gross < alt costs;
mechanism question OPEN — T-only picks +49 vs T∩P consensus +2.7 (steelman reads the same split as a
monotone t-purity gradient with P-only −33; unresolved).

**VERDICT (both gates, symmetric):** capday selection = clean registered negative (earned, adequate
coverage). Arm T = underpowered positive, direction replication-grade, NOT significant, NOT deployable
(pooled book under costs; deployable strata are secondary/hypothesis-grade). **Registered next step per
prereg: forward paper accumulation (~2 fold-months closes the two-sided CI at the current point), NO
re-tuning.** v2 score variants (winsorized-t, sign/binomial, downside-penalized) to be REGISTERED as new
method slugs before any evaluation — the method-keyed scores table (incerto TICKET-0035) exists for this.

Artifacts: data/derived/copy_cohort/{alt_universe_cohorts.json, alt_fresh_validation_report.json,
informedness/fold=*/pool.parquet}; alt_select.py, alt_fresh_validate.py, informed.py, lake.py;
ALT_UNIVERSE_PREREG.md (+addendum). Zero-overlap note: C vs T/P cohorts share 0 wallets; T∩P 24/30.

## 2026-07-16 (evening) — V2 BAKEOFF + DECAY ANATOMY + CONSTRUCTION GRID (all candidate-ranking on burned folds)

Three registered follow-ons to the fresh-wallet validation, all on burned folds 202511–202606 (reuse-stamped:
ranking/diagnosis only, no significance claims). Preregs: V2_BAKEOFF_PREREG.md, DECAY_ANATOMY.md (diagnostic),
CONSTRUCTION_PREREG.md. Interim: the z-band "rising star" refinement (TSPLIT_HYPOTHESIS.md) was killed by its
semi-fresh probe BEFORE these ran — zband on unseen wallets −0.5bp CI[−29.8,+28.1], upper bound excludes the
hypothesized +49 (powered negative for that effect; winner's-curse within the labeled 130). zband_semifresh.py.

**1. V2 bakeoff (6 selector arms, v2_bakeoff.py):** *(2026-07-17 audit correction: these CIs were
bootstrap-understated; corrected t_v1 [−4.4,+65.4] / t_noliq [−3.2,+60.1] both SPAN 0, BH .148 — see
AUDIT-FIX RE-PRINT; the ≥$250 strata still exclude 0.)* t_v1 +27.6 [+0.7,+53.1] 7/8 folds and t_noliq +27.4
[+2.6,+51.1] 8/8 (≈90% cohort overlap; the liq screen dodges the bad fold) lead; zband +15.6, notional-floor
+13.0, winsor_t +5.9, sign_stat +5.1 all span 0. Min BH-adj p=0.070 → still AMBER. ≥$250 stratum stronger for
both leaders (CIs excl 0, same taint). SELECTION IS AT ITS CEILING — no alternative ranking beats plain t.
Paper-trader arms per registered rule: t_v1 + t_noliq, entries weighted toward ≥$250.

**2. Decay anatomy (decay_anatomy.py — answers "why do good-t wallets decay OOS"):** they don't. Cohort
trader-persistence (own forward capped PnL/day > 0) = **79.7% vs 33.9% pool base rate (2.35×)** — t-selection
finds REAL traders. The copy shortfall decomposes: 119/240 wallet-folds have ZERO evaluable alt flat-open
entries (coverage hole); of trader-won folds 39% still copy-lose (wedge). Negative tail ≈ 53% wedge / 47%
curse. Within-cohort, formation t/z carry NO dose signal for who fails (p≈.5–.7) → better selection stats
can't fix it; copy CONSTRUCTION is the lever. Quadrant medians: TW·CW +63.5bp copy; TW·CL −58.6; TL·CL −68.4
(trader-lost fwd own capday −$448/d median).

**3. Construction grid (construction_study.py; 15 cells = {E1 alt flat-opens, E2 +majors, E3 +adds} ×
{1h,4h,8h,24h,48h}; adds pulled on the DROPLET — laptop crashed streaming them; droplet pattern is now the
default for per-fill pulls):** coverage 93→156 (E2) →165 (E3) of 240 wallet-folds — majors entries alone
nearly double visibility. Horizon: the edge is FRONT-LOADED — E1/1h +21.8 [+7.1,+40.2] 7/8 ≈ same point as
E1/8h +23.0 [−9.5,+59.3] at ~⅓ the CI width; E3/4h +14.5 [+3.5,+25.9] 8/8 on 2.6M entries; 24–48h cells all
degrade/span 0. All GROSS mid-to-mid: shorter horizons fix variance/turnover, NOT the taker-cost wall.

**Open decisive question (running):** lag haircut — asset_ctx is per-minute so seconds-scale follower lag
needs the tape itself; measuring markout with follower entry = first print at trader-fill +{0,3,10,30}s +
slippage decomposition (trader px vs next print). If the front-loaded 1h edge dies at 3–10s lag, the gross
was trader priority/impact, not followable drift → maker-entry or nothing. Report:
data/derived/copy_cohort/lag_haircut_report.json when done.

### 2026-07-16 addendum — LAG HAIRCUT: the 1h edge is FOLLOWABLE (survives 30s lag at real print prices)

Decisive economics check (lag_haircut.py; prints pulled on droplet; report lag_haircut_report.json).
Follower entry px = FIRST TAPE PRINT at trader-fill +{0,3,10,30}s (asset_ctx is per-minute → tape is the
only honest sub-minute basis), E1 alt flat-opens, arm-T cohorts, endpoints asset_ctx mid at +1h/+4h.
RESULT: 1h robust wallet-equal is FLAT across lags — +18.1/+18.9/+19.5/+18.9 bp at 0/3/10/30s, ALL CIs
exclude 0 (P>0=1.00, wf=86); slippage of lagging = median −0.6/−1.0/−1.4 bp; drop rate ≤1.5%. The
front-loaded edge is followable drift, NOT trader priority/impact. Basis note: entry at print px embeds
the entry-side spread → remaining costs = fees (~5–9bp RT) + exit side; wallet-equal net ≈ +10bp at 1h.
Entry-EQUAL mean at print basis ≈ 0 → dust entries earn nothing after their spread (independently
confirms the ≥$250 screen). 4h cells positive but CIs span 0 (variance growth) — 1h is the deployment
horizon candidate. Same reuse stamp as the construction grid (burned folds); the paper trader confirms.

### 2026-07-16 addendum 2 — LIQUIDITY CUT: the alt book's edge is in untradeable names; MAJORS is the deployable cell

Post-hoc ADV-bucket cut (hypothesis-grade, burned folds) of the >=\$250 alt book @1h/10s-lag: ADV<\$1M
+39.8bp (15.6% of book — 50-150bp RT coins, unharvestable), \$1-10M −16.7, \$10-100M −15.0 (together 79%
of the book, NEGATIVE), >\$100M +43.6 (n=134, wf=8, anecdote). The >=\$250 aggregate +41 was carried by
illiquid names → the LIQUID-ALT copy book at 1h is NOT supported. DEPLOYABLE CELL = E2 MAJORS @1h:
+7.5bp CI[+1.2,+14.3] 7/8 folds, majors RT ~2-4bp → ~+4bp net, unlimited practical liquidity, lag-proof.
Paper-trader spec should arm: (A) majors E2/1h book (primary), (B) liquid-alt (ADV>\$10M) book as a
falsification arm (expected ~0 per this cut), both t_v1 + t_noliq. Illiquid-alt paper profits are to be
reported but labeled unharvestable.

### 2026-07-16 addendum 3 — K-SWEEP × VENUE + book economics: majors dead; K=100 liquid-alt = the candidate

Naive daily-equity sim ($5k clips, no netting): majors book ann. Sharpe ≈ 0.12 (+$1.2k/8mo), alt book at
30bp cost Sharpe −3.6 → per-trade edge real but naive book economics insufficient; position-state netting
is the remaining Sharpe lever. Registered K-sweep (ksweep.py, 8 cells, burned folds): MAJORS ≤0 at every K
(K=100 CI [−5.6,+4.5] — tight zero, venue dropped); LIQUID_ALT(ADV≥$10M) frontier improves with K →
K=100: +15.3 [+3.6,+28.6] P=0.995, 20 entries/day, 120 wallets. FLAG: partially contradicts the addendum-2
bucket cut (−15 on $10-100M within the K=30 book) — both burned; paper trader adjudicates. Candidate spec:
K=100 t-stat (fresh, no-liq screen optional) × liquid-alt trailing-ADV≥$10M × ≥$250 × 1h; net ≈ 0-8bp/trade
after lag+costs; position-state construction still untried. Census pending.

### 2026-07-16 addendum 4 — COHORT CENSUS: the signal is one archetype; 12/145 are PUBLIC VAULTS

COHORT_CENSUS.md/cohort_census.json (kmeans k=5, post-hoc descriptive). Copy markout concentrates in the
"diversified alt grinder" archetype (33/145: breadth≥10 coins, taker 0.2-0.7, 100+ active days): +33 pooled
/+26 median on 75% of copy entries; all other archetypes ≤0 or structurally uncopyable (14 pure makers emit
zero copy entries — free selection filter). Persistent core = anonymous HFT/maker bots (real PnL, uncopyable
flow) → explains the coverage hole + wedge. 12/145 wallets are PUBLIC HL VAULTS (16% of re-selected) incl.
PF1 3×-selected +39bp/821 entries → VAULT-DEPOSIT arm: selector as vault-picker sidesteps lag/spread/wedge
entirely (own the actual fills). Next registered candidates: archetype-gated K=100 liquid-alt book;
vault-ranking deposit strategy. All hypothesis-grade (post-hoc labels) — prereg before evaluation.

### 2026-07-16 addendum 5 — MAJORS-NATIVE × HORIZON: majors alpha exists at 8h (user's horizon hypothesis right)

majors_native.py (registered first; burned folds, candidate-ranking). Venue-matched selection (t-stat on
MAJORS-only capped PnL) × horizons: at 1h still ~0 (prior null NOT a selection artifact at that horizon),
but term structure rises to K30/8h = +28.1 [+4.0,+54.8] P=0.99, 5/8 folds, 23 e/day, fading by 48h.
K30 ≫ K100 (majors skill concentrated — opposite of alts). Survives fee/lag arithmetic at 8h. Caveats:
10 dependent cells, 8h a-priori favored, ~16/30 cohort overlap with arm-T. PAPER-TRADER CANDIDATES now
three: (1) K100 liquid-alt @1h (+archetype gate hypothesis), (2) K30 majors-native @8h, (3) vault-deposit
ranking (12 public vaults). Forward paper data adjudicates all three; no further burned-fold sweeps.

### 2026-07-16 addendum 6 — WALLET×COIN HIERARCHICAL SELECTOR: coin-conditioning does NOT beat pooled selection (registered CLOSING LOOK — burned folds retired)

wallet_coin_selector.py (registered first; burned folds, candidate-ranking, declared LAST look).
Per-(wallet,coin) capped-PnL t (wallet-DAY-level cap, nd_wc≥8) probit-z, EB-shrunk toward the pooled z
(w=nd_wc/(nd_wc+20), τ=20 frozen), top-300 cells/fold, trailing-ADV≥$10M venue rule (no look-ahead),
copy each wallet ONLY in its selected coins @8h majors/1h alts. Result: MAJORS +2.1 [−12.0,+15.9],
ALT +1.6 [−9.7,+13.5], COMBINED +2.0 [−9.2,+12.5] — each sub-book's CI upper bound BELOW its same-venue
baseline point (majors-native K30/8h +28.1; K100 liquid-alt/1h +15.3). Method-scoped ranking, not a
"coin-conditioning dead" claim (combined CI still admits +12). Census: only 38% of the 1,193 selected
cells are specialists (share≥0.5), median share 0.21 — the selector mostly picks generalists' best
coins; shrinkage toward pooled z re-imports the dilution it tried to escape, and high-nd_wc cells skew
HFT-ish (uncopyable flow). NOT armed on the paper trader. Selection tables at
data/derived/copy_cohort/wallet_coin_selection/. BURNED FOLDS NOW RETIRED — paper trader only.

### 2026-07-16 addendum 7 — BACKTEST + TERM-STRUCTURE-BY-ARCHETYPE: user's HFT thesis rescues the alt book at 8h

BACKTEST.md (descriptive, frozen specs, all costs): majors@8h = ONLY profitable book (+$10.7k net, Sharpe
+1.02, Sortino +1.79, maxDD 20%, +13bp/trade net); liquid-alt@1h NEGATIVE net (−$19.2k, gross +12 < 21.5bp
RT); gross positive every month (+$39k) — costs are the killer. Sizing: S1 fixed-clip sanest by principle
(S2 per-wallet-equal anti-weights busy days — single-entry wallet-days are strongly NEGATIVE, +11-entry days
+99bp — activity-conditional entry rule registered as forward hypothesis; S3 saturated). Archetype gate lifts
alt gross +11.9→+16.6 (helps, insufficient at 1h). TERM STRUCTURE BY ARCHETYPE (descriptive): user's thesis
confirmed with corrected mechanism — HFT entries (3% count) have actively NEGATIVE long-horizon markout
(−67 @24h, −121 @48h, CIs excl 0), poisoning the pooled long end; ex-{HFT,dust} ≥$250 curve RISES
monotonically +19.6/+26.0/+50.4/+72.3/+82.0 (1h→48h), grinder archetype +65.5 @8h CI[+34,+103] → nets ~+40
over alt costs. The 1h alt exit was a pooling artifact. FINAL PAPER SLATE (burned folds now fully retired):
(1) majors-native K30 @8h, (2) GATED-ALT (grinder archetype, ≥$250, ADV≥$10M) @8h — REPLACES the 1h spec,
(3) vault-deposit ranking. Convergent spec: human traders, ≥$250, 8h, both venues.

### 2026-07-16 addendum 8 (CLOSING) — FINAL SLATE BACKTEST: alt copy book dead at 8h too; majors@8h + vaults is the strategy

final_backtest_report.json / BACKTEST.md §FINAL SLATE (descriptive, burned): Book M majors@8h +$10,691,
SR 1.02, +13.0bp/tr (ex-bot-entries variant slightly worse — seats matter, entries don't). Book G gated-alt
@8h in LIQUID (trailing ADV≥$10M) names: −$8,730, −42.2bp/tr — the term-structure +65.5 grinder cell had NO
liquidity screen; screened, the gross itself goes negative. CONCLUSION: the alt copy edge is an
ILLIQUID-COIN phenomenon at every horizon tested (1h and 8h) — real markout, untradeable exit; market
intelligence, not a book. Alt copying SHELVED (revisit paths: maker execution; or vault deposits, which hold
the traders' actual alt positions natively — the only vehicle that monetizes this edge). FINAL FORWARD
SLATE: (1) majors-native K30 @8h copy book (+ bot-seat-recovery selection variant, + daily-rolling cadence
variant), (2) vault-deposit ranking. Burned folds fully exhausted and retired.

### 2026-07-16 addendum 9 (FINAL) — RECONCILIATION: the alt edge lives in within-hold repeat entries; pyramiding is the forward hypothesis

reconciliation.py/report + BACKTEST.md §RECONCILIATION. (1) Dollar-book CIs (day-block bootstrap): Book G
−42.2 [−86.8,+1.4], firmly excludes the +65 surface (p=0.002 vs +20) — death real, not small-n; Book M
+13.0 [−17.9,+42.1] — majors book is ALSO an underpowered positive, not proven. (2) DECISIVE stage
decomposition: grinder stat +65.5 → +54.0 after trailing-ADV (liquidity NOT the killer) → −3.6 after
max-1-concurrent dedup: the edge sits in 2nd..Nth entries fired WHILE ALREADY IN POSITION (conviction
bursts) — signals a single-position copy book structurally discards. User's burst intuition correct as
DAY-STATE (K100@1h flips +5.8 net SR 1.17 under within-day ≥2-entries conditioning; underpowered post-hoc);
burstiness-as-TRAIT refuted (corr ≈ 0). Sparse-wallet hypothesis (mine) refuted. FORWARD SLATE (final):
(1) majors-native K30 @8h [underpowered +], (2) PYRAMIDING alt book — add-on-repeat-entry, harvesting the
burst edge as SIZE not entries [new registered hypothesis], (3) vault-deposit ranking, (4) day-state
conditioning variant. Burned folds exhausted; every open question now has a named forward test.

### 2026-07-17 — PYRAMID-ALT mechanics verified: ladder harvests the burst edge gross (+21.8bp/u); net sits exactly on the taker-cost wall

pyramid_book.py per frozen PYRAMID_ALT_PREREG.md (descriptive, no variants): 3,668 units/1,713 theses,
gross +21.8bp/u (+$19.9k) — first dollar realization of the +65 repeat-entry surface — net +0.25bp/u
CI[−27.5,+25.9] vs 21.5bp taker RT. VERDICT: the alt edge is real and harvestable GROSS by the ladder;
economics hinge entirely on execution cost → the maker shadow book (fill-rate vs ~2bp) is THE forward
number. Slate final: PYRAMID-ALT lead (maker path decisive), majors@8h side, vaults, day-state variant.
Deviations to add before arming: trader-exit hard stop, maker shadow. Forward criteria per prereg (60/120d).

### 2026-07-17 addendum — WALLET ATTRIBUTION: user's dragger thesis confirmed for the alt book (taker-side HFT leak)

wallet_attribution.{py,md}/report (descriptive, ex-post caveats stamped). Book P (pyramid): broad positive
body (59% wallets+, median +31.5bp/wallet) dragged to +0.25 by concentrated blowups — #1 dragger is a
22k-fills/day TAKER-side HFT bot (0 majors formation) that the taker-share<0.1 screen structurally misses:
−$7.4k/888 units; ex-dragger-1 book = +10.9bp NET at taker costs. Dragger profile: hyperactive/breadth/bot
(trades/day 19.9 vs 3.7 winners; nothing p<0.05, hypothesis-grade). PREREG AMENDMENT (intent-implementation,
timing stamped): add fills/day<1000 bot screen (pre-existing majors_archetype criterion) to PYRAMID_ALT spec.
Book M (majors): NOT a dragger story — winners' book (6 majors-only specialists carry +20bp; typical wallet
flat; drop-best-7 goes negative). Hypothesis-grade lean: majors book wants majors-SPECIALISTS (high majors
share, low breadth); losers were breadth/alt profiles ranked on majors t. Registered as forward variant only.

### 2026-07-17 addendum 2 — VENUE-MATCH RE-CUT: convergence story NOT confirmed; M-specialist lean re-expressed, P anti-monotone

venue_match.{py}/venue_match_report.json + WALLET_ATTRIBUTION.md §VENUE-MATCH (descriptive, burned folds,
post-hoc-motivated cut of a pre-existing feature; dependent cells). Formation 3-mo majors-share buckets on
both frozen books. M: PnL fully concentrated in MATCHED specialists (97% of net $, +23.0 vs +3.8 bp pooled;
wallet-equal gross +20.1 vs −30.9) but MISMATCHED cell empty (1 wf/6 trades — selector admits no alt
wallets), MATCHED CI [−22.7,+73.1] spans 0, %wf>0 ≈ equal → same p≈0.07 lean re-expressed, NOT new evidence.
P: pooled net ANTI-monotone (majors-profile MISMATCHED +13.1 > MIXED +5.2 > alt-native MATCHED −4.3); the
alt-native deficit is the known taker-HFT dragger (ex-0x223537ac MATCHED ≈ +17.2bp) — P's drag is the BOT
screen, not venue; NO alt-native filter justified. 0xa1b6d8ef sign-flip debunked as venue story: MIXED
(maj% 0.37–0.54) in both books every fold; flip = fold-timing noise. Forward: only the already-registered
M majors_share≥0.8 specialist variant survives (cost now quantified: sheds ~15% flow / ~3% PnL burned).

### 2026-07-17 addendum — CONSENSUS CONDITIONING (pre-declared 3W×3L grid + top-t variant, both books)

consensus_conditioning.py / consensus_report.json / WALLET_ATTRIBUTION.md §consensus (descriptive, burned,
20 dependent cells, grid stamped before outcomes). Entry-equal NET: crowd (≥2 others, same coin+dir, trailing
W) positive in ALL 6 (book,W) cells (A +92/+60/+42; B +37/+33/+31) while solo ≈0-to-negative everywhere —
both books' entire net profit sits in crowd entries. Strict pre-set rule (CI-clear + all-window consistent):
NOTHING qualifies. CI-clearing cells (2/20, uncorrected): B/1h/crowd +54.7 [+15,+101] *(2026-07-17: FLIPS
to spanning 0 under the binding coin-day cluster CI [−10.2,+106.1] — see AUDIT-FIX RE-PRINT)*; TOP-HALF-T
consensus — B gap +121 [+32,+203], A crowd +98.7 [+46,+155] *(both survive coin-day clustering)* — replicates the sparse majors "consensus rescues" lean in
both books. Volume at crowd: B 57-79%, A 22-47% (deployable gate, not thin). REGISTERED FORWARD VARIANT:
consensus-gate arm (skip solo entries; smart-money variant = top-half-t pool, W=6h) on both paper books.
Hypothesis-grade until forward data.

### 2026-07-17 addendum (WRAP) — CONSENSUS-GATED BACKTEST: combined smart-money book = SR 1.89, the study's best

gated_backtest.py / gated_backtest_report.json / BACKTEST.md §CONSENSUS-GATED (descriptive; gate ex-post-
conditioned — NOT forward evidence). Combined smart-money book (pyramid-alt bot-screened + majors K30, skip-
solo/top-half-t 6h gate): +$15,167 net / +30.2bp/tr / SR 1.89 / Sortino 3.12 / maxDD 8.9% / 6/8 months+,
CI [−7.2,+69.8] (includes 0). Gate halves turnover, ~doubles per-trade net, does NOT shrink DD (concentrates);
202604 = 65% of profit. Per-book: pyramid crowd SR 1.45 (+$11.1k, +35.9bp); majors smart SR 1.28 (+$6.4k,
+23.7bp). FORWARD MUST CONFIRM: gated−ungated gap ~+15-20bp; smart>crowd>solo ordering; SR>1 sans single-
month dependence. This is the paper-trader target spec; burned-fold work concludes here.

### 2026-07-17 — AUDIT-FIX RE-PRINT (cluster-bootstrap multiplicity + NULL-markout guard + gate ordering + two-way CIs)

Six audit fixes implemented on top of snapshot 1535c74 and every affected report re-run (all re-emitted
reports stamp `code_commit: 1535c74-dirty`). Fixes: (1) **CRITICAL — cluster bootstrap collapsed duplicate
wallet draws** (resample concatenated duplicate picks but the statistic keyed wallet|fold via np.unique →
duplicates merged → variance understated). Fixed with multiplicity-preserving pseudo-cluster tags
(`wallet#j` per draw), verified ≡ the ksweep weighted pattern to 1.4e-14; synthetic probe (60 wallets,
known random effect): 95%-CI coverage 0.844 (old) → **0.952 (fixed)**, mean CI halfwidth +~30%. Affected:
alt_fresh_validate `_cluster_boot`/`_paired_delta_boot`, v2_bakeoff `_boot`, capday_alt_validate
`_paired_h2`/`_h1_bootstrap`, walkforward `_wallet_equal_bootstrap_ci` (wallet leg). ksweep/majors_native
cell boots were ALREADY correct (weighted). (2) **NULL-markout guard**: bare `np.asarray` on duckdb
fetchnumpy masked columns exposed fill garbage as finite markouts; ported construction_study's
masked→NaN `_np()` into alt_fresh_validate/ksweep/majors_native/v2_bakeoff. Real effect: majors_native n
was a constant 5,655/12,264 across ALL horizons pre-fix (leaked NULLs), now falls with horizon as it must
(K30: 5,614@1h → 5,250@48h). (3) **median-perm permuted entries, not wallets** → rebuilt as wallet-label
permutation (whole wallets move between arms). (4) **gated_backtest ordering**: concurrency/dedup now runs
FIRST, gate = pure subset of accepted entries (the 'same entries' prose was false for book B pre-fix);
old ordering kept as labeled 'gate-pre-concurrency (burst-entangled)' rows; BACKTEST.md re-emitted with
corrected prose. (5) **consensus CIs two-way**: every cell/gap now reports wallet-cluster AND
(coin × calendar-day)-cluster boot CIs; the WIDER is quoted (gated_backtest already day-block — no change
needed there). (6) alt_select `top()` → total deterministic ordering (key desc, tie desc, wallet asc) —
prospective only, frozen cohorts JSON untouched. Reconciliation anchors still tie (pyramid re-sim 3,668
units / $232.87 vs attribution $232.89 in both re-runs). walkforward.py code fixed but NOT re-run — its
2026-07-12 report's `wallet_equal_ci.wallet_only` legs are understated per the probe (nominal 95% ≈ 84%
actual); treat its week_block/two-way CGM numbers as the binding ones until a re-run.

**BEFORE → AFTER (all changed headline numbers; robust wallet-equal bp unless noted):**

| study / cell | old (pre-fix) | corrected | verdict change |
|---|---|---|---|
| alt_fresh arm C H1 | −6.9 [−127.0,+84.1] | −6.9 [−145.2,+121.3] | none (spans 0) |
| alt_fresh arm T H1 | +24.5 [−3.0,+51.2] P=.96 | +24.6 [−9.2,+62.1] P=.93 | none (underpowered positive, wider) |
| alt_fresh arm P H1 | −14.2 [−36.8,+6.1] P(>0)=.10 | −13.9 [−42.6,+13.9] P(>0)=.17 | negative lean SOFTENS |
| alt_fresh H2 scale Δ (C) | −4.8 [−181,+177]; med-perm p=.017 | −4.3 [−214,+194]; wallet-perm p=.243 | med-perm "signal" GONE (entry-perm artifact) |
| alt_fresh H2 Δ (T) med-perm | p=.0006 | p=.100 | FLIPS to non-significant |
| alt_fresh T−C / P−C | +32.1 [−78,+161] / −5.0 [−113,+121] | +32.7 [−111,+180] / −4.6 [−152,+143] | none (span 0) |
| v2 bakeoff t_v1 | +27.6 [+0.7,+53.1] BH=.070 | +27.8 [−4.4,+65.4] BH=.148 | **CI FLIPS to spanning 0** |
| v2 bakeoff t_noliq | +27.4 [+2.6,+51.1] BH=.070 | +27.5 [−3.2,+60.1] BH=.148 | **CI FLIPS to spanning 0** |
| v2 t_v1 / t_noliq ≥$250 stratum | +50.3 / +39.6 (excl 0) | +50.3 [+3.7,+104.0] / +39.6 [+5.9,+80.9] | still exclude 0 (only surviving excl-0 v2 cells) |
| majors_native K30/8h | +28.1 [+4.0,+54.8] n=5,655 | **+29.0 [+4.9,+55.6]** n=5,494 | survives (marginally stronger) |
| majors_native K30/48h | +8.4 [−45.6,+64.6] | **+19.0 [−40.1,+75.7]** n=5,250 | point ↑ (NULL-leak was diluting); spans 0 |
| majors_native K100/8h / K100/48h | +7.3 [−4.5,+19.4] / +7.7 [−21.2,+36.2] | +7.5 [−4.3,+19.5] / +14.1 [−17.4,+46.2] | none (span 0) |
| ksweep K100/LIQUID_ALT | +15.3 [+3.6,+28.6] | +15.7 [+4.0,+29.1] n=4,881 | survives (boot was already correct; NaN-guard only) |
| ksweep K50/MAJORS | −4.8 [−12.3,+1.5] P(>0)=.077 | −4.3 [−12.1,+2.4] P(>0)=.113 | negative lean softens |
| capday_alt H1 large boot | [+22.7,+347.4] P=.99 | +196.9 [+7.8,+495.0] P=.98 | survives, CI much wider |
| capday_alt H2 large−small | +125.7 [−113,+363] | +126.0 [−219,+475] | none (spans 0, wider) |
| consensus B/1h/crowd | +54.7 [+15.1,+101.2] (CI-clearing cell) | wal [+15.1,+101.2] / coin-day [−10.2,+106.1] → binding coin-day | **FLIPS to spanning 0** (was 1 of the 2 uncorrected CI-clearing grid cells) |
| consensus B topT gap (smart) | +121.1 [+31.6,+203.0] | wal [+31.6,+203.0] / coin-day [+32.1,+160.1] | survives BOTH cluster units |
| consensus A topT crowd | +98.7 [+46.0,+154.8] | wal [+46.0,+154.8] / coin-day [+21.7,+171.6] | survives BOTH cluster units |
| consensus B/6h/pair | −60.8 [−128.2,−1.8] | wal [−128.2,−1.8] / coin-day [−93.7,+3.3] (binding wal) | quoted CI still excl 0; coin-day view spans |
| gated B_crowd | +18.9bp SR 1.11 (burst-entangled) | **subset-gate +24.2bp SR 1.36** (preconc row: +18.9/1.11) | subset ordering HELPS (+5.3bp, n 1,194→1,114) |
| gated B_smart | +23.7bp SR 1.28 | **subset-gate +27.3bp SR 1.42** (preconc: +23.7/1.28) | subset ordering HELPS (+3.6bp, n 1,074→981) |
| gated COMBINED_smart | +$15,167 / +30.2bp / SR 1.89 CI[−7.2,+69.8] | **+$15,499 / +32.4bp / SR 1.97 CI[−8.1,+69.0]** | still spans 0; still ex-post-conditioned |

**Net read-through:** (a) the v2 bakeoff full-sample "CIs excl 0" for t_v1/t_noliq were a bootstrap
artifact — both leaders are now underpowered positives (points unchanged ~+28, one-sided p .04–.05,
BH .148); the ≥$250 strata are the only v2 cells whose corrected CIs exclude 0. (b) The alt_fresh
median-perm p-values (the strongest-looking H2 numbers) were entry-permutation artifacts and are gone.
(c) The majors 8h cell — the forward slate's anchor — SURVIVES the corrected inference at both K
(K30/8h +29.0 [+4.9,+55.6]) and got slightly stronger after the NULL-leak fix; K100 liquid-alt also
survives. (d) Of the consensus grid's two uncorrected CI-clearing cells, B/1h/crowd dies under coin-day
clustering; the top-half-t (smart-money) results survive both cluster units in both books — the forward
smart-gate spec is unchanged. (e) The subset-ordered gate is BETTER than the burst-entangled one
(+3.6–5.3bp/trade, SR 1.36–1.42 vs 1.11–1.28), so the old gated rows UNDERSTATED the gate — but the
combined book's day-block CI still includes 0 and remains non-evidence (ex-post gate). Arm T, capday-alt
directional replication, and all other standing verdicts are unchanged in direction, with honestly wider
CIs. Artifacts: alt_fresh_validation_report.json, v2_bakeoff_report.json (selections frozen, re-inferred),
majors_native_report.json, ksweep_report.json, capday_alt_validation_report.json, consensus_report.json
(+WALLET_ATTRIBUTION.md re-print), gated_backtest_report.json (+BACKTEST.md re-print).

### 2026-07-17 — TWEEDIE POSTERIOR MEAN: winner's-curse de-bias + sizing weight off the frozen f-hat (descriptive)

User's idea ("P_informed(z) × denoised effect at z") = the empirical-Bayes posterior mean of the effect;
exact closed form is Tweedie (Efron 2011): E[θ|z] = z + σ0²·d/dz log f(z). Since the two-groups f-hat is a
degree-5 log-polynomial, the correction is σ0²·polyval(coef_f', z) — computed straight off the EXISTING fit,
no constants tuned (`informed.two_groups` now also returns `theta_hat`/`theta_of`/`coef_f`; `tweedie_diag.py`).
Descriptive/diagnostic only — NOT a new selector (registration would be needed for any forward claim).

**Exactness verified:** closed-form (θ−z)/σ0² matches a central finite-difference of the fitted log-density
to max|err| 3.7e-9 on the occupied support; θ(z) is monotone across the selection tail → it does NOT reorder
the top-30 (confirms the a-priori read: a magnitude/sizing tool, not a selection lever; consistent with the
v2 bakeoff "t is at the selection ceiling").

**Winner's-curse haircut on the frozen arm-T cohort (30/fold, naive z_sel → de-biased θ):**
202511 6.23→5.68 (×0.91) | 202512 6.44→6.22 (×0.96) | 202601 6.49→5.27 (×0.81) | 202602 7.09→5.44 (×0.77) |
202603 6.59→3.98 (×0.62) | 202604 6.68→4.64 (×0.70) | 202605 6.86→5.64 (×0.82) | 202606 7.50→5.94 (×0.79) |
202607 7.32→7.16 (×0.98). So the selected wallets' apparent formation t is overstated by ~2–38% (worst 202603);
the de-biased effect is the honest magnitude the ledger's "winner's curse" caveat kept invoking, now quantified.

**Sizing:** per-wallet weight ∝ max(θ,0) is near-even (top-5-of-30 share 0.17–0.21 vs 0.167 uniform) — mild tilt
to the highest-z wallets, NOT concentrated → Tweedie sizing ≈ equal-weight with a gentle lean, so it won't
introduce a fragile few-wallet bet. **CANNOT overcome the study's binding limit:** θ de-noises the FORMATION
effect, and the weak link is formation-θ → forward-copyable edge (buried under ~164 bp/trade; structure not raw
t is what carries forward). Denoising a weak predictor yields a cleaner weak predictor. **Use:** (1) winner's-
curse-corrected expected magnitude for the paper-trader's honest priors; (2) a principled continuous sizing
weight — both fold into the paper-trader spec; NOT a selection claim. Artifacts: `tweedie_diag_report.json`,
`tweedie_diag.py`, `informed.py` (theta_of/theta_hat/coef_f added).

### 2026-07-17 — WHALE-TILT of Tweedie: NEGATIVE here (daily cap severs score↔size); + registered forward rules

**Tested the "Tweedie makes whales do better (lower hit-rate, higher return)" claim on our frozen arm-T
cohorts (192 cohort-wallet-folds).** Result: it does NOT transfer to this construction.
- corr(θ, log scale) = **+0.054**; corr(z, log scale) = +0.025; rank-corr +0.084 — θ ⟂ wallet scale.
- θ-weighted mean log-scale 5.442 ≈ equal-weight 5.426 → θ-weighting sends NO extra capital to big wallets.
- mean θ LARGE +5.39 (n97) vs SMALL +5.32 (n143), despite LARGE median notional $754 vs SMALL $55 (~14×).
**Mechanism:** the folklore holds where the *score correlates with size* (raw $-PnL / liquidity-weighted
alpha). Our metric is capped ($100k/day) + vol-normalized t = a CONSISTENCY score, so the ±cap deliberately
severs score↔size; θ is size-neutral and the whale/lumpiness channel never engages (also why the Tweedie
weights are near-even, top-5-of-30 ≈ 0.18). Reproduce: the θ-vs-scale block over `informedness/fold=*` ⋈
`alt_universe_cohorts.json` scale_med_notl.

**REGISTERED FORWARD RULES (frozen a priori, evaluate on forward/new data only — NOT tuned on burned folds):**
- **`theta_weight_v1` sizing/selection:** copy weight ∝ max(θ,0) (Tweedie posterior mean, `informed.theta_of`)
  over the bot-screened (fills/day<1000, taker_share<0.1) + liquid (trailing ADV≥$10M) + ≥$250 pool; N is
  EMERGENT (no top-K), single-wallet weight capped (cap TBD, e.g. 10%) so no name dominates. Replaces
  "top-30 equal-weight." Also carries the winner's-curse-corrected θ as the honest expected-magnitude prior.
- **`capday_monthcap` candidate metric slug:** metric = mean of DAILY-capped PnL additionally capped at the
  MONTH level, ÷ active days. A-PRIORI PREDICTION (pre-committed): small effect on THIS selection (θ already
  whale-flat; monthly cap bites hyperactive many-capped-days wallets already removed by the bot screen);
  DIRECTION = more-consistency/less-magnitude (raise hit-rate, lower return concentration) — the OPPOSITE
  lever to the whale tilt. To be evaluated only if a forward test is run; reordering-vs-daily-cap is a cheap
  burned-fold diagnostic (allowed) but any edge claim needs forward data.

**Next (offered):** direct hit-rate/return test = θ-weight vs equal-weight forward BOOK on the arm-T cohort
(the paper-trader comparison) — the only thing that measures the "lower hit-rate/better-return" claim head-on.

### 2026-07-17 — TWEEDIE N-SIZING actually RUN: no lift over equal-weight top-30 (registration demoted)

Ran the θ-weight / emergent-N book on the arm-T cohort's REAL forward 8h alt markouts (8 burned folds,
winsor-p95 + wf≥3, self-truncating top-200-by-θ pull; `tweedie_sizing.py` / `tweedie_sizing_report.json`).
Answers the user's "did we try the Tweedie sizing" directly — YES, and it does not beat equal-weight.
- **θ-weight ≈ equal at N=30:** 18.5 vs 18.8 bp (Δ ≈ −0.3, negligible vs these books' single-digit-to-tens-bp
  noise), hit rate identical 57.5%, effective N 232 vs 240 (θ concentrates only ~3.5%). The cap-neutralized
  score is too flat to reweight — consistent with the whale-flat finding (corr(θ,scale)=+0.05).
- **Emergent N wider HURTS:** top60 13.9 / top100 14.2 bp, hit 54.4/54.5% — expanding past top-30 dilutes
  return (18.8→~14) and hit rate (57.5→54.5). Ranks 31–100 by θ add lower-return, same-hit-rate flow →
  emergent-N wants to go TIGHTER, not looser. (top100==top200: only ~573 followable wallet-folds exist in
  the top-200, so the θ-book self-truncates.)
- **The "lower hit-rate / higher-return" whale signature does NOT appear:** hit rate is flat ~54–58% across
  every scheme and θ-weighting doesn't raise return — the cap severs the size channel it would ride.

**Registration correction (anti-ratchet — the test was built and run, no lift):** `theta_weight_v1` is
DEMOTED from the forward sizing spec — equal-weight top-30 is retained (θ-weight gives no improvement and
wider-N dilutes). The Tweedie θ column stays useful for its OTHER job — the winner's-curse-corrected
expected magnitude (the honest prior, per the 2026-07-17 de-bias entry) — just not as a sizing/N rule.
Method-scoped: "θ-posterior-mean sizing does not beat equal-weight on this cap-neutralized selector."

### 2026-07-17 — ENTRY-LEVEL (per-trade) SHAPE: near-coinflip hit rate + broad right skew; notional-sizing is the lottery, equal-$ is robust

The sharper question the wallet-collapsed test couldn't answer. Arm-T roster forward 8h alt markout, RAW
(no winsor), 11,728 entries / 63 wallets, 8 burned folds (`tweedie_entry_book.py` / _report.json).
- **Per-TRADE hit rate = 51.5%** (vs the wallet-level 57.5%) — barely above a coinflip. **mean +31.0 vs
  median +12.4 bp** ⇒ strong RIGHT SKEW: the edge is winners being BIGGER than losers, not winning more
  often. Tail p90 +615 / p99 +1475 / max +6673; p10 −529 / min −6920.
- **Equal-$ book ($1k/entry): NOT a lottery — broad-based & robust.** net +$36.3k @ 31bp; dropping the
  single biggest winning trade leaves $35.6k, dropping the TOP TEN leaves $31.5k of $36.3k. The right tail
  is spread across the top ~10–20% of trades, not one moonshot.
- **Notional-sized book (copy actual position size): collapses AND becomes a one-trade lottery.** net only
  +$1.28k @ 4.9bp on $2.64M; **dropping the single biggest winner turns it NEGATIVE (−$89)**; drop-top-10
  = −$6.3k. A few huge-notional entries dominate the dollar book and their outcomes are noise.
**Read:** the copy edge is a positive-EXPECTANCY-via-asymmetry profile (≈coinflip frequency, winners fatter
than losers), broad and robust UNDER EQUAL-$ SIZING but a fragile one-bet lottery UNDER NOTIONAL SIZING —
directly reconfirming the prior betascale/α-curve result (α=1 copy-actual-size fragile 2/8 folds; compress-to-
typical robust) and the "size carries info but full notional is fragile" thread. **Paper-trader implication:
size equal-$ / compressed, NOT notional-proportional.** CAVEAT: RAW includes the illiquid-name tail (the
+600–6700bp prints are likely ADV<$1M names per the liquidity cut — unharvestable at size), so the liquid-
screened equal-$ book is lower than 31bp; the STRUCTURAL findings (51.5% per-trade hit, right skew,
notional-fragility) are the robust takeaways, not the 31bp level. Corrects the earlier over-reach ("no whale
signature") — the right-skew/few-big-winners shape IS present per-trade; it's just harvestable only if you
DON'T size by notional. Artifacts: tweedie_entry_book.py, tweedie_entry_book_report.json.

### 2026-07-17 — MAJORS per-trade shape (K30-native @8h): coin-flip hit rate, median trade ≈ 0, edge is ALL right tail

Majors counterpart of the alt entry-book (user flagged the alt run was alts-only). Majors-native K30
selection (majors-only capped-PnL t-stat), majors flat taker opens ≥$250, 8h markout, RAW, 5,655 entries /
51 wallets, 8 burned folds (`majors_entry_book.py` / _report.json).
- **Per-trade hit rate = 50.0%** (exact coin flip; alts 51.5%). **mean +24.9 vs median +0.4 bp** — the median
  majors trade makes ≈NOTHING; the entire +24.9 mean is the right tail. Even more asymmetric than alts
  (median +12.4). Tail p90 +452 / p99 +1027 / max +1996; p10 −384 / min −1216 — TIGHTER than alts (max 1996
  vs 6673: liquid, no illiquid-print blowups).
- **Equal-$ book:** net +$14.1k @ 24.9bp; robust — drop top-1 winner → $13.9k, drop top-10 → $12.3k of
  $14.1k. Broad-based, not a lottery (like alts equal-$).
- **Notional book:** net +$24.4k @ 23.3bp — UNLIKE alts (where notional collapsed to 4.9bp & went negative on
  drop-top-1), majors notional-sizing HOLDS (23.3bp ≈ equal-$) but is more concentrated: drop top-10 winners
  → $5.4k (−78%), still positive. Majors notionals lack the alt dust/whale spread, so notional sizing is
  tolerable on majors though equal-$ is still more robust.
**Read:** majors (the liquid, deployable book) is a **50% hit-rate, median≈0, right-tail-only** edge — you are
paid entirely on the tail, not the typical trade. COST IMPLICATION is sharp: a 2–4bp majors round-trip eats
the ~0 median trade outright, so the net edge lives purely in the tail clearing costs — reinforces why the
majors book's honest net is thin (BACKTEST §FINAL: +13bp/tr net, SR 1.02) despite +25bp gross. Equal-$ sizing
preferred on both venues; notional tolerable on majors, fatal on alts. Artifacts: majors_entry_book.py,
majors_entry_book_report.json.

### 2026-07-18 — FILTERED TRADER QUALITY: architecture frozen; no result yet

**Question.** Can a filtered daily relative-PnL state improve the rolling majors-native top-30 @8h selector?
**Design.** Daily majors realized PnL is total-fee-netted and normalized to a $100k notional budget, converted
to a within-day normal-score rank, then passed through a pooled causal homoskedastic AR(1)/Kalman filter.
Each monthly cutoff resets state over the same trailing three months as the fair `TSTAT30` control; top-30,
equal-$, 8h, $250-minimum book mechanics stay fixed. Primary = ungated accepted-entry capital-weighted net-bp
delta `KF-REL − TSTAT30`; the frozen 6h distinct-other smart-consensus rule is a same-rule secondary overlay,
not part of the selector claim. Care-about = +5bp improvement.

**Inference/governance.** Historical 202511–202606 folds are burned and can candidate-rank only. A new forward
epoch must be prospectively sealed before its first fill, with a six-month no-read minimum and 12-month cap.
Binding uncertainty is the envelope of multiplicity-preserving wallet-cluster and paired calendar-block CIs;
MDE and +5bp controls must pass under both outer resampling families. Any interval admitting a material lift,
failed power/control, or construction mismatch is unresolved with its point direction surfaced—not a null.

**Architecture audit.** Independent stats, leakage, and correctness passes found and forced repairs to the
initial design: the primary unit was aligned to +5bp/entry; wallet clustering was added; AR(1) gap covariance,
state history, deterministic fallback, forward sealing/outcome maturation, priceability/ordering, distinct-
other consensus, outer MDE resampling, and an exhaustive unresolved verdict were frozen. Re-review reports no
remaining material blocker. **No performance number has been computed.** Artifact:
`FILTERED_TRADER_QUALITY_ARCH.md`; audit scope: `audit/filtered_trader_quality_arch/SCOPE.md`.

### 2026-07-18 — FILTERED TRADER QUALITY RUN: adverse point vs TSTAT30, unresolved/underpowered; consensus does not rescue KF

**Question/method.** The frozen daily relative-PnL AR(1)/Kalman selector was run on burned folds
202511–202606 and compared with the same-input rolling majors `TSTAT30` selector. Every arm has exactly 30
unique wallets/fold. The book uses majors flat opens ≥$250, equal-$2.5k clips, max one concurrent
wallet×coin position, $50k/coin cap, 8h markout, and 5.5bp cost. Cache reuse is bound to source-manifest,
code/config, context, and exact-roster hashes. Historical folds remain candidate-ranking only.

**Primary result.** `KF_REL − TSTAT30` = **−15.35bp/accepted entry**, wallet CI
**[−47.50,+18.14]**, calendar-block CI **[−54.37,+17.04]**, binding CI
**[−54.37,+18.14]**. Cross-unit directions: **3/8 folds** and **2/4 coins** favor KF. Absolute descriptive
books: KF **−2.39bp** (n=559) versus TSTAT30 **+12.96bp** (n=1,625); published majors30 **+15.50bp**
(n=1,654). Normal MDE diagnostic is **51.34bp**, far above the +5bp care effect; the preregistered empirical
outer-resampling MDE was not run. Therefore this has **not earned a null/"filtering does not work" verdict**:
status is **UNRESOLVED / UNDERPOWERED, negative primary direction**, not deployable and not a replacement for
TSTAT30.

**Secondary/consensus.** KF−EMA is a narrow positive lean at **+6.86bp**, binding CI
**[−22.21,+41.07]**, only 3/8 folds and 2/4 coins positive; it is burned, unadjusted, and KF itself remains
negative. KF−TSTAT is positive on SOL (+88.46bp) and ETH (+28.20bp), but those are post-result dependent
slices. The frozen smart-consensus subset does **not** rescue KF: KF-smart **+4.19bp on only 16 entries**;
KF-smart−TSTAT-smart **−15.87bp**, binding CI **[−138.57,+138.42]**. TSTAT-smart is descriptively
+20.06bp versus +12.96bp ungated, but this run contains no direct smart-minus-ungated inference and ex-HYPE
smart is negative, so it adds no new consensus claim. The pre-existing consensus-gated TSTAT/published
strategy remains the forward hypothesis; consensus is not part of the filtered-selector result.

**Construction correction and audits.** The first emitted book was rejected after correctness audit found
that `_ctx_parts` failed to include next-month context. The glob was fixed, all book caches invalidated, and
the report rerun. Seven folds now include the full evaluation month plus next-month days 1–3. June has context
through 2026-06-29 only and applies one recorded common cutoff (2026-06-29 15:59 UTC) before arm filtering.
Final audit reconciled code/roster/cache hashes, all funnel identities and report arithmetic; 10 focused tests
pass. Independent steelman preserves only a forward KF-vs-EMA / SOL-ETH hypothesis; independent prosecution
finds no carryable positive because the broad primary is adverse, the secondary is multiplicity-exposed, and
consensus is extremely sparse. Artifacts: `filtered_quality.py`, `filtered_quality_book.py`,
`data/derived/copy_cohort/filtered_quality/{rosters.json,book_report.json}`; audit scopes under
`audit/filtered_trader_quality_{arch,code}/`.

### 2026-07-18 — DYNAMIC T-QUALITY: corrected architecture frozen; no result yet

**Question.** Can recency weighting improve the successful majors top-30 without replacing its t-stat
estimand by daily percentile ranks? Historical 202511–202606 is explicitly post-hoc/burned diagnostic data.

**Frozen primary.** Build total-fee-net daily majors PnL scaled down to a $100k turnover budget. On one common
EW-rankable pool, compare equal-calendar `TSTAT_COMMON30` with a 21-day-half-life `EW_T30`; both retain PnL
magnitude, wallet-specific dispersion, and effective sample size. Literal unrestricted TSTAT remains a
reconciliation arm. A common HAC-valid static/EW pair checks seven-day serial dependence. Blowup handling
(liquidation or normalized day <=−$10k, reset plus 30-day quarantine) and formation-only copyability/HFT gates
are separate secondaries with same-window static controls, so they cannot be credited to filtering.

**Execution/inference.** Copy only collapsed majors flat opens ≥$250, fixed $2.5k, 8h, 5.5bp cost, wallet-coin
concurrency, $10k source-wallet cap, and $50k coin cap. Entry and exit use the first context midpoint after the
causal decision time; common maturation precedes arm membership. Consensus stays a strict-prior distinct-other
secondary overlay. The sole decision distribution is a crossed global-wallet×paired-seven-day product-weight
bootstrap; it supplies CI, MDE80, +5bp power, and Holm p-values. One-way wallet/time intervals and fold/coin
signs are diagnostics only.

**Architecture audit.** Independent stats, leakage, and correctness audits forced repairs to the initial draft:
common-pool parity, post-shock static/EW parity, a HAC-valid intersection, causal test-month quarantine,
strictly-post-signal pricing, deterministic cap ordering, exact context cutoff, exact-money boundaries, a
fully specified consensus pool, crossed two-way inference, and operational Holm/power rules. Re-review found
no remaining HIGH blocker. **No performance number has been computed.** Artifact:
`DYNAMIC_T_QUALITY_ARCH.md`; audit scope: `audit/dynamic_t_quality_arch/SCOPE.md`.

### 2026-07-18 — DYNAMIC T-QUALITY RUN: 21-day EW is adverse vs static t-stat; missingness-unresolved and underpowered at +5bp

**Question/method.** The frozen corrected design was run on eight walk-forward but historically burned folds,
202511–202606. The primary is the common-pool, ungated `EW_T30 − TSTAT_COMMON30` accepted-entry net-bp
difference. Formation uses total-fee-net daily majors PnL scaled down to a $100k daily turnover budget; both
arms select 30 wallets from the same rankable pool. The copy book uses strictly post-signal midpoint entry,
$2.5k equal clips, one wallet×coin position, $10k/wallet and $50k/coin caps, 8h holding, and 5.5bp cost.
Historical results remain **POST-HOC BURNED DIAGNOSTIC; NOT FORWARD EVIDENCE**.

**Primary controlled result.** EW minus static t-stat is **−22.72bp/entry**, crossed global-wallet×paired-7d
CI **[−51.18,−1.98]** (wallet CI [−36.62,−10.98], time CI [−41.84,−7.53]). The direction is adverse in
**7/8 folds**; the fold deltas are −31.39, +1.64, −14.21, −26.12, −20.63, −3.83, −66.06, and −9.87bp.
Cross-coin directions split: BTC −12.63, HYPE −33.83, ETH +15.57, SOL +16.72bp (**2/4 positive**), so the
pooled adverse result is materially HYPE-dependent. Absolute books are descriptive only: EW −19.59bp
(n=1,563) versus common static t-stat +3.14bp (n=1,621).

**Over-nulling gate / construction.** MDE80 is **31.61bp** and power at the +5bp care effect is only
**7.43%**, so the design is blind to the deployment-sized lift. Crossed fold/wallet combination was run as
registered. The May-30 partial context reserved capacity rather than freeing slots or backfilling: EW has
5/1,568 unpriced accepted-capacity entries overall and 5/180 (2.78%) in May; static has 10/1,631 overall and
10/196 (5.10%) in May. Both breach the frozen 2% per-fold gate. Under the registered ±2,000bp endpoint stress,
the favorable crossed CI reaches **+56.33bp**. Therefore the exhaustive decision flags correctly read
`positive_promotion_eligible=false`, `method_null_eligible=false`, verdict
**`MISSINGNESS_UNRESOLVED`**. This earns the wording “EW materially underperformed directionally in these
burned pooled-major folds,” but **not** “recency filtering has no value” or even a powered method-scoped null.

**Secondaries and consensus.** All four registered secondary improvements fail promotion after Holm and all
fail the +5bp power gate: EW-HAC−HAC −5.40bp, CI [−30.03,+19.22], Holm q=1; shock−EW −1.42bp,
CI [−7.10,+3.88], q=1; copyable-EW−copyable-static −11.95bp, CI [−30.34,+1.52], q=0.434; and
EW-smart−static-smart −37.12bp, CI [−94.42,+0.26], q=0.434. Thus consensus does not rescue EW.
The rolling top-30 **selector itself does not use consensus**. The old highest raw majors book is the
published static top-30 with a separate smart-consensus subset overlay (distinct other top-half-t wallet,
same coin/direction, prior 6h): in this stricter rerun it is descriptively +17.97bp (n=984), CI
[−31.28,+78.35], versus published ungated +5.52bp (n=1,650), CI [−29.55,+47.02]. No direct registered
smart-minus-ungated inference exists here; dropping the best fold leaves smart +0.10bp and ex-HYPE is
−55.44bp. It remains a concentrated HYPE-forward hypothesis, not an established best strategy.

**Required opposing framing and audit.** Independent steelman preserves only the hypothesis that static
t-stat selection plus prior-wallet agreement may identify a real HYPE-heavy consensus effect; it cannot
steelman broad EW improvement. Independent prosecution finds no carryable positive because the sample is
burned, the apparent smart lift lacks a direct controlled contrast, the static books are regime/HYPE
concentrated, and all registered EW comparisons are adverse or unresolved. Final independent correctness
reconciliation is CLEAR: primary ordering and arithmetic, all 72 arm-fold funnel identities, 18 book dollar
totals, crossed CI/MDE/power fields, missingness endpoints/flags, and both Holm families reconcile; 31 focused
tests and Ruff pass. Artifacts: `dynamic_t_quality.py`, `dynamic_t_book.py`,
`data/derived/copy_cohort/dynamic_t_quality/{rosters.json,book_report.json}`; audit scopes under
`audit/dynamic_t_quality_{arch,code}/`.

### 2026-07-18 — LONG HALF-LIFE T-QUALITY: 60-day diagnostic frozen; no result yet

**Question.** Does a **60-calendar-day half-life** beat the identical common-pool static t-stat in the burned
folds? Sixty days was chosen after observing the 21-day result; there is no further half-life sweep, but this
adaptive run cannot identify why 21 days failed or earn a fresh historical positive/null. Formation data,
$100k daily turnover normalization, wallet-specific
uncertainty/effective N, exact top-30, causal equal-$ 8h book, crossed inference, missingness endpoints, +5bp
care effect, and four Holm-controlled secondaries are unchanged. Consensus remains an overlay, not selector
input. The eight months are burned diagnostic data and the 21-day artifacts must not be overwritten. **No
60-day performance number has been computed.** Architecture audits require frozen profile-specific paths,
explicit 60-day propagation through every EW score, profile-bound cache/report identities, and fail-closed
book validation before computation. Artifact: `LONG_HALF_LIFE_ARCH.md`.

### 2026-07-18 — LONG HALF-LIFE T-QUALITY RUN: EW60 lands near static; small positive point, direction unresolved

**Method/governance.** The single frozen `hl60` profile was run on burned folds 202511–202606 after independent
statistics, leakage, and correctness audits. Sixty calendar days is explicit in primary EW, weighted HAC,
shock-reset EW, and copyability EW; the static comparator remains ordinary and uses the identical EW60-rankable
common pool. All panels, rosters, entries, sidecars, and reports are isolated under
`dynamic_t_quality_hl60`; the original 21-day roster/report hashes are unchanged. Because 60 days was chosen
after observing the related KF/21-day results, the artifact is always
**`BURNED_ADAPTIVE_CANDIDATE_DIAGNOSTIC`** and cannot earn historical promotion or a formal method null.

**Primary controlled result.** EW60 is descriptively **+3.89bp/entry** (n=1,570) versus common static t-stat
**+3.14bp** (n=1,621), so `EW60 − static` = **+0.75bp/entry**. Crossed global-wallet×paired-7d CI is
**[−13.07,+15.72]** (wallet [−8.18,+11.37], time [−6.35,+7.49]). Fold deltas are −8.06, −4.63,
+15.59, −0.78, −1.75, 0.00, +7.25, and −2.43bp: **2/8 positive**, one zero. Coin deltas split **2/4**:
BTC +2.80, ETH +2.59, SOL −2.90, HYPE −2.17bp. The point therefore does not have broad cross-unit support.

**What the longer memory changed.** EW60 overlaps static by 25–27/30 wallets per fold (mean 26.4), versus
EW21 overlap with EW60 of 20–26 (mean 23.4). Relative to the identical static comparator, the historical point
moved descriptively from EW21 **−22.72bp** to EW60 **+0.75bp**: longer memory removed the severe adverse
21-day result and behaves like a conservative static rerank. This is useful candidate ranking, but it is not
a calibrated EW60−EW21 mechanism test and does not prove that recency adds edge.

**Over-nulling/construction gate.** MDE80 is **20.42bp**, far above the +5bp care effect; power at +5bp is
only **7.25%**. May again breaches the frozen 2% per-fold missingness gate: EW60 excludes 9/216 = **4.17%**
and static 10/196 = **5.10%**, despite balanced overall rates (0.57% vs 0.61%). All-actual-coin sensitivity
retains +0.75bp with CI [−12.82,+14.97], but endpoint bounds are unresolved: adverse CI
[−92.03,+9.41], favorable [−9.12,+96.06]. Thus neither positive nor +5bp-null sensitivity passes. The
correct conclusion is **inconclusive/underpowered, positive point direction, missingness unresolved**—not
“EW60 works,” “EW60 does not work,” or “filtering has no value.”

**Secondaries.** All four registered comparisons have Holm q=1 and no promotion/null eligibility: EW-HAC−HAC
−0.56bp, CI [−10.98,+6.46]; shock−EW −1.20bp, [−6.75,+3.52]; copyable-EW−copyable-static −1.40bp,
[−8.38,+3.33]; EW-smart−static-smart +3.40bp, [−19.61,+27.16]. Absolute EW60-smart is descriptively
+12.34bp versus static-smart +8.94bp, but there is no smart-versus-ungated estimand here, ex-HYPE smart is
−58.46bp, and dropping the best fold leaves −5.18bp. This run adds no consensus claim.

**Mandatory opposing passes and reconciliation.** The independent steelman retains EW60 as a plausible sealed
forward candidate: it greatly reduces roster churn, is not a single-wallet artifact (drop-best-wallet
+0.51bp), and its CI still admits an economically useful lift. Independent prosecution explains the same
facts as mechanical convergence to static plus ordinary roster noise: only 2/8 folds favor EW60, May drives
the absolute profit, MDE/power are poor, and the experiment is the third related adaptive primary on the same
burned months. Final construction audit is CLEAR: identity/hash lineage, primary arithmetic and arm order,
all 72 arm×fold funnels, May bounds, secondaries/Holm, verdict flags, and output isolation reconcile. Tests:
**36 passed; Ruff clean.** Artifacts: `LONG_HALF_LIFE_ARCH.md`, `dynamic_t_hl60.py`, and
`data/derived/copy_cohort/dynamic_t_quality_hl60/{rosters.json,book_report.json}`.

### 2026-07-18 — ADAPTIVE R/Q FILTER: component-ablation architecture frozen; no result yet

**Question/design.** Test a per-trader robust-magnitude state filter with fixed 60-day gain, then independently
add (1) breadth/concentration-dependent observation R, (2) market-volatility-dependent R, (3) slow Q/4, and
(4) explicit blowup reset/quarantine; also test all components together. Increasing R says a particular
observation is less trustworthy; Q/4 is the clean registered way to make every wallet estimate move more
slowly. A global R×4 arm is omitted because, with covariance rescaled consistently, it is algebraically the
same gain change as Q/4; a deterministic unit test must prove parity.

**Powered repair.** Architecture audit found that another top-30 book would be blind by construction: the
EW60 book's MDE80 was 20.42bp against a +5bp care effect. The load-bearing primary is therefore frozen as an
all-eligible-wallet, coin-by-coin cross-sectionally neutral factor: `KF60_ALL−EW60`, measurement bp/day.
This factor conditions on the realized same-day active wallet set and is explicitly a non-executable
end-of-day selector-quality measurement; it cannot establish tradable returns. Standalone
`R_BREADTH−BASE`, `R_VOL−BASE`, `Q_SLOW−BASE`, and `BLOWUP−BASE`, plus `ALL−BASE`, `BASE−EW60`, and
`ALL−TSTAT_COMMON`, form one seven-test Holm positive family and a separate +5bp-null family. Every contrast
must pass an end-to-end injected +5bp control, MDE80≤5bp, ≥80% injected power, bootstrap validity, and support
gates. Exact top-30/equal-$ 8h books are constructed only if the factor primary is demonstrably powered; if it
is not, the run stops and reports that the available burned data cannot resolve this adaptive filter.

The common formation mask uses exact asset-context coverage and is shared by all eight arms. Volatility R is
the squared current/prior-20 market-RV ratio; breadth R depends on same-day openings and HHI. The slow arm uses
Q/4 with stationary posterior initialization. Blowup/ALL apply a registered state reset, final-30 formation
exclusion, and causal D+1…D+30 evaluation quarantine. Consensus is excluded.

**Architecture audit result.** Independent statistics, leakage, and correctness re-reviews are CLEAR after
repairs to stationary initialization, the exact RV lattice/date contract, coin/day neutrality, mask-before-
centering, the daily-sum crossed estimator, and a genuinely fixed injected-data +5bp recovery control. The
conditional book proceeds only if all power/support/control gates pass, regardless of observed factor
direction. No outcome was read during architecture repair.

The design was created after reading KF-relative, EW21, and EW60 on these folds, so every output is a
`BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC` with formal positive/null eligibility forced false. No outcome has been
computed. Artifact: `ADAPTIVE_RQ_FILTER_ARCH.md`.

### 2026-07-18 — ADAPTIVE R/Q POWERED FACTOR RUN: combined filter is adverse; only blowup handling leans positive

**Method/governance.** The frozen eight-arm adaptive-R/Q design ran on all eight burned folds using an
end-of-day, coin-by-coin active-wallet-neutral measurement factor. This is a selector-quality measurement,
not an executable return. All 242 evaluation days passed the common support lattice (100% in every fold),
with 85,057 global wallets and 35 seven-day blocks. Every contrast passed the fixed +5bp recovery, MDE,
power, invalid-draw, support, and calendar gates; formal promotion/null eligibility remains forced false.

**Powered primary.** `KF60_ALL−EW60` is **−0.970 measurement bp/day**, crossed global-wallet×paired-7d CI
**[−1.499,−0.490]**, MDE80 **0.687bp**, shifted-noise +5bp power **100%**. Only **1/8 folds** and **0/4
coins** favor ALL; BTC −0.149, ETH −0.188, HYPE −0.618, SOL −0.014bp/day. The fixed injected point shifts
exactly +5 and its paired shift CI is [4.521,5.518]. Top-five-wallet absolute contribution share is only
4.38%, so the adverse result is not a few-wallet artifact. This is a powered adverse direction on the burned
measurement estimand; it is not a formal historical method null or deployable return result.

**Independent components.** `R_VOL−BASE` is the clearest harm: **−0.505**, CI [−0.802,−0.241], positive-family
Holm q=0.011, **0/8 folds and 0/4 coins positive**. `Q_SLOW−BASE` is −0.106, [−0.172,−0.019], q=0.065
(1/8, 0/4): making the state roughly twice as slow did not help this measurement. `R_BREADTH−BASE` is
−0.190, [−0.363,−0.006], q=0.105 (1/8, 0/4). `BASE−EW60` is −0.551,
[−0.917,−0.255], q=0.039 (1/8, 0/4), so the robust-magnitude random-walk base itself trails EW60.

The sole positive point is `BLOWUP−BASE`: **+0.371**, CI [+0.033,+0.734], but Holm q=0.105, with 5/8 folds
and 3/4 coins positive; it is a suggestive burned component, not multiplicity-controlled evidence.
Interactions do not rescue it: `ALL−BASE` −0.419, [−0.802,−0.027], q=0.105, and `ALL−TSTAT_COMMON`
−0.707, [−1.192,−0.258], q=0.039 with 0/8 folds positive. All seven secondary +5-null families resolve
below the care effect after Holm, but governance retains only within-run, named-contrast conclusions.

**Registered continuation.** Because the primary was demonstrably resolution-capable, the design requires
the causal top-30/equal-$ 8h book to run independently of point direction. No adaptive book outcome has yet
been computed. Artifact: `data/derived/copy_cohort/adaptive_rq_filter/factor_report.json` and frozen
wallet×coin×day contribution/lattice files under `adaptive_rq_filter/contributions/`.

### 2026-07-18 — ADAPTIVE R/Q CONDITIONAL BOOK: tail leans are unresolved; no adaptive arm beats EW60

**Lineage and execution.** The factor was regenerated after code audit so its atomic report cryptographically
binds all eight per-fold score files. The conditional book then formed deterministic score-descending,
wallet-ascending top-30 rosters and reused the audited causal entry engine: strictly post-signal midpoint,
$2,500 clips, $10k/wallet and $50k/coin caps, 8h, and 5.5bp costs. Online D+1…D+30 shock quarantine applied
only to BLOWUP/ALL; consensus was excluded. Final validation passed 67/67 factor checks, replayed the book
from frozen entry caches with zero differences, reconciled architecture/code/report/roster/score hashes, and
left every promotion/null eligibility flag false. Related tests: 55 passed; Ruff clean.

**Absolute book points.** EW60 is +3.89bp/entry (1,570 entries; crossed CI [−33.36,+46.23]) and common t-stat
is +2.99 (1,607; [−33.72,+46.39]). KF60_BASE is −20.71 (921; [−52.65,+12.55]); Q_SLOW −4.85
(966; [−38.49,+39.16]); R_VOL +3.63 (846; [−27.69,+36.72]); BLOWUP −12.42
(919; [−42.51,+17.27]); R_BREADTH −12.89 (2,410; [−39.34,+17.67]); and ALL −16.65
(2,327; [−36.76,+7.22]). These are descriptive absolute means, not evidence that any book is profitable.

**Primary book.** `ALL−EW60` is −20.54bp/entry, crossed CI [−59.88,+13.37], MDE80 49.32bp, +5bp power
5.01%, 1/8 folds and 2/4 coins positive. Top-five wallets supply 26.44% of absolute contrast contribution.
The overall missing-outcome rates are only 0.17% versus 0.57%, but EW60 reaches 4.17% in one fold, breaching
the registered 2% per-fold gate. Thus the book layer is **inconclusive / underpowered and missingness-
unresolved**, not evidence of zero effect and not a deployable negative. It cannot override the powered
non-executable factor result, which remains adverse at −0.970bp/day [−1.499,−0.490].

**Independent component books.** Every component CI crosses zero, every MDE80 is 45–59bp against the 5bp
care effect, +5bp power is only 3.85%–4.70%, every positive Holm q is at least 0.762, and every comparison
fails the frozen per-fold missingness gate. The strongest positive points are:

- `R_VOL−BASE` +24.35bp, [−4.88,+56.02], MDE45.23, 7/8 folds and 4/4 coins positive, Holm q=.762,
  top-five contrast share 30.79%. This tail lean conflicts with the powered factor: −0.505
  [−0.802,−0.241], Holm q=.011, 0/8 folds and 0/4 coins positive.
- `Q_SLOW−BASE` +15.86bp, [−6.02,+52.63], MDE47.25, 7/8 folds and 3/4 coins positive, Holm q=1.0,
  top-five share 46.79%. Thus reducing Q to one-quarter (about a 120d implied half-life) preserves a
  tail-only hypothesis, but the powered factor is adverse: −0.106 [−0.172,−0.019], q=.065.
- `BLOWUP−BASE` +8.29bp, [−25.13,+40.96], MDE48.22, 4/8 folds and 3/4 coins positive, Holm q=1.0,
  top-five share 31.94%. Its powered factor is the sole positive component: +0.371
  [+0.033,+0.734], 5/8 folds and 3/4 coins, but positive-family Holm q=.105.

**Required opposing framing.** The steelman finds the BLOWUP reset/exclusion/quarantine bundle most credible:
its factor point is powered, diffuse (4.17% top-five share), positive under wallet/time/crossed resampling,
and directionally supported by the book, although it is multiplicity-unestablished and tightly smaller than
the registered +5bp/day care size. It also preserves R_VOL and Q_SLOW as possible nonlinear top-tail effects.
The independent prosecution notes that BASE is an unusually poor book comparator, entry sets are sparse and
unequal, component rosters are unstable, contrast concentration is material, all book Holm tests fail, and
the broad powered factors point against R_VOL/Q_SLOW. Reconciliation: **BLOWUP is a live small burned
positive; R_VOL/Q_SLOW top-30 effects are unresolved residuals, direction unknown; no adaptive arm is
established or deployable.** This study did not involve consensus-opinion trading.

Artifacts: `data/derived/copy_cohort/adaptive_rq_filter/factor_report.json`,
`data/derived/copy_cohort/adaptive_rq_filter/rosters.json`, and
`data/derived/copy_cohort/adaptive_rq_filter/book_report.json`.

### 2026-07-19 — PARITY-LOCKED NESTED T FILTER: the slow filter no longer collapses; improvement is unresolved

**Question and repair.** Rebuild filtering as a genuinely nested modification of the published majors
selector: three-month BTC/ETH/SOL/HYPE daily `(pnl-fee)` scaled down to a $100k daily-turnover budget,
ordinary active-day t-stat eligibility (`nd>=15`, `sd>0`), top 30, fixed-$5k 8h Book-B mechanics, and no
consensus/opinion input. The earlier `KF_REL`/adaptive studies changed the estimand through cross-sectional
rank normalization or robust magnitude scaling and therefore were not slight filters of the successful
statistic. The new Q=0 recursion reproduces ordinary t exactly; the static roster and independently
materialized daily/summary oracle match in every fold before any dynamic roster is accepted.

**Construction result.** The 120-day filter is genuinely slight: `KF120_T30` overlaps static by 28–30/30
wallets in every fold (mean **28.88**) with mean full-pool Spearman **0.9999**. `KF60_T30` overlaps by
25–28 (mean **26.5**, Spearman **0.9982**). In contrast, the combined adaptive-R/breadth/blowup arm is not a
slight filter (mean overlap **13.38**, Spearman **0.6648**) and triggers the registered construction warning
in six folds. Consensus was excluded throughout.

**Legacy parity and stale-cache discovery.** A pre-comparison hard gate found the old majors cache was a
strict subset of current support: 5,494 old finite entries versus 5,569 refreshed, with 75 newly supported
month-end rows (33/17/4/21 in 202601/02/03/05) and no old row removed. The architecture was explicitly
amended post-hoc to entry-support/mark reads, before comparative filtered outcomes, and retains the original
frozen selector SHA. Two independently structured current queries (`p0->p8` and the complete historical
`p0->p1->p4->p8->p24->p48` chain) match exactly. The old-cache subset reproduces historical Book B exactly:
**1,643 accepted, 3,851 wallet×coin skips, zero coin-cap skips, +13.0143bp net/entry**. The separately
labeled refreshed historical-rule book has 1,652 accepted and **+15.5608bp**. This nine-entry shift is a
warning that a few tail rows can materially move the headline.

**Registered primary.** Under the corrected common-maturity, capacity-before-outcome comparison book,
static is **+12.359bp/entry** (n=1,612 supported) and KF120 is **+13.380bp** (n=1,594), so
`KF120-STATIC` = **+1.021bp/entry**. Crossed global-wallet×paired-7d CI is
**[-9.222,+12.919]**, wallet CI [-4.942,+9.308], time CI [-5.115,+7.093], two-sided p=.816.
The direction is positive in four folds, negative in one, and exactly tied in three; coin deltas are
BTC +0.971, ETH -0.350, HYPE +0.492, SOL +7.530bp (**3/4 positive**). This establishes that a correctly
nested slow filter does **not** reproduce the earlier catastrophic underperformance, but it does not
establish improvement.

**Over-null and construction gates.** MDE80 is **15.577bp** against the +5bp care effect; power at +5 is
only **9.43%**. The null-centered injected +5 point is exact but its crossed CI is
**[-5.401,+16.953]**, so the positive control fails. Missingness is balanced and small overall
(KF120 11/1,605 = 0.685%; static 10/1,622 = 0.617%) but localized in 202605 at 4.78% and 5.08%, breaching
the 2% per-fold gate. The adverse endpoint-bound CI is [-98.639,+7.701] and the favorable CI
[-6.523,+103.710]. Five wallets supply **92.65%** of absolute contrast contribution. Raw outcomes also do
not corroborate the small book lean: equal-entry gross is 26.11 versus 27.81bp and the registered
p95-winsorized wallet-fold-equal point is 14.06 versus 24.95bp. Therefore the primary is an
**inconclusive, noise-plausible residual; direction unknown**, not a live positive and not a null. The
available eight burned folds cannot resolve a +5bp effect for a selector that swaps only about one wallet
per fold; a powered answer requires genuinely new folds, not another post-hoc historical estimator search.

**Secondaries.** The strongest steelman is `KF120-KF60`: **+8.484bp**, CI [-2.856,+28.151], but MDE
26.031bp, +5 power 5.35%, only HYPE positive among four coins, top-five contribution 73.1%, missingness gate
failed, and positive Holm q=1. This is only a suggestive hypothesis that slower filtering avoids damage
from faster filtering. `R_BREADTH-KF60` is +6.011bp, [-13.453,+28.119], but only 2/8 folds positive and
Holm q=1. R_VOL is -10.539bp, KF60-static -7.463bp, ALL-KF120 -4.040bp, bot500-static -0.362bp, and
BLOWUP-KF60 -0.047bp; none earns a positive or a +5bp method-null after power, missingness, and Holm gates.

**Mandatory opposing passes and audits.** Independent steelman retains only the unresolved slow-versus-fast
filter hypothesis and notes the near-zero wallet-only/time-only lower bounds for KF120-KF60. Independent
prosecution explains all positive points as a few marginal wallet substitutions in heavy-tailed HYPE/May
outcomes, emphasizes nine correlated contrasts layered onto earlier burned searches, and finds no positive
survives the registered IUT/Holm/missingness/control stack. It also rejects a blanket null because even the
tightest BLOWUP contrast has MDE 5.46bp, a failed +5 control, failed missingness bound, and Holm q=1. Final
calibration: **no established filter improvement; no earned method-wide null; standard/static and KF120 are
indistinguishable at the available resolution.** Architecture and final code audits are CLEAR across
correctness, statistics, and leakage; focused tests **16 passed**, Ruff clean.

Artifacts: `NESTED_T_FILTER_ARCH.md`, `nested_t_filter.py`, `nested_t_book.py`,
`data/derived/copy_cohort/nested_t_filter/{rosters.json,book_report.json}`, and audit scopes under
`audit/nested_t_filter_{arch,code}/`.

### 2026-07-19 — EFRON BOT500: exact pre-fit HFT screen does not fix November; direction unresolved

**Question and construction.** Test the user's basic majors Efron top-30 with one isolated change: before
each fold's independent empirical-Bayes fit, exclude every otherwise eligible wallet whose all-coin
formation activity exceeds 500 fills per active day, then refill to 30. The unscreened Efron roster, the
full eligible-wallet fills/day mask, and the saved direct-t BOT500 roster all reproduced independently in
every fold (oracle maximum difference zero). Across the eight folds, 11,014 of 370,060 eligible wallet-folds
were excluded (2.3%–3.5% per fold); screened/unscreened top-30 overlap was 18, 19, 21, 22, 23, 26, 27, and
30. Both arms used one globally chronological $5k, 8h, 5.5bp capacity stream. Consensus was excluded.

**Absolute and primary results.** The unscreened Efron book is **+16.238bp/entry** (1,745 supported entries,
$14,167.71) and the screened book is **+12.339bp** (1,819, $11,221.88). The registered
`E_BOT500−E30` point is therefore **−3.900bp/entry**, crossed global-wallet×paired-7d CI
**[−15.709,+7.006]**, two-sided p=.435. Only **2/8 folds** (December and May) and **2/4 coins** (ETH and
SOL) favor the screen; June is exactly tied. Five wallets supply **50.8%** of absolute contrast
contribution. The point estimate leans adverse, but the interval still admits a benefit larger than the
+5bp care effect.

**The November mechanism is not addressed.** Wallet `0xa1b6…4f04`, responsible for nearly all of the
previously diagnosed November Efron loss, had only **116.75** all-coin formation fills per active day. It
therefore remains selected—rank 2 in E30 and rank 1 after the screened refit. The November screen contrast
is **−23.079bp**. Thus this cutoff cannot be justified as removing that dominant losing wallet; it changes
other roster members and the Efron population instead.

**Over-null and missingness gates.** MDE80 is **14.274bp** against the +5bp care effect and analytical power
at +5 is only **15.36%**. The centered injected point moves exactly +5, but its crossed CI
**[−6.753,+15.881]** crosses zero. Overall missingness is small (0.852% E30, 0.926% BOT500; 0.074pp
imbalance), but May breaches the registered 2% fold gate at 3.989% and 5.263%. The ±2,000bp constructions
span an adverse **−39.439bp** to favorable **+31.689bp** point, so the frozen verdict is
**MISSINGNESS_UNRESOLVED**. This does not earn a helpful, harmful, or method-null conclusion.

**Required opposing passes.** The independent steelman notes higher raw gross mean/median/hit rate for the
screen, more accepted capacity from fewer raw signals, lower fitted empirical-null sigma in every fold,
and positive ETH/SOL and December/May substructure. But the registered wallet-fold-equal raw statistic
reverses (13.11bp screened versus 20.87bp unscreened), showing the raw lean is frequency-weighted rather
than broad wallet-level corroboration. The independent prosecution emphasizes the adverse registered point,
2/7 positive nonzero fold signs, concentration, failed +5 recovery, repeated burned folds, and failure to
remove the November wallet. Reconciliation: **the BOT500 screen has some hypothesis-generating raw-fill and
capacity-utilization substructure, but the registered effect's direction is unresolved; it is not a live
positive, not an earned null, and not deployable.**

Architecture plus pre/post correctness, statistics, and leakage audits are CLEAR; focused and inherited
tests **20 passed**, Ruff clean. Artifacts: `EFRON_BOT500_ARCH.md`, `efron_bot500.py`,
`data/derived/copy_cohort/efron_bot500/{rosters.json,book_report.json}`, and audit scopes under
`audit/efron_bot500_{arch,code}/`.

### 2026-07-19 — EFRON BOT500 VISUAL ATLAS: weighting, tails, dependence, and concentration are visible

**Question and artifact.** Build a burned, post-hoc diagnostic atlas of the standard Efron majors top-30
and the isolated pre-fit BOT500 screen, using only byte-bound frozen inputs and without refitting or changing
the registered book. The seven-page atlas covers the inference gate, estimator ladder, chronological markout
paths, return tails, the complete formation cohort, empirical-null assumptions, same-fold arm overlap,
capacity/missingness, and wallet concentration. Every page is watermarked underpowered,
missingness-unresolved, and non-deployable; consensus/opinion trading is excluded. The immutable current
generation is `18cb1290dd9e69db981cdb7617d92553ba3b830292e03cff2ebb7debd1552084`.

**What the pictures add.** The standard Efron absolute point is positive across three differently weighted
descriptive layers: +20.76bp raw equal-entry gross, +20.87bp p95-winsorized wallet-fold-equal gross, and
+16.24bp capacity-supported net across 1,745 entries. It is positive in 5/8 folds but only 2/4 coins; HYPE
longs dominate accepted rows, so regime/beta exposure remains a live alternative. The BOT500 arm's apparent
raw equal-entry advantage (+28.6 versus +20.8bp) reverses under wallet-fold weighting (+13.1 versus +20.9)
and the executable capacity book (+12.3 versus +16.2), making frequency/tail/composition weighting the most
visible explanation for that raw lean. These are descriptive diagnostics, not a new absolute-E30 test.

The outcome distributions are strongly non-Gaussian: normal QQ curves bend in both tails, survival extends
past 1,000bp, and a small fraction of entries supplies a large fraction of absolute return magnitude. The
formation cross-section is also not `N(0,1)`: fitted empirical-null width is above one in every fold and the
observed positive tail greatly exceeds the fitted null at large z. Within-wallet lag-1 dependence is positive
in all folds (roughly 0.06–0.14), so neither the raw daily PnL nor selected-wallet observations are iid. The
atlas bins mean/volatility only after transforming both coordinates (`log10 SD`, signed
`log10(1+|mean|)`), avoiding the misleading geometry found and rejected during visual audit.

The 500-fills/day rule removes only 2.3%–3.5% of eligible wallet-folds, but the same-fold arm overlap starts
at 18/30 and rises to 30/30 by June because the population refit moves the early selection boundary. It does
not remove the registered November dominant wallet (116.75 fills/day; E30 rank 2, BOT rank 1). Capacity
acceptance is only about 11%–46%; missingness is localized in May and principally HYPE. Five wallets supply
50.8% of absolute BOT500-minus-E30 contrast contribution, and leave-k deletion crosses zero repeatedly,
showing that the adverse point is not diffuse.

**Opposing framing.** The independent steelman calls standard Efron a credible **suggestive** OOS positive:
its sign survives raw, wallet-fold, and capacity views, has a positive median/hit rate, and recovers after the
early drawdown. It is not established or deployable because this study's inferential target is BOT500−E30,
not E30 versus a matched null; there is no absolute-E30 CI/MDE here, coin breadth is weak, and HYPE exposure
is large. The independent prosecution finds no positive BOT500 case: the registered point and robust raw
comparison favor E30, fold breadth is 2/8, the dominant wallet survives, concentration is high, May
missingness can reverse direction, and +5bp power is only 15.4%. Reconciliation is unchanged:
**standard Efron remains suggestive but unestablished; BOT500 remains missingness-unresolved and
underpowered, neither positive nor an earned method null.**

Artifacts: `EFRON_BOT500_VISUALS_SPEC.md`, `efron_bot500_visuals.py`,
`data/derived/copy_cohort/efron_bot500/visuals/latest.json`, and generation
`data/derived/copy_cohort/efron_bot500/visuals/generation-18cb1290dd9e69db981cdb7617d92553ba3b830292e03cff2ebb7debd1552084/`
(`index.html`, `diagnostic_atlas.pdf`, seven PNGs, and `visual_manifest.json`). Final focused/inherited tests:
**26 passed**; Ruff clean. Final immutable-output and visual-statistical-framing audits are **CLEAR**. Early
rendered generations with distorted hexbin geometry were rejected and are not current.

### 2026-07-19 — WALLET×COIN T30: positive absolute book, unresolved advantage over wallet T30

**Question and construction.** Reopen the burned 2025-11 through 2026-06 majors window for one forensic
test: replace the pooled-wallet formation statistic with a direct wallet×coin daily t-stat. For every fold,
form the prior three full months of wallet×coin days, cap each pair-day PnL at $100k of pair-day notional,
require at least 15 days and positive finite SD, rank the full pair pool globally, and select the top 30
wallet×coin seats. Copy only each selected wallet's selected coin. Everything downstream matches the
registered majors book: BTC/ETH/SOL/HYPE, flat taker opens >=$250, fixed $5k, at most one concurrent
wallet×coin position, $50k per-coin capacity, 8h exit, 5.5bp cost, globally continuous capacity, backward
ASOF context, and common cutoffs. Consensus/opinion trading and BOT500 filtering are excluded.

**Absolute result.** `PAIR_T30` produced **+13.975 net bp/trade mean**, **-4.587bp median**, **49.35%** net
hit rate, **4/8 positive/evaluable months**, 1,153 supported trades, and **+$8,056.40** at $5k sizing.
Per-coin net means were BTC -14.811bp, ETH +2.953bp, HYPE +21.879bp, and SOL -63.026bp. Monthly means were
-62.949, -55.882, +135.869, -11.152, +49.700, +8.404, +90.775, and -10.353bp. The raw pre-capacity gross
layer was +31.500bp mean, +12.780bp median, and 51.86% hit rate across 4,177 entries; its registered
wallet-fold-equal point was +19.343bp. These are descriptive, not an absolute-vs-null inference.

**Primary relative result.** The exact globally continuous `WALLET_T30` control reproduced at +12.529 net
bp/trade, -7.125bp median, 49.07% hit rate, 5/8 positive months, 1,610 trades, and +$10,085.97. Therefore
`PAIR_T30-WALLET_T30` is **+1.446bp/trade**, binding crossed wallet/pair 95% CI
**[-19.837,+20.675]**, two-sided p=.866, MDE80 **27.290bp**, and power at +5bp **6.32%**. Only 3/8 fold
deltas and 2/4 coin deltas favor pairs. The CI admits economically meaningful benefit and harm, while the
instrument is blind to the +5bp care effect, so this does **not** earn a method null.

**Missingness, sparsity, and sensitivities.** Overall missingness is low and balanced (0.689% pair versus
0.617% wallet), but May is 4.908% versus 5.076%, breaching the frozen 2% fold gate; adverse/favorable
±2,000bp constructions move the delta from -24.700bp to +27.553bp. The verdict is therefore
`MISSINGNESS_UNRESOLVED`. Of 240 pair fold-seats, **172 (71.7%)** have no forward candidate or supported
trade; only 6–12 of the nominal top 30 seats trade in each fold, and 86.6% of accepted PAIR_T30 entries are
HYPE. Top-five absolute contrast contribution is 32.8% by wallet and 30.5% by pair, below the registered
concentration threshold but not diffuse. Secondary pair constructions lean the same way but do not
replicate independently: wallet-day-cap T30 is +2.571bp versus wallet T30, and pair E30 is +5.626bp versus
wallet E30; both are underpowered, fail missingness gates, and have Holm directional q=1.

**Mandatory opposing passes and verdict.** The independent steelman emphasizes the positive absolute book,
the +1.446bp registered point, slightly better median/hit rate than wallet T30, positive robust raw point,
low balanced overall missingness, non-dominant concentration, and a plausible ETH coin-specific-skill
mechanism. The independent prosecution emphasizes selecting 30 extremes from roughly 52k–60k eligible pairs
per fold, 71.7% zero-forward seats, HYPE/regime dependence, weak fold/coin breadth, negative net median,
lower total dollars than wallet T30, and missingness bounds that reverse direction. Reconciliation:
**PAIR_T30 is a positive descriptive absolute backtest, but its advantage over pooled-wallet T30 is
inconclusive/underpowered and missingness-unresolved; direction unknown. It is neither dead, an earned null,
a live positive, nor deployable.** This burned reopening cannot promote a favorable result.

Architecture plus final correctness, statistics, leakage, data-integrity, and reproducibility audits are
**CLEAR**; focused tests **9 passed**, Ruff clean, arithmetic/all-actual reconciliation passed. Artifacts:
`WALLET_COIN_T30_ARCH.md`, `wallet_coin_t30.py`,
`data/derived/copy_cohort/wallet_coin_t30/{rosters.json,book_report.json,entries/,panels/}`, and
`audit/wallet_coin_t30_arch/SCOPE.md`.

### 2026-07-19 — POOLED-WALLET EFRON TOP-30 NOTEBOOK: audited mechanics and descriptive book EDA

**Artifact and method.** Added an executed notebook and static HTML report for the frozen unscreened
`WALLET_E30` baseline. The notebook does not refit the selector or ingest data: it authenticates the
governance, roster/code/dependency hashes, all eight entry/meta records, then reconstructs the globally
chronological capacity book using the audited engine. It fail-closes on exact supported ordered/multiset
hashes, funnels, missing count, and headline arithmetic. Consensus and the >500-fills/day screen are
excluded. PnL is credited at the 8-hour exit on the full 242-day UTC calendar including zero-PnL days.

**Descriptive mechanics.** The notebook exactly reproduces 1,745 supported trades, +16.238 net bp/trade,
-0.275bp median, and +$14,167.71. Exit-day daily metrics are annualized Sharpe **1.321**, Sortino **2.077**,
maximum drawdown **$8,910.99** or **16.2%** of the realized $55,000 maximum gross exposure, profit factor
1.155, 234/242 active days, and 5 positive exit-calendar months. Average gross exposure is $12,121.21.
EDA covers daily equity/drawdown, rolling Sharpe, entry-fold and coin breadth, tails, direction, wallet
contribution, roster turnover, and the capacity funnel. HYPE contributes +$17,235 while ETH and SOL are
negative; the net median is slightly negative; top-five wallets are 45.6% of absolute wallet contribution.

**Missingness and framing.** Fifteen of 1,760 capacity-accepted outcomes are unavailable. Applying the
registered ±2,000 net-bp stress to all accepted entries gives **-0.946 to +33.145bp/trade** and **-$832.29
to +$29,167.71**, so the absolute sign can flip. The notebook therefore says: **positive descriptive mean,
but burned and missingness-unresolved; direction not established or deployable.** Independent final
correctness, statistics/framing, and leakage/provenance audits are **CLEAR**; all 11 cells executed without
error. Artifacts: `POOLED_WALLET_EFRON_TOP30_NOTEBOOK_SPEC.md` and
`notebooks/pooled_wallet_efron_top30_backtest.{ipynb,html}`.

### 2026-07-19 — SAME-COIN DIRECTION POLICY: favorable execution residual, unresolved

**Question and construction.** Diagnose what happens when the frozen pooled-wallet `WALLET_E30` book has
simultaneous long and short 8-hour sleeves in the same coin. The baseline keeps those as separate virtual
sleeves: both consume gross capacity and both pay 5.5bp. The comparison arm independently replays the same
complete 7,919-row pre-capacity stream from empty state, but suppresses a new signal whenever an opposite
direction is already open in that coin; it never early-closes, crosses, or flips. Exits precede entries at
timestamp ties, then the wallet×coin, opposite-direction, and coin-cap gates run in that order. Selection,
rosters, costs, $5k sizing, 8-hour exits, majors, and all other mechanics are unchanged. Consensus and the
BOT500 screen remain excluded. Exact parent capacity/book/headline parity and NaN/noise outcome-blind shadow
replays pass.

**Book mechanics.** The virtual baseline is mixed long/short in at least one coin for **9.690%** of the
fixed wall-clock span and **8.332%** of active coin-time. Its average gross exposure is **$12,121**, versus
**$11,059** absolute-net, demonstrating real internal offset. The one-side policy makes both mixing measures
exactly zero. It registers 172 opposite-direction skips, but later freed capacity means accepted entries
fall by only 85 (1,760→1,675; supported 1,745→1,661). Average gross falls **$585**, while average
absolute-net rises **$477**, because shorts fall disproportionately (220→162 supported) relative to longs
(1,525→1,499). This is suppression of hedges and a more directional book, not free execution netting.

**Descriptive result and uncertainty.** `ONE_SIDE_PER_COIN−VIRTUAL_SLEEVES` is **+$2,296.35** total net
dollars, **+3.586bp/trade**, Sharpe **1.321→1.517**, Sortino **2.077→2.414**, profit factor
**1.155→1.191**, and median trade **−0.275→+1.696bp**; both arms retain 5 positive exit months and the
same **$8,910.99** maximum drawdown. The registered paired seven-day block point interval is
**[−$166.24,+$4,966.90]**, two-sided p=.081. Observed positive-tail MDE80 is **$3,929.45** with only
**39.92%** power at +$2,500; the negative-tail MDE is $3,461.00 with 56.35% power. Therefore the test does
not resolve the $2,500 care effect, and the positive point must not be buried as null.

**Missingness and cross-unit combination.** Overall missingness passes (0.836% policy, 0.852% baseline),
as does the 0.0165pp arm imbalance, but May is **4.03% / 3.99%**, failing the frozen 2% per-fold gate.
Fourteen missing rows are shared and coupled to cancel; only one baseline-exclusive row creates the
adverse/favorable point range **+$1,296 to +$3,296**. The conservative missingness CI is
**[−$2,585,+$6,314]**; binding MDE80 is $4,899 positive/$5,257 negative, power is 31.16%/24.09%, and both
binding injection controls fail. Fold deltas are 5 positive, 2 negative, 1 tie (exact sign p=.453); coin
deltas are 2 positive and 2 negative (p=1.0). HYPE contributes **+$2,565**, 112% of the total delta, while
BTC+ETH+SOL sum negative.

**Mandatory opposing passes and verdict.** The independent steelman emphasizes a mechanism-aligned
favorable residual: higher dollars despite fewer opportunities, better mean/median/Sharpe, a still-positive
adverse missing point, 5/7 nonzero folds positive, and improvements concentrated in folds with material
conflict suppression. The independent prosecution emphasizes whole-arc post-hoc multiplicity, no fresh
holdout, failed MDE/power/missingness gates, HYPE domination, weak coin breadth, unchanged drawdown/month
count, and the benign explanation that removing shorts increased long/regime exposure. Reconciliation:
**underpowered positive execution residual; direction unresolved. It is not established, not a null, never
suggestive/candidate/deployable, and does not replace the virtual-sleeve baseline.** The machine claim is
`UNRESOLVED`; positive-promotion and method-null eligibility remain false.

Architecture and pre/post correctness, statistics, and leakage/provenance audits are **CLEAR**; Ruff is
clean and focused/inherited tests **20 passed**. The existing notebook and HTML were extended and executed
without errors. Artifacts: `SAME_COIN_DIRECTION_POLICY_ARCH.md`, `same_coin_direction_policy.py`,
`tests/test_same_coin_direction_policy.py`,
`data/derived/copy_cohort/same_coin_direction_policy/report.json`, and
`notebooks/pooled_wallet_efron_top30_backtest.{ipynb,html}`.

### 2026-07-19 — CR<=50 RELATIVE-NOTIONAL FILTER: exact fixed-book identity; selector unactivated

**Question and construction.** Test one user-specified entry veto on the frozen unscreened pooled-wallet
Efron top-30 book: refuse a candidate whose copied notional exceeds 50 times that wallet's exact continuous
median majors opening notional over the same strict-prior three formation months. Formation notionals are
read as `DECIMAL(38,10)` and reproduced by independent Python exact-Decimal and DuckDB widened-Decimal
oracles; membership uses exact cross multiplication and equality passes. The filter runs before capacity,
while candidates without a positive prior scale pass through. There was no cutoff sweep. Consensus,
BOT500, and the same-coin suppression policy are excluded.

**Activation and realized result.** Prior scales exist for **7,774/7,919 candidates (98.17%)**; 145 rows
pass through. Median CR is **1.001**, p99 **6.696**, maximum kept CR **24.307**. Only **one** candidate
(0.0126%) exceeds 50: a November HYPE long with CR **96.808**. That row was already ineligible in the
baseline because the same wallet had an open HYPE sleeve from roughly 64 minutes earlier. Accordingly,
both arms accept the exact same **1,760** source identities and support the exact same **1,745** outcomes;
accepted, supported, daily-PnL, and exposure hashes are identical. CR50 therefore reproduces the baseline
exactly: **+$14,167.71**, **+16.238bp/trade mean**, **-0.275bp median**, Sharpe **1.321**, Sortino
**2.077**, and 5/8 positive exit months. The registered contrast is **$0 and 0bp/trade**.

**Null-gate accounting.** Observed, adverse-missingness, and favorable-missingness paired points and 95%
CIs are all exactly **$0 [$0,$0]**; MDE80 is $0 and the +/-$2,500 injections are recovered exactly because
the arm vectors are identical. All eight fold contrasts and all four coin contrasts are exact ties. All 15
missing accepted identities are common to both arms and cancel, leaving coupled dollar and mean-bp contrast
bounds exactly zero. Construction, exact parent parity, independent source oracles, outcome-blind shadows,
cache seals, and publication-boundary lineage checks pass. The frozen machine claim nevertheless remains
`UNRESOLVED` because May's 3.99% absolute missing rate breaches the preregistered 2% per-fold gate and burned
governance forces `method_null_eligible=false`. That generic absolute-arm gate cannot create contrast
uncertainty when both arms and all missing identities are identical, but the preregistered label is not
overridden post hoc.

**Mandatory opposing passes and conclusion.** The steelman correctly identifies zero treatment exposure:
the threshold is an extreme guardrail, the sole qualifying event was capacity-masked, pooled three-month
medians may dilute coin/regime-specific abnormal size, and 145 unknown-scale rows passed through. Thus the
test has no power to estimate returns conditional on rejecting an otherwise accepted CR>50 trade; the
degenerate MDE is proof of path identity, not power for that unobserved treatment. The prosecution finds no
positive to carry: every executable identity and metric is equal, every cross-unit contrast ties, the
threshold lies in an empty empirical gap, and the folds/rule are burned within a heavily inspected arc.
Reconciliation: **the exact CR>50 refusal rule was non-binding and had exactly no realized effect on this
frozen executable book. Relative-size filtering when it actually binds remains unresolved; this is not
evidence that the broader idea is dead, and it is not positive, suggestive, candidate, or deployable.**

Architecture and pre-outcome correctness, statistics, and leakage audits are **CLEAR** after closing a
publication-lineage TOCTOU check, production CR-value shadow assertion, and inherited arm-label wiring bug;
the independent post-run positive-steelman, positive-prosecution, and 40-check provenance audits are also
**CLEAR**. Targeted and inherited tests **30 passed**, Ruff clean. Artifacts: `NOTIONAL_CR50_FILTER_ARCH.md`,
`notional_cr50_filter.py`, `tests/test_notional_cr50_filter.py`,
`data/derived/copy_cohort/notional_cr50_filter/{formation_scales.json,formation_scales.meta.json,report.json}`,
and the updated executed `notebooks/pooled_wallet_efron_top30_backtest.{ipynb,html}`.

### 2026-07-21 — TAPE CAPDAY + FILTER GRID: external "filters rescue capday top-30" claim does NOT reproduce on majors; selector reconciles tape↔lake exactly

**Question.** The user's other repo (incerto = serving layer; claim upstream of it) reports capday top-30
(trailing 3-mo $100k-capped daily net PnL / active day, incerto `signals_ddl.py` definition frozen verbatim)
+ next-month copy + fixed markout exit is "very successful **after filters** that remove draggers." Recreated
on the LOCAL node_fills majors tape (first majors study computing selection AND entries from the tape itself,
not the Reservoir lake). Arch `TAPE_CAPDAY_FILTER_ARCH.md` v1.1 (4-agent audit folded: common-winsor
contrasts, paired t7+wallet-cluster deltas, FRTS rank-then-screen arm, LIQ_ORIGIN own-side predicate,
oid-grouped entries, ts-based boundaries, `audit/tape_capday_filter_arch/`). 8 burned folds 202511–202606;
8 pre-declared arms (F0 baseline; F1 bot<500 fills/day, F2 taker≥0.10, F3 dust med≥$250, F4 own-liq=0,
F5 one-day≤50%, FALL=∧, FRTS) × {1,4,8,24}h; primary FALL@8h; care-about +5bp. `tape_capday_filter.py`,
report `tape_capday_filter_report.json` (code_commit stamped; 8GB-RAM/1GB-disk-safe semi-join build).

**Result — the claim does not reproduce on majors.** PRIMARY FALL@8h robust wallet-fold-equal **−0.1bp
CI[−33.7,+34.4]**; filter effect FALL−F0@8h **+5.6 [−41.1,+52.4]** (t=0.29). Equal-$1k books NET-NEGATIVE
and the filtered book is WORSE: F0@8h −10.4bp (SR −0.80), FALL@8h **−17.7bp (SR −1.42)**. Grid at the null
rate: 1/32 cells CI-clear (F2_MAKER@24h **−87.9 [−172.5,−5.2]** — the one clear cell says the maker screen
HURTS) vs 1.6 expected; BH min q 0.167. Mechanism incoherent for a dragger story on majors: bot- and
dust-screened wallets had POSITIVE forward mk8 (+63.3/+45.5bp — the screens removed helpers), corroborating
2026-07-17 attribution ("Book M is NOT a dragger story"). Prosecutor pass (separate agent) killed every
positive lean: the 4h "cluster" (F0/F4/F5/FRTS +11–14) is ONE fold's +146.43bp identical-to-float-precision
across nested arms (F0@4h ex-202603 ≈ −4.7); FRTS≈F0 (fold deltas exactly 0 in 6/7); FALL−F0@24h +56.9
[−11.5,+125.4] is baseline-crash (F0@24h −57.3; FALL@24h itself −23.2) + one thin fold (202602 +192, overlap
6/30), wallet-boot CI [−34.1,+101.2], MDE 94 ≫ point — logged as direction-unknown curiosity only.

**Symmetric honesty (steelman pass, separate agent) — this is NOT a powered negative and does NOT demote the
prior lineage.** MDE 39–98bp vs +5 care-about at every cell (blind by construction, declared a priori — no
NULL vocabulary permitted); every CI contains the prior +16.7 dollar-book and +29.0 majors-native points; the
negative equal-$ books REPLICATE the ledger's own "equalizing destroys the edge" measurement (equal-per-entry
+16.7→−3.1 precedent), and wallet-equal is the estimand whose sign the 2026-07-14 correction ruled noise.
Verdict scope: **method-scoped adverse-direction descriptive on the deployable filtered book; filter overlay
UNRESOLVED; prior capday-lineage underpowered positive UNCHANGED.**

**Genuine positive contribution — selector reconciliation.** Tape-built capday top-30 = the frozen-133 lake
cohort **30/30 in every fold** (F0∩frozen133=30 ×8): two independent data paths (node_fills tape vs Reservoir
lake wcd) produce the same wallets under the incerto-frozen metric — end-to-end selector validity, and the
incerto-certified definition is confirmed implementable from raw fills alone. Funnels: pool 41–50k eligible
wallets/fold; followable surface remains the binding constraint (202 F0 entries / 8 months; 19 robust wf
units; fold 202605 zero evaluable F0 entries; 202606 right-censored, ctx ends 2026-06-29).

**Read-through for the external claim:** whatever the other repo measured, on the majors venue under
this repo's leakage-clean accounting it is not visible: primary flat, deployable book adverse, no BH
survivor. Escapes that remain honest: the claim may live on ALTS (invisible on this tape — the ledger's
alt line already found the alt copy edge real-but-unharvestable at taker costs), on a gross/in-sample
accounting, or at a tuned horizon. Adjudicator stays the forward paper trader; no new burned-fold looks.
Artifacts: `TAPE_CAPDAY_FILTER_ARCH.md`, `tape_capday_filter.py`, `tape_capday_filter_report.json`,
`audit/tape_capday_filter_arch/FINDINGS.md`; steelman + prosecutor recorded this session.

### 2026-07-21 addendum — DRAGGER ANATOMY: the dragger "archetype" is the SHORT SIDE, not a wallet cluster; long-only overlay registered

**Question.** Locate the archetype dragging the tape-capday F0 top-30 down (the pre-declared screens removed
helpers, so the draggers sit INSIDE the cohort). `tape_capday_draggers.py` / `tape_capday_draggers_report.json`
— POST-HOC DESCRIPTIVE on burned folds; median cohort wallet has 2 evaluable entries, so wallet-identity
profiles are noise-dominated and were treated only as pointers.

**Wallet-level pass (weak):** drag is BROAD, not concentrated — 26/43 pooled wallets negative, worst wallet
only 17.4% of total drag, 5 wallets for half (contrast the alt book's single-bot dragger story). No formation
feature separates draggers from helpers (nd/metric/fills-day/taker/conc all overlap); the only flip-cuts were
outcome-circular (hit<45%) or entry-composition proxies (short-share, HYPE-share) — which pointed to the real
axis:

**Entry-level decomposition (the finding):** the F0 book's 8h drag is DIRECTIONAL. Raw: LONG +31.6bp (5/6
folds>0, 30 wallets) vs SHORT −48.0bp (1/8, 25 wallets); within dual-side wallets short<long 8/12; worst cell
HYPE-short −159.8 (n=19). **Beta exonerated and the effect sharpened:** sample drift is NEGATIVE for
BTC/ETH/SOL (−7.5/−10.6/−10.8bp per 8h; HYPE +7.6) so shorts were beta-HELPED; field-adjusted (mk8 −
dir·coin×fold drift): LONG **+48.7 [−9.5,+86.0]** (5/6 folds), SHORT **−55.6 [−107.4,−28.4] — wallet-cluster
CI excludes 0**, 1/8 folds. The cohort's longs beat the field; their shorts are anti-predictive. Long-only
equal-$1k book: net +29.0bp/trade (n=102, ~13 entries/mo, +$296/8mo at $1k clips).

**Honesty:** post-hoc cut discovered on burned folds (direction was 1 axis of a small pre-listed set, but the
CI-excl-0 on shorts is still a discovery, not a registered result); tiny n; 202605 missing. NOT a burned-fold
edge claim. **REGISTERED FORWARD RULE (entry-level, ex-ante, no new selector): LONG-ONLY overlay — copy only
`Open Long` flat opens on the capday/majors book; a-priori prediction: overlay ≥ baseline by ~30–50bp/trade
gross.** Short-FADE (taking the other side) is noted as hypothesis-grade only — one more sign-flip away from
the data than exclusion, and not registered. Consistent priors in the ledger: the majors book is a
winners'-book (2026-07-17 attribution), and the archetype lesson generalizes as "condition on the SIDE, not
the seat." Artifacts: `tape_capday_draggers.py`, `tape_capday_draggers_report.json` (§direction_decomposition).

### 2026-07-21 — METRIC SWEEP ATLAS (user-directed, exploratory): PnL-level features are ANTI-predictive at pool scale; structural features (lowDD/activity/turnover/clip) are the monotone axis; composite top-30 = +20.4bp we / SR 1.74 (descriptive)

**Design.** `tape_metric_sweep.py` / `tape_metric_sweep_report.json` (+`_composite.json`): 32 formation
features × quintile buckets over the FULL eligible pool (~42-50k wallets/fold, nd≥15), walk-forward to
next-month copy performance (flat opens ≥$250, 8h mk, net 2.6bp; wallet-fold-equal + equal-$1k Sharpe/
Sortino per bucket), 8 folds. USER-DIRECTED EXPLORATORY on burned folds — screening atlas, NOT evidence;
no multiplicity control by design. Month-grain caches (wcd + all-wallet 8-horizon entry markouts).
Proxies documented (hold=open→next-close gap; leave-best-DAY-out; maxDD raw $, scale-confounded).

**Headline structure (per-fold q5−q1 wallet-equal delta = the WF quantity; pooled-bucket view can
Simpson-flip via cross-fold wallet pooling — both stored):**
- **PnL-LEVEL features are ANTI-monotone at pool scale:** worst_decile_pnl d=−9.1 (0/8 folds>0!),
  median_daily_pnl −7.0 (1/8), pct_prof_days −6.1 (1/8), consistency −5.4, leave_best_coin −4.3 (0/8).
  Broad-pool recent PnL levels mean-REVERT for a copier. (Does not contradict the top-30 capday tail —
  quintiles ≠ extreme tail — but explains why PnL-ranking alone struggles.)
- **STRUCTURAL features are the monotone axis:** max drawdown (smaller better) d=+9.9 **8/8 folds**,
  q5 Sharpe +0.78 vs q1 −1.48; trades_per_active_day +9.6 **8/8**; turnover +8.2 (7/8); median entry
  notional +5.4 (7/8); ret_autocorr +3.7 (7/8). Q5 cells are the only positive-Sharpe cells in the atlas.
- Formation markout: pooled-bucket slope negative (Simpson) but per-fold deltas mildly positive
  (mk8 d=+2.2, 7/8) — weak either way at quintile grain, consistent with the 2026-07-12 "markout can't
  ID wallets" verdict. Degenerate cells (maker_share q1, uniqueness, frac_months_prof, cap_sensitivity)
  = discrete-mass quantile collapse; noted, need custom bins if pursued.
- Pool level: average eligible wallet's copy markout ≈ −5 to −8bp we (the field is bad; selection is
  about escaping it).

**Composite (post-atlas, hypothesis-grade):** mean percentile of {−maxDD, +trades/day, +turnover,
+med_entry_notl} — NO PnL feature. Quintile monotone 7/8 folds (q5−q1 +6.1bp avg); q5 (≈18k wallets)
net +0.9bp SR +0.60 — the only positive-net quintile-scale cell. **Composite TOP-30: wallet-equal
+20.4bp, net +10.7bp/trade, SR 1.74, Sortino 2.70, n=1,178 entries / 88 wallets, 6/8 folds positive —
~6× the capday top-30's followable surface** (structural selection picks active, followable wallets by
construction). Caveat: composite chosen AFTER seeing the atlas on the same folds (selection-on-selection);
fold 202512 negative both views. Candidate forward arm: "structural top-30" (± long-only overlay per the
dragger addendum) alongside majors-native and capday arms. Artifacts: tape_metric_sweep.py,
tape_metric_sweep_report.json, tape_metric_sweep_composite.json.

### 2026-07-21 addendum — STRUCTURAL TOP-N KNIVES + FREEZE: all four features load-bearing; N=30; long-only stacks; spec FROZEN

Final descriptive knives (`structural_knives.py` / `structural_knives_report.json`, burned folds) before
the freeze: **Gates help** (metric_cap>0 ∧ fills/day<1000: we +20.4→+26.6, SR 1.74→1.99, 7/8 folds).
**LOFO — every feature earns its seat:** drop maxDD → wallet-equal collapses +26.6→+1.3; drop activity →
SR 1.24; drop turnover → net +3.3; drop clip → net +1.6. Full-4 retained. **N-sweep:** N30 best (SR 1.99);
N50 = 8/8 fold-positive at lower point (+19.4/SR 1.49, secondary); N20 underdiversified; N75/100 dilute
(confirms "tighter beats wider" on this selector too). **Long-only overlay stacks as the dragger addendum
predicted:** N30 long-only we **+41.5, net +29.0, SR 2.58** (770 entries, 77 wallets, 6/8 folds).
Ex-202512 sensitivity: +32.9/SR 1.81 — 202512 drags, doesn't flip. **`STRUCTURAL_TOPN_PREREG.md` v1.0
FROZEN**: gates → 4-feature rank-mean score → top-30 → long-only flat opens ≥$250 → equal-$ (10%/wallet
cap) → 8h; predictions P1–P4 registered (net>0 expected +15–30bp; long-only ≥ both-sides; structural ≥
capday; ≥80 entries/mo); ≥6mo forward before any verdict. Burned-fold work on this line CONCLUDES here.

### 2026-07-21 addendum — STRUCTURAL COHORT ATTRIBUTION: drag is NOT wallet-persistent (identity ≈ winner's curse) but IS feature-separable (whale-clip/slow/crowded profile); prereg stays v1.0

**Question (user).** Are the structural cohort's draggers persistently-bad, structurally-different,
pre-filterable traders? `structural_attribution.py` / `structural_attribution_report.json` +
`_amendments.json` (descriptive, burned folds).

**Persistence — the premise's identity-level half is REJECTED.** 240 wallet-folds → 169 distinct wallets
(92 silent on the long book). Of 77 active: 36 draggers (−$1,240) / 41 helpers (+$3,469). Only 12 wallets
active in ≥2 folds; consecutive-fold contribution sign agreement **57% (n=14 pairs, ≈chance)**, corr +0.28
(noise-grade). **Repeat draggers: 2; repeat helpers: 7.** 11 of the top-12 draggers were selected in
exactly ONE fold. Per-wallet drag does not repeat → identity-level exclusion ("ban last month's losers")
cannot work; at the wallet-identity level the drag IS winner's-curse-shaped noise.

**BUT the group-level structural profile is real and formation-visible.** Dragger vs helper medians (the
composite score itself is FLAT — 0.822 vs 0.819, at its selection ceiling): draggers are **whales**
(median formation clip $80k vs $44k; test-month clip $109k vs $40k), **slower** (hold proxy 106 vs 50
min), **swingier** (formation maxDD $94 vs $38), **more crowded** (entry consensus 370 vs 288), **less
HYPE** (13% vs 41%), shorter-tilted in test (31% vs 20%), with **weaker formation entry markout (+9.2 vs
+32.4bp)** — within the already-selected cohort, formation mk8 separates even though it can't select at
pool scale (nested-signal read of the 2026-07-12 verdict). Also lower pct-prof-days (0.69 vs 0.77).

**Candidate feature-level screens quantified (burned, hypothesis-grade):** on the frozen primary
(long-only N30, +41.5 we / +29.0 net / SR 2.58, 6/8): (A) formation-mk8≥0 gate → +42.6/+21.7/1.47 (7/8);
(B) **clip≤$100k cap → +56.7/+32.0/2.57 (6/8)**; (C) both → +61.5/+28.3/2.11 (7/8); (D) mk8 tiebreak
top60→30 → +50.6/+23.8/1.81 (7/8, widens surface to 1,004 entries). **PREREG STAYS v1.0 — no amendment**:
these gains are exactly the shape the anti-ratchet clause guards (new screens minted from the same burned
folds post-freeze); variant (B) is TRACKED as a shadow secondary in the forward run (report-only), and
promotion would require it to beat the primary forward. Consistent priors: whale/notional fragility
(entry-level shape 2026-07-17), crowding ≠ quality at entry grain, "condition on the side/feature, not
the seat." Artifacts: structural_attribution.py, structural_attribution_report.json,
structural_attribution_amendments.json.

### 2026-07-21 addendum — STRUCTURAL PRIMARY WF BACKTEST: headline SR 3.25 but it is a HYPE book (86% of profit); ex-HYPE = weak underpowered positive

Full frozen-spec book (`structural_wf_backtest.json`): long-only N30, 8h, $1k clips, 10%/wallet cap
(cap active: 770→434 entries, and it HELPS — per-trade net rises to +42.3bp). PRIMARY: **net +42.3bp/tr,
+$1,837, SR 3.25, Sortino 6.76, MDD $216 = 1.7% of $13k peak exposure**, 6/8 months+, robust to 5.5bp
stress (SR 3.04). **BUT the coin cut is decisive: HYPE = 42% of entries and 86% of profit** (+86.5bp net,
SR 3.31); **EX-HYPE: +10.4bp net, $263, SR 1.05, Sortino 1.64, 4/8 months** — direction positive, not a
book. Per-coin: BTC +8.8bp SR 0.80; ETH +14.0 SR 0.93; SOL +12.3 SR 0.30. HYPE 8h field drift +7.6bp
explains <10% of the HYPE cell — the excess is real selection-on-HYPE-flow in this era, but it is ONE
COIN, ONE REGIME (listing era; the helpers' hype_share 41% vs draggers' 13% presaged this). Honest read:
the strategy as frozen is substantially a "copy structural winners ON HYPE" trade; ex-HYPE it is an
underpowered positive (~+10bp) in the majors-native K30 class. Forward adjudication unchanged; P1–P4
stand; ADD registered forward cut: report PRIMARY and EX-HYPE separately every read (concentration
tripwire: HYPE >60% of monthly profit = flag).

### 2026-07-21 addendum — EX-HYPE SWEEP (BTC/ETH/SOL only, selection AND forward): structural axis SURVIVES; the harvestable book does NOT

`tape_metric_sweep_exhype_report.json` + `structural_exhype_composite.json` (descriptive, burned).
**Atlas:** the structural axis is NOT a HYPE artifact — maxDD d=+7.5 **8/8 folds** (was +9.9), trades/day
+7.7 **8/8** (was +9.6), turnover +5.1 7/8, clip +3.2 6/8, ret_autocorr +2.8 6/8; PnL-level features stay
anti-monotone (worst-decile −6.3, 0/8). Attenuation ~20–35% but identical ordering and fold consistency.
**Composite books (BES selection × BES forward, frozen mechanics):** long-only N30 wallet-equal +38.0 BUT
equal-$ net only **+3.6bp, SR 0.29** (214 entries; the wallet-equal/entry-mean gap = busy wallets' marginal
entries are weak); both-sides N30 +8.7bp net SR 0.87; N50 long-only −1.0. At realistic 10bp RT taker fees
all ex-HYPE variants are ≤0. **Read: the structural selection signal generalizes across coins (feature
level), but its harvestable expression at taker costs was HYPE-regime-specific.** The forward slate's
honest framing stands: primary book = HYPE-concentrated with tripwire; ex-HYPE = wallet-level signal
awaiting a cheaper execution path (maker) or a richer regime, not a taker book.
