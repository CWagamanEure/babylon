# COPY_COHORT_ARCH — powered wallet-cohort copyable-markout persistence test
**v1.1, 2026-07-12** — revised after the design-stage audit swarm
(`audit/copy_cohort_arch/{SCOPE,FINDINGS}.md`: 1 CRITICAL + 4 HIGH accepted; clean bills on lane
firewall, EB validity, Stage-0 leakage safety, verdict taxonomy, prior-findings register).

**The one question this answers:** does a wallet cohort selected at a cutoff, on formation-window-only
evidence, have **positive out-of-sample episode-level timing alpha at a copyable horizon** — beating
activity/size/coin-mix-matched random cohorts — with a design **powered at the follower-economics
care-about (~5 bp)** instead of the ~160 bp MDE that made Stage A blind by construction?

**Why — user steer.** The user wants the copytradeable-cohort question answered properly: (1) coin-day
sampling burns 3–4× the sample on an unmeasured dependence assumption — measure the dependence and pick
the unit empirically; (2) decisions, not fills, are the economic unit a follower copies; (3) handle
residual dependence with cluster-robust inference at a coarser level, not by discarding data; (4) run a
realized-PnL selector arm alongside markout (the P0 ledger-fix run found taker-only PnL rank persistence
Spearman +0.453 OOS, +17.06 bp [−5.95, +40.55] — a live lead with open obligations: beta-cleaning,
winsorization, clustered CI. This study discharges those obligations inside a pre-registered harness).

**Relation to prior verdicts (must-not-contradict register):**
- *Stage A (naive taker rankings)*: INCONCLUSIVE, MDE ≈ 160 bp — not a null. This study is the
  "build a powered design" obligation from the anti-ratchet rule, not a re-run of a blind instrument.
- *wallet_flow "alpha wallets" tight null*: that closed axis is **flow-alignment selection to improve
  the hourly xsec panel signal** (per-bucket partial IC). This study's estimand — per-wallet episode
  markout for direct copy — is a different quantity on a different unit. No contradiction either way;
  neither verdict transfers.
- *Stage M*: population day-weighted persistence +0.16 is real but not tradable after costs on that
  window; frozen unit precedent = decision episodes, conservative N_eff. This study keeps the episode
  unit and replaces the blanket N_eff=days conservatism with measured dependence (Stage 0).
- *edge3 stale-candle artifact*: guarded by the lake's construction — **entry** priced at the first
  oracle tick STRICTLY after `open_ts`; **horizon ends** priced backward-ASOF within ≤90 s of
  `entry_bar_ts + h` (no lookahead either way). ⚠️ The entry-side freshness guards are *carried but
  not enforced* by the lake — this study must re-apply them (filter F0 below).

---

## 1. Estimand

**Universe.** Majors only (BTC, ETH, SOL, HYPE) — the coverage of `data/derived/episodes/`
(~34 M episodes) and `data/derived/episodes_markout/`. Window 2025-08 … 2026-06 (11 months).
The alt cross-section is out of scope (alt_flow lake has no per-wallet episodes; a majors-positive
result does NOT license an alts claim — see the wallet_flow alt-extension negative).

**Observation unit = position episode** (`research/data/episodes_build.py` lifecycle: flat→nonzero
opens; only return-to-flat or flip terminates; adds/reduces intra-episode; cross-month carry threaded).
Implementation cautions (from the builder's own contract): all time predicates on `open_ts`/`close_ts`,
NEVER on the finalize-month partition key; the markout-join population is `NOT inherited_basis` by
construction; join key = (wallet, coin, opener_block, opener_event_index), which is unique ONLY
under `NOT inherited_basis` (an inherited FLIP leg reuses its residual leg's key — both join sides
must filter). All CLUSTERING time keys (day, week) are anchored on `open_ts` (one time base ⇒
day ⊂ week nesting holds); the entry-tick ISO week is used only for the μ join. Known one-tick
asymmetry, accepted: the μ censor is `(t + h) ≤ cutoff` (mu_baseline R2/R10) while episode
membership is strict `<` — one boundary minute per coin-fold, immaterial.

**Primary outcome (Arm A target): timing-residual episode markout at h = 4 h**, from
`data/derived/episodes_markout/` (oracle_px, per-minute ASOF, dir-signed bp; columns `raw_markout_<h>`
with all horizons wide on one row, plus `ph_<h>` prices and `entry_lag_s`/`entry_after_close`):
`y = raw_markout_4h − dir_sign·μ_4h(coin, ISO-week)` — the Tier-2 timing-alpha construction.
μ_4h(coin, week) is computed **per fold** from the built per-minute `data/derived/fwd_returns/`
primitive with the `(t + h) ≤ cutoff` censor (the R2/R10 rule in `mu_baseline.py` — this correctly
truncates the cutoff-straddling ISO week). The single-global-cutoff aggregation in
`features_markout.py` / `addr_coin_markout` is **forbidden as a μ source** (its censor is pinned to
2026-06-29 → per-fold leakage). Evaluation-side μ uses the same construction censored at the NEXT
fold's cutoff (fully out-of-formation by then).
- Secondary (directional only): h ∈ {1h, 2h, 8h}; BTC-beta-residualized variant
  (per `markout_study/src/cohort_M_power.py` construction).
- Wallet-level statistic: **equal-weight mean of y over the wallet's qualifying episodes**
  (a follower allocates per decision, not per fill; per-fill weighting would let one split order
  dominate).

**Copyability secondary estimand (frozen):** follower-lag markout — entry at the +5 min oracle tick:
`y_lag = dir_sign·(ph_4h − ph_5m)/ph_5m·1e4 − dir_sign·μ_lag(coin, ISO-week)`,
computed **exactly from the `ph_5m`/`ph_4h` price columns** (NOT `raw_markout_4h − raw_markout_5m`,
whose common-`p0` denominator gives a different quantity). μ_lag per minute t from the fwd_returns
primitive: `(1 + fwd_ret_4h)/(1 + fwd_ret_5m) − 1`, aggregated per (coin, week) under the same ≤cutoff
censor. Reported alongside the primary; the GREEN verdict requires the cohort's y_lag point estimate to
remain positive (a cohort whose entire markout dies in the first 5 minutes is not copyable).

**Care-about effect size (frozen): +5 bp** per episode at 4 h for the selected cohort — taker-copy
round-trip breakeven (~2.5 bp/side, prior wallet-screen finding). Maker-path care-about 1.5 bp is
recorded but the power gate is set at 5 bp.

## 2. Stage 0 — dependence calibration (pick the unit empirically, then freeze it)

Burn-in slice: **202508–202510 only.** Calibration (test-validity) analysis, not effect selection —
no selector, horizon, or filter choice may be made from Stage-0 effect sizes. (Audit clean bill: the
decisional diagnostics below are functions of second moments / rejection rates, effect-blind to first
order, so burn-in-inside-formation overlap is benign.)

Candidate observation units: (a) opener fills, (b) episodes, (c) wallet-coin-hour means,
(d) wallet-coin-day means. Candidate SE-clustering levels: episode, wallet-coin-day, wallet-week,
**coin-week (time-block — captures cross-wallet dependence)**, wallet (whole burn-in).

Diagnostics and frozen rules:
1. **Variance-ratio (Moulton) check** — empirical variance of wallet-week mean y vs the iid-implied
   variance from unit-level y; the ratio is the SE-inflation factor per (unit, cluster) pair.
2. **Sign-flip calibration — non-circular construction (audit S4).** The null is generated by
   flipping signs at the **coarsest wallet level** (one flip per wallet, broadcast to all its rows —
   the NEW `cluster_id` variant of `stats.sign_flip_pvalue`); the test statistic is then computed
   with CR0 clustering at each **finer** candidate level (episode / wallet-coin-day / wallet-week;
   t critical at G−1). The SAME seed — hence an identical sign matrix — is used for every candidate
   level (paired comparison). **n_perm = 10,000** (Wilson half-width ≈ 0.0043 at rate 0.05).
   Registered calibration populations (code-audit F3): wallets with **≥ 10** scoreable burn-in
   episodes (breadth) AND the **≥ 30** F1-level subpopulation (matches downstream eligibility).
   **Frozen rule: adopt the coarsest candidate below wallet whose rejection-rate Wilson 95% CI ⊂
   [0.03, 0.07] on BOTH populations**, applied to episode-level observations; if none calibrates,
   fall back to wallet-week `stats.cluster_bootstrap_ci` and report the miscalibration. Cross-wallet
   time dependence is NOT visible to wallet-level flips (coin-week is not wallet-nested and cannot
   enter this ladder — it appears in the Moulton table only); that axis is handled structurally by
   the two-way inference in §5.5, validated by deliverable 3.
3. **Two-way-CI coverage simulation (audit S1 deliverable):** simulate wallet-shock + week-shock +
   noise panels matched to burn-in dimensions and verify the §5.5 CGM interval covers ≥ 93% at
   nominal 95% (and that the rejected "wider-of-two" rule undercovers, as the audit probe showed —
   80.0% — recorded for the record).
4. Supporting descriptives (reported, not decisional): autocorrelation of y residuals by episode lag
   and by inter-episode time gap; correlation among overlapping-markout-window episodes; cross-wallet
   same-(coin, hour) correlation of y before vs after μ-subtraction.

Output: one frozen (unit, cluster-level) pair used everywhere downstream, recorded in
`FINDINGS.md` with the diagnostic table, seeds, and n_perm.

## 3. Eligibility filters (frozen; formation-window-only; computed at the cutoff)

From `data/derived/episodes/` + `data/derived/episodes_markout/` + `data/derived/addr_coin_features/`.

**Scoreability and the two membership rules (audit W1/W3/D1 — load-bearing):**
- **F0 (entry freshness, both arms):** an episode is scoreable only if `NOT entry_after_close AND
  entry_lag_s ≤ 90` (the lake stores but does not enforce these; ~19–21% of raw episodes fail
  `entry_after_close` — sub-minute round-trips whose "entry" tick postdates the close).
- **Arm A formation membership (window censor, no close requirement):**
  `entry_bar_ts + h < cutoff` per horizon h. This (i) keeps every formation markout window strictly
  pre-cutoff — `close_ts ≤ cutoff` alone lets a 4h window end 3h inside the evaluation month, and the
  straddle-week μ would otherwise inject month-T returns into every candidate's score — and
  (ii) removes the disposition-effect tilt of conditioning on "closed by cutoff" (Arm A's outcome
  never needs the close).
- **Arm B formation membership:** `close_ts < cutoff` (realized PnL needs the close) AND the F0
  guard. The Arm-A/Arm-B membership asymmetry is intentional and documented here.
- Boundary convention: strict `<` at the cutoff instant (first ms of the evaluation month).

A wallet is **eligible** at cutoff M iff, over its formation window (scoreable episodes as above):

| # | Filter | Frozen value | Field basis |
|---|--------|-------------|-------------|
| F1 | Scoreable episodes | ≥ 30 | F0 + membership rules above |
| F2 | Distinct active days | ≥ 20 | distinct date(open_ts) |
| F3 | Distinct active ISO weeks | ≥ 6 | distinct week(open_ts) |
| F4 | Median episode hold time | ≥ 60 min (HFT exclusion) | `hold_minutes` |
| F5 | Median opening notional | ≥ $1,000 (dust/copyability) | `initial_notional_usd` |
| F6 | Decision concentration | max single-episode share of formation gross opening notional ≤ 25% | `initial_notional_usd` |
| F7 | Flag hygiene (incl. vault coverage) | episode excluded if `opener_flagged` (the zhash ∪ self-liq ∪ vault-netting superset — no clean TWAP flag exists; note `VAULT_SQL` is fills-level and vault-ness reaches episodes ONLY inside this superset, so a vault wallet with ≤20% flagged episodes is not otherwise excludable from episode fields alone) or `is_liquidation_close`; wallet excluded if flagged episodes > 20% of formation episodes | `opener_flagged`, `n_flagged_fills`, `is_liquidation_close` |
| F8 | Copyable opener | primary population = episodes with taker opener (`crossed_open = TRUE`); maker-opener population is a labeled secondary | `crossed_open` |

One spec, no grid. Any filter change after first forward evaluation starts a new config epoch
(prereg discipline, cf. `docs/XSEC_BOOK_PAPER_PREREG.md`).

## 4. Selectors — two pre-registered arms, same harness, BH across arms

- **Arm A (markout):** empirical-Bayes shrunk wallet mean of y (timing-residual markout @4h).
  **Estimand freeze (code-audit F2):** `ȳ_w` = the **equal-weight mean over the wallet's episodes**
  — identical to the §1 wallet statistic and the §5.3 forward statistic, so the selector optimizes
  exactly what the walk-forward measures (mean-of-cluster-means was rejected: it re-weights sparse
  clusters and diverges from the registered estimand). Shrinkage: `ŷ_w = B_w·ȳ_w + (1−B_w)·ȳ_pool`,
  `B_w = τ²/(τ² + v_w)`, with `v_w` = the **CR1-corrected CR0 cluster-sandwich variance of ȳ_w at
  the Stage-0-frozen cluster level** (dependence enters here; `n_eff` = cluster count is reported),
  and τ² by method-of-moments across wallets on the formation window per fold (train-only; ȳ_pool
  computed under the same §3 window censor). Degenerate-case spec: τ̂² floored at a small positive
  value with a logged flag; if the MoM estimate is ≤ 0, the registered fallback ranking is the
  wallet t-stat ȳ_w/√v_w; wallets with < 2 clusters carry no variance information → score = pool
  mean, excluded from ȳ_pool and the MoM. NEW lib fn `research/lib/stats.py::eb_shrink` implements
  exactly this; NaN inputs are refused.
- **Arm B (realized PnL):** EB-shrunk wallet mean of realized bps of closed notional
  (HL `closed_pnl`, per the P0 fixed ledger), winsorized at the formation p99, taker-opener episodes
  only. Beta-vs-skill guard: report both raw and coin-week-demeaned variants (demeaning under the
  §3 censor); the demeaned one is Arm B's primary (this is the P0 "index-hedged re-run" obligation).

**Cohort:** top **K = 100** eligible wallets by the arm's shrunk score at the cutoff. Frozen id-list
per fold.

## 5. Walk-forward protocol + matched placebo

Folds via `research/lib/cv.walkforward_splits` (expanding): formation = months < T, evaluation =
month T, for **T ∈ {202602 … 202606}** (5 folds). **Cutoff for fold T =
`cv.as_of_cutoff_ms(last formation month)`** (i.e. `as_of_cutoff_ms(202601)` for T=202602 — NOT
`as_of_cutoff_ms(T)`, which is end-of-T); runtime assertion: cutoff == first ms of month T, and the
fold-T `addr_coin_features` panel is `cutoff=<last formation month>`. Wallet_flow harness pattern
reused (`walkforward.py` / `placebo.py` cohort-temp-table mechanism), evaluation statistic swapped.

Per fold:
1. Freeze eligibility pool and both arms' cohorts on formation only (§3 membership rules).
2. Forward outcome: episodes **opened** in month T by cohort wallets — predicate
   `open_ts ∈ [cutoff_T, cutoff_T+1)` **scanning all partitions** (finalize-month partitioning means
   an episode opened in T that closes in T+1 lives in partition T+1; pruning by `month=T` would
   condition the outcome on fast closes). `OPEN_AT_END` rows are kept (they carry valid markouts;
   relevant in the T=202606 fold). Runtime assertion: #forward episodes in partitions > T is
   positive in any normal month. Markout windows may extend past month end — allowed, the outcome
   is anchored at the open; formation membership (§3) guarantees no window contributes to both sides.
3. **Cohort statistic: equal-weight-over-wallets mean of wallet-mean y** (wallets with ≥ 3 forward
   episodes; count of below-threshold wallets reported, not silently dropped).
4. **Matched placebo:** **B = 100** random cohorts of size K from the eligible pool, stratified to
   match the real cohort's joint composition on **(formation-activity quintile × median-notional
   quintile × majority-coin × formation long-share half)** — activity/size alone leaves
   coin/direction tilts unmatched and makes the null too easy. Stratum-collapse rule: any stratum
   with < 3× the draws it must supply is merged with its nearest neighbor (order: long-share half →
   majority-coin → notional quintile), and the collapse is logged. **Mean placebo↔real-cohort
   membership overlap is reported per fold** (thin strata force overlap, which drags placebo scores
   toward the real cohort and burns power — if overlap > 25% the stratification is too fine and the
   pre-registered fallback is activity×notional matching only). Per-fold empirical p =
   (#{placebo ≥ observed} + 1)/(B + 1).
5. Inference on the cohort statistic (audit S1 — the CRITICAL fix): **two-way
   Cameron–Gelbach–Miller combination** of cluster-bootstrap variances,
   `SE² = SE²_wallet + SE²_week − SE²_iid` (week = ISO-week blocks pooling all cohort episodes;
   iid = unclustered), CI via t critical value at min(G_wallet, G_week) − 1 df, negative-variance
   guard: SE² floored at max(SE²_wallet, SE²_week). The v1.0 "wider of the two CIs" rule is
   REJECTED (audit probe: 80% coverage at nominal 95%). **Per-fold intervals: wallet-cluster CI
   only** (a single month has ~4–5 ISO weeks; week-block bootstrap at G≈5 undercovers — probe 84%);
   week-block and two-way interval inference is reserved for the pooled statistic, where
   G_week ≈ 22.

Pooled (primary test, one per arm): all-folds pooled cohort statistic with the two-way CI above.
**Load-bearing cross-unit test (audit S5): one-sided wallet-level sign test** on the K cohort
wallets' forward mean y (n ≈ 100 units, direction pre-registered positive), via `stats.sign_test`'s
one-sided tail. The cross-fold sign test (5 folds vs fold-wise matched-placebo medians) is reported
**one-sided** (two-sided min-p on 5 folds is 0.0625 — structurally unable to fire) and is a
consistency display, not the primary. **BH-FDR across the 2 arms** (`stats.bh_fdr`); arm-level
p-values = one-sided sign-flip p of the pooled statistic at the Stage-0 frozen cluster level with
the +1/(B+1) correction. Everything else is labeled secondary/directional. Caveat carried from
wallet_flow: folds share an overlapping wallet pool — 5/5 is not 5 independent draws; say so in
every summary.

## 6. Power gate (before any forward number is looked at)

Two components, both mandatory (audit S2/S3 — the v1.0 gate was vacuous on selection and mis-leveled
on inference):

1. **Instrument MDE at the realized test level:** MDE = (z_α + z_β)/z_α × half-width of the SAME
   pooled two-way CI procedure as §5.5, computed on formation data **sized to forward dimensions**
   (5 single-month legs, K = 100, the ≥3-forward-episode floor applied, cluster counts as realized).
   Not `power.mde_mean` on Stage-0-level σ — that level is wallet-nested and blind to cross-wallet
   week shocks.
2. **Planted-cohort selection control:** inside formation (formation-internal split), plant a
   synthetic skilled sub-population — 150 random eligible wallets given +5 bp per episode on both
   sub-windows — then run the FULL pipeline (filters → EB scores → top-K → pseudo-forward
   evaluation). Report (a) top-K capture rate of planted wallets and (b) recovered cohort effect
   with its CI. The gate passes only if the recovered effect's CI covers the planted +5 bp and
   excludes 0. A uniform `power.inject_positive_control` injection is retained ONLY as an
   evaluation-stage arithmetic check (it cannot test selection — any top-K inherits a uniform edge).

- Both pass (MDE ≤ 5 bp AND planted control recovered) → proceed.
- Either fails → **STOP. Do not run the forward evaluation.** Redesign (pool horizons by SNR, widen
  folds, deepen residualization) or declare "the available data cannot resolve this" — per the
  anti-ratchet rule, do not run a blind instrument and call the result inconclusive.

API note: the lib entry points are `power.power_check(values, care_about, ...) → PowerReport` and
`power.inject_positive_control(values, edge, direction)`; the planted-cohort harness is NEW (§9).

## 7. Verdict rules (frozen)

- **GREEN (cohort exists):** pooled primary two-way CI excludes 0 (positive) for ≥ 1 arm after BH;
  one-sided wallet-level sign test p < 0.05 in that arm; ≥ 4/5 folds beat their matched-placebo
  median; follower-lag secondary point estimate > 0.
- **AMBER (live lead, not established):** pooled point estimate > 0 but CI ∋ 0 with realized
  half-width ≤ 5 bp, or GREEN-pattern in folds but follower-lag ≤ 0. Register in ledger as
  underpowered-positive or not-copyable-positive respectively; no deployment claim.
- **RED (method-scoped negative, earned):** **realized pooled forward CI half-width ≤ 5 bp** (not
  merely a passed pre-gate) AND pooled CI tight around 0 or negative AND the one-sided wallet-level
  sign test unremarkable → "no copyable cohort edge *from these two selectors on majors*."
  Point estimate + CI + MDE + cross-unit sign test printed — all four over-nulling-gate items —
  before the word "negative" appears.
- Mandatory dual adversarial passes before ANY final verdict (separate agents from the analyst):
  **steelman-the-positive** and **prosecute-the-positive**, equal standing (CLAUDE.md gate).

## 8. Multiplicity ledger (every look enumerated)

Primary looks: 2 (Arm A, Arm B pooled tests) — BH-controlled, p-construction per §5. Registered
secondaries (directional, never headline): 3 extra horizons × 2 arms; beta-residual variant;
maker-opener population; follower-lag estimand; per-fold results; Arm-B raw (non-demeaned) variant.
Stage-0 diagnostics are calibration, not effect looks. Anything not in this list that gets computed
goes into the ledger as an extra look before it is reported.

## 9. Data & code plan (reuse-first; statuses per audit verification)

| Piece | Status | Source |
|---|---|---|
| Episodes lake | BUILT | `data/derived/episodes/` (11 months, 4 majors; finalize-month partitions — predicate on ts, never partition key) |
| Episode markout @ 5m…48h | BUILT | `data/derived/episodes_markout/` (`research/data/markout.py`; wide `raw_markout_*`/`ph_*` columns, `entry_lag_s`, `entry_after_close`; F0 guards NOT enforced by the lake — study re-applies) |
| fwd_returns per-minute primitive | BUILT | `data/derived/fwd_returns/` (`mu_baseline.py`) |
| Per-fold μ_h(coin, ISO-week, ≤cutoff) | **NEW** (trivial aggregation of the primitive; `addr_coin_markout` forbidden as source — global-cutoff censor) | `research/studies/copy_cohort/mu_fold.py` |
| Cutoff feature panels | BUILT | `data/derived/addr_coin_features/` (cutoffs 202508–202606 verified on disk) |
| Walk-forward splitter / cutoffs | BUILT | `research/lib/cv.py` (`as_of_cutoff_ms(last formation month)`) |
| Cluster/block bootstrap, sign test, BH | BUILT | `research/lib/stats.py` |
| Cluster-level sign-flip (`cluster_id` arg) | **NEW** | extend `stats.sign_flip_pvalue` |
| Two-way CGM CI helper | **NEW** | `research/lib/stats.py::twoway_cluster_ci` |
| EB shrinkage (`eb_shrink`, spec §4) | **NEW** | add to `research/lib/stats.py` |
| MDE / uniform injected control | BUILT (`power_check`, `inject_positive_control`) | `research/lib/power.py` |
| Planted-cohort selection control | **NEW** | `research/studies/copy_cohort/power_gate.py` |
| Stage-0 dependence calibration | **NEW** | `research/studies/copy_cohort/stage0_dependence.py` |
| Eligibility + selector panel | **NEW** | `research/studies/copy_cohort/selectors.py` |
| Matched-placebo walk-forward | **NEW** | `research/studies/copy_cohort/walkforward.py` |

Firewall notes (audit: clean bill): research-lane only (`research/studies/copy_cohort/`); consumes
derived lakes read-only; nothing imports from `markout_study/gate_a/` or `src/babylon/`; scratch
under the study dir or the session scratchpad, never into `data/raw/`.

## 10. Order of work

1. ~~Audit swarm on this doc~~ DONE 2026-07-12 → `audit/copy_cohort_arch/FINDINGS.md`; this v1.1
   incorporates every accepted finding.
2. Lib additions (`eb_shrink`, cluster sign-flip, `twoway_cluster_ci`) + `mu_fold.py` +
   Stage 0 build → code audit → run Stage 0 → freeze (unit, cluster) + CI-coverage simulation.
3. Selector panel + walk-forward + planted-control build → code audit.
4. Power gate (§6, both components). STOP here if not powered.
5. Forward run → steelman + prosecute passes → verdict → `FINDINGS.md` + master ledger update.
