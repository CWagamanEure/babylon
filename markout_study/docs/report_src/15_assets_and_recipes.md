# 15 — Assets inventory & plotting cheatsheet (for fast report-building)

**Purpose.** A turnkey reference so whoever assembles the final report does not have to re-derive
data recipes or re-run anything heavy. Everything below is **read-only inspection** — no bar-pricing,
no tape scans. All recipes load already-aggregated `out/*.parquet` files (KB–low-MB, safe on a small
box) with `pl.read_parquet` or, at most, `pl.scan_parquet(...).select(...).collect()` on the `out/entries/`
partition (still a lightweight *derived* entries table, not the raw fill tape).

---

## FACTS — what already exists

### A. Notebook inventory (what each already computes)

| Notebook | Purpose / headline | Figures it makes (saved to) | Tables it prints | Reusable lib |
|---|---|---|---|---|
| `notebooks/markout_findings.ipynb` | Phase-1 descriptive EDA: field markout term structure, winsorization, per-wallet dispersion, optimal-exit roll-up, winner's-curse | `out/figs/01_scope.png` … `16_activity_decile.png` (16 figs, see table B) | field mean markout pivot (coin×horizon); optimal_exit summary by coin (scored/held_out/stable/median peak) | `src/eda_figs.py` (16 `fig_*` functions, `ALL` list, run `python eda_figs.py` to regen) |
| `notebooks/persistence_findings.ipynb` | Stage-A baseline OOS test: do naive top-50 rankings beat random selection forward? Verdict: **inconclusive, MDE=160bp** | `out/figs_persist/01..08_*.png` (8 figs) | primary-cell verdict (S_bps, null_p95, joint_p, spearman) per coin; positive/negative control table | `src/persistence_figs.py` (8 `fig_*`, one (`fig_null_hist`) recomputes the null and needs `mkcommon`/bars — the only "heavy" one) |
| `notebooks/persistence_refinement.ipynb` | Stage-C: can a sharper ranker (ew/vw, top-N, robust rankers, distribution) rescue persistence? Verdict: **noise-limited, coherent-but-unproven 24h/small-K lean** | `out/figs_refine/01..05_*.png` (5 figs) | ew-vs-vw grid; 24h coherence table (vw_edge K10/25/50, median, trim10); distributional mean/median vs fair-null table; graduation table | `src/refine_figs.py` (5 `fig_*`) |
| `notebooks/hold_feasibility.ipynb` | How many wallets sit in the "copyable box" (taker-opened, 1–24h hold, n≥100)? | `out/figs_hold/hold_feasibility.png` (one 2×2 panel fig) | wallet counts in box by `n_copyable`/`taker_share` threshold; hold-band totals | inline in the notebook (not a separate `_figs.py` module — see recipe below to reproduce) |
| `notebooks/report_assets.ipynb` | Consolidated report pack — re-displays tables/figures from ALL the above, organized to match the ledger | embeds existing PNGs from `out/figs*/` (does not generate new ones) | field-mean pivot; long/short@24h; top-10-by-vw_edge cohort per coin (full stat lines); persistence verdict; sweep/refine headline tables; ew/vw + 24h-coherence; distributional table | none new — pure aggregator; good template for the final report's table style (`pl.Config.set_tbl_rows/hide_dataframe_shape/tbl_width_chars`) |

There is also `out/figs_forensics/01_typology_K50.png` (from `src/forensics_figs.py`, reading
`out/forensics_typology.parquet`) — belongs to the separate cohort-forensics arc, not wired into any of
the 5 notebooks above, but directly useful for the **cohort characterization** figure family (§C below).

### B. All existing figure files (31 PNGs, none need regeneration unless data changes)

```
out/figs/            01_scope 02_coverage 03_term_structure 04_term_structure_zoom 05_winsor_effect
                      06_downside_term 07_long_short 08_edge_dist 09_size_blind_vs_deployable
                      10_n_vs_edge 11_hstar_dist 12_stable_counts 13_peak_vs_lo 14_winnerscurse
                      15_example_candidates 16_activity_decile
out/figs_persist/     01_primary_vs_null 02_pgrid 03_power 04_recovered 05_spearman 06_censoring
                      07_split_scatter 08_null_hist
out/figs_refine/      01_winnerscurse_dist 02_mean_vs_median 03_tailloss 04_ew_vw_summary
                      05_coherent_24h_positive
out/figs_forensics/   01_typology_K50
out/figs_hold/        hold_feasibility
```

No PDFs exist anywhere in the repo (figures are PNG-only, dpi 110–130).

### C. Precomputed parquet artifacts usable WITHOUT bar-pricing (data dictionary)

All under `markout_study/out/`. Sizes are all small (rows shown); safe to `pl.read_parquet` freely.

| File | Shape | Key columns | What it is |
|---|---|---|---|
| `field_by_coin_horizon.parquet` | 72×6 | coin, horizon, n, field_mean_bps, field_median_bps, field_dd_bps | THE field markout term structure (all takers, winsorized) |
| `eda_field_dir.parquet` | 60×8 | coin, horizon, field_raw_bps, field_wins_bps, long_bps, short_bps, n_long, n_short | raw vs winsorized field mean + long/short split |
| `coverage_report.parquet` | 60×6 | coin, horizon, n_total, valid_frac, winsor_cap_bps, clip_frac | pricing coverage (survivorship check) + winsor caps |
| `markout_stats.parquet` | 457,910×15 | wallet, coin, horizon, n, n_eff, volume, vw_edge_bps, net_exec_bps, exec_quality, avg_edge_bps, hit_rate, sharpe, sortino, cum_pnl_gross, coverage | per-(wallet,coin,horizon) stat line — THE per-wallet EDA/top-table source |
| `optimal_exit.parquet` | 37,947×11 | wallet, coin, n, volume, coverage, h_star, peak_net_bps, peak_net_lo, n_eff, peak_stable, beats_field | in-sample optimal exit + held-out peak + bootstrap-stability gate |
| `eda_winnerscurse.parquet` | 22,230×6 | coin, wallet, h_star, train_peak_bps, heldout_bps, heldout_net_bps | train-half peak vs held-out value — THE winner's-curse scatter source |
| `winsor_caps.parquet` | 2,544×3 | coin, horizon, cap | winsorization caps used everywhere |
| `persistence_verdict.parquet` | 75×14 | coin, metric, horizon, n_splits, S_bps, null_mean_bps, null_p95_bps, joint_p, persists, is_primary, spearman, n_both, decile_slope, persists_fdr | Stage-A OOS verdict per (coin,metric,horizon) cell |
| `persistence_splits.parquet` | 600×11 | coin, metric, horizon, test_bucket, pool, cohort_vw_bps, cohort_vw100_bps, cohort_ew0_bps, n_active, turnover, net_bps | per-split cohort detail behind the verdict (for scatter/spread figs) |
| `persistence_controls.parquet` | small | control, delta_bps, trials, detections, rate, recovered_bps | positive/negative control + MDE (power) |
| `sweep_verdict.parquet` / `sweep_global.parquet` | 756×15 / 1×6 | coin, metric, horizon, floor, stratum, S_bps, null_p95_bps, joint_p, persists_fdr / observed_beats, global_null_p95, global_p | Stage-B reliability-metric sweep + global selection-corrected null |
| `refine_grid.parquet` | 9,668×15 | coin, metric, horizon, floor, K, train, eval, stratum, pooled_S, mean_fold_S, std_fold_S, n_folds, folds_pos, n_active_tot | Stage-C full exploratory grid (9 rankers × 12h × K × train × eval) |
| `refine_dist.parquet` | 120×38 | coin, horizon, K, stratum, te_mean, te_median, rand_med_lo/hi, rand_vw_lo/hi, te_med_gt_band, vw_te_median_bps, vw_te_gt_band, te_tailloss, tr_*/te_*/field_* (mean/median/std/skew/p5/p95/tailloss/win) | full distributional dissection (train vs test vs field), the fair-null bands |
| `refine_graduation.parquet` | 2×8 | target, metric, horizon, K, train, winner_stat, config_selection_p, note | the one config-selection-corrected exit — nothing graduates |
| `hold_size_dist.parquet` | 29,334×14 | wallet, n_close_all, taker_share, n_tk_close, med_hold_h, p25/p75_hold_h, n_copyable, nb_lt15m…nb_gt72h | per-wallet hold-time distribution + copyable-box counts |
| `forensics_typology.parquet` | 180×14 | coin, K, selection, descriptor, cohort, cohort_ci_lo/hi, ctrl_lo/hi, field, control_reliable, outside_ctrl, ci_disjoint, direction | top-K cohort vs matched-control-band typology descriptors (highvol_frac, notl_cv, add_frac) |
| `cohort_K_arch.parquet` | 1,694×5 | wallet, archetype (DIRECTIONAL/TWAP/VAULT/HEDGER/MIXED), dir_style (**momentum/meanrev/na**), soft_archetype, kmeans_cluster | per-wallet behavioral archetype labels — the **fade-vs-momentum** field lives here |
| `cohort_K_archfeat.parquet` | 1,694×12 | wallet, funding_capture_bps, time_in_pos_frac, med_hold_h_train, cadence_cv, size_cv, net_long_frac, coin_hhi, add_frac, avgdown_rate, regime_tilt, n_train_dec | per-wallet behavioral feature vector (cohort-characterization inputs) |
| `cohort_K_entries.parquet` | 812,616×18 | wallet, coin, b_ts, ym, dir, notl, regime, split, raw_1h/neut_1h … raw_24h/neut_24h | per-ENTRY raw AND coin-day-**neutralized** markout at 5 horizons (1h,2h,4h,8h,24h) — the **neutralized term-structure source**, already priced, no bar access needed |
| `cohort_M_frozen.parquet` | 1,693×11 | wallet, n_elig, n_top, conv, notl_med, notl_mean, dir_bias, n_entries, n_days, n_coins, cohort | the 121-wallet "recurring" cohort flag + per-wallet descriptive stats |
| `cohort_M1_top.parquet` | 20×14 | wallet, tr/te_net_m/sd, tr/te_alpha_m/sd, shrunk_tr_alpha, topday_sh, toptok_sh | top-20 wallet detail table (train/test net & alpha) |
| `deployable_deciles.parquet` | 10×8 | decile, n_wall, n_test, raw_bp, neut_bp, neut_lag_bp, raw_lag_bp, pct_pos | decile-sorted deployable edge (raw vs neutralized vs lagged) |
| `maker_taker_split.parquet` | 5,859×29 | wallet, trN, mkshare_n/v, trF/trT_eqw/t/vw (full/taker-only train & test splits) | maker-vs-taker share and split-sample edge |

**Other artifacts that exist but belong to arcs OUTSIDE this notebook set** (consensus/order-burst,
Stage E behavioral feature test, individual/wallet-level persistence) — present, lightweight, but not
wired into any of the 5 notebooks: `consensus_master.parquet`, `consensus_placebo.parquet`,
`consensus_test_table.parquet`, `consensus_wallet_counts.parquet`, `real_exec_consensus.parquet`,
`prosecute_e_test.parquet`, `stage_e_verdict.parquet`, `individual_persistence.parquet`,
`wallet_level_persistence.parquet`, `highn_persistence.parquet`, `forensics_typology.parquet` (partly
used, see above). Available if another report section needs them; out of scope for this cheatsheet.

### D. Matplotlib conventions actually in use (and one gap to fix)

From `src/report_style.py` (newest, most polished — created today, not yet adopted everywhere) and the
per-notebook `*_figs.py` libraries:

```python
# report_style.py — the "canonical" shared style (use this for anything new)
COIN_COLORS = {"BTC": "#f7931a", "ETH": "#627eea", "SOL": "#14f195", "HYPE": "#e6007a", "ALL": "#333333"}
GROUP_COLORS = {"RECURRING": "#d62728", "ORDINARY": "#7f7f7f", "CONTROL": "#c7c7c7"}
plt.rcParams.update({
    "figure.dpi": 130, "savefig.dpi": 130, "font.size": 10.5, "font.family": "DejaVu Sans",
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.alpha": 0.25, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.titlesize": 12, "axes.titleweight": "bold", "legend.frameon": False,
    "figure.constrained_layout.use": True})
bp_axis(ax)   # signed "+12 / -8" bp tick formatter (FuncFormatter "{v:+.0f}")
```

- **Units:** everything is basis points (bps); axis labels say "(bps)" explicitly, and the signed
  `+/-` formatter (`bp_axis`) should be used on any markout/edge axis.
- **Horizon x-axis:** ALWAYS use the ladder order, never alphabetical —
  `H_LABELS = ["5m","15m","30m","1h","2h","4h","8h","12h","24h","48h","72h","168h"]` with an index
  map `HIDX = {h:i for i,h in enumerate(H_LABELS)}`; sort/pivot by `HIDX[horizon]` before plotting.
  ≥72h is right-censored (`refine_figs._grey_censor` shades it and labels "censoring" — reuse this
  helper for any new 72h/168h panel).
  Where different scripts define `HZ`/`H_LABELS` locally (`eda_figs.py`, `persistence_figs.py`,
  `refine_figs.py`, `mkcommon.py` all redefine the same 12-label list) — copy the list, don't import
  across notebook-specific modules.
- **CI whiskers:** `ax.errorbar(x, y, yerr=[pt-lo, hi-pt], fmt='o', capsize=3)` (see
  `forensics_figs.fig_typology`); a "cleared the null" point gets a gold star marker
  (`marker='*', s=90-140, color='gold', edgecolor='k'`) — reuse this ★ convention for any
  "exceeds the null" annotation, it already reads clearly across 3 notebooks.
  Fair-null bands use `ax.fill_between(x, lo, hi, color="0.82", alpha=0.7)` (see
  `refine_figs.fig_mean_vs_median`).
- **Zero line:** always `ax.axhline(0, color="k", lw=0.6-0.8)` on any signed-bps axis.
- **⚠️ GAP — coin-color inconsistency across modules** (fix before the final report so all figures
  read as one system):

  | module | BTC | ETH | SOL | HYPE | SPX |
  |---|---|---|---|---|---|
  | `report_style.py` (canonical, unused yet) | `#f7931a` | `#627eea` | `#14f195` | `#e6007a` | — |
  | `eda_figs.py` | `#F7931A` | `#627EEA` | `#14F195` | `#2EC4B6` | `#111111` |
  | `persistence_figs.py` / `refine_figs.py` | `#f7931a` | `#627eea` | `#9945ff` | `#00b4a0` | `#e23` |

  BTC/ETH agree everywhere (exchange-brand colors); **SOL and HYPE differ across all three**, and SPX
  is undefined in `report_style.py`. For the final report, standardize on one dict (recommend
  `report_style.COIN_COLORS`, extended with SOL `#14f195` and SPX `#111111`) and re-render any figure
  that mixes coins from more than one module side by side.

---

## FIGURES-TO-MAKE — master list with exact data recipes (no bar-pricing)

Every recipe below is `pl.read_parquet(...)` + light polars/numpy — nothing calls `mkcommon._load_bars`,
`markout_ret`, or touches `scratch_conv/mlscreen` bars, and nothing scans the raw fill tape (`cand2`).

### 1. Raw markout term-structure (per coin, all horizons)
Already built — reuse, don't recompute: `out/figs/03_term_structure.png` / `04_term_structure_zoom.png`
(`src/eda_figs.py:fig_term_structure`, `fig_term_structure_zoom`).
```python
import polars as pl
H = ["5m","15m","30m","1h","2h","4h","8h","12h","24h","48h","72h","168h"]
f = pl.read_parquet("out/field_by_coin_horizon.parquet")
piv = (f.filter(pl.col("coin").is_in(["BTC","ETH","SOL","HYPE","SPX"]))
        .with_columns(o=pl.col("horizon").replace_strict({h:i for i,h in enumerate(H)}))
        .sort("coin","o")
        .pivot(values="field_mean_bps", index="coin", on="horizon")
        .select(["coin"]+[h for h in H]))
# plot: one line per coin, x = H index, y = field_mean_bps; axhline(0); legend
```
Downside-risk companion (`06_downside_term.png`) uses the same pivot on `field_dd_bps`.
Long/short split (`07_long_short.png`) uses `out/eda_field_dir.parquet` (`long_bps`/`short_bps` per coin×horizon).

### 2. NEUTRALIZED markout term-structure (coin-day-neutralized, per coin)
Not yet plotted anywhere as a term-structure line chart (exists only as scalar deciles/cell means) —
build from `cohort_K_entries.parquet`, which already carries **both** `raw_Xh` and `neut_Xh` per entry
for horizons {1h,2h,4h,8h,24h} (no 12h/48h/72h/168h — that's the ceiling of this artifact):
```python
import polars as pl
d = pl.read_parquet("out/cohort_K_entries.parquet")
HN = ["1h","2h","4h","8h","24h"]
rows = []
for h in HN:
    g = d.group_by("coin").agg(
        raw=pl.col(f"raw_{h}").mean()*1e4, neut=pl.col(f"neut_{h}").mean()*1e4, n=pl.len())
    rows.append(g.with_columns(horizon=pl.lit(h)))
term = pl.concat(rows)
# two-panel: left = raw mean bps by coin x horizon, right = neut mean bps (same x-axis order as HN)
# NOTE: raw_Xh/neut_Xh are already fractional returns (x1e4 -> bps) per cohort_K_entries build script
```
Sanity check the units by comparing `raw_24h` mean against `field_by_coin_horizon`'s 24h row per coin
before trusting scale (the `cohort_K_entries` cohort is a filtered/TRAIN+TEST-split subset, not the
full field — expect a similar sign/magnitude, not an identical number).
**Deployability decile version** (already built, no recompute): `out/deployable_deciles.parquet` —
`decile, raw_bp, neut_bp, neut_lag_bp, raw_lag_bp, pct_pos` — a ready-made bar/line chart of edge by
decile, raw vs neutralized vs lag-neutralized, no further computation needed.

### 3. EDA distributions (per-wallet edge histograms, size-blind vs deployable, evidence vs edge)
Already built — reuse: `08_edge_dist.png`, `09_size_blind_vs_deployable.png`, `10_n_vs_edge.png`,
`16_activity_decile.png` (`src/eda_figs.py`). Recipe pattern (edge histogram, any coin/horizon):
```python
s = pl.read_parquet("out/markout_stats.parquet").filter(
    (pl.col("coin")=="BTC") & (pl.col("horizon")=="24h"))
v = s["vw_edge_bps"].drop_nulls().to_numpy()
v = v[np.abs(v) < np.nanpercentile(np.abs(v), 99)]   # display-only trim, never trims the reported stat
# plt.hist(v, bins=60, density=True); axvline(0)
```
Size-blind-vs-deployable scatter = `avg_edge_bps` (x) vs `vw_edge_bps` (y) from the same filtered frame,
with a `y=x` reference line and a shared symmetric limit at the 99th percentile of `|value|`.

### 4. Top-wallet tables (per coin, in-sample — MUST be labeled in-sample/winner's-curse-prone)
Exact recipe from `report_assets.ipynb` §2 (already produces the numbers, just needs table/markdown
formatting for the report):
```python
ms = pl.read_parquet("out/markout_stats.parquet")
cohort = (ms.filter((pl.col("horizon")=="24h") & pl.col("coin").is_in(MAJORS) & (pl.col("n")>=30))
            .sort("vw_edge_bps", descending=True).group_by("coin", maintain_order=True).head(10))
# columns to show: wallet (truncate to 10 chars + "…"), n, vw_edge_bps, avg_edge_bps, hit_rate, sharpe, cum_pnl_gross
```
Swap `horizon`/`head(N)`/`n>=` floor as needed; the same recipe generalizes to any horizon.
**Frozen-cohort variant** (the 121-wallet "recurring" cohort, ready-made): `out/cohort_M_frozen.parquet`
(`n_elig, n_top, conv, notl_med/mean, dir_bias, n_entries, n_days, n_coins, cohort` flag) and
`out/cohort_M1_top.parquet` (top-20 detail: train/test net & alpha, shrunk alpha, top-day/top-token share).

### 5. OOS scatter (winner's-curse: in-sample peak vs held-out)
Already built — reuse: `14_winnerscurse.png` (`src/eda_figs.py:fig_winnerscurse`).
```python
w = pl.read_parquet("out/eda_winnerscurse.parquet")   # coin, wallet, h_star, train_peak_bps, heldout_bps, heldout_net_bps
x, y = w["train_peak_bps"].to_numpy(), w["heldout_bps"].to_numpy()
# scatter x vs y, y=x reference line, PLUS a binned-mean overlay (regression-to-mean is the whole point):
bins = np.linspace(*np.nanpercentile(x[np.isfinite(x)], [1,99]), 12)
idx = np.digitize(x, bins)
bx = [x[idx==i].mean() for i in range(1,len(bins)) if (idx==i).sum()>=50]
by = [y[idx==i].mean() for i in range(1,len(bins)) if (idx==i).sum()>=50]
```
**OOS persistence scatter** (cohort edge vs random-selection null, the OTHER "OOS scatter" reading):
`out/persistence_verdict.parquet` (`S_bps` vs `null_p95_bps` per coin) — bar-pair chart, reuse
`src/persistence_figs.py:fig_primary_vs_null`; per-split spread version = `fig_split_scatter` reading
`out/persistence_splits.parquet`.

### 6. Fade/reversal bars
Two SAFE, already-available sources (no bar-pricing needed):
- **Directional asymmetry (long vs short field markout):** `out/eda_field_dir.parquet`
  (`long_bps`, `short_bps` per coin×horizon) — already plotted as `07_long_short.png`.
- **Per-wallet dir_style classification (momentum vs mean-reversion):** `out/cohort_K_arch.parquet`
  (`dir_style` ∈ {momentum, meanrev, na}) — NOT yet plotted anywhere; trivial bar chart:
  ```python
  a = pl.read_parquet("out/cohort_K_arch.parquet")
  a["dir_style"].value_counts()   # momentum=264, meanrev=265, na=1165 (of 1,694 classified wallets)
  ```
  Pair with `out/cohort_K_archfeat.parquet`'s `avgdown_rate`/`regime_tilt` for a richer 2-axis
  fade-strength cut if the report wants more than a headcount bar.

  **⚠️ GAP:** the report's actual headline fade/reversal claim (`docs/report_src/12_fade_reversal.md`:
  "the wallets' entire gross edge is captured by a costless mechanical fade priced at their own
  entry/exit times," the F0–F2 tables with CIs) is **NOT backed by any saved parquet** — it comes from
  `src/cohort_M2_deploy.py` / `cohort_M3_trigger.py` / `cohort_M4_residual.py` / `cohort_P1_behavioral.py`,
  all of which call `mkcommon._load_bars()` (loads the full bar tape — forbidden under the RAM rule for
  this task) and none of which write a `.parquet` output (`grep to_parquet` on those 4 files returns
  nothing). **To visualize those specific numbers, transcribe the point-estimate+CI tables already
  computed and recorded in the ledger/report_src text into a simple forest-plot (`errorbar`, one row per
  quantity) — do NOT re-run those scripts to regenerate figures.**

### 7. Cohort characterization
Already built — reuse: `out/figs_forensics/01_typology_K50.png` (`src/forensics_figs.py:fig_typology`,
reads `out/forensics_typology.parquet`: cohort vs activity/notional-matched control band, vw vs ew
selection, ★ = CI disjoint from control).
Additional safe sources for a fuller characterization panel:
```python
arch = pl.read_parquet("out/cohort_K_arch.parquet")       # archetype, dir_style, soft_archetype, kmeans_cluster
feat = pl.read_parquet("out/cohort_K_archfeat.parquet")   # funding_capture_bps, time_in_pos_frac, cadence_cv,
                                                            # size_cv, net_long_frac, coin_hhi, add_frac, ...
frozen = pl.read_parquet("out/cohort_M_frozen.parquet")   # the 121-wallet recurring cohort + descriptive stats
j = arch.join(feat, on="wallet").join(frozen.select("wallet","cohort"), on="wallet", how="left")
# archetype counts: DIRECTIONAL=587, TWAP=151, VAULT=17, HEDGER=19, MIXED=920 (n=1,694)
# group_by("cohort").agg(mean of each archfeat column) -> recurring vs ordinary comparison table/bars
```
**⚠️ GAP:** the richer "entry-state" behavioral decomposition (trailing-move size, signed-fade,
distance-below-24h-high, acceleration — `docs/report_src/14_cohort_characterization.md` §A) again comes
from `src/cohort_P1_behavioral.py`, which needs `_load_bars()`. Same rule as above: transcribe the
ledger's numbers into a table/bar chart rather than recomputing.

### 8. Hold-time feasibility (bonus family already covered by its own notebook)
`out/hold_size_dist.parquet` (see data dictionary above) → the 2×2 panel already built in
`notebooks/hold_feasibility.ipynb` (not a separate `_figs.py` — the plotting code is inline in the
notebook's one cell, ~40 lines, fully reusable by copy-paste: log-scale scatter of `n_copyable` vs
`med_hold_h` colored by `taker_share`, hold-dispersion (IQR vs median) scatter, histogram of
`n_copyable`, bar chart of pooled hold-band totals).

---

## GAPS

1. **Coin-color palette is inconsistent across the three `*_figs.py` modules** (SOL and HYPE each have
   2–3 different hex values; SPX undefined in the newest `report_style.py`). Fix before final rendering
   — pick one dict, referenced in §D above.
2. **`report_style.py` is unused so far** — it was created today (most recent file in `src/`, timestamp
   ahead of everything else) but no notebook or `_figs.py` module imports it yet. Decide whether to
   retrofit existing figures to it or treat it as the forward-only standard for new figures.
3. **The fade/reversal and cohort-characterization NARRATIVE numbers (report_src §12, §14) have no
   parquet backing** — they live only in `docs/FINDINGS_LEDGER.md` prose and the report_src markdown
   tables. Reproducing them requires `mkcommon._load_bars()` (full bar tape in RAM), which this task's
   RAM rule forbids. Treat those specific tables as **transcribe-only** for the report (hand-build a
   forest-plot from the already-published point estimates + CIs); do not attempt to regenerate the
   underlying figures from source in a memory-constrained pass.
4. **`hold_feasibility.ipynb` has no standalone `_figs.py` module** (unlike the other 4 notebooks) — the
   plotting code lives inline in one notebook cell. If the report needs a modified/re-styled version of
   that panel, copy the cell code (recipe §8 above) into a new small script rather than editing the
   notebook in place.
5. **`cohort_K_entries.parquet`'s neutralized term structure only covers 5 of the 12 horizons**
   (1h,2h,4h,8h,24h — no 5m/15m/30m/12h/48h/72h/168h). A neut-vs-raw comparison figure is limited to
   that subset; don't try to extend the ladder without recomputing (which needs the entries+bars
   pipeline, not just this parquet).
6. **Several precomputed parquet artifacts exist outside the 5-notebook scope** (consensus/order-burst
   arc, Stage-E behavioral test, individual/wallet-level persistence — listed at the end of §C) and were
   not evaluated in depth here since they're not part of this task's assigned notebooks; flag for
   whoever owns those report sections to inventory separately.
