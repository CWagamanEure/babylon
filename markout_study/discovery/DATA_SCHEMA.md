# DATA_SCHEMA — inputs, intermediate tables, outputs

## Inputs

- **Fill tape** (`../../scratch_conv/mlscreen/cand2_*.parquet`): wallet, coin, ts (ms), px, sz (signed), crossed (bool), plus liquidation flag if present. Majors only for primary. **API ceiling: ~11 months, cannot backfill older** — this bounds the walk-forward (see `POWER_AND_COVERAGE_AUDIT_PLAN.md`).
- **5-min bars** (`mkcommon._load_bars`): coin, bar_ts, close. No BBO/depth → no true execution markout; latency/cost are modelled assumptions.

## Intermediate tables

**episodes** (one row per episode):
`wallet, coin, dir, t0 (signal ts), build_end, n_add, avg_build_px, first_px, peak_notl, hold_est_h, crossed_frac, month, day, elig_asof_ok`

**episode_markouts** (episode × band-horizon):
`episode_id, h, gross_mk_bp, copy_mk_bp` (copy = post-latency, cost-adjusted), plus `avgbuild_mk_bp` (descriptive).

**wallet_month** (one row per wallet × cutoff-month × band):
`wallet, cutoff, band, n_episodes, active_days, active_months, shrunk_info, shrunk_copy, post_sd, eff_n_days, p_pos, coin_conc, month_conc, live_30d, elig_ok`

**selection** (per cutoff): `cutoff, band, wallet, rank, copy_score, in_basket, sizing_weight`

**benchmark** (per cutoff): frozen public strategy signals + returns under matched implementation (`PUBLIC_BENCHMARK_SPEC.md`).

## Output tables / figures

Enumerated in `EXPECTED_OUTPUTS.md`. All headline outputs are fold-level (per evaluation month) with month-block inference; entry-level pooled statistics appear only as descriptive appendices.

## Provenance / RAM discipline

8 GB box: one heavy tape pass at a time, `POLARS_MAX_THREADS ≤ 3`, batch wallets, source `ramguard.sh`. The heavy passes are: (1) episode construction from the tape, (2) episode markout pricing from bars. Everything downstream (shrinkage, ranking, basket eval, inference) is light and operates on the intermediate parquet tables. Read-only audit agents cost ~0 local RAM.

Each intermediate table is written to `discovery/out/` and each script maps to a claim in a number-to-source file, mirroring the prior study's convention.
