# RE-COSTING AUDIT SWARM (2026-07-11): audit the session's decomposition + |s_inf|→vol + maker-re-costing conclusions

This session, holding the informed cohort fixed, decomposed `s_inf`'s OOS IC to find "what we're missing," then chased a lead
(`|s_inf|`→forward-vol) to its consequence (adverse selection) and RE-COST the maker book, reaching a load-bearing NEGATIVE: the
"+1-2/hr liquid maker" is a flat-cost-model artifact and the honest maker net is ≤0. Your job: audit whether these conclusions are
CORRECT. BOTH error directions are live — over-NULL (we buried a real deployable edge) and over-CARRY (we banked a fragile positive
or a too-harsh negative). Record is `research/studies/wallet_flow/FINDINGS.md` — read from "WHERE IS THE SIGNAL LEAKING?" onward.

## LOAD-BEARING CLAIMS TO AUDIT (verify the numbers; don't take on faith)
**A. WALLET-SELECTION axis CLOSED (powered neg).** Honest split-half oracle (fit wallet θ on half-fold A, eval disjoint half B) =
  +0.0198 ≈ current skill +0.0231; the +0.1205 full-oracle was ~85% DoF inflation. equal-weight breadth +0.0192 (skill adds only
  +0.004). Quintile curve NON-monotone. Claim: better per-wallet selection cannot lift IC; signal is diffuse BREADTH not smart-wallet-ID.
**B. CONVICTION/magnitude CLOSED (powered neg).** Held skill-selection fixed, varied vote value: base_sign +0.0231 BEST; every
  magnitude transform ≤ (raw −0.0166 t−7.1, sqrt −0.0070, wallet_norm −0.0067 despite look-ahead). Claim: size-blind is near-optimal.
**C. COIN/REGIME heterogeneity ~closed.** coin-IC half-A→half-B persistence Spearman +0.12; honest OOS coin-select top-half +0.0256
  vs pooled +0.0230 (+0.003); dispersion terciles flat. In-sample "keep best-10 → +0.049" = winner's curse.
**D. HORIZON: 4h ~optimal.** Directional IC plateau h∈[2,4] (h3 fold-t +10.3), marginal decay half-life ~2-3h (gone by h6). No hidden
  long-horizon directional signal.
**E. ⭐ |s_inf|→FORWARD-VOL (the positive).** `|s_inf|` (INTENSITY, not direction) predicts forward realized vol: raw IC +0.165;
  PARTIAL | trailing-vol = +0.048; PARTIAL | trailing-vol + trailing-|s_inf| + log-VOLUME = **+0.042 (h4 t+8.0, h24 t+10.2), 7/7 folds**.
  Signed s_inf→vol ≈0 (it's the magnitude). Volume itself does NOT predict fwd vol beyond trailVol (−0.016). Claim: certified real,
  orthogonal, ~2× directional, survives 3 confounds.
**F. OFI-SIGNED ADVERSE SELECTION rises with |s_inf|.** AC = sign(net taker OFI from alt_flow.crossed)·(fwd mid move bp). By |s_inf|
  quintile (30m): Q0 6.5 → Q4 14.3 bp; mean +8.6bp; Q4−Q0 gradient +6..+11bp POSITIVE all 7 folds. Earned hs ~4bp < AC everywhere.
**G. ⛔ MAKER RE-COSTING (the load-bearing NEGATIVE).** Replaced flat gross×0.70 with explicit per-cell adverse (EARN hs, PAY AC5 =
  sign(OFI)·5min mid move). Liquid subset (14 names, hs<2.5): reb2 net_flat +1.81 → net_REAL κ=1.0 **−11.6** / κ=0.5 −4.6; reb4 +1.50 →
  −5.2 / −1.6. Negative ALL 7 folds, both reb, both κ. Mechanism: decile trades EXTREME-rank = highest-|s_inf| = worst-adverse names.
  Claim: honest maker net ≤0; "+1-2/hr" was a flat-model artifact; xsec maker leg deployability in serious doubt (taker already dead).

## DATA & ARTIFACTS (verify against these)
- Cache `data/derived/xsec_kalman/panel_cache.npz`: R,Cc (cell hour-idx 0..7991 + coin 0..44), s_inf, hours(7992), panel_month(7 folds
  202512..202606), resid_alt(7992,45), hs_arr(45), n_alt=45. Canonical IC = GLOBAL pooled Spearman `_spear` (per-hour-ranked IC is a
  BUG — sign-unstable; the anchor `_spear(cache s_inf, fwd)=+0.023`). Forward via `S0.fwd_sum` (strictly t+1..t+h).
- `asset_ctx` (DuckDB `research.data.db.connect`; `SET memory_limit='1400MB'; SET threads=1`): per-MINUTE mid_px, impact_bid/ask_px,
  day_ntl_vlm (rolling daily notional volume), funding, open_interest. `alt_flow`: per (wallet,coin,bucket=5min) crossed(taker flag),
  flow_signed, n. Coin order = `A.universe(con, A.UNIV_FORMATION, include_majors=False)` (matches cache Cc; verified via per-coin
  diagonal corr(asset_ctx return, resid_alt) median +0.34).
- Pipeline `research/studies/wallet_flow/kalman_swarm_perwallet.py` `load()` (~130s, 37M per-wallet votes) → fold_weight, carry_aggregate.
- **Session probe scripts** in `/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad/`:
  `decomp_leak.py`, `oracle_honest.py` (A), `conviction.py` (B), `vol_control.py` (E), `adverse_calib.py`, `adverse_signed.py` (F),
  `recost_book.py` (G). READ them for the exact constructions; re-run/modify in scratchpad (`.venv/bin/python`, set PYTHONPATH=repo root).
  `.venv/bin/python` = numpy+duckdb (NO pandas); `/opt/miniconda3/bin/python` = pandas.

## YOUR LENS (one per agent; extend, don't be limited)
- **OVER-NULL agent:** the maker-dead (G) and the 4 closed axes (A-D) are the suspects. Is G over-nulled? κ=1.0 assumes 100% fill +
  full unconditional pickoff every rebalance — is that pessimistic-by-construction? What's the REAL fill model, and does a defensible
  one flip maker net positive? Is the adverse cost double-counting the gross? Is the honest-oracle (A) underpowered (half-fold fit)?
  For any negative: point-estimate + CI + MDE + cross-unit sign. Flag INCONCLUSIVE where a null rests on a pessimistic assumption.
- **STEELMAN-the-positive agent:** argue |s_inf|→vol (E) is REAL and DEPLOYABLE, and that a maker/vol strategy CAN net positive
  (e.g. vol-timing overlay, quote only low-|s_inf| cells, size by predicted vol, or a straddle/gamma structure). Find the config where
  the edge survives realistic cost. Also steelman that the directional signal has a deployable home we missed (taker with the vol gate?).
- **AVERAGING-AWAY agent:** is a real edge hidden in a POOL? Is the maker net negative on AVERAGE but positive in a sub-regime / sub-
  universe / sub-|s_inf|-band the pooled re-costing averages out? Is the vol signal averaged across coins where it's strong vs dead?
  Is adverse selection concentrated in a few names we could just exclude, leaving a positive core?
- **STATS agent:** audit the specific inferences — the partial-IC controls (E: is residualizing on trailing-vol the right control? omitted-
  variable?), the fold-clustered t's, the adverse-selection gradient significance, the re-costing per-fold spread + day-block CI, effective-N/
  coin-independence, the κ sensitivity, multiplicity across the whole session's search. Is the maker-negative statistically robust or a
  few-fold/few-name artifact?
- **RESEARCH agent — microstructure/adverse-selection:** is the OFI-signed adverse-cost proxy (F) methodologically sound vs the market-
  making literature (realized spread, effective spread, permanent vs transient impact, Glosten-Milgrom)? Is charging sign(OFI)·mid-move to a
  DIRECTIONAL maker correct, or does it mis-map our fills? Is the κ bracket right? What would a correct offline adverse-selection estimate be
  from the data we HAVE (asset_ctx + alt_flow), short of the Reservoir fill ingest?
- **RESEARCH agent — order-flow-informed volatility:** is `|s_inf|`→forward-vol (E) a known effect (informed-flow / order-flow → vol
  forecasting)? How is it monetized in practice (vol carry, gamma, sizing, execution timing)? Does the literature suggest the maker
  adverse-selection link is the right use, or a better one? Any confound we missed (OI change, funding, event-clustering)?

## GUARDRAILS (CLAUDE.md — BOTH gates; be adversarial + specific)
- Over-null: a "dead"/"undeployable" verdict must EARN it (point est + CI + MDE + cross-unit). G (maker-dead) rests on κ=1.0 pessimism →
  prime over-null suspect. Over-carry: E (vol positive) faces the full FP gauntlet (matched null, per-fold, multiplicity, deployable-net).
- VERIFY before claiming — reproduce the load-bearing number or cite the exact probe line. No repo edits (scratchpad only). Resource-safe
  (DuckDB memory_limit 1400MB, threads 1; per-coin loops not 43M-row fetches). Follow `audit/AUDIT_PROTOCOL.md` if present.

## DELIVERABLE (each agent)
Ranked AUDIT FINDINGS from your lens: for each — claim audited, VERDICT (confirmed / over-null / over-carry / stat-error / bug /
inconclusive), evidence (reproduced number or cited line/probe), corrected conclusion + its CI. RUN a real probe on your highest-value
finding. End with the single most important correction (if any) to this session's conclusions.
