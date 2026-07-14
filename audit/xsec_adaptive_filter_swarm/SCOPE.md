# RESEARCH SWARM — an ADAPTIVE observation-noise (R) / process-noise (Q) model for the xsec selection signal

We only ever tested a FIXED-gain filter (constant α=0.90 = constant Kalman R) → a small phase-fragile tilt. The user's
point: the powerful filter has a **time/coin/wallet-VARYING R** — trust each hour's measurement LESS when it is noisier.
We already KNOW the signal quality is heteroskedastic (2× IC in mid-dispersion; the denoise helps most in noisy hours),
so an adaptive-R filter has real headroom the constant gain cannot reach. This swarm's job: **design + EMPIRICALLY discover
what observables drive R (and Q), grounded in the data.** Do NOT build the final filter yet — DISCOVER the drivers.

## The model
Latent state x_a = the true forward-predictive selection signal for alt a. Observation z_{a,t} = the measured per-hour
`S_a`. **R_{a,t} = observation noise = how much to DISTRUST this hour's measurement.** inverse-R ∝ the CONDITIONAL forward
predictive quality: where the signal's forward IC is HIGH, R is low (trust it); where IC COLLAPSES, R is high (lean on the
prior / smooth harder). **Q = process noise = how fast the true state drifts** (high Q → trust new obs more → smooth less).
So the empirical program is: **find observables `f` such that the signal's forward IC is strongly heteroskedastic in `f`.**
Those are the R/Q drivers. (This is a heteroskedastic measurement model, richer than a scalar Kalman.)

## CANDIDATE R/Q DRIVERS (your lens = one family; propose more)
- **Crowding / noise-trader contamination (R):** when the hour's `S_a` is built from MANY low-skill / marginal wallets, or
  contaminated by a burst of unskilled participation, the measurement is noisier. Observables: # distinct cohort wallets
  contributing this (alt,hour); share of the vote from LOW-W vs HIGH-W wallets; whale-concentration (one wallet = X% of the
  vote); skilled-vs-unskilled sub-cohort AGREEMENT (disagreement → high R).
- **Per-wallet track record (R / a dynamic W):** we use a STATIC train-frozen skill weight. Test a CAUSAL, rolling per-wallet
  reliability (recent hit-rate / recent forward-IC of that wallet's votes) — is dynamic trust a better precision weight than
  the frozen W? Bayesian shrinkage of each wallet's noise.
- **Per-token reliability (R):** rolling CAUSAL per-coin forward IC of the signal; per-coin vol / spread / liquidity. Are some
  coins persistently high-R? A per-coin adaptive gain.
- **Regime / process noise (Q):** cross-sectional dispersion (reconcile with the mid-dispersion 2× lift), realized vol,
  funding flips, volume spikes — do these make the true state DRIFT (→ high Q, smooth less) vs measurement-noise (→ high R,
  smooth more)? Distinguish an R-driver from a Q-driver empirically (R-driver: IC low AND smoothing helps; Q-driver: IC low
  AND smoothing HURTS).

## THE DIAGNOSTIC (how to measure R empirically) — do this, don't hand-wave
For a candidate observable `f`, bucket the signal cells by `f` and compute the CONDITIONAL forward IC of `s_inf` vs the
forward residual return within each bucket. Strong monotone heteroskedasticity in IC(f) ⇒ `f` is a real R/Q driver. Then the
deployable test (later) is whether a filter that DOWN-WEIGHTS high-R cells beats the fixed-α and baseline OOS + phase-averaged.

## RESOURCES
- **Cache `data/derived/xsec_kalman/panel_cache.npz`** (fast; POST-aggregation): keys R,Cc,s_inf,hours,panel_month,disp,
  resid_alt[7992×45],hs_arr[45],hs_default,n_alt,folds. Forward return of a cell = `S0.fwd_sum(resid_alt,h)[R,Cc]*1e4`;
  conditional IC = Spearman(s_inf, forward-resid-rank) within a bucket. Per-coin/regime/dispersion drivers are cache-doable.
- **Full pipeline (per-wallet composition & track-record drivers NEED this ~130s DuckDB load):** replicate the load in
  `research/studies/wallet_flow/kalman_swarm_perwallet.py` (gives wcode,ccode,r,mth,q_trail,W-per-fold,nW) — that's the ONLY
  way to get per-hour cohort composition (# wallets, W-concentration, skill-tier agreement) and per-wallet rolling reliability.
- `asset_ctx` (DuckDB) has per-coin funding / OI / vol / spread if a driver needs it. DuckDB safety: `SET memory_limit=
  '1400MB'; SET threads=1; SET temp_directory=...; SET preserve_insertion_order=false`.
- Reuse `xsec_concentrated_book` as CB for any booking; `ADJ.sign_test`; `xsec_flow_step0` as S0.

## GUARDRAILS (hard-won from the two prior swarms — violate and the result is worthless)
- **CAUSAL only:** any R/Q observable and any rolling stat uses ONLY data ≤ t. No look-ahead in the conditioning.
- **PHASE-AVERAGE any booked magnitude** (the reb4[::4] grid is a favorable phase — a single-phase number over-carries ~4×).
- **OOS-validate:** discover the R-driver on EARLY folds, confirm the conditional-IC pattern holds on LATE folds. In-sample
  heteroskedasticity is trivial to mine — it must replicate OOS.
- **Multiplicity:** every observable you scan is a DoF; report how many you tried; prefer drivers robust across a RANGE + OOS.
- Distinguish "IC is heteroskedastic in f" (a real finding) from "a filter using f beats baseline" (the deployable claim) —
  report both, don't conflate.

## ENV
`.venv/bin/python` (numpy+duckdb; NO pandas/matplotlib). Write NEW scripts `research/studies/wallet_flow/adfilter_<lens>_*.py`
or scratch. Do NOT modify frozen files or the cache.

## DELIVERABLE (each agent)
A written report: which observable(s) you tested, the CONDITIONAL forward-IC heteroskedasticity table (in-sample AND
OOS/late-fold), whether it is an R-driver or a Q-driver, and a concrete recommendation for the measurement/noise model
(what to ingest, what raises R). Flag what needs the pipeline vs cache. Both gates: don't over-null a weak-but-real driver,
don't over-carry an in-sample-only heteroskedasticity.
