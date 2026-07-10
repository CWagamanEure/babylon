# liq_reaction — DESIGN AUDIT response (2026-07-07)

Five adversarial design reviewers (leakage, false-fade, stats-design, feasibility, economic-premise) tore
at the original design (unconditional pooled fade-mean at 15 min, priced on `oracle_px`). Verdict: **do not
freeze as written** — the frozen primary was inconclusive-by-construction (an over-null trap). The redesign
(A1′, in `PREREGISTRATION.md`) resolves every load-bearing finding. Trail below, grouped by resolution.

## The pivotal contradiction (why we run adversaries with opposing priors)
- **feasibility-F1 [CRITICAL]:** `oracle_px` is an external CEX-median index blind to HL's own book
  overshoot → measuring on it is a **false NULL by construction**. Use `mid_px`.
- **false-fade-F4 [HIGH]:** measuring on the book price reintroduces the mechanical bounce that killed
  edge3 → use `oracle_px`.
- **Resolution:** both are right about their own risk. Price on **`mid_px`** (sees the overshoot; not
  EMA-smoothed like `mark_px`, so no relaxation artifact); neutralize the bounce by **never entering at the
  liq fill price** (entry = post-event mid) + **placebo-differencing**. `oracle_px` becomes a robustness
  channel; `mark_px` is BARRED from the return path.

## Root-cause cluster #1 — the estimand was confounded (→ reframed primary)
- **false-fade-F1 [CRITICAL]:** `forced_dir = −sign(start_position) ≈ −sign(recent move)`, so
  `forced_dir·fwd_ret` is a generic post-move reversion detector; Null A (shuffle) is blind to it and Null B
  matched magnitude not signed move. → **placebo-differenced abnormal reversion** (signed-move+vol-matched).
- **economic-F1/F2 [CRITICAL×2]:** 15 min is too slow for the sub-minute snapback (arbed / absorbed at mark
  by HLP) and too fast for the fire-sale reversal (hours–days), and the pooled mean averages fade (crowded
  flush) and follow (trending deleveraging) into ≈0. → **h\* chosen by SNR; regime split co-primary;
  unconditional pooled mean demoted to an expected-≈0 control.**
- **economic-F4 [HIGH]:** `is_liq_origin` mixes 4 mechanisms with different signs (book overshoot vs
  backstop-at-mark vs cascade vs ADL). → **primary = book-market-order tranche only.**
- **feasibility-F5 [MED]:** at day-cluster resolution MDE ~10 bp ≫ a few-bp care-about → underpowered
  unless variance-reduced. → the **placebo-differenced, dose-conditioned, coin-pooled A1′ IS the primary**,
  not a fallback (the placebo does double duty: confound control + variance reduction).

## Root-cause cluster #2 — dependence treated as independence (→ day is the unit)
- **stats-F1 [CRITICAL]:** the 4-coin sign test can't reach p<.05 (floor 0.125 at n=4) AND is
  anti-conservative (coins co-move). → **demoted to corroboration; BTC/ETH/SOL-without-HYPE replaces it.**
- **stats-F2 [CRITICAL]:** MDE on naive `√n_events` declares a blind design "powered". → **MDE from
  day-clustered SE; positive control = clustered power curve, not constant-shift.**
- **stats-F3 / leakage-F3 / false-fade-F2:** cluster/permute by (coin,day) or per-event undercounts the
  market-wide crash day. → **cluster AND permute at the DAY level; block length in TIME.**
- **stats-F4:** event-weighted pooled mean lets one mega-cascade day dominate; §1 vs §3 disagreed on the
  estimator. → **mean-of-day-means, bootstrap statfn matched; weightings reported as dominance diagnostics.**
- **stats-F5:** `StableEdge median-of-weekly-means` cited but not implemented in `research/lib/`. →
  **dropped from the frozen gate** (can add later if implemented + audited).

## Data-hygiene / correctness gates (fix in the harness + EDA)
- **leakage-F1 [CRITICAL] / feasibility-F3 [HIGH]:** interior ctx-coverage gaps (2026-05-30 partial day,
  sporadic missing minutes) → ASOF silently matches a stale price = edge3 artifact. → **max-staleness bound
  (~90 s) on every ASOF match; drop events whose [entry, entry+h) crosses a gap** (harness test).
- **leakage-F5/F6:** pin `t_decision = max(liq-fill ts)`, entry `ts > t_decision` (strict); trailing
  quantile strictly `[t−W, t)`, no self-inclusion / centered / full-sample.
- **leakage-F2 / false-fade-F5 / economic-F6:** matched-baseline covariates must be **strictly pre-event,
  lagged**, not full-sample deciles; report raw-and-matched side-by-side (over-subtraction visible).
- **feasibility-F6:** EDA must verify `liq_method`/`liq_mark_px` non-null **on `is_liq_origin` rows** (may
  sit on the counterparty row) — A3/A6 contingent.
- **feasibility-F7 / PREREG prose:** primary = **threshold-exceeding** events only (not "all liq events").

## Deployability honesty
- **feasibility-F2 / economic-F5 [HIGH]:** the `impact` spread cost proxy blows out exactly at liquidation
  minutes; using the **median** understates it. → **gross is the primary result; net is a band at median
  AND high-percentile contemporaneous spread + latency; a wide net does not over-null a clean gross.**

## Mechanism confounds to label
- **economic-F3 [HIGH]:** Oct-10-2025 / Jan-31-2026 (ADL tail days) dominate and are a different mechanism.
  → **tail-day policy: report with/without; ADL subset separate estimand.**
- **false-fade-F3 [HIGH] / economic-F7:** HYPE mid/oracle may be HL-endogenous (mechanical bounce on 1 of 4
  units); ADL/HLP-unwind rows mis-sign `forced_dir`. → **HYPE exogeneity check; ADL/HLP rows split out.**

## What the audit confirmed CLEAN (kept)
`forced_dir` from pre-fill `start_position` is causal; `liq_mark_px` is never used as a tradable price (the
edge3 trap is closed); the sign-symmetric fade/follow decision rule; no argmax-over-horizons (h\*
pre-registered); walk-forward on the fitted params; the harness plumbing is **feasible + RAM-safe** (DuckDB
ASOF, ~1.9M ctx rows, aggregate in SQL, pull only the small event table). Measuring on `oracle_px` did
genuinely defeat the naive bounce — the redesign keeps that defense via placebo-differencing on `mid_px`.
