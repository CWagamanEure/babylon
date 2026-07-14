# SESSION-AUDIT SWARM (2026-07-11): adversarially audit this session's taker-revival + feature-combination CONCLUSIONS

This session ran two big swarms (taker-revival, feature-combination) + follow-on tests and reached a lot of NEGATIVE / "undeployable"
verdicts. Your job: audit whether those conclusions are CORRECT — over-NULL (we buried a real signal), over-CARRY (we banked something that
won't hold), stats errors, averaging-away (we hid signal in a pooled construction), and code bugs. Both error directions are live. The record
is `research/studies/wallet_flow/FINDINGS.md` (read the entries from "IDEATION SWARM — TIER-1 TEST" onward — that's this session).

## THE LOAD-BEARING CLAIMS TO AUDIT (with their numbers — verify, don't take on faith)
**A. TAKER DEFINITIVELY CLOSED.** Invariant: fee×turnover dominates; turnover is DECAY-LOCKED at ~1.3/reb because alpha HL~4h. Sub-claims:
  (a) GP cost-aware partial-rebalance (aim portfolio): alpha-per-turnover ceiling **2.48bp < impact-spread 3.25bp → dead even at ZERO fee**.
  (b) persistence/EMA subset: best break-even fee +0.89 (<2.4). (c) alpha-decay: NO slow tail (marginal IC lag13-48h = −0.0006); gross &
  cost curves never cross. (d) execution: killer is the FEE not spread; free-spread taker at 2.4 fee = +0.40/hr 3/7. (e) cheaper estimand: k=1
  pair +1.17/hr post-hoc non-monotonic. (f) steelman: GP-aim+reb8+γ0.05+MID reaches +0.36/hr CI[+0.02,+0.72] 6/7 but sign-p 0.125, 2-3/4 clean
  folds. (g) position-building (accumulation cohort): FALSIFIED — decays faster, gross halved, taker worse.
  ⚠️ ONE untested JOINT combo flagged by the GP agent but NEVER run: **GP-aim (best alpha/turnover) × the tight-spread LIQUID subset (14 names
  hs<2.5bp)** — the ceiling only fails vs the 3.25bp POOLED spread; does the signal carry more alpha-per-turnover in liquid names to clear ~3.7bp?
**B. REVERSAL real-IC but MAKER-UNDEPLOYABLE.** REV=−trailing-mom, IC +0.032 (z=14 vs matched null, REAL). Prosecutor: combined maker delta CI
  STRADDLES 0 under 3-way split (reb4 −0.04 [−1.06,+1.03]); REV IC DECAYS across folds, NEGATIVE on 2 most recent (+0.041→+0.007→−0.014).
  First agent's "+1.4-1.6/hr 7/7 bank it" used FAST k=4 (corr +0.15, adverse-selection-prone). Confirms prior REVERSAL-FLOOR maker-weak negative.
**C. Δlog-OI + impact-spread = SAME crowding/reversal factor, maker-undeployable** (dlog_oi8 maker +0.72/hr 7/7 but CI OVERLAPS base; spread
  gate = concentration + spread-earn-CREDIT artifact). LEVELS (funding/basis/volume/OI) all dead.
**D. REGIME `mabs`(market-|ret|): real Sharpe/rate lever but CONCENTRATES not adds** (28% cov; total-return/hr FALLS 3.17→1.26); dispersion
  "mid-cell" = in-sample MIRAGE (frozen→flat).
**E. CONSENSUS = the one reversal-distinct maker lead** (corr +0.016 w/ REV): reb2 +0.70/hr paired-CI[+0.07,+1.31] SIGNIFICANT but FADES neg on
  202605/06; reb4 +0.34/hr underpowered but HOLDS recent. Significance & recent-robustness DON'T coincide → forward-gated.
**F. VERDICT: ship s_inf-alone + consensus (live A/B) + magnitude-weighting (+8% mean tilt).**

## HARNESS FACTS (established, high-confidence — the machinery is trustworthy)
Every probe reproduces the FROZEN baseline EXACTLY: decile equal-weight maker_a30 = reb4 +3.17/hr, reb2 +5.37/hr, 7/7 folds. So book/cost
plumbing is correct on the baseline; audit the VARIANT paths + the statistical inferences, not the baseline.

## DATA & ARTIFACTS
- Cache `data/derived/xsec_kalman/panel_cache.npz`: R,Cc,s_inf, hours(7992), panel_month(7 folds 202512..202606), disp, resid_alt(7992,45),
  hs_arr(45), hs_default, n_alt=45. Forward via `S0.fwd_sum` (t+1). Book/cost/CI machinery: `research/studies/wallet_flow/ideation_tier1_eval.py`
  (`book()`, maker/taker cost, phase-avg, `_dayblock_ci`, `_sign_test`), `ideation_tier2_eval.py` (fill-rate model), `taker_posbuilding.py`
  (position-building). asset_ctx (DuckDB `research.data.db.connect`, `SET memory_limit='1400MB'; SET threads=1`) = funding/OI/spread/vol.
  Pipeline (`kalman_swarm_perwallet.py` load ~130s) = per-wallet votes / consensus / pre-residual S.
- The prior agents' probe scripts are in the SESSION SCRATCHPAD `/private/tmp/claude-501/-Users-corywagamaneure-bablyon/<session>/scratchpad/`
  (aim_probe.py, persist_probe.py, taker_*.py, rev_flow_probe*.py, combo*.py, regime_*.py, fund_v2.py, liq_*.py, consensus_*.py) — READ them to
  check the actual constructions for bugs; you may re-run/modify in scratchpad.

## GUARDRAILS (CLAUDE.md — BOTH gates; this is a verification pass, be adversarial and specific)
- **Over-null**: a "dead"/"undeployable" verdict must EARN it — point estimate + CI + positive-control MDE + cross-unit sign. If a negative
  rests on an underpowered test (2-fold "decay", a CI that includes a care-about effect, a construction that can't recover an injected edge),
  flag it as INCONCLUSIVE, not dead. The taker's untested GP×liquid-subset combo (A⚠️) and the reversal-maker "decay on 2 folds" are prime
  suspects for over-null.
- **Over-carry**: any surviving positive faces the full FP gauntlet (matched-null, per-fold sign across ALL 7 folds, multiplicity across the
  whole session's search, deployable-net not just IC). Consensus reb2's front-loaded significance and magnitude-weighting's +8% are suspects.
- **Averaging-away**: is a real signal being hidden by the POOLED equal-weight decile book / the z-blend combination / phase-averaging? (e.g. is
  reversal maker-deployable in a LIQUID subset or a different construction the pooled book averages out?)
- **Stats**: audit the specific inferences — paired-delta CIs, matched-DoF nulls, 3-way splits, the "decay across folds" (real trend or 2-fold
  noise?), per-fold sign p-values, effective-N / coin-independence, multiplicity accounting.
- VERIFY before claiming (reproduce the load-bearing number or cite the exact probe line). No repo edits — scratchpad only. `.venv/bin/python`
  (numpy+duckdb) / `/opt/miniconda3/bin/python` (pandas). DuckDB memory_limit 1400MB, threads 1.

## DELIVERABLE (each agent)
A ranked list of AUDIT FINDINGS from your lens: for each, the claim audited, VERDICT (confirmed / over-null / over-carry / stat-error / bug /
inconclusive), the evidence (reproduced number or cited line), and the corrected conclusion + its CI. Run a real probe on your highest-value
finding. End with a one-line "the single most important correction (if any) to this session's conclusions."
