"""reconcile_oos_audit — OVER-NULL AUDIT of the alt-timing OOS z=0.07 vs prereg WF z=+2.0 discrepancy.

Reproduces the prereg's OWN test (recency-gated top-1500, audit-fixed alt-only scoring, per-fold walk-forward
@H1) using the SAME code path as the deployed dashboard (alt_timing_dashboard_data.py's OOS loop), but reports
PER-FOLD IC+z, a pooled day-block-bootstrap CI + MDE over just the 4 prereg folds, AND (for comparison) the
full dashboard TESTM pooled number — all from ONE consistent, audit-fixed (alt-only scoring/tilt) code path.

    .venv/bin/python -m research.studies.wallet_flow.reconcile_oos_audit
"""
from __future__ import annotations
import functools, time, warnings, json
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

SCRATCH = "/private/tmp/claude-501/-Users-corywagamaneure-bablyon/565ad9b7-d53e-409a-abe5-66918970dbf0/scratchpad/duck_reconcile"
A.SCRATCH = SCRATCH

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

Wb, MINOBS = 720, 240
N_PLACEBO = 60
SEED = 20260710
MIN_RECENT_H = 40
NSEL_OOS = 1500
FOLDS = (202603, 202604, 202605, 202606)     # the prereg's own 4 test folds
HOUR = 3600000


def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30: return np.nan
    ra = np.argsort(np.argsort(a[m])).astype(float); rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean(); d = np.sqrt((ra @ ra) * (rb @ rb)); return (ra @ rb) / d if d > 0 else np.nan


def _prev(m):
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


def _rand_mask(rng, npool, nsel):
    mm = np.zeros(npool, bool); mm[rng.choice(npool, min(nsel, npool), replace=False)] = True; return mm


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False); coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0]); hh = hours.astype(np.int64)
    days = (hours // 86400000).astype(np.int64)
    _log(f"panel ready N={N} coins={len(coins)}")

    months = [int(r[0]) for r in con.execute("SELECT DISTINCT mth FROM awb ORDER BY mth").fetchall()]
    print(f"ALL awb months: {months}")
    TESTM_DASH = months[4:]
    print(f"dashboard TESTM = months[4:] = {TESTM_DASH}")
    print(f"prereg FOLDS = {list(FOLDS)}  (subset of dashboard TESTM: {set(FOLDS) <= set(TESTM_DASH)})")

    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64); C = len(coins)
    Lp = np.full((N, C), np.nan); rr = ((ha - hmin) // HOUR).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok]); R = np.diff(Lp, axis=0, prepend=np.nan)
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]; eth_o = eth - rolling_beta(eth, btc, Wb, MINOBS) * btc
    idx = np.nanmean(R[:, [ci[c] for c in alts]], axis=1)
    idx = idx - rolling_beta(idx, btc, Wb, MINOBS) * btc; idx = idx - rolling_beta(idx, eth_o, Wb, MINOBS) * eth_o
    cs = np.where(np.isfinite(idx), idx, 0.0)
    fwd1 = np.array([cs[h + 1] if h < N - 1 else np.nan for h in range(N)])
    _log("index/fwd ready")

    inlist = "('" + "','".join(alts) + "')"
    rng = np.random.default_rng(SEED)

    def run_fold(m):
        """Returns dict with informed tilt, IC, z, t, plus the full placebo drawmat (N_PLACEBO x N) for this fold."""
        ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={m}").fetchone()[0])
        emb = ms_cut - HOUR
        fmask = np.isfinite(fwd1) & (hh < emb)
        con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": fwd1[fmask].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
        sc = con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb
                WHERE mth<{m} AND coin NOT IN ('BTC','ETH') GROUP BY wallet,h)
            SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
            WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>=20""").fetchnumpy()
        wal_m = np.asarray([str(x) for x in sc["wallet"]], dtype=object); score_m = sc["score"].astype(float)
        r1, r2 = _prev(_prev(m)), _prev(m)
        act = con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({r1},{r2}) AND coin IN {inlist}
            GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
        active = set(str(x[0]) for x in act)
        elig = np.array([w in active for w in wal_m]); wal_e = wal_m[elig]; sc_e = score_m[elig]
        if len(wal_e) < NSEL_OOS:
            print(f"  fold {m}: SKIP (elig {len(wal_e)} < {NSEL_OOS})"); return None
        cohort_m = set(wal_e[np.argsort(-sc_e)[:NSEL_OOS]])
        con.register("elig_arr", {"wallet": wal_e.astype(object)})
        fr = con.execute(f"""SELECT wb.wallet, wb.h, sign(wb.flow) s FROM awb wb JOIN elig_arr e USING(wallet)
            WHERE wb.mth={m} AND wb.flow<>0 AND wb.coin NOT IN ('BTC','ETH')""").fetchnumpy(); con.unregister("elig_arr")
        fw_ = np.asarray([str(x) for x in fr["wallet"]], dtype=object)
        fh = ((fr["h"].astype(np.int64) - hmin) // HOUR).astype(int); fs = fr["s"].astype(np.int64)
        uwm, wcm = np.unique(fw_, return_inverse=True); kk = (fh >= 0) & (fh < N); fh, fs, wcm = fh[kk], fs[kk], wcm[kk]

        def fold_tilt(wmask):
            sel = wmask[wcm]
            npo = np.bincount(fh[sel & (fs > 0)], minlength=N).astype(float)
            nne = np.bincount(fh[sel & (fs < 0)], minlength=N).astype(float)
            den = npo + nne; return np.where(den > 0, (npo - nne) / den, np.nan)

        cm = np.array([w in cohort_m for w in uwm]); ft = fold_tilt(cm)
        mh = np.isfinite(ft) & np.isfinite(fwd1); n_eff = int(mh.sum())
        ic = _spear(ft, fwd1)
        drawmat = np.full((N_PLACEBO, N), np.nan)
        draws_ic = np.empty(N_PLACEBO)
        for j in range(N_PLACEBO):
            rt = fold_tilt(_rand_mask(rng, len(uwm), NSEL_OOS))
            drawmat[j] = rt; draws_ic[j] = _spear(rt, fwd1)
        mu, sd = float(np.nanmean(draws_ic)), float(np.nanstd(draws_ic))
        z = (ic - mu) / sd if sd > 0 else float("nan")
        t0 = ic * np.sqrt(max(n_eff - 3, 1))
        print(f"  fold {m}: elig {len(wal_e):,} cohort {len(cohort_m)} n_eff_h {n_eff} "
              f"IC {ic:+.4f} z_vs_random {z:+.2f} t_vs_zero {t0:+.2f}")
        return dict(ic=float(ic), z=float(z), t_vs_zero=float(t0), n_eff=n_eff, elig=len(wal_e),
                    cohort=len(cohort_m), placebo_mu=mu, placebo_sd=sd, tilt=ft, mask=mh, drawmat=drawmat)

    print(f"\n=== PER-FOLD (prereg's own 4 folds, N=1500, alt-only audit-fixed scoring/tilt) ===")
    res = {}
    for m in FOLDS:
        r = run_fold(m)
        if r is not None: res[m] = r
    _log("prereg 4-fold done")

    order_ms = [m for m in FOLDS if m in res]
    zs = np.array([res[m]["z"] for m in order_ms]); ics = np.array([res[m]["ic"] for m in order_ms])
    npos = int((zs > 0).sum())
    print(f"\nPer-fold z: {[round(float(z),2) for z in zs]}")
    print(f"Per-fold IC: {[round(float(x),4) for x in ics]}")
    print(f"mean z = {zs.mean():+.2f}   {npos}/{len(zs)} folds positive (sign test)")

    # ---- pooled IC + day-block bootstrap CI + pooled paired-draw z, across the 4 prereg folds ----
    tilt_pool = np.full(N, np.nan)
    drawmat_pool = np.full((N_PLACEBO, N), np.nan)
    for m in order_ms:
        tilt_pool[res[m]["mask"]] = res[m]["tilt"][res[m]["mask"]]
        mm = np.isfinite(res[m]["drawmat"])
        drawmat_pool[mm] = res[m]["drawmat"][mm]
    pool_mask = np.isfinite(tilt_pool) & np.isfinite(fwd1)
    ic_pool = _spear(tilt_pool, fwd1); n_eff_pool = int(pool_mask.sum())
    pool_draw_ic = np.array([_spear(drawmat_pool[j], fwd1) for j in range(N_PLACEBO)])
    mu_p, sd_p = float(np.nanmean(pool_draw_ic)), float(np.nanstd(pool_draw_ic))
    z_pool = (ic_pool - mu_p) / sd_p if sd_p > 0 else float("nan")
    t_pool = ic_pool * np.sqrt(max(n_eff_pool - 3, 1))

    def dbCI_ic(tilt_arr, mask):
        ud = np.unique(days[mask]); idx = [np.nonzero((days == dd) & mask)[0] for dd in ud]
        rngc = np.random.default_rng(11); st = []
        for _ in range(600):
            sidx = np.concatenate([idx[i] for i in rngc.integers(0, len(ud), len(ud))])
            st.append(_spear(tilt_arr[sidx], fwd1[sidx]))
        st = np.array([v for v in st if np.isfinite(v)])
        return np.percentile(st, [2.5, 97.5]), len(ud)
    (lo, hi), n_days = dbCI_ic(tilt_pool, pool_mask)
    print(f"\nPOOLED (4 prereg folds only): IC {ic_pool:+.4f}  day-block-CI[{lo:+.4f},{hi:+.4f}] (n_days={n_days})  "
          f"n_eff_h={n_eff_pool}  t_vs_zero={t_pool:+.2f}  z_vs_random(pooled paired draws)={z_pool:+.2f}")

    # ---- MDE: analytic (Fisher) + empirical (placebo sd) at 80% power, one-sided alpha=0.05 ----
    z_a, z_b = 1.645, 0.8416
    mde_fisher = (z_a + z_b) / np.sqrt(max(n_eff_pool - 3, 1))
    mde_empirical = (z_a + z_b) * sd_p
    print(f"\nMDE (IC units, 80% power, 1-sided a=0.05): analytic(Fisher, n_eff={n_eff_pool}) = {mde_fisher:.4f} "
          f"| empirical(placebo sd) = {mde_empirical:.4f}")
    print(f"observed pooled IC = {ic_pool:+.4f} -> {'>= MDE' if abs(ic_pool) >= mde_fisher else '< MDE (underpowered zone)'}")

    # ---- reference: FULL dashboard TESTM pooled (sanity check vs ic.json's +0.0045/z=0.07 headline) ----
    print(f"\n=== reference: FULL dashboard TESTM ({len(TESTM_DASH)} months) pooled H1 (same audit-fixed code) ===")
    res_full = {}
    for m in TESTM_DASH:
        r = run_fold(m)
        if r is not None: res_full[m] = r
    tilt_full = np.full(N, np.nan); drawmat_full = np.full((N_PLACEBO, N), np.nan)
    for m in res_full:
        tilt_full[res_full[m]["mask"]] = res_full[m]["tilt"][res_full[m]["mask"]]
        mm = np.isfinite(res_full[m]["drawmat"]); drawmat_full[mm] = res_full[m]["drawmat"][mm]
    full_mask = np.isfinite(tilt_full) & np.isfinite(fwd1)
    ic_full = _spear(tilt_full, fwd1); n_full = int(full_mask.sum())
    draw_ic_full = np.array([_spear(drawmat_full[j], fwd1) for j in range(N_PLACEBO)])
    mu_f, sd_f = float(np.nanmean(draw_ic_full)), float(np.nanstd(draw_ic_full))
    z_full = (ic_full - mu_f) / sd_f if sd_f > 0 else float("nan")
    print(f"FULL-TESTM pooled IC={ic_full:+.4f}  n_eff_h={n_full}  z_vs_random={z_full:+.2f}  "
          f"(dashboard headline reference: informed +0.0045, z_vs_random +0.07)")
    print(f"per-month z, full TESTM: " + " ".join(f"{m}:{res_full[m]['z']:+.1f}" for m in res_full))

    summary = {
        "all_months": months, "dashboard_TESTM": TESTM_DASH, "prereg_folds": list(FOLDS),
        "per_fold_4": {str(m): {k: v for k, v in res[m].items() if k not in ("tilt", "mask", "drawmat")} for m in res},
        "per_fold_full": {str(m): {k: v for k, v in res_full[m].items() if k not in ("tilt", "mask", "drawmat")} for m in res_full},
        "pooled_4fold": {"ic": float(ic_pool), "ci95_dayblock": [float(lo), float(hi)], "n_days": int(n_days),
                          "n_eff_hours": n_eff_pool, "t_vs_zero": float(t_pool), "z_vs_random_pooled": float(z_pool)},
        "mde_ic_80pct_power": {"fisher_analytic": float(mde_fisher), "empirical_placebo_sd": float(mde_empirical)},
        "full_dashboard_testm": {"ic": float(ic_full), "n_eff_hours": n_full, "z_vs_random": float(z_full)},
    }
    outp = "/Users/corywagamaneure/bablyon/data/derived/alt_timing/reconcile_oos_audit.json"
    with open(outp, "w") as f: json.dump(summary, f, indent=2)
    print(f"\nwrote {outp}")


if __name__ == "__main__":
    main()
