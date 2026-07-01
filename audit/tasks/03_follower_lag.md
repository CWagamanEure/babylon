# Audit 03 — Follower-lag pricing model  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/03_lag.md`.

## Scope
We earn the market price at `trade_time + lag`, not the wallet's own fill. The `lag` value and
how it's applied is the difference between a real and a fantasy edge. Audit the lag end to end.

## Read
- `src/babylon/follow/followable.py` (lag applied to entry & exit pricing).
- `src/babylon/follow/scheduler.py`, `src/babylon/follow/live.py` (the live detect→enter latency).
- `src/babylon/follow/capture/markout.py` (`due = event_time + lag`, the live markout lag).
- `docs/LIVE_CAPTURE.md` invariant: "`lag` == the live system's real detect→enter latency. One
  config value, shared."

## Adversarial hypotheses to test
1. **Is `lag` actually one shared value?** Find every place a lag/latency constant is defined
   (offline sweep default `--lags`, scheduler, capture, live). If the offline edge is validated
   at one lag but the live system enters at a different (larger) latency, the deployed edge is
   smaller than measured. Enumerate the values.
2. **Scalar lag vs latency distribution.** The prior audit flagged "pin `lag` to the MEASURED
   live latency p50/p75, not a scalar." Is a single scalar still used where a distribution
   matters? A right-skewed latency distribution means the mean RT decays more than the median lag
   implies (edge is convex-down in lag — check the sweep's lag sensitivity).
3. **Lag applied to the wrong clock.** `trade_time` is the wallet's fill time as we *observe* it.
   Is our detection delay (WS receipt) already baked in, so `+lag` on top double-counts or
   under-counts? Trace what timestamp `event_time` actually is.
4. **Entry/exit lag symmetry.** Both legs get `+lag`. Is that right — do we exit with the same
   latency we enter? If exit detection is faster/slower, the model is mis-specified.
5. **Lag=0 row.** The sweep includes `lag=0`. Confirm no headline number is ever quoted at lag=0
   (instantaneous = impossible follower).

## RAM
STATIC.
