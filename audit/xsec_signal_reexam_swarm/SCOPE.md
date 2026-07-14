# SIGNAL RE-EXAM + TASK-4 AUDIT SWARM (2026-07-11)

Two jobs: (1) ADVERSARIALLY AUDIT the fresh maker-leg resolution (~+1/hr positive) + the session's settled conclusions — the newest
claim is a POSITIVE so OVER-CARRY is now the dominant hazard; (2) GENERATIVELY re-examine the settled signal `s_inf` for a GREATER
averaged-away signal, and hunt NONLINEAR feature combinations that lift OOS IC. Record = `research/studies/wallet_flow/FINDINGS.md`
(read "WHERE IS THE SIGNAL LEAKING?" onward, incl. the "RE-COSTING AUDIT SWARM ADJUDICATION" and "TASK-4 OFFLINE RESOLUTION" entries).

## THE STATE TO AUDIT / BUILD ON (verify the numbers; don't take on faith)
**Settled signal `s_inf`** = Σ_w W_w·q_{w,a} (size-blind wallet reallocation breadth, ⊥[crowd, trailing-24h mom]), ranked → decile
long-short. Pooled OOS IC (canonical GLOBAL pooled Spearman `_spear` vs per-hour xsec-ranked fwd-4h resid return) = **+0.0231, fold-t
+7.97, 7/7 folds**. ⚠️ per-hour-ranked IC is a BUG (sign-unstable) — always use global `_spear`; anchor `_spear(cache s_inf, fwd)=+0.023`.

**Prior session verdicts (audit whether still right):**
- A. Wallet-SELECTION CLOSED: honest split-half oracle +0.0198 ≈ current; +0.12 full-oracle was DoF inflation; equal-weight breadth +0.0192.
- B. CONVICTION/magnitude CLOSED: size-blind best; every magnitude transform ≤ (raw −0.017 t−7).
- C. COIN/REGIME ~closed: coin-IC persistence +0.12; honest OOS coin-select +0.0256 vs +0.023.
- D. HORIZON: 4h ~optimal (plateau h2-4); marginal decay half-life ~2-3h.
- E. `|s_inf|`→forward-VOL: partial IC +0.042 (7/7) BUT ~2× over-carried (contemp-move control → +0.024); non-novel (MDH/VPIN); UNBANKABLE
  (no alt options; maker vol-gate zeroes gross). Downgraded to confirmatory diagnostic / sizing overlay.
- F. OFI-signed adverse selection rises with |s_inf| (Q0 6.5→Q4 14.3bp) — sound as MARKET-IMPACT, but NOT the directional maker's cost.
- ⭐G (THE FRESH POSITIVE — audit hardest). Maker-leg sign, after a round trip (flat "+1-2" → mis-specified "−11.6/dead" [OVER-NULL, symmetric-
  MM impact charged to a directional book, corr(pos,OFI)=−0.08 fades the crowd] → swarm "inconclusive~0"), RESOLVED by TASK-4 to a SMALL
  POSITIVE. `task4_fillcond.py`: position-signed, fill-conditional residual markout — weight each decile name's pos-signed fwd RESIDUAL return
  by OPPOSING taker volume that fills it (long←sell-taker, short←buy-taker, from alt_flow crossed/flow_signed). Real liquid half-spread 1.36bp.
  Net/hr = fillcond gross + 1.36 − 1.0 fee: **reb2 +1.47 (6/7, recent +1.45), reb4 +1.10 (5/7, recent +0.68)**. KEY model-light finding:
  fill-selection adverse corr(opposing-flow, pos-signed fwd) = **+0.012/+0.016 ≈ 0** (fills NOT adversely selected — the informed decile fades
  the crowd). Labeled SMALL LIVE POSITIVE, underpowered (fold-t ~2-2.7), single-model (entry-only spread, IGNORES EXIT-side adverse selection,
  assumes clean factor hedge).

## DATA & MACHINERY
- Cache `data/derived/xsec_kalman/panel_cache.npz`: R,Cc (cell hour-idx 0..7991 + coin 0..44), s_inf, hours(7992), panel_month(7 folds
  202512..202606), resid_alt(7992,45)=per-hour resid return (target via `S0.fwd_sum` strictly t+1..t+h), disp(7992)=cross-alt dispersion,
  hs_arr(45), n_alt=45. Canonical IC = `_spear` (global pooled Spearman). Coin order = `A.universe(con, A.UNIV_FORMATION, include_majors=False)`
  (matches Cc; verified per-coin diagonal corr(asset_ctx return, resid_alt) median +0.34).
- `asset_ctx` (DuckDB `research.data.db.connect`; `SET memory_limit='1400MB'; SET threads=1`): per-MINUTE mid_px, impact_bid/ask_px,
  day_ntl_vlm, funding, open_interest. `alt_flow`: per (wallet,coin,bucket=5min) crossed(taker flag), flow_signed, n → OFI / taker buy/sell vol.
- Pipeline `research/studies/wallet_flow/kalman_swarm_perwallet.py` `load()` (~130s, 37M per-wallet votes) → per-wallet q, fold_weight, carry_aggregate
  (gives per-wallet consensus/breadth/structure + the pre-residual signal — needed for genuinely NEW feature construction).
- **Session probe scripts** in `/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad/`:
  decomp_leak.py, oracle_honest.py, conviction.py, vol_control.py, adverse_signed.py, recost_book.py, task4_fillcond.py, steel_*.py, AUDIT_micro*.py.
  READ for exact constructions; re-run/modify in scratchpad. `.venv/bin/python` (numpy+duckdb, NO pandas), PYTHONPATH=repo root; `/opt/miniconda3/bin/python` (pandas).

## YOUR LENS (one per agent)
**— AUDIT half (over-carry is now the dominant hazard) —**
- **OVER-NULL agent:** are the remaining NEGATIVES/DOWNGRADES over-nulled? Is Task-4's "underpowered/single-model" caveat TOO harsh (is the maker +1/hr
  actually more robust than labeled)? Is E's unbankable/downgrade over-nulled (a real deployable vol use missed)? Are A-D genuinely closed or is one
  a blind test? For any negative: point-est + CI + MDE + cross-unit.
- **STEELMAN agent:** steelman the maker +1/hr (bigger? more robust? add the reb-sweep / consensus / vol-sizing overlay to lift it) AND steelman that a
  GREATER deployable edge exists (better construction, a leg we dismissed). Any config must be OOS + realistic-cost (task4 fill model, 1.36bp spread).
- **AVERAGING-AWAY agent:** is the maker +1/hr much BIGGER in a sub-slice (coin, regime, session, |s_inf|-band, consensus-band) an ex-ante rule could
  target? AND — the user's ask — is `s_inf` itself AVERAGING AWAY a greater signal (the equal-weight decile, the ⊥crowd/mom neutralization, the
  size-blind sum, the breadth aggregation each pool over structure that a sharper construction would keep)?
- **STATS agent:** Task-4 rigor — fold-clustered CI on the +1.47/+1.10 net, the fill-model assumptions, EXIT-side adverse selection (unmodeled — bound
  it), effective-N (14 names), the +0.012 adverse corr significance, session-wide multiplicity now spanning the WHOLE arc incl. this swarm's new tests.
**— RESEARCH / GENERATIVE half —**
- **RESEARCH microstructure agent:** is the Task-4 fill model correct? Biggest open assumption = it IGNORES EXIT-side adverse selection and assumes a
  clean factor hedge (raw unhedged inventory markout was −15bp/4h = pure beta). Build/estimate the exit-side cost and the hedge slippage offline; does
  the +1/hr survive? What's the right realized-maker-net accounting per the market-making literature (fill prob × post-fill markout, both legs)?
- **SIGNAL-RECONSTRUCTION agent (user ask):** reconsider `s_inf` from scratch for a GREATER averaged-away signal. Suspects: (a) the ⊥[crowd, trailing-mom]
  neutralization may be projecting out real signal (test raw vs neutralized IC, and partial-out ALTERNATIVES); (b) the size-blind ±1 sum discards a
  sharper sub-population; (c) decile discretization + equal-weight is lossy vs a continuous/optimally-weighted score; (d) the 24h vote-trailing window /
  skill-weight recipe may be suboptimal. Use the pipeline `load()` for per-wallet structure. Show any lift OOS with matched-null + per-fold.
- **NONLINEAR-FEATURE agent (user ask):** the prior feature-combo swarm tested LINEAR z-blends only. Hunt NONLINEAR interactions that lift OOS IC beyond
  +0.023: s_inf × consensus (agreement-gated), s_inf × |s_inf| (conviction-conditioned), s_inf gated by vol/dispersion/session REGIME, sign(s_inf)×f(other),
  threshold/tree interactions, s_inf × Δlog-OI, s_inf × funding. ⚠️ HIGHEST over-carry activity in the whole study — MANDATORY: fit interaction/threshold
  on TRAIN folds, apply forward; report IC LIFT (combined − s_inf) not combined IC; matched-DoF null (add K random interactions, show real lift beats null
  band); per-fold sign on the LIFT; corr(feature, s_inf) orthogonality; state the size of your interaction search. An in-sample IC always rises — it is meaningless.

## GUARDRAILS (CLAUDE.md — BOTH gates)
- Over-CARRY is now dominant (fresh claim G is positive; feature-hunting overfits by construction): every positive faces matched-null + per-fold sign
  across all 7 folds + session-wide multiplicity + deployable-net (not just IC) + orthogonality. A lift that's 4/7 or CI-crosses-0 is a LEAD, not a win.
- Over-NULL still live: a "closed"/"unbankable"/"underpowered" verdict must EARN it (point-est + CI + MDE + cross-unit).
- VERIFY before claiming (reproduce the load-bearing number / cite the probe line). No repo edits (scratchpad only). Resource-safe (DuckDB memory_limit
  1400MB threads 1; per-coin loops not 43M-row fetches; pipeline load ~130s — budget it).

## DELIVERABLE (each agent)
Ranked findings: claim/hypothesis, VERDICT (confirmed / over-null / over-carry / stat-error / bug / real-lift / dead-end / inconclusive), evidence
(reproduced number or probe line), corrected conclusion + CI. RUN a real probe on your highest-value finding. End with the single most important
correction OR the single most promising NEW lead (with its OOS lift + per-fold + matched-null), honestly labeled.
