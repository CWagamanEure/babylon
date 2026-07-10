# Study: <NAME>

> Copy this folder to start a study: `cp -r research/studies/_template research/studies/<name>`.
> Delete this quote block and fill in the rest.

**Status:** DESIGN | RUNNING | WRITE-UP | REGISTERED-NULL | LIVE-POSITIVE | DEAD-END
**Owner / date:** <you> · <YYYY-MM-DD>

## The question (one sentence)
<e.g. "Does a coin's funding rate predict its next-8h return, net of taker cost, out-of-sample?">

## Hypothesis & mechanism
Why should this edge exist? What's the economic story? What would falsify it?

## Estimand
The exact quantity being estimated (units, horizon, universe, weighting). Be specific enough that the
number is reproducible — e.g. "notional-weighted mean 8h markout in bps over BTC/ETH/SOL/HYPE,
wallet-day-clustered, OOS by month."

## Data
- Source views used from `research.data` (`fills`, `asset_ctx`, `episodes`, …).
- Any derived table this needs — is it shared (`data/derived/`) or study-private (`out/`)?
- Universe, date range, filters.

## Method
- Signal construction.
- Walk-forward scheme (`research.lib.cv.walkforward_splits`).
- Null model + multiplicity control (`research.lib.stats`).
- Cost treatment (`research.lib.cost`) — gross and net kept separate.

## The over-null gate (fill BEFORE calling any null)
- [ ] Point estimate + CI (`cluster_bootstrap_ci` / `moving_block_bootstrap_ci`)
- [ ] Positive-control MDE ≤ care-about (`power.power_check`, `inject_positive_control`)
- [ ] Cross-unit sign test (`stats.sign_test`)
- [ ] Construction-conservatism check (null band built at the right level, not against the finding)

## Files
- `run.py` — the analysis entry point (starter below).
- `FINDINGS.md` — the running ledger (update at the end of each stage).
- `out/` — study-private artifacts (parquet/json/figs).
