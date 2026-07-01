# Audit 19 — Live execution / paper-fill parity  [STATIC]

> Read `audit/00_GROUND_RULES.md` first. Write findings to `audit/findings/19_execution.md`.

## Scope
The gate trusts realized PAPER fills. If the paper fill model is optimistic (fills at prices we
couldn't get, no slippage/queue, look-ahead on the book), the realized P&L feeding the gate is
inflated → false GO. Also verify backtest≡live parity so the validated path is the deployed path.

## Read
- `src/babylon/execution/paper.py`, `src/babylon/execution/fill_model.py`, `src/babylon/execution/backtest.py`, `base.py`.
- `src/babylon/follow/live.py`, `src/babylon/follow/strategy.py`.
- `tests/test_paper_parity.py`, `tests/test_fill_model.py`.

## Adversarial hypotheses to test
1. **Fill price realism.** When the paper engine fills a follow order, does it fill at the
   touch/next-trade (realistic) or at mid/the wallet's price (optimistic)? An optimistic fill is a
   direct overstatement of realized edge → straight into the gate. **Highest-value check here.**
2. **Look-ahead in the fill model.** Does the fill decision use a price/book state from at or after
   the decision instant? Even one bar of look-ahead in paper fills fabricates P&L.
3. **Slippage / partial fills / queue.** Are size, spread, and partial fills modeled, or does every
   order fill fully and instantly? On thin alts a full instant fill is fantasy.
4. **paper ≡ backtest parity (test_paper_parity).** Read the parity test — does it actually pin the
   two engines to identical fills on a non-trivial scenario, or only a degenerate one? A weak parity
   test lets live and backtest diverge silently.
5. **Cost consistency.** Does the paper fill apply the same fees/cost the offline edge was netted at
   (audit 10)? A paper engine with lower cost than the offline `--cost-bps` over-reports net edge.
6. **Lag consistency.** Does live execution enter at the same `lag` the edge was validated at
   (audit 03)? A faster paper entry than reality inflates realized edge.

## RAM
STATIC — read the parity test rather than running it; if you must, run only `tests/test_paper_parity.py`
under the DYNAMIC rules (but this task is tagged STATIC — prefer reasoning).
