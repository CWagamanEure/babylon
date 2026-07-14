# 07 — OOS non-persistence: top in-sample markout wallets regress to the field

**Section thesis.** Rank Hyperliquid taker wallets by their in-sample markout, and the top cohort looks
excellent in-sample. Out-of-sample, that discrete top ranking does **not** carry: the exact top-20 basket is
~0 net and the top→top transition is at chance. The honest nuance (per CLAUDE.md, guarding both over-null and
over-carry): a **weak-but-real** rank persistence does survive when you pool across many rolling folds
(rank-IC ≈ +0.09), but it is small, gross-of-cost, and mostly a generic short-horizon-reversal style, not
wallet-specific skill. The strong "no persistence" claim is scoped to the **exact top-20 / discrete top→top**
instrument.

---

## FACTS (each with source line)

### The train / test / embargo split (canonical for the whole arc)
- **TRAIN = Aug 2025 – Jan 2026 (months 1–6); EMBARGO = Feb 2026; TEST = Mar – Jun 2026 (months 8–11).**
  Chronological split, 1-month embargo so no wallet-day straddles the seam.
  - Source: `FINDINGS_LEDGER.md` Stage F line — "TRAIN<Feb / EMBARGO Feb / TEST Mar-Jun"; Stage E — "TRAIN-only
    (Aug'25–Jan'26)… held-out (Mar–Jun'26, Feb embargoed)"; memory `babylon-oos-persistence.md` "Select wallets
    by TRAIN-only (Aug'25–Jan'26)… measure held-out (Mar–Jun'26, Feb embargoed)".
- Earlier Stage-A instrument used a purged/embargoed **expanding walk-forward (7 splits over 11 months)** with
  an embargo that drops any train entry whose priced 168h exit crosses the test seam.
  - Source: `FINDINGS_LEDGER.md` Stage A; memory `babylon-oos-persistence.md` "purged/embargoed walk-forward (7
    expanding-train / 1-bucket-forward splits over 11 months, 4 majors + SPX)".

### The core "no persistence" result — the exact top-20 / discrete ranking
- **Top-20 basket OOS (Stage M1, patched exact rerun):** Family A (copyability, E[net copied]>0) =
  **+3.75 bp, 95% CI [−7.6, +15.3], p=0.26**; under the study's realistic cost table (8/8/10/14) it collapses
  to **+0.20 bp [−11.3, +11.7], p=0.50**. Family B (incremental over the mechanical fade) = **+1.54 bp EW /
  −1.95 bp pooled, p=0.44–0.63, 0/12 Romano–Wolf survivors** — the fade-beating was largely a selection-leak
  artifact; done clean there is no incremental edge over a costless mechanical fade.
  - Source: `FINDINGS_LEDGER.md` Stage M1 lines "Corrected exact-rerun result… Family A +6.9 (p=0.08) → +3.75
    bp [−7.6,+15.3] p=0.26; Family B '+7.9 beats fade' (p=0.15) → +1.54 EW / −1.95 pooled bp, p=0.44–0.63,
    0/12 RW" and robustness line "Family A collapses to +0.20 bp [−11.3,+11.7], p=0.50".
- **The basket conclusion depends on ≤2 wallets:** removing the top-2 positive contributors takes Family B
  +1.54 → **−7.10** (and A +3.75 → −0.96); one thin wallet (20 test days, day-SD 215 bp, CI [−15,+172]) drives
  most of the positive. **8/20 wallets attrited** (insufficient test coverage), including **4 of the top-10
  train ranks with ZERO test days** — the best train wallets went silent. Within-top-20 rank did not persist
  (train ranks 1/2/7 are among the worst in test).
  - Source: `FINDINGS_LEDGER.md` Stage M1 battery line.
- **Month-instability:** monthly Family-A net = −0.8 / +10.3 / −19.0 / +0.0; Family-B alpha = −7.5 / +19.3 /
  +0.8 / −11.6 — **sign flips every month.**
  - Source: `FINDINGS_LEDGER.md` Stage M1 robustness line.

### The discrete top→top transition — at chance
- **P(top-decile in fold t+1 | top-decile in fold t) = 0.109 vs the 0.10 base rate = ×1.09, p=0.22 — NOT
  significant** (the earlier "×3.2" was a James-Stein shrinkage-collapse bug, since fixed).
  - Source: `FINDINGS_LEDGER.md` Stage M2 item (3): "transition P(top|top)=0.109 vs 0.10 = ×1.09, p=0.22 — NOT
    significant (was the bug-inflated '3.2×'…)".

### The Stage-A minimum p-value / FDR survivor counts
- Primary cell **vw_edge@24h joint-p: BTC 0.09 / SPX 0.15 / HYPE 0.18 / SOL 0.42 / ETH 0.78 — none < 0.05**;
  **min p = 0.09** (BTC). Of 75 cells, 6 cross raw p<.05 but **0 survive BH-FDR**. Train→eval wallet-rank
  **Spearman ≈ 0** (0.002–0.05, sign-flipping across coins, SE≈0.007).
  - Source: `FINDINGS_LEDGER.md` Stage A; memory `babylon-oos-persistence.md` "primary cell (vw_edge@24h)
    joint-p = 0.09 BTC / 0.15 SPX / 0.18 HYPE / 0.42 SOL / 0.78 ETH… 0 survive BH-FDR"; bottom-line
    "train→eval wallet-rank Spearman ≈ 0 (0.002–0.05… SE≈0.007)".
- **Winner's-curse (direct powered number):** selecting each wallet on its best in-sample horizon returns
  **−28.7 bp NET out-of-sample** (pooled; BTC −20 / ETH −36 / SOL −46) — past markout is *anti*-predictive
  per wallet.
  - Source: `FINDINGS_LEDGER.md` bottom-line 2026-07-04; memory "winner's-curse held-out… = −28.7 bp NET
    pooled OOS (BTC−20/ETH−36/SOL−46; `out/eda_winnerscurse.parquet`)".

### The weak-but-real persistence (do NOT over-null this — it is the load-bearing positive)
- **Adjacent-fold rank-IC (rolling monthly folds, bug-corrected):** 4h **+0.081 [+0.054, +0.108]** (9/10
  folds); **8h +0.093 [+0.061, +0.126]** (10/10 folds, sign-p=0.002); 24h +0.085 [+0.041, +0.134] (9/10) —
  all CIs exclude 0. Corroborating term structure peaks at **8h: +0.219 [+0.154, +0.282]**, monotone 1h→8h,
  robust to drop-HYPE/SOL and BTC-only.
  - Source: `FINDINGS_LEDGER.md` Stage M2 items (1) and corroboration line.
- **Top-decile forward edge = +5.72 vs field +1.24 = +4.48 bp [+2.17, +7.54]** (9/10 folds, significant) —
  this is the "top-quantile next-period return vs field" number. (Gross, coin-month-neutralized markout.)
  - Source: `FINDINGS_LEDGER.md` Stage M2 item (2): "top-decile forward edge +5.72 vs field +1.24 = +4.48 bp
    [+2.17,+7.54] 9/10 folds".
- **Day-weighted population rank-IC = +0.16, p=0.0001** (robust to drop-HYPE/SOL +0.156, within-BTC +0.144);
  but **entry-weighted = −0.055** — a naive per-episode copier captures nothing. Persistence lives only under
  day-equal-weighting.
  - Source: `FINDINGS_LEDGER.md` Stage M1 origin line; audit correction "single-weighting (day-weighted;
    entry-weighted is −0.055), not multiplicity-adjusted across weighting schemes, not tradable".
- **Decile long-short day-capped instrument (audit-built) = +14.37 bp [+8.15, +20.12], p<1e-4**; top-decile
  long-only +9.95 [+5.75, +14.26]; survives raw and within-BTC (+7.26 [+2.83, +11.47]); positive 5/5 test
  months; IC t=5.1. The population signal is monthly-STABLE — the top-20's month-instability was an
  underpowered-instrument artifact.
  - Source: `FINDINGS_LEDGER.md` Stage M2 corroboration audit #3 line.

### The over-carry cap (do NOT sell the +4.5 bp as tradeable skill)
- The +4.48 / +14 bp is **GROSS, coin-month-neutralized markout — NOT net of cost and NOT vs the mechanical
  fade.** A costless mechanical contrarian ("fade") at the SAME entry times earns **~+9.5 bp** (Stage L), and
  the decile's ALPHA over that fade is **+1.00 bp [−10.75, +13.66], p=0.44 ≈ 0** at 8h (+1.29, p=0.39 at 4h).
  Wallet identity adds ~nothing over the mechanical setup.
  - Source: `FINDINGS_LEDGER.md` Stage M2 over-carry caveat; Stage-M2 deployability gate "ALPHA vs mechanical
    fade +1.00 [−10.75,+13.66] p=0.44".

### Power / MDE caveats (why "not significant" ≠ "no effect" here)
- **Stage A positive-control MDE ≈ 160 bp/entry** at 92% power (0% ≤80 bp, 100% ≥320 bp) — ~10–30× a realistic
  single-to-low-double-digit-bp edge, so the naive 30-entry ranker is **blind by construction** to a realistic
  edge. The 4/5-coin positive point estimates (BTC +31, HYPE +45, SOL +13, SPX +35; ETH −41 bp) are surfaced,
  not buried.
  - Source: `FINDINGS_LEDGER.md` Stage A; memory "positive control MDE = 160 bp/entry at 92% power".
- **Top-20 basket MDE ~85 bp** (blind-by-construction, audit agents #13/#15) — the frozen top-20 failing is a
  blind instrument, not evidence of no persistence. Copyability CI is ±11–17 bp at all cost levels including 0
  → cost is not what nulls it; the instrument is underpowered.
  - Source: `FINDINGS_LEDGER.md` Stage M2 over-null-vindicated line; Stage M1 audit corrections.

### My own light corroboration (single-fold, `out/cohort_K_entries.parquet`, 1694-wallet mid-freq taker cohort)
Computed live (POLARS_MAX_THREADS=2), per-wallet mean coin-month-neutralized 8h markout, TRAIN(Aug–Jan) vs
TEST(Mar–Jun), embargo excluded:
- **Entry-weighted (naive per-episode)**, wallets with train n≥50 & test n≥20 (N=936): **train→test Spearman
  = +0.049, p=0.14 (n.s.)**. Top-train-decile TEST mean = **−2.36 bp vs field −1.81 bp (excess −0.56 bp)** —
  the top in-sample cohort regresses to (slightly below) the field. Train-decile means fan monotonically
  −35 → +43 bp; the corresponding TEST means are a flat noise band (−6.3 → −2.4 bp, no monotone carry).
- **Day-weighted** (wallet-day mean first), train days≥15 & test days≥8 (N=1076): **Spearman = +0.026,
  p=0.40 (n.s.)**; top-train-decile TEST = −1.89 vs field −1.67 (excess −0.22 bp).
- **Interpretation:** on THE single canonical train→embargo→test split, the discrete top ranking does not beat
  the field under either weighting — corroborating the Stage-M1 top-20 null. The +0.09 rank-IC positive
  emerges only when pooling across **many rolling adjacent folds** (Stage M2), which averages out the single
  Aug–Jan→Mar–Jun regime transition that dominates one fold. (Note: cohort_K is the mid-freq-taker universe,
  a superset overlap of but not identical to the M2 ranked universe; treat as directional corroboration.)

---

## FIGURES TO MAKE

### Figure 7A — Train-vs-test rank scatter ("looks great in-sample, regresses OOS")
- **Type:** scatter, one point per wallet. X = TRAIN mean neut_8h markout (bp), Y = TEST mean neut_8h markout
  (bp). Overlay OLS/lowess line + the y=x diagonal + a horizontal line at the field TEST mean (≈ −1.8 bp).
- **Data:** from my light computation above — entry-weighted, N=936 wallets (train n≥50, test n≥20). The cloud
  is near-vertical: train spans roughly −35→+43 bp per decile mean while test collapses to a flat ±5 bp band.
  Annotate **Spearman = +0.049 (p=0.14, n.s.)**.
- **Companion panel (recommended):** the *powered* view — plot the Stage-M2 **adjacent-fold rank-IC per fold**
  (4h/8h/24h) as a small strip: 8h +0.093 [+0.061,+0.126], 9–10/10 folds positive. This is the honest
  "weak-but-real when pooled" counterpoint to the flat single-fold scatter. Message: no carry in one fold;
  a small consistent carry across ten.

### Figure 7B — Top-quantile next-period return vs field (decay bar)
- **Type:** grouped bar. For each train-decile (1…10), two bars: TRAIN mean markout (bp) and TEST mean markout
  (bp). The dramatic collapse of decile-10 (train +43 → test ~field) is the headline.
- **Data (my single-fold cohort_K, entry-weighted, bp):**

  | train decile | TRAIN mean neut_8h | TEST mean neut_8h |
  |---|---|---|
  | 1 (bottom) | −35.2 | −6.3 |
  | 2 | −16.9 | −0.1 |
  | 3 | −10.5 | +0.1 |
  | 4 | −5.3 | −5.4 |
  | 5 | −1.1 | −3.0 |
  | 6 | +2.9 | −3.7 |
  | 7 | +6.9 | −1.3 |
  | 8 | +12.2 | +2.1 |
  | 9 | +21.1 | +2.0 |
  | 10 (top) | +43.0 | −2.4 |

  Field (all-wallet) TEST mean = **−1.8 bp**. Top decile excess over field = **−0.56 bp** (i.e. none).
- **Alternate / stronger-framing bar (from the ledger's powered rolling-fold result, cite Stage M2):** a
  three-bar "top-decile forward edge" panel — **top-decile +5.72 vs field +1.24 → excess +4.48 bp
  [+2.17,+7.54]** (gross), then a third bar **alpha-over-mechanical-fade +1.00 bp [−10.8,+13.7], n.s.** to
  show the gross edge is almost entirely generic reversal, not wallet skill. This single figure carries the
  whole "weak-real-but-not-skill" thesis.

### Figure 7C (optional) — MDE / power annotation strip
- A simple bar or caption block contrasting the **effect we care about (~5–20 bp)** against the **instrument
  MDEs**: Stage-A naive ranker 160 bp; top-20 basket ~85 bp; M4 window blind < 11–16 bp. Visual proof that
  "not significant" on the discrete instruments = under-powered, not zero.

---

## GAPS / caveats for whoever writes the prose

1. **My single-fold cohort_K numbers are a light corroboration, not the registered result.** They are
   entry/day-weighted on one train→test split of the mid-freq-taker cohort (1694 wallets), computed live here;
   the registered persistence numbers (rank-IC +0.09, decile +4.48) come from the multi-fold M2 harness on the
   ranked universe. Label figure 7A/7B data as "single-fold illustration"; use M2 for the powered claim.
2. **Do not state "wallets have no persistence" flat.** The registered position is: (a) the exact top-20 /
   discrete top→top ranking does NOT persist tradeably (top-20 ~0 net, transition ×1.09 n.s., 8/20 attrition);
   (b) a broad population rank persistence IS real and powered (IC ≈ +0.09, 10/10 folds at 8h; decile +4.48 bp
   gross); (c) but that gross edge is ~entirely captured by a costless mechanical fade (alpha-over-fade +1.00,
   p=0.44) → persistent *ranking* ≠ wallet-specific *skill* ≠ deployable.
3. **Aggregation weighting is load-bearing and must be stated:** day-weighted rank-IC +0.16 vs entry-weighted
   −0.055. A naive copier who trades every episode earns the entry-weighted (~0) number, not the day-weighted
   one (wallets over-trade their worse days). This is the single most over-carry-prone point.
4. **The +4.48 / +14 bp are GROSS, coin-month-neutralized markout** — not net of ~5–6 bp realistic HL
   round-trip cost, not funding-netted, single epoch, and the fade benchmark itself is post-hoc here. Any
   forward/deployable read is unresolved (Phase-3 forward spec, `docs/PHASE3_FORWARD_SPEC.md`).
5. **cohort_K vs the M2 ranked universe are not identical.** If exact reproduction of a scatter on the *ranked*
   universe is needed for the report, it requires re-running the M2 recurrence harness (bar-free, but not done
   here under the RAM budget) rather than my cohort_K light read.
6. **Numbers to pull directly from parquet if the report wants exact tables (not done here — RAM budget):**
   `out/cohort_M1_{ep,top}.parquet`, `out/cohort_M2_recurrence` outputs, `out/persistence_verdict.parquet`,
   `out/eda_winnerscurse.parquet`.

---

**Artifacts referenced:** `docs/FINDINGS_LEDGER.md` (Stages A, M1, M2, M2-deploy); memory
`babylon-oos-persistence.md`, `babylon-wallet-screen-verdict.md`; `src/cohort_M1_daycap.py`,
`src/cohort_M2_recurrence.py`, `src/cohort_M2_deploy.py`, `src/oos_persistence.py`;
`out/cohort_K_entries.parquet` (my live corroboration).
