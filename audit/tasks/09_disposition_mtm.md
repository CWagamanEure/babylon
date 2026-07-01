# Audit 09 — Disposition / MTM-at-cutoff / dangling positions  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/09_disposition.md`.

## Scope
Closed-only scoring drops open-at-cutoff positions, which are disproportionately losers. The prior
audit measured this at **+15 bp (long-hold) up to +122 bp in the 7-day warm-up (9× true edge)** —
the single largest live-score bias. Verify the MTM-at-cutoff fix actually removes it.

## Read
- `src/babylon/follow/capture/stepper.py`, `src/babylon/follow/capture/scorer.py`.
- `src/babylon/follow/skill.py` — `_positions_for`, `_basket_ret_bps`.
- Commits 9ddf901, 11a249d ("MTM-at-cutoff disposition fix", "dangling-held-out").
- `docs/LIVE_CAPTURE.md` must-fix #2.

## Adversarial hypotheses to test
1. **Is every open position marked at the cutoff, or only some?** The fix should MTM *all*
   in-flight positions at the cutoff (or use fixed-horizon markouts). Find the Scorer query — does
   it `SELECT closed roundtrips` only, or does it also fold open_state MTM? If open positions are
   silently excluded, the bias is back.
2. **Offline vs live symmetry.** The offline sweep ("dangling-held-out") *holds out* danglers; the
   live scorer *MTMs* them. These are different estimators — held-out drops them, MTM includes a
   mark. Do they bias the same direction? If offline validates one disposition and live uses
   another, the live score isn't the validated one.
3. **MTM price source.** When marking an open position at cutoff, is the mark from the same book/
   candle source as a normal exit? A mark from a stale or favorable source re-introduces bias.
4. **Warm-up window.** The +122 bp blow-up was in the 7-day warm-up — exactly when we'd first
   trust a fresh wallet. Does the eligibility floor (min_positions) keep us out of the regime where
   open-censoring dominates, or can a wallet with 6 closed + many open RTs still rank high?
5. **Conviction / taker-open filters.** `_positions_for` filters `taker_open`, `conviction_open`.
   Does excluding non-conviction opens interact with disposition (e.g. drops the *closes* but keeps
   the *opens*, unbalancing the round-trip)? Trace a flip (open→reverse) through the stepper.

## RAM
STATIC.
