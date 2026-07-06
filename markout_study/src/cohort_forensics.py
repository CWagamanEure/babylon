"""
Stage 1 (Cohort Forensics) — trader TYPOLOGY. Entry-STRUCTURE descriptors of the top cohort vs an
activity+notional-MATCHED control band + the field, at archetype/pooled level with bootstrap CIs
(cohorts are thin — no per-wallet points). COHORT_FORENSICS_ARCHITECTURE.md v2.1 §2-§3.

Descriptive, hypothesis-generating — NOT findings. Every claim is cohort-vs-matched-control with a CI
(no un-baselined statements). Cohort = top-K by vw_edge@24h; matched control removes the volume-weighted
selection artifact (vw_edge rewards active/large wallets, so an UNMATCHED control would make the cohort
look like "high-cadence whales" mechanically). Skill/luck + deployability discriminators = Stage 1b.

Uses Stage-0 columns: `pos_after` (true position), `avg_entry_px` (open-inventory COST basis — the correct
column for averaging-down), `fill_vwap` (execution basis). Output: out/forensics_typology.parquet
"""
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import MAJORS, BAR_MS, _load_bars

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
PH = "24h"; METRIC = "vw_edge_bps"; EW_METRIC = "avg_edge_bps"; FLOOR = 30
KS = [10, 50]; R_CTRL = 200; R_BOOT = 400; SEED = 12345
KBAR = 12          # preceding-1h (12×5min) return for the momentum/contrarian timing descriptor
VOLWIN = 288       # trailing-24h rolling vol window (bars) for the vol-regime descriptor
NDEC = 5           # deciles→quintiles for control matching (thin strata otherwise)
MIN_CAND = 5       # per-stratum non-cohort candidate floor for a RELIABLE matched control
POOL_FLOOR = 3     # pool must be >= POOL_FLOOR*K for a reliable control (SPX=130 fails K=50)
# NOTE: `highvol_frac` classifies each entry's vol regime vs the coin's FULL-SAMPLE median rollvol — a mild
# absolute look-ahead (does NOT bias the cohort-vs-control contrast: same threshold both sides). Descriptive.

DESCRIPTORS = ["cadence_per_day", "median_notl", "notl_cv", "long_frac", "coin_hhi",
               "add_frac", "avgdown_rate", "momentum", "highvol_frac"]


# ---------------------------------------------------------------- bar features
def entry_bar_feats(bt, cl, b_ts):
    """Per-entry preceding-KBAR return + high-vol-regime flag (close-to-close; bars are close-only)."""
    idx = np.clip(np.searchsorted(bt, b_ts, side="right") - 1, 0, bt.size - 1)   # bar at/just before entry
    prev = np.clip(idx - KBAR, 0, bt.size - 1)
    pre_ret = cl[idx] / cl[prev] - 1.0
    logret = np.zeros(cl.size); logret[1:] = np.diff(np.log(cl))
    rollvol = pl.Series(logret).rolling_std(VOLWIN, min_samples=VOLWIN // 2).to_numpy()
    med = np.nanmedian(rollvol)
    highvol = (rollvol[idx] > med).astype(np.float64)
    return pre_ret, highvol


# ---------------------------------------------------------------- descriptors
def wallet_descriptors(ent):
    """Per-(wallet,coin) entry-structure descriptors. `ent` has wallet,coin,b_ts,dir,q,notl,
    pos_after,avg_entry_px,fill_vwap,pre_ret,highvol. Returns one row per (wallet,coin)."""
    add = ent["pos_after"].abs() > ent["q"].abs() * (1.0 + 1e-6)          # position-increasing onto same side
    avgdn = add & (((ent["dir"] == 1) & (ent["fill_vwap"] < ent["avg_entry_px"])) |
                   ((ent["dir"] == -1) & (ent["fill_vwap"] > ent["avg_entry_px"])))
    mom = (ent["dir"].sign() * ent["pre_ret"].sign())                     # +1 momentum, -1 contrarian
    e = ent.with_columns(add.alias("_add"), avgdn.alias("_avgdn"), mom.alias("_mom"))
    g = e.group_by("wallet", "coin").agg(
        n=pl.len(),
        span_days=((pl.col("b_ts").max() - pl.col("b_ts").min()) / 86_400_000.0),
        median_notl=pl.col("notl").median(),
        notl_cv=(pl.col("notl").std() / pl.col("notl").mean()),
        long_frac=(pl.col("dir") == 1).mean(),
        add_frac=pl.col("_add").mean(),
        _n_add=pl.col("_add").sum(), _n_avgdn=pl.col("_avgdn").sum(),
        momentum=pl.col("_mom").mean(),
        highvol_frac=pl.col("highvol").mean(),
    )
    return g.with_columns(
        cadence_per_day=(pl.col("n") / pl.max_horizontal(pl.col("span_days"), pl.lit(1.0))),
        avgdown_rate=pl.when(pl.col("_n_add") > 0).then(pl.col("_n_avgdn") / pl.col("_n_add")).otherwise(None),
    )


def coin_hhi(ms):
    """Per-wallet Herfindahl of notional across the majors it trades (1=one-coin specialist)."""
    tot = ms.group_by("wallet").agg(vtot=pl.col("volume").sum())
    return (ms.join(tot, on="wallet")
            .with_columns(share2=(pl.col("volume") / pl.col("vtot")) ** 2)
            .group_by("wallet").agg(coin_hhi=pl.col("share2").sum()))


# ---------------------------------------------------------------- aggregation (per-coin numpy matrices)
def _nanmean_rows(D, rows):
    return np.nanmean(D[rows], axis=0) if rows.size else np.full(D.shape[1], np.nan)


def _boot_ci(D, rows, rng):
    """Bootstrap (p5,p95) of each descriptor's mean over the wallet set (resample wallets)."""
    if rows.size < 3:
        return np.full(D.shape[1], np.nan), np.full(D.shape[1], np.nan)
    bs = np.stack([_nanmean_rows(D, rows[rng.integers(0, rows.size, rows.size)]) for _ in range(R_BOOT)])
    return np.nanpercentile(bs, 5, axis=0), np.nanpercentile(bs, 95, axis=0)


def matched_control_band(D, strat, cohort_rows, rng):
    """R_CTRL control cohorts, each matched to the cohort's (n-quintile × volume-quintile) strata;
    returns (p5,p95) band per descriptor + min per-stratum candidate count (reliability). [M4] de-confounds
    the volume selection. strat aligned to D rows; candidates exclude the cohort itself."""
    cohort_set = set(cohort_rows.tolist())
    coh_strata = strat[cohort_rows]
    cand_by_s = {}
    for s in np.unique(coh_strata):
        cand_by_s[s] = np.array([r for r in np.nonzero(strat == s)[0] if r not in cohort_set])
    min_cand = int(min(cand_by_s[s].size for s in coh_strata)) if coh_strata.size else 0
    draws = []
    for _ in range(R_CTRL):
        pick = [cand_by_s[s][rng.integers(0, cand_by_s[s].size)] for s in coh_strata if cand_by_s[s].size]
        if len(pick) >= 3:
            draws.append(_nanmean_rows(D, np.array(pick)))
    if not draws:
        return np.full(D.shape[1], np.nan), np.full(D.shape[1], np.nan), min_cand
    dr = np.stack(draws)
    return np.nanpercentile(dr, 5, axis=0), np.nanpercentile(dr, 95, axis=0), min_cand


def main():
    rng = np.random.default_rng(SEED)
    ms = pl.read_parquet(OUT / "markout_stats.parquet").filter(
        (pl.col("horizon") == PH) & (pl.col("coin").is_in(MAJORS)) & (pl.col("n") >= FLOOR))
    pool_df = ms.select("wallet", "coin", "n", "volume", METRIC, EW_METRIC)
    hhi = coin_hhi(ms)
    lk = _load_bars()

    # entries for pool wallets only (semi-join), + per-entry bar features per coin
    ent = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
           .filter(pl.col("coin").is_in(MAJORS))
           .join(pool_df.lazy().select("wallet", "coin"), on=["wallet", "coin"], how="semi").collect())
    parts = []
    for coin in MAJORS:
        ec = ent.filter(pl.col("coin") == coin)
        if ec.height == 0 or lk.get(coin) is None:
            continue
        pre, hv = entry_bar_feats(lk[coin][0], lk[coin][1], ec["b_ts"].to_numpy())
        parts.append(ec.with_columns(pl.Series("pre_ret", pre), pl.Series("highvol", hv)))
    desc = wallet_descriptors(pl.concat(parts)).join(hhi, on="wallet", how="left")

    rows = []
    for coin in MAJORS:
        pc = pool_df.filter(pl.col("coin") == coin)
        if pc.height < max(KS):
            continue
        # descriptor matrix D over the whole coin pool (wallet->row map decouples D order from selection)
        dc = pc.select("wallet", "n", "volume").join(desc.filter(pl.col("coin") == coin), on="wallet", how="left")
        wl = dc["wallet"].to_numpy(); widx = {w: i for i, w in enumerate(wl)}
        D = np.column_stack([dc[d].to_numpy().astype(np.float64) for d in DESCRIPTORS])
        nn = dc["n"].to_numpy(); vv = dc["volume"].to_numpy()
        nq = np.clip(np.searchsorted(np.quantile(nn, np.linspace(0, 1, NDEC + 1)[1:-1]), nn), 0, NDEC - 1)
        vq = np.clip(np.searchsorted(np.quantile(vv, np.linspace(0, 1, NDEC + 1)[1:-1]), vv), 0, NDEC - 1)
        strat = nq * NDEC + vq
        fmean = _nanmean_rows(D, np.arange(D.shape[0]))
        for K in KS:
            for sel, met in [("vw", METRIC), ("ew", EW_METRIC)]:   # [M4] vw = primary, ew = cross-check
                top = pc.sort(met, descending=True).head(K)["wallet"].to_numpy()
                coh_rows = np.array([widx[w] for w in top])
                cmean = _nanmean_rows(D, coh_rows)
                blo, bhi = _boot_ci(D, coh_rows, rng)
                clo, chi, min_cand = matched_control_band(D, strat, coh_rows, rng)
                reliable = (D.shape[0] >= POOL_FLOOR * K) and (min_cand >= MIN_CAND)
                for j, d in enumerate(DESCRIPTORS):
                    fin = np.isfinite(cmean[j]) and np.isfinite(clo[j]) and np.isfinite(blo[j])
                    above = fin and blo[j] > chi[j]      # cohort CI entirely above control band (fair test)
                    below = fin and bhi[j] < clo[j]
                    rows.append(dict(coin=coin, K=K, selection=sel, descriptor=d, cohort=cmean[j],
                                     cohort_ci_lo=blo[j], cohort_ci_hi=bhi[j], ctrl_lo=clo[j], ctrl_hi=chi[j],
                                     field=fmean[j], control_reliable=reliable,
                                     outside_ctrl=bool(fin and (cmean[j] < clo[j] or cmean[j] > chi[j])),
                                     ci_disjoint=bool(above or below),
                                     direction="above" if above else ("below" if below else "")))
    res = pl.DataFrame(rows)
    res.write_parquet(OUT / "forensics_typology.parquet")
    rel = res.filter(pl.col("control_reliable"))
    vw = rel.filter((pl.col("selection") == "vw") & (pl.col("ci_disjoint")))
    print(f"DONE -> forensics_typology ({res.height} rows). Reliable-control cells: {rel.height}. "
          f"vw CI-disjoint (fair test): {vw.height}", flush=True)


if __name__ == "__main__":
    main()
