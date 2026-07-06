# OOS-Persistence — Reliability-Aware Sweep + Distributional + All-Horizons (addendum v2)

**Status:** v2, post-audit (metric-math + multiplicity/power). Extends the audited
`PERSISTENCE_ARCHITECTURE.md` v2. Base purge/joint-null/cohort/control machinery UNCHANGED. This adds
(a) depth-aware ranking metrics, (b) a distributional view, (c) a per-horizon sweep over all 12
horizons — plus the two audit BLOCKERS' fixes: a **grid-wide global permutation null** and a
**pre-registered adversarial-kill protocol** for any survivor. `[Ax]` = audit finding.
**Framing (per user + audit):** built to DETECT with power per horizon, and to KILL any positive
before believing it. Still performance-only; the step BEFORE features. **Date:** 2026-07-04

---

## 0. Why
The base ranker is **noise-limited**: none of its 5 metrics rewards evidence depth, so a
+500 bp/30-trade lucky wallet outranks a +40 bp/2000-trade reliable one (the winner's curse). If a
**reliability-aware** ranking persists where raw edge does not, the edge is real and we ranked wrong.
That is the hypothesis. Either outcome is performance-only and evidence-depth-bounded (see §8).

## 1. New ranking metrics (reward reliability) — math fixed
Per wallet on the **purged-train, per-split** pool (μ, τ², field-scale floor all estimated there —
NO test quantity; leak surface confirmed clean `[math-#4]`). Add one aggregate to `wallet_agg`:
`sum_w2 = Σ r_w²` (winsorized 2nd moment) `[math-M1]`.

- **t-stat** `= √n_i · mean_w_i / std_eff_i`, where **`std_eff_i = max(std_raw_i, 0.15·field_std_raw,
  EPS)`** — a field-scale denominator floor reusing the `SORTINO_K=0.15` precedent
  (`markout_stats.py:108`). Without it, near-degenerate wallets (tiny std, esp at 5m where n is huge
  and same-bar entries collapse dispersion) get a huge finite t-stat and hijack the top-50
  `[math-B1]`. `field_std_raw` = std of raw markout over the purged-train set (per coin,horizon,split).
  It is a *ranking score*, not a Student-t (winsor-mean over raw-std is deliberate & conservative:
  tail-luck wallets are doubly attenuated) — kept faithful to base `sharpe·√n`. `[math-ruling]`
- **eb_edge** — empirical-Bayes shrunk equal-weight edge. Per wallet: `s_i² = (sum_w2 − sum_w²/c)/(c−1)`
  (WINSORIZED variance, consistent with `avg_i` `[math-M1]`), `v_i = s_i²/n_i`. Prior:
  `τ² = max(Var_i(avg) − mean(v_i), 0)`; **grand mean is precision-weighted (GLS)**:
  `μ = Σ(avg_i/(τ²+v_i)) / Σ(1/(τ²+v_i))` (mean of per-wallet `avg_i`, NOT pooled Σr_w/N) `[math-M2]`.
  `B_i = τ²/(τ²+v_i)`, `eb_i = μ + B_i(avg_i − μ)`. **τ²≈0 degenerate guard:** if `τ²` ≈ 0 (all B_i→0,
  every eb_i→μ → arbitrary lowest-id tie), mark the (coin,horizon,split) cell **degenerate and skip**
  it (mirror the thin-split `pool<K` skip) — never rank by id `[math-M3]`. τ² MoM is approximate under
  heteroskedastic v_i; DerSimonian–Laird is the noted upgrade path `[math-m1]`.
- **Raised activity floor** — robustness AXIS (not a metric): rerun with `FLOOR_TR ∈ {30, 200}`.
  Report pool attrition. **Counts in the multiplicity budget** (§4) `[mult-B1]`.

**Evaluation unchanged:** metrics change only the RANKING; OOS outcome is still the active-only
deployable **vw** cohort edge `S` + joint-null p. Ruling `[math-Q1]`: rank-by-size-blind /
measure-by-vw is the already-audited base design (avg_edge, sharpe) — not a leak, cannot manufacture
persistence; it can only *reduce power* (EB optimizes an equal-weight target scored on a volume
target). State that power caveat; turnover-aware shrinkage is an optional upgrade, not required.
NB **eb_edge is a reliability-tilt of avg_edge**, not an orthogonal axis (`B→1`⇒avg_edge, `B→0`⇒μ) —
account for that in multiplicity and do NOT treat it as independent evidence `[math-m4]`.

## 2. All 12 horizons, per-horizon (NOT pooled)
Identical rank-and-measure at EACH ladder horizon, ranking-h == measurement-h (no cross-horizon
argmax — that is a winner's curse across the term structure `[mult-M3]`). `markout_ret` already
returns 12 columns in one pass. **Censoring segregation `[mult-B1]`:** gate every cell on its scorable
fraction; route censoring-dominated long horizons (≥72h, and any cell below a scorable-fraction
threshold) to a clearly-labeled **"censoring-dominated, non-inferential" stratum OUTSIDE** the primary
global-null/FDR family — else 48/72/168h low-N noise pumps the false-positive floor (base found 6
raw-sig cells, all 168h). Short-horizon caveat: at 5m, t-stat degenerates toward an n-ranking
(√n unbounded → ≈ most-active-positive wallets, close to cum_pnl) — flag so it isn't read as
"reliability" `[math-m3]`.

## 3. Distributional persistence (descriptive) — "is the mean tail-dragged?"
For the train-selected top-K cohort, per (coin,horizon), compare the cohort markout distribution
TRAIN vs TEST (and vs field). **Fixes `[mult-Q4]`:** use a **single frozen cap on both windows** (per-
split caps would make pooled tails a cap-mixture artifact); **headline only LOCATION (mean, median)
from the cross-split pool**; show **shape (skew, p5/p95, tail-loss fraction) as per-split panels**, and
label any pooled tail stat explicitly as a regime-mixture not attributable to cohort shape. The
mean-vs-median/tail-loss decomposition is the right lens (does central location persist while the mean
regresses = real center + tail risk, vs whole-distribution collapse). Always show the **turnover-
weighted (deployable) location beside the median.** **Verbatim caveat in the output `[mult-M2]`:**
> "This view carries no multiplicity control and no power statement; a persistent median is size-blind
> (pitfall #18) and is NOT evidence of deployable edge — it cannot upgrade a joint-null null and must
> be confirmed by the turnover-weighted global null."

## 4. Multiplicity — GLOBAL permutation null is the headline `[mult-B1, Q5]`
Grid = 5 coins × 7 metrics × 12 horizons × 2 floors = **840 evaluations** (the floor axis is counted).
The 12 horizons are the SAME entry priced at different exits (near-perfectly nested) and eb/t-stat are
rank-correlated with avg/sharpe → cells are strongly dependent, so "~21 expected FP, BH handles it" is
**dishonest** (FPs clump into whole horizon columns). Instead:
- **Headline control = grid-wide global permutation null:** one persistent random score per wallet,
  propagated through ALL cells simultaneously; report the **null distribution of "# cells beating
  their own null"** vs the observed count → a calibrated "expected X, observed Y (p=…)" using the true
  cross-cell dependence. Reuses the audited joint-null machinery.
- **BH-FDR is a secondary cross-check only** (validity rests on PRDS under the nesting, can't be
  asserted). Report both; the global null leads.
- **Primary:** `vw_edge@24h` stays the SOLE pre-registered primary (continuity). **`eb_edge@24h` is
  the pre-registered LEAD SECONDARY hypothesis** — reported first within the grid but NOT protected
  from the family, NOT a co-primary (a 2nd protected cell splits alpha and is post-hoc-flavored)
  `[mult-M1, math-m4]`.

## 5. Power per horizon — built to detect, honestly bounded `[mult-M?]`
Run positive/negative/MDE controls per horizon for **BTC AND HYPE** (HYPE = widest null) → an MDE term
structure spanning best-case (BTC) to a wide-null coin `[mult-MAJOR-1]`. MDE rises with horizon
(per-entry vol) and compounds with long-horizon censoring, so a 168h null is the LEAST informative.
- **Every non-power-measured coin's per-horizon null is labeled "power-unknown, MDE ≥ BTC(h)"** — no
  bounded-null claim without a measured MDE for that coin.
- **Every term-structure figure overlays the MDE(h) band**, so a high point inside noise cannot be
  eyeballed as signal `[mult-M3]`. No horizon may be promoted post-hoc; the only route to declaring a
  non-primary cell real is passing the global null AND the §6 kill-gauntlet.
- Interpretation guard instantiates **MDE(coin, h)** per cell (a 168h null reads as a far weaker bound
  than 24h) `[mult-m2]`.

## 6. Adversarial-kill protocol for ANY survivor — PRE-REGISTERED `[mult-B2]`
Given this project's record (every prior "edge" died to a kill-test — stale-candle artifact, z=+3.86
majors-timing), **any cell surviving the global null is a presumptive artifact until it clears ALL
four, pre-registered here before the run:**
1. **Cell-specific label-shuffle** negative control (does the exact cell's significance vanish under
   permuted wallet identity?).
2. **Raw post-fill markout kill-test** (does the edge survive on the plain copyable quantity, no
   winsor / no metric cleverness?).
3. **N-active & cluster inspection** (base survivors were 6–15 wallets over 1–2 splits; apply the
   Jaccard co-trade collapse).
4. **Off-grid replication** (rolling-4 split, the other floor, adjacent horizons — does it reappear?).
Only a survivor clearing all four is a candidate — and still performance-only, still to be verified
with features/BBO before any deployment claim.

## 7. Pitfall checklist (delta — code must satisfy)
1. t-stat denominator floored at `0.15·field_std_raw` (train) — no near-zero blow-up. ✔ §1
2. eb uses winsorized `Σr_w²` variance; GLS precision-weighted μ; τ²=0 → skip+flag. ✔ §1
3. Metrics change ranking only; OOS = deployable vw + joint null; μ/τ²/floor train-per-split. ✔ §1
4. Per-horizon; no cross-horizon argmax; 5m-t-stat & censoring caveats surfaced. ✔ §2
5. Censoring-dominated horizons segregated to a non-inferential stratum. ✔ §2/§4
6. Distributional: frozen cap both windows; location-only headline; size-blind verbatim caveat. ✔ §3
7. Multiplicity = global permutation null (headline) + BH (secondary); floor axis counted (840). ✔ §4
8. Power on BTC+HYPE; non-measured coins power-unknown; MDE(h) band on every figure. ✔ §5
9. Pre-registered 4-step kill-gauntlet for any survivor. ✔ §6
10. Base guards inherited (purge, silent-as-0, frozen test cap, determinism, cand2-only, RAM). ✔

## 8. The sentence the results must carry (verbatim, either outcome)
> "Either outcome is performance-only and evidence-depth-bounded: a cell that survives the global
> permutation null is a HYPOTHESIS to be adversarially killed (cell label-shuffle + raw-markout
> kill-test + N-active/cluster inspection + off-grid replication) before it is believed, and a
> reliability metric that does not survive is INCONCLUSIVE below MDE(coin, h) — not evidence that no
> edge exists."
