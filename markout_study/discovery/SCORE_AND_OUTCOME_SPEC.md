# SCORE_AND_OUTCOME_SPEC — exact, reproducible Gate-A math

Every quantity is estimated using data **strictly before** its reference cutoff. C = a monthly walk-forward cutoff; m = the evaluation month immediately after C. h ∈ {1,2,4,8} h. All markouts are **gross signed** bp. This doc is normative for §A.3/A.7/A.10/A.11 of `PREREGISTRATION_v2.md`.

---

## 1. Episode markout (naming per EPISODE_SPEC §Entry-price convention)
Episode e of wallet w: `entry_price_ts(e)` = first 5-min close strictly after the opening `fill_ts`; `endpoint_price_ts(e,h) = entry_price_ts(e)+h`; direction `d_e ∈ {+1,−1}`:

  m(e,h) = d_e · ( P(endpoint_price_ts(e,h)) / P(entry_price_ts(e)) − 1 ) · 1e4   [bp]

An episode contributes at horizon h **only if its endpoint is observed before the reference cutoff**: `endpoint_price_ts(e,h) < C` for training scores (h_max=8 h ⇒ 8-hour purge); for the realized outcome the endpoint must exist on the tape (final-month incomplete endpoints omitted, never zero-filled). No censored endpoint is ever assigned a value. This is pure gross markout — no latency/cost.

## 2. Wallet-day aggregation (handles multiple episodes/day, fragmentation)
For wallet w, calendar day d:

  M(w,d,h) = mean over e ∈ episodes(w,d) of m(e,h)

One value per (wallet, day, horizon). This is the atomic unit; days with many fragmented episodes get weight 1, not N (fixes D3 at the statistic level).

## 3. Training-window wallet aggregation
Over the training window ending at C (wallet-days with d < C, purged per §1):

  Zbar(w,C,h) = mean over eligible wallet-days d of M(w,d,h)
  n(w,C,h)   = # eligible wallet-days for w at horizon h

Wallets active in multiple coins: wallet-days are pooled **across coins** (the score is a wallet-level, coin-pooled quantity; coin specialization is admissible value — §9 of prereg). Per-coin decomposition is diagnostic only.

## 4. Horizon standardization (cross-sectional scale, pre-C only) — item 8
Across the eligible **wallet** cross-section at C (each wallet one point, coin-pooled), per horizon, with q1 = 1st and q99 = 99th cross-sectional percentiles of {Zbar(·,C,h)}:
- **clip each wallet's own value:** `Zc(w,C,h) = clip( Zbar(w,C,h), q1, q99 )`,
- μ(C,h) = mean of {Zc(·,C,h)},  σ̂(C,h) = SD of {Zc(·,C,h)} (denominator N−1),  scale s(C,h)=1/σ̂(C,h),
- **standardized value:** `z(w,C,h) = ( Zc(w,C,h) − μ(C,h) ) / σ̂(C,h)` — the wallet's **clipped** value is used in the numerator, so extreme wallets do not remain extreme in the score after a winsorized scale.

Scale is computed **across wallets** (not wallet-days/episodes), **coin-pooled**, `d < C` only. **Degenerate scale:** if σ̂(C,h)=0 or q1==q99 for any horizon, the cross-section is **degenerate** and the fold is **unrankable** (§7b) — this is *not* treated as identity clipping. The cross-section must have ≥ **N_min = 100** wallets (fixed; feasibility-checked by the counts audit); below that the fold is unrankable.

## 5. Band score (pre-shrinkage), missing-horizon rule
  Zband(w,C) = (1/H_w) · Σ_{h ∈ H_w} z(w,C,h)

where H_w = the horizons at which w has ≥ **J = 20** eligible wallet-days (fixed; feasibility-checked by the counts audit, **not** optimized on positive-control recovery). A wallet is **scoreable (training)** only if |H_w| ≥ **3 of 4** horizons. Equal weight across present horizons. (Evaluation requires **4 of 4** — §9.)

## 6. Sampling variance — weekly cluster bootstrap (change 4, frozen)
V(w,C) = variance of Zband(w,C) under a **weekly cluster bootstrap** — dependence-aware (a wallet's within-week days are correlated), simpler than any block/moving scheme. Purpose: estimate **cross-sectional shrinkage reliability only** — it does **not** provide headline time-series inference (that is the calendar-month fold sign test).
- **One cluster = one active calendar week** (ISO week with ≥1 eligible wallet-day). That cluster contains **all of the wallet's active wallet-days, across all coins and all four horizons, in that week — and they move jointly** (a sampled week brings its entire contents together; days/coins/horizons are never split).
- Resample **whole weeks with replacement**, B = 1000; **stable seed** `seed(w,C) = int(sha256(GLOBAL_SEED ∥ w ∥ C)) mod 2³²`.
- Each draw uses the wallet's **original frozen horizon set H_w** and the frozen μ(C,·), σ̂(C,·); eligibility/horizon sets are **frozen on the original sample** (not re-tested per draw).
- **No redraw-until-success:** a draw lacking any horizon in H_w is marked **invalid** (not resampled away); the **invalid-draw fraction** is reported.
- **Scoreability floor (change 2 — no population-prior selection):** the weekly bootstrap requires **≥ 6 active calendar weeks**. A wallet with **< 6 active weeks is UNSCOREABLE for the primary ranking and cannot be selected** (there is no wallet-specific reliability estimate for it) — it may **not** enter the basket via the min-20 rule or the hash tie-break. Such wallets remain in counts/liveness reporting only. **No population-prior-only wallet enters the performance-ranked basket.**

Captures within-week dependence and the cross-horizon correlation directly.

## 7. Empirical-Bayes shrinkage (normal–normal, method-of-moments)
Across the scoreable cross-section at C:
- μ̂_C = cross-sectional mean of Zband(w,C)  (≈0 by construction; computed, not assumed),
- τ̂²_C = max( 0, Var_w[Zband(w,C)] − mean_w V(w,C) )   (between-wallet signal variance),
- shrinkage weight  λ(w,C) = τ̂²_C / ( τ̂²_C + V(w,C) ),
- **posterior (item 12):**  θ_w | Zbar_w ~ N( θ̂(w,C),  τ̂²_C·V(w,C)/(τ̂²_C+V(w,C)) ),  with **posterior mean** θ̂(w,C) = μ̂_C + λ(w,C)·(Zband(w,C) − μ̂_C),
- the quantity  τ̂²_C·V(w,C)/(τ̂²_C+V(w,C)) = λ(w,C)·V(w,C) is the **posterior variance of the latent wallet effect θ_w** (NOT the variance of the posterior mean),
- **tie-break key:**  P( θ_w > μ̂_C ) = Φ( ( θ̂(w,C) − μ̂_C ) / sqrt( λ(w,C)·V(w,C) ) ).

Reliability enters through V(w,C). **No `R_C ≥ 0.05` reliability-ratio gate** (removed — change 3).

### 7b. Unrankable-fold rule (change 3, frozen)
A fold is **unrankable** iff **any** of: the eligible cross-section is below **N_min = 100**; the cross-sectional scale is **degenerate** (§4); estimated between-wallet variance is non-positive (**τ̂²_C ≤ 0**, so λ≡0, all θ̂ identical, no ordering); or the estimator otherwise cannot produce a meaningful ordering. An unrankable fold forms **no basket**, is logged `unrankable`, and is **not** repaired by a replacement estimator or a post-hoc variance floor. It **does not count toward F**; if **>50% of candidate folds are unrankable or evaluation-insufficient**, the verdict is **INCONCLUSIVE/INFEASIBLE**, not FAIL.

## 8. Worked example (hypothetical wallet W at cutoff C)
Cross-section at C: μ(C,·) = {2, 3, 5, 8} bp, σ̂(C,·) = {40, 55, 80, 120} bp.
Wallet W: Zbar(W,C,·) = {12, 18, 30, 40} bp, n(W,C,·) = {25,25,25,25} wallet-days, all 4 horizons present.

- z(W,C,·) = {(12−2)/40, (18−3)/55, (30−5)/80, (40−8)/120} = {0.250, 0.273, 0.313, 0.267}
- Zband(W,C) = mean = **0.2756**
- Weekly cluster bootstrap ⇒ V(W,C) = **0.0100** (SD ≈ 0.10)
- Population: μ̂_C = 0.00, Var_w[Zband] = 0.090, mean_w V = 0.020 ⇒ τ̂²_C = 0.090 − 0.020 = **0.070**
- λ(W,C) = 0.070 / (0.070 + 0.010) = **0.875**
- θ̂(W,C) = 0 + 0.875 · (0.2756 − 0) = **0.2412**
- **Posterior variance of the latent effect** λV = 0.875 · 0.010 = 0.00875 ⇒ SD = 0.0935 (this is Var(θ_W | data), **not** the variance of the posterior mean)
- P(θ_W > 0) = Φ(0.2412 / 0.0935) = Φ(2.58) = **0.995**

Every number above is mechanically reproducible from the inputs; no implementation choice is left implicit.

---

## 9. Realized next-month Gate-A outcome (FROZEN — exactly one)
For wallet w in evaluation month m, using pre-month scales only:

  Yband(w,m) = (1/4) · Σ_{h ∈ {1,2,4,8}} s(m−1,h) · Mbar(w,m,h)

- Mbar(w,m,h) = wallet w's month-m gross signed markout at horizon h, aggregated **first by wallet-day (§2) then across wallet-days** in month m,
- s(m−1,h) = 1/σ̂(m−1,h), the horizon scale estimated **before** month m — the evaluation month never supplies its own standardization,
- Yband is **scaled but not re-centered** (no μ subtracted), so its sign is the wallet's signed performance.

**Completeness (item 7 — frozen):** Yband(w,m) is **defined only when w has ≥1 valid wallet-day outcome at ALL FOUR horizons** in month m. No missing horizon is zero-filled. Training scores may still use ≥3-of-4 horizons (§5), but **evaluation uses 4-of-4** for outcome comparability. A 3-of-4 realized outcome (dividing by present horizons) is a **pre-registered sensitivity only** and cannot replace the primary.

**Raw absolute band markout (for the positivity object — change 1):**

  Aband(w,m) = (1/4) · Σ_{h ∈ {1,2,4,8}} Mbar(w,m,h)     [raw bp, equal-weight, NOT scaled]

Aband is defined on the same 4-of-4 complete-outcome wallets as Yband. Yband (scaled, dimensionless) drives the **ranking**; Aband (raw bp) is the **interpretable absolute** performance. Raw per-horizon Mbar(w,m,h) are reported as decomposition; **no best horizon is selected.** Mbar(w,m,4h) is the preselected Gate-B holding outcome only.

## 10. Gate-A outputs — relative ranking (verdict) vs absolute positivity (report) — changes 1, 2
All cross-sectional statistics — **rank IC, decile assignments, and selected-minus-field** — run over the **scored cross-section only** (§11: eligible, scoreable, finite θ̂; wallets that cannot be ranked are excluded from selected, field, IC, and deciles alike). Within it, statistics are **conditional on a complete 4-of-4 next-month outcome** (§9); inactive/incomplete wallets are **never zero-filled** and never removed on the sign/magnitude of return. Every group/decile reports evaluation-active count, complete-outcome count, and fractions. Liveness/attrition and eligible-but-unscoreable wallets are reported separately (`FUTURE_ACTIVITY_AND_ATTRITION.md`).

### The verdict object (RANKING)
**`Δ_relative,m`** = mean_{w∈selected, complete} Yband(w,m) − mean_{w∈field, complete} Yband(w,m), equal-weight per wallet. This is the **sole deterministic ranking verdict** via the monthly sign test:
- valid-fold count F = # folds that are **rankable** (§7b) **and evaluation-sufficient** = **≥10 complete-outcome selected AND ≥50 complete-outcome field wallets**. Decile density and selected-completeness rate are **descriptive only** and never gate fold validity — a sparse-decile month still contributes to the sign test and reports its decile curve as "sparse/unavailable";
- pass threshold **k(F) = min{ k∈{0,…,F} : P[Binomial(F,0.5) ≥ k] ≤ 0.05 }**. **At α=0.05 under the one-sided exact sign test, no rejection is possible with F<5 valid folds, so F<5 is automatically INCONCLUSIVE.** The implementation **computes and verifies k(F) mechanically** from the binomial (not a hard-coded table); if no k satisfies the inequality, INCONCLUSIVE;
- **PASS** iff Δ_relative,m > 0 in ≥ k(F) folds; **FAIL** iff enough valid folds exist and it does not pass; **INCONCLUSIVE** iff too few valid folds or >50% of candidate folds are unrankable/evaluation-insufficient. (The positive control is a **pre-run gate**, not part of this real-data table — see execution order.)
- **Independence caveat (mandatory):** the one-sided binomial p is **exact only conditional on independent monthly fold signs.** Because wallets recur and the training window expands, serial dependence between monthly outcomes may reduce the effective evidence. Report **lag-one autocorrelation of `Δ_relative,m` and of the sign sequence** as limitation diagnostics; they **do not alter** the frozen verdict.

### The positivity object (ABSOLUTE — reported, NOT part of the verdict)
**`A_selected,m` = mean over complete-outcome selected wallets of `Aband(w,m)`**, where `Aband(w,m) = ¼ Σ_h Mbar(w,m,h)` in **raw bp** (§9). Reported positive or negative each month + pooled. **Also report the selected-wallet raw mean separately at 1 h, 2 h, 4 h, and 8 h**, so the band average cannot conceal that positivity exists at only one horizon. **A positive `Δ_relative` with negative `A_selected` is reported as "ranking separates better-from-worse wallets, but selected wallets' gross markout is still negative" — NOT "found positive-markout wallets."** Absolute positivity never merges into the ranking verdict.

### Mandatory descriptive corroboration (cannot veto or rescue the verdict)
**(a) Rank IC:** IC_m = Spearman(θ̂(w,m−1), Yband(w,m)) over complete-outcome wallets — individual wallets, never 10 decile means. **(b) Decile gradient:** deciles by prior-data θ̂; per-month equal-wallet mean Yband per decile (report counts); pooled curve = Spearman across the **ten month-equal decile averages** (never pool wallets across months); report all 10 deciles + top-minus-bottom. **(c) Leave-one-wallet/-coin/-month** recomputations of Δ_relative.
These are **related summaries of the same ranking and outcomes — not independent confirmations** — and are **mandatory to report** but **cannot change** the sign-test verdict.

## 11. Non-selected field — the scored cross-section (canonical definition)
**The field consists of all wallets that were eligible, scoreable, successfully assigned a finite θ̂, and included in the same frozen ranking cross-section at cutoff C, but were not selected.** A wallet with fewer than six active weeks, an invalid bootstrap estimate, missing required training horizons, or any other condition preventing it from being ranked **cannot enter either the selected group or the field.**

This **same scored-cross-section rule** governs every cross-sectional evaluation statistic — **wallet rank IC, decile assignments, selected-minus-field, and field completeness/activity reporting** all run over the scored cross-section only. Within that set, the contrast uses **complete-outcome** wallets (4-of-4 Yband); coin specialization and directional beta are allowed (gross estimand) then decomposed diagnostically; the comparator is the equal-weight mean of per-wallet Yband over complete-outcome field wallets — never a pooled mean over episodes, never zero-filled. **Eligible-but-unscoreable wallets are reported separately in the attrition/accounting table** (`FUTURE_ACTIVITY_AND_ATTRITION.md`), never in the field.

## 12. Gate-C benchmarks — two distinct objects (item 8)
**(i) Diagnostic timestamp-matched benchmark (descriptive only).** A mechanical fade / market-state direction evaluated **at the wallets' own entry timestamps**. Answers: does wallet *direction* add value given the wallet already supplied the *timing*? Not a make-or-buy answer.

**(ii) Standalone public-strategy benchmark = Gate C.** Generates its **own** entries from prior-fitted public market-state rules (fitted on data before each fold). It must **not** use wallet timestamps, wallet activity, selected-wallet direction, or wallet trade occurrence. Matched to the wallet strategy on eligible coins, evaluation months, latency, cost schedule, exit horizon, portfolio capital, concurrency, coin caps, and an approximately comparable trade/risk budget. Gate C asks: is the wallet layer preferable to independently running the public strategy? Only object (ii) can answer make-or-buy.
