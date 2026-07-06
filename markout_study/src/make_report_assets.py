"""Build notebooks/report_assets.ipynb — the CONSOLIDATED report-ready pack: every table and figure for
the wallet-copyability study in one place. Tables are computed live from out/*.parquet (reproducible,
tweakable); figures are embedded from the rendered out/figs*/ PNGs. Organized by stage to mirror
docs/FINDINGS_LEDGER.md. Execute to refresh."""
from pathlib import Path
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks" / "report_assets.ipynb"
NB.parent.mkdir(exist_ok=True)
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))


md(r"""# Report Assets — all tables & figures (wallet copyability)
### `markout_study` · consolidated pack for the write-up

Every result in one place, organized to match `docs/FINDINGS_LEDGER.md`. **Tables** are computed live from
`out/*.parquet` (edit and re-run freely); **figures** are embedded from `out/figs*/`. Bottom line
(calibrated): *performance-based ranking of takers is noise-limited — nothing is individually significant OOS,
but a small directionally-coherent positive survives at ~24h / small cohorts across several independent cuts.
Inconclusive/underpowered, NOT a disproof; size-blind, not deployable. Next lever: behavioral features.*""")

code(r"""import sys; from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
import polars as pl
from IPython.display import Image, display, Markdown
pl.Config.set_tbl_rows(60); pl.Config.set_tbl_hide_dataframe_shape(True); pl.Config.set_tbl_width_chars(200)
OUT = ROOT / "out"
MAJORS = ["BTC", "ETH", "SOL", "HYPE", "SPX"]
HZ = ["5m","15m","30m","1h","2h","4h","8h","12h","24h","48h","72h","168h"]; HO = {h:i for i,h in enumerate(HZ)}
def show(p, w=1050): display(Image(str(p), width=w))
print("assets root:", OUT)""")

# ---------------- Section 1: field markout term structure ----------------
md(r"""## 1. The tape — markout term structure per coin (the field baseline)
Average signed post-fill markout (bps) at each horizon, per coin, across ALL taker entries. This is the raw
material: does the average taker fill carry a markout, and how does it evolve with holding horizon.""")

code(r"""fld = (pl.read_parquet(OUT/"field_by_coin_horizon.parquet")
       .filter(pl.col("coin").is_in(MAJORS))
       .with_columns(o=pl.col("horizon").replace_strict(HO)).sort("coin","o"))
# markout-per-horizon-per-coin: mean (bps), pivoted for the report
tbl_field = (fld.select("coin","horizon","field_mean_bps")
             .with_columns(pl.col("field_mean_bps").round(2))
             .pivot(values="field_mean_bps", index="coin", on="horizon")
             .select(["coin"]+[h for h in HZ if h in fld["horizon"].unique().to_list()]))
print("Field MEAN markout (bps) per coin × horizon:"); tbl_field""")

code(r"""# long vs short field markout + counts (directional asymmetry)
ed = pl.read_parquet(OUT/"eda_field_dir.parquet").filter(pl.col("coin").is_in(MAJORS))
(ed.filter(pl.col("horizon")=="24h")
   .select("coin", pl.col("field_wins_bps").round(2).alias("field@24h_bps"),
           pl.col("long_bps").round(2).alias("long@24h"), pl.col("short_bps").round(2).alias("short@24h"),
           "n_long","n_short").sort("coin"))""")

code(r"""show(OUT/"figs/03_term_structure.png"); show(OUT/"figs/06_downside_term.png"); show(OUT/"figs/07_long_short.png")""")

# ---------------- Section 2: top-wallet stats per coin ----------------
md(r"""## 2. Top-wallet statistics per coin (in-sample)
The top wallets by deployable edge (`vw_edge`) at the 24h horizon, per coin, with their full in-sample stat
line. **These are IN-SAMPLE (selection) numbers — inflated by the winner's curse; the out-of-sample test of
whether ranking on them persists is §3.** Floor: ≥30 entries.""")

code(r"""ms = pl.read_parquet(OUT/"markout_stats.parquet")
cohort = (ms.filter((pl.col("horizon")=="24h") & (pl.col("coin").is_in(MAJORS)) & (pl.col("n")>=30))
          .sort("vw_edge_bps", descending=True).group_by("coin", maintain_order=True).head(10))
# per-coin summary of the top-10 cohort
summary = (cohort.group_by("coin").agg(
    n_wallets=pl.len(), median_entries=pl.col("n").median(),
    vw_edge_bps=pl.col("vw_edge_bps").mean().round(1), avg_edge_bps=pl.col("avg_edge_bps").mean().round(1),
    hit_rate=pl.col("hit_rate").mean().round(3), sharpe=pl.col("sharpe").mean().round(3),
    cum_pnl_gross=pl.col("cum_pnl_gross").mean().round(0)).sort("coin"))
print("Top-10-by-vw_edge@24h cohort — mean in-sample stats per coin:"); summary""")

code(r"""# the actual top-10 wallets per coin (truncated address) — full stat line
(cohort.select("coin", (pl.col("wallet").str.slice(0,10)+"…").alias("wallet"), "n",
   pl.col("vw_edge_bps").round(1), pl.col("avg_edge_bps").round(1), pl.col("hit_rate").round(3),
   pl.col("sharpe").round(3), pl.col("cum_pnl_gross").round(0)))""")

code(r"""show(OUT/"figs/08_edge_dist.png"); show(OUT/"figs/14_winnerscurse.png"); show(OUT/"figs/09_size_blind_vs_deployable.png")""")

# ---------------- Section 3: OOS significance ----------------
md(r"""## 3. OOS significance — does ranking on those stats persist?
The core test: rank on a past window, copy top-50, score on a future window vs a random-selection null.
**Headline: no cell is individually significant; 0 survive FDR.** But point estimates lean positive on 4/5
coins, and the power floor (MDE≈160 bp/entry) means this is *underpowered*, not a disproof.""")

code(r"""# baseline persistence — primary cell (vw_edge@24h) per coin
(pl.read_parquet(OUT/"persistence_verdict.parquet").filter(pl.col("is_primary"))
 .select("coin","metric","horizon", pl.col("S_bps").round(1).alias("cohort_edge_bps"),
         pl.col("null_p95_bps").round(1).alias("null_p95"), pl.col("joint_p").round(3),
         "persists_fdr", pl.col("spearman").round(3)).sort("coin"))""")

code(r"""# power (positive control) + selection-corrected sweep/refine headlines
print("SWEEP global null (reliability metrics, config-corrected):")
display(pl.read_parquet(OUT/"sweep_global.parquet").select(
    pl.col("observed_beats"), pl.col("global_null_p95"), pl.col("global_p").round(3), "n_primary_family_cells"))
print("\nREFINE graduation (config-selection-corrected over ~8,400 cells) — nothing graduates:")
display(pl.read_parquet(OUT/"refine_graduation.parquet").select(
    "target","metric","horizon","K","train", pl.col("winner_stat").round(2),
    pl.col("config_selection_p").round(3).alias("corrected_p")))
print("\nPositive-control MDE (power to detect an injected edge):")
display(pl.read_parquet(OUT/"persistence_controls.parquet").filter(pl.col("control")=="positive")
        .select("coin","horizon", pl.col("delta_bps"), pl.col("recovered_bps").round(1), "rate").head(8))""")

code(r"""show(OUT/"figs_persist/01_primary_vs_null.png"); show(OUT/"figs_persist/03_power.png"); show(OUT/"figs_persist/05_spearman.png")""")

# ---------------- Section 4: refinement grid ----------------
md(r"""## 4. Refinement — ew/vw, top-N, robust rankers (where the coherent positive lives)
Averaged over all horizons nothing beats ~0 and ew<vw everywhere — but that averaging **dilutes the 24h lean**.
At 24h the positive is directionally coherent across orthogonal cuts (robust rankers + top-N), 4–5/5 coins.""")

code(r"""G = pl.read_parquet(OUT/"refine_grid.parquet")
d = G.filter((pl.col("K")==50)&(pl.col("train")=="expanding")&(pl.col("stratum")=="primary_family"))
print("ew vs vw, mean pooled edge over coins × non-censored horizons (K=50, expanding):")
display(d.group_by("metric","eval").agg(mean_bps=pl.col("pooled_S").mean().round(1),
    coins_h_pos=(pl.col("pooled_S")>0).sum()).sort("metric","eval"))""")

code(r"""# the 24h coherence table: vw_edge across K + robust rankers, # coins positive
h = G.filter((pl.col("horizon")=="24h")&(pl.col("train")=="expanding")&(pl.col("eval")=="vw"))
rows=[]
for m,k in [("vw_edge",10),("vw_edge",25),("vw_edge",50),("median_edge",50),("trim10_edge",50)]:
    r=h.filter((pl.col("metric")==m)&(pl.col("K")==k))
    rows.append({"cut":f"{m}·K{k}","mean_bps":round(r["pooled_S"].mean(),1),
                 "coins_positive":f'{int((r["pooled_S"]>0).sum())}/5'})
print("24h coherence — the buried underpowered positive:"); display(pl.DataFrame(rows))""")

code(r"""show(OUT/"figs_refine/04_ew_vw_summary.png"); show(OUT/"figs_refine/05_coherent_24h_positive.png")""")

# ---------------- Section 5: distributional ----------------
md(r"""## 5. Distributional / fat-tail — central vs tail, vs a fair pooled null
Is the surviving lean a central shift or a fat-tail artifact? `★`/`gt_band=1` = the cohort median clears the
one-sided fair pooled p95 null. BTC clears at 24h & 48h (central); the deployable turnover-weighted median is
inside its band for all coins (not a deployability signal).""")

code(r"""(pl.read_parquet(OUT/"refine_dist.parquet").filter((pl.col("K")==50)&(pl.col("horizon").is_in(["24h","48h"])))
 .select("coin","horizon", pl.col("te_mean").round(1), pl.col("te_median").round(1),
         pl.col("rand_med_hi").round(0).alias("null_p95"), "te_med_gt_band",
         pl.col("vw_te_median_bps").round(1).alias("deployable_vw"),
         pl.col("rand_vw_hi").round(0).alias("vw_null_p95"), "vw_te_gt_band",
         pl.col("te_tailloss").round(3)).sort("horizon","coin"))""")

code(r"""show(OUT/"figs_refine/02_mean_vs_median.png"); show(OUT/"figs_refine/01_winnerscurse_dist.png"); show(OUT/"figs_refine/03_tailloss.png")""")

md(r"""---
### Index of assets
- **Tables** (live from parquet): field markout term structure (§1); top-wallet in-sample stats per coin (§2);
  baseline OOS persistence p-values + FDR (§3); sweep & refine selection-corrected p, positive-control MDE (§3);
  ew/vw + 24h-coherence grids (§4); distributional central-vs-tail vs fair null (§5).
- **Figures**: `out/figs/` (tape/EDA), `out/figs_persist/` (OOS persistence), `out/figs_refine/` (refinement).
- Narrative + caveats per stage: `docs/FINDINGS_LEDGER.md`. Method: the per-stage architecture docs.""")

nb = nbf.v4.new_notebook(); nb.cells = cells
nb.metadata = {"kernelspec": {"name":"python3","display_name":"Python 3","language":"python"},
               "language_info": {"name":"python"}}
NB.write_text(nbf.writes(nb)); print("WROTE", NB, "|", len(cells), "cells")
