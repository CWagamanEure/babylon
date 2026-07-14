# SWARM SCOPE — prosecute the α≈0.90 DENOISE win (over-carry gauntlet) + resolve the 2 open candidates (over-null)

Last swarm OVERTURNED a false null: my Result 11 said "smoothing dead" but a coarse-α grid had stepped over a
light-denoise optimum. We banked the win and wired it for the forward test. **Now apply the symmetric discipline:**
a fresh positive must face the FULL false-positive gauntlet (permutation null, multiplicity/FDR, kill-gauntlet,
replication) — the "prosecute the positive / null the residual" pass — AND we must NOT now over-null the two
remaining candidate levers. Both gates, equal standing (see `CLAUDE.md` / `[[babylon-overnulling-gate]]`).

## THE CLAIMS UNDER AUDIT
**CLAIM A — the banked win (prosecute hardest):** a strictly-causal AGGREGATE level-EMA `m_t = α·S_t + (1−α)·m_{t−1}`
at **α≈0.90** raises the decile long-short book **gross ~+27% (+3.74→+4.76/hr) with turnover FLAT (1.36→1.34)** — i.e.
via **DENOISING** (cross-sec IC +0.028→+0.030), lifting **maker_a30 +4.35→+5.06 (7/7 folds)** and **taker_smallclip
+1.42→+2.48 (CI clears 0)**. Corroborated by (a) a fine-grid inverted-U peaking at α≈0.87–0.90, (b) an INDEPENDENT
AR(1)+noise fit whose MSE-optimal gain lands α≈0.9 from the autocorrelation alone, (c) an early-4-folds→late-3-folds
OOS overfit-killer that wins OOS on all legs (LATE gross +3.94→+5.39). Reproduced by 4 agents last round.
**CLAIM B — the 2 unresolved candidates (do NOT prematurely null):** (1) wider hysteresis hold-band **q2≈0.30** on the
FRESH signal → helps the TAKER (mid-regime 7/7 sign p=0.016, lower turnover), HURTS maker; (2) phase-averaged **reb=2**
→ maker +5.34/hr but grid-phase-confounded.

## KNOWN CAVEATS TO PROBE (the prosecution's leads)
- **α is tuned IN-SAMPLE** over a broad search (space × α × reb × regime) → the OOS split is ONE 3-month window (weak).
- **The maker lift (+5.06) sits INSIDE baseline's CI [+2.9,+5.7]** — is it statistically distinguishable from baseline at all?
- **Gross moved ~4× more than IC** (+27% gross vs +7% IC) — tail-noise amplification? Is the decile-spread gain a few
  lucky tail names, not a broad ranking improvement?
- **Grid-phase confound (horizon agent, last round):** the reb4 `[::4]` grid lands on FAVORABLE timestamps (reb4 gross
  +3.74 ≫ reb3 +1.94, reb6 +1.53). All α variants share that grid so the RELATIVE α effect may be clean — but VERIFY the
  denoise win replicates across all 4 grid phase-offsets AND across reb∈{3,4,6}, or it's a reb4-phase artifact.
- **The +27% from a 10% blend is large** — sanity-check the magnitude; is it a construction/leak artifact?

## RESOURCES (iterate FAST off the cache; no DuckDB unless a hypothesis needs pre-aggregation)
- **`data/derived/xsec_kalman/panel_cache.npz`** — fully-built leak-free cells (keys: R,Cc,s_inf,hours,panel_month,disp,
  resid_alt[7992×45],hs_arr[45],hs_default,n_alt,folds). Build dense `SIG[R,Cc]=s_inf`; `FVr=S0.fwd_sum(resid_alt,reb)`.
- Reuse the exact engine: `xsec_concentrated_book` as `CB` — `CB.simulate_raw`, `CB.scenario_net_series`, `CB.SCENARIOS`,
  `CB._dayblock_ci`; `ADJ.sign_test`. Rebalance grid frozen to `sorted(observed hours)[::reb]` (only signal differs).
- The exact denoise curve + OOS test: `research/studies/wallet_flow/kalman_swarm_decisive.py` (has `dense_ema`, fine grid,
  the early→late OOS split). The forward wiring: `xsec_book_eval.py` (`smooth_signals`, α=0.90 frozen A/B).
- Filtering harness from last round: `kalman_swarm_filter_lib.py` (+`_dynamics.py`,`_frontier.py`). Prior swarm:
  `audit/xsec_kalman_swarm/SCOPE.md`; the per-wallet DEAD lever: `kalman_swarm_perwallet.py`.
- **Baseline gate:** α=1 must give maker_a30 +4.35, taker_smallclip +1.42 (pooled reb4). Reproduce BEFORE trusting any variant.
- **Leakage discipline:** any filter/threshold strictly causal (signal ≤t only). Any tuned parameter = in-sample search →
  report multiplicity, prefer robustness across a RANGE, and OOS/permutation-confirm before crediting.

## ENV
- `.venv/bin/python` (numpy+duckdb; NO pandas/matplotlib). DuckDB safety if you connect: `SET memory_limit='1400MB';
  SET threads=1; SET temp_directory=...; SET preserve_insertion_order=false`. Write NEW scripts as
  `research/studies/wallet_flow/denoise_swarm_<lens>_*.py` or scratch. Do NOT modify frozen files or the cache.

## DELIVERABLE (each agent)
A written verdict with exact numbers (point est + day-block CI + per-fold sign for taker_top_smallclip / taker_top_impact
/ maker_earn_a30 / maker_earn_a50). State whether CLAIM A **SURVIVES the false-positive gauntlet** (and the honest
deployable magnitude/label), and — for the over-null lenses — whether CLAIM B's candidates should be pursued, killed, or
need a specific powered test. Address BOTH gates explicitly.
