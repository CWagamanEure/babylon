# 12 — The central finding: the persistent wallet markout is TRIGGERED short-horizon REVERSAL, not wallet-specific skill

**One-line claim.** Wallet *rankings* do persist out-of-sample (small but real), and wallet *activity* does mark
a profitable fade setup — but at the level that matters for copying, the wallets' entire gross edge is captured by
a costless mechanical contrarian ("fade the recent move") priced at the wallets' **own** entry/exit times. Wallet
**direction** and **timing** add ~nothing over the observable trailing-move setup. Both error-gates are honored:
the persistence is real (not over-nulled) and it is generic reversal (not over-carried as skill), with one live,
underpowered day-capped residual (+5.87 bp) the historical window is blind to.

Sources: `docs/FINDINGS_LEDGER.md` Stages M2 (deployability gate), M3, M4, Phase-2; memory `babylon-markout-study.md`.
Code: `src/cohort_M2_deploy.py`, `src/cohort_M3_trigger.py`, `src/cohort_M4_residual.py`, `src/cohort_P2_freeze_models.py`.

---

## FACTS (with exact numbers + source)

### F0 — The mechanical-fade benchmark (the object everything is measured against)
The benchmark is a costless, purely mechanical short-horizon contrarian, evaluated at the **same entry and exit
timestamps** as the wallet events (so execution/cost/entry-lag cancel in the difference):

- trailing move `= ent/past − 1` (return over the trailing window, e.g. trailing 8h before entry)
- **`fade_dir = −sign(trailing move)`** — bet *against* the recent move
- forward move `= ex/ent − 1` (entry→exit return over horizon H)
- **`fade return = fade_dir × forward move`** (in bp: `−np.sign(ent/past−1) · (ex/ent−1) · 1e4`)

Source (verbatim): `cohort_M2_deploy.py:34`, `cohort_M3_trigger.py:32`, `cohort_M4_residual.py:50`
(`fade = -np.sign(ent/past - 1.0) * move * BP`). Entry = next-bar-close, coin-day-capped, per-coin realistic cost.

At the persistent cohort's own entry times this mechanical fade earns **~+9.5 bp gross [+5.1, +13.4]** (≈+4.5 net)
— a live short-horizon-reversal edge the arc only ever used as a benchmark (Stage L / audit #14, ledger L556–559).

### F1 — Deployability gate: the decile's gross edge is real and powered, but its ALPHA vs the fade is ~zero
`src/cohort_M2_deploy.py`: rank TRAIN day-weighted GROSS wallet markout, freeze top decile (99 wallets), judge
untouched TEST day-capped, joint day-block bootstrap. **@8h:**

| Quantity | Estimate | 95% CI | p |
|---|---|---|---|
| Top-decile GROSS long-only | **+13.99 bp** | [+5.38, +22.81] | 0.0003 |
| NET of realistic cost (~6–9 bp) | +7.09 bp | [−1.94, +15.83] | 0.062 (marginal) |
| NET of campaign cost | +4.19 bp | [−4.52, +12.92] | 0.18 |
| **ALPHA vs mechanical fade** | **+1.00 bp** | **[−10.75, +13.66]** | **0.44 (≈0)** |

**@4h:** gross +10.0 (p<1e-4), net +3.1 (p=0.12), **alpha vs fade +1.29 (p=0.39).**

Reading: the persistence is CONFIRMED and POWERED (gross CI excludes 0, 5/5 test months, IC t≈5) — so it is NOT
over-nulled. But the **entire ~+14 bp gross is the mechanical fade**; wallet identity adds +1.00 bp (p=0.44).
Corroborated by audit #5: no coin-conditional wallet edge — per-coin positives are coin-level drift/beta shared by
train-BOTTOM wallets; the cross-coin differential spans 0 (MDE≈3.8 bp). Source: ledger L535–552.

**Symmetry caveat (do NOT read as a tight zero):** the alpha CI is wide (±12 bp — variance inflated by differencing
against the ρ<0 fade), MDE≈12 bp ≈ the care-about, and the CI admits up to +13.7 bp. So this is
"no incremental wallet skill DEMONSTRATED," i.e. **INCONCLUSIVE on the increment**, not a proven zero — but
gross≈fade+~0 makes generic-reversal the strong read (ledger L536, L546–547).

### F2 — M3 A/B/C/D: direction adds nothing; the fade needs a trigger
`src/cohort_M3_trigger.py`, 4 strategies on TEST, 8h / next-bar-entry / coin-day-capped / realistic-cost / joint
day-block bootstrap. Top-decile frozen wallet set (99 → 170 after the train-only leak fix, 44 attrition).

| | Strategy | Net bp/coin-day | 95% CI | p |
|---|---|---|---|---|
| **A** | wallet DIRECTION at wallet events | +3.02 | [−4.1, +10.2] | 0.20 |
| **B** | mechanical fade at the SAME timestamps | +5.53 | [−5.6, +16.7] | 0.15 |
| **C** | fade at ALL bars (no wallet info) | **−7.00** | [−16.4, +2.5] | 0.08 |
| **D** | fade at matched NON-wallet timestamps | **−5.12** | [−9.0, −1.3] | 0.003 |

Key comparisons (values after the audit-round-2 train-only leak correction in parentheses):
- **A − B = −2.51 [−11.9, +7.0], p=0.58 (→ −3.3 n.s.) — wallet DIRECTION adds no information** over the fade at the
  same times (confirms F1 and the P2 model in F4).
- **C = −7.00 net — the unconditional fade run EVERYWHERE LOSES money.** Corrects any "the mechanical fade is simply
  deployable" framing: the reversal is *not free everywhere*; it needs a trigger.
- **D placebo FAILS = −5.12** (feature-matched non-wallet timestamps also lose) → activity IS a real trigger
  (verdict-2-leaning), but…
- **B − D disagrees by aggregation** (the central unresolved point): day-capped +10.64 [+0.3, +21.0] p=0.044
  (post-fix +12.35 [+2.2, +23.1] p=0.014) **vs** episode-level matched-pairs (n=16,704, cleanest) +4.44 [−8.4, +17.5]
  p=0.47 (post-fix +6.61 [−5.4, +18.8] p=0.28). And matching left a residual confound: **wallet events sit on ~13%
  larger trailing moves (195 vs 172–174 bp)** → bigger mechanical reversals, inflating both.
- B − C = +12.53 [+5.8, +19.2] p<0.001 (wallet activity beats blind fading); B leave-one-wallet-out range 1.68 bp
  (NOT 1-wallet-driven). By coin: SOL B +13.7 / ETH +8.0 / BTC +4.2 / HYPE −3.8; positive 3/4 months (May −11).

**VERDICT (4) — INCONCLUSIVE:** wallet-triggered-vs-matched-control (B−D) is underpowered and confounded (clean
episode pairs n.s.). Firm riders: direction adds nothing; the unconditional fade is net-negative (not verdict 3);
the placebo fails (leans verdict 2 = activity is a trigger). Whether the trigger must be *wallet-specific* is
UNRESOLVED. Source: ledger L562–588.

### F3 — M4 continuous-control residual: state over-explains the event fade; day-capped +5.87 is a LIVE underpowered positive
`src/cohort_M4_residual.py` (resolves the M3 |tret| confound with a continuous, not binned, control). Fit
`E[fade 8h return | state]` by OLS on **172,558 TRAIN non-wallet bars** — controls = signed trailing-8h return,
|trailing move|, vol, coin dummies + coin×|tret| slopes, time-of-day (sin/cos) — **freeze**, apply to **18,380 TEST**
top-decile (train-only) wallet events; residual = realized fade − predicted fade.

- Mean **realized fade +7.44** vs **predicted +8.74** → the observable state **OVER-explains** the event fade advantage.
- **PRIMARY, day-capped residual: +5.87 bp [−5.54, +17.66], p=0.15** (positive, not significant; ETH +11.4 / SOL +12.0
  driven, HYPE −4.2 / BTC +4.4; May −7.5).
- **SECONDARY, per-event residual: −1.30 bp [−15.6, +13.0], p=0.57 (~zero)** → at the EVENT level the state fully
  explains the fade advantage; wallets identify publicly-observable extreme-move setups.
- **Positive-control MDE (audit r3):** bootstrap SE = 5.81 on 122 test coin-days → MDE(95% CI excl 0) ≈ **11.4 bp**,
  MDE(80% power) ≈ **16.3 bp**; injecting +5 bp is NOT detected, +10 bp is. **The window is BLIND below ~11–16 bp ≫
  the ~5 bp we'd care about.**

**VERDICT (both gates):** at the event level the observable state fully explains the fade advantage (per-event ~0,
realized < predicted) — NOT residual timing skill; **BUT** the pre-registered PRIMARY day-capped +5.87 is a positive
point estimate the test is UNDERPOWERED to resolve (gate condition 2 fails: MDE ≫ care-about) → **a LIVE UNDERPOWERED
POSITIVE (ETH/SOL-concentrated, weighting-dependent), NOT a null.** Do not call it "no skill" (over-null); do not carry
it as skill (over-carry). Resolution requires the frozen forward experiment (Phase 3). Source: ledger L590–606.

### F4 — Corroboration: nested models say wallet features add ~nothing even in-sample
`src/cohort_P2_freeze_models.py`: target = signed 8h forward coin return. M0 = 17 market-state features; M1 = M0 + 5
wallet features (recurring indicator, conviction rank, wallet direction, log size, position-building). Ridge,
month-block cross-fit. **In-train cross-fit rank-IC: M0 = +0.0490, M1 = +0.0487, incremental M1−M0 = −0.0003.**
Even in-sample-CV, wallet features (including direction) add ~nothing over market state — corroborates M3 A−B and
M4 per-event ~0, sets a low forward prior. Source: ledger L618–623.

### F5 — What the persistence IS (the other gate — do NOT over-null it away)
Wallet-ranking persistence is a **small, real, cross-fold-consistent** effect (Stage M2 recurrence, bug-corrected):
adjacent-fold rank-IC **8h +0.093 [+0.061, +0.126], 10/10 folds, sign-p=0.002**; top-decile forward edge **+4.48 bp
[+2.17, +7.54], 9/10 folds**; term structure peaks at 8h. It is REAL but it is **gross coin-month-neut markout, not
net and not vs the fade** — a costless robot fade earns ~+9.5 bp at the same entries, so the persistence is a
*reversal-style proxy*, not demonstrated wallet skill. Behavioral fingerprint (Phase 1): recurring wallets are
**aggressive contrarian faders** — they enter with the 8h-return-in-trade-direction median at −86 bp (vs ordinary
−12), on larger trailing moves, deeper below the 24h high. Their "edge" IS the mechanical fade, done harder.
Source: ledger L500–533, L613–617.

### F6 — The synthesis (both gates, one sentence each)
- Wallet RANKING persists (small, real: IC≈0.09 @8h, forward-decile +4.5 bp gross) — **not nulled.**
- At the EVENT level wallet DIRECTION and TIMING add nothing beyond the observable trailing-move setup (A−B ~0;
  per-event residual ~0; M2 gross ≈ fade, alpha +1.00 p=0.44) — **not over-carried as skill.**
- The day-capped wallet-trigger residual is a **live underpowered +5.87 bp** the historical window cannot resolve
  (MDE 11–16 bp) → forward experiment specified. The fade needs a trigger (C −7 net, D −5 placebo fail); whether
  wallet-specificity of that trigger is real is **UNRESOLVED, not disproven.**

---

## FIGURES TO MAKE

1. **Alpha-vs-fade bar with CI (the headline).** Grouped bars for the top decile @8h (and @4h as a second panel):
   GROSS +13.99, NET-realistic +7.09, NET-campaign +4.19, **ALPHA-vs-fade +1.00**, each with its 95% CI whisker.
   Overlay a horizontal reference band at the mechanical-fade gross (~+9.5 bp [+5.1, +13.4]). Visual message: the
   gross bar sits ON the fade band; the alpha bar collapses to ~0 and its CI straddles zero. Data: F1 table (@8h),
   `cohort_M2_deploy.py` output. *(See dataviz skill before plotting.)*

2. **A/B/C/D comparison chart.** Four horizontal bars (net bp/coin-day) with 95% CIs: A wallet-direction +3.02,
   B fade-at-wallet-times +5.53, C fade-everywhere **−7.00**, D fade-matched-nonwallet **−5.12**. Annotate the three
   contrasts: A−B ≈ 0 (direction adds nothing), B−C ≫ 0 (activity beats blind fading), B−D (day-capped +12.4 sig vs
   episode +4.4 n.s. — the disagreement). Shade C and D negative to make "fade needs a trigger" legible. Data: F2.

3. **M4 residual-with-MDE.** Point-and-CI for the day-capped residual **+5.87 [−5.54, +17.66]** and the per-event
   residual **−1.30 [−15.6, +13.0]**, plotted against a shaded MDE floor band **[11.4, 16.3] bp** and a "care-about"
   marker at ~5 bp. Visual message: the +5.87 point sits BELOW the detectability floor → the test is blind here; it
   is a live underpowered positive, not a null. Optional inset: realized +7.44 vs predicted +8.74 (state
   over-explains). Data: F3.

4. *(optional context panel)* **Persistence term structure** — adjacent-fold rank-IC vs horizon (1h→8h→24h),
   peaking at 8h +0.093, CI-excludes-0 markers, to establish "the ranking IS real" before the deployability gate
   deflates it. Data: F5 / ledger L509, L518–519.

---

## GAPS / caveats to flag in the report

- **The alpha-vs-fade zero is NOT a tight null.** Alpha CI ±12 bp (variance inflated by differencing vs the ρ<0
  fade); MDE≈12 bp ≈ care-about; CI admits up to +13.7 bp. Report as "no incremental wallet skill demonstrated /
  INCONCLUSIVE-on-increment," with the strong descriptive read "gross ≈ fade" — not "wallet skill = 0."
- **Two live underpowered positives must be carried, not buried:** (a) M4 day-capped residual +5.87 (ETH/SOL);
  (b) the M3 D-placebo failure (activity-is-a-trigger lean). Both are gross, single-epoch, post-hoc-adjacent.
- **B−D is aggregation-dependent and confounded:** day-capped significant, clean episode-pairs not; wallet events
  sit on ~13% larger trailing moves (195 vs 174 bp) — the matched control doesn't fully balance move magnitude.
- **Single historical epoch, gross-of-cost persistence.** The +14 bp decile gross is coin-month-neut markout, not
  net and not funding-adjusted. The mechanical fade itself is a live *unprosecuted* positive that has not had its
  own standalone gauntlet (net / funding / impact / own OOS).
- **Only forward data resolves it.** The frozen Phase-3 nested-model forward experiment (M0 market-state vs M1 +wallet,
  primary H1 = day-capped net(B−A) > 0, MDE≤5 bp target ≈ ≥250–300 forward coin-days) is the specified resolution;
  the historical window is non-admissible as confirmatory. Source: ledger L608–627, `docs/PHASE3_FORWARD_SPEC.md`.
- **Numbers to reconcile with sibling report sections:** the "generic reversal" language was softened to "TRIGGERED"
  in audit round 3 — ensure this section and any Stage-L / Stage-K section agree (Stage-L DIR-mrev was relabeled
  INCONCLUSIVE; the mechanical fade is registered as a live positive needing its own gauntlet).
