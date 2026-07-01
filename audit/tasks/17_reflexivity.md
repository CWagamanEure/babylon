# Audit 17 — Reflexivity / reference price  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/17_reflexivity.md`.

## Scope
We mark all wallets against the same live book our own taker flow moves → we inflate the very
incumbents we trade. Negligible at $1k, real at target notional on thin alts (the universe is
non-majors). Audit whether the markout reference is flow-independent and whether our volume share
is bounded/monitored.

## Read
- `src/babylon/follow/capture/markout.py`, BookCache, `src/babylon/follow/live.py`, `src/babylon/execution/`.
- `docs/LIVE_CAPTURE.md` must-fix #6 (reflexivity).

## Adversarial hypotheses to test
1. **Is the markout reference flow-independent?** When we mark a wallet's RT at `t+lag`, does the
   book mid at that instant already include OUR fills (we may have just entered the same coin)?
   Prior audit fix: "snapshot pre-order / net out our fills." Is any such isolation implemented, or
   does the score read the post-our-flow book → self-reinforcing selection?
2. **Volume-share bound.** Is there any monitor on our per-coin volume share? On a thin alt, our
   own entry can be the marginal price move that makes a followed wallet look good → we select it
   harder → we move it more. Unbounded, this is a feedback loop. Is it bounded/alarmed?
3. **Severity scaling.** Argue the magnitude: at the current $1k paper notional it's negligible
   (correct to defer), but document the notional at which it becomes material on the median
   universe coin's depth, so the team knows the ceiling before scaling.
4. **Selection vs gate.** Confirm reflexivity touches selection only (inflates incumbents we'd pick)
   and cannot reach the gate's realized-fill measurement. If it can, severity jumps.

## RAM
STATIC — this is largely a reasoning/architecture finding. Likely low severity at current scale;
the value is documenting the threshold, not crying wolf.
