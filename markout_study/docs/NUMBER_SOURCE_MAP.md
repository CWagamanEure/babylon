# Number-to-source map — report v2

Every headline estimate mapped to the script that produces it and the output it is read from.

| Estimate (report v2) | Value | Source script | Output / note |
|---|---|---|---|
| Universe entries / wallets / instruments | 7,332,013 / 32,949 / 273 | `src/build_entries.py` | `out/entries/part_*.parquet` |
| Analysis cohort wallets / entries | 1,694 / 812,616 | `src/cohort_K_define.py`, `src/cohort_K_price.py` | `out/cohort_K.txt`, `out/cohort_K_entries.parquet` |
| Cohort funnel | 29,334 → 12,544 → 1,694 | `src/cohort_K_define.py` | `out/hold_size_dist.parquet`, `out/cohort_K.txt` |
| Split counts (train/embargo/test) | 583,032 / 61,116 / 168,468 | `src/cohort_K_price.py` | `out/cohort_K_entries.parquet` (`split`) |
| Observation-unit definition | position-increasing taker decision | `src/mkcommon.py` (`taker_entries`) | — |
| Markout definition | post-fill signed price return | `src/mkcommon.py` (`markout_ret`, `price_entries`) | `raw_*` / `neut_*` columns |
| Neutralization definition | coin-month drift strip | `src/cohort_K_price.py` | `neut_*` columns |
| Term-structure means + day-block 95% CI | pooled 8h −0.60 [−5.4,+3.9], BTC 24h −6.4 [−12.9,−0.3] | `src/verify_v2.py` | `out/termstructure_ci.json` |
| HYPE 24h raw vs neut | +2.8 vs −18.6 bp | `src/fig_v2.py` | `out/cohort_K_entries.parquet` |
| Static train→validation rank correlation | ≈ +0.02 (n.s.) | `src/fig_v2.py` (f3) | `out/cohort_K_entries.parquet` |
| Winner's-curse net OOS | −28.7 bp | `src/oos_persistence.py` | `docs/FINDINGS_LEDGER.md` (Stage A / eda_winnerscurse) |
| Walk-forward best p / FDR survivors | 0.09 / 0 | (Stage A) | `docs/FINDINGS_LEDGER.md` |
| Rolling adjacent-month rank IC (4h/8h/24h) | +0.081 / +0.093 [+0.061,+0.126] / +0.085 | `src/cohort_M2_recurrence.py` | stdout / ledger Stage M2 |
| Forward-decile over field (4h / 8h) | +4.4 [+1.8,+6.8] / +11.4 [+5.3,+17.0] | `src/verify_v2.py` (recomputed both horizons) | stdout |
| Recurrence vs chance (≥2/≥3/≥4 months) | 204/184 p=0.059 · 48/35 p=0.017 · 9/5 p=0.066 | `src/cohort_M2_recurrence.py` | stdout / ledger Stage M2 |
| Recurring cohort size / threshold | 121 (≥2 of 6 train months); 28 (≥3) | `src/cohort_M_freeze.py` | `out/cohort_M_frozen.{txt,parquet}` |
| Cohort traits (conv, coins, size, dir) | 0.72 vs 0.48 · 4 vs 3 · ~$4.1k · +0.36 | `src/cohort_M_freeze.py` | `out/cohort_M_frozen.parquet` |
| Fixed-121 validation over field (8h neut, wallet-day) | +10.4 bp (n=93) | `src/verify_v2.py` | stdout |
| Behavioral medians (recurring/ordinary/control) | \|8h\| 175/151/72; signed −86/−12; dist −281/−218/−166; accel −6.2/0/−1.6; vol 23.4/21.5/14.3 | `src/cohort_P1_behavioral.py` | stdout / ledger Phase 1 |
| Per-wallet contrarian share | 83% net; 65% ≥60%; median 0.67 vs 0.52 | `src/cohort_P1b_perwallet_fade.py` | `out/cohort_P1b_perwallet.parquet`, `out/cohort_P1b.log` |
| Top-decile gross / net / benchmark-adjusted (8h) | +14.0 [+5.4,+22.8] / +7.1 / +1.0 [−10.75,+13.66] p=0.44 | `src/cohort_M2_deploy.py` | stdout / ledger Stage M2-deploy |
| A / B / C / D (net, day-capped) | +2.6 / +5.9 / −7.0 / −6.4 | `src/cohort_M3_trigger.py` | stdout / ledger Stage M3 |
| Market-state residual (per-event / day-capped) + MDE | −1.3 [−15.6,+13.0] / +5.9 [−5.5,+17.7]; MDE 11–16 bp | `src/cohort_M4_residual.py` | stdout / ledger Stage M4 |
| Nested model incremental IC | −0.0003 | `src/cohort_P2_freeze_models.py` | `out/cohort_P2_models.npz` |
| Top training-decile wallet table | see report §D | `src/fig_topwallets_oos.py` | `out/top_wallets_8h.parquet`, `out/top_wallets_8h.md` |
| Trade-size / dispersion quantiles | see appendix | `src/fig_v2.py` | `out/appendix_tables.md` |

## Part I additions (report v3)

| Estimate | Value | Source script | Output |
|---|---|---|---|
| Core markout table (mean, CI, median, hit, std, N) | see report §3 | `src/verify_v2.py` + inline | `out/termstructure_ci.json`, `out/core_markout_table.md` |
| Coin×horizon heatmap + CI-excludes-zero marks | §3 | `src/fig_v3_parti.py` | `out/termstructure_ci.json` |
| Event study, signed response −8h→+24h (per coin, day-block CI) | pre-entry +18 to +33 bp | `src/pi_compute.py` | `out/eventstudy.json` |
| Subsequent 8h markout vs signed trailing move | monotone decreasing | `src/pi_compute.py` + `src/fig_v3_parti.py` | `out/entry_features.parquet` |
| Markout by notional quintile (equal vs notional wt) | §4 | `src/fig_v3_parti.py` | `out/cohort_K_entries.parquet` |
| Monthly coin×month 8h markout | §5 | `src/fig_v3_parti.py` | `out/cohort_K_entries.parquet` |
| Distribution IQR/tails; vol-quintile; time-of-day | appendix | `src/fig_v3_parti.py` | `out/entry_features.parquet` |
| Directional hit rates (~50%) | §3 | inline | `out/core_markout_table.md` |

## v4 corrections + additions (report v4)

| Estimate | Value | Source script | Output |
|---|---|---|---|
| Effective sample (days/wallet-days/wallet-coin-days) | 334 / 179,402 / 252,223 | `src/verify_v4.py` | `out/v4.json` |
| Long/short raw vs neutralized (by coin×horizon, CI, counts) | e.g. BTC 24h raw −23.4/+17.2, neut −0.4/−3.4 | `src/verify_v4.py` | `out/v4.json` |
| Conditional training slope (subsequent 8h vs signed pre-entry move) | BTC −0.070 / ETH −0.050 / SOL −0.051 / HYPE −0.068; p(≥0) ≤ 0.03 | `src/verify_v4.py` | `out/v4.json` |
| Size within coin×month (equal & notional wt, CI, counts) | no increase with size | `src/verify_v4.py` | `out/v4.json` |
| Recurrence permutation null (≥2/≥3/≥4 mo) | 213/186 p=0.0005 · 72/35 p<0.001 · 25/5 p<0.001 | `src/verify_v4.py` | `out/v4.json` |
| Fixed-121 full validation inference | +10.5 [+5.0,+16.3] p=0.001; cost-adj +3.5; fade-adj −1.1 [−14.1,+12.0] p=0.572; 97/121 active | `src/verify_v4.py` | `out/v4.json` |
| Rolling decile-by-decile (4h/8h, CI, field) | top-minus-field +4.0@4h / +10.3@8h; monotone gradient | `src/verify_v4.py` | `out/v4.json` |
| Event-study relabelled (pre-entry sign convention) | pre-entry = earlier price vs entry in trade dir | `src/pi_compute.py` | `out/eventstudy.json` |
