"""steelman_event_burst — STEELMAN pass: does a discrete PILE-IN EVENT/BURST formulation (coin+dir, >=K cohort
wallets net-same-direction within a trailing W-min window) carry a bigger per-event directional move than the
continuous hourly breadth-tilt (+0.0043 IC baseline, data/derived/alt_timing/dashboard/series.parquet)? Mirrors
the majors consensus>=9 design (markout_study/src/real_exec_consensus.py) on the ALT cohort/universe.

Uses the SAME fixed deployed cohort (data/derived/alt_timing/cohort.json, 1500 wallets) and the SAME factor-neutral
target (BTC/ETH + LOO-alt-index neutralized residual, research.studies.wallet_flow.alt_flow.build_resid) as the
dashboard baseline -- only the AGGREGATOR varies (continuous tilt vs event/burst), isolating the aggregation effect.
Same circularity caveat as the dashboard baseline (cohort selected using late-window recency data, applied
retroactively across the whole test window) applies here too -- disclosed, not hidden, and applies symmetrically
to both the baseline and this steelman so it does not advantage either.

Event detection = a single SQL self-join per window W (DuckDB manages memory/spill, not raw python arrays) --
for every cohort (wallet,coin,bucket) row (the "trigger"), count distinct cohort wallets with positive/negative
NET flow in that coin over the trailing W-minute window ending at the trigger's bucket. Thresholding by K and
burst-collapsing (consecutive same coin+dir flags within W of each other -> one event, matching majors) is done
in python on the (small) resulting per-candidate table.

    .venv/bin/python -m research.studies.wallet_flow.steelman_event_burst
"""
from __future__ import annotations
import functools, json, time, warnings
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

COH = Path("data/derived/alt_timing/cohort.json")
SCRATCH2 = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/565ad9b7-d53e-409a-abe5-66918970dbf0/scratchpad/ev")
FOLDS = (202512, 202601, 202602, 202603, 202604, 202605, 202606)   # matches dashboard's pooled 7-month OOS window
HORIZONS = (1, 4, 8, 24)          # hours
WINDOWS_MIN = (15, 30, 60)        # trailing pile-in window (minutes) -- sweep, Bonferroni-corrected
PRIMARY_W = 30                    # pre-committed primary (matches majors' WIN=30min exactly)
KS = (5, 8, 12, 16, 20, 25)
Wb, MINOBS = 720, 240
SEED = 20260711
N_PLACEBO = 12                    # matched-random-cohort placebo draws (independent, RAM/time-budgeted)


def _sign_arr(x):
    return np.where(x > 0, 1, np.where(x < 0, -1, 0)).astype(np.int8)


def extract_month_batched(con, alts, wallets, tag):
    """Month-batched (wallet,coin,bucket) net-flow extraction, cached to scratch parquet. RAM-safe."""
    outdir = SCRATCH2 / tag; outdir.mkdir(parents=True, exist_ok=True)
    alt_inlist = "('" + "','".join(alts) + "')"
    wlist = "('" + "','".join(wallets) + "')"
    for m in FOLDS:
        outp = outdir / f"month={m}.parquet"
        if outp.exists() and outp.stat().st_size > 0:
            continue
        con.execute(f"""COPY (
            SELECT wallet, coin, bucket, sum(flow_signed) AS flow
            FROM alt_flow WHERE month={m} AND wallet IN {wlist} AND coin IN {alt_inlist}
            GROUP BY wallet, coin, bucket
        ) TO '{outp}' (FORMAT PARQUET)""")
    return str(outdir)


def detect_candidates(con, glob_path, W_ms):
    """Self-join SQL: for every DISTINCT (coin,bucket) that has >=1 trigger, count distinct cohort wallets with
    net-positive / net-negative flow in that coin over the trailing (bucket-W, bucket] window (the window depends
    only on (coin,bucket), NOT on which wallet triggered it -- computed ONCE per (coin,bucket), then joined back
    to each trigger row for its own direction). Fixes an earlier bug where grouping the window count by
    (coin,t,trig_dir) without also grouping by trig_wallet summed duplicate windows once per co-timed trigger."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE cflow AS SELECT * FROM read_parquet('{glob_path}/month=*.parquet') WHERE flow<>0")
    n = con.execute("SELECT count(*) FROM cflow").fetchone()[0]
    q = con.execute(f"""
        WITH cand AS (SELECT DISTINCT coin, bucket AS t FROM cflow),
             wnet AS (
                 SELECT a.coin AS coin, a.t AS t, b.wallet AS w2, sum(b.flow) AS wsum
                 FROM cand a JOIN cflow b ON a.coin = b.coin AND b.bucket > a.t - {W_ms} AND b.bucket <= a.t
                 GROUP BY a.coin, a.t, b.wallet
             ),
             wc AS (
                 SELECT coin, t, count(*) FILTER (wsum > 0) AS n_pos, count(*) FILTER (wsum < 0) AS n_neg
                 FROM wnet GROUP BY coin, t
             )
        SELECT c.coin AS coin, c.bucket AS t, sign(c.flow) AS trig_dir, wc.n_pos AS n_pos, wc.n_neg AS n_neg
        FROM cflow c JOIN wc ON c.coin = wc.coin AND c.bucket = wc.t
    """).fetchnumpy()
    return n, q


def collapse_bursts(coin_arr, t_arr, dir_arr, flagged_mask):
    """Collapse consecutive same (coin,dir) flagged candidates within their own window-gap into one event
    (first flagged timestamp = event trigger), matching majors' burst-merge exactly."""
    idx = np.nonzero(flagged_mask)[0]
    order = idx[np.lexsort((t_arr[idx], dir_arr[idx], coin_arr[idx]))]
    events = []
    prev_key = None; prev_t = None
    for i in order:
        key = (coin_arr[i], dir_arr[i])
        t = int(t_arr[i])
        if key != prev_key:
            events.append([coin_arr[i], dir_arr[i], t])
        prev_key, prev_t = key, t
    return events   # note: gap-based re-open handled by caller (needs W per K, done post-hoc since gap depends on W not K)


def main():
    cfg = json.loads(COH.read_text())
    cohort = sorted(set(cfg["cohort"]))
    print(f"cohort: {len(cohort)} wallets (sha {cfg['cohort_sha']}), as_of {cfg['as_of_hour_ms']}")

    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1000MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evburst'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    _log(f"alts={len(alts)}")
    panel = A.build_resid(con, coins)
    hours, ci, N, resid = panel["hours"], panel["ci"], panel["N"], panel["resid"]
    hmin = int(hours[0])
    _log("panel/resid built")

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
    _log("forward cum series built (raw + resid)")

    outdir = extract_month_batched(con, alts, cohort, "cohort_flow")
    _log("cohort extraction done")

    results = {}   # W -> (n_candidates, arrays)
    for Wmin in WINDOWS_MIN:
        W_ms = Wmin * 60_000
        n, q = detect_candidates(con, outdir, W_ms)
        results[Wmin] = q
        _log(f"W={Wmin}min: {n:,} trigger rows -> {len(q['coin']):,} candidate summaries "
             f"(max n_pos={q['n_pos'].max()}, max n_neg={q['n_neg'].max()})")

    np.savez(SCRATCH2 / "cohort_candidates.npz",
             **{f"W{w}_coin": results[w]["coin"] for w in WINDOWS_MIN},
             **{f"W{w}_t": results[w]["t"] for w in WINDOWS_MIN},
             **{f"W{w}_dir": results[w]["trig_dir"] for w in WINDOWS_MIN},
             **{f"W{w}_npos": results[w]["n_pos"] for w in WINDOWS_MIN},
             **{f"W{w}_nneg": results[w]["n_neg"] for w in WINDOWS_MIN})
    np.savez(SCRATCH2 / "fwd_panels.npz", hours=hours, coins=np.array(coins, dtype=object), hmin=hmin, N=N,
             **{f"raw_H{h}": fwd_raw[h] for h in HORIZONS}, **{f"res_H{h}": fwd_res[h] for h in HORIZONS})
    _log("saved candidates + forward panels; stage 1 done")


if __name__ == "__main__":
    main()
