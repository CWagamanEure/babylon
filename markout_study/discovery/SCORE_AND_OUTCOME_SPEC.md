# SCORE_AND_OUTCOME_SPEC — exact, reproducible Gate-A math

Every quantity is estimated using data **strictly before** its reference cutoff. C = a monthly walk-forward cutoff; m = the evaluation month immediately after C. h ∈ {1,2,4,8} h. All markouts are **gross signed** bp. This doc is normative for §A.3/A.7/A.10/A.11 of `PREREGISTRATION_v2.md`.

---

## 1. Episode markout
Episode e of wallet w: first-entry bar `t0(e)` (first bar with `ts ≥ entry event` — post-fill, no look-ahead), direction `dir(e) ∈ {+1,−1}`. For horizon h:

  m(e,h) = dir(e) · ( close(t0(e)+h) / close(t0(e)) − 1 ) · 1e4   [bp]

An episode contributes at horizon h **only if its forward endpoint is complete before the reference cutoff**: `t0(e)+h < C` for training scores (h_max = 8 h ⇒ 8-hour purge), and `t0(e)+h` inside month m for the realized outcome. No episode is assigned a value at a horizon whose endpoint is not observed (no censored fills).

## 2. Wallet-day aggregation (handles multiple episodes/day, fragmentation)
For wallet w, calendar day d:

  M(w,d,h) = mean over e ∈ episodes(w,d) of m(e,h)

One value per (wallet, day, horizon). This is the atomic unit; days with many fragmented episodes get weight 1, not N (fixes D3 at the statistic level).

## 3. Training-window wallet aggregation
Over the training window ending at C (wallet-days with d < C, purged per §1):

  Zbar(w,C,h) = mean over eligible wallet-days d of M(w,d,h)
  n(w,C,h)   = # eligible wallet-days for w at horizon h

Wallets active in multiple coins: wallet-days are pooled **across coins** (the score is a wallet-level, coin-pooled quantity; coin specialization is admissible value — §9 of prereg). Per-coin decomposition is diagnostic only.

## 4. Horizon standardization (cross-sectional scale, pre-C only)
Across the eligible **wallet** cross-section at C (each wallet one point, coin-pooled), per horizon:
- winsorize {Zbar(w,C,h)} at the 1st/99th percentile (outlier stabilization),
- μ(C,h) = cross-sectional mean of the winsorized wallet means,
- σ̂(C,h) = cross-sectional SD of the winsorized wallet means (denominator N−1),
- scale s(C,h) = 1 / σ̂(C,h).

Standardized wallet-horizon value:  z(w,C,h) = ( Zbar(w,C,h) − μ(C,h) ) / σ̂(C,h).
The cross-sectional scale is computed **across wallets** (not wallet-days, not episodes) and **pooled across coins**. It uses only d < C data.

## 5. Band score (pre-shrinkage), missing-horizon rule
  Zband(w,C) = (1/H_w) · Σ_{h ∈ H_w} z(w,C,h)

where H_w = the horizons at which w has ≥ J eligible wallet-days (min evidence per horizon; **J resolved by audit-only coverage**, not returns — see AUDIT_ONLY_PLAN.md). A wallet is **scoreable** only if |H_w| ≥ 3 of 4 horizons; otherwise ineligible. Equal weight across present horizons.

## 6. Sampling variance (captures cross-horizon correlation)
V(w,C) = variance of Zband(w,C) under a **wallet-day block bootstrap**: resample w's eligible wallet-days with replacement, recompute Zband using the **frozen** μ(C,·), σ̂(C,·); B = 1000 draws. This estimates Zband's sampling error directly, so the (large) correlation across horizons is captured rather than assumed independent.

## 7. Empirical-Bayes shrinkage (normal–normal, method-of-moments)
Across the scoreable cross-section at C:
- μ̂_C = cross-sectional mean of Zband(w,C)  (≈0 by construction; computed, not assumed),
- τ̂²_C = max( 0, Var_w[Zband(w,C)] − mean_w V(w,C) )   (between-wallet signal variance),
- shrinkage weight  λ(w,C) = τ̂²_C / ( τ̂²_C + V(w,C) ),
- **wallet score (posterior mean):**  θ̂(w,C) = μ̂_C + λ(w,C) · ( Zband(w,C) − μ̂_C ),
- posterior variance  Var(θ̂(w,C)) = λ(w,C) · V(w,C),
- **tie-break key:**  P( θ_w > μ̂_C ) = Φ( ( θ̂(w,C) − μ̂_C ) / sqrt(Var(θ̂(w,C))) ).

Reliability enters through V(w,C), which scales with 1/(active wallet-days) — reliability = active days, not trade count.

## 8. Worked example (hypothetical wallet W at cutoff C)
Cross-section at C: μ(C,·) = {2, 3, 5, 8} bp, σ̂(C,·) = {40, 55, 80, 120} bp.
Wallet W: Zbar(W,C,·) = {12, 18, 30, 40} bp, n(W,C,·) = {25,25,25,25} wallet-days, all 4 horizons present.

- z(W,C,·) = {(12−2)/40, (18−3)/55, (30−5)/80, (40−8)/120} = {0.250, 0.273, 0.313, 0.267}
- Zband(W,C) = mean = **0.2756**
- Wallet-day bootstrap ⇒ V(W,C) = **0.0100** (SD ≈ 0.10)
- Population: μ̂_C = 0.00, Var_w[Zband] = 0.090, mean_w V = 0.020 ⇒ τ̂²_C = 0.090 − 0.020 = **0.070**
- λ(W,C) = 0.070 / (0.070 + 0.010) = **0.875**
- θ̂(W,C) = 0 + 0.875 · (0.2756 − 0) = **0.2412**
- Var(θ̂) = 0.875 · 0.010 = 0.00875 ⇒ SD = 0.0935
- P(θ_W > 0) = Φ(0.2412 / 0.0935) = Φ(2.58) = **0.995**

Every number above is mechanically reproducible from the inputs; no implementation choice is left implicit.

---

## 9. Realized next-month Gate-A outcome (FROZEN — exactly one)
For wallet w in evaluation month m, using pre-month scales only:

  Yband(w,m) = (1/4) · Σ_{h ∈ {1,2,4,8}} s(m−1,h) · Mbar(w,m,h)

- Mbar(w,m,h) = wallet w's month-m gross signed markout at horizon h, aggregated **first by wallet-day (§2) then across wallet-days** in month m,
- s(m−1,h) = 1/σ̂(m−1,h), the horizon scale estimated **before** month m — the evaluation month never supplies its own standardization,
- Yband is **scaled but not re-centered** (no μ subtracted), so its sign is the wallet's signed performance.

This single Yband is used for **all three** Gate-A statistics (§10–11). The raw per-horizon Mbar(w,m,h) in bp are reported separately as economic decomposition; **no single best horizon is selected.** Mbar(w,m,4h) in raw bp is the preselected Gate-B holding-period outcome (only).

## 10. The three Gate-A statistics (defined independently)
**(a) Wallet-level rank IC.** Within month m, across all wallets scored before m:
  IC_m = Spearman( θ̂(w,C=m−1), Yband(w,m) )  over wallets.
Computed on **individual wallets**, never on 10 decile means.

**(b) Decile gradient.** Assign wallets to deciles by prior-data θ̂ only. Per month, equal-wallet mean Yband by decile. Report all 10 deciles, top-minus-bottom, and Spearman across the decile index (1..10) — per month, then summarized.

**(c) Selected-vs-field contrast (equal-wallet — item 6).** Per month m:
  Δ_m = mean_{w ∈ selected} Yband(w,m) − mean_{w ∈ field} Yband(w,m)
each wallet weighted **equally** (selected set and field set each an equal-weight mean of per-wallet Yband). This tests wallet *identification*, not activity concentration. The wallet-day bounded-book contrast is reported as an operational secondary bridging to Gate B, and cannot substitute for this equal-wallet test.

## 11. Non-selected field, defined exactly (item 7)
The field for month m = every wallet that is **eligible in the same fold and not selected**, using identical episode construction, horizons, wallet-day aggregation, missing-horizon rule, and evaluation dates as the selected basket. Coin specialization and directional beta **are allowed** to contribute (gross business estimand), then decomposed diagnostically by coin/direction. The field comparator is the **equal-weight mean of per-wallet Yband over non-selected eligible wallets** — never a pooled mean over all non-selected episodes.

## 12. Gate-C benchmarks — two distinct objects (item 8)
**(i) Diagnostic timestamp-matched benchmark (descriptive only).** A mechanical fade / market-state direction evaluated **at the wallets' own entry timestamps**. Answers: does wallet *direction* add value given the wallet already supplied the *timing*? Not a make-or-buy answer.

**(ii) Standalone public-strategy benchmark = Gate C.** Generates its **own** entries from prior-fitted public market-state rules (fitted on data before each fold). It must **not** use wallet timestamps, wallet activity, selected-wallet direction, or wallet trade occurrence. Matched to the wallet strategy on eligible coins, evaluation months, latency, cost schedule, exit horizon, portfolio capital, concurrency, coin caps, and an approximately comparable trade/risk budget. Gate C asks: is the wallet layer preferable to independently running the public strategy? Only object (ii) can answer make-or-buy.
