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

**1. V2 bakeoff (6 selector arms, v2_bakeoff.py):** t_v1 +27.6 [+0.7,+53.1] 7/8 folds and t_noliq +27.4
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
NOTHING qualifies. CI-clearing cells (2/20, uncorrected): B/1h/crowd +54.7 [+15,+101]; TOP-HALF-T consensus —
B gap +121 [+32,+203], A crowd +98.7 [+46,+155] — replicates the sparse majors "consensus rescues" lean in
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
