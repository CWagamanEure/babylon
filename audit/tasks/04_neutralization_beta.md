# Audit 04 — Market-neutralization & beta  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/04_beta.md`.

## Scope
Returns are de-market'd by a same-month liquid-coin index with `beta=1.245`. A wrong index,
look-ahead in the index, or a mis-estimated/over-fit beta can manufacture or destroy edge.

## Read
- `src/babylon/follow/skill.py` — `build_basket`, `_basket_ret_bps`.
- `scripts/edge_sweep.py` — `--beta 1.245`, how the basket is applied per RT.
- `scripts/convergence_his.py` / `convergence_test.py` — how beta/index was derived.

## Adversarial hypotheses to test
1. **Where does beta=1.245 come from?** Is it estimated in-sample on the same data used to
   report edge? An in-sample beta over-fits the neutralizer → can shrink or inflate the residual.
   Is it frozen, or re-estimated per transition with future data?
2. **Same-month index = look-ahead?** "Same-month liquid-coin index" — does the index for a RT
   use the *whole month's* basket return (includes future) or only causal up to exit+lag? If it
   uses same-month aggregates, the neutralizer peeks.
3. **Basket composition causality.** `build_basket` picks "liquid coins" — chosen using which
   window? If liquidity is measured over the full period, that's survivorship in the *index*.
4. **Single beta across all coins.** One beta for thin alts and liquid names is a mis-spec; a
   high-beta alt RT gets over/under-neutralized → residual contaminated. Is beta per-coin or global?
5. **Neutralized vs directional divergence.** In the sweep, when do `directional` and
   `neutralized` disagree most? A large gap that flips sign of the edge means the result is an
   artifact of the neutralizer choice, not robust edge. Flag the operating points where this bites.
6. **Does live execution neutralize the same way?** If selection is on neutralized return but the
   live book is directional (or vice versa), the deployed edge ≠ measured.

## RAM
STATIC — candles are small if you must trace one basket, but prefer reasoning.
