"""Timing-skill LUCK TEST — per-wallet permutation null + standardized max-statistic horizon correction + FDR.

Question: of the hygiene-clean candidate wallets, how many have entry-TIMING skill that beats chance, at which
horizon? Null (stats-audit F5): keep each wallet's actual trades, directions, and active window, but replace its
entry TIMING with random minutes drawn from that same window — destroys timing skill, preserves the wallet's
calendar footprint and directional bets. μ_week already removes week-level drift (so the null isn't crediting
static beta). Key simplification: timing_alpha_i = dir_i · TA_h(minute_i), where TA_h(m) = fwd_ret_h(m) −
μ_week_h(m) is a DIRECTION-FREE per-minute market-adjusted return. So the null just resamples minutes.

Statistic per (wallet,horizon) = simple mean of dir·TA_h over the wallet's entries (v1; the nested weighted mean
is the point estimate, this is a valid test stat). Horizon search corrected by standardizing each horizon by its
own null (z = (obs−mean_null)/std_null) then taking max over horizons vs the null max. BH-FDR over the family.

    python -m research.data.permute_timing            # B=1000 on the candidate pool
"""
from __future__ import annotations

import numpy as np
import duckdb

from .markout import HORIZONS, COINS, REPO_ROOT
from .features_markout import CUTOFF_TS, ENTRY_LAG_MAX_S

HZ = ["1h", "2h", "4h", "8h"]
B = 1000
RNG_SEED = 20260708
FDR_Q = 0.10


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute(f"SET temp_directory='{REPO_ROOT / '.tmp'}'")
    return c


def _hygiene_pool(con):
    """Hygiene-clean wallet-coins that pass the descriptive positive bar (est>0 & lb>0) at >=1 horizon, n_weeks>=6."""
    t2 = str(REPO_ROOT / "data/derived/addr_coin_features/cutoff=202606/window=expanding/coin=*/part.parquet")
    mk = str(REPO_ROOT / "data/derived/addr_coin_markout/coin=*/horizon=*/part.parquet")
    con.execute(f"""CREATE TEMP TABLE hyg AS SELECT address AS wallet, coin FROM read_parquet('{t2}', hive_partitioning=true)
      WHERE n_fills>=250 AND n_active_iso_weeks>=8 AND sum_traded_notional_usd>=1e6
        AND (n_flagged_fills::DOUBLE/nullif(n_fills,0))<0.30 AND coalesce(n_liq_fills::DOUBLE/nullif(n_fills,0),0)<0.10
        AND coalesce(top1_grossprofit_share,1)<0.30""")
    con.execute(f"""CREATE TEMP TABLE pool AS
      SELECT DISTINCT wallet, coin FROM hyg JOIN read_parquet('{mk}', hive_partitioning=true) USING(wallet,coin)
      WHERE n_weeks>=6 AND est_g>0 AND lb_g>0""")
    fam = con.execute(f"""SELECT count(*) FROM (SELECT DISTINCT wallet,coin FROM hyg JOIN
      read_parquet('{mk}', hive_partitioning=true) USING(wallet,coin) WHERE horizon='4h' AND n_weeks>=6)""").fetchone()[0]
    return fam


def _coin_grid(con, coin: str):
    """Per-minute TA_h(m) = fwd_ret_h(m) − μ_week_h(≤C, m), direction-free, one array per horizon; + ts index."""
    fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
    C = con.execute(f"SELECT {CUTOFF_TS}").fetchone()[0]
    cols = ", ".join(f"fwd_ret_{h}" for h in HZ)
    muw = ", ".join(f"avg(fwd_ret_{h}) FILTER (ts + {HORIZONS[h]} <= {C}) OVER (PARTITION BY iso_week) AS mu_{h}" for h in HZ)
    d = con.execute(f"""SELECT ts, {cols}, {muw} FROM read_parquet('{fwd}') ORDER BY ts""").fetchnumpy()
    ts = np.asarray(d["ts"])
    def _f(name):  # MaskedArray NULL fix (audit 2026-07-10)
        a = d[name]
        return np.ma.filled(a.astype(np.float64), np.nan) if isinstance(a, np.ma.MaskedArray) else np.asarray(a, np.float64)
    TA = {h: (_f(f"fwd_ret_{h}") - _f(f"mu_{h}")) for h in HZ}
    return ts, TA


def _coin_entries(con, coin: str):
    """Candidate wallets' member entries for this coin, grouped: list of (wallet, rows[], dir_sign[])."""
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    C = con.execute(f"SELECT {CUTOFF_TS}").fetchone()[0]
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts, m.dir_sign
      FROM read_parquet('{mk}') m JOIN pool p ON p.wallet=m.wallet AND p.coin='{coin}'
      WHERE m.close_ts <= {C} AND NOT m.entry_after_close AND m.entry_lag_s <= {ENTRY_LAG_MAX_S}
        AND m.raw_markout_8h IS NOT NULL AND (m.entry_bar_ts + {HORIZONS['8h']}) <= {C}
      ORDER BY m.wallet""").fetchnumpy()


def run():
    rng = np.random.default_rng(RNG_SEED)
    con = _con(); fam = _hygiene_pool(con)
    npool = con.execute("SELECT count(*) FROM pool").fetchone()[0]
    print(f"full hygiene family (n_weeks>=6): {fam:,}   candidate pool (est>0&lb>0 @>=1 hz): {npool:,}")
    print(f"permutation null B={B}, seed={RNG_SEED}, max-stat over {HZ}, BH-FDR q={FDR_Q}\n")

    recs = []  # (wallet, coin, best_h, obs_z_max, p_max, {p_h})
    for coin in COINS:
        ts, TA = _coin_grid(con, coin)
        e = _coin_entries(con, coin)
        wal = np.asarray(e["wallet"], dtype=object)
        if len(wal) == 0:
            continue
        # map entry_bar_ts -> grid row (exact tick, since entry_bar_ts is a real px tick)
        row_all = np.clip(np.searchsorted(ts, np.asarray(e["entry_bar_ts"])), 0, len(ts) - 1)
        dir_all = np.asarray(e["dir_sign"], dtype=np.float64)
        # rows are ORDER BY wallet -> contiguous groups
        uniq, first = np.unique(wal, return_index=True)
        bounds = np.append(np.sort(first), len(wal))
        n_tested = len(uniq)
        for gi in range(len(uniq)):
            s, ez = bounds[gi], bounds[gi + 1]
            w = wal[s]
            r = row_all[s:ez]; d = dir_all[s:ez]
            n = len(r)
            lo, hi = r.min(), r.max()
            if hi <= lo or n < 3:
                continue
            # B null draws of n minutes each from the wallet's window [lo,hi]; SAME draws across horizons
            draws = rng.integers(lo, hi + 1, size=(B, n))
            obs_z, null_z_max, p_h = [], None, {}
            for h in HZ:
                ta = TA[h]
                obs = float(np.mean(d * ta[r]))
                null = np.mean(d[None, :] * ta[draws], axis=1)          # (B,)
                mu, sd = null.mean(), null.std()
                sd = sd if sd > 1e-9 else 1e-9
                p_h[h] = (1 + int(np.sum(null >= obs))) / (B + 1)
                z = (obs - mu) / sd
                obs_z.append(z)
                nz = (null - mu) / sd
                null_z_max = nz if null_z_max is None else np.maximum(null_z_max, nz)
            obs_z = np.array(obs_z)
            best_i = int(np.argmax(obs_z))
            p_max = (1 + int(np.sum(null_z_max >= obs_z[best_i]))) / (B + 1)
            recs.append((w, coin, HZ[best_i], round(float(obs_z[best_i]), 2), p_max, p_h))
        print(f"  {coin}: tested {n_tested:,} candidate wallets", flush=True)

    # BH-FDR over p_max across the whole family (untested pool members implicitly p=1)
    m = fam
    pv = sorted((r[4], i) for i, r in enumerate(recs))
    surv = set()
    thr = 0.0
    for k, (p, i) in enumerate(pv, 1):
        if p <= (k / m) * FDR_Q:
            thr = p; surv = {i for (pp, i) in pv[:k]}
    print(f"\ntested {len(recs):,} candidates against family m={m:,}")
    print(f"BH-FDR q={FDR_Q}: {len(surv)} survive the max-stat luck test (threshold p<= {thr:.4g})")
    # per-horizon uncorrected significant (p<0.05) for the term structure
    print("\nper-horizon UNCORRECTED p<0.05 counts (descriptive term structure):")
    for h in HZ:
        c = sum(1 for r in recs if r[5][h] < 0.05)
        print(f"   {h}: {c:,}")
    print("\nsurvivors (max-stat FDR):")
    for i in sorted(surv, key=lambda i: recs[i][4]):
        w, coin, bh, z, pmax, ph = recs[i]
        print(f"   {w[:10]}… {coin:4s} best={bh} z={z:+.2f} p_max={pmax:.4g}")


if __name__ == "__main__":
    run()
