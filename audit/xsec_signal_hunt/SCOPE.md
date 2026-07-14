# SIGNAL-HUNT SWARM — where are we HIDING / OVER-NULLING the edge? (2026-07-10)

This is the OVER-NULL / signal-recovery counterpart to the prosecutor swarm (`audit/xsec_flow_decompose/`).
Mandate (CLAUDE.md OVER-NULLING GATE + user): find where ASSUMPTIONS, AVERAGING, or CLAUDE'S PESSIMISM are
SUPPRESSING a real edge. A p>0.05 / "sub-cost" / "earned-negative" is NOT proof of absence. Your bias should be
to RECOVER signal the current analysis buries — while staying honest (don't manufacture; note forking paths).

## The finding so far (what you're re-examining)
A cross-sectional wallet-flow SELECTION signal on ~45 PIT-liquid HL alts. Predictor = size-blind RELATIVE
(demeaned) reallocation flow of a shrunk-skill-weighted informed cohort; target = per-hour cross-sectional RANK
of forward BTC/ETH-residual return. Current verdict: **real & statistically green** (V-trail L2 IC +0.023
[+0.018,+0.029] z≈8, 39/45 coins, survives leakage+multiplicity+prosecutor) but **TAKER earned-negative**
(measured ~10bp impact-cost × 1.3–1.5 turnover > 2.3bp/hr gross) and **MAKER break-even-to-thin** (~+1.1bp/hr
decile, gross of unmodeled adverse selection). Claude concluded "offline analysis exhausted, gated on fill."

## Corpus (read what your focus needs)
- Code: `research/studies/wallet_flow/`  → `xsec_flow_step0.py` (S0: panel `build_resid` via alt_flow, `run_horizon`
  skill-weights/embargo, `build_q` demean, `residualize`, `fwd_sum`, `xsec_rank`, `trailing_resid_mom`),
  `xsec_flow_adjudicate.py` (ADJ: `build_q_fixed`, `gap_lag`, quintile `_hour_spreads`, `_spread_ci`, `sign_test`),
  `xsec_flow_decompose.py` (D1 horizon / D2 extremity+conviction / D3 per-coin+ADV / D4 regime / gap-lag / D5 cost),
  `xsec_taker_book.py` (held-book taker backtest w/ impact-price cost + turnover). Also `alt_flow.py`, `alt_universe.py`.
- Results (FULL grids — mine these, don't rebuild): `data/derived/xsec_flow_adjudicate/results.json`,
  `data/derived/xsec_flow_decompose/results.json`, `data/derived/xsec_taker_book/results.json`.
- Prior swarm verdicts: `audit/xsec_flow_decompose/SCOPE.md` + the finding history in memory `babylon-xsec-statarb`.
- Logs: scratchpad `decomp_run.log`, `taker_run.log`, `adj_run.log`.

## ⚠️ RESOURCE SAFETY (8GB box, 6 sibling agents running concurrently — HARD RULES)
- **Do NOT rebuild the residual panel or reload the 37M-row flow tape** (that is what the main scripts' `run()` do;
  7 parallel rebuilds WILL OOM the box). Work from the EXISTING results.json + code reading.
- You MAY run SMALL read-only checks: `.venv/bin/python` arithmetic on results.json; at most ONE small targeted
  DuckDB query with `SET memory_limit='800MB'; SET threads=1` (e.g. a per-coin or per-hour aggregate) if truly
  needed. Prefer proposing a computation as a recommendation over running a heavy one.
- NO edits to any file. Verify-before-report.

## Deliverable
Findings most-impactful-first. For each: (a) the specific ASSUMPTION / AVERAGING / PESSIMISM, with `file:line`;
(b) WHY it plausibly hides or understates real edge; (c) a CONCRETE, buildable proposal to recover it + your best
estimate of how much signal it could recover; (d) confidence (CONFIRMED by a check / PLAUSIBLE / SPECULATIVE).
Explicitly call out any place CLAUDE'S VERDICT was too pessimistic (rounded a positive down to null/sub-cost/dead).
Honesty guard: if a suspected suppression turns out not to hide anything, say so. End with your TOP-1 highest-EV
next experiment. Return the report as your final message (data for the orchestrator, not user-facing).
