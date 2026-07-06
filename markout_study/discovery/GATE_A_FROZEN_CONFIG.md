# GATE_A_FROZEN_CONFIG — one-page reproducible Gate-A spec (PENDING APPROVAL)

Everything needed to reproduce Gate A. Values marked **[AUDIT-ONLY]** are resolved by non-outcome coverage code (AUDIT_ONLY_PLAN.md) *before* freeze; none touches wallet returns. Latency/cost are absent here by design — Gate A needs neither.

| Item | Frozen value |
|---|---|
| Universe | BTC, ETH, SOL, HYPE |
| Band / horizons | mid {1, 2, 4, 8} h |
| Walk-forward | monthly cutoffs C; evaluate month m = month after C; start month & fold count frozen mechanically before any return (C4) |
| Purge | horizon-matched 8 h (episode enters a score only if `t0+h < C`); leakage assertions on forward-endpoint **bar** ts + temporal placebo |
| Episode | 30-min gap; first-entry; startpos reconstructed + left-censored wallets quarantined; hold = flat→flat (not used in primary eligibility); fragments deduped to non-overlapping windows; min-reduction dust floor |
| Wallet-day unit | mean of episode markouts per (wallet, day, horizon) — SPEC §2 |
| Eligibility (return-independent only) | ≥50 independent episodes; ≥30 active days; ≥4 active months **[AUDIT-ONLY]**; scoreable = ≥J wallet-days at ≥3/4 horizons, J **[AUDIT-ONLY]**; episode-count concentration cap **[AUDIT-ONLY]**; liveness = active last 30 d; maker-heavy only if ledger-gate passes |
| Median-hold filter | **removed from primary**; ≥1 h (completed-episodes-only) is a sensitivity |
| Standardization | per horizon, across **wallets**, coin-pooled, winsorized 1/99, pre-C only; z = (Zbar−μ)/σ̂ — SPEC §4 |
| Band score (pre-shrink) | equal-weight mean of present-horizon z; ≥3/4 horizons required — SPEC §5 |
| Sampling variance | wallet-day block bootstrap, B=1000 — SPEC §6 |
| Shrinkage | normal–normal MoM: τ̂²=Var_w[Zband]−mean_w V; λ=τ̂²/(τ̂²+V); θ̂=μ̂+λ(Zband−μ̂) — SPEC §7 |
| Wallet score | θ̂(w,C) |
| Tie-break | posterior P(θ_w > μ̂_C) — SPEC §7 |
| Selection | top 10% of eligible by θ̂, min 20 / max 50; **no return-based concentration gate**; effective-N floor **[AUDIT-ONLY]** |
| Realized outcome (single) | Yband(w,m) = ¼ Σ_h s(m−1,h)·Mbar(w,m,h) — SPEC §9; raw 1/2/4/8 h bp reported as decomposition, no best-horizon picking |
| Non-selected field | equal-weight mean of per-wallet Yband over same-fold eligible non-selected wallets — SPEC §11 |
| Gate-A statistics | (a) wallet rank IC Spearman(θ̂, Yband); (b) decile gradient; (c) equal-wallet selected−field Δ_m — SPEC §10 |
| Inference unit | **calendar-month fold only**; coin×fold pooling prohibited |
| Sign-test rule | Δ_m>0 in ≥k(F) folds, k(F)=smallest with one-sided binomial p≤0.05 {k5=5,k6=6,k7=7,k8=7,k9=8}; else **inconclusive** |
| Report | every fold, F, #positive, exact p, mean, median, worst fold, LOFO, dispersion; LOO wallet/month/coin |
| Positive controls | injection grid {0,3,5,10} bp cross-sectional spread + identity shuffle + timestamp/direction randomization; fixed, non-selecting — SPEC/A.13 |

## Unresolved Gate-A placeholders (must be resolved by audit-only code before freeze — item 11)
1. **Min active months** (currently 4) — from coverage/reliability.
2. **J** = min eligible wallet-days per horizon for scoreable — from coverage.
3. **Episode-count concentration cap** (days/months) — from activity-shape distribution.
4. **Effective-N floor** for the reliability gate — pinned to positive-control MDE ≤ target (from the 0/3/5/10 grid on training folds), **not** from real rankings.
5. **Liveness window** confirmation (30 d) — operational.
6. **Exclusion-flag thresholds** (TWAP/wash/bot/liquidation) — from the labelled control set, precision/recall.
7. **Start month & fold count** — mechanical from the eligibility counts once 1–5 resolve.

Latency and cost remain unresolved but are **Gate-B/C only** and do not affect Gate A. No placeholder above is set by inspecting wallet markout rankings or basket returns.
