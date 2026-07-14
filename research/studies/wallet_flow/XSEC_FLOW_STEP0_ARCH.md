# Step 0 — Cross-sectional orthogonalized-flow base rate (ARCHITECTURE)

**The one question this answers:** *Is there ANY out-of-sample cross-sectional alt-SELECTION edge in wallet flow,
once beta / rotation / momentum are stripped?* Everything in the "market ecology" vision (agent-state HMM, lead-lag
graph, divergence signal, 6-D latent state) is downstream of this being nonzero. Establish the base rate FIRST;
earn every further layer with an incremental, placebo-validated OOS lift.

**Binding context (why the naive version failed):** the deployed alt-timing signal was BTC/ETH risk-on/off flow
(rotation *beta*) read as skill — clean alt-only OOS IC = +0.0045 (t≈0.3), zero. See `audit/alt_timing_dashboard/
FINDINGS.md`. Step 0 must make that class of contamination structurally impossible, not just check for it.

## Estimand

Universe: PIT liquid alts (`alt_universe`, exclude BTC/ETH — they are hedges/factors only). Hourly. Horizons
h ∈ {4, 24} (slower = cheaper turnover, where cross-sectional selection should live; H1 is where beta lived).

### Target — cross-sectional residual rank (rotation removed AT THE TARGET)
1. `resid_{a,t} = r_{a,t} − β^btc_{a,t}·r^btc_t − β^eth_{a,t}·r^eth_t`  (causal rolling betas, reuse
   `alt_flow.build_resid` / `leadlag.rolling_beta`, W=720/MINOBS=240).
2. Forward sum `Y_{a,t,h} = Σ_{k=1..h} resid_{a,t+k}` (strictly future; embargo h hours at the train/test seam).
3. **Cross-sectional rank each hour:** `u_{a,t,h} = rank_a(Y)/(n_a−1) − 0.5`. Ranks are relative by construction
   → the aggregate alt-vs-majors rotation is removed *at the target*. This is the structural fix: a predictor can
   only score by picking RELATIVE winners, never by loading the rotation factor.

### Predictor — relative (demeaned), size-blind reallocation flow
- `s_{i,a,t} = sign(flow_{i,a,t})` from `awb` (ALT-ONLY; size-blind — size-weighting is whale-dominated, Result 8).
- **Relative reallocation** `q_{i,a,t} = s_{i,a,t} − mean_{a' ∈ traded_i}(s_{i,a',t})`. Build BOTH variants, report both:
  - **V-sim:** traded set = coins the wallet traded THIS hour (pure; sparse — 1-coin-hour wallets get q=0, correctly
    expressing "no cross-sectional view").
  - **V-trail:** traded set = coins traded in the trailing `W_rel=24h` (denser; mild staleness).
  Demeaning across the *traded* set only (never the full universe) avoids imputing shorts a wallet never held.

### Skill weight — continuous, shrunk, walk-forward (no top-N list)
- Train-only portfolio selection score `g_i = mean_{train hours,coins}( q_{i,a,t} · u_{a,t,h} )`  (the §3 score;
  robust for concentrated wallets where a Spearman IC is unstable).
- Shrinkage toward zero: `θ_i = g_i · n_i/(n_i + λ)` (n_i = wallet's train obs; λ tuned on train, e.g. median n).
- `W_i = max(0, θ_i)`  (continuous positive skill weight; dormant/absent wallets → ~0 automatically → no churn wall).

### Coin consensus signal + NEUTRALIZATION LADDER (report IC at every rung — anti-over-null)
`S_{a,t} = Σ_i W_i · q_{i,a,t}`. Then cross-sectionally neutralize (per hour, regress S on controls across coins,
keep residual) and report the OOS IC at EACH level — do NOT only report the fully-scrubbed endpoint:
- **L0** S raw · **L1** ⊥ crowd flow (aggregate coin flow, `aagg`) · **L2** ⊥ lagged residual momentum (trailing
  `resid`) · **L3** ⊥ funding (`asset_ctx`). L2 (momentum-stripped) is the load-bearing "is it novelty?" number.

## Metric, placebos, significance
- **Primary:** pooled forward cross-sectional **Spearman IC** of neutralized S vs u, over held-out months, with a
  **time-block bootstrap CI** and **IC-vs-zero t** (report the estimate + CI, per the gate — never a bare z).
- **Two placebos, baked in from line one** (both must be beaten): **P-random** (W from random recently-active
  wallets) and **P-rotation** (W from wallets ranked by alignment with LAGGED residual momentum — pure past, zero
  forward info; the decisive control that killed the last signal).
- **Effective-N / independence:** correlation-cluster the top-weighted wallets; report the independent-cluster count
  and a dedup-down-weighted IC (10 correlated wallets ≠ 10 votes — audit flagged non-independence).
- **Economics:** gross-per-crossing vs cost at h=24 (cross-section trades many names; the win condition is COST, not
  IC — Result 8: the cross-section is real but ~10× sub-taker-cost; maker frontier is the realistic target).

## Walk-forward protocol
Expanding train, single held-out month folds (mirror `alt_timing_dashboard_data`). Per fold: score+shrink weights on
train-only; recency-gate eligibility to the 2 months before the fold; build S on the held-out month; measure IC +
placebos. Embargo h hours at the seam. Causal betas only. Concatenate folds → pooled OOS IC + per-fold reported.

## Decision rule (both gates)
- **GREEN (earn the ecology):** L2-neutralized OOS IC CI excludes 0 AND beats BOTH placebos AND gross-per-crossing
  clears the maker frontier at h=24. → then add novelty/earliness/permanence → agent-state soft-classification →
  divergence, each earning its keep against placebo.
- **RED (powered negative):** point estimate ~0 with MDE ≤ the care-about (show the positive control recovers an
  injected edge) → "no cross-sectional alt-selection edge in orthogonalized flow," and we STOP — do not add
  parameters until something looks significant.

## Data (all on existing tape — no new builds)
`awb` (wallet,coin,hour signed flow), `aagg` (coin,hour OFI/crowd flow), `asset_ctx` (mid/funding), `alt_universe`,
`alt_flow.build_resid`/`build_cohort_tables`/`rolling_beta`. **Explicitly OUT of scope (Phase 2, only if GREEN):**
per-fill inventory `q`, the O(N²) lead-lag graph, the agent-state HMM, the 6-D latent market state.

## Files
`research/studies/wallet_flow/xsec_flow_step0.py` (build+run), reuses `alt_flow` machinery. Output →
`data/derived/xsec_flow_step0/` (ic_ladder.json, per-fold, placebo draws). Positive-control injection test included.
