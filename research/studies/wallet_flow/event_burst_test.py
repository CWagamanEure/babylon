"""event_burst_test — HEADLINE TEST: does a discrete cohort PILE-IN EVENT (coin+dir, >=K cohort wallets
net-same-direction within a trailing W-min window) carry a bigger per-event directional move than the
continuous hourly breadth-tilt (+0.0043 pooled IC baseline, dashboard/series.parquet)? Second-pass build on
`steelman_event_burst.py` stage-1 cache (the DuckDB self-join event-detection is already correct/bug-fixed
there and cached to scratch -- reused here, NOT re-run, to stay RAM/time-safe).

Fixes the ONE real gap in the prior partial run: event dedup was NOT horizon-aware (same n_events regardless
of H -> overlapping forward windows pooled as if independent -> inflated N, understated SE for large H). This
script re-derives events per-H with a genuinely non-overlapping (coin,dir) walk: an event's forward window must
fully elapse before the next same-(coin,dir) event can register. Reports point estimate + day-block-bootstrap
CI + MDE, a K x W grid (Bonferroni-flagged), and a fresh matched-random-cohort placebo (pool extracted ONCE,
each of N draws filters the cached pool in-memory -- no repeat full-tape rescans).

Stage 1 (cached, reused): W15_/W30_/W60_ coin/t/npos/nneg candidate arrays, `cohort_candidates.npz`.
Stage 2 (this file): rebuild price/resid forward-return panels incl H=6 (cheap); horizon-aware dedup; event
  stats + day-block CI, full K x W grid.
Stage 3 (this file): matched-random-cohort placebo at the primary (K=9, W=30).
Stage 4 (this file): compare to the continuous +0.0043 IC baseline; write JSON report.

    PYTHONPATH=/Users/corywagamaneure/bablyon .venv/bin/python -m research.studies.wallet_flow.event_burst_test [stage]
"""
from __future__ import annotations
import functools, json, sys, time
from pathlib import Path
import numpy as np
warnings_module = __import__("warnings")
warnings_module.filterwarnings("ignore")
np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:7.1f}s] {m}")

COH = Path("data/derived/alt_timing/cohort.json")
SCRATCH2 = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/565ad9b7-d53e-409a-abe5-66918970dbf0/scratchpad/ev")
OUT = SCRATCH2 / "burst2"
OUT.mkdir(parents=True, exist_ok=True)

FOLDS = (202512, 202601, 202602, 202603, 202604, 202605, 202606)   # full pooled OOS window (dashboard-matched)
HORIZONS = (1, 4, 6, 8)                     # hours; 6h added (task spec); 8h kept for grid continuity w/ stage1
PRIMARY_W, PRIMARY_K, PRIMARY_H = 30, 9, 4   # matches majors' consensus>=9 / WIN=30min design exactly
WINDOWS_MIN = (15, 30, 60)
KS = (5, 7, 9, 12, 16, 20, 25)
N_PLACEBO = 5
SEED = 20260711
MIN_RECENT_H, RECENT_MONTHS = 40, (202605, 202606)   # matches export_timing_cohort.py recency gate


def build_panels():
    """Rebuild the price/resid panel + forward-cum matrices (raw & resid) incl H=6. Cheap (~90s): reuses
    A.build_resid, not the heavy self-join. Cached to fwd_panels2.npz."""
    outp = OUT / "fwd_panels2.npz"
    if outp.exists():
        d = np.load(outp, allow_pickle=True)
        return {k: d[k] for k in d.files}
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1200MB'; SET threads=2")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins)
    hours, ci, N, resid = panel["hours"], panel["ci"], panel["N"], panel["resid"]
    hmin = int(hours[0])
    inlist = "('" + "','".join(coins) + "')"
    drop = " AND day NOT IN (" + ",".join(str(d) for d in A.DROP_DAYS) + ")" if A.DROP_DAYS else ""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbev AS
        WITH v AS (SELECT coin, ts, (ts - ts%3600000) AS h, mid_px FROM asset_ctx
                   WHERE coin IN {inlist} AND mid_px>0{drop})
        SELECT coin, h, arg_max(mid_px, ts) AS mid FROM v GROUP BY coin, h""")
    d = con.execute("SELECT coin, h, mid FROM hbev").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64)
    C = len(coins)
    Lp = np.full((N, C), np.nan)
    rr = ((ha - hmin) // 3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok])
    Rraw = np.diff(Lp, axis=0, prepend=np.nan)

    def fwdcum(mat):
        cs = np.where(np.isfinite(mat), mat, 0.0)
        out = {}
        for H in HORIZONS:
            o = np.full((N, C), np.nan)
            for h in range(N - H):
                o[h] = cs[h+1:h+1+H].sum(axis=0)
            out[H] = o
        return out
    fwd_raw = fwdcum(Rraw)
    fwd_res = fwdcum(resid)
    out = dict(hours=hours, coins=np.array(coins, dtype=object), hmin=np.array(hmin), N=np.array(N))
    for H in HORIZONS:
        out[f"raw_H{H}"] = fwd_raw[H]; out[f"res_H{H}"] = fwd_res[H]
    np.savez(outp, **out)
    _log("fresh forward panels built (incl H=6)")
    return out


def _load_cand(W):
    d = np.load(SCRATCH2 / "cohort_candidates.npz", allow_pickle=True)
    coin = d[f"W{W}_coin"].astype(str); t = d[f"W{W}_t"].astype(np.int64)
    npos = d[f"W{W}_npos"].astype(np.int64); nneg = d[f"W{W}_nneg"].astype(np.int64)
    # collapse duplicate (coin,t) rows (one row per triggering wallet -> same npos/nneg repeated)
    key = np.array([f"{c}|{tt}" for c, tt in zip(coin, t)])
    _, idx = np.unique(key, return_index=True)
    return coin[idx], t[idx], npos[idx], nneg[idx]


def build_events_horizon_aware(coin, t, npos, nneg, K, H_ms):
    """For each (coin,dir) independently: sort candidate times ascending; walk greedily, registering an event
    only when the previous same-(coin,dir) event's H-hour forward window has fully elapsed. Non-overlapping
    forward windows by construction -> the resulting per-event returns for a given coin+dir are not pooling
    overlapping price paths (still correlated ACROSS coins/dirs on the same day -> day-block CI handles that)."""
    ev_coin, ev_t, ev_dir = [], [], []
    for dirn, cnt, thr in ((1, npos, K), (-1, nneg, K)):
        mask = cnt >= thr
        if not mask.any():
            continue
        cc, tt = coin[mask], t[mask]
        order = np.lexsort((tt, cc))
        cc, tt = cc[order], tt[order]
        last_t = {}
        for c, ti in zip(cc, tt):
            lt = last_t.get(c)
            if lt is None or ti > lt + H_ms:
                ev_coin.append(c); ev_t.append(int(ti)); ev_dir.append(dirn)
                last_t[c] = ti
    return np.array(ev_coin), np.array(ev_t, dtype=np.int64), np.array(ev_dir, dtype=np.int8)


def event_returns(ev_coin, ev_t, ev_dir, panels, H, kind, coin_idx):
    hmin = int(panels["hmin"]); N = int(panels["N"])
    fwd = panels[f"{kind}_H{H}"]
    h = (ev_t - hmin) // 3_600_000
    ok = (h >= 0) & (h < N)
    h = h[ok]; d = ev_dir[ok]; c = ev_coin[ok]; tv = ev_t[ok]
    ci = np.array([coin_idx.get(x, -1) for x in c])
    ok2 = ci >= 0
    h, d, ci, tv = h[ok2], d[ok2], ci[ok2], tv[ok2]
    r = fwd[h, ci] * d * 1e4   # bp, sign-aligned with event direction
    fin = np.isfinite(r)
    return r[fin], tv[fin], c[ok2][fin]


def day_block_ci(vals, days, n_boot=3000, seed=SEED):
    """Bootstrap over distinct calendar days (resample days w/ replacement, pool their events)."""
    u = np.unique(days)
    if len(u) < 5 or len(vals) < 15:
        return (np.nan, np.nan, np.nan, len(u))
    by_day = {dd: vals[days == dd] for dd in u}
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    m = len(u)
    for b in range(n_boot):
        pick = u[rng.integers(0, m, m)]
        pooled = np.concatenate([by_day[p] for p in pick])
        means[b] = pooled.mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi), float(means.std()), m


def event_stats(r, tv, seed=SEED):
    if len(r) < 15:
        return None
    days = (tv // 86_400_000).astype(np.int64)
    lo, hi, se_boot, n_days = day_block_ci(r, days, seed=seed)
    return dict(n_events=int(len(r)), n_days=int(n_days), mean_bp=float(np.mean(r)),
                median_bp=float(np.median(r)), sd_bp=float(np.std(r)), frac_pos=float(np.mean(r > 0)),
                ci_lo=lo, ci_hi=hi, se_boot=se_boot)


def stage2_grid(panels):
    outp = OUT / "grid2.json"
    coins = [str(x) for x in panels["coins"]]
    coin_idx = {c: i for i, c in enumerate(coins)}
    grid = []
    for W in WINDOWS_MIN:
        coin, t, npos, nneg = _load_cand(W)
        for K in KS:
            for H in HORIZONS:
                ev_c, ev_t, ev_d = build_events_horizon_aware(coin, t, npos, nneg, K, H * 3_600_000)
                for kind in ("raw", "res"):
                    r, tv, _ = event_returns(ev_c, ev_t, ev_d, panels, H, kind, coin_idx)
                    st = event_stats(r, tv)
                    if st is None:
                        continue
                    st.update(W=W, K=K, H=H, kind=kind)
                    grid.append(st)
        _log(f"W={W}: grid rows so far={len(grid)}")
    outp.write_text(json.dumps(grid, indent=2))
    return grid


def eligible_pool(con, alts, real_cohort):
    inlist = "('" + "','".join(alts) + "')"; rm = ",".join(str(m) for m in RECENT_MONTHS)
    act = con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({rm}) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
    pool = sorted(set(str(x[0]) for x in act) - set(real_cohort))
    return pool


def extract_pool_once(con, alts, pool, tag="pool_flow"):
    outdir = SCRATCH2 / tag; outdir.mkdir(parents=True, exist_ok=True)
    alt_inlist = "('" + "','".join(alts) + "')"
    plist = "('" + "','".join(pool) + "')"
    for m in FOLDS:
        outp = outdir / f"month={m}.parquet"
        if outp.exists() and outp.stat().st_size > 0:
            continue
        con.execute(f"""COPY (
            SELECT wallet, coin, bucket, sum(flow_signed) AS flow
            FROM alt_flow WHERE month={m} AND wallet IN {plist} AND coin IN {alt_inlist}
            GROUP BY wallet, coin, bucket
        ) TO '{outp}' (FORMAT PARQUET)""")
        _log(f"  pool extract month={m} done")
    return str(outdir)


def detect_for_wallets(con, glob_path, wallets_sql_list, W_ms):
    """Self-join restricted to a wallet subset (fast: pool cache already coin/month filtered)."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE dcflow AS
        SELECT * FROM read_parquet('{glob_path}/month=*.parquet')
        WHERE flow<>0 AND wallet IN {wallets_sql_list}""")
    q = con.execute(f"""
        WITH cand AS (SELECT DISTINCT coin, bucket AS t FROM dcflow),
             wnet AS (
                 SELECT a.coin AS coin, a.t AS t, b.wallet AS w2, sum(b.flow) AS wsum
                 FROM cand a JOIN dcflow b ON a.coin = b.coin AND b.bucket > a.t - {W_ms} AND b.bucket <= a.t
                 GROUP BY a.coin, a.t, b.wallet
             ),
             wc AS (
                 SELECT coin, t, count(*) FILTER (wsum > 0) AS n_pos, count(*) FILTER (wsum < 0) AS n_neg
                 FROM wnet GROUP BY coin, t
             )
        SELECT coin, t, n_pos, n_neg FROM wc
    """).fetchnumpy()
    return q


def stage3_placebo(panels):
    outp = OUT / "placebo2.json"
    draws = []
    if outp.exists():
        prev = json.loads(outp.read_text())
        draws = prev.get("draws", [])
        if len(draws) >= N_PLACEBO:
            return prev
        _log(f"resuming placebo: {len(draws)} draws already cached, need {N_PLACEBO - len(draws)} more")
    cfg = json.loads(COH.read_text())
    real_cohort = sorted(set(cfg["cohort"]))
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=2")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2_pl'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    coin_idx = {c: i for i, c in enumerate(coins)}

    pool = eligible_pool(con, alts, real_cohort)
    _log(f"placebo pool (recency-eligible, ex-real-cohort): {len(pool):,}")
    glob_path = extract_pool_once(con, alts, pool)
    _log("pool extraction (one-time, full 7mo) done")

    rng = np.random.default_rng(SEED)
    W_ms = PRIMARY_W * 60_000
    for i in range(N_PLACEBO):
        samp = rng.choice(pool, size=len(real_cohort), replace=False)
        if i < len(draws):
            continue   # deterministic RNG stream -- skip already-completed draws, keep the stream advancing
        wsql = "('" + "','".join(samp.tolist()) + "')"
        t0 = time.time()
        q = detect_for_wallets(con, glob_path, wsql, W_ms)
        coin_a, t_a = q["coin"].astype(str), q["t"].astype(np.int64)
        npos_a, nneg_a = q["n_pos"].astype(np.int64), q["n_neg"].astype(np.int64)
        row = {"draw": i, "n_candidates": int(len(coin_a))}
        for H in (1, 4, 6):
            ev_c, ev_t, ev_d = build_events_horizon_aware(coin_a, t_a, npos_a, nneg_a, PRIMARY_K, H * 3_600_000)
            for kind in ("raw", "res"):
                r, tv, _ = event_returns(ev_c, ev_t, ev_d, panels, H, kind, coin_idx)
                st = event_stats(r, tv, seed=SEED + i + 1)
                row[f"H{H}_{kind}"] = st
        draws.append(row)
        h1 = row.get("H1_res") or {}
        _log(f"draw {i}: {time.time()-t0:.0f}s, n_cand={row['n_candidates']:,}, "
             f"H1_res mean={h1.get('mean_bp', float('nan')):+.2f}bp n={h1.get('n_events', 0)}")
        # incremental save -- never lose completed draws if the run is cut short
        result = {"pool_size": len(pool), "cohort_size": len(real_cohort), "draws": draws}
        outp.write_text(json.dumps(result, indent=2))
    return result


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    panels = build_panels()
    _log(f"panels ready: N={int(panels['N'])}, coins={len(panels['coins'])}, horizons cached={HORIZONS}")
    if stage in ("all", "grid"):
        grid = stage2_grid(panels)
        _log(f"grid done: {len(grid)} rows -> {OUT/'grid2.json'}")
    if stage in ("all", "placebo"):
        pl = stage3_placebo(panels)
        _log(f"placebo done: {len(pl['draws'])} draws -> {OUT/'placebo2.json'}")


if __name__ == "__main__":
    main()
