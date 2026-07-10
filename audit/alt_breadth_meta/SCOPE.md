# Alt-breadth META-AUDIT — "what are we averaging away?" (creative signal-recovery swarm)

**Premise (user):** "We are for sure missing something." The alt-breadth informed-cohort study returned an EARNED
NEGATIVE for deployment (pooled partial IC|OFI +0.0058, ~10× sub-cost), but a pooled cross-sectional rank-IC is
exactly the estimator that can AVERAGE a real, concentrated signal into mush. Your swarm's job is NOT to re-confirm
the null — it is to hunt, creatively and adversarially, for where a REAL signal is being over-generalized,
under-generalized, netted, or averaged away. Steelman-the-positive discipline (CLAUDE.md over-null gate): a positive
point estimate that a better-targeted estimator could surface must be surfaced, not buried.

## What was done (read the code + FINDINGS.md Result 7 before anything)
- `research/studies/wallet_flow/alt_flow.py` — the pipeline. Residual = hourly log-return of each of ~45 PIT-liquid
  alts, neutralized on **BTC + ETH-orth + ONE leave-one-out equal-weight alt index** (causal rolling beta W=720),
  forward H=**1h**, POST-bucket. Cohort = top **20%** of eligible wallets by TRAIN "alignment" = mean(sign(flow)·
  fwd_resid). Cohort flow per (coin,hour) = **Σ flow_signed over cohort wallets, BOTH crossed**; OFI = Σ FILTER(crossed).
  Deliverable = **pooled rank-IC** of (cohort flow ⟂ OFI) vs fwd_resid across ALL 129,510 coin-hour cells, per-coin
  z-scored then pooled. TRAIN month<202603 / TEST≥202603 (4 months, data hole 2026-04-18→05-16).
- `alt_placebo.py` (random same-size cohorts), `alt_confirm.py` (in-sample positive control z=+16.85; walk-forward),
  `alt_sweep.py` (cohort-sharpness Q∈{20,10,5,2,1}% + conviction-weighted book), `alt_wf_sharp.py` (WF at sharp Q).
- Key results: pooled placebo z=+0.91 p=0.19 FAIL; sharpen→top-1% z=+1.88 p=0.020 (argmax, half mechanical baseline
  collapse); conviction-weighted (all wallets) DEAD NULL z=−0.14; sharp-WF 4/4 same-sign p=0.062; in-sample z=+16.85.
- Binding design: `research/studies/wallet_flow/ALT_BREADTH_AUDIT_RESPONSE.md`. NOTE a real gap it flags: the
  mandated **3–5 sector/PC factors + sector-matched placebo (F4) were NEVER built** (only the single LOO index).

## Data / reuse (do NOT re-scan the 337M-row tape)
- Cached, memory-safe: `alt_flow.build_resid(con, coins)` rebuilds the residual panel in ~17s;
  `alt_flow.build_cohort_tables(con, coins)` registers views **awb** (wallet×coin×hour flow, 60M rows, 2.4GB — cached
  parquet at `<SCRATCH>/alt_wb/`) and **aagg** (coin×hour OFI, tiny). `alt_universe.universe(con, 20260301)` = 45 alts.
- `<SCRATCH>` = `/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad`.
- Python: `/Users/corywagamaneure/bablyon/.venv/bin/python` (numpy + DuckDB only; NO pandas/pytz — never materialize a
  tz timestamp; use `epoch_ms(...)` in SQL).

## ⛔ MEMORY-SAFETY (this box OOM-kills — non-negotiable)
- Every DuckDB connect: `SET memory_limit='600MB'; SET threads=1; SET preserve_insertion_order=false;`
  and a UNIQUE temp dir: `SET temp_directory='<SCRATCH>/duck_<youragentletter>'`.
- **Do ALL heavy aggregation IN SQL; only ever `fetchnumpy()`/`fetchall()` SMALL results** (coin-level ~45 rows, or
  coin-hour ~350k rows max). NEVER pull the 60M-row wallet grain into Python. Prefer GROUP BY in DuckDB (it spills to
  disk safely) over numpy over big arrays.
- Keep your probes LIGHT (a few queries). You do NOT need to run a full re-study — the orchestrator will run the
  heavy confirmation of your top proposal. Your deliverable is DIRECTION + the exact decisive test.

## Rules
- READ-ONLY. Do not edit any file under `research/` or `src/`. Write scratch scripts to `<SCRATCH>` only.
- Verify before you claim (AUDIT_PROTOCOL): show the query + number behind every assertion.
- If you find a positive cut, you MUST also state its multiplicity cost (how many cuts you tried) — no argmax-as-headline.

## DELIVERABLE (return as text)
1. The single strongest mechanism by which THIS pipeline could be averaging/netting/over-neutralizing away a real edge.
2. Any light evidence you gathered (queries + numbers), honestly caveated with multiplicity.
3. The ONE decisive test to run next, as exact code / precise spec (what to compute, on what grain, expected signature
   if the signal is real vs benign).
4. Your lens's verdict: is there a live thread here, or is this dimension genuinely exhausted?
