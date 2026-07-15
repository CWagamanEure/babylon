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
