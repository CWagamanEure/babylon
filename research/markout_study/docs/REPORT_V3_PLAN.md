# Report v3 — pre-build plan (produced before regenerating figures/PDF)

## 1. Figure plan

### Main body (Part I — aggregate markouts)
| # | Figure | Source data | New? |
|---|---|---|---|
| 1 | Signed price response around taker entries (event study, −8h→+24h, per coin, day-block CI) | bars + cohort_K_entries | **new compute** |
| 2 | Mean post-entry markout by coin × horizon (heatmap, bp in cell, CI-excludes-zero mark) | cohort_K_entries + termstructure_ci.json | new (light) |
| 3 | Markout term structure by entry direction (long vs short, small multiples by coin) | cohort_K_entries | new (light) |
| 4 | Subsequent 8h markout conditional on the pre-entry move (per coin) | entry_features (new) | **new compute** |
| 5 | Markout by entry notional bucket (equal- vs notional-weighted, 1h & 8h) | cohort_K_entries | new (light) |

### Main body (Part II — informed-wallet experiment)
| # | Figure | Source | New? |
|---|---|---|---|
| 6 | Monthly mean 8h markout by coin (month × coin heatmap) | cohort_K_entries | new (light) |
| 7 | Static wallet-rank persistence (training-decile plot + train/validation scatter) | cohort_K_entries | reuse v2 f3 |
| 8 | Rolling rank persistence by horizon + gross/net/benchmark-adjusted returns | cohort_M2_recurrence, cohort_M2_deploy | reuse v2 f4+f5 |
| 9 | Market conditions at recurring-wallet entries (small multiples) | cohort_P1_behavioral | reuse v2 f8 |

### Appendix
Universe funnel; raw-vs-neutralized term structure; distribution interval plot / quantile tables; per-wallet contrarian-share ECDF; returns under wallet-direction and fade rules (A/B/C/D); residual after conditioning on market state; markout by realized-volatility quintile and time-of-day; regime composition; hold-time distribution; monthly volume; top training-decile wallet table; corrections table.

## 2. Required data fields — availability

| Field needed | Exists? | Source |
|---|---|---|
| Entry timestamp, coin, direction, notional | yes | cohort_K_entries (`b_ts`, `coin`, `dir`, `notl`) |
| Post-fill markout 1/2/4/8/24h (raw, neutralized) | yes | cohort_K_entries (`raw_*`, `neut_*`) |
| Bar closes (5-min) for event study + trailing move + vol | yes | `mkcommon._load_bars()` |
| Trailing 1h/4h/8h signed return, absolute move, realized vol | derivable | new pass `pi_compute.py` |
| Trade size buckets | yes | `notl` |
| Time-of-day, month, BTC regime | yes | `b_ts`, `ym`, `regime` |
| Round-trip hold time, taker share | yes | `out/hold_size_dist.parquet` |
| Fill VWAP vs next-bar close | partial | `out/entries/part_*` (`fill_vwap`) — conflates spread+drift, no contemporaneous mid |
| **Contemporaneous midprice / BBO / spread / depth** | **no** | not in dataset |
| **Second/minute-scale immediate markout, price impact, adverse selection vs depth** | **no** | requires BBO/trade tape |
| Funding / basis | external only | `scratch_conv/mlscreen/funding.parquet` (not used in Part I) |

## 3. Requested analyses that cannot be produced from existing data

- Full execution-quality markout: fill-to-mid implementation shortfall, immediate (seconds/minutes) markout, spread paid, price impact vs size, adverse selection vs depth. All require BBO/midprice and are unavailable with candle data. These are listed in the report as an explicit execution-analysis limitation and as the figures a future BBO-enabled study would add.
- A rigorous market-adjusted (beta-neutral) markout is feasible in principle (subtract each entry's contemporaneous BTC return over the same horizon) but is defined and deferred, not computed, to avoid adding a new estimator mid-revision; drift-neutralized markout is retained as the adjusted measure.

## 4. No-future-information verification

- Part I is descriptive; there is no wallet or parameter selection, so there is no train/validation leakage surface.
- All conditioning variables (trailing 1h/4h/8h return, absolute move, realized volatility, notional, time-of-day, regime) are measurable at or before the entry bar; only the outcome (subsequent markout) is forward.
- Event-study post-entry points are forward by construction (that is the object being described) and are never used to condition or select.
- Entry and exit prices use the first bar strictly after the timestamp (post-fill); trailing windows use bars strictly before the entry pricepoint. No point uses a price from inside its own forward window.

## 5. Dynamic vs fixed cohort separation (confirmed)

- The rolling monthly top-decile (dynamic, re-ranked each month; `cohort_M2_recurrence.py`) and the fixed 121-wallet recurring cohort (`cohort_M_freeze.py`) are reported as separate analyses.
- The +4.4 bp (4h) / +11.4 bp (8h) forward-decile figures belong only to the dynamic ranking. The fixed 121-cohort validation estimate (+10.4 bp, 8h neutralized, wallet-day-weighted) is computed independently (`verify_v2.py`). No dynamic estimate is attributed to the fixed cohort.

## 6. Constraints honored

No new wallet selectors are optimized; no strategy definitions change; headline Part II estimates are unchanged from v2. New Part I figures are descriptive summaries of the same entry table, not searches. Any new number is documented in the number-to-source map.
