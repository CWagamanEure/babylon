# Audit 01 — Universe construction & survivorship  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/01_universe.md`.

## Scope
The rolling past-only universe is the single biggest historical lever: a frozen survivor pool
inflated the edge from ~+15 to +159 bp/RT. Your job is to prove the "past-only, rolling"
construction is *actually* leak-free end to end — in the offline export AND in the live roller.

## Read
- `other_repo_notes/README.txt` (construction spec: top-1500 by cumulative PAST notional per k).
- `scripts/convergence_his.py`, `scripts/split_his_fills.py` (how `past_univ.json`/universe is built/consumed).
- `src/babylon/follow/selection.py`, `src/babylon/follow/scheduler.py` (live universe per roll).
- `scratch_conv/universe_k.json`, `scratch_conv/boundaries.txt` (the artifact actually used by `edge_sweep`).

## Adversarial hypotheses to test
1. **Does `past_univ[k]` truly use only months 0..k?** Check the boundary at each transition: a
   single off-by-one (including month k+1's notional, or `<=` vs `<` on the boundary ms) silently
   re-introduces future information into selection. Trace `bounds[k]`→`t0,t1` in `edge_sweep.py`.
2. **Superset contamination.** The exported fills are the *union* over all k. Confirm nothing in
   the measurement keys off "is this wallet in the superset" (that's a whole-period survivor signal).
3. **Live ≠ offline universe rule.** Does the live `selection.py` reproduce "filter candidates to
   `past_univ[k]`", or does it ever rank over a frozen/current roster? A drift here means the
   deployed edge ≠ the validated edge.
4. **Notional definition consistency.** README ranks by taker notional excluding majors+`:` coins.
   Does the live/selection path rank by the *same* notional definition? A different denominator
   re-sorts the universe.
5. **Eligibility re-introducing survivorship** (cross-check with audit 05): is the candidate pool
   ever gated on a *performance* statistic computed with future data?

## Do NOT re-report
Known #1 (frozen-pool survivorship) and #6 (eligibility on closed-RT count, fixed fe44463) — only
flag if you find the fix incomplete or reintroduced.

## RAM
STATIC — reason from code + the small JSON artifacts. Do not open the monthly parquets.
