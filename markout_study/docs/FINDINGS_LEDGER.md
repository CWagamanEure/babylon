# Wallet Copyability — Findings Ledger

**Purpose.** The single, accumulating, report-ready record of what we have *established* (and, honestly, what
we have NOT) in the search for copyable/informed Hyperliquid wallets. **Discipline: at the END of each stage,
before moving on, this ledger is updated** — question, method, calibrated result, caveats, artifacts. Findings
are stated at their true strength per `babylon/CLAUDE.md` (no over-nulling, no over-claiming). Each stage's
detail lives in its notebook/figs; this is the consolidated backbone for the final report.

**Overarching question.** Can we identify wallets whose *future* trading is worth copying — and if so, how?

**📊 All report-ready tables & figures live in `notebooks/report_assets.ipynb`** (consolidated pack: field
markout term structure per coin, top-wallet stats per coin, OOS significance/power, refinement grids,
distributional — every table computed live from `out/*.parquet`, every figure embedded). Rebuild:
`python3 src/make_report_assets.py && jupyter nbconvert --execute --inplace notebooks/report_assets.ipynb`.

**➡️ LATEST (2026-07-05, Stages F–H — the neutralization arc):** (1) Wallet coin-day-neutralized entry edge
persists OOS at **r=+0.61** (confirmed 4 ways) — real skill, but it's a NON-TRADEABLE benchmark; hedged copy P&L
is negative (Stage F). (2) Tape round-trip: the cohort is NOT net-profitable (real thin +2.4bp entry timing run
as 68–76% takers → typical wallet loses; Stage G). (3) **Best live lead:** a consensus/order-burst signal
(follow the cohort *into* dips, exit 4–6h) is **execution-survivable and cohort-specific (not generic crowding),
BTC-reliable ~+8bp — but underpowered (clustered CI spans 0) and small-capacity; suggestive, not deployable**
(Stage H). Net: still NO established deployable copy edge, but a genuine underpowered BTC lead worth a
forward-months powered test. See Stages F/H for detail. The 2026-07-04 bottom line below remains valid for the
performance-ranking legs.

**Bottom line (revised 2026-07-04 after a 4-agent findings+process audit — a deliberate correction of an
over-CARRY, the mirror of the over-null we guard against).** Split the claim by what the evidence actually supports:
- **Performance-based ranking of takers yields NO copyable edge — and we have earned the right to say so, not
  "inconclusive."** Two direct, powered numbers settle it: (i) selecting each wallet on its best in-sample
  horizon returns **−28.7 bp NET out-of-sample** (pooled; BTC −20 / ETH −36 / SOL −46 — `eda_winnerscurse`),
  i.e. past markout is *anti*-predictive per wallet; (ii) train→eval wallet-rank **Spearman ≈ 0** (0.002–0.05,
  sign-flipping across coins, SE≈0.007 — a *tight* null on the load-bearing quantity). Add: the deployable
  (turnover-weighted) median clears its band at exactly the chance rate (5/120), nothing graduates the
  config-selection null (p=0.17/0.26, negative winner stats), and the whole arc ran ~10,000 hypotheses whose
  survivor rate sits AT the ~5% noise floor. For *performance selection specifically*, this is a registered
  negative.
- **The "coherent 24h/small-K positive" is DEMOTED** from "live positive" to *"the residual we could not
  resolve — direction unknown, deployable version at chance."* It is post-hoc (24h = argmax of 12 horizons;
  30m is *also* 5/5 and was ignored), lives only at small-K (K=50 breaks it: ETH→−41), treats non-independent
  coins as independent (effective N<4 → the 5/5 sign-test p≈0.03 becomes ≈0.12–0.25), and lives entirely in the
  uncontrolled descriptive layer. It is a *motivation*, not evidence.
- **The behavioral-feature bet was TESTED (Stage E, pre-registered, OOS) — result: no *general* copyable edge,
  but a real HYPE/SOL-specific one and an unresolved weak residual.** Selecting wallets by TRAIN-only high-vol-entry
  propensity, the held-out neutralized rank-slope is +3.28 bps/σ (CI excludes 0) — but that significance is
  **HYPE-concentrated** (drop-HYPE CI [-0.44,+3.27] spans 0) and **DOF-fragile** (only the coin-month neutralization
  grain clears), and the deployable raw edge (+7.7bp) is **below the ~10bp cost hurdle**. So the pooled majors
  reading is NOT supported (HYPE hump + selection wiggle). BUT — not a clean null either: on SOL/HYPE the deployable
  raw top-quartile markout is large and clears cost (+22 / +31 bp), exactly the coins a high-vol trait should light
  up, and the non-HYPE residual is a *tight-ish zero* (admits ~+3bp/σ), underpowered-not-absent. **Honest verdict:
  performance-ranking is dead; the behavioral feature gives a HYPE/SOL-specific signal, not a general majors edge;
  the one legitimate escalation is a HYPE/SOL-specific, funding-netted, forward-months (12–16) test — not more
  majors-pooling.** Deployment is unresolvable until funding is netted.

---

## Stage A — Baseline OOS persistence of naive rankings  ·  *status: complete*
**Question.** Rank takers by a naive metric (edge / Sharpe / hit-rate / cum-PnL) on a past window, copy the
top-50 — does the cohort beat *random* selection on a future window?
**Method.** Purged/embargoed expanding walk-forward (7 splits, 4 majors + SPX); persistent-random-score
permutation JOINT null; BH-FDR; negative + positive controls for calibration & power.
**Result (calibrated).** **No naive ranking clears the random bar — but INCONCLUSIVE, not "no edge."**
Primary cell `vw_edge@24h` joint-p: BTC 0.09 / SPX 0.15 / HYPE 0.18 / SOL 0.42 / ETH 0.78 (none <0.05);
0 cells survive FDR. **Point estimates lean positive on 4/5 coins** (BTC +31, HYPE +45, SOL +13, SPX +35;
ETH −41 bp). **Power: MDE ≈ 160 bp/entry** — ~10–30× a realistic edge, so the test is *blind by construction*
to realistic effects. "Not significant" here = the naive 30-entry ranker cannot resolve a realistic edge.
**Caveats.** Underpowered; selection-noise-limited at 30-entry depth.
**Artifacts.** `notebooks/persistence_findings.ipynb`, `docs/PERSISTENCE_ARCHITECTURE.md`,
`out/persistence_{verdict,splits,controls}.parquet`.

## Stage B — Reliability-metric sweep  ·  *status: complete*
**Question.** Do *reliability-aware* rankings (t-stat = √n·mean/std; empirical-Bayes shrunk edge) rescue
persistence where raw edge failed?
**Method.** All 12 horizons × 2 floors × reliability metrics; grid-wide permutation null; FDR.
**Result (calibrated).** **No.** Global permutation p = 0.40; 0 FDR survivors. Reliability shrinkage does not
beat raw `vw_edge`. `vw_edge` retains a consistent positive lean peaking ~24–48h.
**Artifacts.** `docs/PERSISTENCE_SWEEP_ARCHITECTURE.md`, `out/sweep_{verdict,global}.parquet`.

## Stage C — Refinement: ew/vw · top-N · rolling · robust rankers · distribution  ·  *status: complete*
**Question.** Attack the baseline from every remaining angle — per-decision(ew) vs per-dollar(vw) scoring,
cohort size K, rolling vs expanding training, outlier-immune rankers (median, 10%-trimmed), and a
distributional dissection of what any surviving lean is made of.
**Method.** 9 rankers × 12 horizons × K∈{10,25,50,100,200} × {expanding,rolling} × {vw,ew} (9,668 cells);
config-selection-corrected graduation (deterministic `mean_folds−std_folds` rule, label-permutation null over
the full metric axis); distributional cohorts vs a *fair pooled* random-cohort band. Code + framing 3-way
audited.
**Result (calibrated) — noise-limited, NOT refuted; a coherent underpowered positive survives at ~24h/small-K:**
- **Nothing graduates** (config-corrected): best config vw p = 0.17, ew p = 0.26; both winner stats negative.
  *Caveat:* the `mean−std` rule structurally selects low-variance 5m cells and **cannot select** the
  high-variance 24h cell — so this did not *test* the 24h candidate.
- **The 24h/small-K lean is directionally coherent across THREE cuts — but all three CONDITION on h=24h, the
  post-hoc-selected peak, so they are one selection viewed thrice, not three confirmations** (audit finding):
  (1) outlier-immune `trim10_edge` positive on 5/5 coins @24h (sign-test p≈0.03 *treating coins as independent*;
  effective N<4 → ≈0.12–0.25), `median` 4/5 — rules out the lucky-trade explanation but not noise; (2) `vw_edge`
  positive on 5/5 coins @24h at K=10/K=25, **diluting to nothing by K=50** (the doc's own `[D-M1]` warns a
  small-K peak is EXPECTED under noise); (3) BTC per-decision cohort median above a pooled random band at 24h —
  **CORRECTED NUMBER:** `refine_dist` `vw_te_median_bps` = **+31.4 (K=50)** / +48.6 (K=10), not the "+13" a
  prior draft cited; and the `te_med_gt_band` flag is internally inconsistent (K=10 +48.6 → False, K=50 +31.4 →
  True) — **the band/flag logic needs a code check before any distributional number appears in the report.**
- **NOT a deployability signal (the cut that would matter for copying):** the turnover-weighted (deployable)
  median is **inside** its band for all 5 coins, and clears at exactly the chance rate (5/120) — at the noise
  floor. The effect is size-blind/per-decision, and 24h is the post-hoc peak horizon.
- Secondary: ew < vw for all 9 rankers in aggregate; rolling < expanding (except SOL); "central vs tail" is
  coin-specific (BTC central; ETH/HYPE tail-driven); loss-tail grows 0%→28% across horizons.
**Caveats.** All within-noise; 24h post-hoc; coins not fully independent; size-blind; descriptive not inferential.
**Artifacts.** `notebooks/persistence_refinement.ipynb`, `docs/PERSISTENCE_REFINE_ARCHITECTURE.md`,
`out/refine_{grid,dist,graduation}.parquet`, `out/figs_refine/` (5 figs).

## Stage D — Cohort forensics (typology + drawdown → feature battery)  ·  *status: Stage 0 + Stage 1 done; Stage 2 (drawdown) next*
**Question.** Who are the top-cohort wallets (trader types), and what causes their severe drawdowns — to
generate testable feature/risk hypotheses for the OOS feature stage.
**Method.** `docs/COHORT_FORENSICS_ARCHITECTURE.md` **v2.1** (two audit rounds: 4-agent swarm on v1, then
Stage-0-correctness + methodology-delta audit): archetype-level typology vs matched controls; drawdown
forensics as a **graded scorecard** (loss-vs-win-vs-neutral · top-recovered-vs-bottom-terminal-censored ·
de-clustered wallet-count+#windows · pre-entry-only) that RANKS candidates for OOS (not a pass/fail filter —
a hard AND would itself be a forensic over-null); tiered feature battery → held-out-wallet OOS test.
**Stage 0 (COMPLETE, 2026-07-04) — position reconstruction.** `build_entries.py`/`mkcommon.taker_entries`
now emit 3 additive columns: **`pos_after`** (true signed net position, from the internal `cum` over all
fills), **`avg_entry_px`** (running open-inventory cost basis, numba scalar recurrence — a cumsum is wrong,
partial reduces rebase), **`fill_vwap`** (execution-price basis of the bar's taker sweep). Audited clean
(independent brute-force + 3k-seq fuzz, 0 mismatches; recurrence hand-check exact). Full 16-shard rebuild:
7,332,013 entries (identical count → existing columns/analysis unchanged), `sign(pos_after)==dir` 100%, 0 NaN.
Unlocks true averaging-down (~26% of long-adds), martingale escalation, inventory-MTM drawdown. Note for
downstream: use `avg_entry_px` (cost basis) for averaging-down/martingale, not `fill_vwap`.

**Stage 1 (COMPLETE, 2026-07-04) — trader TYPOLOGY** (`cohort_forensics.py`, `forensics_figs.py`, code +
methodology audited; `out/forensics_typology.parquet`, `out/figs_forensics/01_typology_K50.png`). Entry-
structure descriptors of the top-K vw_edge@24h cohort vs an **activity+notional-matched** control band +
field, per major; fair test = cohort bootstrap-CI disjoint from control band; **ew-selected cross-check**
(a trait that dies under equal-weight selection was volume-induced); SPX dropped (130 wallets → control
degenerate). Descriptive/hypothesis-generating, NOT findings.
- **Aggregate is real:** 25/45 descriptors outside the matched-control band at K=50 (Poisson P≈2e-11) — the
  top cohort is genuinely structurally different from an activity+notional-matched field, not a multiplicity
  artifact.
- **The one ROBUST trait — enters more in HIGH-VOL regimes** (`highvol_frac` cohort ~0.77 vs field ~0.65):
  CI-disjoint above the control band under **BOTH vw and ew selection on 3/4 coins** (ETH within). Survives
  the volume-selection cross-check → a genuine behavioral signature. Caveats: market-timing trait (coins share
  the return environment → effective N<4); vol regime uses a full-sample-median threshold (descriptive).
- **`notl_cv` (variable position sizing) = a VOLUME-SELECTION ARTIFACT:** looked strongest under vw (4/4
  CI-disjoint) but **vanishes under ew (0/4)** — a textbook demonstration of the cross-check working. NOT
  carried forward as a trait.
- **`add_frac` (adds to positions more) = consistent directional lean, selection-dependent** (ew 4/4 CI-disjoint,
  vw 1/4). Candidate, weaker than highvol.
- **Within noise:** coin concentration, momentum(trend-vs-fade), averaging-down rate, cadence, net-long
  direction (`long_frac` — the earlier "less net-long" read was over-claimed; 0/4 on the fair test, HYPE hump
  leaking; DROPPED).
**Candidate features handed to Stage E (OOS):** high-vol-regime entry propensity (strongest), position-adding
propensity (ew-flavored). `notl_cv` explicitly NOT carried (artifact). Methodological notes for the report:
`outside_ctrl` (point-vs-band) is lenient — the fair test is CI-vs-band; quintile matching is coarse; the
skill/luck + deployability discriminators (conviction, factor-residual, size-elasticity, copyability-at-lag)
are Stage 1b, not yet built.
**Result (Stage 2 pending).** *(drawdown scorecard — record on completion.)*

## Stage E — Feature → held-out-edge analysis  ·  *status: RUN + prosecuted; verdict INCONCLUSIVE, HYPE-driven*
Pre-registered frozen-v2 confirmatory test (`src/stage_e.py`, `docs/STAGE_E_ARCHITECTURE.md`): select wallets by
TRAIN-only high-vol-entry propensity; primary = two-way-clustered rank-slope of held-out coin-month-neutralized
24h markout on the continuous selector.
**Headline (reproduced exactly):** pooled slope **+3.28 bps/σ**, coin-week CI **[+0.36,+6.83]**, wallet CI
**[+1.01,+5.69]** (both exclude 0); placebo spans 0; +10bp positive control recovers. Deployable top-quartile
RAW **+7.7 bp < 10 bp** cost hurdle → the frozen rule's CONFIRM was NOT met on the raw leg; verdict INCONCLUSIVE.

**PROSECUTE + steelman + reconcile (2026-07-04, `src/prosecute_e.py`, `src/prosecute_e_analyze.py`):**
- **DECISIVE — the pooled significance is HYPE-driven.** Drop-HYPE slope **+1.42, CI [-0.44,+3.27] coin-week AND
  [-0.73,+3.98] wallet — spans 0 under BOTH clusterings.** HYPE supplies **63% of the slope numerator** (Szy
  +995k of net +1,575k) on ~20% of the z-variance. Per-coin: BTC +1.94 [+0.03,+3.82] (only individually-sig coin,
  marginal), ETH −1.81, SOL +4.96 (spans), HYPE +11.41 (spans, wide). Leave-one-coin-out: only removing HYPE
  collapses the point estimate; removing ETH (the negative coin) *raises* it to +4.45 [+1.00,+8.84].
- **DOF-sensitivity: significance sits at a favorable corner.** Robust to winsorization (no-winsor +3.52 …
  p95 +2.89, all EXCL0) and to weighting (vw +10.0 EXCL0). **FRAGILE to neutralization grain** — of {raw,
  coin, coin-month, coin-day} only the frozen coin-MONTH excludes 0 (+3.28); raw +2.84, coin +2.62, coin-day
  +1.24 all span 0. Vol-threshold: p50 (frozen) & p80 EXCL0, p70 spans. So the frozen (coin-month, p50, all-coins)
  is one of few cells that clears — the upstream selector/grain/horizon search leaks through.
- **Deployability fails where the slope is cleanest.** BTC top-q RAW = **−0.4 bp** (the only slope-significant
  coin has no tradeable edge); ETH +2.1; deployable edge is entirely SOL (+22.4) & HYPE (+30.9). Pooled +7.7 <
  hurdle; **drop-HYPE pooled +2.3 bp** — nowhere near cost.
- **Funding (no data):** 24h price-markout does NOT contain funding, so funding cannot manufacture the slope;
  but it is an unmodeled ~10–25 bp/24h stream that plausibly correlates with the high-vol selector and can flip
  the sub-hurdle SOL/HYPE deployable numbers either way → deployment unresolvable without it.
- **Multiplicity:** one nominally-p<0.05 pre-registered test, but the selector was chosen from the Stage-D
  battery, 24h is the post-hoc argmax, and neighbors in the DOF cube span 0 — fully consistent with the arc's
  ~5% survivor floor.
- **STEELMAN (what survives):** OOS, non-circular behavioral selector, placebo-clean, positive under both
  clusterings *with* HYPE, 3/4 coins positive point, BTC marginally sig alone; on the two highest-vol coins
  (SOL/HYPE) the deployable RAW markout is large and clears cost (+22/+31 bp > 10/14). A weak non-HYPE residual
  persists (drop-HYPE point +1.42; coin-day-neut drop-HYPE +1.68 EXCL0; p80 drop-HYPE +1.77 EXCL0).
- **RECONCILE — call: (b)-leaning-(c).** The significant *general* copyable-edge reading is NOT supported — it is
  a **HYPE-concentrated effect + selection DOF**; the frozen +3.28 must not be carried as a general majors edge.
  The *non-HYPE* signal is genuinely **INCONCLUSIVE/underpowered** (drop-HYPE CI [-0.44,+3.27] still admits a
  care-about +3 bp/σ — a tight-ish zero, not proven absence), leaning weak-positive. Escalation, if any, is a
  **HYPE(+SOL)-specific, funding-netted forward-month** test — NOT a re-run of the pooled majors slope.
**CODE AUDIT (independent reproduction, 2026-07-04):** every headline number reproduced to the digit (slope,
CIs, n, positive control); the CI-lower-bound>0 is robust across 8 seeds × 3 winsor variants (lo ∈ [+0.20,+0.53],
positive 100%) — the marginal positive is REAL, not a lucky seed, but genuinely marginal. Train/test split clean
(selector/threshold/pool/z all train-only, Feb embargoed), pricing exact, no further NaN-drop bugs. One earlier
bug WAS found & fixed mid-run (polars `.mean()` propagates NaN → coin-month benchmark NaN for 3/4 test months →
76% of entries silently dropped → a spurious "24 coin-weeks / underpowered INCONCLUSIVE"; fixed → 72 coin-weeks /
581k entries). Minor pre-registration-fidelity cleanups flagged, ALL conservative/immaterial (verdict unchanged):
winsor cap is test- not train-derived (train cap → slope +3.35, same CI); MDE computed on the quartile-mean not
the slope (didn't bite — INCONCLUSIVE fired via raw<hurdle); bootstrap is coin-week-only not two-way (the wider,
conservative CI). None inflate the finding.
**Artifacts.** `src/stage_e.py`, `docs/STAGE_E_ARCHITECTURE.md`, `src/prosecute_e.py`, `src/prosecute_e_analyze.py`,
`out/stage_e_verdict.parquet`, `out/prosecute_e_test.parquet`.

## Stage F — Deployable copy-edge from the r≈0.61 coin-day-neut persistence  ·  *status: complete; OVER-CLAIM caught*
**Question.** Ranking wallets by past coin-DAY-neutralized edge predicts future coin-day-neut edge (r≈+0.61,
reproduced +0.617). IF we copy the top-conviction decile, what is the actual OOS edge, and does it clear cost
once we honor clustering AND book it through a REAL hedge?
**Method (`src/deployable_edge.py`, `src/deployable_hedge_check.py`).** TRAIN<Feb / EMBARGO Feb / TEST Mar-Jun.
Rank pooled-majors wallets (n_train≥300, N=1768) by day-clustered coin-day-neut t-stat → deciles. Top-decile OOS
neut & raw markout; wallet- AND coin-week-cluster bootstrap CIs; positive-control MDE; 15-min follower lag; per-coin
COST_BPS; funding sensitivity; **and the decisive test — replace the un-tradeable coin-day-mean benchmark with an
implementable leave-one-out INDEX-BETA hedge** (the P&L a real market-neutral copier books).
**Result (calibrated) — the headline is a benchmark ARTIFACT; NO deployable edge:**
- **Clean monotone dose-response on the neut metric** (deciles 1→10: −40,−20,−7,−1,+9,+0,+11,+21,+29,**+67** bp) and
  top-decile neut = **+67.2 bp, 95%CI [+58,+78]** (wallet & coin-week cluster, EXCLUDES 0), lag-robust (+65), all
  4 coins positive, drop-HYPE +59 [+51,+69]. MDE≈14.6 bp (recovers +5/+10/+20 injections). *Taken alone this looks
  like a spectacular deployable edge — it is not.*
- **DECOMPOSITION: 91% of the +67 is un-tradeable.** neut = raw + (−d·coin_day_mean); top-decile RAW markout is
  only **+6.1 bp** (below the 9.5 bp cost) while **−d·daymean = +61.1 bp**. The cohort is selected for (and
  persistently keeps) a *lean-against-the-daily-drift STYLE*; the coin-day-mean is not a tradeable instrument, so
  that +61 is an accounting subtraction, not P&L.
- **BOOKABLE market-neutral P&L (leave-one-out index-beta hedge) = −7.0 bp, 95%CI [−28.4, +11.4]** (spans 0, leans
  negative); **−16.5 bp NET of cost.** Per-coin bh: BTC +0.2 / SOL +11.3 / ETH −13.7 / **HYPE −31.9** (the +99 neut
  HYPE hump inverts under a real hedge). Sub-period: bh **+14 (Mar-Apr) → −33 (May-Jun)** — sign-flips.
- **Verdict: the r≈0.61 persistence is REAL but is a persistent directional/style regularity, NOT a hedgeable
  alpha.** No implementable market-neutral copy strategy books the +67; the closest real hedge is slightly
  NEGATIVE and net-negative. The copyable raw component (+6 bp) is below cost. This is a textbook OVER-CARRY the
  guard caught: coin-day neutralization is a valid *variance-reduction for skill MEASUREMENT* but its output is
  **not a deployable return** — treating "neutralized edge" as "what a market-neutral copier captures" (the task's
  premise) is false for coin-day grain. **Not deployable.**
**Caveats (symmetry / not over-nulling).** Single epoch; the hedged CI [−28,+11] is not a *tight* zero (MDE on the
hedged leg ≈28 bp > 10 bp care-about → the hedged leg is somewhat underpowered and admits a small +edge, but its
point estimate is negative and net-negative even at the CI upper bound minus cost). Funding unmodeled (would only
worsen a long-biased book). So: no *established* deployable positive; best case (95% upper, gross) ≈ breakeven.
**Artifacts.** `src/deployable_edge.py`, `src/deployable_hedge_check.py`, `out/deployable_deciles.parquet`.

## Stage G — What are these wallets ACTUALLY doing? Tape round-trip reconstruction  ·  *status: complete; 3-agent audited*
**Question.** The neut-persistent cohort has real entry-timing skill (+0.61 OOS) — so "they must be capturing an
edge somehow." Reconstruct their REAL trading from the raw fill tape (not markout inference): are they profitable,
how do they trade, and does entry skill convert to P&L?
**Method (`src/how_they_trade.py`, `src/tape_roundtrip.py`).** Top-decile TRAIN-neut cohort (178 wallets,
`out/cohort_wallets.txt`). (1) markout TERM STRUCTURE + contrarian signature on their entries; (2) full average-cost
position ledger over the raw fill tape (`../scratch_conv/mlscreen/cand2_*.parquet`, signed sz+px), realized+MTM PnL,
holds, taker/maker. 3-agent audit: code (FIFO cross-check), scope/power, steelman-the-skill.
**Result (calibrated) — real thin directional-timing signal, run through an expensive taker style that gives it back:**
- **Fingerprint:** CONTRARIAN (sign(dir)·sign(prior-1h) = −0.38, buy dips/sell rips), ~49-min median holds, **68-76%
  TAKER** (pay spread, not makers), $10B+ gross = high-turnover scalpers. RAW markout PEAKS +4.4bp@4h then DECAYS to
  +1.1@24h (mean-reversion pop); NEUT balloons to +64bp@24h but that is MECHANICAL (buying below day-mean price →
  arithmetically higher fwd return) — do NOT quote +64 as alpha.
- **Not net-profitable (code-audit CONFIRMED, FIFO matches to the cent; PRE-FEE = generous).** Majors realized
  −3.64 bps of vol. Scope-audit correction: **~70% of the $ loss is ONE wallet's −211bp ETH blow-up; ex-outlier the
  cohort is price-BREAKEVEN (−1.1bp, CI [−6.0,+0.6] incl 0).** The DURABLE powered negative is **cross-wallet: only
  40% of wallets profitable, sign-test p=0.013** (holds ex-ETH p=0.029, and in alts). All-coin+funding −3.86bp (alts
  WORSE −6.6bp; funding immaterial −0.05bp). **Fees (~2-4bp, unmodeled) are the decisive cost** tipping the ex-outlier
  price-breakeven to net-negative for the taker style.
- **"Skilled at entering" — final:** opening DIRECTIONAL TIMING real but THIN (+2.4bp mid-drift/1h, +0.61 OOS) — not
  nulled; BUT execution NEGATIVE (fills −0.19bp vs contemporaneous mid — pay spread, don't beat mid); typical wallet
  not net-profitable. A genuine profitable maker or two exist (one +6.3bp/$644k) but are unidentifiable ex-ante and
  don't persist copyably (H1 top-decile PnL → H2 −8.4bp). NOT "talented traders capturing an edge we can't."
**Caveats.** In-sample-inclusive PnL (conservative: selection-window inclusion biases PnL UP, so true OOS ≤ this);
majors + alts scope; fees not modeled (makes it worse). Corrects BOTH an over-claim ("genuinely skilled") and an
over-correction ("they lose money" — really ex-outlier breakeven + a powered typical-wallet negative).
**Artifacts.** `src/how_they_trade.py`, `src/tape_roundtrip.py`, `out/cohort_wallets.txt`.

---

## Stage H — Consensus>=9 copy signal under REAL execution  ·  *status: complete; tape-grounded*
**Question.** The consensus signal (>=9 cohort wallets open same coin+dir within trailing 30min → copy, exit
4-6h) is idealized-net +12.6bp@4h / +15.5bp@6h (mid-to-mid, flat COST_BPS). Does it survive real fills, entry
lag/adverse entry, spread both sides, exit fade, funding, and capacity? **Method.** Re-priced the SAME flagged
TEST events (1270 flagged entries → 140 distinct >30-min-separated bursts) against the raw taker tape
(`cand2_*`, crossed fills): entry = same-dir taker VWAP, exit = opposite-dir taker VWAP, +3.5bp/side fee,
funding joined from `funding.parquet`, no-look-ahead fast entry = cross AFTER the trigger bar closes ("next5m").
**Result (calibrated).**
- **The adverse-fill premise is FALSIFIED for this signal — it is a DIP-BUY, not momentum-chasing.** Price
  moves **−43bp median AGAINST** the cohort's own direction from the 1st wallet to the trigger (frac>0 = 23%).
  The follower crosses *into* a dip, so real round-trip crossing cost is only **~+2.8bp** (BTC +1.2, ETH −3.3,
  SOL +3.6, HYPE +22.9) — far below the flat 9.8bp assumed. Entry slip is ~flat/favorable, not adverse.
- **The +15bp SURVIVES the execution mechanics** because true all-in cost (real spread ~3bp + 7bp fees +
  ~0.3bp funding ≈ 10bp) ≈ the flat COST_BPS the idealized calc already subtracted. Honest no-look-ahead fast
  entry: **NET/event +12.6bp@4h / +15.6bp@6h** (matches idealized); NET/burst +14.5 / +25.6.
- **BUT NOT statistically established, and NOT uniform.** Burst-clustered 95% CI **spans 0** at both horizons
  and all fee levels (4h [−10.9,+39.7]; 6h [−5.6,+58.5]; N_burst=140). Concentrated: **BTC** (1030 ev / 92
  bursts, best capacity) is a modest **+7-11bp**; **SOL** +100-160 but only 10-11 bursts (all-positive, one
  regime); **HYPE** +27/+107 but wildly dispersed (per-ev min −571 / max +739) and its real spread (23bp)
  is the worst; **ETH is NEGATIVE** (−15 to −45). The headline burst number is inflated by the tiny-N SOL/HYPE
  tails — drop-BTC = +28.5/+57.7 on 47 bursts is fragile, not a stronger result.
- **Funding immaterial** (+0.2 to +0.3bp/hold). **Latency:** a 15-min-late follower keeps a positive point
  estimate but loses ~5-9bp (4h NET/burst +8.9, 6h +20.3). **Capacity:** median trigger-bar one-side taker flow
  BTC $4M / ETH $1.45M / HYPE $1.3M / SOL $0.33M → at 1-5% participation ~$40-200k/trade on BTC (edge > impact),
  far less on alts; a small book, not size.
**Verdict.** The +15bp is **NOT a mid-to-mid mirage erased by adverse fills** — the opposite of the feared
mechanism holds (dip-buy → cheap/favorable entry), and real all-in cost ≈ the assumed cost, so net ≈ idealized
under realistic FAST execution. It is a **live, execution-survivable, but underpowered positive** (140 bursts,
CI spans 0), reliable-but-modest on BTC (+~8bp) and noise-dominated on the alts, that degrades under latency.
Suggestive, not deployable-established. **Artifacts.** `src/real_exec_consensus.py`, `out/real_exec_consensus.parquet`.

**4-AGENT RECONCILIATION (2026-07-05) — the strongest live lead in the study, still underpowered.** Code: no
look-ahead leak, fix *strengthened* it, but it counts ENTRIES not distinct wallets (order-burst, min 2 wallets)
and effective N≈106 → cluster-adj t≈0.9. Significance: coin-day-clustered CI **[−20,+55] spans 0**, MDE≈56bp≫
effect → underpowered/INCONCLUSIVE (not null). Placebo (300 activity-matched random 178-wallet cohorts): random
crowds center **−8bp**, real cohort at **87–97th pct (p≈0.13)** → **NOT generic crowding; a real but weak
cohort-specific tilt.** Execution: adverse-fill fear FALSIFIED (dip-buy → favorable fill), net survives ≈
idealized, **BTC-reliable +7–11bp**, alts noise, ETH negative, small capacity, fast-latency. **Net classification:
a live, real, execution-survivable, cohort-specific but UNDERPOWERED positive — suggestive, not established.**
Per anti-ratchet, resolving needs a powered design: pool for more independent bursts + **fresh forward months**
(12–16), BTC-focused. Do NOT deploy on this window; do NOT call it dead either (it survived every kill the
weaker leads did not).

---

## Stage J — Maker/taker contamination of the persistence null  ·  *status: Job 1 done + 3-agent audited (positive RETRACTED/demoted; base-rate correction + maker-exclusion rationale kept); Jobs 2–6 (markout-of-openings archetype decomposition) pending*
**Origin (2026-07-05).** 3-agent read-only audit prompted by the user's economic objection ("high-volume
traders can't persistently trade at a negative edge or they go broke → we must be mis-measuring/mis-pooling").
Audit converged 3/3: **no maker-share filter/column exists anywhere in the ranked universe**; the existing
realized-PnL null is full-ledger (maker+taker mixed), $-vw (one-whale-blown, CI [−73,+10]), and ≥2000-fill
**HFT-only → the mid/low-freq target trader is excluded by construction**; `maker_taker_split.py` had never run
(it OOM-crashed). Design in `docs/STAGE_J_ARCHITECTURE.md`. RAM-safe serial execution (BATCH 500→150, ramguard).
**Question (Job 1).** Split each wallet's realized round-trip PnL into a **clean TAKER-ONLY** avg-cost ledger and
test train→test persistence, **stratified by notional maker-share** — is the pooled ~0 a mixture of a positive
taker-dominant population and a negative maker-heavy one?
**Method.** `src/maker_taker_split.py` (5859 wallets ≥2000 train majors fills; TRAIN<Feb / TEST≥Mar) →
`src/mt_stratified.py`: Spearman(trT_vw, teT_vw) with wallet-bootstrap CI + MDE + top-quartile OOS edge + sign
test, per maker-share bucket. In-memory on the 1MB output.
**Result (calibrated) AFTER a 3-agent audit (code / prosecute-steelman / stats) — the initial "mixture CONFIRMED"
read was OVER-CARRIED and is RETRACTED. Split by what survives:**
- **`closes_taker` is BUGGED for maker-heavy wallets (code audit).** It drops maker fills *before* the avg-cost
  recurrence, so a position opened-maker/closed-taker is mis-booked as a phantom opening short → non-economic
  garbage (the >0.8 bucket's test median is −2,920 bp/round-trip). The >0.8 wallets have a median of only **37
  taker closes** (p25=28, on the floor). **The −0.352 "maker-heavy anti-persistence" is a thin-denominator +
  phantom-round-trip ARTIFACT** — it vanishes as the close-count floor rises (−0.352 → −0.11 @50 → +0.25 @200).
  RETRACT the "maker-heavy wallets anti-persist and mask a pooled positive" claim. (The realized-round-trip
  taker ledger is the wrong instrument; it is coherent only for taker-dominant wallets.)
- **The POSITIVE ("informed takers persist once makers removed") DOES NOT SURVIVE A CHANGE OF ESTIMAND (stats
  audit) → DEMOTED to "an exposure-weighted lean, skill-direction unknown."** The +0.113 (0.2–0.5) exists ONLY on
  the notional-weighted `vw` scalar; **equal-weight: −0.012 (p=0.74); t-stat/consistency: −0.040 (p=0.27)**; and in
  the largest bucket (<0.2, 65% of universe) the sign FLIPS (vw +0.042 vs **eqw −0.058, p=0.007**). Big-gross
  wallets drive it (+0.143 vs +0.082); 10%-whale-trim collapses it to +0.072 (≈ its MDE). Most likely reading:
  **persistent directional EXPOSURE / beta-carry, not repeatable skill** — the classic over-carry the vw estimand
  manufactures. Multiplicity: family-wise permutation P(max|ρ|≥0.113)=0.17 (marginal); it survives raw
  Bonferroni/FDR on its own p but was selected from 4 buckets. Survivorship: the `nteT≥20` filter drops ~40% and
  keeps train-winners (kept +21bp vs dropped −8bp train-median) → can manufacture positive train→test rank corr.
- **What IS robust / trustworthy:** (a) pooled taker-only Spearman **−0.007 [−0.047,+0.031], MDE 0.034 — a
  *powered* near-zero** (on the vw realized-round-trip estimand): removing makers reveals ≈zero, not a positive.
  (b) The **<0.2 pure-taker vw Spearman +0.042 is floor-STABLE** (+0.02…+0.045 across floors 20→400) — a genuinely
  robust but *tiny* and underpowered vw-lean, top-q deployable edge ≈0 (median −3bp). (c) From the CORRECT full
  ledger (`split_pnl`), high-maker wallets' **taker-closing legs lose (−56bp, 20% OOS-positive)** — real
  adverse-selection churn that justifies EXCLUDING maker-heavy wallets as a design choice (not a persistence claim).
- **Symmetry / not over-nulling:** the eqw null is only p=0.74 (CI admits +0.06), so this does NOT *prove* absence
  of taker skill — it shows the realized-round-trip vw instrument doesn't demonstrate it. The sound estimand (24h
  markout of taker OPENINGS, EQUAL-WEIGHT / coin-day-neutralized) was never what this Job measured.
**Net verdict.** Job 1 corrects the base rate (full −0.102 → taker-only −0.007) and cleanly justifies excluding
maker-heavy wallets, but produces **NO established positive** — the apparent one is exposure-weighted and
estimand-fragile. **Lesson for the build: abandon the realized-round-trip taker ledger; run the archetype
decomposition on the 24h-markout-of-openings estimand, ranked EQUAL-WEIGHT (or t-stat), coin-day-neutralized for
power, raw for deployability, with per-coin clustered CIs** (Jobs 2–6). Honest prior: real chance of INCONCLUSIVE.
**Artifacts.** `src/maker_taker_split.py`, `src/mt_stratified.py`, `out/maker_taker_split.parquet`,
`docs/STAGE_J_ARCHITECTURE.md`, `out/maker_taker_split.log`.

---

## Stage K — Powered test of the isolated mid-freq copyable-taker cohort  ·  *status: complete; 3 design-audits + 3 verdict-audits (code/over-null-gate/steelman)*
**Origin (2026-07-05).** User's frame: isolate large-N taker wallets with 1h–24h holds, characterize them, and
test whether they have positive copyable markout — at the RIGHT horizon and the HONEST (equal-weight) way.
Arch in `docs/STAGE_K_ARCHITECTURE.md`; design-audited (stats/feasibility/adversarial) BEFORE build → reframed
from confirmatory to **exploratory + power-scoping** (this window's pre-registration is spent; deployable leg
underpowered; TEST is a −10.85% BTC DOWN window; regime obs OK: TRAIN 40B/58Be/80C, TEST 38B/41Be/43C).
**Cohort (frozen, outcome-independent, `out/cohort_K.txt`).** taker_share≥0.70 AND median hold∈[1h,24h] AND
n_train≥200 decisions → **1,694 wallets** (99% taker, median hold 2.5h, median 289 decisions). Genuinely the
mid-freq copyable takers. Jobs B/C/D: `cohort_K_define.py` → `cohort_K_price.py` (812,616 cohort entries priced
at 1/2/4/8/24h, raw + coin-month drift-strip 'neut' + BTC-7d regime) → `cohort_K_analyze.py`.
**Result (calibrated, both gates) — NO aggregate copyable edge (EARNED powered null), but a real small
reversal-STYLE residual that is most likely generic, not wallet alpha:**
- **Term structure, equal-weight (honest skill estimand), TEST:** 1h −0.2 / 2h −0.1 / **4h +0.5 [−0.8,+1.9]** /
  8h −1.5 / 24h −4.3. Drift-strip 4h **+0.3 [−1.0,+1.6]**. MDE ≈ **1–2 bp** at 1–8h. The 24h −9.5(train)/−4.3(test)
  is POST-EXIT DRIFT (they hold ~2.5h) — the horizon fix mattered but revealed FLAT, not positive.
- **The null is EARNED, not a mislabel (over-null gate cleared):** injected +10 bp positive control recovers
  **+10.31 [+8.93,+11.66]** (100%) / **+2.79 [+1.41,+4.18]** (25%, excl 0) → pipeline CAN see a care-about edge;
  pooled 4h CI excludes +10 bp. Code-audited clean (markout recomputes to 0.0 diff; NaN-rate ~0%; drift-strip
  differs from raw by only 0.1–1.3 bp so cannot hide an edge). Outcome-independent train-top-quartile → OOS
  −0.17 [−3.2,+2.8] (no selectable skilled minority persists).
- **SURFACED per over-null symmetry (do NOT bury):** (a) per-coin 4h neut TEST **ETH +3.1 [+0.25,+6.0], SOL +5.3
  [+1.65,+9.1]** CI-exclude-0 (BTC −1.0) — the recurring SOL/HYPE-specific residual. (b) **Trading STYLE predicts
  OOS markout:** train regime-tilt (momentum vs mean-reversion, outcome-independent: corr w/ train edge +0.008)
  vs OOS neut_4h corr **−0.138, p≈8e-6** (partial-out-train-edge unchanged); mean-reversion sub-cohort (544 w)
  OOS neut_4h **+3.0 bp [+0.4,+5.9]** (pooled +2.87 [+1.12,+4.61]), all 4 coins +, both halves +, strengthens in
  CHOP to +6.2 [+2.4,+10.0]; momentum tail **−5.9 [−9.6,−2.1]** (only cell surviving BH-FDR q=0.10 / 15 cells).
- **But NOT over-carried as wallet alpha (over-carry gate):** the style effect is **almost certainly the generic
  short-horizon REVERSAL anomaly**, not skill — it's a STYLE not a performance trait, mechanism is textbook 4h
  mean-reversion, strongest in CHOP (where a mechanical fade pays), so a "fade the recent move" rule captures it
  WITHOUT copying any wallet. And it is **+3 bp gross < ~5 bp round-trip cost → net-negative** (only the CHOP +6
  cell would clear). "Generic vs cohort-specific" is UNRESOLVED (needs a field/random-contrarian placebo on the
  tape; prior strongly favors generic). "Only generic momentum" was softened to "directional/beta-consistent".
**Verdict.** For the user's goal (copyable INFORMED traders): **no** — the isolated cohort's aggregate markout is
a powered zero at their holding horizon, and the only structure is a small, net-negative, most-likely-generic
short-horizon reversal effect these wallets' styles align with or against — not wallet-selection alpha. This is a
report-ready characterization, not underpowered limbo. **Decisive open test (optional, net-negative regardless):**
field placebo — does a random/mechanical contrarian cohort earn the same +3 bp? If yes → generic reversal, close.
**Artifacts.** `src/cohort_K_{define,price,analyze}.py`, `out/cohort_K.txt`, `out/cohort_K_features.parquet`,
`out/cohort_K_entries.parquet`, `docs/STAGE_K_ARCHITECTURE.md`, `notebooks/hold_feasibility.ipynb`.

---

## Stage L — Trader typology of the frozen cohort_K (WHO are they; does any archetype carry edge?)  ·  *complete; 3 design-audits + code-audit + steelman/prosecute*
**Origin (2026-07-05).** User: after removing the non-informed types (TWAP, vaults, hedgers), do the remaining
top-volume traders have edge? Decompose the 1,694-wallet cohort into archetypes (outcome-independent, TRAIN-only)
and read each one's markout separately. Arch `docs/STAGE_L_ARCHITECTURE.md`; code `cohort_K_{vault,archfeat,
classify,arch_markout}.py`; artifact `out/cohort_K_arch_markout.parquet`.
**Classification (ground-truth + behavior, no performance):** HL API `userRole` (17 VAULT, 27 subAccount) +
TRAIN-only features (funding-capture & holds from a cohort-only tape ledger; cadence/size/hhi/net-long/regime-tilt
from entries). Sizes: VAULT 17, TWAP 151, HEDGER 19, DIRECTIONAL 587 (mom 264 / meanrev 265), MIXED 920.
**Result (equal-weight TEST neut_4h, k>=10 floor, wallet-boot CI; mechanical-fade placebo = generic-reversal
benchmark = +2.51bp):**
- VAULT / HEDGER: **INCONCLUSIVE (blind, <20 test wallets)** — too few taker-active vaults/hedgers to resolve;
  NOT "no edge" (correctly not nulled). [answers the user's "don't just delete vaults" — some are skilled leaders.]
- TWAP −1.65 [−5.7,+2.6]: **EXPECTED-ZERO** (execution algos ~0 by design). DIRECTIONAL −0.25 [−2.7,+2.3],
  MIXED +0.84 [−0.9,+2.8], DIR-mom −1.66 [−5.1,+1.8]: **METHOD-SCOPED NEGATIVE** (CI upper < +3bp → no copyable
  positive edge; +10bp injection recovers → not blind).
- **DIR-mrev +2.15 [−1.8,+5.8]: "reproduces generic reversal, no wallet edge."** The decisive kill: a mechanical
  fade priced at the wallets' OWN entry times earns **+9.54 [+5.1,+13.4]**; wallet-minus-fade = **−7.4 [−11.8,−3.1]**
  (CI excl 0); only 35% beat their own mechanical benchmark. The mean-reversion "edge" is generic short-horizon
  reversal captured BETTER by a robot. Per-coin SOL +13.5 / ETH +7.4 are a **coin-level residual present even in
  execution-only TWAPs (SOL +6.6)** — a coin-month-neut artifact + small-K, NOT archetype skill (this also
  deflates the Stage-K ETH/SOL per-coin residual). Nothing survives BH-FDR (q=0.645).
**Verdict.** After removing TWAP/vaults/hedgers, the remaining top-VOLUME (not top-PnL) directional traders'
AVERAGE is a powered zero, and the only structure is generic reversal a mechanical rule captures better. Both
gates cleared: no positive over-carried, no negative over-nulled; the fair (entry-matched) placebo made the
negative STRONGER. **Not** a claim informed traders don't exist — a skilled minority is diluted in the
activity-selected average and not separable without winner's curse (rank on past PnL) or survivorship (drop the
blowups). Answers "who": mostly directional-but-unskilled + execution algos + a mixed tail + slow bleeders.

## Stage M — Two-stage OOS copyable-edge test: DESIGN + power-gate NEGATIVE  ·  *M0 gate run; full harness NOT built (blind)*
**Origin (2026-07-05).** User (w/ a ChatGPT-proposed protocol) asked for the rigorous test to prove a wallet has
copyable mid/low-freq markout edge. Designed it (`docs/STAGE_M_ARCHITECTURE.md`), 3-agent design-audited, ran the
mandatory §7 power pre-check (`src/cohort_M_power.py`).
**The test (frozen design, for when forward data accrues):** unit = decision EPISODES (not fills); outcome = net
copyable ALPHA over a mechanical benchmark (H0: μ_i ≤ benchmark, one-sided) — cost cancels in the difference for
spread+fee (valuable), impact doesn't; horizon = wallet's own median hold (no argmax); chronological split;
inference = joint day-block bootstrap → Hansen SPA omnibus then Romano–Wolf stepdown max-t; benchmark = worst-case
over {fade, momentum} priced per-coin at H, and must be a DEPLOYABLE (net-positive) alternative else it over-nulls
(don't subtract a net-negative fade's gross); N_effective = distinct DAYS not episodes.
**Power-gate result (EARNED method-scoped NEGATIVE — blind, not "no edge"):** on cohort_K × 122-day TEST window,
the per-wallet SPA/RW test **cannot resolve a 10–25bp copyable edge**. Median wallet: 73 entries / 29 days.
Variance reduction: the direction-matched **market residual** cuts per-entry σ 145→95bp (−34%; the fade INCREASES
σ (ρ<0) and coin-month drift cuts ~0 — F1). Real correlation-aware max-t hurdle = 4.78; **median MDE_RW = 33bp**
(> care-about). The apparent "222 powered wallets" is a **BTC-degeneracy artifact** (β_BTC=1 → market residual ≡ 0
→ spuriously tiny SE; those wallets are 89% BTC, day-SD 16.6 vs 51.7). A representative +20bp injection does NOT
survive the hurdle. Widening the window is √-scaling, negligible vs the multiplicity penalty. **Do NOT build the
SPA/RW survivor hunt** — it would be a blind instrument whose "no survivors" is by-construction (over-null trap).
**Path forward:** the pooled/archetype copyable question is already answered (Stage L: nothing beats the fade);
the only lever that adds the independent-DAY count the max-t hurdle needs is **forward paper-accrual** (copy
episodes live, months 12+). Register the frozen Stage-M design and run it on forward data.

## Stage M1 — Day-capped copy test: is the day-weighted persistence tradable?  ·  *complete; 3 independent Opus audits → reconcile → patch → exact rerun → robustness battery*
**Origin (2026-07-05).** The one lens that showed a positive in the whole arc: **day-weighted** (equal-capital-per-
wallet-day) train→test rank-IC = **+0.16, p=0.0001**, robust to drop-HYPE/SOL (+0.156) and within-BTC (+0.144), and
the coin-mix confound is ruled out (corr(train HYPE/SOL share, test mean)=+0.02 n.s.). NOTE the aggregation split:
day-weighted +0.16 vs **entry-weighted −0.055** (what a naive per-episode copier earns) — a copier who trades every
episode captures nothing; the persistence lives only under day-equal-weighting (wallets over-trade their worse days).
**The decisive test (`src/cohort_M1_daycap.py`, pre-registered, motivated by prior data inspection → not virgin):**
fixed capital per wallet-day (day = mean episode return), 4h frozen exit, next-bar-close entry, per-coin cost; rank
TRAIN by shrunk daily alpha-over-mechanical-fade; freeze top-20; judge untouched TEST with day-block bootstrap +
single-step max-t RW. **Family A (copyability): E[net copied]>0. Family B (incremental): E[copied−fade]>0. Reported
SEPARATELY, not merged.**
**Audit (3 independent Opus agents: statistical / trading-economic / data-integrity) → NO fatal defects.** Confirmed
correct: chronological split + 1-mo embargo (no wallet-day straddles), train-only rank/shrink, cost scaling EXACT (one
round-trip per wallet-day, cancels in B → B is cost-invariant), signs/lookahead clean, fade identical & non-degenerate
for BTC, joint day-block bootstrap, max-t recentering. **Two verified bugs PATCHED:** (1) `te_nd≥15` sat in the
*selection* filter (test-side info) → moved to train-only freeze + eval-time attrition; (2) top-day-share used a signed
sum (the reported "58% concentration") → abs → **actually 4%** (the fragility flag was a formula bug).
**Corrected exact-rerun result (before→after the patch):** Family A +6.9 (p=0.08) → **+3.75 bp [−7.6,+15.3] p=0.26**;
Family B "+7.9 beats fade" (p=0.15) → **+1.54 EW / −1.95 pooled bp, p=0.44–0.63, 0/12 RW** — the fade-beating was
**largely a selection-leak artifact**; done clean there is **no incremental edge over the mechanical fade** (sign-
unstable to weighting). 12/20 wallets evaluable (8 attrition = insufficient test coverage, incl. one wallet at −131bp
on a *single* test day).
**Full battery + wallet-influence (`src/cohort_M1_battery.py`, code-audited: 1 material fix — day-cuts on the [5] EW/pooled
estimators not an episode-weighted third one): **the basket conclusion depends on <=2 wallets** — removing the top-2
positive alpha contributors takes Family B +1.54 -> **−7.10** (and A +3.75 -> −0.96); one THIN wallet 0x6bf6c46b (20 test
days, day-SD 215bp, CI [−15,+172]) drives most of the positive. **8/20 attrition** incl. **4 of the top-10 train ranks
with ZERO test days** (the best train wallets went silent). Within-top-20 rank did NOT persist (ranks 1/2/7 are among the
worst in test). Winsor (1/99 pct): A +3.44 / B +2.27 (tails not driving it). B cost-cancellation confirmed as an identity
(fee+spread cancel on same coin/day; IMPACT does not, unmodeled). **DECISION MEMO verdict = (3) inconclusive but sufficient
to justify a FROZEN forward test, LOW prior:** not proof of edge (B~0, <=2-wallet-dependent, 0/12 RW), not proof of no edge
(CIs ±11-18bp, population rho +0.16 real). Forward spec frozen (wallet list, <15-day attrition/no-replace, next-bar entry,
4h exit, wallet-day cap, both cost tables, matched fade, EW basket, day-block+RW, stop at CI half-width<=10bp or 6mo).
Primary forward quantity = incremental wallet value = day-capped copy return − matched fade return. Carry-forward effect
sizes: copyability ~+0.2bp net (realistic cost), incremental-over-fade ~+0.5bp, both CIs span 0.
Robustness battery (`src/cohort_M1_robust.py`, all pre-specified):** under the study's **realistic cost (8/8/10/14)**
Family A collapses to **+0.20 bp [−11.3,+11.7], p=0.50** (the +3.75 rode the optimistic 5/5/8/8 table). Genuine fragility
is **temporal**: monthly A net −0.8/+10.3/−19.0/+0.0, B alpha −7.5/+19.3/+0.8/−11.6 — **sign flips every month**;
cumulative path swings around zero; drop-best-day B −1.4→−3.1; LOO∈[−3.1,+1.1]. Token lean = ETH/HYPE only (top-token
0.37), negative elsewhere. Top-day 4% (NOT day-concentrated).
**VERDICT (3) — persistence exists statistically but is NOT economically tradable after costs, on this window.** BOTH
gates honored: the **+0.16 population day-weighted persistence is REAL and PRESERVED** (not nulled — it is the load-
bearing positive, tight & powered on the population rank-IC); the **frozen top-20 basket is ~0 net (realistic cost),
does not beat the fade, and is month-unstable** (not over-carried). The basket test is *underpowered* (CIs ±11–17bp,
0/12 RW) → inconclusive-leaning-zero on 122 days, NOT a tight null. **Forward paper-accrual** is the only lever that
adds independent days; expected forward EV of *this* basket is low → the higher-value move is a variance-reduced /
larger-N redesign of the persistence signal. Artifacts: `out/cohort_M1_{ep,top}.parquet`, `out/cohort_M1_frozen.txt`.

## Stage M2 — RECURRENCE across rolling folds: the broad persistence hypothesis is POWERED-POSITIVE  ·  *the right diagnostic (user-directed); the top-20 cutoff was blind, the recurrence under it is real*
**Origin (2026-07-05).** User: "check whether the problem is the exact top-20 cutoff" — run repeated chronological folds,
measure how often each wallet recurs in the TOP DECILE across independent periods, evaluate the whole decile / a
shrinkage basket, not just top-20. Built `src/cohort_M2_recurrence.py` (RAM-light, neut_{4,8,24}h already in parquet,
NO bars): monthly folds over all 11 months, day-weighted shrunk within-month ranking, top-decile flag.
**⚠️ BUG-CORRECTED (audit round 3, 2026-07-05).** The James-Stein `shrink()` collapsed to a constant (tau2=0) in 4/11
months, flagging 100% of wallets "top-decile" those months and inflating the recurrence/transition counts ~10-22×. Fixed
(fall back to raw m4 rank when tau2<=0) and re-run. **Corrected RESULT — persistence REAL but WEAKER than first reported;
the discrete-transition overclaim removed:** (1) adjacent-fold rank-IC 4h +0.081 [+0.054,+0.108] 9/10, **8h +0.093
[+0.061,+0.126] 10/10 folds sign-p=0.002**, 24h +0.085 [+0.041,+0.134] 9/10 — all CI-excl-0, UNAFFECTED by the bug (the
IC/forward-decile auto-dropped the collapsed months) → these are the load-bearing survivors; (2) **top-decile forward edge
+5.72 vs field +1.24 = +4.48 bp [+2.17,+7.54] 9/10 folds** (survives, significant); (3) transition P(top|top)=**0.109 vs
0.10 = ×1.09, p=0.22 — NOT significant** (was the bug-inflated "3.2×"; the discrete top→top persistence essentially vanishes
once corrected, + a wallet-clustering caveat on even that p); (4) recurrence vs luck null: **≥4mo 9 vs 5 (p=0.066), ≥3mo 48
vs 35 (p=0.017), ≥2mo 204 vs 184 (p=0.059)** — modest, only ≥3mo clears (was 403/686/1107); (5) repeat-ranker basket forward
+6.15 vs field +2.47 = +3.69 [−4.53,+10.41] 6/8 (not significant). **Net: rank persistence is a small, real, cross-fold-
consistent effect (IC ~0.09, forward decile +4.5bp gross-drift-stripped); the strong recurrence/transition magnitudes were
a shrinkage artifact.** **Independently corroborated by audit-agent #10:**
the persistence is a slow-info TERM STRUCTURE peaking at **8h (+0.219 [+0.154,+0.282])**, monotone 1h->8h, robust to
drop-HYPE/SOL and BTC-only, stronger with reliability-weighting -> 4h/equal-weight was mildly conservative.
**BOTH GATES: over-null VINDICATED** — the broad hypothesis "some wallet rankings predict future performance" is
CONFIRMED & POWERED; the frozen top-20 failing (Stage M1) was a blind underpowered instrument (agents #13 MDE~85bp,
#15 basket blind-by-construction), NOT evidence of no persistence. **over-CARRY caveat:** this is GROSS coin-month-neut
markout, NOT net-of-cost and NOT vs the mechanical fade; a costless robot fade earns ~+9.5bp at these same entry times
(Stage L) so much of it is generic short-horizon reversal. So persistent-ranking != wallet-specific-skill != deployable
YET. **DECISIVE NEXT TEST:** does the recurrence-selected (repeat top-decile) cohort's forward edge SURVIVE the mechanical
fade, net of realistic ~5-6bp cost (agent #6), at 8h reliability-weighted? yes -> real deployable wallet edge; no ->
"copy the setup not the wallet" (persistent reversal-style proxy). Powered design (agents #10/#15): pool the whole
cross-section (rank-weighted portfolio), center 8h, reliability-weight, over-select 40-60, add a recency/liveness gate
(agent #12: 2 top-10 M1 wallets died pre-selection). Artifact: `src/cohort_M2_recurrence.py`.
**Corroboration — audit #3 (steelman) built the day-capped DECILE instrument (not top-20) and got the strongest positive
in the arc:** decile L-S day-block **+14.37 [+8.15,+20.12] p<1e-4**, top-decile long-only **+9.95 [+5.75,+14.26]**,
survives on RAW + within-BTC (+7.26 [+2.83,+11.47]), positive 5/5 test months. IC t=5.1 (0.16 is strong by equity-quant
standards). The top-20 "month-unstable / ~0" was an underpowered-instrument artifact; the population signal is monthly-STABLE.**

## Stage M2 DEPLOYABILITY GATE — the persistence is TRIGGERED short-horizon reversal; incremental wallet skill NOT demonstrated  ·  *`src/cohort_M2_deploy.py`; decile day-capped, net-of-cost + vs mechanical fade at 8h/4h*
> **Audit round-3 reframes (do not read as tight nulls):** (a) "GENERIC" → "TRIGGERED" — M3 showed the UNCONDITIONAL fade LOSES net (C −7.0) and the feature-matched placebo FAILS (D −5.1), so the reversal needs a *trigger*, it is not free everywhere; the open question is whether wallet activity is a *uniquely useful* trigger. (b) The `tend>=8` eligibility here is a test-activity selection LEAK (fixed to train-only in M3/M4, 99→170 wallets); it is NON-FATAL because alpha is differenced at identical entries (selection cancels) and empirically the leak DEFLATED the wallet gap. (c) "alpha vs fade +1.00 p=0.44 ≈0" and "NOT SUPPORTED" = **no incremental skill DEMONSTRATED**, NOT a proven zero (MDE~12bp ≈ care-about; CI admits +13.7bp). Carry as INCONCLUSIVE-on-the-increment + a strong descriptive gross≈fade, not a negative.
**The decisive test (does the powered persistence survive cost AND the fade):** rank TRAIN day-weighted GROSS wallet
markout, freeze top decile (99 wallets), judge TEST day-capped, day-block bootstrap. Wallet & fade both next-bar-close
entry so cost cancels in alpha. **Result @8h:** top-decile GROSS long-only **+13.99 [+5.38,+22.81] p=0.0003** (persistence
REAL & powered, re-confirmed); NET realistic cost (~6-9bp) **+7.09 [−1.94,+15.83] p=0.062** (marginal); NET campaign cost
+4.19 [−4.52,+12.92] p=0.18; **ALPHA vs mechanical fade +1.00 [−10.75,+13.66] p=0.44** (≈ZERO). @4h: gross +10.0 p<1e-4,
net +3.1 p=0.12, **alpha vs fade +1.29 p=0.39.** **VERDICT (both gates): the broad hypothesis "wallet rankings predict
future performance" is CONFIRMED & POWERED (over-null vindicated) — BUT it is GENERIC SHORT-HORIZON REVERSAL, not wallet-
specific skill (over-carry respected): the decile's entire +14bp gross is captured by a costless mechanical contrarian at
the SAME entries; incremental alpha over fade is +1.00bp p=0.44.** Wallet identity adds ~nothing over the mechanical setup.
Caveat (not a TIGHT zero): the alpha CI is wide (±12bp, variance inflated by differencing vs the ρ<0 fade), so a SMALL
wallet increment isn't excluded — but gross≈fade+~0 makes generic-reversal the strong read. Confirmed by audit #5 (no coin-
conditional wallet edge: per-coin positives are coin-level drift/beta shared by train-BOTTOM wallets, cross-coin differential
spans 0 MDE~3.8bp). **DEPLOYABLE OBJECT = the mechanical 4-8h reversal setup on majors (~+9-14bp gross, ~+4-7bp net), NOT
wallet-copying.** The mechanical fade is the live unprosecuted positive (audit #14) and deserves its own full gauntlet
(standalone net/funding/impact + own OOS/forward; single-epoch & post-hoc here). **Wallet-copy-as-skill: NOT SUPPORTED on
this data — persistent ranking != incremental skill.** Artifacts: `src/cohort_M2_{recurrence,deploy}.py`.

### Audit corrections owed to the ledger (15-agent adversarial pass, 2026-07-05) — apply on next edit
- **Stage L DIR-mrev:** relabel "generic reversal, no wallet edge" -> **INCONCLUSIVE** (raw +2.15 [−1.76,+5.81] admits +3bp, MDE 5.49>care, 4/4 coins +); the −7.4 wallet-minus-fade is entry-weighted (flips to ~0 under day-weight, M1) and exists only as ledger prose, not reproducible in committed code (agents #9,#14).
- **Stage M0:** "method-scoped NEGATIVE" -> "blind-on-this-window / edge INCONCLUSIVE" (it is a power verdict; the word invites "no edge") (agent #14).
- **Stage M1 "+0.16 REAL, tight & powered":** qualify as **single-weighting (day-weighted; entry-weighted is −0.055), not multiplicity-adjusted across weighting schemes, not tradable** (agent #14 over-carry). Still real (within-BTC +0.144, drop-HYPE/SOL robust) but drop unqualified "tight & powered."
- **Cost:** realistic HL round-trip ~5-6bp (fee 3.5-5 + half-spread; scheduled 4h exit can rest maker), NOT 8-14bp; carry copyability point at ~+3.7-4.7bp with campaign as a stress case, not the reverse (agent #6). Copyability still underpowered at ALL costs incl. 0 (CI ±11.5bp) — cost is not what nulls it.
- **Unprosecuted positive:** the mechanical fade itself earns ~+9.5bp gross [+5.1,+13.4] at cohort entry times (~+4.5 net) — a live short-horizon-reversal edge the arc only ever used as a benchmark; register it, don't drop it (agent #14).
- **Pricing:** `neut` coin-DAY strip can null directional alpha (use coin-MONTH, which we do); winsor p99 mildly biases high-edge wallets' means down -> report medians too (agent #11). Stage-L DIRECTIONAL/MIXED/DIR-mom negatives still need a per-coin sign test (G3) before they're clean (agent #14).

## Stage M3 — is persistent-wallet ACTIVITY a useful trigger for the fade, or does the fade work equally without wallets?  ·  *`src/cohort_M3_trigger.py`; frozen M2 choices; code-audited (2 material B-D fixes applied)*
**Design (user-specified, frozen):** 4 strategies on TEST, 8h/next-bar-entry/coin-day-capped/realistic-cost, joint day-block
bootstrap. A=wallet direction at top-decile (99 frozen) wallet events; B=mechanical fade at the SAME timestamps; C=fade at
ALL bars (no wallet info); D=fade at NON-wallet timestamps matched on coin×month×tod×tret-quintile×vol-tertile (same N, 20
draws). Code-audit fixed 2 material B-D biases: matched candidate placed on the EVENT coin-day (preserves pairs) + tret
quintiles + report the |tret| balance. **Results (net bp/coin-day):** A +3.02 [−4.1,+10.2] p=0.20; B +5.53 [−5.6,+16.7]
p=0.15; **C −7.00 [−16.4,+2.5] p=0.08** (fade run EVERYWHERE LOSES money net); D −5.12 [−9.0,−1.3] p=0.003.
**Comparisons:** (1) **A−B = −2.51 [−11.9,+7.0] p=0.58 → wallet DIRECTION adds no info** (confirms M2). (2 CENTRAL) **B−D
disagrees by aggregation: day-capped +10.64 [+0.3,+21.0] p=0.044 vs episode-level matched-pairs (16704, cleanest) +4.44
[−8.4,+17.5] p=0.47** — and matching left a residual confound (**wallet events sit on ~13% larger trailing moves, 195 vs
172bp → bigger mechanical reversals**), inflating both. (3) **B−C = +12.53 [+5.8,+19.2] p<0.001** (wallet activity beats
blind fading strongly). B leave-one-wallet-out range 1.68bp → NOT 1-wallet-driven. By coin SOL B +13.7/ETH +8.0/BTC +4.2/
HYPE −3.8; by month positive 3/4 (May −11 all strats). Capacity: 34 events/coin-day, ~11x overlapping 8h holds, high turnover.
**VERDICT (4) — INCONCLUSIVE: the wallet-triggered vs matched-control difference (B−D) is underpowered & confounded** (clean
episode-pairs n.s. p=0.47; day-capped p=0.044 but weighting-dependent + |tret| imbalance). **Firm riders:** wallet DIRECTION
adds nothing (not verdict 1); the standalone unconditional fade is NOT the complete signal — it LOSES money net run everywhere
(C −7.0), so not verdict 3 either. The feature-matched placebo D DOES fail (−5.1), leaning toward "activity is a real trigger"
(verdict 2) but not confirmable at the episode level. **CORRECTS the M2 framing** that "the mechanical fade is the deployable
candidate" — the fade needs a trigger (loses money unconditionally); whether the trigger must be wallet-specific is unresolved.
**Clean settle (a DIFFERENT frozen spec, not a tweak): pre-registered continuous-|tret| control** — regress fade return on
trailing-move magnitude, test the wallet-event residual. Artifact: `src/cohort_M3_trigger.py`.
**M3 LEAK CORRECTION (audit round 2):** M3 (and M2-deploy) re-derived the wallet set inline with `tend>=8` (test-activity)
in selection AND fitted the matched-control quintile/tertile boundaries on TEST bars — two test leaks. Fixed to TRAIN-ONLY
selection (170-wallet top-decile, 44 attrition no-replacement) + TRAIN-fitted frozen bucket boundaries. Before->after: B−D
daycap +10.64 p=0.044 -> +12.35 [+2.2,+23.1] p=0.014; B−D episode +4.44 p=0.47 -> +6.61 [−5.4,+18.8] p=0.28; A−B −2.5 -> −3.3
(n.s.); B−C +12.5 -> +12.9 p<0.001; |tret| imbalance persists (events 195 vs matched 174bp). Leaks were mildly DEFLATING B−D;
qualitative verdict (4) unchanged.

## Stage M4 — frozen continuous-control residual: no residual timing skill ESTABLISHED; the window is BLIND below ~11-16bp → the +5.87 is a live underpowered positive, not a null  ·  *`src/cohort_M4_residual.py`; resolves the M3 |tret| confound*
**Design (frozen, leak-checked):** fit E[mechanical-fade 8h return | state] via OLS on 172,558 TRAIN NON-wallet bars, continuous
controls = signed trailing-8h return, |trailing move|, vol, coin dummies + coin×|tret| slopes, time-of-day (sin/cos); FREEZE;
apply to 18,380 TEST top-decile (TRAIN-only) wallet events; residual = realized fade − predicted fade. PRIMARY = day-capped per
coin-day; SECONDARY = per-event; joint day-block bootstrap. H1: E[day-capped residual] > 0.
**Result:** mean realized fade +7.44 vs **predicted +8.74** (observable state OVER-explains the event fade advantage). **PRIMARY
day-capped +5.87 bp [−5.54,+17.66] p=0.15** (positive, NOT significant; ETH +11.4/SOL +12.0-driven, HYPE −4.2/BTC +4.4; May −7.5);
**SECONDARY per-event −1.30 bp [−15.6,+13.0] p=0.57** (~zero). **POSITIVE-CONTROL MDE (added audit r3):** bootstrap SE=5.81 on
122 test coin-days → **MDE(95% CI excl 0) ~11.4bp, MDE(80% power) ~16.3bp**; injecting +5bp is NOT detected, +10bp is. So the
window is **BLIND by construction below ~11-16bp ≫ the ~5bp we'd care about.** **VERDICT (both gates, corrected): at the EVENT
level the observable state fully explains the fade advantage (per-event residual ~0, realized<predicted) — wallets identify
publicly-observable extreme-move setups; BUT the pre-registered PRIMARY day-capped residual +5.87 [−5.5,+17.7] is a POSITIVE
point estimate the test is UNDERPOWERED to resolve (MDE≫care-about → gate condition 2 fails) → this is a LIVE UNDERPOWERED
POSITIVE (ETH/SOL-concentrated, possibly coin-curvature misspec per audit #4, weighting-dependent), NOT a null.** Do not call it
"no skill" (over-null); do not carry it as skill (over-carry). The anti-ratchet obligation = a POWERED design: the forward
nested-model experiment (Phases 1-3 below) accrues independent coin-days to resolve it. EXPLORATORY; needs FORWARD confirmation.
Artifact: `src/cohort_M4_residual.py`.

## Canonical cohort freeze + Phase 1 (behavioral) + Phase 2 (frozen nested models) + Phase 3 (forward spec)  ·  *2026-07-05; historical wallet-ranking search CLOSED*
**Cohort freeze (`src/cohort_M_freeze.py`).** Audit round-3 found 3 conflated "top-decile" sets (recurrence 686 all-months /
deploy-leaked 99 / train-only 170). CANONICAL = TRAIN-ONLY, recurrence-based on `neut_8h`: top-decile in ≥2 of 6 train months
→ **PRIMARY 121 wallets** (STRICT ≥3mo = 28), + continuous conviction rank + traits, persisted to `out/cohort_M_frozen.{txt,parquet}`.
All downstream reads the file (no more inline re-derivation).
**Phase 1 — behavioral decomposition (`src/cohort_P1_behavioral.py`, EXPLANATORY).** Recurring vs ordinary-wallet vs non-wallet
control entries on TRAIN. Signature: **recurring wallets are aggressive CONTRARIAN FADERS** — signed 8h-return-in-trade-direction
median **−86 bp** (vs ordinary −12, i.e. they enter hard AGAINST the move), on larger trailing moves (|8h| 175 vs 151 vs 72 control),
deeper below the 24h high (−281 vs −218 vs −166), as the move decelerates (accel −6.2 vs 0), slightly higher vol; similar median
size (~$4k) with a fatter large-trade tail. Their "edge" IS the mechanical fade, done harder. Deferred features (VWAP, volume/OI,
liquidations, basis, OFI, aggressiveness) → forward log. **Phase 2 — frozen nested models (`src/cohort_P2_freeze_models.py`).**
Target = signed 8h forward COIN return; M0 = 17 market-state features, M1 = M0 + 5 wallet features (recurring indicator, conv rank,
wallet direction, log size, position-building). Ridge, month-block cross-fit for α, refit+frozen to `out/cohort_P2_models.npz`.
**In-train cross-fit rank-IC: M0 +0.0490, M1 +0.0487, incremental M1−M0 = −0.0003** — even in-sample-CV, wallet features (incl.
direction) add ~nothing over market state (low prior for forward; corroborates M3 A−B, M4 per-event ~0). Deliberately NOT scored on
the historical test window. **Phase 3 — frozen forward pre-registration (`docs/PHASE3_FORWARD_SPEC.md`).** Rules A=M0 / B=M1 /
C=copy-direction, same 8h exit + capital rule + costs; PRIMARY H1 = day-capped net(B)−net(A) > 0; calendar-day block inference;
forward log captures BBO/latency/spread/slippage/funding/overlap (closes M4's liquidity gap); power target MDE≤5bp (~≥250-300 fwd
coin-days); decision rules 1-4 (incremental value / trigger-only / proxy-for-setup / discontinue). Historical window is NON-admissible
as confirmatory; only forward data resolves the two live underpowered positives (M4 +5.87; trigger-specificity).

## Registered nulls / dead ends (so we don't re-run them)
- **The neut-persistent cohort is NOT a set of copyable/profitable traders (Stage G).** Real but thin entry-timing
  (+2.4bp/1h, +0.61 OOS) run as 68-76% takers @ 49-min holds; typical wallet net-unprofitable (40% profitable,
  p=0.013), ex-outlier price-breakeven, net-negative after fees. Alts (−6.6bp) & funding don't rescue. The profitable
  minority is unidentifiable ex-ante and PnL-ranking doesn't persist copyably. Don't re-pitch these wallets as copyable.
- **The r≈0.61 coin-day-neut wallet persistence is a benchmark artifact, NOT a deployable edge (Stage F).** The
  +67 bp top-decile "market-neutral" number is 91% the un-tradeable −d·coin_day_mean term; the real index-beta-hedged
  P&L is −7 bp gross / −16.5 bp net, HYPE-inverting and sign-flipping across test halves. Do not re-quote the +67 as
  deployable. (Coin-MONTH and raw persistence are ~0; only the coin-DAY grain manufactures the correlation.)
- Raw-edge and reliability-shrunk rankings do not clear random-selection OOS at significance (Stages A/B).
- **Performance-based wallet selection has NO copyable edge (registered NEGATIVE, 2026-07-04):** per-wallet
  winner's-curse = −29 bp net OOS; train→eval rank Spearman ≈ 0; deployable median at chance; config-null
  p=0.17/0.26. This is the *third* independent fall of this premise (cf. memory: edge3 stale-pricing artifact;
  wallet-screen sealed-test FAIL) — do not re-run performance-ranking variants.
- ew (per-decision) scoring is worse than vw; rolling-1-month worse than expanding (Stage C).
- Outlier contamination is NOT the bottleneck — median/trim rankers land on the field in aggregate (Stage C).
- **Adding more descriptive cuts (more rankers/horizons/descriptors, incl. a drawdown typology) is negative-EV**
  (audit): each new slice surfaces one more "coherent underpowered positive" a noise field is expected to
  produce. The only positive-EV move is the pre-registered, powered gate below.

## The residual we could NOT resolve (demoted from "live positive" — direction unknown)
- A small per-decision lean at **~24h, small-K**, on liquid coins — but post-hoc (24h = argmax of 12), K=50
  breaks it, coins non-independent, deployable version at chance. **Not evidence of edge.** It only earns
  further work if the free Step-0 gate (below) shows a copyable residual survives beta/lag/funding stripping.

## The decisive next move (from the 4-agent edge-isolation swarm, 2026-07-04)
**Step 0 — a FREE, powered gate on existing data, before ANY new build:** for the top cohort's 24h markout,
compute (a) the **index-beta split** (regress entry markout on `dir×index_return`, β fit on the full field →
idiosyncratic residual vs beta-timing), (b) the **15-min-lag rebase** (copyability: does the edge survive a
follower's lag or was it own-impact/latency), (c) **funding-net** (subtract realized funding over the inferred
24h hold — pull the funding stub; ~5–15 bp, can be the whole lean), (d) the **SNR term structure**
(`mean/(σ/√N)` across all 12 horizons — is 24h actually the most-detectable horizon or just the biggest mean).
Decision: if the lean dies under lag → not copyable (STOP); dies under funding → carry not alpha (STOP/reframe);
residual≈0 → all beta-timing, unconfirmable with 5 coins×11mo (STOP/pivot); **idiosyncratic residual survives →
GO** to a pre-registered Stage-E test (coin×day-neutralized 24h vw-markout of a *feature-selected wallet
portfolio*, wallet+time-disjoint m1-6/m7-embargo/m8-11 split, two-way-clustered bootstrap CI, frozen
CONFIRM/KILL/INCONCLUSIVE rule; neutralization+pooling+horizon-by-SNR is what crosses MDE 160→~13 bp *iff the
edge is idiosyncratic*). Data priority: **funding first, then forward months 12-16 as a lockbox**; BBO/L2 only
once existence survives; liquidations are for the drawdown/risk question, not edge.

**Step 0 lag+beta legs RUN + 3-agent AUDIT (2026-07-04, `src/edge_gate.py`) — verdict: the gate is
NON-DISCRIMINATING (a test that couldn't fail); the initial "GO / 3-PASS" read was OVER-CARRY and is
RETRACTED.** All three legs are mechanical artifacts of selecting the cohort in-sample on its own 24h edge —
*demonstrated on data, not asserted* (code audit reproduced every number exactly; markout is leak-free):
- **Copyability "PASS" = MECHANICAL, zero cohort information.** Random FIELD wallets show the identical keep%
  (BTC 99 / ETH 106 / SOL 105 / HYPE 94 / SPX 110%) because a 15-min lag on a 24h window shares 99.6% of the
  path for *anyone*. Weak true residual: it only rules out a sub-15-min reversion blip (first-15-min markout is
  0.8–7% of the 24h total).
- **Idiosyncratic "4/5 PASS" = mostly WINNER'S CURSE, refuted OOS.** (i) Label-permutation null (zero skill by
  construction) reproduces **60–70%** of the headline idio (perm-mean ETH+40/SOL+57/HYPE+143/SPX+23). (ii) The
  real excess over the null (z=3–10 on 4/5) does NOT persist: rank on first-half edge → held-out second-half
  idio collapses to ETH −3[−24,+7] / SOL 0[−12,+9] / HYPE +31[−25,+69] / SPX −56, all CIs back at field level
  (~95% shrinkage). (iii) Beta-split is unfair — the cohort's OWN beta is higher (SOL 1.07 / HYPE 1.23 / SPX
  1.70 vs field 0.76), so field-β over-attributes to idio; using cohort-β, SPX idio vanishes (+36→−1.5). Plus
  EW-index self-inclusion deflates BTC (fix: leave-one-out index).
- **"SNR peaks at 24h / slow-information shape" = SELECTION-HORIZON ARTIFACT.** Re-selecting the cohort at any
  horizon moves the peak to that horizon (select@8h→peak 8h); the mean curve ≈ edge₂₄·(h/24), the exact
  signature of reading sub-windows of a ~random walk selected on its 24h endpoint. No info about edge timing.
- **What genuinely survives (symmetric guard — NOT a null):** the gate is uninformative in BOTH directions, so
  it neither supports nor kills the edge. The prior stands unchanged: an underpowered, inconclusive, directional
  4/5-positive residual (MDE≈160 bp); HYPE & SPX remain individually inconclusive (OOS CIs admit +58 bp); if any
  edge exists it is slow (5m≈0) → in the copyable regime. "In-sample idio dominated by selection, no OOS-persistent
  signal" is NOT "idio provably zero."
- **Consequence for Stage-E:** still a legitimate ONE-SHOT bet, but justified by the **anti-ratchet obligation**
  (given an inconclusive prior, build one powered design), NOT by this gate. It must select on the INDEPENDENT
  behavioral trait (high-vol-entry — non-circular), be OOS + coin×day-neutralized with a built-in MDE positive
  control, funding-netted, and use a cohort-robust/LOO beta. Honest expectation from the free OOS previews: a
  real chance of KILL/INCONCLUSIVE. Do NOT carry "copyable + idiosyncratic" in as an established premise.

---

## CONSENSUS>=9 signal — significance under non-independence + generic-crowding placebo (2026-07-05, `src/consensus_sig.py` + `consensus_master.py` + `consensus_analysis.py`)

**Question:** Is the consensus-subset edge (>=9 same-dir cohort entries in trailing 30min → 6h markout net
+15.53bp on n=1270 TEST entries, naive CI ~[+4,+27]) a real cohort-specific signal, or non-independence +
generic crowding? **Verdict: INCONCLUSIVE / underpowered positive with a WEAK cohort-specific lean — the naive
significance is a non-independence artifact; NOT deployable. Guards both over-null and over-carry.**

Reproduced exactly: entry-count consensus (conditional_copy2 def) cons>=9 → n=1270, gross +24.1, cost 8.6,
NET **+15.53bp**. (Fragile operating point: net +10 at >=10, +1.6 at >=12, −24 at >=15; distinct-WALLET count
>=9 gives only +8.5.)

- **(1) True independent N ≈ 80–100, NOT 1270.** Three methods agree: dedup to non-overlapping coin blocks →
  192 events (30min) / 156 (60min) / **106 (6h non-overlap fwd window)**; SE-ratio effective N ≈ **77**;
  coin-day clusters = **95**. Design effect ≈ 16× variance (4× SE). The 1270 "entries" are ~13 correlated
  copies per independent decision.
- **(2) Cluster-honored CI SPANS ZERO.** Coin-DAY cluster bootstrap (95 clusters): point +15.53,
  **95% CI [−19.8, +55.5]**. Coin-WEEK (40 clusters): [−25.0, +66.8]. Naive iid CI [+5.9, +25.2] EXCLUDED
  zero — that was pure non-independence inflation (iid SE 4.9 vs cluster SE 19.9). **The claimed significance dies.**
- **(3) MDE ≈ 56bp ≫ +15.5.** At honest clustering the design is BLIND to a +15.5 effect (MDE = 2.8×19.9).
  → per the over-null gate this is **inconclusive, full stop** — cannot be called null (CI admits up to +55).
- **(4) PLACEBO (decisive): NOT generic crowding, but only a weak lean.** 300 activity-matched (>=300 majors
  entries, ex-cohort) random 178-wallet cohorts, identical cons>=9 pipeline: random consensus net centered
  **NEGATIVE** (mean −8.1, median −6.9, sd 15.9). So "crowd piles into a dip → bounce" does NOT generically
  pay — a random crowd's consensus predicts slightly negative net. Real +15.5 sits at ~97th pct, fixed-threshold
  empirical **p=0.033**. BUT selection-corrected: threshold 9 is the argmax; letting each random cohort shop the
  same thresholds {7,8,9,10,12} → real best at ~87th pct, **p≈0.13**. BTC-only (1030/1270 entries live there):
  real +7.5 at ~86th pct, **p≈0.14**. So cohort-specificity is a genuine but sub-significant lean.
- **(5) Concentration-fragile.** By coin: BTC +7.5 (n=1030, the bulk), SOL +154 (n=36), HYPE +101 (n=109),
  **ETH −48** (n=95). 3/4 positive but wildly heterogeneous. Event-weighted edge +46 (upweights small alt bursts)
  collapses to +20 after dropping the 5 most-extreme events. Drop-HYPE → +7.5; drop-BTC → +50.

**Bottom line:** the naive "+15.5, CI excludes 0" is FALSE (non-independence: eff N ~80, clustered CI
[−20,+55] spans zero, MDE 56 ≫ effect). It is ALSO not merely generic crowding (random crowds → −8bp; real at
~87–97th pct). Net: an **underpowered, inconclusive positive with a weak (~p0.13) cohort-specific tilt**, driven
disproportionately by a few small SOL/HYPE bursts and a hand-picked threshold. Not significant, not deployable;
would need a variance-reduced/pooled powered design (or more test epochs) to resolve. Artifacts:
`out/consensus_master.parquet`, `out/consensus_test_table.parquet`, `out/consensus_placebo.parquet`.
