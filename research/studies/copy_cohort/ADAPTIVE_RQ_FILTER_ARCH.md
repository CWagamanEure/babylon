# ADAPTIVE R/Q TRADER-QUALITY FILTER — frozen powered component ablation

**Stamped before any adaptive-R/Q roster or evaluation outcome is computed: 2026-07-18.** This was proposed
after inspecting KF-relative, EW21, and EW60 on 202511–202606. Every output is an adaptive, burned diagnostic;
no historical arm may be promoted or called a method null.

## 1. Question, arms, and estimands

Can a slowly changing per-trader state improve EW60 when observation trust varies causally with trade
breadth/concentration and market volatility, and blowups trigger an explicit state break? Test each requested
component alone and all together; do not sweep formulas.

Frozen score arms:

1. `KF60_BASE`: fixed-R, fixed-Q state filter.
2. `KF60_R_BREADTH`: base plus per-wallet/day breadth/concentration R.
3. `KF60_R_VOL`: base plus common daily market-volatility R.
4. `KF60_Q_SLOW`: base with Q/4.
5. `KF60_BLOWUP`: base plus shock reset and 30-day formation/test quarantine.
6. `KF60_ALL`: breadth R × volatility R, Q/4, and blowup handling.
7. `EW60`: 60-day exponentially weighted t-score on the common tape/pool.
8. `TSTAT_COMMON`: ordinary t-stat on the common tape/pool.

### Powered primary layer

The load-bearing outcome is not another 30-wallet book. Each score forms a next-month, all-eligible-wallet,
coin-by-coin cross-sectionally neutral **end-of-day measurement factor** (Section 6). Primary = `KF60_ALL
factor − EW60 factor`, in measurement bp/day. Care-about = +5bp/day. Because the factor conditions on the
realized same-day active set, it measures whether the score orders realized PnL; it is not executable and
cannot itself establish a tradable return. Only the conditional book can address deployability.

Registered secondaries are `R_BREADTH−BASE`, `R_VOL−BASE`, `Q_SLOW−BASE`, `BLOWUP−BASE`, `ALL−BASE`,
`BASE−EW60`, and `ALL−TSTAT_COMMON`. They form one seven-test Holm positive family and a separate seven-test
+5bp-null Holm family. The first four are standalone component contrasts. `ALL−BASE` is a bundle/interactions
contrast, not a fifth attributable component; this design does not identify interactions inside ALL.
`BASE−EW60` also includes the state model plus robust observation transform and is not a pure Kalman-only
ablation.

### Downstream book layer

Exact top-30 rosters and the audited 8h copy book are secondary candidate diagnostics only. Run that book only
if the factor primary passes the registered +5bp positive-control/MDE gate. Consensus is excluded so the study
isolates selector quality.

## 2. Common formation tape and eligibility

Formation is the prior three complete months only. For each wallet/coin/day across BTC, ETH, SOL, HYPE,
compute exact-Decimal total-fee-net PnL and notional, then wallet/day:

```text
x = (sum pnl - sum fee - sum coalesce(builder_fee,0))
    * min(1, 100000 / sum notional)
HHI = sum((coin_notional / wallet_day_notional)^2)
```

Zero-notional days are absent. A wallet/day is common-valid only when HHI is finite in (0,1], the market-RV
day is coverage-valid (Section 4), and x is finite. **The same common-valid day mask is applied to all eight
arms, including EW60 and static.** After masking, recompute every eligibility statistic: ≥15 active days,
positive finite dispersion, activity in the final 30 calendar days, and EW60 Kish effective N ≥8. A wallet
must satisfy all of them to enter the common pre-shock base pool.

For state observations, on those exact common-valid x values define

```text
med_i = median(x_i)
MAD_i = median(abs(x_i - med_i))
s_i = 1.4826 * MAD_i
```

If `s_i` is zero/nonfinite, fall back to sample SD with `ddof=1`; if that is not positive finite, fail the
wallet. Observation `y_i,d=clip(x_i,d/s_i,-5,+5)`. Do not subtract `med_i`: persistent positive location must
remain signal. Unmodified x remains the EW/static input and shock detector.

`BASE`, both R arms, `Q_SLOW`, EW60, and static select from this identical base pool. `BLOWUP` and `ALL`
intentionally apply an additional final-30-day shock gate. Their comparisons therefore measure the requested
bundle of state reset + formation eligibility + online quarantine, not a pure matched-pool reset effect.
Require and report ≥30 wallets after each arm-specific gate, base/shock pool sizes, and roster overlaps.

## 3. State clock, base Q/R, and slow Q

The scalar random-walk model is per trader and is not the old cross-sectional rank-normal AR(1):

```text
theta_d = theta_d-1 + eta_d        Var(eta per calendar day)=Q
y_d     = theta_d + epsilon_d      Var(epsilon)=R_d
```

Let `K60=1-2^(-1/60)`, `Q60=K60^2/(1-K60)`, `Rbase=1`. Initialize at the stationary posterior
`theta=0, P=K60`, with cursor `formation_start_ordinal-1`. For every observed day d, exact order is:

1. `gap=d-cursor` (consecutive calendar days have gap=1);
2. predict `P <- P + gap*Q`, theta unchanged;
3. if the arm has blowup handling and d is a shock, apply the reset in Section 5;
4. update `K=P/(P+R_d)`, `theta <- theta+K*(y-theta)`, `P <- (1-K)*P`;
5. set cursor=d.

After the last observation, predict through `formation_end_ordinal-cursor` and rank by `theta/sqrt(P)`, wallet
ascending on ties. Missing wallet-days are prediction-only, never zero-PnL updates.

For `Q_SLOW`/`ALL`, set `qslow=Q60/4`, solve
`Kslow=(-qslow+sqrt(qslow^2+4*qslow))/2`, and initialize `P=Kslow`. This gives the intended slower response from
the first observation rather than a diffuse fast transient.

A global-R arm is omitted because it is ranking-equivalent: compare slow `(Q=Q60/4,R=1,P0=Kslow)` with
`(Q=Q60,R=4,P0=4*Kslow)`. Theta and gains must match exactly, the latter P is 4×, and
`theta/sqrt(P)` differs only by the constant 1/2. A deterministic test must prove ranking equivalence. The
innovation `y-theta_pred` is never manually reduced; slowness comes from gain.

## 4. Adaptive observation R

### 4.1 Breadth/concentration

For common-valid wallet/day:

```text
breadth = max(n_open_flat,0.25) / (4*HHI)
R_breadth = clip(breadth^(-1/2),0.5,4)
```

This is a tempered reliability proxy, not an independence claim. One/no flat open concentrated in one coin is
trusted less; several opens spread across majors are trusted more.

### 4.2 Market volatility and exact lattice

Use only explicit local `asset_ctx` files whose UTC dates fall inside the three-month formation window; never
load test-month context or pre-formation warmup. Require exact expected-date equality: exactly one
`day=YYYYMMDD/ctx.parquet` for every formation calendar date, with no extras or duplicates. Bind the sorted
file list, sizes, and SHA-256 values before and after materialization. Fail on duplicate `(coin,ts)` rows;
there is no aggregation fallback.

For every UTC day and major, targets are exactly 00:00, 00:05, ..., 23:55 UTC (288). At each target choose the
first positive finite midpoint with `target <= ts <= target+90s`; odd-second timestamps are allowed only by
that rule. Require all 288 targets for all four majors. Compute 287 within-day log returns per coin—never a
cross-midnight return—then coin RV `sqrt(sum(r^2))` and market RV as the RMS of four coin RVs. A day with a
missing target, nonpositive midpoint, nonfinite/zero coin or market RV, or any incomplete major is invalid and
is removed from every arm's formation tape. The known partial 2026-05-30 day is therefore invalid, never
treated as low volatility.

For valid day d, the denominator uses at most the prior 20 **strictly earlier, valid, within-formation** market
RV days. With fewer than five, multiplier=1. Otherwise:

```text
vol_ratio = clip(RV_d / median(RV_prior20),0.5,4)
R_vol = vol_ratio^2
```

The squared ratio freezes the hypothesis that observation-noise **standard deviation** scales linearly with
market RV. Current-day RV is available at the same day close as x; no future day enters. `ALL` uses
`R=clip(R_breadth*R_vol,0.125,64)`. Report the complete frozen list of content-invalid formation days and the
reason for each; missing whole files are fatal rather than content-invalid.

## 5. Blowup state break

Shock = `n_liq>0` or unmodified normalized `x<=-$10,000`. Operation order is prediction, then
`theta=min(theta,-3)` and `P=max(P,1)`, then the day's ordinary update. A wallet shocked in the final 30
formation days is excluded only from `BLOWUP` and `ALL` top-30/shock-pool factor universes. During evaluation,
only those two arms remove the wallet from the factor universe and quarantine copying on D+1 through D+30
inclusive; D itself cannot retroactively cancel factor weight or signals. Excluded wallets are removed before
centering/normalization and embedded afterward with exact zero weights. This intentionally tests reset plus
exclusion/quarantine and does not hide a blowup by increasing R.

## 6. Powered all-wallet factor and positive control

Freeze each arm's formation score before reading the evaluation month. Evaluation then deliberately uses an
end-of-day conditional-on-activity measurement estimand, not a causal trading factor. For every evaluation
calendar day use WCD only for wallets in the common base pool. Define coin fee-net PnL first, then multiply
every coin row by the **single wallet-day** scale `min(1,100000/wallet_day_notional)` to obtain `x_wc`; thus
`sum_c x_wc` exactly equals normalized wallet-day PnL. Set `x_bp_wc=10000*x_wc/100000`.

Within each arm, convert formation scores to ascending average-tie percentiles over its eligible formation
pool and raw values `v_i=2*((rank_i-0.5)/N)-1`. On coin c/day d let `U_a,c,d` be wallets that are in that
arm's formation-eligible pool, active in c on d, and not under a quarantine known before d. Require at least
30 wallets and a positive finite normalization denominator. Center and normalize **only over U**:

```text
u_i = v_i - mean_U(v)
w_i,c,d = (1/4) * u_i / sum_U(abs(u))    for i in U; exactly 0 otherwise
```

Assert per arm/coin/day `sum(w)=0`, `sum(abs(w))=1/4`, and excluded/quarantined weights exactly zero. This
forms one active-wallet-neutral measurement return per coin and combines BTC/ETH/SOL/HYPE equally. It removes
coin/day common shocks from the measurement, including HYPE-specific shocks. A shock on d enters quarantine
only from d+1.

Start from every calendar day in each evaluation month. The one study-common estimand lattice D retains a day
only when at least 200 distinct base-pool wallets are active and every arm×coin cell passes the ≥30 and
normalization gates. This activity-conditioned inclusion is why the factor is explicitly non-executable.
Report every excluded day/reason and require at least 90% calendar coverage in every fold for resolution;
never replace an excluded day with a selected zero. Factor return is `sum_i,c w_i,c,d*x_bp_i,c,d`. Coin
contributions must sum exactly to it.

For contrast A−B define fixed realized contributions
`z_i,c,d=(w_A,i,c,d-w_B,i,c,d)*x_bp_i,c,d` on D and

```text
point = sum_d sum_i,c z_i,c,d / |D|.
```

Use a factor-specific 10,000-draw crossed bootstrap—not Dynamic-T's entry-row mean. Draw one global-wallet
multinomial multiplicity vector `m_i` and paired seven-calendar-day block multiplicities `t_d`; absent cells
are zero and factor weights are never renormalized inside a draw:

```text
T* = sum_d t_d * sum_i m_i * sum_c z_i,c,d / sum_d t_d.
```

One-way wallet/time draws set the other multiplicity to one and are diagnostic. Invalid denominator draws are
counted. Report point bp/day, 95% percentile CIs, MDE80, +5bp power, eight fold directions, four coin
directions, support, and concentration. Freeze concentration as
`top5_wallet_abs_contribution_share`: aggregate z over coin/day within each global wallet, take absolute
wallet totals, and divide the five largest sum by the all-wallet sum; report null only when that denominator
is zero.

Freeze `u=T*-mean(T*)`, two-sided positive-family
`p=(1+sum(abs(u)>=abs(point)))/(B+1)`, one-sided +5-null
`p=(1+sum(u<=point-5))/(B+1)`, critical `q97.5(u)`,
`MDE80=critical-q20(u)`, and analytic power `mean(u+5>critical)`. The single primary is unadjusted; the seven
secondaries use two-sided Holm, and the seven +5-null p-values use a separate Holm family. A secondary
within-run positive direction requires point>0, crossed CI lower>0, all resolution gates, and positive-family
Holm q≤.05. A resolved `<+5` secondary requires crossed CI upper<5, MDE≤5, all resolution gates, and null-family
Holm q≤.05. Burned governance still forbids formal promotion/null labels.

Before interpreting a contrast, run an end-to-end +5bp recovery control. Let
`d_i,c,d=w_A,i,c,d-w_B,i,c,d`. For the observed lattice inject into the normalized wallet×coin outcome vector
along d with the single global coefficient

```text
c0 = 5*|D| / sum_d,i,c d_i,c,d^2
x'_bp_i,c,d = x_bp_i,c,d + c0*d_i,c,d.
```

Assert the recomputed point is exactly original+5. In every bootstrap draw, use **the same fixed c0 and the
same frozen wallet/time multiplicity draws**; never recalibrate the injection by draw. Materialize the fixed
injected outcome/contribution arrays and run them through the ordinary
factor-statistic path with weights, support, and quarantine fixed from the original construction. Assert only
the realized point shift is exactly +5; bootstrap shifts are allowed to vary and are the purpose of the
control. Report the absolute injected crossed CI, the paired `T_injected*−T_original*` crossed CI, all invalid
draw fractions, zero-contrast days, and median/max absolute wallet×coin perturbation. The fixed-injection
recovery passes only when its paired shift CI lower bound exceeds zero.

Separately label `mean(u+5>critical)` as shifted-noise power; it is not the injected-data bootstrap. A contrast
is resolution-capable only if empirical MDE80≤5bp, shifted-noise +5bp power≥80%, the fixed injected point is
exactly original+5, the fixed-injection recovery passes, all original/fixed-injection invalid-draw fractions
are ≤1%, calendar coverage passes, and there are at least 10 global wallets and 10 occupied calendar blocks
per arm. Apply Holm to the seven positive and separately seven +5bp-null families.

If the primary fails this power gate, stop before constructing the top-30 book and state: “the available
burned data cannot resolve this adaptive filter.” Powered component contrasts may be described individually;
unpowered ones cannot support either direction.

## 7. Conditional downstream top-30 book

Only after the factor primary passes **every** resolution condition—MDE, injected power, original/control
invalid-draw rates, calendar coverage, and wallet/block support—construct exact top-30 rosters and reuse the
audited Dynamic-T execution primitives in a new isolated runner (the hard-coded Dynamic-T `run()` is
forbidden). Apply online shock quarantine only to BLOWUP/ALL. This gate is independent of the primary point
direction: a powered adverse or flat factor still proceeds so the requested components are not selectively
stopped. The book remains a downstream descriptive diagnostic.

Execution is unchanged: collapsed flat-opening majors signals ≥$250; strictly-post-signal first midpoint;
$2,500 equal clips; one wallet×coin position; $10k/wallet and $50k/coin caps; 8h; 5.5bp. Capacity freezes before
outcome support; unsupported accepted trades retain capacity; May-30 partial context and June cutoff remain
registered.

Book inference incorporates Dynamic-T Section 7 exactly: 1% overall, 2% per-fold, and 0.5pp arm-imbalance
missingness gates; ≤1% invalid bootstrap draws; common/all-actual/adverse-bound positive rule;
common/all-actual/favorable-bound null IUT; ±2,000bp endpoints; crossed wallet×7d bootstrap; and separate
seven-test positive/null Holm families. Print point, CI, MDE, power, folds, coins, and concentration. Because
this book was reached through the factor screen, it has no promotion authority.

## 8. Governance, cache contract, and stopping

All results force `positive_promotion_eligible=false`, `method_null_eligible=false`, and
`verdict_status=BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC`. Within-run direction requires its multiplicity-aware
crossed CI and construction/power gates—not a raw point. Even a resolved absence statement is limited to the
named contrast on these burned folds and cannot become a formal method null.

Panel caches bind the adaptive profile, exact WCD manifest plus daily object HEAD lineage, explicit formation
context paths/sizes/SHA values, all formulas/windows/coverage rules, and selector/runner code. Rehash WCD and
context after materialization and fail closed on mutation. Factor evaluation WCD and conditional book WCD/OPE
plus execution context have separate fold-lineage identities. Rebuild under
`data/derived/copy_cohort/adaptive_rq_filter/`; do not reuse EW/KF entry caches. A fail-closed runner must reject
profile/architecture mismatches and direct generic execution.

Architecture audit → implementation → code audit → factor/power run → conditional book only if powered →
independent steelman and prosecution → findings ledger. No formula, threshold, window, shock rule, K, horizon,
or consensus follow-up may be tuned on these folds. Existing KF/EW21/EW60 artifacts are immutable.
