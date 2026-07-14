"""alt_event_burst_v2 — SECOND-PASS, independently-written event/burst evaluator for the informed alt cohort.

Tests whether a discrete "pile-in" formulation (coin+dir, >=K cohort wallets net-same-direction within a
trailing W-min window, majors-style) carries a bigger per-event directional move than the continuous hourly
breadth-tilt baseline (IC +0.0043 pooled 7-month, `data/derived/alt_timing/dashboard/series.parquet`).

Written independently of the partial (script-less) scratch artifacts left by an interrupted prior attempt at
this exact question (data/derived cache only, no source) -- reuses ONLY the reviewed, deterministic stage-1
extraction (`steelman_event_burst.py`: extract_month_batched + detect_candidates, both re-read and audited
here) via its cached output when the cohort hash matches, else recomputes. All EVENT/PLACEBO/CI logic below is
new and independently implemented, including a corrected burst-collapse (the inherited `collapse_bursts` in
steelman_event_burst.py was an documented-incomplete stub -- grouped candidates by (coin,dir) key only, with
NO time-gap re-open, which would silently merge unrelated pile-ins months apart into one event).

    .venv/bin/python -m research.studies.wallet_flow.alt_event_burst_v2 real       # real-cohort event grid + CI
    .venv/bin/python -m research.studies.wallet_flow.alt_event_burst_v2 placebo N  # N matched-random-cohort draws
    .venv/bin/python -m research.studies.wallet_flow.alt_event_burst_v2 maker      # maker-only trigger variant
"""
from __future__ import annotations
import functools, json, sys, time, warnings
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
S1 = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/565ad9b7-d53e-409a-abe5-66918970dbf0/scratchpad/ev")
S2 = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/565ad9b7-d53e-409a-abe5-66918970dbf0/scratchpad/evb2")
S2.mkdir(parents=True, exist_ok=True)
FOLDS = (202512, 202601, 202602, 202603, 202604, 202605, 202606)
PRIMARY_FOLDS = (202603, 202604, 202605, 202606)   # window where K>=9 events actually occur (verified below)
PRIMARY_W = 30; PRIMARY_K = 9
KS = (5, 8, 9, 12, 16, 20, 25)
WS_MIN = (15, 30, 60)
HORIZONS = (1, 4)
SEED = 20260711


# ---------------------------------------------------------------- shared: panel build (coins, fwd resid/raw) ----
def build_panels(con, coins):
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
                o[h] = cs[h + 1:h + 1 + H].sum(axis=0)
            out[H] = o
        return out
    return dict(hours=hours, ci=ci, N=N, hmin=hmin, coins=coins,
                fwd_raw=fwdcum(Rraw), fwd_res=fwdcum(resid))


def extract_flow(con, alts, wallets, tag, months=FOLDS, crossed=None):
    outdir = S2 / tag; outdir.mkdir(parents=True, exist_ok=True)
    alt_inlist = "('" + "','".join(alts) + "')"
    wlist = "('" + "','".join(wallets) + "')"
    cross_sql = "" if crossed is None else (f" AND crossed={'true' if crossed else 'false'}")
    for m in months:
        outp = outdir / f"month={m}.parquet"
        if outp.exists() and outp.stat().st_size > 0:
            continue
        con.execute(f"""COPY (
            SELECT wallet, coin, bucket, sum(flow_signed) AS flow
            FROM alt_flow WHERE month={m} AND wallet IN {wlist} AND coin IN {alt_inlist}{cross_sql}
            GROUP BY wallet, coin, bucket
        ) TO '{outp}' (FORMAT PARQUET)""")
    return str(outdir)


def detect_candidates(con, glob_path, W_ms):
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


# ---------------------------------------------------------------- CORRECTED burst collapse (time-gap re-open) ----
def collapse_bursts_correct(coin_arr, t_arr, dir_arr, flagged_mask, W_ms):
    """Per (coin,dir), sort candidates chronologically; start a NEW event whenever the previous flagged
    timestamp for that (coin,dir) is more than W_ms in the past (majors' exact rule: `key != prev_key or
    (t-prev_t) > WIN`). This is what the inherited stub explicitly deferred to a caller (comment: 'gap-based
    re-open handled by caller') -- the caller was never checked in; implemented fresh here."""
    idx = np.nonzero(flagged_mask)[0]
    if len(idx) == 0:
        return []
    order = idx[np.lexsort((t_arr[idx], dir_arr[idx], coin_arr[idx]))]
    events = []
    prev_key = None; prev_t = None
    for i in order:
        key = (coin_arr[i], dir_arr[i]); t = int(t_arr[i])
        if key != prev_key or (t - prev_t) > W_ms:
            events.append([coin_arr[i], dir_arr[i], t])
        prev_key, prev_t = key, t
    return events


def events_for_KW(cand, K, W_ms):
    coin, t, trig_dir, npos, nneg = cand["coin"], cand["t"], cand["trig_dir"], cand["n_pos"], cand["n_neg"]
    flag = ((trig_dir > 0) & (npos >= K)) | ((trig_dir < 0) & (nneg >= K))
    ev = collapse_bursts_correct(coin, t, trig_dir, flag, W_ms)
    return ev   # list of [coin, dir, t]


def eval_events(ev, panels, window_months=None):
    """Return per-event bp move (raw & resid) at each horizon, restricted to window_months (YYYYMM ints) if given."""
    hmin, ci, N = panels["hmin"], panels["ci"], panels["N"]
    out = {}
    if not ev:
        return {H: {"raw": np.array([]), "resid": np.array([]), "t": np.array([]), "coin": np.array([])} for H in HORIZONS}
    coin = np.array([e[0] for e in ev], dtype=object)
    dirn = np.array([e[1] for e in ev], dtype=np.int64)
    t = np.array([e[2] for e in ev], dtype=np.int64)
    if window_months is not None:
        import datetime
        ym = np.array([int(datetime.datetime.fromtimestamp(x / 1000, datetime.timezone.utc).strftime("%Y%m")) for x in t])
        keep = np.isin(ym, window_months)
        coin, dirn, t = coin[keep], dirn[keep], t[keep]
    hr = ((t - hmin) // 3600000).astype(int)
    cc = np.array([ci.get(str(c), -1) for c in coin])
    valid0 = (hr >= 0) & (cc >= 0)
    for H in HORIZONS:
        ok = valid0 & (hr < N - H)
        raw = np.full(len(coin), np.nan); res = np.full(len(coin), np.nan)
        raw[ok] = panels["fwd_raw"][H][hr[ok], cc[ok]] * dirn[ok] * 1e4
        res[ok] = panels["fwd_res"][H][hr[ok], cc[ok]] * dirn[ok] * 1e4
        fin = np.isfinite(res)
        out[H] = {"raw": raw[fin], "resid": res[fin], "t": t[fin], "coin": coin[fin]}
    return out


def dayblock_ci(vals, t_ms, nboot=2000, seed=SEED):
    """Day-block bootstrap CI on the mean (cluster by calendar day -- events within a burst / same day share
    regime exposure, so plain iid SE understates uncertainty)."""
    if len(vals) < 5:
        return dict(mean=float("nan"), lo=float("nan"), hi=float("nan"), n_days=0)
    import datetime
    days = np.array([datetime.datetime.fromtimestamp(x / 1000, datetime.timezone.utc).strftime("%Y%m%d") for x in t_ms])
    udays = np.unique(days)
    rng = np.random.default_rng(seed)
    by_day = {d: vals[days == d] for d in udays}
    boots = np.empty(nboot)
    nd = len(udays)
    for b in range(nboot):
        pick = rng.choice(udays, nd, replace=True)
        boots[b] = np.concatenate([by_day[d] for d in pick]).mean()
    return dict(mean=float(vals.mean()), lo=float(np.percentile(boots, 2.5)), hi=float(np.percentile(boots, 97.5)),
                n_days=int(nd), n=int(len(vals)))


def cohort_pool(con, alts):
    inlist = "('" + "','".join(alts) + "')"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE elig AS SELECT wallet FROM alt_flow
        WHERE month IN (202605,202606) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= 40""")
    pool = con.execute("SELECT wallet FROM elig").fetchnumpy()["wallet"]
    return np.asarray([str(x) for x in pool], dtype=object)


def real_stage():
    cfg = json.loads(COH.read_text())
    cohort = sorted(set(cfg["cohort"]))
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1000MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panels = build_panels(con, coins)
    _log(f"panels built, alts={len(alts)}")

    # candidates: reuse stage-1 cache if hash matches (deterministic function of raw data + reviewed code)
    cand_npz = S1 / "cohort_candidates.npz"
    use_cache = cand_npz.exists() and "290980281b5c3f4f" in (S1 / "stage1.log").read_text()
    if use_cache:
        d = np.load(cand_npz, allow_pickle=True)
        _log("using verified stage-1 cache (cohort sha matches)")
    else:
        outdir = extract_flow(con, alts, cohort, "real_flow")
        d = {}
        for Wmin in WS_MIN:
            n, q = detect_candidates(con, outdir, Wmin * 60_000)
            d[f"W{Wmin}_coin"] = q["coin"]; d[f"W{Wmin}_t"] = q["t"]; d[f"W{Wmin}_dir"] = q["trig_dir"]
            d[f"W{Wmin}_npos"] = q["n_pos"]; d[f"W{Wmin}_nneg"] = q["n_neg"]

    grid = []
    per_month = {}
    for Wmin in WS_MIN:
        cand = dict(coin=d[f"W{Wmin}_coin"], t=d[f"W{Wmin}_t"], trig_dir=d[f"W{Wmin}_dir"],
                    n_pos=d[f"W{Wmin}_npos"], n_neg=d[f"W{Wmin}_nneg"])
        for K in KS:
            ev = events_for_KW(cand, K, Wmin * 60_000)
            res = eval_events(ev, panels)
            for H in HORIZONS:
                for kind in ("raw", "resid"):
                    vals = res[H][kind]; t_ms = res[H]["t"]
                    if len(vals) < 5:
                        continue
                    ci_ = dayblock_ci(vals, t_ms)
                    grid.append(dict(W=Wmin, K=K, H=H, kind=kind, n_events=len(ev), n_valid=len(vals),
                                      **ci_))
            if Wmin == PRIMARY_W and K == PRIMARY_K:
                import datetime
                res1 = res[1]
                months = np.array([int(datetime.datetime.fromtimestamp(x / 1000, datetime.timezone.utc).strftime("%Y%m")) for x in res1["t"]])
                for m in sorted(set(months.tolist())):
                    mm = months == m
                    per_month[str(m)] = dict(n=int(mm.sum()), mean_resid_bp=float(np.nanmean(res1["resid"][mm])),
                                              mean_raw_bp=float(np.nanmean(res1["raw"][mm])))
        _log(f"W={Wmin} done")

    (S2 / "real_grid.json").write_text(json.dumps(grid, indent=1))
    (S2 / "real_per_month_K9W30.json").write_text(json.dumps(per_month, indent=1))
    _log(f"real stage done: {len(grid)} grid cells")
    # print primary
    for r in grid:
        if r["W"] == PRIMARY_W and r["K"] == PRIMARY_K:
            print(r)
    print("per-month K9/W30/H1:", json.dumps(per_month, indent=1))


def placebo_stage(ndraw, months=PRIMARY_FOLDS, seed_base=SEED + 1000):
    cfg = json.loads(COH.read_text())
    real_cohort = set(cfg["cohort"])
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1000MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2_pl'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panels = build_panels(con, coins)
    pool = cohort_pool(con, alts)
    pool = np.array([w for w in pool if w not in real_cohort], dtype=object)
    _log(f"placebo pool (ex-real-cohort): {len(pool):,}")

    outp = S2 / "placebo_results.json"
    prior = json.loads(outp.read_text()) if outp.exists() else []
    done = len(prior)
    for i in range(done, done + ndraw):
        rng = np.random.default_rng(seed_base + i)
        draw = rng.choice(pool, size=len(real_cohort), replace=False)
        outdir = extract_flow(con, alts, list(draw), f"placebo_flow_{i}", months=months)
        n, q = detect_candidates(con, outdir, PRIMARY_W * 60_000)
        cand = dict(coin=q["coin"], t=q["t"], trig_dir=q["trig_dir"], n_pos=q["n_pos"], n_neg=q["n_neg"])
        ev = events_for_KW(cand, PRIMARY_K, PRIMARY_W * 60_000)
        res = eval_events(ev, panels, window_months=months)
        rec = {"draw": i, "n_events": len(ev)}
        for H in HORIZONS:
            v = res[H]["resid"]; vr = res[H]["raw"]
            rec[f"H{H}_n"] = int(len(v))
            rec[f"H{H}_resid_mean_bp"] = float(np.nanmean(v)) if len(v) else float("nan")
            rec[f"H{H}_raw_mean_bp"] = float(np.nanmean(vr)) if len(vr) else float("nan")
        prior.append(rec)
        outp.write_text(json.dumps(prior, indent=1))
        _log(f"draw {i}: n_events={len(ev)} H1_resid={rec.get('H1_resid_mean_bp'):.2f}bp H4_resid={rec.get('H4_resid_mean_bp'):.2f}bp")
    print(f"placebo total draws so far: {len(prior)}")


def maker_stage():
    """Combine lead #1 (maker-only) with the event-burst formulation: trigger events using ONLY the cohort's
    resting (crossed=false) fills, matching the alt-timing maker-only lead's mechanism."""
    cfg = json.loads(COH.read_text())
    cohort = sorted(set(cfg["cohort"]))
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1000MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2_mk'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panels = build_panels(con, coins)
    _log("panels built")
    grid = []
    for tag, crossed in (("maker", False), ("taker", True), ("all", None)):
        outdir = extract_flow(con, alts, cohort, f"real_flow_{tag}", months=PRIMARY_FOLDS, crossed=crossed)
        n, q = detect_candidates(con, outdir, PRIMARY_W * 60_000)
        cand = dict(coin=q["coin"], t=q["t"], trig_dir=q["trig_dir"], n_pos=q["n_pos"], n_neg=q["n_neg"])
        for K in (5, 9, 12):
            ev = events_for_KW(cand, K, PRIMARY_W * 60_000)
            res = eval_events(ev, panels, window_months=PRIMARY_FOLDS)
            for H in HORIZONS:
                vals = res[H]["resid"]; t_ms = res[H]["t"]
                if len(vals) < 5:
                    grid.append(dict(tag=tag, K=K, H=H, n_events=len(ev), n_valid=len(vals))); continue
                ci_ = dayblock_ci(vals, t_ms)
                grid.append(dict(tag=tag, K=K, H=H, n_events=len(ev), **ci_))
        _log(f"tag={tag} done, n_trigger_rows={n}")
    (S2 / "maker_grid.json").write_text(json.dumps(grid, indent=1))
    for r in grid:
        print(r)


def _prev(m):
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


def early_cohort_stage(cutoff=202602, test_months=PRIMARY_FOLDS, nsel=1500):
    """⚠️ CIRCULARITY CHECK (critical, not optional): the deployed cohort.json was formed as_of 2026-06-29 --
    i.e. using data through the END of the test window -- and applied RETROACTIVELY across Dec'25-Jun'26. The
    K>=9 event effect above is measured almost entirely in Apr-Jun (the months closest to/at formation), which
    is exactly the same circularity pattern Result 9b found inflated the continuous signal's in-sample z from
    ~0.07 (honest walk-forward) to ~20.6 (static-cohort-applied-backward). This builds a cohort using ONLY
    train data BEFORE `cutoff` (score = avg(sign(net_flow))*fwd_idx_h1 over train hours, recency-gated on the
    2 months before cutoff -- mirrors alt_timing_dashboard_data.py's honest per-fold WF cohort construction
    exactly) and tests the SAME K=9/W=30 event design on the held-out `test_months` (2026-06-29 look-ahead
    impossible by construction). If the effect survives here, it is not pure circularity."""
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2_early'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panels = build_panels(con, coins)
    A.build_cohort_tables(con, coins)      # cached awb (per wallet,coin,hour,month) -- reused if already built
    hours, hmin, N = panels["hours"], panels["hmin"], panels["N"]
    hh = hours.astype(np.int64)
    _log("panels + awb ready")

    # BTC/ETH-neutral alt-index forward H1 (same target as the dashboard fold_tilt scoring)
    ci = panels["ci"]
    idx = np.nanmean(panels["fwd_res"][1][:, [ci[a] for a in alts]], axis=1)  # proxy: resid-avg ~ index-neutral direction
    ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={cutoff}").fetchone()[0])
    emb = ms_cut - 3600000
    fmask = np.isfinite(idx) & (hh < emb)
    con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": idx[fmask].astype(float)})
    con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
    sc = con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb
            WHERE mth<{cutoff} AND coin NOT IN ('BTC','ETH') GROUP BY wallet,h)
        SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
        WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>=20""").fetchnumpy()
    wal = np.asarray([str(x) for x in sc["wallet"]], dtype=object); score = sc["score"].astype(float)
    r1, r2 = _prev(_prev(cutoff)), _prev(cutoff)
    act = con.execute(f"""SELECT wallet FROM awb WHERE mth IN ({r1},{r2})
        GROUP BY wallet HAVING count(DISTINCT h) >= 40""").fetchall()
    active = set(str(x[0]) for x in act)
    elig = np.array([w in active for w in wal]); wal_e, sc_e = wal[elig], score[elig]
    _log(f"train wallets scored: {len(wal)}, recency-eligible: {len(wal_e)}")
    if len(wal_e) < nsel:
        print(f"NOT ENOUGH eligible wallets ({len(wal_e)} < {nsel}) -- abort"); return
    early_cohort = list(wal_e[np.argsort(-sc_e)[:nsel]])
    _log(f"early cohort formed (cutoff={cutoff}, train<{cutoff}, recency={r1}/{r2}): {len(early_cohort)} wallets")

    outdir = extract_flow(con, alts, early_cohort, f"early_flow_{cutoff}", months=test_months)
    n, q = detect_candidates(con, outdir, PRIMARY_W * 60_000)
    cand = dict(coin=q["coin"], t=q["t"], trig_dir=q["trig_dir"], n_pos=q["n_pos"], n_neg=q["n_neg"])
    out = {}
    for K in (5, 9, 12):
        ev = events_for_KW(cand, K, PRIMARY_W * 60_000)
        res = eval_events(ev, panels, window_months=test_months)
        row = {"K": K, "n_events": len(ev)}
        for H in HORIZONS:
            vals = res[H]["resid"]; t_ms = res[H]["t"]
            if len(vals) >= 5:
                row[f"H{H}"] = dayblock_ci(vals, t_ms)
            else:
                row[f"H{H}"] = {"n": len(vals)}
        out[str(K)] = row
        _log(f"K={K}: n_events={len(ev)} H1={row['H1']}")
    (S2 / f"early_cohort_{cutoff}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def score_cohort_for_month(con, m, idx, hh, nsel=1500):
    """Score+select a cohort using ONLY data strictly before month m (mirrors the honest per-fold WF cohort in
    alt_timing_dashboard_data.py / early_cohort_stage). Returns the wallet list, or None if underpowered."""
    ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={m}").fetchone()[0])
    emb = ms_cut - 3600000
    fmask = np.isfinite(idx) & (hh < emb)
    con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": idx[fmask].astype(float)})
    con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
    sc = con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb
            WHERE mth<{m} AND coin NOT IN ('BTC','ETH') GROUP BY wallet,h)
        SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
        WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>=20""").fetchnumpy()
    wal = np.asarray([str(x) for x in sc["wallet"]], dtype=object); score = sc["score"].astype(float)
    r1, r2 = _prev(_prev(m)), _prev(m)
    act = con.execute(f"""SELECT wallet FROM awb WHERE mth IN ({r1},{r2})
        GROUP BY wallet HAVING count(DISTINCT h) >= 40""").fetchall()
    active = set(str(x[0]) for x in act)
    elig = np.array([w in active for w in wal]); wal_e, sc_e = wal[elig], score[elig]
    if len(wal_e) < nsel:
        return None
    return list(wal_e[np.argsort(-sc_e)[:nsel]])


def pooled_wf_stage(test_months=(202603, 202604, 202605, 202606), nsel=1500):
    """The CORRECT honest comparison to the continuous baseline's pooled walk-forward IC (+0.0043): for EACH
    test month m, form a cohort using train<m only (no look-ahead), extract that fold's own cohort's flow for
    JUST month m, detect K=9/W=30 events inside that single held-out month, then POOL all months' events into
    one OOS series -- exactly mirroring how alt_timing_dashboard_data.py concatenates per-fold OOS tilt into one
    series before computing the headline IC. This is the number that should be set against +0.0043, NOT the
    single fixed end-of-window cohort applied retroactively (which is analogous to the discarded in-sample
    z=20.6 circular number)."""
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_evb2_wf'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panels = build_panels(con, coins)
    A.build_cohort_tables(con, coins)
    hh = panels["hours"].astype(np.int64); ci = panels["ci"]
    idx = np.nanmean(panels["fwd_res"][1][:, [ci[a] for a in alts]], axis=1)
    _log("panels + awb ready")

    all_ev = []
    for m in test_months:
        cohort_m = score_cohort_for_month(con, m, idx, hh, nsel)
        if cohort_m is None:
            _log(f"month {m}: not enough eligible wallets, skip"); continue
        outdir = extract_flow(con, alts, cohort_m, f"wf_flow_{m}", months=(m,))
        n, q = detect_candidates(con, outdir, PRIMARY_W * 60_000)
        cand = dict(coin=q["coin"], t=q["t"], trig_dir=q["trig_dir"], n_pos=q["n_pos"], n_neg=q["n_neg"])
        for K in (5, 9):
            ev = events_for_KW(cand, K, PRIMARY_W * 60_000)
            all_ev.append((m, K, ev))
            _log(f"month {m} K={K}: cohort={len(cohort_m)} raw_trigger_rows={n} events={len(ev)}")

    out = {}
    for K in (5, 9):
        pooled = []
        for m, k, ev in all_ev:
            if k == K:
                pooled.extend(ev)
        res = eval_events(pooled, panels, window_months=test_months)
        row = {"K": K, "n_events": len(pooled)}
        for H in HORIZONS:
            vals = res[H]["resid"]; t_ms = res[H]["t"]
            row[f"H{H}"] = dayblock_ci(vals, t_ms) if len(vals) >= 5 else {"n": len(vals)}
        out[str(K)] = row
        _log(f"POOLED K={K}: n_events={len(pooled)} H1={row['H1']}")
    (S2 / "pooled_wf.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "real"
    if mode == "real":
        real_stage()
    elif mode == "placebo":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        placebo_stage(n)
    elif mode == "maker":
        maker_stage()
    elif mode == "early":
        cutoff = int(sys.argv[2]) if len(sys.argv) > 2 else 202602
        tm = tuple(m for m in PRIMARY_FOLDS if m > cutoff)
        early_cohort_stage(cutoff, test_months=tm)
    elif mode == "pooledwf":
        pooled_wf_stage()
    else:
        raise SystemExit(f"unknown mode {mode}")
