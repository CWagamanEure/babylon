# FEATURE-COMBINATION SWARM (2026-07-11): what OTHER features, combined with the wallet-flow signal, lift OOS IC (and the MAKER net)?

GOAL: the wallet-flow selection signal `s_inf` has pooled IC **+0.0231** — a thin slice of a big target (forward residual return is
~47bp/hr median per alt). Find features F, ORTHOGONAL to `s_inf`, that in COMBINATION lift the OUT-OF-SAMPLE IC — and, because the taker is
closed and the maker is the only live leg, that lift the MAKER net bp/hr, not just an academic IC. Regime-conditioning is a first-class part
of this (where is the signal strong/weak; does a 2nd feature tell us when to trust it). Steelman + a mandatory prosecutor pass (feature
combination is the single highest-overfit activity in quant — the over-CARRY gate is the dominant hazard here).

## GROUNDING (measured on the cache, 2026-07-11 — build on these, don't re-derive)
- `s_inf` pooled IC(fwd-4h-resid-rank) = **+0.0231**; per-hour IC mean +0.0216 / median +0.0192 / **std 0.166** / 55% hours positive
  (weak-but-real, very noisy per hour → combination must be judged pooled + per-fold, never per-hour).
- Forward residual return magnitude = **median 47bp/hr per alt, p90 78bp** — the signal explains a sliver; large orthogonal variance remains.
- **⭐ Strongest orthogonal feature already visible:** trailing-24h cross-sectional momentum has IC **−0.0320** with the forward return (the
  residual REVERSAL) — LARGER than the wallet signal, and `s_inf` is ALREADY residualized ⊥[crowd, mom] so it is constructed orthogonal →
  a combined (reversal + flow) signal is legitimate and may lift IC materially. NOTE: reversal alone is taker-untradeable AND its standalone
  maker ceiling was weak/negative OOS ([[babylon-xsec-statarb]] REVERSAL FLOOR) — so the test is whether the COMBINATION lifts the maker net.
- Mild regime structure: dispersion IC low +0.0231 / **mid +0.0258** / hi +0.0203; session-of-day **08-16Z +0.0296** vs 00-08Z +0.0183.

## THE SYSTEM & DATA
`s_inf = Σ_w W_w·q_{w,a}` (size-blind wallet reallocation breadth, ⊥[crowd, trailing-mom]), ranked → decile long-short, maker book.
- **Cache** `data/derived/xsec_kalman/panel_cache.npz`: `R,Cc` (cell hour 0..7991 + coin 0..44), `s_inf`, `hours(7992)`, `panel_month(7992)`
  (7 folds 202512..202606), `disp(7992)` (cross-alt dispersion), `resid_alt(7992,45)` (per-HOUR resid return = target & book PnL; forward via
  `S0.fwd_sum` → t+1), `hs_arr(45)`, `hs_default`, `n_alt=45`. Book+cost machinery: `research/studies/wallet_flow/ideation_tier1_eval.py`
  (`book()`, maker/taker cost, phase-avg, per-fold sign, day-block CI — reproduces the frozen baseline reb4 maker +3.17/reb2 +5.37/hr).
- **asset_ctx** (DuckDB `research.data.db.connect`; `SET memory_limit='1400MB'; SET threads=1`): per-coin per-hour funding, open interest,
  mark/mid, impact bid/ask, volume → the FEATURE SOURCE for funding/OI/basis/liquidity/vol. **Pipeline** (`kalman_swarm_perwallet.py` load
  ~130s) gives per-wallet votes → consensus/breadth/wallet-structure features + the pre-residual signal.
- Known LIVE orthogonal lever already: **directional CONSENSUS** `cons_a=|Σ W·sign(q)|/Σ W` (contested cells fwd-IC≈0, unanimous ≈+0.05,
  corr −0.20 with breadth) — a proven 2nd axis; formalize its combined IC lift properly.

## FEATURE FAMILIES (each agent takes one lens; extend, don't be limited)
- **Reversal × flow** (the #1 grounded lead): combine `s_inf` with the trailing-reversal signal (−0.032); OOS-weight the combination; does it
  lift pooled IC AND the maker net? Test also fast/slow reversal horizons.
- **Funding / OI / basis** (asset_ctx): cross-sectional funding extremes, OI change/divergence, perp basis — orthogonal to flow? combined IC?
- **Volatility / dispersion / SESSION regime**: regime-condition and regime-INTERACT `s_inf` (mid-disp, 08-16Z session, vol state); a gated or
  regime-scaled model. Is the signal being AVERAGED across regimes where it's dead + regimes where it's strong?
- **Consensus / breadth / wallet-structure**: formalize consensus×s_inf + breadth into an OOS stacked model; wallet-dimension features (skill
  dispersion, effective-N, smart-vs-crowd polarization).
- **Liquidity / volume / microstructure**: volume, ADV, turnover, spread state as conditioning features (trust the signal more in liquid names?).
- **Signal-derived / higher-order**: signal momentum/acceleration, signal dispersion, signal age/freshness, second-derivative of flow.

## GUARDRAILS — the OVER-CARRY gate is the dominant hazard (CLAUDE.md; feature-combination overfits by construction)
1. **OOS only.** Fit any combination weight / regime threshold on TRAIN folds, apply forward. Report the IC LIFT (combined − s_inf-alone), not
   just the combined IC. In-sample IC ALWAYS rises when you add features — it is meaningless.
2. **Matched-DoF null (mandatory).** Adding K features lifts in-sample IC by ~√(K/N) for free. Your feature must beat a matched null: add K
   RANDOM features (or shuffle the real one within hour) and show the real lift exceeds the null band. State it.
3. **Per-fold sign test on the LIFT** across all 7 folds, + day-block CI on the lift. A lift that's 4/7 folds / CI-crosses-0 is a lead, not a win.
4. **Orthogonality check.** Report corr(F, s_inf). A feature ~collinear with s_inf adds nothing (this killed SE/vote-variance = 97% collinear
   with breadth). A feature must be BOTH orthogonal AND incrementally predictive.
5. **Deployable check.** An IC lift that doesn't lift the MAKER net bp/hr (phase-avg, per-fold) is academic — the maker leg is the only live one.
   Report the maker-net delta, not just IC.
6. **Multiplicity.** State the size of your feature/threshold search. The winner of a 50-feature hunt needs a far bigger lift to be real.
7. Verify before claiming; no repo edits (probes in scratchpad); two envs (`.venv/bin/python` numpy+duckdb / `/opt/miniconda3/bin/python` pandas).

## DELIVERABLE (each agent)
Ranked feature/combination ideas with SCOPE tags (hypothesis / construction / corr-with-s_inf / test+cost / OOS-IC-lift with per-fold sign +
matched-null / MAKER-net delta / overfit+multiplicity / priority), a real cache/asset_ctx PROBE of your top combination WITH the OOS lift +
per-fold sign + matched-DoF null, and a "test ONE thing" pick. Be honest if a feature adds nothing OOS (an earned negative is a real result);
be equally honest if a real orthogonal lift survives the null — that's a genuine maker-side improvement worth banking.
