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
