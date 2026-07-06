# Figure plan — report v4

## Main body
| Fig | Title | Section | Source | Change from v3 |
|---|---|---|---|---|
| p1_eventstudy | Price path around taker entries, aligned in trade direction | §4 | `pi_compute.py`/`eventstudy.json` | axis relabelled, sign convention corrected |
| p2_heatmap | Mean post-entry markout by coin and horizon | §3 | `termstructure_ci.json` | enlarged |
| p3_long_short | Term structure by direction — raw vs neutralized (2 rows) | §3 | `verify_v4.py` | rebuilt: adds neutralized row, enlarged |
| p4_conditional | Subsequent markout declines with the signed pre-entry move | §4 | `verify_v4.py`/`v4.json` | quantile bins, day-cluster CI, fitted training slope |
| p5_size | Markout by entry notional (quintiles within coin-month) | §4 | `verify_v4.py` | within coin-month, CI, no impact claim |
| p6_static | Static full-history ranking does not generalize | §7 | `fig_v4.py` | enlarged, decile bars + scatter |
| p6_monthly | Mean 8h markout by coin and month | §5 | `fig_v3_parti.py` | reused |
| p7_rolling_decile | Next-month markout by prior-month rank decile (4h & 8h) | §7 | `verify_v4.py`/`v4.json` | NEW — gradient vs top-only |
| p8_topdiff_month | Top-decile minus field by month | §7 | `verify_v4.py` | NEW |
| p9_behavioral | Market conditions at entry (recurring/other/control) | §8 | `fig_v4.py` | rebuilt clean grouped bars |
| f5_gross_net_bench | Gross / cost-adjusted / fade-adjusted returns | §9 | `cohort_M2_deploy.py` | reused, relabelled |

## Appendix (embedded)
a_distribution, a_regime_time, f2_raw_vs_neut, f1_termstructure, f9_fade_ecdf, f6_abcd, f7_residual — all embedded in the PDF; no local-path references remain in the body.

## Confirmation
Every main-body claim maps to a script/output in `docs/NUMBER_SOURCE_MAP.md` (v4 section) and Appendix E. Dynamic monthly decile, static full-history ranking, and fixed 121-cohort are kept as three separate objects.
