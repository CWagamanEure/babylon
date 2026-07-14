"""alt_agg_maker_focus — follow-up on the (e) maker-only-tilt standout from alt_agg_compare.py: per-fold
breakdown + day-block bootstrap CI (CLAUDE.md gate: CI + per-fold combination, not just a pooled z).

    .venv/bin/python -m research.studies.wallet_flow.alt_agg_maker_focus
"""
from __future__ import annotations
import functools, warnings, json, time
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")

Wb, MINOBS = 720, 240
N_PLACEBO_OOS = 60
SEED = 20260711
MINH = 20
MIN_RECENT_H = 40
RECENT_MONTHS = (202605, 202606)
HOUR = 3600000
OUT = Path("data/derived/alt_timing/agg_compare")
COH = Path("data/derived/alt_timing/cohort.json")


def _spear(a, b): return A._spear(a, b)
def _prev(m):
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo
def _rand_mask(rng, npool, nsel):
    mm = np.zeros(npool, bool); mm[rng.choice(npool, min(nsel, npool), replace=False)] = True; return mm


def main():
    cfg = json.loads(COH.read_text())
    cohort = list(cfg["cohort"])
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_aggcmp'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False); coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0]); hh = hours.astype(np.int64)
    days = (hours // 86400000).astype(np.int64)
    _log(f"panel ready N={N}")

    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64); C = len(coins)
    Lp = np.full((N, C), np.nan); rr = ((ha - hmin) // 3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok]); R = np.diff(Lp, axis=0, prepend=np.nan)
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]; eth_o = eth - rolling_beta(eth, btc, Wb, MINOBS) * btc
    def neutral(cols):
        s = np.nanmean(R[:, [ci[c] for c in cols]], axis=1)
        s = s - rolling_beta(s, btc, Wb, MINOBS) * btc
        return s - rolling_beta(s, eth_o, Wb, MINOBS) * eth_o
    idx = neutral(alts); cs = np.where(np.isfinite(idx), idx, 0.0)
    fwd1 = np.array([cs[h + 1] if h < N - 1 else np.nan for h in range(N)])

    inlist = "('" + "','".join(alts) + "')"; rm = ",".join(str(m) for m in RECENT_MONTHS)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE elig AS SELECT wallet FROM alt_flow
        WHERE month IN ({rm}) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""")
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT mth FROM awb ORDER BY mth").fetchall()]
    TESTM = months[4:]; NSEL_OOS = min(len(cohort), 1500)
    print(f"TESTM: {TESTM}")

    maker_tilt = np.full(N, np.nan); rnd_maker = np.full((N_PLACEBO_OOS, N), np.nan)
    fold_res = []
    rng = np.random.default_rng(SEED)
    for m in TESTM:
        ms_cut = int(con.execute(f"SELECT min(h) FROM awb WHERE mth={m}").fetchone()[0]); emb = ms_cut - HOUR
        fmask = np.isfinite(fwd1) & (hh < emb)
        con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": fwd1[fmask].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
        sc = con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb
                WHERE mth<{m} AND coin NOT IN ('BTC','ETH') GROUP BY wallet,h)
            SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
            WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
        wal_m = np.asarray([str(x) for x in sc["wallet"]], dtype=object); score_m = sc["score"].astype(float)
        r1, r2 = _prev(_prev(m)), _prev(m)
        act = con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({r1},{r2}) AND coin IN {inlist}
            GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
        active = set(str(x[0]) for x in act)
        elig = np.array([w in active for w in wal_m]); wal_e = wal_m[elig]; sc_e = score_m[elig]
        if len(wal_e) < NSEL_OOS: continue
        cohort_m = set(wal_e[np.argsort(-sc_e)[:NSEL_OOS]])
        con.register("elig_arr", {"wallet": wal_e.astype(object)})
        mt_q = con.execute(f"""SELECT wallet, coin, (bucket-bucket%3600000) h, crossed, sum(flow_signed) f
            FROM alt_flow WHERE month={m} AND coin IN {inlist} AND wallet IN (SELECT wallet FROM elig_arr)
            GROUP BY wallet, coin, h, crossed""").fetchnumpy()
        con.unregister("elig_arr")
        mw = np.asarray([str(x) for x in mt_q["wallet"]], dtype=object)
        mh_ = ((mt_q["h"].astype(np.int64) - hmin) // 3600000).astype(int)
        mcr = np.asarray(mt_q["crossed"], dtype=bool); mf = mt_q["f"].astype(float)
        kk = (mh_ >= 0) & (mh_ < N); mw, mh_, mcr, mf = mw[kk], mh_[kk], mcr[kk], mf[kk]
        uwm2, wcm2 = np.unique(mw, return_inverse=True)

        def mt_tilt(mask):                                    # maker only (crossed=False)
            sel = mask[wcm2] & (~mcr) & (mf != 0)
            npo = np.bincount(mh_[sel & (mf > 0)], minlength=N).astype(float)
            nne = np.bincount(mh_[sel & (mf < 0)], minlength=N).astype(float)
            den = npo + nne; return np.where(den > 0, (npo - nne) / den, np.nan)

        cm2 = np.array([w in cohort_m for w in uwm2]); ft = mt_tilt(cm2)
        fmh = np.isfinite(ft) & np.isfinite(fwd1); n_eff = int(fmh.sum())
        fic = _spear(ft, fwd1)
        drawmat = np.full((N_PLACEBO_OOS, N), np.nan); draws_ic = np.empty(N_PLACEBO_OOS)
        wal_e_idxset = wal_e
        for j in range(N_PLACEBO_OOS):
            rmask_full = _rand_mask(rng, len(wal_e), NSEL_OOS)
            wal_e_sel = set(wal_e_idxset[rmask_full])
            rmask2 = np.array([w in wal_e_sel for w in uwm2])
            rt = mt_tilt(rmask2); drawmat[j] = rt; draws_ic[j] = _spear(rt, fwd1)
        mu, sd = float(np.nanmean(draws_ic)), float(np.nanstd(draws_ic))
        fz = (fic - mu) / sd if sd > 0 else float("nan")
        print(f"  fold {m}: elig {len(wal_e):,} cohort {len(cohort_m)} n_eff_h {n_eff} "
              f"maker-IC {fic:+.4f} z_vs_random {fz:+.2f}")
        fold_res.append({"month": m, "ic": float(fic), "z": float(fz), "n_eff": n_eff})
        maker_tilt[fmh] = ft[fmh]
        dm = np.isfinite(drawmat); rnd_maker[dm] = drawmat[dm]

    zs = np.array([f["z"] for f in fold_res]); npos = int((zs > 0).sum())
    print(f"\nper-fold z: {[round(float(z),2) for z in zs]}  mean={zs.mean():+.2f}  {npos}/{len(zs)} positive")

    pool_mask = np.isfinite(maker_tilt) & np.isfinite(fwd1)
    ic_pool = _spear(maker_tilt, fwd1); n_eff_pool = int(pool_mask.sum())
    pool_draw_ic = np.array([_spear(rnd_maker[j], fwd1) for j in range(N_PLACEBO_OOS)])
    mu_p, sd_p = float(np.nanmean(pool_draw_ic)), float(np.nanstd(pool_draw_ic))
    z_pool = (ic_pool - mu_p) / sd_p if sd_p > 0 else float("nan")
    t_pool = ic_pool * np.sqrt(max(n_eff_pool - 3, 1))

    def dbCI(tilt_arr, mask):
        ud = np.unique(days[mask]); idx = [np.nonzero((days == dd) & mask)[0] for dd in ud]
        rngc = np.random.default_rng(11); st = []
        for _ in range(1000):
            sidx = np.concatenate([idx[i] for i in rngc.integers(0, len(ud), len(ud))])
            st.append(_spear(tilt_arr[sidx], fwd1[sidx]))
        st = np.array([v for v in st if np.isfinite(v)])
        return np.percentile(st, [2.5, 97.5]), len(ud)
    (lo, hi), n_days = dbCI(maker_tilt, pool_mask)

    z_a, z_b = 1.645, 0.8416
    mde_fisher = (z_a + z_b) / np.sqrt(max(n_eff_pool - 3, 1))
    mde_empirical = (z_a + z_b) * sd_p

    print(f"\nPOOLED (7-month, same window as dashboard/baseline): maker-only IC {ic_pool:+.4f}  "
          f"day-block-CI[{lo:+.4f},{hi:+.4f}] (n_days={n_days})  n_eff_h={n_eff_pool}  "
          f"t_vs_zero={t_pool:+.2f}  z_vs_random(pooled)={z_pool:+.2f}")
    print(f"MDE (80% power, 1-sided a=0.05): fisher={mde_fisher:.4f}  empirical(placebo sd)={mde_empirical:.4f}")
    print(f"observed IC {ic_pool:+.4f} vs MDE -> {'>= MDE (powered)' if abs(ic_pool) >= mde_fisher else '< MDE (still underpowered by Fisher)'}")

    out = {"fold_res": fold_res, "pooled": {"ic": float(ic_pool), "n_eff": n_eff_pool,
           "ci95_dayblock": [float(lo), float(hi)], "n_days": int(n_days), "t_vs_zero": float(t_pool),
           "z_vs_random_pooled": float(z_pool), "mde_fisher": float(mde_fisher), "mde_empirical": float(mde_empirical)}}
    (OUT / "maker_focus.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {OUT}/maker_focus.json")


if __name__ == "__main__":
    main()
