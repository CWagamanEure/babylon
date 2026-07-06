# 08 — The Metrics Graveyard: "we ranked by many metrics and NONE persisted OOS"

**Section thesis (load-bearing).** Across the whole markout / copy-trade study we tried a large
family of wallet-selection metrics — raw performance, risk-adjusted, robust/outlier-immune,
reliability-shrunk, position-return, consistency, behavioral-feature, neutralized, and order-burst
consensus selectors — under an out-of-sample (walk-forward / train→test) discipline. **No
performance-based selector produced a copyable, deployable OOS edge.** The one selector that
persists strongly OOS (coin-day-neutralized edge, r≈+0.61) persists on an **un-tradeable benchmark
term**, not on bookable P&L. This section is the exhaustive "filter graveyard" the user wants shown.

Two framing facts the reader needs up front:
1. **Performance-based wallet selection is a REGISTERED NEGATIVE** (2026-07-04), not "inconclusive."
   Two direct powered numbers: per-wallet winner's-curse (select each wallet on its best in-sample
   horizon) = **−28.7 bp NET pooled OOS** (past markout is *anti*-predictive per wallet); train→eval
   rank **Spearman ≈ 0** (0.002–0.05, sign-flipping, SE≈0.007) = a tight null on the load-bearing
   quantity. This is the **third independent fall** of the performance-selection premise (the earlier
   two: the +24–31 bp "edge" was an hourly-candle stale-pricing artifact — edge3 audit; and the sealed
   wallet-screen tournament FAILED — wallet-screen verdict).
2. **The rank-persistence that IS real is generic short-horizon reversal, not wallet skill.** Wallet
   rankings *do* predict future performance (Stage M2: rank-IC ~0.09, top-decile forward +4.5 bp
   gross) — but the decile's entire gross edge is captured by a costless mechanical contrarian fade at
   the *same* entries; incremental alpha over the fade is **+1.00 bp, p=0.44 ≈ 0**. So "some rankings
   persist" is true and "copying the wallet beats copying the setup" is not supported.

---

## FACTS — the exhaustive selector table

Grouped by study arc. "OOS test" = the held-out / walk-forward / train→test measurement.
Outcome codes: **NULL/dead** (earned negative), **artifact** (positive that dissolved under audit),
**inconclusive/underpowered** (CI admits an effect; MDE ≫ care-about), **kept** (survives but not as a
deployable edge — e.g. a sizing lever or a non-tradeable benchmark).

### Arc 1 — `selci_fh` selection-metric panels (the original "edge exists" arc, later FALSIFIED)
Source: memory `babylon-edge-investigation.md`. **CRITICAL CAVEAT:** every selector in this arc was
later shown to be ranking on an **hourly-candle stale-pricing artifact** — the whole +24–31 bp edge
was the artifact (edge3 audit; post-fill pricing → eof +0.4 [−14.4,+18.5], all cells gone). So these
"wins" are wins at ranking *noise*. ~17 metrics across 3 panels.

| Selector | Ranked on | Horizon/metric | OOS test | Outcome | Source |
|---|---|---|---|---|---|
| Sortino (old default) | risk-adj edge | 6h fixed-horizon eof | 4-fold walk-forward | mid-pack; cost ~+20 bp/field vs trimmed — beaten | edge-investigation |
| Sharpe | winsor-mean / raw-std | 1h & 6h | 4-fold WF | beaten by central tendency | edge-investigation |
| **Trimmed-mean** | central-tendency edge | 1h & 6h | 4-fold WF | "won" in-sample (+32.8, 4/4) — but the whole edge was later the stale-pricing artifact | edge-investigation / edge3-audit |
| Mean, Median | central tendency | 1h & 6h | 4-fold WF | ≈ trimmed, all ranking the artifact | edge-investigation |
| log_growth, calmar | drawdown-aware | 6h, OOS log-growth | 4-fold WF | do NOT beat trimmed → past drawdowns not predictive enough to SELECT on | edge-investigation |
| recency_wt, recent_third, trend, rolling_pos | recency / hot-streak | 6h | 4-fold WF | all WORSE (recency HURTS — hot streaks mean-revert) | edge-investigation |
| consistency | hit-consistency | 6h | 4-fold WF | ties trimmed, no better | edge-investigation |
| Bet-size filter ("copy bigger-than-usual bets") | per-wallet bet-size elasticity | edge vs size | 2336 wallets | **NULL** — edge DECLINES with size (<0.5x +8 → >5x +3.4), per-wallet Spearman ≈ −0.01 | edge-investigation |
| Downside-deviation (Sortino denominator) | tail-risk, as a SIZING lever | L900_H6 | train→test Spearman | **KEPT for SIZING** (+0.38 pooled, 4/4 folds; orthogonal to edge) — not a selection edge | edge-investigation |

**Verdict of Arc 1:** "metric-selection lever EXHAUSTED" was declared here (trimmed-mean wins/ties every
time across ~17 metrics) — but the edge itself was subsequently killed as an artifact, so read this as
"even among 17 selectors, none rescued a real edge, because there was none to rescue."

### Arc 2 — `mlscreen` sealed tournament (the wallet-screen study, separate cand2 pipeline)
Source: memory `babylon-wallet-screen-verdict.md`, `babylon-wallet-screen-test.md`. Sealed Apr–Jun
2026, 11 months of tape, 6 adversarial audit rounds. **FAIL on everything registered.**

| Selector / signal | Ranked on | OOS test | Outcome | Source |
|---|---|---|---|---|
| Long-window Sharpe | train Sharpe | train→test Spearman | **noise:** +0.07 (524 alt wallets) / +0.03 (1751 tape wallets); selection pctile 84%/75% (not sig) | wallet-screen-test |
| Tournament A / B / C | various screen configs | walk-forward + pooled z | no winner past 1.64 | wallet-screen-verdict |
| Signal E (shrinkage basket) | empirical-Bayes shrunk | walk-forward | ≈ baseline (no lift) | wallet-screen-verdict |
| Signal E2 (lower-CI rank) | conservative CI rank | walk-forward | **INVERTED (−1.17)** — actively wrong | wallet-screen-verdict |
| Signal F (ex-majors selection) | trailing NON-major markout PnL | 10/10 folds incl. 2 virgin months | **sole survivor: positive 10/10** (BUT: alt-identifiability, not a deployed net edge; awaited July confirm) | wallet-screen-verdict |
| Signal G (full-position raw-$ rank) | raw book PnL | walk-forward | did NOT replicate | wallet-screen-verdict |
| Signal G3 (full-position RETURN rank = PnL / scored turnover) | return-on-turnover | 7/9 folds | 2nd candidate (+2.27 virgin), multiplicity-inflated (~9th config) → needed July confirm | wallet-screen-verdict |
| Signal H "the badge" v1 | winsorized pooled-demeaned t | 8/8-fold transfer | **DEMOLISHED** (round-7 audit): ±500 winsor manufactured it; raw transfer +0.42 | wallet-screen-verdict |
| Signal H "the badge" v2 | raw, per-coin demeaned, flip-null | empirical FDR | **ZERO nameable individuals** (empFDR floor 0.26); ~40 real informed wallets exist among 22k but unnameable → product is the BASKET, not a ranking | wallet-screen-verdict |
| Realized-PnL consistency (per-trade Sharpe / hit-rate) | consistency among recently-active | walk-forward, 3 audit swarms | EQUAL-WEIGHT sig (+0.195%/pos, perm p=0.001) **but NOT at deployable TURNOVER-WEIGHT (+0.078%, p=0.08)** — edge lives in small/illiquid trades (capacity trap) | wallet-screen-verdict |
| **Filter graveyard (rejected filters):** concentration / effective-bets (all variants); maker-exclusion (population test: makers transfer BETTER — H4); win-breadth rank; crowd-relative previews (self-crowding bug); drift-neutralization (didn't fix majors); fills-ceiling (whales ≠ desks) | — | population / decile-matched certification | all **rejected** — "filters fix mechanics, statistics fix luck" | wallet-screen-verdict |

### Arc 3 — `markout_study` OOS-persistence stages A–M4 (the core of this study)
Source: `docs/FINDINGS_LEDGER.md` (Stages A–M4), memory `babylon-oos-persistence.md`,
`babylon-markout-study.md`. Universe = BTC/ETH/SOL/HYPE (+SPX where noted), 11 months, purged/embargoed
walk-forward, post-fill pricing.

| Stage | Selector | Ranked on | Horizon | OOS test | Outcome | min p / key stat |
|---|---|---|---|---|---|---|
| **A** | Naive rankings | edge / Sharpe / hit-rate / cum-PnL | 24h primary | 7-split joint-perm null + BH-FDR | **no ranking clears random; 0 FDR survivors** (but MDE≈160 bp → blind → *inconclusive*, 4/5 coins +ve point est) | vw_edge@24h joint-p BTC 0.09 / SPX 0.15 / HYPE 0.18 / SOL 0.42 / ETH 0.78 |
| **B** | Reliability metrics | t-stat (√n·mean/std); empirical-Bayes shrunk edge | all 12 h × 2 floors | grid-wide perm null + FDR | **NULL** — shrinkage does not beat raw vw_edge | global perm p = 0.40; 0 FDR survivors |
| **C** | Robust / top-N / rolling sweep | 9 rankers (median, trim10, mean, vw_edge, eb_edge…) × 12 h × K∈{10,25,50,100,200} × {exp,roll} × {vw,ew} = **9,668 cells** | 5m–168h | config-selection-corrected graduation (label-perm null, max over metric axis) | **nothing graduates**; 24h/small-K "coherent positive" later DEMOTED to unresolved residual (post-hoc argmax, K=50 breaks it) | best config vw p=0.17, ew p=0.26 (both winner-stats negative) |
| **C (sub)** | ew (per-decision) vs vw | equal- vs value-weight | all | aggregate | ew < vw for all 9 rankers; eb_edge negative | — |
| **C (sub)** | rolling vs expanding train | window | all | aggregate | rolling < expanding (except SOL) | — |
| **C (sub)** | outlier-immune (median/trim) | central | all | aggregate | median/trim land ON the field in aggregate → outliers NOT the bottleneck | — |
| **D** | Behavioral traits (typology) | highvol_frac, notl_cv, add_frac, long_frac, coin-conc, momentum, avg-down, cadence | 24h | cohort CI vs activity+notional-matched control band; ew cross-check | descriptive; **highvol_frac** = only robust trait (candidate); **notl_cv** = volume-selection artifact (dies under ew); **long_frac** dropped (over-claimed) | 25/45 descriptors outside band (P≈2e-11) but only 1 robust |
| **E** | High-vol-entry propensity (behavioral, non-circular) | TRAIN-only trait | coin-month-neut 24h | pre-registered 2-way-clustered rank-slope | **INCONCLUSIVE, HYPE-driven:** pooled +3.28 bps/σ (CI excl 0) but **drop-HYPE +1.42 [−0.44,+3.27] spans 0**; deployable raw +7.7 bp < 10 bp cost | pooled CI excl 0; drop-HYPE spans 0; DOF-fragile (only coin-month grain clears) |
| **F** | Coin-day-neut edge decile (conviction t-stat) | past coin-day-neut markout | 24h | decile dose-response, wallet & coin-week cluster CI | **top-decile neut +67 bp (CI excl 0) — but 91% is the un-tradeable −d·coin_day_mean benchmark term; RAW markout only +6.1 bp (< 9.5 bp cost); hedged P&L −7 gross / −16.5 net** | +67.2 [+58,+78]; raw +6.1; hedged CI [−28,+11] |
| **F (neut)** | Raw directional persistence (the tradeable leg) | past raw dir markout | 24h | train→test correlation | **POWERED NULL, −0.03** (same pipeline detects +0.61 neut → not blindness; earns the negative) | r_raw = −0.03 vs r_neut = +0.61 |
| **G** | PnL / entry-timing ranking | realized book PnL; entry direction | H1→H2 | tape round-trip | **PnL ranking does NOT persist copyably (H1 top-decile → H2 −8.4 bp);** cohort not net-profitable (40% profitable, sign-test p=0.013) | H1→H2 −8.4 bp; typical wallet net-negative |
| **H** | Consensus / order-burst (≥9 cohort entries, trailing 30 min) | crowd-agreement trigger | 4–6h | coin-day cluster bootstrap + activity-matched placebo | **UNDERPOWERED positive:** naive net +15.5 (iid CI excl 0) but **clustered CI [−20,+55] spans 0**, eff N≈80, MDE≈56 bp; placebo center −8 bp → real but weak cohort-specific tilt (p≈0.13) | clustered CI [−19.8,+55.5]; selection-corr p≈0.13 |
| **J** | Maker-share-stratified persistence | vw taker markout by maker-share bucket | 24h | wallet-bootstrap Spearman + MDE | **pooled taker-only Spearman −0.007 [−0.047,+0.031] (powered ~0);** vw-positive RETRACTED as beta-carry (equal-weight −0.012 p=0.74; t-stat −0.040) | −0.007 (MDE 0.034); vw positive dies under change of estimand |
| **K** | Isolated mid-freq taker cohort (taker≥0.7 ∧ hold∈[1h,24h] ∧ n≥200) | membership + markout | 1/2/4/8/24h | drift-strip + BTC-regime, +10 bp injection control | **POWERED NULL:** 4h TEST equal-wt +0.3 [−1.0,+1.7], MDE ~1–2 bp; no aggregate copyable edge. Residual: STYLE predicts markout (mrev +3, mom −6) but **generic reversal, not wallet alpha** | 4h +0.3 [−1.0,+1.7]; outcome-indep train-top-q → OOS −0.17 |
| **L** | Archetype typology (vault/hedger/TWAP/directional/mrev/momentum) | userRole + TRAIN behavior | 4–8h | per-archetype markout, BH-FDR | DIR/MIXED/DIR-mom **method-scoped NEGATIVE** (CI upper < +3 bp); DIR-mrev +2.15 = **generic fade** (mechanical fade earns +9.54, wallet-minus-fade **−7.4 [−11.8,−3.1]** — they UNDERPERFORM a robot); nothing survives FDR (q=0.645) | wallet-minus-fade −7.4; FDR q=0.645 |
| **M** | Per-wallet copyable-edge test | single-wallet markout | 4–24h | day-block bootstrap, Romano-Wolf max-t | **power-gate NEGATIVE (BLIND):** median MDE_RW = 33 bp ≫ care-about; apparent "powered tail" is a BTC-degeneracy artifact | MDE_RW 33 bp; median 73 entries/29 days |
| **M1** | Day-weighted rank (shrunk daily alpha-over-fade), top-20 basket | day-weighted markout | 4h | day-block bootstrap + RW max-t | **population day-weighted rank-IC +0.16 (p=0.0001) is REAL & preserved; but frozen top-20 basket ~0 net** (Family A +3.75→+0.20 bp p=0.50 at realistic cost; fade-beating was a selection-leak artifact; month-sign flips) | IC +0.16; basket +0.20 [−11.3,+11.7]; **entry-weighted (naive copier) −0.055** |
| **M2** | Recurrence (repeat top-decile across rolling folds) | cross-fold rank recurrence, neut_8h | 8h | rolling folds, day-capped decile L-S | **rank persistence REAL & powered** (IC 8h +0.093 10/10 p=0.002, fwd-decile +4.5 bp) — but the discrete 3.2× transition was a shrinkage-collapse BUG (→1.09×, p=0.22) | IC 8h +0.093; fwd-decile +4.48 [+2.17,+7.54] |
| **M2-deploy** | Recurrence decile, net-of-cost vs mechanical fade | day-weighted gross markout | 8h & 4h | day-capped, vs fade at same entries | **generic reversal, NOT skill:** gross +14.0 [+5.4,+22.8]; net +7.1 p=0.06 (marginal); **alpha vs mechanical fade +1.00 [−10.8,+13.7] p=0.44 ≈ 0** | alpha-vs-fade +1.00 p=0.44 |
| **M3** | Wallet activity as a fade TRIGGER | wallet event timestamps | 8h | A/B/C/D matched-control, day-block | wallet DIRECTION adds nothing (A−B −3.3 n.s.); unconditional fade LOSES net (C −7.0); trigger-specificity **inconclusive** (B−D daycap +12.4 p=0.014 vs episode +6.6 p=0.28, |tret| confound) | A−B −3.3 n.s.; C −7.0; B−D weighting-dependent |
| **M4** | Frozen continuous-control residual | realized fade − predicted fade | 8h | OLS state model frozen on train, day-block | **per-event residual −1.30 ≈ 0** (state OVER-explains); day-capped **+5.87 [−5.5,+17.7] p=0.15** = LIVE UNDERPOWERED positive (MDE ~11–16 bp ≫ 5 bp care-about, ETH/SOL-driven) | day-capped +5.87 p=0.15; MDE 11–16 bp |
| **P2** | Nested model wallet features (recurring indicator, conv rank, direction, size, position-building) | market-state + wallet | 8h fwd coin return | in-train month-block cross-fit rank-IC | **incremental M1−M0 = −0.0003** — even in-sample-CV, wallet features add ~nothing over 17 market-state features | M0 +0.0490 vs M1 +0.0487 |

### Arc 4 — the neutralization discovery & the free "Step-0" edge gate
Source: memory `babylon-oos-persistence.md` (neutralization discovery), ledger "decisive next move".

| Selector / gate leg | Ranked on | OOS test | Outcome | Source |
|---|---|---|---|---|
| **Coin-day-neutralized per-wallet edge** | dir − coin-day-mean fwd24, pooled across majors | train→test correlation | **+0.61 (biggest signal in the study)** — confirmed 4 ways (perm null →0 at 20σ, placebo 19.7σ, all 7 splits, all 4 coins, h 6–48h) BUT **99% is the untradeable `bench` term; tradeable raw leg = −0.03 (powered null)** | oos-persistence (neutralization discovery) |
| Step-0 (a) index-beta split | idiosyncratic residual vs beta-timing | label-perm null + held-out | **artifact:** perm null reproduces 60–70% of headline idio; real excess does NOT persist OOS (~95% shrinkage); field-β over-attributes (cohort β higher) | ledger Step-0 |
| Step-0 (b) 15-min-lag rebase (copyability) | keep-% under follower lag | random-field comparison | **non-discriminating:** random field wallets show identical keep-% (99–110%) — a 15-min lag on a 24h window shares 99.6% of the path for anyone | ledger Step-0 |
| Step-0 (c) funding-net | edge after subtracting realized funding | — | funding immaterial to the lean (does not rescue or kill) | ledger Step-0 |
| Step-0 (d) SNR term structure | most-detectable horizon | re-select at each horizon | **selection-horizon artifact:** re-selecting at any h moves the "peak" to that h; mean curve ≈ edge₂₄·(h/24) — no info about edge timing | ledger Step-0 |

**Step-0 verdict:** the gate is a "test that couldn't fail" — non-discriminating in BOTH directions; the
initial "3-PASS / GO" read was OVER-CARRY and was RETRACTED. Prior stands: underpowered, inconclusive.

---

## Summary of the graveyard (the one-line answer)

- **Performance selectors (raw edge, Sharpe, Sortino, trimmed-mean, median, mean, cum-PnL, t-stat,
  empirical-Bayes shrinkage, reliability, recency/trend, consistency, bet-size, full-position raw-$,
  return-on-turnover, lower-CI rank):** every one either **NULL/dead** OOS, or a **winner's-curse
  artifact** that collapsed under audit or held-out re-scoring. Registered NEGATIVE: winner's-curse
  −28.7 bp, rank-Spearman ≈ 0.
- **Robustness variants (outlier-immune, top-N, rolling vs expanding, ew vs vw):** none rescued it;
  nothing graduated across 9,668 cells (best p=0.17/0.26).
- **Behavioral-feature selectors (high-vol-entry, position-adding, archetype):** best case (high-vol
  entry) is **INCONCLUSIVE and HYPE-concentrated** (drop-HYPE CI spans 0); archetypes are
  method-scoped negatives or generic-fade.
- **Neutralized selector (coin-day-neut edge, r=+0.61):** the strongest persistence in the study, but
  **91–99% is a non-tradeable within-day benchmark**; the bookable raw leg is a **powered zero (−0.03)**.
- **Consensus / order-burst (Stage H):** a genuine but **underpowered** cohort-specific lean
  (clustered CI [−20,+55], p≈0.13) — the best live lead, not deployable.
- **The persistence that IS real (rank-IC ~0.09, Stage M2) is generic short-horizon reversal:**
  alpha over a costless mechanical fade at the same entries is **+1.00 bp, p=0.44 ≈ 0**.

**Bottom line for the report:** many selectors, one honest OOS conclusion — no performance-based wallet
ranking converts to a copyable net edge; the only robust persistent signal is either non-tradeable
(neutralization benchmark) or non-wallet-specific (mechanical reversal).

---

## FIGURES-TO-MAKE (optional)

1. **Graveyard table-as-figure (recommended, primary).** Render the Arc-3 (Stages A–M4) table as a
   clean small-multiples "tombstone" strip: one row per selector, columns = {selector, what it ranked
   on, OOS statistic, verdict color-chip (dead / artifact / inconclusive / kept)}. Color chips make the
   "all red/grey" story land visually. No new computation — pure re-render of the table above.
2. **Winner's-curse fan (if a supporting quantitative fig is wanted).** In-sample selected mean vs
   held-out mean per selector, showing the collapse (e.g. in-sample "stable" candidates −11 to −48 bp
   held-out; winner's-curse −28.7 bp pooled). Data: `out/eda_winnerscurse.parquet` (per
   `babylon-oos-persistence.md`); READ-ONLY, no re-pricing.
3. **Neutralization decomposition bar (one bar).** top-decile neut +67 bp split into raw +6.1 (tradeable,
   below cost line) vs benchmark +61.1 (untradeable) — the single most persuasive "the big number is a
   mirage" visual. Data already in `out/deployable_deciles.parquet`.
4. **Persistence-vs-fade twin bars (Stage M2-deploy).** decile gross +14 → net +7.1 → alpha-vs-fade
   +1.0 — the "wallet identity adds nothing" story. Data in `out/cohort_M2_deploy` artifacts.

All figures are re-renders of existing parquet outputs — **none require bar-pricing or a tape scan**
(RAM-safe).

---

## GAPS

- **Two data pipelines are pooled in this section.** Arc 1 (`selci_fh`) and Arc 2 (`mlscreen`
  tournament) predate `markout_study` and run on the older `fills_his` / earlier `cand2` extractions;
  Arc 3–4 are the clean-room `markout_study`. The narrative (no selector persists) is consistent across
  all four, but if the report scopes strictly to `markout_study` the Arc-1/Arc-2 rows should be flagged
  as "prior work, same conclusion" rather than same-pipeline evidence.
- **Signal F / G3 (ex-majors and return-on-turnover) were "sole survivors" AWAITING July confirmation**
  as of the wallet-screen verdict. This info-gathering pass did not locate a July-forward confirmation
  result — status is "frozen, unconfirmed," not "persisted." If a July result exists it should be added;
  otherwise state F/G3 as unresolved-forward, not as a persisting selector.
- **Exact per-selector held-out numbers for Arc-1** (individual metric OOS eof per fold) live in
  `scratch_conv/selci_full.jsonl` / `selci_full2.jsonl` and were not re-extracted here (would need a
  read of those files); the table reports the panel-level rank orderings from memory. Verify against the
  jsonl if per-metric fold numbers are wanted in the report.
- **Stage M1 "entry-weighted −0.055" vs "day-weighted +0.16"** is a load-bearing nuance (a naive copier
  who trades every episode gets nothing; the persistence lives only under day-equal-weighting). Worth a
  callout box in the report — it is the cleanest single illustration of "the metric that persists is not
  the metric you can trade."
- **The live/underpowered positives are NOT graveyard entries** and must not be buried by this section
  (over-null gate): Stage H consensus (best lead, CI admits +55), Stage M4 day-capped residual (+5.87,
  underpowered), and the Stage M2 population rank-persistence (real, powered) belong in the "open /
  live" section, cross-referenced from here so the graveyard is not mis-read as "everything is dead."
- **Multiplicity across the whole arc:** ~10,000 hypotheses were run; survivor rate sits AT the ~5%
  noise floor. If the report wants a single multiplicity statement, that is the number to cite (ledger
  header, 2026-07-04 bottom line).
