# Stage K — Powered, pre-registered test of the high-sample taker cohort
### regime-distribution · breadth · beta-split · archetype · OOS persistence

**Status:** ARCHITECTURE (pre-build). To be design-audited (read-only swarm) → built → code-audited → run →
steelman/prosecute → ledger. Pre-registration: the decision rules in §7 are frozen BEFORE any test-window
number is examined.

---

## 0. Motivation & priors (from the 2026-07-05 working session)
- Ranking wallets by markout fails at low sample = winner's curse (demonstrated: train-positive wallets at
  n∈[200,500] go **−5.3 bp OOS**; individually-"significant" in-sample wallets revert to +5.7 [−20,+32]).
- BUT the selection test's OOS edge **rises with sample size**: train-positive wallets go +5.4 bp (n 500–1000)
  and **+19.1 bp (n≥1000)**, differential-over-train-negative **+6.4 / +24.2 bp** — an **underpowered positive**
  (only 294 / 25 wallets; CIs span 0, MDE 17/42 bp). The signal appears exactly where power runs out.
- **Beta timing IS skill** (not a confound). The confound is that *static long exposure* (bull-market luck)
  and *directional timing skill* look identical in a mostly-up 11-month sample. Separating them needs the
  regime variation we do have (and, for confirmation, forward months).
- Goal is BOTH: a **beta-neutral (idiosyncratic)** edge is preferred (orthogonal to market, easiest to trust
  as "informed"); a **directional-timing** edge is acceptable (boss will take directional exposure).
- Over-null AND over-carry both apply: every verdict carries point estimate + CI + MDE + cross-unit sign;
  a null must EARN it (tight CI + MDE ≤ care-about); a positive faces the full FP gauntlet.

**Overarching question.** Within the taker-dominant, high-sample cohort — where the winner's curse fades — is
there a persistent OOS edge that is (a) idiosyncratic (survives beta-neutralization), and/or (b) a genuine
directional timer (regime-robust, not just static long-luck), and (c) *broad* (not carried by a few days)?

---

## 1. Cohort definition — OUTCOME-INDEPENDENT (frozen before any outcome is read)
The cardinal rule: **select on who they are, never on how they did.** Selection uses only:
- **Taker-dominant:** `taker_share ≥ 0.70` (notional crossed share, whole-window) — from
  `out/hold_size_dist.parquet` (Job A, already computed for ~29k ≥200-fill wallets). Excludes MM/hedgers.
- **High sample:** pooled TRAIN 24h-markout entries `n_train ≥ 200` (primary strata: 200–500, 500–1000,
  ≥1000) — from `out/wallet_level_persistence.parquet` / recomputed in Pass C. The ≥500 tier is the
  pre-registered PRIMARY (where the lean appeared); 200–500 reported as a secondary/power-context stratum.
- **Copyable hold:** median taker hold in [1h, 24h] AND `n_copyable ≥ 100` (taker-opened 1–24h round-trips)
  — from Job A. (Rationale: the horizon we can actually copy; excludes pure HFT scalpers and 48h+ swing-only.)
- Coins: BTC, ETH, SOL, HYPE. SPX excluded (prior stages: control degenerate).
NOTE: the cohort list is written to `out/cohort_K.txt` and FROZEN before Pass C prices any test entry.

## 2. Splits (identical to every prior stage; leak-free by construction)
TRAIN `ts < 2026-02-01` · EMBARGO Feb · TEST `ts ≥ 2026-03-01`. Selection, ranking, regime thresholds,
breadth reference, neutralization benchmarks: **all computed on TRAIN (or full-field priors), never on the
per-wallet TEST outcome.** TEST enters only through the outcome metric.

## 3. Estimands (report BOTH; neither is privileged a priori)
- **RAW 24h markout** `dir·(px(b+24h)/px_entry − 1)·1e4` — the directional/deployable basis.
- **Coin-day-neutralized** `raw − (coin-day-mean of raw)` — the idiosyncratic/skill-measurement basis.
  ⚠️ Per Stage F, neut is NOT a deployable return (you can't hedge the coin-day mean). It is the cleanest
  *skill* measure; deployability is judged on RAW (+ regime robustness).
- **Horizon:** PRIMARY = 24h (comparability with all prior stages). SECONDARY diagnostic = the SNR term
  structure across {1,2,4,8,24h} computed on TRAIN only (to see where the edge realizes) — used to *report*,
  NOT to select the horizon (argmax-horizon selection is banned; cf. edge_gate artifact).

## 4. Regime definition — the luck-vs-timing separator (must be look-ahead-free & non-circular)
Regime is a BACKGROUND condition known at entry, on a SLOWER timescale than the 24h markout, so it cannot be
the same move the outcome measures:
- **`btc_trail7`** = sign & magnitude of BTC's trailing 7-day return AT entry bar (known at entry, no
  look-ahead). Buckets (thresholds frozen): **BULL** `> +3%`, **BEAR** `< −3%`, **CHOP** otherwise.
- Also tag **entry direction** `dir` (+1 long / −1 short) and, secondarily, `vol_regime` (trailing realized
  vol tercile) for a robustness cut.
The discriminator, per wallet AND pooled cohort, is the (regime × dir) edge table:
- **Static long-luck** signature: positive edge in BULL-long, negative/absent in BEAR; net-long everywhere.
- **Directional-timing skill** signature: positive edge in BULL-long AND **BEAR-short** (they flip and the
  shorts pay) → real timing.
- **Neutral/idiosyncratic** signature: edge positive across regimes AND survives coin-day-neut → orthogonal.

## 5. The tests
**Backbone — OOS persistence (pooled, clustered).** Pre-specified operating cohort = the §1 cohort (NOT
re-ranked on outcome). PRIMARY estimand = pooled TEST edge (raw and neut, separately) with **two-way
(wallet, coin-week)-clustered bootstrap 95% CI**. Report per-coin and drop-HYPE. Also the SELECTION variant
(train-positive subset → TEST edge) for continuity with the session finding, clearly labelled as a secondary
(selection-conditioned) view.

**(a) Regime-distribution test (§4 table).** Pooled cohort edge by (regime × dir), clustered CI per cell.
Classify the cohort (and each wallet) into static-luck / timer / neutral by the §4 signatures. Cross-unit:
sign consistency of the BEAR-short cell across the 4 coins.

**(b) Breadth test (disqualifier).** Per wallet (and cohort): fraction of total signed markout·notl from the
single best UTC trading day; **days-to-half** (min #days for 50% of edge); **leave-best-day-out** edge. A
wallet/cohort whose edge does not survive removing its single best day is flagged NON-BROAD (luck-like).

**(c) Beta split.** RAW vs coin-day-neut (§3). Additionally a per-trade regression `markout ~ dir·mkt_ret`
(field β) → idiosyncratic residual, LOO-index to avoid self-inclusion (cf. edge_gate). Report idio share.

**(d) Archetype characterization.** On the frozen cohort, behavioral typology from Job-A/tape features
(hold-band mix, add/martingale via `pos_after`/`avg_entry_px`, coin HHI, cadence, conviction-scaling: does
edge rise with add-intensity? — the doubling-down feature). Descriptive/hypothesis-generating, not a verdict.

## 6. Power / MDE / positive control (mandatory — no blind test)
- Per stratum & per regime cell: `MDE = 2.8 · SE_cluster`. If `MDE ≫ care-about (+10 bp)` → that cell is
  **INCONCLUSIVE by construction**, reported as such, never "null."
- **Positive control:** inject a synthetic `+10 bp` edge onto a random 25% of the cohort's TEST entries;
  confirm the estimator's CI excludes 0 (pipeline can *see* the care-about effect). If it can't, the design
  is blind → fix before interpreting.
- **Negative/placebo control:** 200 activity+taker-share-matched RANDOM cohorts through the identical
  pipeline → the real cohort's percentile (guards "generic crowding"/field-drift manufacturing the result).

## 7. PRE-REGISTERED decision rules (frozen before reading TEST)
Primary = pooled TEST edge of the ≥500-tier taker cohort. Judged separately for NEUT and RAW:
- **NEUTRAL (idiosyncratic) leg — CONFIRM** iff: pooled TEST neut CI excludes 0, MDE ≤ +10 bp, breadth-robust
  (survives leave-best-day-out), and placebo percentile ≥ 95. → "beta-neutral informed edge in this cohort."
- **DIRECTIONAL leg — CONFIRM (timer)** iff: pooled TEST raw CI excludes 0 AND the BEAR-short regime cell is
  positive with CI excluding 0 (they make money short in bear) AND breadth-robust. → "directional timing skill."
- **STATIC-LUCK verdict** iff raw edge is positive ONLY in BULL and BEAR-short ≤ 0 → label static exposure,
  NOT skill (expected to fail forward in a bear).
- **INCONCLUSIVE** iff point estimate positive but CI includes 0 or MDE > care-about → surface point + CI +
  direction; do not call null. (Expected outcome given ~300 wallets: at least the neut leg likely lands here.)
- **METHOD-SCOPED NEGATIVE** (earned) iff pooled TEST edge is a TIGHT zero (CI within ±care-about) with
  MDE ≤ care-about, breadth/regime showing nothing → "no persistent copyable edge even in the clean
  high-sample taker cohort" — a real, registerable conclusion.
Multiplicity: ONE primary per leg (neut, raw). Regime cells, strata, per-coin, archetype = secondary/
descriptive, reported with the caveat and (where inferential) BH-FDR across the cell family.

## 8. Execution plan — RAM-safe, strictly serial (one heavy job at a time, ramguard, streaming)
- **Job A (running):** `hold_size_dist.py` → taker_share + hold + n_copyable per wallet. (defines §1 cohort.)
- **Job B (in-memory):** join Job A + `wallet_level_persistence` → apply §1 filters → write `out/cohort_K.txt`
  (+ `out/cohort_K_features.parquet`). FROZEN.
- **Job C (serial tape/entry+bars pass):** price ONLY the cohort's entries — per-entry RAW + coin-day-neut 24h
  markout (reuse `how_they_trade.fwd`/`mkcommon._next_bar_close_vec`), + `btc_trail7` regime tag + UTC day key
  + dir, TRAIN/TEST flag. Per-coin streaming over `out/entries` filtered to cohort wallets. Output small
  per-entry parquet `out/cohort_K_entries.parquet` (~cohort-sized, not 7.3M). Peak ≤ ~1 GB.
- **Job D (in-memory):** the §5 tests + §6 power/controls + §7 rules on the small per-entry file.
- **Job E:** read-only steelman + prosecute swarm; update `docs/FINDINGS_LEDGER.md` Stage K.
Reuse: `mkcommon` (pricing, splits, MAJORS), `how_they_trade.fwd/daymean`, `deployable_edge`/`stage_i_probe`
(cluster bootstrap), `cohort_forensics.wallet_descriptors` (archetype). Never `read_parquet` the 3.3 GB tape;
Job C reads `out/entries` (already-built, sharded) filtered to the cohort + per-coin bars.

## 9. Known failure modes to pre-empt (for the design audit to pressure-test)
- Regime tag circularity / look-ahead (btc_trail7 must be strictly pre-entry).
- Breadth metric gamed by notional-weighting (a whale-day). Report equal-weight breadth too.
- Coin-day-neut re-quoted as deployable (Stage F ban).
- Selection touching the outcome (cohort must be outcome-independent).
- Under-power masquerading as null (§6 gate); over-carry of a regime cell that's argmax-of-cells.
- Cohort too small after §1 AND-filters (if ≥500-tier taker+copyable < ~80 wallets, primary is underpowered →
  say so, fall to ≥200 tier, and flag forward-months as the only resolution).
