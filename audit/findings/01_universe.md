# Audit 01 — Universe construction & survivorship  (agent: 01_universe_survivorship)

## Summary
I traced the past-only universe end to end: the offline artifacts (`past_univ.json` /
`scratch_conv/universe_k.json`), the offline consumers (`edge_sweep.py`,
`convergence_his.py`, `convergence_test.py`), and the live path (`main.py` →
`selection.py` → `scheduler.py`). The **offline** estimate is clean: it ranks per-transition
`past_univ[k]`, the artifact is demonstrably rolling (not frozen), and the consuming code
applies a strict past-only seam (`exit_t < t0` train / `t0 <= exit_t < t1` test) independent
of the universe. The real issue is a **live-vs-offline divergence**: the deployed candidate
universe is a *different, frozen, performance-filtered* pool (`long_hold_wallets.csv`, the
"~1404") built by code that is **not in the repo**, so the validated +10–20 bp/RT number does
not certify what live actually deploys, and the survivorship-killing rolling rule is not the
one running. Top severity HIGH (escalates to CRITICAL only on an in-sample misuse path).

## Findings

### F1 — Deployed live universe ≠ validated universe; default pool is the frozen performance-filtered 1404, not rolling `past_univ[k]`  [HIGH]
- **Where:** `src/babylon/follow/main.py:142` (`--candidates` default
  `data/follow/long_hold_wallets.csv`), `main.py:68-73` (`load_candidates`),
  `main.py:160` → `run_live` → `RollScheduler` (`scheduler.py:106` `roll`) which ranks the
  **same static `candidates` list at every roll T0**. Contrast the validated path:
  `scripts/edge_sweep.py:124` (`for w in univ[k]`) and `convergence_his.py:92` (`u = univ[key]`),
  which re-filter candidates to per-transition `past_univ[k]`.
- **Blast radius:** selection-power / deployed-edge ≠ validated-edge (forward run) →
  **gate-false-GO** on the in-sample misuse path (see "why it's real").
- **Failure scenario:**
  1. The validated edge (README ref +10.7/+9.6 bp; `edge_sweep`) is measured on the
     **rolling top-1500-by-cumulative-past-notional** universe, re-derived each transition.
  2. Live (`main.py`) instead loads ONE static CSV, `long_hold_wallets.csv` — 1404 wallets
     ranked by `longhold_skill_bps` with an `n_over8h`/`median_hold_min`/`top_quintile`
     schema. This is a **behaviour+performance filter**, a different membership rule than
     "top-1500 by past notional". So the deployed selection operates on a pool the offline
     study never validated. Even the `eligible_pool="broad_study_pool"` label in
     `locked_config` (main.py:59) is asserted, not derived from `past_univ`.
  3. This CSV is the "FROZEN 1404" called out in `convergence_test.py:5` as the pool that
     produced the **+159 bp/RT survivorship** number the rolling universe was built to kill.
     The live default re-adopts exactly that pool.
  4. The runner accepts a historical `t0_ms` and a local `--fills-dir`
     (`main.py:147-149`, `run_live(..., t0_ms=...)`), so the live measure→register→decide
     stack can be pointed at the **Feb–Jun in-sample window** with the default candidates.
     Because membership in the 1404 was itself selected on a performance stat over that same
     window, measuring those wallets' "forward" returns inside that window is the textbook
     survivorship false-GO.
- **Why it's real (not theoretical):** the default is wired (`main.py:142`), nothing in
  `run_live`/`roll` re-derives a past-only universe per roll, and `LIVE_FOLLOW.md:15` confirms
  v1 selection is *frozen at T0*, not rolling. For a genuine forward deploy (T0 = 2026-06-30,
  measuring July+) this is "only" a representativeness/power issue — the forward returns are
  honest and a non-persistent edge would correctly read INCONCLUSIVE. It becomes a
  false-GO **only** if the gate is run over the in-sample window with this pool; that path is
  the default-candidate path of least resistance, which is what makes it HIGH rather than MED.
- **Confidence:** high that deployed ≠ validated universe rule; medium that it can fabricate a
  GO (depends on whether any in-sample run of `measure→decide` uses these default candidates —
  that is audit-05's gate scope; flag the cross-check).
- **Fix sketch:** either (a) make the live candidate pool the rolling `past_univ[k]` re-derived
  at each T0 from past-only notional (match the validated rule), or (b) hard-refuse any
  `measure→decide` whose candidate-pool hash ≠ the validated `past_univ` hash and whose T0 is
  inside the in-sample span. At minimum, bind the candidate-file content hash into
  `universe_hash`/the `run_id` so a frozen-pool run is not mistaken for the validated one.

### F2 — Frozen pool `long_hold_wallets.csv` has no in-repo builder; its past-only construction is unverifiable  [MED]
- **Where:** `data/follow/long_hold_wallets.csv` (columns `longhold_skill_bps, n_longhold,
  n_over8h, median_hold_min, pct_over_1h, pct_over_8h, n_total, top_quintile`). No committed
  code emits these columns — grep across `src/`, `scripts/`, notebooks for
  `longhold_skill_bps|n_over8h|median_hold_min` finds only *consumers* of a pre-existing
  `top_quintile` column (`main.py:70`, `walkforward.py`, `oos.py`, `copy_backtest.py`),
  never a writer. `src/babylon/follow/skill.py:244` builds a `top_quintile` flag but with a
  different schema (`median_bps`), not this file.
- **Blast radius:** selection-power (forward); offline-estimate if this pool ever feeds an
  in-sample measurement (see F1).
- **Failure scenario:** `longhold_skill_bps` is a per-wallet performance statistic. If it was
  computed over the **full Feb–Jun window** (the likely source given the May–Jun coin set),
  then membership in the 1404 is conditioned on surviving + performing across the whole study
  span — a frozen-pool survivorship selection. There is no artifact in the repo to confirm the
  skill/long-hold filter used only past data, so the pool's leak-freeness cannot be
  established. The 281 `top_quintile=True` rows are explicitly the in-sample winners
  (`main.py:144` "survivorship-tainted; NOT default") — the default broad 1404 is the parent
  pool of those winners and shares their selection window.
- **Why it's real:** the file is a static input with no provenance in the tree; the audit
  cannot certify "past-only" for a universe whose construction it cannot read.
- **Confidence:** medium (the mismatch is certain; whether the underlying skill filter leaked
  future data is unprovable from the repo).
- **Fix sketch:** commit the builder for `long_hold_wallets.csv` and assert it ranks only on
  data strictly before each wallet's eligibility cutoff; or replace it with the validated
  `past_univ` derivation (F1 fix-a).

### F3 — Notional-ranking coin set ≠ priced coin set (universe membership partly set by unmeasured volume)  [LOW]
- **Where:** `other_repo_notes/README.txt:5` (notional excludes only majors + coins containing
  `':'`) vs `data/follow/alt_universe.txt` RULE (also excludes `'/'` spot, `'@'` spot-index,
  `'#'` builder-index) and `convergence_his.py:80-83` (`priceable &= his_coins`).
- **Blast radius:** selection-power only (which wallets enter the pool); not the gate.
- **Failure scenario:** `past_univ[k]` ranks wallets by notional that *includes* `@`/`/` coin
  volume, but returns are measured only on symbol-named perps (~73% coverage,
  `convergence_his.py:6`). A wallet that ranked into the top-1500 mostly via spot-index (`@`)
  volume contributes round-trips only from its small priced subset, so the pool is sorted on a
  denominator that differs from the measured one. This re-sorts the universe vs an
  all-priced-coins ranking. Symmetric across field and selected, so edge-over-field is not
  inflated; it only perturbs membership. Overlaps with known coverage-bias issue #9.
- **Confidence:** medium (definition mismatch is plain; magnitude unknown without recomputing
  per-coin notional shares).
- **Fix sketch:** rank `past_univ` notional on the **priceable** coin set (intersect the README
  rule with `alt_universe`) so membership and measurement share one denominator.

### F4 — Could not fully verify hypothesis-1 (off-by-one including the test month in `past_univ[k]`)  [INFO / unverified]
- **Where:** universe build (not in repo); consumed at `edge_sweep.py:113-128`,
  `convergence_his.py:85-92`.
- **What I confirmed (mitigations):**
  - `scratch_conv/universe_k.json` is **byte-equivalent in membership** to
    `other_repo_notes/past_univ.json` for all k (checked set equality per transition) — the
    artifact `edge_sweep` uses is the same one the README documents.
  - The pool **rolls** (consecutive-k membership overlap 1140/1195/1179 of 1500, i.e. ~76–80%),
    so it is demonstrably *not* a single frozen roster — the primary survivorship fix is in
    effect at the artifact level.
  - The **consuming** seam is correct and universe-independent: `edge_sweep.py:127-128` uses
    `tr = exit_t < t0` (strict) and `te = t0 <= exit_t < t1`; `ParquetFillsProvider.__call__`
    (`fills_source.py:111`) slices `[start,end)` half-open. So even if the universe were
    mis-built, the *return* measurement keeps train/test disjoint and past-only.
  - **Superset contamination (hypothesis 2) is clean:** measurement keys off `univ[k]`
    (edge_sweep, convergence), never off "is wallet in superset"; per-wallet files are read by
    the wallet's own path, so superset membership is just a storage filter, not a signal.
- **Residual risk I could NOT rule out:** whether `past_univ[k]` membership was built from
  cumulative notional over months `0..k` only, vs an off-by-one that folds in month `k+1` (the
  test month). That would select wallets on test-month activity = survivorship in membership.
  The build script is absent, so this is unconfirmable from code.
- **Confidence:** the consuming code is leak-free (high); the artifact's internal construction
  is unverified (state).
- **Probe that would settle it:** recompute `notl_full[m]` per wallet from the *small*
  per-wallet `data/follow/fills_his/<wallet>.parquet` files (taker notional, majors +`:`
  excluded), batched ≤20 wallets at a time (RAM-safe), and assert
  `past_univ[k] == top-1500 by sum(notl_full[0..k])` with no month `k+1` contribution. Do NOT
  use the banned monthly `fills_*.parquet`.

## Items checked and found clean
- Offline candidate filtering uses per-transition `past_univ[k]` (not a frozen pool) —
  `edge_sweep.py:124`, `convergence_his.py:92`.
- Train/test seam strictly past-only and disjoint — `edge_sweep.py:127-128`.
- Eligibility gate in the offline scripts (`tr count >= 2`, `te.size >= 1`,
  `edge_sweep.py:144-145`) conditions only on past (train) RT count and on having a test RT;
  the test-RT requirement applies symmetrically to field and selected, so it does not inflate
  edge-over-field (it is a disposition concern for audit 05/06, not a survivorship/future-leak).
- `universe_k.json` ≡ `past_univ.json`; pool is rolling, not frozen.
