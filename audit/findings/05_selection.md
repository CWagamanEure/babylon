# Audit 05 — Eligibility & selection gating  (agent: 05_eligibility_selection)

## Summary
I reviewed the live selection/eligibility path (`selection.py`, `scheduler.py`, `weights.py`,
`live.py`, `main.py`, `fills_source.py`) against the offline edge estimators
(`edge_sweep.py`, `convergence_his.py`, `convergence_test.py`) and the live-capture replacement
(`capture/scorer.py`, `capture/store.py`). The live candle path's eligibility is correctly on
RAW fill activity (fix #6 holds there), the tie-break is deterministic, re-ranking is NOT
endogenous to the poll cap, and winner's-curse cannot inflate the OOS gate. Two real
mismatches move a number, both **selection-power / offline-estimate** (no false-GO path):
(F1) the live `>=20 raw-fill` gate is an *extra* filter the offline edge validation never
applied and it bites the low-turnover candidate pool; (F2) the capture-path discovery
re-introduces the exact closed-round-trip-count gate that fe44463 removed. No CRITICAL/HIGH.

## Findings

### F1 — Live eligibility adds a `>=20 raw-fill` gate absent from the offline edge validation, biting the low-turnover candidate pool  [MED]
- **Where:** `src/babylon/follow/scheduler.py:70-72` (`select_roster`, the `activity_by_wallet`
  branch) with `min_positions=20` from `src/babylon/follow/main.py:60` (`locked_config`);
  vs offline `scripts/edge_sweep.py:144-145`, `scripts/convergence_test.py:79-80`,
  `scripts/convergence_his.py:108` (all gate only `train_r[w].size >= 2 and test_r[w].size >= 1`).
- **Blast radius:** offline-estimate (+ selection-power). NOT a gate-false-GO: the live gate
  reads forward fills, so it cannot fabricate an edge; it only makes the deployed roster's
  eligible pool differ from the one the +16.3bp/+9.6bp-edge-over-field claim
  (`other_repo_notes/README.txt:19-20`) was measured on.
- **Failure scenario:** Live requires BOTH `len(r) >= 2` followable round-trips AND
  `activity >= 20` raw fills in the 30-day train window. The offline estimators require ONLY
  `>= 2` train round-trips — no raw-fill floor. A wallet with, e.g., 4 qualifying
  taker/conviction/min-hold round-trips but only 8–18 total fills (a low-turnover, hold-heavy
  trader) is eligible offline and contributes to the +9.6bp edge-over-field, but is **excluded
  live** by `activity_by_wallet.get(w,0) >= 20`. The default candidate pool is
  `data/follow/long_hold_wallets.csv` (`main.py:142`) — a population *selected for low
  turnover* — so the 20-fill floor can drop a non-random, possibly large slice of the intended
  candidates, shifting the deployed roster toward higher-turnover wallets. The `select_roster`
  docstring asserts "the min then has no material effect" (`scheduler.py:64-66`); that claim is
  unverified and is most fragile for exactly this low-fill pool.
- **Why it's real (not theoretical):** The threshold value (20) is the same integer reused for
  both the disposition-free raw-activity gate and the documented `min_positions`, but a round-trip
  needs only ~2 fills, so "20 fills" is a much higher bar than "2 round-trips." The gap band
  (2–19 fills with >=2 RTs) is non-empty for hold-heavy wallets by construction. No code path
  re-includes them. Note: this is turnover selection, not disposition — the raw-fill gate is
  still disposition-free (it does not depend on which RTs *closed*), so fix #6's core claim is
  intact; the residual is a turnover/pool-composition mismatch vs the validated number.
- **Confidence:** medium. What would raise it: using the allowed pre-split per-wallet files
  (`data/follow/fills_his/<w>.parquet`, ≤20 wallets, one at a time), count per train window the
  wallets with `>=2` followable RTs but `<20` raw fills; if that fraction of the long-hold pool
  is material (say >10%), the deployed edge is being read off a different eligibility than the
  validated +9.6bp.
- **Fix sketch:** Either (a) re-run the offline sweep with the same `>=20 raw fill` gate so the
  validated number matches the deployed eligibility, or (b) gate live on raw activity scaled to
  the pool's turnover (e.g. a low single-digit fill floor) rather than reusing the `min_positions=20`
  integer, and drop the "no material effect" assertion until measured.

### F2 — Capture-path discovery re-introduces the closed-round-trip-COUNT eligibility that fe44463 removed (known #6, incompletely propagated)  [MED]
- **Where:** `src/babylon/follow/capture/scorer.py:52-54` (`CaptureScorer.active_candidates`)
  → `src/babylon/follow/capture/store.py:65-70` (`active_wallets`:
  `... GROUP BY wallet HAVING COUNT(*) >= min_n`, counting round-trips CLOSED in the train window).
- **Blast radius:** selection-power. Per `docs/LIVE_CAPTURE.md`, capture feeds *selection only*;
  and `scorer.py:11` states it is "built + tested, NOT yet wired into the live roll." So this is
  a **latent** defect that activates when CaptureScorer replaces SelectionAdapter
  (`docs/LIVE_CAPTURE.md:59`).
- **Failure scenario:** Commit fe44463 moved live eligibility from closed-RT count to raw
  activity precisely because closed-count gating is disposition-correlated (it selects
  high-turnover / fast-winner-closing wallets and shrinks the pool, known issue #6). The candle
  path was fixed (`scheduler.py:70-72`, `selection.py:65` `activity_fn`). The capture
  replacement's discovery was NOT: `active_wallets` gates on `COUNT(*)` of closed round-trips,
  the original biased statistic. When wired, the capture roster's eligible set is again
  disposition-skewed. Secondary endogeneity: the `RoundtripStore` is populated only from live
  shadow-markouts of *polled* wallets, so `active_candidates` can only ever surface wallets
  already being tracked — a new edge-holder never enters (`docs/LIVE_CAPTURE.md:82` claims
  "New edge-holders enter automatically," which the store-scoped discovery does not deliver
  unless every candidate is markedout).
- **Why it's real (not theoretical):** The SQL is unambiguous (`HAVING COUNT(*) >= min_n` over
  `roundtrips`), and there is no raw-activity equivalent in the capture store
  (`store.py` exposes only `returns` and `active_wallets`). No guard re-broadens the pool.
- **Confidence:** high (that the gate differs from the fixed live path); medium on impact
  (capture is shadow, so today it changes nothing — severity is bounded by "not yet wired").
- **Fix sketch:** Before wiring CaptureScorer, add a raw-fill / raw-activity count to the store
  (or to the markout ingest) and gate `active_candidates` on that, mirroring `selection.activity_fn`,
  and ensure markouts cover the full candidate pool (not just the roster) so discovery isn't
  endogenous.

### F3 — No empirical-Bayes shrinkage on the Sortino RANK (winner's curse) — but it cannot inflate the gate, only costs power  [LOW]
- **Where:** `src/babylon/follow/scheduler.py:78` (`ranked = sorted(eligible, key=-_sortino)`),
  same in `edge_sweep.py:149` / `convergence_*.py`. Prior audit explicitly asked for it
  (`docs/LIVE_CAPTURE.md:131` "shrink the Sortino RANK (empirical-Bayes), not just the Kelly weights").
- **Blast radius:** selection-power only. This **refutes** the task's hypothesis-3 claim that
  "selected test return is biased up by the max-pick": ranking is on TRAIN returns
  (`returns_fn(..., before_ms=t0)`), the gate measures forward/OOS realized returns, and offline
  "selected return" uses disjoint test RTs (`exit_t >= t0`, `edge_sweep.py:127-128`). Under the
  null, selecting on train noise regresses to the mean on test → top ≈ pool-mean in
  expectation, so winner's curse does NOT push `top_minus_control` above 0. It only mis-picks
  noise wallets over skilled ones, reducing power → biases the verdict toward INCONCLUSIVE,
  never a false GO.
- **Why it's real:** With few train RTs the Sortino is high-variance, so the top-quintile is
  partly noise; the Kelly weights already SNR-shrink (`weights.py:34-36`) but the *rank/membership*
  does not, so noisy wallets still take roster slots from skilled ones.
- **Confidence:** high (mechanism), and high that it is power-only given the OOS train/test split.
- **Fix sketch:** Shrink the per-wallet Sortino toward the pool mean by its sample size (James-Stein
  / EB) before `sorted(...)`, so low-n wallets need a larger raw stat to make the quintile.

## Checked and clean (no finding)
- **H1 — live eligibility uses no performance/future info:** `selection.activity_fn`
  (`selection.py:65-72`) counts raw fills in `[t0-train, t0)`; `select_roster` gates on it
  (`scheduler.py:70-72`). Disposition-free and pre-T0. Holds for the live candle path. (Capture
  path is the exception → F2.)
- **H4 — ties & determinism:** `candidates` is a CSV-ordered `list` (`main.py:68-73`), preserved
  into `RollScheduler._candidates` and the `eligible` dict (insertion order). `sorted` is stable,
  so equal-Sortino ties break by candidate order — deterministic and independent of test return.
  Re-derivable.
- **H5 — Kelly/poll-cap endogeneity:** `--max-roster=50` caps only the *live-polled* roster.
  Each re-roll calls `prepare → prefetch(candidates, ...)` over the FULL candidate pool
  (`main.py:112-118`, `live.py:106-108`), so re-ranking is not restricted to previously-rostered
  wallets. No endogenous lock-in in the candle path. (The capture path WOULD be endogenous — see F2.)
- **H6 — liveness/heartbeat gating:** Selection is computed at roll time from REST-prefetched
  train fills, not from the live poll heartbeat, so a transient live-poll outage cannot drop a
  wallet from the next roll. `prefetch` is all-or-nothing: a single wallet's REST error
  propagates out of `reroll` and is caught at `live.py:140-141` ("reroll.failed"), aborting the
  WHOLE roll — so there is no partial-pool survivorship at re-rank. Minor robustness note (not a
  bias): a persistently-failing single wallet would block every re-roll, freezing the roster at
  the prior selection.

## Could not rule out (needs the bounded probe in F1)
- The magnitude of F1 (what fraction of the long-hold candidate pool falls in the 2–19-fill /
  >=2-RT gap band). Settle with ≤20 pre-split `fills_his/<w>.parquet` files, one at a time,
  `POLARS_MAX_THREADS=2`, streaming — do NOT touch the monthly `fills_*.parquet`.
