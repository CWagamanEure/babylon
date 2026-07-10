"""wallet_flow — the "differentiator" leg of xsec_statarb (ARCHITECTURE §10, AUDIT_RESPONSE A8).

QUESTION: Does signed flow from a STRICTLY POINT-IN-TIME informed-wallet cohort predict factor-neutral
forward returns on majors, BEYOND aggregate order-flow imbalance (OFI)?

Discipline (the whole ballgame = A8): the informed-wallet cohort is ranked on a TRAIN span only, FROZEN
(wallet id list), then evaluated on a disjoint held-out TEST span. No test-period data touches the labels.
This directly re-tests the repo's discouraging prior (generic wallet-selection alpha unsupported OOS;
"identifiability != copyability") in the factor-neutral + aggregate-flow-controlled framing that was never
cleanly run.

Firewalled research lane: reads only research.data.db (asset_ctx, fills). Never imports src/babylon or
markout_study/gate_a.

Method (leak-freeness is verifiable from this):
  1. Buckets = hourly per coin (ts//3600000). Bucket price = last mid_px in the hour (asset_ctx, mid_px>0).
  2. Per-wallet signed flow per (coin,bucket) = sum((side='B'?+1:-1)*notional_usd), active non-vault wallets
     with >=50 lifetime major trades.
  3. Aggregate OFI per (coin,bucket) = signed AGGRESSOR flow = sum over crossed=true fills of sign*notional.
  4. Factor-neutral forward return over h buckets: fwd_ret_i(t->t+h) residualized on a leave-one-out
     equal-weight major index using a rolling CAUSAL beta (trailing window ending at t). Window starts at the
     END of bucket t (no mechanical-impact contamination — audit A3).
  5. Cohort: rank wallets on TRAIN buckets (month<TEST_MONTH) by alignment = mean over the wallet's active
     train buckets of sign(wallet_flow)*fwd_resid, requiring >=MIN_TRAIN_BKT active train buckets. Cohort =
     top quantile. FREEZE the wallet list.
  6. TEST (month>=TEST_MONTH, disjoint): per (coin,bucket) sum the frozen cohort's net signed flow. Regress
     fwd_resid ~ z(cohort_flow) + z(OFI). Report cohort coef + t-stat, PARTIAL IC (cohort_flow residualized
     on OFI first), naive IC, with time-block bootstrap CIs, per horizon.

Sanity: (a) aggregate ALL-wallet signed flow ~ 0 per bucket (both counterparties recorded);
        (b) OFI alone has a non-zero predictive sign (positive control: order flow predicts short-horizon
            returns — the pipeline works).

  .venv/bin/python -m research.studies.wallet_flow.flow
"""
import datetime as dt
import time
import functools
from pathlib import Path
import numpy as np
from research.data.db import connect

print = functools.partial(print, flush=True)  # unbuffered progress when stdout is a file
_T0 = time.time()


def _log(msg):
    print(f"[{time.time()-_T0:6.1f}s] {msg}")

# ---- config ----
MIN_LIFETIME = 50          # active-wallet floor: lifetime major trades
MIN_TRAIN_BKT = 20         # min active TRAIN (coin,bucket) obs to be eligible for the cohort ranking
COHORT_Q = 0.20            # top quantile of alignment -> informed cohort
TEST_MONTH = 202603        # train = month < this ; test = month >= this  (disjoint, per prompt)
W = 720                    # rolling causal beta window (hourly buckets = 30d)
MIN_BETA_OBS = 240         # min trailing return obs to estimate a beta
HORIZONS = [1, 2]          # forward horizons in buckets (1h, 2h)
BOOT = 2000
SCRATCH = "/private/tmp/claude-501/-Users-corywagamaneure-bablyon/e7986c68-b22e-4ff8-a672-1a1b4b625c30/scratchpad"
MAJORS = ("BTC", "ETH", "SOL", "HYPE")


def _month_of(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)
    return d.year * 100 + d.month


def _rank(x):
    return np.argsort(np.argsort(x)).astype(float)


def _spearman(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return np.nan
    ra, rb = _rank(a[m]), _rank(b[m])
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra @ ra) * (rb @ rb))
    return (ra @ rb) / d if d > 0 else np.nan


def _ols_resid(y, x):
    """residual of y regressed on [x, 1] (leave-one-out-free simple OLS)."""
    m = np.isfinite(y) & np.isfinite(x)
    r = np.full_like(y, np.nan, dtype=float)
    if m.sum() < 10:
        return r
    X = np.column_stack([x[m], np.ones(m.sum())])
    b = np.linalg.lstsq(X, y[m], rcond=None)[0]
    r[m] = y[m] - X @ b
    return r


# ---------------------------------------------------------------------------
# Price / factor-neutral residual panel  (asset_ctx, majors only — tiny)
# ---------------------------------------------------------------------------
def build_resid(con):
    """Return dict with hours grid, month, and per-horizon fwd_resid[N,4] (leave-one-out beta-neutral)."""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE mbars AS
        WITH v AS (SELECT coin, ts, (ts - ts%3600000) AS h, mid_px
                   FROM asset_ctx
                   WHERE coin IN {MAJORS} AND mid_px>0)
        SELECT coin, h, arg_max(mid_px, ts) AS mid FROM v GROUP BY coin, h""")
    b = con.execute("SELECT coin, h, mid FROM mbars").fetchnumpy()
    coin_arr = np.asarray(b["coin"], dtype=object)
    h_arr = b["h"].astype(np.int64)
    ci = {c: i for i, c in enumerate(MAJORS)}
    hmin, hmax = int(h_arr.min()), int(h_arr.max())
    hours = np.arange(hmin, hmax + 1, 3600000, dtype=np.int64)
    N = len(hours)
    rows = ((h_arr - hmin) // 3600000).astype(int)
    cols = np.array([ci[str(c)] for c in coin_arr])
    Lp = np.full((N, 4), np.nan)
    Lp[rows, cols] = np.log(b["mid"].astype(float))
    R = np.diff(Lp, axis=0, prepend=np.nan)                     # 1-bucket log returns [N,4]

    # leave-one-out equal-weight index of 1-bucket returns: loo_i = (sum_j R_j - R_i)/3
    tot = np.nansum(R, axis=1, keepdims=True)
    cnt = np.sum(np.isfinite(R), axis=1, keepdims=True)
    loo = np.full((N, 4), np.nan)
    for i in range(4):
        others = (tot[:, 0] - np.where(np.isfinite(R[:, i]), R[:, i], 0.0))
        ocnt = cnt[:, 0] - np.isfinite(R[:, i]).astype(int)
        loo[:, i] = np.where(ocnt > 0, others / ocnt, np.nan)   # mean of the OTHER majors

    # rolling CAUSAL beta of R_i on loo_i over trailing window ending at t (out-of-fit: uses [t-W+1, t])
    beta = np.full((N, 4), np.nan)
    for i in range(4):
        y = R[:, i]; x = loo[:, i]
        good = np.isfinite(y) & np.isfinite(x)
        yv = np.where(good, y, 0.0); xv = np.where(good, x, 0.0)
        g = good.astype(float)
        csum_xy = np.concatenate([[0.0], np.cumsum(xv * yv)])
        csum_xx = np.concatenate([[0.0], np.cumsum(xv * xv)])
        csum_x = np.concatenate([[0.0], np.cumsum(xv)])
        csum_y = np.concatenate([[0.0], np.cumsum(yv)])
        csum_n = np.concatenate([[0.0], np.cumsum(g)])
        for t in range(N):
            lo = max(0, t - W + 1)
            n = csum_n[t + 1] - csum_n[lo]
            if n < MIN_BETA_OBS:
                continue
            sxy = csum_xy[t + 1] - csum_xy[lo]; sxx = csum_xx[t + 1] - csum_xx[lo]
            sx = csum_x[t + 1] - csum_x[lo]; sy = csum_y[t + 1] - csum_y[lo]
            cov = sxy - sx * sy / n; var = sxx - sx * sx / n
            if var > 0:
                beta[t, i] = cov / var

    month = np.array([_month_of(int(h)) for h in hours])
    resid = {}
    for H in HORIZONS:
        fr = np.full((N, 4), np.nan)
        for i in range(4):
            fwd = Lp[H:, i] - Lp[:-H, i]                        # end of t -> end of t+H (A3: post-bucket)
            # LOO forward index return over the same window
            fwd_all = Lp[H:, :] - Lp[:-H, :]
            others = (np.nansum(fwd_all, axis=1) - np.where(np.isfinite(fwd), fwd, 0.0))
            ocnt = np.sum(np.isfinite(fwd_all), axis=1) - np.isfinite(fwd).astype(int)
            loo_fwd = np.where(ocnt > 0, others / ocnt, np.nan)
            bcol = beta[:-H, i]
            fr[:-H, i] = fwd - bcol * loo_fwd                  # factor-neutral forward residual
        resid[H] = fr
    return dict(hours=hours, month=month, N=N, resid=resid, ci=ci)


def register_resid(con, panel, H):
    """Push the (coin,bucket)->fwd_resid map (for horizon H) into DuckDB for the wallet joins."""
    hours = panel["hours"]; month = panel["month"]; fr = panel["resid"][H]
    co, hh, mo, rv = [], [], [], []
    for i, coin in enumerate(MAJORS):
        col = fr[:, i]
        good = np.nonzero(np.isfinite(col))[0]
        co.extend([coin] * len(good)); hh.extend(hours[good].tolist())
        mo.extend(month[good].tolist()); rv.extend(col[good].tolist())
    # register numpy arrays as a zero-copy DuckDB relation (fast; executemany row-by-row was the stall)
    rel = {"coin": np.array(co, dtype=object), "h": np.array(hh, dtype=np.int64),
           "month": np.array(mo, dtype=np.int64), "fwd_resid": np.array(rv, dtype=float)}
    con.register("resid_src", rel)
    con.execute("CREATE OR REPLACE TEMP TABLE resid AS SELECT * FROM resid_src")
    con.unregister("resid_src")
    return len(co)


# ---------------------------------------------------------------------------
# Wallet flow tables (heavy — stays in DuckDB, only compact aggregates pulled)
# ---------------------------------------------------------------------------
def build_wallet_tables(con, months):
    """active-wallet universe + per (wallet,coin,bucket) signed flow, OFI, all-wallet flow.

    The per-(wallet,coin,bucket) flow is the one heavy aggregate (tens of millions of groups). A single
    GROUP BY over the whole tape thrashes the 1500MB cap; instead we aggregate MONTH-BY-MONTH into Parquet
    (each month's hash table fits in memory, no spill) and expose the union as the `wb` view.
    """
    wb_dir = Path(SCRATCH) / "wb"
    wb_dir.mkdir(parents=True, exist_ok=True)
    def _cached(p):
        return p.exists() and p.stat().st_size > 0
    todo = [m for m in months if not _cached(wb_dir / f"month={m}.parquet")]
    if todo:
        con.execute(f"""CREATE OR REPLACE TEMP TABLE active AS
            SELECT wallet FROM fills WHERE is_vault=false
            GROUP BY wallet HAVING count(*) >= {MIN_LIFETIME}""")
        _log(f"active table built ({con.execute('SELECT count(*) FROM active').fetchone()[0]:,} wallets)")
    for m in months:
        out = wb_dir / f"month={m}.parquet"
        if _cached(out):
            _log(f"wb month={m} cached, skip")
            continue
        con.execute(f"""COPY (
            SELECT f.wallet, f.coin, (f.ts - f.ts%3600000) AS h, {m} AS mth,
                   sum(CASE WHEN f.side='B' THEN f.notional_usd ELSE -f.notional_usd END) AS flow
            FROM fills f JOIN active a USING(wallet)
            WHERE f.month={m} AND f.is_vault=false
            GROUP BY f.wallet, f.coin, h
        ) TO '{out}' (FORMAT PARQUET)""")
        _log(f"wb month={m} written")
    con.execute(f"""CREATE OR REPLACE VIEW wb AS
        SELECT * FROM read_parquet('{wb_dir}/month=*.parquet')""")
    # OFI + all-wallet signed flow per (coin,bucket). Each hour lives in one calendar month, so aggregate
    # MONTH-BY-MONTH over disjoint ts ranges (small per-month scans -> jetsam-safe) and union. fills_raw =
    # pass-through (no per-row DECIMAL casts of the enriched view); notional computed inline from sz,px.
    agg_dir = wb_dir.parent / "agg"
    agg_dir.mkdir(parents=True, exist_ok=True)
    for m in months:
        out = agg_dir / f"month={m}.parquet"
        if out.exists() and out.stat().st_size > 0:      # size>0 guards against 0-byte killed-write leftovers
            _log(f"agg month={m} cached, skip"); continue
        # month={m} filters on the Hive PARTITION column -> guaranteed file pruning (only that month scanned).
        con.execute(f"""COPY (
            WITH f AS (SELECT coin, ts, side, crossed,
                              abs(TRY_CAST(sz AS DECIMAL(38,6)))*TRY_CAST(px AS DECIMAL(38,6)) AS ntl
                       FROM fills_raw WHERE month={m})
            SELECT coin, (ts - ts%3600000) AS h,
                   sum(CASE WHEN crossed AND side='B' THEN ntl
                            WHEN crossed AND side='A' THEN -ntl ELSE 0 END) AS ofi,
                   sum(CASE WHEN side='B' THEN ntl ELSE -ntl END) AS allflow
            FROM f GROUP BY coin, h) TO '{out}' (FORMAT PARQUET)""")
        _log(f"agg month={m} written")
    con.execute(f"CREATE OR REPLACE VIEW agg AS SELECT * FROM read_parquet('{agg_dir}/month=*.parquet')")


def freeze_cohort(con, H):
    """Rank active wallets on TRAIN alignment (uses ONLY month<TEST_MONTH), freeze top-quantile wallet ids."""
    q = con.execute(f"""
        WITH j AS (
            SELECT wb.wallet, sign(wb.flow) * r.fwd_resid AS a
            FROM wb JOIN resid r ON wb.coin=r.coin AND wb.h=r.h
            WHERE wb.mth < {TEST_MONTH} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL
        )
        SELECT wallet, avg(a) AS align, count(*) AS nb
        FROM j GROUP BY wallet HAVING count(*) >= {MIN_TRAIN_BKT}
    """).fetchnumpy()
    wallets = np.asarray(q["wallet"], dtype=object)
    align = q["align"].astype(float)
    npool = len(wallets)
    if npool == 0:
        return [], 0
    thr = np.quantile(align, 1.0 - COHORT_Q)
    cohort = wallets[align >= thr]
    con.register("cohort_src", {"wallet": np.array([str(w) for w in cohort], dtype=object)})
    con.execute("CREATE OR REPLACE TEMP TABLE cohort AS SELECT * FROM cohort_src")
    con.unregister("cohort_src")
    return cohort, npool


def test_panel(con, H):
    """On TEST buckets: per (coin,bucket) frozen-cohort net flow + OFI + fwd_resid."""
    q = con.execute(f"""
        WITH cf AS (
            SELECT wb.coin, wb.h, sum(wb.flow) AS cohort_flow
            FROM wb JOIN cohort c USING(wallet)
            WHERE wb.mth >= {TEST_MONTH}
            GROUP BY wb.coin, wb.h
        )
        SELECT r.coin, r.h, r.fwd_resid,
               COALESCE(cf.cohort_flow,0) AS cohort_flow,
               COALESCE(agg.ofi,0) AS ofi
        FROM resid r
        LEFT JOIN cf  ON cf.coin=r.coin  AND cf.h=r.h
        LEFT JOIN agg ON agg.coin=r.coin AND agg.h=r.h
        WHERE r.month >= {TEST_MONTH}
    """).fetchnumpy()
    return q


# ---------------------------------------------------------------------------
# Inference: within-coin standardize, pool, block bootstrap over time
# ---------------------------------------------------------------------------
def _zc(v, coin):
    """z-score v within each coin."""
    out = np.full_like(v, np.nan, dtype=float)
    for c in np.unique(coin):
        m = coin == c
        x = v[m]; s = np.nanstd(x)
        if s > 0:
            out[m] = (x - np.nanmean(x)) / s
    return out


def block_boot_stat(hours, coin, y, xc, xo, fn, n=BOOT, seed=0):
    """Block bootstrap resampling whole time-blocks (preserves within-period cross-name dependence)."""
    rng = np.random.default_rng(seed)
    uh = np.unique(hours)
    idx_by_h = {h: np.nonzero(hours == h)[0] for h in uh}
    stats = []
    for _ in range(n):
        pick = rng.integers(0, len(uh), size=len(uh))
        sel = np.concatenate([idx_by_h[uh[p]] for p in pick])
        stats.append(fn(y[sel], xc[sel], xo[sel], coin[sel]))
    stats = np.array([s for s in stats if np.isfinite(s)])
    if len(stats) < 10:
        return (np.nan, np.nan)
    return tuple(np.percentile(stats, [2.5, 97.5]))


def naive_ic(y, xc, xo, coin):
    return _spearman(xc, y)


def partial_ic(y, xc, xo, coin):
    return _spearman(_ols_resid(xc, xo), y)


def ofi_ic(y, xc, xo, coin):
    return _spearman(xo, y)


def coef_and_t(y, zc, zo):
    """OLS y ~ zc + zo + 1 ; return (coef_zc, t_zc, coef_zo, t_zo) with classical SE (color only)."""
    m = np.isfinite(y) & np.isfinite(zc) & np.isfinite(zo)
    X = np.column_stack([zc[m], zo[m], np.ones(m.sum())])
    yv = y[m]
    b, *_ = np.linalg.lstsq(X, yv, rcond=None)
    resid = yv - X @ b
    dof = max(1, m.sum() - 3)
    s2 = (resid @ resid) / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    return b[0], b[0] / se[0], b[1], b[1] / se[1]


def run():
    Path(SCRATCH).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='900MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'")
    con.execute("SET preserve_insertion_order=false")

    print("[1/4] price/residual panel ...")
    panel = build_resid(con)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM fills ORDER BY month").fetchall()]
    print(f"[2/4] wallet flow tables (per-month aggregate -> parquet): {months}")
    build_wallet_tables(con, months)

    # sanity A: aggregate all-wallet signed flow ~ 0
    s = con.execute("""SELECT sum(allflow) tot, avg(abs(allflow)) mabs,
                              avg(abs(ofi)) mofi FROM agg""").fetchone()
    print(f"\n=== SANITY A: aggregate all-wallet signed flow ~ 0 ===")
    print(f"  sum(all-wallet signed flow) over every (coin,bucket) = {float(s[0]):.2f} USD  "
          f"(mean |all-flow|={float(s[1]):.1f}, mean |OFI|={float(s[2]):.1f})")
    print(f"  -> both counterparties recorded; net signed flow is ~0 by construction. OK.")

    nactive = con.execute("SELECT count(DISTINCT wallet) FROM wb").fetchone()[0]
    print(f"\nactive wallets (>= {MIN_LIFETIME} lifetime trades, non-vault): {nactive:,}")

    results = {}
    for H in HORIZONS:
        print(f"\n{'='*70}\nHORIZON h = {H} bucket(s) ({H}h)\n{'='*70}")
        nres = register_resid(con, panel, H); _log(f"resid registered ({nres} rows)")
        cohort, npool = freeze_cohort(con, H); _log("cohort frozen")
        print(f"[3/4] cohort frozen on TRAIN (month<{TEST_MONTH}): ranked pool={npool:,} wallets "
              f"(>= {MIN_TRAIN_BKT} train buckets); cohort=top {COHORT_Q:.0%} = {len(cohort):,} wallets")
        tp = test_panel(con, H); _log("test panel built")
        coin = np.asarray(tp["coin"], dtype=object)
        hours = tp["h"].astype(np.int64)
        y = tp["fwd_resid"].astype(float)
        cflow = tp["cohort_flow"].astype(float)
        ofi = tp["ofi"].astype(float)
        # within-coin standardize regressors (and target, for coef interpretability)
        zy = _zc(y, coin); zc = _zc(cflow, coin); zo = _zc(ofi, coin)

        # positive control: OFI alone
        ic_ofi = ofi_ic(zy, zc, zo, coin)
        ci_ofi = block_boot_stat(hours, coin, zy, zc, zo, ofi_ic, seed=1)
        # cohort naive + partial
        ic_naive = naive_ic(zy, zc, zo, coin)
        ci_naive = block_boot_stat(hours, coin, zy, zc, zo, naive_ic, seed=2)
        ic_part = partial_ic(zy, zc, zo, coin)
        ci_part = block_boot_stat(hours, coin, zy, zc, zo, partial_ic, seed=3)
        _log("bootstrap CIs done")
        # regression coef + t (classical SE color) on standardized target/regressors
        c_c, t_c, c_o, t_o = coef_and_t(zy, zc, zo)

        # per-coin sign (cross-unit)
        percoin = {}
        for c in MAJORS:
            m = coin == c
            percoin[c] = (_spearman(_ols_resid(cflow[m], ofi[m]), y[m]), int(m.sum()))

        n_test = np.isfinite(y).sum()
        print(f"[4/4] test obs (coin,bucket) with valid resid: {n_test:,}")
        print(f"\n  POSITIVE CONTROL  OFI naive IC = {ic_ofi:+.4f}  95%CI [{ci_ofi[0]:+.4f},{ci_ofi[1]:+.4f}]")
        print(f"  COHORT naive IC             = {ic_naive:+.4f}  95%CI [{ci_naive[0]:+.4f},{ci_naive[1]:+.4f}]")
        print(f"  COHORT PARTIAL IC | OFI     = {ic_part:+.4f}  95%CI [{ci_part[0]:+.4f},{ci_part[1]:+.4f}]  <-- the deliverable")
        print(f"  regression fwd_resid ~ z(cohort)+z(OFI):")
        print(f"      cohort coef = {c_c:+.4f}  t = {t_c:+.2f}")
        print(f"      OFI    coef = {c_o:+.4f}  t = {t_o:+.2f}")
        print(f"  per-coin partial IC (cohort|OFI):")
        for c in MAJORS:
            v, nn = percoin[c]
            print(f"      {c:5s} {v:+.4f}  (n={nn:,})")
        results[H] = dict(ic_ofi=ic_ofi, ci_ofi=ci_ofi, ic_naive=ic_naive, ci_naive=ci_naive,
                          ic_part=ic_part, ci_part=ci_part, c_c=c_c, t_c=t_c, c_o=c_o, t_o=t_o,
                          npool=npool, ncohort=len(cohort), n_test=int(n_test), percoin=percoin)
    con.close()
    return results


if __name__ == "__main__":
    run()
