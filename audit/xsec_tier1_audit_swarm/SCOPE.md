# TIER-1 IMPLEMENTATION AUDIT + NEW-CONSTRUCTION SWARM (2026-07-11)

Round-1 of the ideation swarm tested the 3 cache-cheap "probed winners" and ALL THREE DEFLATED under faithful OOS costing
(`research/studies/wallet_flow/ideation_tier1_eval.py`, results `data/derived/xsec_ideation_tier1/results.json`, ledger entry
at the end of `research/studies/wallet_flow/FINDINGS.md`). Two jobs for this swarm:
  (1) AUDIT my Round-1 implementations for BUGS that unfairly deflated (or inflated) a result — this cuts BOTH ways: an over-null
      bug (I broke the min-var book / mis-charged the taker) or an over-carry bug (a leak inflating a number). Verify before you claim.
  (2) Propose + PROBE DIFFERENT/BETTER constructions of the same ideas, and two NEW directions the user asked for: PCA factor-
      representative trading, and HAR-RV realized-vol forecasting for weighting/horizon/sizing.

## VALIDATED GROUND TRUTH (do not re-derive; the harness is trustworthy on the baseline)
The harness reproduces the FROZEN pre-reg baseline EXACTLY: decile equal-weight maker_a30 = **reb4 +3.17/hr, reb2 +5.37/hr**
(matches the pre-reg honest phase-avg priors +3.2/+5.4). So the book/cost plumbing is correct on the baseline; bugs (if any) are in
the VARIANT paths (weighting, concentration extremity, fade split), not the core book.

## ROUND-1 OUTCOMES (what you're auditing / improving on)
- **A. Covariance book:** inverse-vol improves annualized Sharpe +15-16% (reb4 SR 5.96→6.93; reb2 10.18→11.31) at −5% mean net.
  The FULL min-variance / Σ⁻¹ off-diagonal char-portfolio adds NOTHING beyond the diagonal (minvar SR 6.36<6.93 reb4). Verdict: inv-vol
  small Sharpe tilt; off-diagonal dead. → AUDIT: is my Σ⁻¹/Ledoit-Wolf/μ construction correct, or did I break the off-diagonal?
- **B. Conviction-concentration:** taker stays NEGATIVE at every extremity under TURNOVER-AWARE cost (−1 to −3/crossing, 1-3/7 folds);
  steelman's taker-rescue (+1→+13/crossing) was a per-crossing-flat-cost artifact. Maker rises with concentration but only into the
  ~2-name netting trap. → AUDIT: is my turnover-aware cost model faithful, or does it over-charge the taker?
- **C. Fade-vs-chase:** pooled IC split REPLICATES (fade +0.044 vs chase +0.002, h=4) but cross-fold sign test FAILS (5/7, p=0.45; agent
  claimed 7/7 p=0.016) and hard fade-gate makes the book worse. → AUDIT: is my split faithful (agree=sign(SIG)·sign(trailing-24h-mom))?
  the raw-S caveat (s_inf is already ⊥mom → split may be attenuated/mechanically suspect).

## THE CACHE (fast; the ONLY data you need for cache probes) — `data/derived/xsec_kalman/panel_cache.npz`
`R,Cc` (int, per-cell hour-index 0..7991 + coin-index 0..44); `s_inf` (V-trail signal, ⊥[crowd, trailing-mom]); `hours(7992)` ms;
`panel_month(7992)` YYYYMM per hour (folds = 7 months 202512..202606); `disp(7992)` cross-alt dispersion; `resid_alt(7992,45)`
per-HOUR BTC/ETH(+LOO)-residual return per alt (the book PnL source; forward via S0.fwd_sum → t+1 entry); `hs_arr(45)` STATIC impact
half-spread bp/side; `hs_default`; `n_alt=45`; `folds(7)`. Point-in-time spread + raw pre-residual S + per-wallet size need the
pipeline (`kalman_swarm_perwallet.py` load ~130s) or asset_ctx (DuckDB).

## NEW DIRECTIONS (user asked explicitly)
- **PCA factor-representative trading:** PCA/eigendecompose the alt return panel (causal rolling `resid_alt` cov). The signal loads on
  certain directions; instead of equal-weight decile, trade the alts that BEST REPRESENT each factor direction (highest |loading|), or
  build PC-mimicking portfolios and tilt by the signal's projection onto each PC. This is the eigen-view of the min-variance idea — it
  may recover the "paired rotation A↔B" off-diagonal structure the naive Σ⁻¹ missed. Cache-testable. (Watch: causal loadings, PC sign
  ambiguity, how many PCs, leakage.)
- **HAR-RV realized-vol forecasting:** Corsi HAR-RV (daily+weekly+monthly RV components) to FORECAST per-alt realized vol — a better vol
  estimate than my crude flat COVWIN=480h trailing std. Uses: (a) sharper inverse-vol weights, (b) the vol-adaptive HARVEST HORIZON
  (the known Q-lever: reb2−reb4 edge scales with vol), (c) signal scaling / position sizing (trade bigger when vol-forecast favorable).
  Cache (`resid_alt`, `disp`) + asset_ctx (mark/funding/OI for RV). Cache-testable. (Watch: causal RV only, overfit the HAR lags.)

## GUARDRAILS (repo discipline — audit/AUDIT_PROTOCOL.md; CLAUDE.md over-null AND over-carry gates)
- DuckDB: `SET memory_limit='1400MB'; SET threads=1` if you touch it. Cache probes are cheap (numpy).
- Every book claim: PHASE-AVERAGE over reb offsets, t+1 entry (S0.fwd_sum), per-fold (month) sign test, day-block CI. Report point
  estimate + CI, NOT a bare IC. A null must EARN it (CI + cross-fold sign + is-it-underpowered). A positive faces multiplicity.
- VERIFY before reporting a bug: show the exact line + a minimal repro/probe. No edits to repo files — probes go in scratchpad.
- Two envs: `.venv/bin/python` (numpy+duckdb, NO pandas/matplotlib); `/opt/miniconda3/bin/python` (pandas/matplotlib).

## DELIVERABLE (each agent)
(1) BUGS/ISSUES found in the audited code (verified, with repro) or "clean, here's why". (2) A RANKED list of DIFFERENT/BETTER
constructions with the SCOPE tags: hypothesis / construction / test+cost (cache/pipeline/asset_ctx) / leakage+overfit risk / maker-vs-
taker / priority. (3) A quick cache PROBE of your top idea. (4) "if I could test ONE thing" pick. Ideas + verified findings, not verdicts.
