# SWARM SCOPE — did the Kalman/smoothing test (Result 11) bury a real turnover-rescue?

The user's read: "we didn't do it properly." My Result 11 tested ONE crude filter (fixed-α EMA on the final
residualized signal) over a coarse grid and called it a method-scoped negative. This swarm's job is to attack the
CONSTRUCTION of that test with real filtering/state-estimation expertise and find whether a proper filter rescues
the taker leg or tightens the maker — OR confirm, rigorously, that it doesn't. Apply BOTH gates (see
`CLAUDE.md` / `[[babylon-overnulling-gate]]`): over-null (don't call it dead if it's underpowered/mis-constructed)
AND over-carry (don't carry a marginal cell as a win).

## The object under test
- **Signal:** per-alt `S_a = Σ_w W_w · q_trail_{w,a}` (skill-weighted breadth of an informed 1500-wallet cohort's
  size-blind relative-reallocation flow). `q_trail` = each wallet's flow-sign demeaned over its trailing-24h traded
  set. Then residualized ⊥crowd,⊥momentum → `s_inf` (the deployable per-cell signal).
- **Book:** hourly cross-sectional DECILE long-short (top/bottom 10%, hold-band to 15%), equal-weight, 45-alt
  universe, rebalance every reb=4h, 7 walk-forward folds (202512..202606). Cost engine = `simulate_raw` +
  `scenario_net_series` in `research/studies/wallet_flow/xsec_concentrated_book.py` (import as CB).
- **Baseline (no smoothing) numbers to beat** (pooled reb4): maker_earn_a30 **+4.35/hr** CI[+2.87,+5.70] 7/7;
  maker_a50 +3.60; taker_top_smallclip **+1.42/hr** CI[−0.69,+3.36] 5/7 (inconclusive); taker_impact ≈ 0/neg.
  Mid-dispersion regime baseline: taker_smallclip +2.75 CI[−0.2,+5.9]; maker_a30 +5.39.
- **What Result 11 found:** fixed-α EMA (`m_t=α·S_t+(1−α)·m_{t−1}`) + carry-forward `stale`. Carry-forward INERT
  (cohort trades 43.5/45 alts every hour → names never dormant). The α blend cut turnover but cut gross faster →
  net monotonically WORSE, no interior optimum; taker not rescued. One marginal flip (mid α0.6 taker_smallclip
  CI→[+0.1,+5.5]) with UNCHANGED point estimate. Full detail: `research/studies/wallet_flow/xsec_kalman.py`,
  `data/derived/xsec_kalman/results.json`, and `research/studies/wallet_flow/FINDINGS.md` Result 11.

## Suspected weaknesses in MY test (attack these; not exhaustive)
1. **Wrong smoothing SPACE.** I smoothed the residualized signal LEVEL, then re-ranked. Ranking is scale-free;
   levels have different cross-sectional scale each hour → EMA on raw levels may be incoherent. Should we smooth the
   cross-sectional RANK, the z-scored signal, or smooth the MEMBERSHIP decision — not the level?
2. **Crudest possible filter.** Fixed α is the steady-state KF with fixed SNR. A real state-estimator adapts the
   gain to the innovation / estimates process+observation noise from data. Maybe an adaptive/proper KF beats it.
3. **Conflating "smooth signal" with "cut turnover."** Turnover is rank-CHURN at the decile boundary. The right
   lever may be hysteresis (wider hold-band), a minimum-holding-period, or rank-based dwell — applied to a FRESH
   signal — not staling the signal itself. Compare these turnover-reducers head-to-head.
4. **No horizon re-optimization.** Smoothing lags the signal ~1/α hours; I fixed reb=4. Jointly re-optimizing the
   harvest horizon to the lag may recover the lost gross.
5. **Averaging across regimes/coins/turnover.** Pooled means may hide a CONDITIONAL benefit (high-turnover subset,
   specific coins, specific folds, high-dispersion hours).
6. **Judged on the MEAN, not risk-adjusted.** Turnover reduction cuts variance too; smoothing might raise net
   Sharpe / tighten CI even at a lower mean — the deployment-relevant quantity.
7. **Smoothing applied POST-residualization/aggregation.** Should the filter act earlier — on each wallet's flow
   state, or the cohort aggregate BEFORE cross-sectional ranking?

## Resources (iterate FAST — do NOT rebuild from DuckDB unless you must)
- **`data/derived/xsec_kalman/panel_cache.npz`** holds the fully-built leak-free cells so you can rebuild ANY book
  in seconds without the 130s DuckDB load. Keys:
  `R`(int32 hour-index per cell), `Cc`(int32 alt-index 0..44), `s_inf`(float64 signal per cell),
  `hours`(int64 ms, len 7992), `panel_month`(int32), `disp`(float64 per hour), `resid_alt`(7992×45 fwd resid input),
  `hs_arr`(45 per-alt half-spread bp), `hs_default`(float), `n_alt`(45), `folds`(7 months).
  Build dense signal: `SIG[R[i],Cc[i]]=s_inf[i]`. Forward return: `FVr=S0.fwd_sum(resid_alt,reb)` (bp = ×1e4).
- Reuse `CB.simulate_raw(hours_list, xs_arr, fvb, halfspread_dict, hs_default, step, q1=0.10, q2=0.15, elig)` and
  `CB.scenario_net_series(sim, reb, fee, mode, mult, hs_default)`; scenarios `CB.SCENARIOS`; CI `CB._dayblock_ci`;
  sign test `ADJ.sign_test`. Rebalance grid MUST be frozen to the baseline (`sorted(observed hours)[::reb]`) so every
  variant is compared on identical timestamps — only the signal/rule differs.
- Deeper reconstructions (smooth raw wallet signs or the cohort aggregate before residualization) require the full
  `xsec_concentrated_book.run` pipeline (~130s, DuckDB). Do this ONLY if your hypothesis needs it.
- **Leakage discipline (non-negotiable):** any filter/threshold must be STRICTLY CAUSAL (uses only signal at hours
  ≤ t). Any parameter you tune is an in-sample search → report it as a CANDIDATE needing OOS confirmation, tally the
  multiple comparisons, and prefer results robust across a RANGE (not one knife-edge cell).

## Env
- `.venv/bin/python` (numpy + duckdb; NO pandas/matplotlib). DuckDB safety if you connect:
  `SET memory_limit='1400MB'; SET threads=1; SET temp_directory=...; SET preserve_insertion_order=false`.
- Write NEW scripts under `research/studies/wallet_flow/` (prefix `kalman_swarm_<lens>_`) or the scratchpad. Do NOT
  modify the frozen `xsec_kalman.py` / `xsec_concentrated_book.py` / the cache.
- Reproduce the baseline first (α=1/no-smooth must give maker_a30 +4.35, taker_smallclip +1.42 pooled reb4) to
  prove your harness is correct BEFORE trusting any variant.

## Deliverable (each agent)
A written report: what you tried, the exact numbers (point est + day-block CI + per-fold sign for the FOCUS
scenarios taker_top_smallclip / taker_top_impact / maker_earn_a30 / maker_earn_a50), and a VERDICT that explicitly
addresses both gates. State clearly whether Result 11's negative SURVIVES your attack, is OVERTURNED (with the
construction that does it), or needs a specific further test.
