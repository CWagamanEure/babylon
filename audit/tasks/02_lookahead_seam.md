# Audit 02 — Look-ahead & seam leakage in pricing  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/02_lookahead.md`.

## Scope
Any future information bleeding into an entry/exit price or into the train/test seam fabricates
edge. Verify the pricing is strictly causal everywhere it is computed.

## Read
- `src/babylon/follow/followable.py` — `_close_at`, `load_price_lookups`, `before_ms`, the RT pricer.
- `src/babylon/follow/skill.py` — `_positions_for`, `_basket_ret_bps`, `build_basket`.
- `scripts/edge_sweep.py` `price()` and the train/test split (`p.exit_t < t0` vs `t0 <= exit < t1`).

## Adversarial hypotheses to test
1. **`_close_at` returns the last FULLY-CLOSED candle, never the candle containing t.** Check the
   boundary: at `t` exactly equal to a candle close, does it grab the candle that closes at t
   (ok) or the one that *contains* t and hasn't closed (look-ahead)? Inspect the comparison op.
2. **Entry vs exit asymmetry.** Both `ein` and `eout` use `t+lag`. Is the *same* causal rule
   applied to both? A laxer rule on exit (e.g. allowing the in-progress candle) leaks.
3. **Train/test seam.** `edge_sweep` puts a position in train iff `exit_t < t0`. But the position
   was *priced at exit_t + lag* — if `exit_t < t0 <= exit_t+lag`, the train label uses a price
   from after T0. Does this leak the test boundary into training skill? Quantify.
4. **Skill computed on test data.** Confirm `trsk[w]` (ranking skill) is built only from `tr`
   (train) positions, and `ter[w]` (return) only from `te`. Any crossover = look-ahead selection.
5. **Basket / neutralizer look-ahead.** Does `_basket_ret_bps` over `[entry+lag, exit+lag]` use
   candles that close after exit+lag? (Hand off detail to audit 04, but flag if obvious.)

## Do NOT re-report
Known #4 (look-ahead pricing) and #5 (seam leakage) as bare facts — only flag concrete gaps.

## RAM
STATIC — pure code reasoning. Candles dir (`data/follow/candles/`, 17 MB) is cheap if you must
inspect one coin's lookup, but you should not need to load data.
