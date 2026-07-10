"""Tier-2b markout AGGREGATION — per-(wallet,coin,horizon) timing_alpha headline + CI + concordance + the
robustness fields the 11-filter screen needs. Consumes the two cutoff-independent primitives (episode raw
markout + per-minute forward returns) and applies EVERYTHING cutoff-relative here (R2/R10):

  timing_alpha_global = raw_markout − dir_sign·μ_h(coin, ≤C)          -- timing + regime/week selection
  timing_alpha_weekly = raw_markout − dir_sign·μ_h(coin, entry_week, ≤C)  -- intra-week timing FLOOR (R3)

Headline = wallet-day-weighted mean, nested day→week, with a weekly-block CLUSTER-robust SE (R1, replaces the
biased median-of-means). CI/MDE analytic from the weekly clusters; the real permutation-null + bootstrap +
whole-arc FDR run later on the SURVIVING cohort only (too heavy for 632k wallets). Leakage-safe: every μ uses
only minutes with t+h ≤ C; membership uses close_ts ≤ C; each horizon censored at entry_bar_ts+h ≤ C.

    python -m research.data.features_markout probe ETH 1h
    python -m research.data.features_markout all                 # 4 coins × primary horizons -> parquet
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .markout import _connect, HORIZONS, COINS, REPO_ROOT

MK_GLOB = str(REPO_ROOT / "data" / "derived" / "episodes_markout" / "coin={coin}" / "part-b*.parquet")
FWD_GLOB = str(REPO_ROOT / "data" / "derived" / "fwd_returns" / "coin={coin}" / "part.parquet")
OUT_DIR = REPO_ROOT / "data" / "derived" / "addr_coin_markout"
PRIMARY = ["1h", "2h", "4h", "8h"]                       # pinned primary set (R8); peak-horizon is descriptive
CUTOFF_TS = "epoch_ms(TIMESTAMP '2026-06-29 00:00:00')"  # latest expanding panel C (data ends ~2026-06-29)
ENTRY_LAG_MAX_S = 90                                     # P0 freshness: drop entries whose first tick >90s late
FEAT_MK_SCHEMA = "addr_coin_markout_v1_2026-07-08"


def _cell_sql(coin: str, hname: str) -> str:
    h = HORIZONS[hname]
    mk = MK_GLOB.format(coin=coin); fwd = FWD_GLOB.format(coin=coin)
    C = CUTOFF_TS
    return f"""
    WITH
    -- leakage-safe baselines: only minutes whose endpoint t+h <= C ({C})
    mu_g AS (SELECT avg(fwd_ret_{hname}) mug FROM read_parquet('{fwd}')
             WHERE fwd_ret_{hname} IS NOT NULL AND (ts + {h}) <= {C}),
    mu_w AS (SELECT iso_week, avg(fwd_ret_{hname}) muw FROM read_parquet('{fwd}')
             WHERE fwd_ret_{hname} IS NOT NULL AND (ts + {h}) <= {C} GROUP BY iso_week),
    ep AS (
      SELECT m.wallet, m.dir_sign, m.entry_bar_ts,
             m.entry_bar_ts // 86400000 AS day,
             strftime(make_timestamp(m.entry_bar_ts*1000), '%G%V') AS week,
             m.raw_markout_{hname} AS raw,
             m.raw_markout_{hname} - m.dir_sign*(SELECT mug FROM mu_g) AS ta_g,
             m.raw_markout_{hname} - m.dir_sign*mw.muw               AS ta_w
      FROM read_parquet('{mk}') m
      LEFT JOIN mu_w mw ON mw.iso_week = strftime(make_timestamp(m.entry_bar_ts*1000), '%G%V')
      WHERE m.raw_markout_{hname} IS NOT NULL
        AND m.close_ts <= {C} AND NOT m.entry_after_close
        AND m.entry_lag_s <= {ENTRY_LAG_MAX_S}
        AND (m.entry_bar_ts + {h}) <= {C}
    ),
    daily  AS (SELECT wallet, day, week, avg(ta_g) dm_g, avg(ta_w) dm_w, avg(raw) dm_raw FROM ep GROUP BY 1,2,3),
    weekly AS (SELECT wallet, week, avg(dm_g) wm_g, avg(dm_w) wm_w, avg(dm_raw) wm_raw FROM daily GROUP BY 1,2),
    wk AS (SELECT wallet, count(*) n_weeks,
             avg(wm_g) est_g, stddev_samp(wm_g) sd_g, avg((wm_g>0)::INT) fracw_g,
             (sum(wm_g)-max(wm_g)) exsum_g, avg(wm_w) est_w, stddev_samp(wm_w) sd_w,
             avg((wm_w>0)::INT) fracw_w, (sum(wm_w)-max(wm_w)) exsum_w, avg(wm_raw) raw_est
           FROM weekly GROUP BY 1),
    dy AS (SELECT wallet, count(*) n_days, sum(dm_g) sumd_g, max(dm_g) maxd_g FROM daily GROUP BY 1),
    epw AS (SELECT wallet, count(*) n_ep, median(ta_g) med_g, median(ta_w) med_w,
                   (min(entry_bar_ts)+max(entry_bar_ts))/2 AS mid FROM ep GROUP BY 1),
    half AS (SELECT e.wallet,
               avg(ta_g) FILTER (e.entry_bar_ts <  epw.mid) h1_g,
               avg(ta_g) FILTER (e.entry_bar_ts >= epw.mid) h2_g
             FROM ep e JOIN epw USING(wallet) GROUP BY 1)
    SELECT wk.wallet, '{coin}' AS coin, '{hname}' AS horizon,
           n_ep, n_days, n_weeks,
           round(est_g,3) est_g, round(sd_g/sqrt(n_weeks),3) se_g,
           round(est_g - 1.96*sd_g/sqrt(n_weeks),3) lb_g, fracw_g,
           round(exsum_g/nullif(n_weeks-1,0),3) exbest_g,
           round((sumd_g-maxd_g)/nullif(n_days-1,0),3) dropbest_g,
           round(med_g,3) med_g, round(h1_g,3) h1_g, round(h2_g,3) h2_g,
           round(est_w,3) est_w, round(sd_w/sqrt(n_weeks),3) se_w,
           round(est_w - 1.96*sd_w/sqrt(n_weeks),3) lb_w, fracw_w, round(med_w,3) med_w,
           round(raw_est,3) raw_est
    FROM wk JOIN dy USING(wallet) JOIN epw USING(wallet) JOIN half USING(wallet)"""


def probe(coin: str, hname: str) -> None:
    con = _connect()
    con.execute(f"CREATE TEMP TABLE r AS {_cell_sql(coin, hname)}")
    n, mug = con.execute("SELECT count(*) FROM r").fetchone()[0], None
    print(f"{coin}/{hname}: {n:,} wallet-coins")
    print("  timing_alpha_global est distribution (all wallets, bp):")
    for q, v in zip(["p10","p50","p90","mean"],
                    con.execute("SELECT quantile_cont(est_g,0.1),quantile_cont(est_g,0.5),"
                                "quantile_cont(est_g,0.9),avg(est_g) FROM r").fetchone()):
        print(f"    {q}: {v:+.2f}")
    print("  vs RAW (foil) mean:", round(con.execute("SELECT avg(raw_est) FROM r").fetchone()[0],2), "bp")
    print("  wallets with n_weeks>=6 AND est_g>0 AND lb_g>0 (powered live positive):",
          f"{con.execute('SELECT count(*) FROM r WHERE n_weeks>=6 AND est_g>0 AND lb_g>0').fetchone()[0]:,}")


def build_cell(con, coin: str, hname: str) -> int:
    out = OUT_DIR / f"coin={coin}" / f"horizon={hname}" / "part.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(f"COPY ({_cell_sql(coin, hname)}) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)")
    os.replace(tmp, out)
    return con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        probe(sys.argv[2], sys.argv[3])
    else:
        con = _connect(); t0 = time.time()
        for c in COINS:
            for hn in PRIMARY:
                tm = time.time(); n = build_cell(con, c, hn)
                print(f"  {c}/{hn}: {n:,} wallet-coins  {time.time()-tm:.0f}s", flush=True)
        (OUT_DIR / "_META.json").write_text(f'{{"schema":"{FEAT_MK_SCHEMA}","cutoff":"2026-06-29"}}')
        print(f"=== markout aggregation done {time.time()-t0:.0f}s -> {OUT_DIR} ===")
