# Audit 02 — Look-ahead & seam leakage in pricing  (agent: 02_lookahead_seam)

## Summary
Examined every place entry/exit prices are formed and the train/test seam is drawn:
`_close_at`, `_basket_ret_bps`, `followable_skill`/`followable_returns`, `skill.reconstruct`,
`edge_sweep.price`/`extract_positions`/`main`, and the live selection adapter
(`selection.SelectionData.returns_fn`). Pricing is strictly causal: the candle `time`
column is the candle OPEN time (confirmed in `data/candles.py:54` and
`candles_source.py:43`), and `_close_at` correctly returns the last FULLY-CLOSED candle
with no boundary look-ahead. Entry and exit use the identical causal rule, and the basket
neutralizer shares it. **One genuine but minor gap (LOW):** every seam filter keys on the
wallet's own `exit_t`, while the price is read at `exit_t + lag` — so a round-trip closing
within `lag` (≤15 min) of T0 is priced from a candle that closes *after* T0, leaking a sliver
of post-seam price into the *training/ranking* skill. Blast radius is selection-power /
mild offline-estimate optimism, **not** a gate false-GO. Otherwise a clean bill.

## Findings

### F1 — Seam guard keys on `exit_t`, but pricing reads `exit_t + lag` → ≤`lag` post-seam price leaks into training skill  [LOW]
- **Where:**
  - `src/babylon/follow/followable.py:113` (`followable_returns`, `before_ms` guard:
    `if before_ms is not None and p.exit_t >= before_ms: continue`) combined with the lagged
    price reads at `:115-116` (`_close_at(lookup, p.exit_t + lag_ms)`).
  - `scripts/edge_sweep.py:127-128` (the train/test split `tr = ... p.exit_t < t0`,
    `te = ... t0 <= p.exit_t < t1`) combined with the lagged price reads in `price()` at
    `:59-60`.
  - Same root in `selection.py:60-63` (`returns_fn` passes `before_ms=t0_ms`).
- **Blast radius:** selection-power (live `returns_fn`) and offline-estimate (edge_sweep). The
  contamination is confined to *which wallets rank top-N* on the train window; the reported
  test return arrays themselves are priced cleanly within the test window. **Not** the
  measure→decide gate, which in the live system is scored forward at real fill prices, not
  via `_close_at`.
- **Failure scenario:** Take a training round-trip with `exit_t = t0 − 5min` and the largest
  swept lag `lag = 900_000` (15 min). The exit price is `_close_at(lookup, t0 + 10min)`,
  which returns the last candle fully closed by `t0 + 10min` — a close stamped up to ~10 min
  *inside* the test window. The seam filters (`p.exit_t >= before_ms` in `followable_returns`;
  `p.exit_t < t0` in `edge_sweep`) both pass this position into TRAIN because they test the
  un-lagged `exit_t`. So the train-skill ranking (`trsk[w]` / `returns_fn`) sees a price that a
  pure pre-T0 observer could not have. If a wallet's boundary RTs happen to correlate with its
  test-window behaviour, that wallet's train rank is nudged using test-side price → marginally
  optimistic selection → marginally optimistic reported `sel` mean in `edge_sweep`.
- **Why it's real (not theoretical):** The code paths above unconditionally read
  `exit_t + lag_ms` while every seam comparison uses bare `exit_t`. There is no
  `exit_t + lag_ms <= before_ms` (or `< t0`) guard anywhere. The documented seam fix
  (known-issue #5, "count only RTs closed before T0") was implemented as `exit_t >= before_ms`,
  which is exactly off by the lag term — so this is an *incomplete* version of that fix, not a
  re-report of it. **Magnitude is small:** only RTs exiting in the ≤15-min window `[t0−lag, t0)`
  are affected (≈ `lag / train_window` ≈ 15 min / 31 d ≈ 0.03% of RTs), and each leaked price
  is only shifted to a candle ≤`lag` past T0 (sub-hour price drift), so the perturbation to a
  median/Sortino train rank is negligible. Hence LOW, not a power-killer or a false GO.
- **Confidence:** high (on the mechanism and the off-by-lag); the negligible-magnitude claim is
  medium and would be settled by a bounded probe counting, per transition, how many selected
  wallets' top-N membership flips when train RTs with `exit_t + lag >= t0` are excluded — but
  that is not worth the RAM given the 0.03% bound.
- **Fix sketch:** make the seam guard match the price clock. In `followable_returns:113` use
  `if before_ms is not None and p.exit_t + lag_ms > before_ms: continue`; in
  `edge_sweep.py:127` split train on `p.exit_t + lag < t0` (and correspondingly shift the test
  lower bound). One-line change in each, no behaviour change away from the boundary.

## What I checked and cleared (clean)
- **H1 — `_close_at` boundary (followable.py:40-50).** `i = searchsorted(times, t − _CANDLE_MS,
  "right") − 1` selects the last candle with open ≤ `t − 3.6e6`, i.e. closing at ≤ `t`. At
  `t` exactly on a candle close, the candle that closes *at* `t` is included (it is fully
  closed by `t`) and the candle *containing* `t` is excluded. No look-ahead. The `time` column
  is the OPEN time (verified: `data/candles.py:54` writes `c.open_time`; `candles_source.py:43`
  builds the lookup from `c.open_time`), so the "subtract one interval" logic is correct, not
  off-by-one. Missing/gappy candles just return an older causal close (stale, not future).
- **H2 — entry/exit symmetry (followable.py:74-75, 115-116; edge_sweep.py:59-60).** `ein` and
  `eout` call the *same* `_close_at` with `entry_t + lag_ms` / `exit_t + lag_ms`. Identical
  causal rule on both legs; no laxer exit path.
- **H4 — train/test crossover (edge_sweep.py:141-150).** `trsk[w]` is built only from `tr`
  (`price(tr,...)`) and `ter[w]` only from `te` (`price(te,...)`); selection sorts on `trsk`,
  the reported return concatenates `ter`. No train↔test array crossover. Eligibility
  (`len(tr) >= 2 and ter[w].size >= 1`, :144-145) conditions on the *existence* of test data
  (a legitimate "wallet still active" condition), not on its values.
- **H5 — basket neutralizer (skill.py:196-203).** `_basket_ret_bps` uses the same
  `searchsorted(times, t − 3.6e6, "right") − 1` at both ends over `[entry+lag, exit+lag]`, so
  the basket index is read at the same last-fully-closed grid points as the coin price — no
  candle after `exit+lag` is touched. `build_basket` (:166-193) is a cumprod indexed causally;
  `_ffill` propagates only past values; not-yet-listed coins are NaN-excluded. Clean.
- **Live gate path.** The OOS/gate measure in the live system is scored forward at real fill
  prices via the runner, not via `_close_at`; the only `_close_at`-based numbers are the offline
  edge estimate (`edge_sweep`) and the live *selection* ranking (`selection.returns_fn`). This
  bounds F1's severity below gate-false-GO.

## Not ruled out (out of scope here)
- Positions still open at the test boundary `t1` (`exit_t >= t1`) are dropped by
  `extract_positions`/`reconstruct` (open positions aren't emitted) — a right-censoring /
  disposition concern, **not** look-ahead. Flagged for the disposition/coverage auditor.
