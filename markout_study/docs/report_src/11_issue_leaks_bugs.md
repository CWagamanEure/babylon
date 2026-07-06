# Issues & Solutions, Part C — Leaks & Bugs We Found in Our OWN Pipeline

*Report source. Every bug below was caught by our own adversarial audits (multi-agent
audit rounds 2 & 3, 2026-07-05) and fixed, with the before/after numbers re-run cleanly.
This section documents the rigor: we prosecuted our own positives and killed the ones that
were artifacts.*

Source: `markout_study/docs/FINDINGS_LEDGER.md` (Stages M1–M4, "Canonical cohort freeze");
memory `babylon-markout-study.md`. Exact line numbers cited per fact.

---

## FACTS

### Bug 1 — Test-activity in wallet SELECTION (`te_nd` / `tend>=8`) inflated the positives → moved to eval-time attrition + train-only freeze

**What it was.** The wallet cohort was selected using a filter that required a minimum number
of *test-side* trading days (`te_nd>=15` in M1; `tend>=8` in M3/M2-deploy). Requiring test
activity to be *eligible for selection* leaks test-side information into the frozen set — it
preferentially keeps wallets that happened to stay active (and, conditionally, well-behaved) in
the evaluation window. The fix is to freeze the cohort on **train-only** ranking and treat
insufficient test coverage as **eval-time attrition** (drop, no replacement), not selection.

**M1 before → after** (ledger `FINDINGS_LEDGER.md:467-474`):
- The bug: "`te_nd≥15` sat in the *selection* filter (test-side info) → moved to train-only
  freeze + eval-time attrition."
- **Family A (copyability):** +6.9 bp (p=0.08) → **+3.75 bp [−7.6, +15.3], p=0.26.**
- **Family B (incremental vs fade):** "+7.9 beats fade" (p=0.15) → **+1.54 EW / −1.95 pooled bp,
  p=0.44–0.63, 0/12 RW** — i.e. the fade-beating was "**largely a selection-leak artifact**;
  done clean there is no incremental edge over the mechanical fade."
- Attrition made concrete: 12/20 wallets evaluable, **8/20 attrition** (insufficient test
  coverage), incl. 4 of the top-10 train ranks with ZERO test days (`FINDINGS_LEDGER.md:473,478`).

**M3 before → after** (ledger `FINDINGS_LEDGER.md:583-588`, and reframe note `:536`):
- The bug: M3 (and M2-deploy) "re-derived the wallet set inline with `tend>=8` (test-activity)
  in selection." Fixed to "**TRAIN-ONLY selection (170-wallet top-decile, 44 attrition
  no-replacement)**."
- Cohort size shifted from the leaked **99 → 170 wallets** (`FINDINGS_LEDGER.md:536`).
- The leak was mildly **deflating** the key wallet-vs-control gap (B−D), so removing it did NOT
  flip the verdict — it slightly strengthened the point estimates (see Bug 2 for the paired
  numbers), and qualitative verdict (4) was unchanged (`FINDINGS_LEDGER.md:587-588`).

**Lesson recorded** (memory `babylon-markout-study.md:83-84`; ledger `:124-125`): "a
test-activity filter (`te_nd`) in SELECTION silently inflated the positive; always freeze on
train-only and drop insufficient-coverage wallets at EVALUATION as attrition."

---

### Bug 2 — Test-fitted matched-control bin boundaries → train-fitted (frozen)

**What it was.** In M3, the matched-control arm (D = mechanical fade at non-wallet timestamps
matched on coin×month×tod×`tret`-quintile×vol-tertile) had its **quintile / tertile bucket
boundaries fitted on TEST bars**. Fitting the matching grid on the same data you evaluate on is
a second test leak (it lets the control adapt to the test distribution). Fix: **train-fitted,
frozen bucket boundaries**.

**Before → after** (ledger `FINDINGS_LEDGER.md:583-588`) — this correction was applied jointly
with the Bug-1 train-only selection fix:
- **B−D day-capped:** +10.64 bp (p=0.044) → **+12.35 bp [+2.2, +23.1], p=0.014.**
- **B−D episode-level:** +4.44 bp (p=0.47) → **+6.61 bp [−5.4, +18.8], p=0.28.**
- **A−B:** −2.5 → **−3.3** (n.s.) — wallet DIRECTION still adds nothing.
- **B−C:** +12.5 → **+12.9, p<0.001** — wallet activity still beats blind fading.
- Residual confound that PERSISTS after the fix: `|tret|` imbalance, wallet events sit on
  **195 bp vs matched 174 bp** trailing moves (`FINDINGS_LEDGER.md:587`) — this is what M4 was
  built to resolve.
- Net direction of the leaks: "Leaks were mildly **DEFLATING** B−D; qualitative verdict (4)
  unchanged" (`FINDINGS_LEDGER.md:587-588`).

---

### Bug 3 — James-Stein SHRINKAGE-COLLAPSE in the recurrence instrument (`cohort_M2_recurrence.py`)

**What it was.** The within-month James-Stein `shrink()` step collapsed to a constant when its
between-wallet variance estimate went to zero: **tau2=0 in 4 of 11 months**. When tau2=0 the
shrinkage maps every wallet to the same shrunken value, so the top-decile flag fired on **100%
of wallets** in those months, inflating the recurrence and transition counts by **~10–22×**.
Fix: **fall back to the raw m4 rank when tau2<=0** (`FINDINGS_LEDGER.md:505-507`).

**Before → after** (ledger `FINDINGS_LEDGER.md:505-517`):
- **Recurrence (≥3-month repeat top-decile):** **403 → 48 wallets** (48 vs 35 by luck, p=0.017).
  The full recurrence table also deflated: ≥4mo 9 vs 5 (p=0.066), ≥2mo 204 vs 184 (p=0.059);
  "was 403/686/1107" (`FINDINGS_LEDGER.md:513-514`).
- **Discrete transition P(top|top):** **3.2× (p<1e-4) → ×1.09 (0.109 vs 0.10), p=0.22 — NOT
  significant** ("the discrete top→top persistence essentially vanishes once corrected")
  (`FINDINGS_LEDGER.md:511-512`).
- **What SURVIVES the fix** (the load-bearing, un-inflated evidence — the IC/forward-decile
  auto-dropped the collapsed months): adjacent-fold rank-IC **8h +0.093 [+0.061, +0.126], 10/10
  folds, sign-p=0.002** (also 4h +0.081, 24h +0.085, all CI-excl-0); top-decile **forward edge
  +5.72 vs field +1.24 = +4.48 bp [+2.17, +7.54], 9/10 folds** (`FINDINGS_LEDGER.md:508-511`).
- **Net reframe:** "rank persistence is a small, real, cross-fold-consistent effect (IC ~0.09,
  forward decile +4.5bp); the strong recurrence/transition magnitudes were a shrinkage artifact"
  (`FINDINGS_LEDGER.md:515-517`). This is a rare case where a bug fix demoted our OWN over-claim
  (the "3.2× persistence" story) rather than inflating a null.

---

### Bug 4 — Missing positive-control MDE added to M4 (window is BLIND below ~11–16 bp)

**What it was.** M4's frozen continuous-control residual test reported a positive point estimate
with no power calibration — exactly the pattern the over-nulling gate forbids (you cannot call a
non-significant positive a "null" without showing the test could have detected the effect you
care about). Audit round 3 **added a positive-control MDE** (`FINDINGS_LEDGER.md:597-599`).

**The added calibration** (ledger `FINDINGS_LEDGER.md:595-599`):
- Bootstrap SE = 5.81 on 122 test coin-days → **MDE(95% CI excl 0) ~11.4 bp, MDE(80% power)
  ~16.3 bp.**
- Injection check: **injecting +5 bp is NOT detected; +10 bp is** → "the window is **BLIND by
  construction below ~11–16 bp ≫ the ~5 bp we'd care about.**"
- **Consequence for the verdict:** the pre-registered PRIMARY day-capped residual **+5.87 bp
  [−5.54, +17.66], p=0.15** (ETH +11.4 / SOL +12.0-driven) is reclassified from an implied "no
  residual skill" to a **LIVE UNDERPOWERED POSITIVE, not a null** — gate condition 2 (MDE ≤
  care-about) fails, so it is unresolved, not disproven (`FINDINGS_LEDGER.md:599-605`).
- Context: at the *per-event* level the state fully explains the fade advantage (realized +7.44
  vs **predicted +8.74**; per-event residual **−1.30 bp [−15.6, +13.0], p=0.57 ≈ 0**) — so the
  event-level "wallets mark observable setups" reading is clean; it is only the day-capped
  estimand the window cannot resolve (`FINDINGS_LEDGER.md:595-597`).

**Lesson recorded** (memory `babylon-markout-study.md:124-125`): "always add a positive-control
MDE before any inconclusive-vs-null call."

---

### Bug 5 — Three conflated "top-decile" cohorts → one canonical TRAIN-ONLY cohort frozen to disk

**What it was.** Across stages the "top-decile" wallet set had been re-derived inline three
different ways, producing three incompatible cohorts, some of them leaked (`cohort_M_freeze.py`,
`FINDINGS_LEDGER.md:609-612`):
- **recurrence set = 686 wallets** (all-months),
- **deploy-leaked set = 99 wallets** (the `tend>=8` test-activity leak, Bug 1),
- **train-only set = 170 wallets.**

**The fix** (ledger `FINDINGS_LEDGER.md:609-612`): define ONE **CANONICAL = TRAIN-ONLY,
recurrence-based on `neut_8h`**: top-decile in **≥2 of 6 train months → PRIMARY 121 wallets**
(STRICT ≥3mo = 28), plus a continuous conviction rank + traits, **persisted to
`out/cohort_M_frozen.{txt,parquet}`**. Critically: "**All downstream reads the file (no more
inline re-derivation)**" — the frozen-to-disk artifact is what structurally prevents the leak
from recurring.

**Lesson recorded** (memory `babylon-markout-study.md:124`): "never re-derive a 'frozen' set
inline with a test-activity filter (save to disk)."

---

## Summary table (before → after)

| # | Bug | Metric | Before | After |
|---|-----|--------|--------|-------|
| 1 | `te_nd`/`tend>=8` in selection | M1 Family A | +6.9 bp (p=0.08) | +3.75 bp [−7.6,+15.3] (p=0.26) |
| 1 | `te_nd`/`tend>=8` in selection | M1 Family B (vs fade) | +7.9 (p=0.15) | +1.54 EW / −1.95 pooled (0/12 RW) |
| 1 | `te_nd`/`tend>=8` in selection | M3 cohort size | 99 (leaked) | 170 (train-only, 44 attrition) |
| 2 | Test-fitted matched bins | M3 B−D day-capped | +10.64 (p=0.044) | +12.35 [+2.2,+23.1] (p=0.014) |
| 2 | Test-fitted matched bins | M3 B−D episode | +4.44 (p=0.47) | +6.61 [−5.4,+18.8] (p=0.28) |
| 3 | Shrinkage collapse (tau2=0) | Recurrence ≥3mo | 403 | 48 (vs 35 luck, p=0.017) |
| 3 | Shrinkage collapse (tau2=0) | Transition P(top\|top) | 3.2× (p<1e-4) | 1.09× (p=0.22, n.s.) |
| 4 | Missing positive-control MDE | M4 window MDE | (not computed) | ~11.4–16.3 bp; blind <+10 bp |
| 5 | 3 conflated cohorts | Cohort definition | 686 / 99 / 170 (inline) | 121 canonical (frozen to disk) |

---

## FIGURES TO MAKE (optional)

All are simple, data-light before/after bars — no bar-pricing or tape scans; the numbers are
already in the ledger.

1. **Selection-leak deflation (Bug 1).** Grouped bar: M1 Family A (+6.9 → +3.75) and Family B
   (+7.9 → +1.54) before vs after the train-only freeze, with error bars where CIs are recorded
   (Family A after = [−7.6, +15.3]). Caption: leaking test activity into selection inflated both
   families; the incremental-over-fade edge was ~entirely a leak artifact.
2. **Shrinkage-collapse deflation (Bug 3).** Two-panel before/after: (a) recurrence count
   403 → 48; (b) transition multiple 3.2× → 1.09× (mark the p=0.22 n.s. band). Optionally a third
   panel showing what SURVIVED (IC 8h +0.093 10/10, forward-decile +4.48 [+2.17,+7.54]) to make
   the "small-but-real" point.
3. **M4 blindness gauge (Bug 4).** A single horizontal number line: care-about ~5 bp, point
   estimate +5.87, MDE(95%) ~11.4, MDE(80%) ~16.3 — visually showing the estimate sits inside
   the blind band → underpowered, not null.
4. **Cohort reconciliation (Bug 5).** Simple 686 / 99(leaked) / 170 → 121-canonical funnel to
   illustrate the "one frozen set" resolution.

(Optional; the tables above carry the report on their own.)

---

## GAPS / open items

- **Exact M2-deploy cohort provenance.** The ledger reports the deploy gate on the leaked
  **99-wallet** decile (`FINDINGS_LEDGER.md:538`, alpha-vs-fade +1.00 p=0.44); it was NOT re-run
  post-leak-fix on the 170/121 set. The verdict (persistence = triggered short-horizon reversal,
  no incremental wallet skill demonstrated) is argued to be leak-robust because alpha is
  differenced at identical entries, but the clean re-run number is not in the ledger. Flag as a
  should-verify if the report leans on the deploy alpha figure.
- **`|tret|` imbalance is not a fixed bug — it is a residual confound.** After Bugs 1 & 2 the
  matched control still leaves wallet events on ~195 bp vs 174 bp trailing moves
  (`FINDINGS_LEDGER.md:587`); M4 was the attempt to control it continuously, and M4 is itself
  blind (Bug 4). So the wallet-vs-control question remains genuinely UNRESOLVED, not closed by
  these fixes.
- **No committed unit test / regression is referenced** for the tau2=0 shrinkage fallback or the
  train-only freeze; the fixes are described as re-runs. If the report claims "guarded against
  recurrence," confirm whether guards are in code (the frozen-to-disk artifact for Bug 5 is the
  one structural guard actually described).
- **`cohort_M4_residual.py` coin-curvature misspecification** is flagged as a possible alternative
  explanation for the ETH/SOL-concentrated +5.87 (`FINDINGS_LEDGER.md:603`); not itself a
  fixed bug, but relevant if the report characterizes M4's residual as clean.
