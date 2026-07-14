# PUBLIC_BENCHMARK_SPEC — the make-or-buy comparator (Gate C)

Gate C asks whether the wallet layer adds value over a strategy that uses **only public market data** (no wallet information), implemented under **identical** conditions. The comparator is not "free" — it pays the same trigger, execution, spread, fees, capital, limits, and exits as the wallet basket.

## Matched implementation (identical to the wallet basket)

- Same coins, same evaluation months, same 5-min bar clock.
- Same **latency** (entry at the close of the first bar ≥ signal + 60 s).
- Same **cost schedule** ({8,8,10,14} bp round-trip per position).
- Same **capital rule, caps, and sizing** as `PORTFOLIO_AND_COST_RULE.md` (both equal-weight-signal and activity-weighted variants matched to the two wallet sizings).
- Same **horizon band** and exit as the basket being compared.

## Primary comparator (frozen): threshold reversal

A public reversal strategy that mirrors the population's dominant style so the comparison is fair (the wallet basket must beat the cheap version of what the wallets mostly do):

- Signal: for each coin at each bar, if the trailing 8 h coin return magnitude exceeds a threshold τ\*, emit a fade signal `−sign(trailing 8 h return)`.
- τ\* is fit **once on the first training window** (chosen so signal frequency matches the wallet basket's episode frequency per coin), then **frozen** for all evaluation folds. No per-fold tuning.
- Enter after latency, hold the fixed band horizon, pay costs, obey the same caps.

## Secondary comparator (sensitivity): market-state regression

The frozen market-state model from prior work (`E[return | signed & absolute trailing returns, realized vol, coin, time-of-day]`, fit train-only, frozen) turned into a tradable rule by taking positions in the sign of predicted return above a frozen confidence threshold. Reported as sensitivity #21, not the primary Gate-C comparator.

## Gate-C statistic

Per evaluation month, compute (basket copyability return − benchmark return) under matched implementation and sizing. Gate C passes if the month-block 95% interval of that difference excludes zero and it is positive. Report:

- basket, benchmark, and difference per month (fold-level);
- the difference's month-block CI and sign test;
- decomposition of the wallet-basket return into "shared with benchmark" vs "orthogonal to benchmark" (regress basket monthly returns on benchmark monthly returns; the intercept is the orthogonal component).

## Interpretation rule (pre-registered)

- Gate C **pass** ⇒ the wallet layer contributes return not available from the public signal; worth its implementation cost.
- Gate C **fail with Gate B pass** ⇒ the basket is profitable but the wallet layer is unnecessary — deploy the cheaper public strategy. This is a legitimate, reportable outcome, not a null of profitability.
- Gate C is reported whatever A and B do; it never alone constitutes the headline pass (A + B do).
