# Audit 19 — Live execution / paper-fill parity  (agent: 19_execution_parity)

## Summary
I read the paper/backtest/fill-model executors, the live runner + strategy wiring, the
committed `ExperimentConfig`, the measurement harness, and both execution tests. The core
paper-fill model is **realistic, not optimistic**: retail mode crosses the spread, walks real
L2 depth (VWAP), and folds taker fee + entry impact into the price; the optimistic
wallet-price ("validator") arm is hard-blocked from the live runner; the live fill path is
real-time with no look-ahead. The committed cost/lag knobs (`fee_bps=4.5`, `impact_bps=6.0`,
`max_depth_frac=0.25`, `cost_floor_bps=15`) are internally consistent.

The exposures I could not give a clean bill to are at the **edges of the executor**: (F1) the
code that turns realized paper fills into the gate's per-round-trip `top`/`control` arrays does
not exist in the repo yet — only `measure()`/`decide()`, which consume arrays — so I cannot
confirm the gate is fed by realized fill prices rather than a mid/candle-close markout; (F2) the
pre-registered headline lag (`lag_bucket_ms=60_000`) is never referenced in the live entry path,
so the realized gate operating point is the poll/tick cadence, not the pinned 60s; (F3) the
"parity" test does not actually compare the paper and backtest engines. No confirmed false-GO,
but F1 and F2 are the two places a false GO could enter, and both are currently unguarded.

## Findings

### F1 — No realized-fill→gate bridge in the repo; gate could be fed a spread-free markout  [HIGH]
- **Where:** `src/babylon/follow/measure.py:85` (`measure()` takes `top`/`control` arrays as
  inputs); no non-test caller exists (`grep "measure("`/`"Results("`/`"decide("` → only
  `tests/`). Contrast `src/babylon/follow/followable.py:115-120` (`raw = p.direction *
  (eout/ein - 1) * 1e4`, where `ein`/`eout` are candle **closes** via `_close_at`).
- **Blast radius:** gate-false-GO.
- **Failure scenario:** `measure()`/`decide()` gate on per-round-trip `top`/`control` net-bps
  arrays, but nothing in the committed code reconstructs those arrays from the live
  `PaperExecutor` realized fills. `docs/LIVE_FOLLOW.md:344` states the intent ("realized fill
  price; the round-trip measure subtracts NOTHING further"), but the bridge is unwritten. The
  obvious reuse hazard: the analysis script reuses `followable.followable_returns(...)` (the
  SELECTION ranker), which prices each leg at the lagged **candle close** mid-to-mid and pays
  **no spread, no fee, no impact**. Feeding that into the gate would overstate the realized
  net round-trip return by the full execution cost the paper executor actually charged
  (~half-spread + 4.5bp fee + 6bp impact per side ≈ 15-20bp/RT) — i.e. exactly the
  `cost_floor_bps=15` the MAR test is meant to clear. A +6bp true edge would read ~+20bp and
  clear `mar_bps=8` → false GO.
- **Why it's real (not theoretical):** the two return-computation paths coexist in the same
  package; `followable.py` is the path that already produces a `np.ndarray` of per-RT bps in
  the right shape for `measure()`, and it is mid-to-mid. The capture markout path
  (`capture/markout.py`) *does* bake spread in at the aggressing touch, but per
  `docs/LIVE_CAPTURE.md:97-98` it feeds **selection only**, not the gate. So the one path that
  is correctly priced is explicitly excluded from the gate, and the conveniently-shaped one is
  spread-free.
- **Confidence:** low (the bridge code does not exist, so I cannot show the defect is present —
  only that the guardrail is absent and the wrong reuse is easy). Settled by: the
  yet-to-be-written analysis script, or a test asserting the gate arms are computed from
  journaled `Fill.price` values (with spread/fee/impact in them), not from `_close_at` candle
  marks.
- **Fix sketch:** implement and pin (hash into `analysis_script_hash`) a reconstructor that
  builds `top`/`control` from the journaled `PaperExecutor` fill prices; add a test that a
  known fill journal yields RT returns net of the executed spread+fee+impact, and that they do
  NOT equal the candle-close `followable_returns` for the same trades.

### F2 — Pinned headline lag (60s) is never applied in the live entry path  [HIGH]
- **Where:** `src/babylon/follow/main.py:61` (`lag_bucket_ms=60_000`); the symbol appears
  **nowhere** in `runner.py` or `live.py` (`grep lag_bucket_ms src/babylon/follow/runner.py
  live.py` → no hits). Entry timing is set by `poll_interval_s=2.0` (`live.py:88`) and
  `tick_s=2.0` (`runner.run` default), and `tick()` (`runner.py:155`) fills immediately
  against the latest book.
- **Blast radius:** gate-relevant (realized edge magnitude) → potential gate-false-GO.
- **Failure scenario:** the pre-registration commits to a "single headline lag bucket" of 60s
  (`experiment.py:51` field comment; `docs/LIVE_FOLLOW.md:238` "retail: enter at mid+lag
  (60s-5min)"; `:311` pinned operating point). The live runner instead enters as soon as a
  wallet's position change is detected by the 2s poll and acted on by the 2s tick — an
  effective decision→fill lag of ~2-4s plus whatever the HL fills API latency is. Copy-edge
  decays with lag, so a top−control measured at ~2-4s can exceed the same quantity at the
  pinned 60s and clear `mar_bps=8.0` when the deployable 60s operating point would not. The
  gate is internally consistent (both arms share the live lag), but the operating point it
  certifies is not the one the team pre-registered, and the system records **no per-fill
  realized detection lag** to make the "honest follower lag" claim (`docs:100-101`) checkable
  or to gate on it.
- **Why it's real (not theoretical):** the runner has no delay/lag knob at all on the entry
  path; `tick()` fills on the first fresh tick after detection. `lag_bucket_ms` is a dead
  config field w.r.t. execution. The design philosophy "measure actual latency, don't
  minimize" (`docs:72`) would justify this ONLY if the realized lag were recorded and the
  headline quoted at it — neither is wired.
- **Confidence:** medium. The sign of the bias depends on the true API+poll detection lag,
  which I cannot measure statically; if it organically lands near 60s there is no issue. What
  would settle it: instrument the runner to record `now_wall − wallet_fill_t` per entry and
  compare its distribution to the pinned 60s.
- **Fix sketch:** either (a) record the realized entry lag per fill and quote/gate the headline
  at the achieved bucket, or (b) hold a detected signal until `wallet_fill_t + lag_bucket_ms`
  before entering, so execution matches the pinned, selection-time lag.

### F3 — `test_paper_parity.py` does not test paper≡backtest parity  [MED]
- **Where:** `tests/test_paper_parity.py` (entire file) exercises only `PaperExecutor`;
  `BacktestExecutor` is never imported or compared. Cross-engine equality rests entirely on
  both calling `fill_model.fill()` (`paper.py:100` vs `backtest.py:59`).
- **Blast radius:** reporting / parity integrity (the "live equity == backtested prior" claim,
  `paper.py:78`).
- **Failure scenario:** parity holds only when the two engines are passed equal cost params.
  They are NOT equal by default: `BacktestExecutor` defaults `slippage_bps=0`
  (`backtest.py:25`), while the committed live config sets `impact_bps=6.0` (`main.py:62`,
  flowing to `PaperExecutor` via `live.py:91`). So the live paper fill is 6bp/side worse than
  the execution backtest — the engines already diverge, and the parity test cannot see it
  because it never compares them. A future change to either fee/slippage/depth default would
  silently break parity with no failing test.
- **Why it's real (not theoretical):** the divergence is present today (6bp), in the
  conservative direction (live charges more), so it is not itself a false-GO; the defect is the
  missing guard, which permits a future optimistic divergence to slip through unflagged.
- **Confidence:** high (test content and param defaults are explicit).
- **Fix sketch:** add a test that drives `BacktestExecutor.submit` and
  `PaperExecutor.submit_book` (retail) with identical order, book, fee, slippage/impact, and
  depth params and asserts the returned `Fill.price`/size are equal; assert the live config's
  `(fee_bps, impact_bps, max_depth_frac)` match the backtest's `(taker_fee_bps, slippage_bps,
  max_depth_fraction)` used for the "prior."

### F4 — Full-fill-or-none depth cap blocks exits on thin books → frozen positions  [LOW]
- **Where:** `src/babylon/execution/fill_model.py:91` (`frac > max_depth_fraction` → no fill)
  applies to reduce-only exits too via `runner.py:211` (`submit_book` with `reduce_only`);
  `runner.py:198-203` then appends the coin to `frozen` and logs, but cannot close it.
- **Blast radius:** selection-power / disposition (audit-10 adjacent), with a mild
  fill-survivorship tilt on entries.
- **Failure scenario:** a position large relative to the visible book at exit cannot be reduced
  (the cap returns no fill, never a partial — `backtest.py` docstring §8b), so a position the
  consensus wants flat lingers to the measurement cutoff and is resolved by the MTM-at-cutoff
  disposition. If that disposition marks at mid (not crossing the spread to exit), the unclosed
  leg is valued slightly optimistically. Separately, entries that exceed the cap are skipped
  (no fill), so realized round-trips are mildly selected toward liquid coins/moments.
- **Why it's real (not theoretical):** the cap is symmetric across entry/exit and there is no
  partial-fill or forced-exit fallback; on thin alts an exit can genuinely be blocked. Severity
  is LOW because it is also realistic (you cannot dump into absent liquidity) and the
  disposition handling is owned by audit-09/10.
- **Confidence:** medium.
- **Fix sketch:** allow reduce-only exits to take a partial up to available depth (exits do not
  invent liquidity), or ensure the cutoff disposition marks unclosed legs by crossing the
  spread, not at mid.

## Clean bill (checked, holds up)
- **Fill-price realism (retail, the only live-wired arm):** `paper.py:100` →
  `fill_model.fill` walks the real L2 book for VWAP, crosses the spread (buy lifts ask / sell
  hits bid), and folds taker fee + entry impact into the price (`fill_model.py:106-107`). This
  is realistic-to-conservative, **not** mid and **not** the wallet's price.
- **Optimistic wallet-price arm is blocked live:** validator mode fills at `wallet_px ± maker`
  (`paper.py:96`) but `FollowRunner.__init__` raises `ValueError` if the executor is validator
  (`runner.py:70-73`); `main.py:54` commits `execution="retail"`. The 5% sanity band
  (`paper.py:93`) is a secondary guard. Validator cannot reach the gate.
- **No look-ahead in the live fill:** `tick()` fills against the latest received WS book
  (`runner.py:175,211`), a past snapshot; entries require book age ∈ (0, 30s]
  (`runner.py:179`). Real-time, causal.
- **Cost consistency:** committed `fee_bps=4.5` matches `fill_model.TAKER_FEE` (4.5bp);
  round-trip ask-entry + bid-exit ≈ full spread + 9bp fee + 2×6bp impact, consistent with the
  `cost_floor_bps=15` floor and `docs:238` spec.
- **Capture-vs-gate separation:** the forward capture/markout scorer feeds selection only
  (`docs/LIVE_CAPTURE.md:97-98`); its bugs are power-losses, not false-GO — consistent with the
  blast-radius model.

## Could not rule out
- Whether the (unwritten) realized-return analysis script uses fill prices vs candle marks
  (F1) — needs the script or a pinned test.
- The actual realized entry-lag distribution vs the pinned 60s (F2) — needs runtime
  instrumentation; out of scope for a static read.
