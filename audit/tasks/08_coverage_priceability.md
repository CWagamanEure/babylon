# Audit 08 — Coverage / priceability bias  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/08_coverage.md`.

## Scope
Only ~73% of volume is priceable (symbol perps have candles; `@N` coins don't). Dropping the
unpriceable tail is non-random — it can bias the edge if the dropped trades differ systematically.

## Read
- `src/babylon/follow/followable.py` — `load_price_lookups`, the `c not in lookups` skip.
- `src/babylon/follow/candles_source.py`.
- `scripts/edge_sweep.py` `extract_positions` (`if c not in coins or c not in lookups: continue`).
- Known #9 (coverage bias; compare on matched tradeable subset).

## Adversarial hypotheses to test
1. **Is the drop applied identically to field and selected?** Both the universe-ranking notional
   and the RT pricing must restrict to the SAME priceable coin set. If ranking uses all coins'
   notional but pricing uses only priceable coins, the top wallets are chosen on activity we can't
   actually price → selection/measurement mismatch.
2. **Is the unpriceable tail correlated with edge?** `@N` (index/spot) coins may be where the
   sharpest or the worst trades live. Dropping them silently changes the population. Can you bound
   the direction? (e.g. if alts we can't price are the high-edge ones, we *understate*; if they're
   the toxic ones, we *overstate*.)
3. **Coin-set consistency live vs offline.** Does the live system trade exactly the priceable set
   the offline edge was measured on? A coin tradeable live but unpriceable offline (or vice versa)
   is an unvalidated exposure.
4. **`min_hold_ms` filter coverage.** `extract_positions` drops RTs with `hold_ms < min_hold_ms`
   (default 1h). Is this hold filter applied consistently, and does it drop a non-random slice
   (scalpers) that changes the edge? Confirm it's part of the validated operating point, not ad hoc.
5. **Majors exclusion.** Universe excludes BTC/ETH/SOL/HYPE. Confirm pricing/measurement exclude
   them too — a leak where majors sneak into one side biases the index and the edge.

## RAM
STATIC — candles dir is small if you must list coverage, but prefer reasoning.
