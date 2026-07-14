"""alt_mt_steelman — STEELMAN pass for the alt-complex-timing signal (lean, disk-safe rebuild).

Reconstructs the audited walk-forward OOS pipeline (same scoring/embargo/recency-gate logic as
alt_timing_dashboard_data.py) but queries `alt_flow` DIRECTLY (no month-cached parquet materialization —
the earlier version's 2.4GB /private/tmp cache got wiped mid-run by macOS's low-disk-space purge on this
99%-full machine; direct queries avoid any multi-GB persistent temp state).

Scope (narrowed for disk/time safety): NSEL=1500 (the deployed/prereg cohort size) only. Two subsets:
"recent4" (202603-202606, the EXACT window the prereg's "z~+2.0, 3/4 folds" claim was measured on) and
"all7" (202512-202606, the dashboard's window, for a same-script sanity cross-check against ic.json).
H in (1,4,8), target = the full alt-index (matches ic.json's estimand).

    .venv/bin/python -m research.studies.wallet_flow.alt_mt_steelman
"""
from __future__ import annotations
import functools, warnings, json, time, datetime
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

HS = (1, 4, 8)
NSEL = 1500
N_PLACEBO = 30
MINH = 20
MIN_RECENT_H = 40
SEED = 20260711
HOUR = 3600000
OUT = Path("data/derived/alt_timing/steelman")
TESTM_RECENT4 = (202603, 202604, 202605, 202606)


def _prev(m):
    y, mo = divmod(m, 100); mo -= 1
    return (y - 1) * 100 + 12 if mo == 0 else y * 100 + mo


def _rand_mask(rng, npool, nsel):
    mm = np.zeros(npool, bool); mm[rng.choice(npool, min(nsel, npool), replace=False)] = True; return mm


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1200MB'; SET threads=1")
    Path("data/derived/alt_timing/_ducktmp").mkdir(parents=True, exist_ok=True)
    con.execute("SET temp_directory='data/derived/alt_timing/_ducktmp'")   # repo disk, NOT /private/tmp (macOS purges tmp under disk pressure — bit us twice)
    con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False); coins = list(A.FACTORS) + alts
    _log(f"universe: {len(alts)} alts")
    panel = A.build_resid(con, coins)
    _log("resid panel built (no cohort-table cache — querying alt_flow directly)")
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0]); hh = hours.astype(np.int64)

    cfg = json.loads(Path("data/derived/alt_timing/cohort.json").read_text())
    basket = list(cfg["basket"])

    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca = np.asarray(d["coin"], dtype=object); ha = d["h"].astype(np.int64); C = len(coins)
    Lp = np.full((N, C), np.nan); rr = ((ha - hmin) // 3600000).astype(int); cc = np.array([ci[str(x)] for x in ca])
    ok = (rr >= 0) & (rr < N); Lp[rr[ok], cc[ok]] = np.log(d["mid"].astype(float)[ok]); R = np.diff(Lp, axis=0, prepend=np.nan)
    btc, eth = R[:, ci["BTC"]], R[:, ci["ETH"]]; eth_o = eth - rolling_beta(eth, btc, 720, 240) * btc

    def neutral(cols):
        s = np.nanmean(R[:, [ci[c] for c in cols]], axis=1)
        s = s - rolling_beta(s, btc, 720, 240) * btc
        return s - rolling_beta(s, eth_o, 720, 240) * eth_o
    idx = neutral(alts)
    cs_idx = np.where(np.isfinite(idx), idx, 0.0)
    fwH_idx = {H: np.array([cs_idx[h+1:h+1+H].sum() if h < N-H else np.nan for h in range(N)]) for H in HS}
    inlist = "('" + "','".join(alts) + "')"

    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM alt_flow ORDER BY month").fetchall()]
    TESTM_ALL = months[4:]
    _log(f"months {months} -> TESTM_ALL {TESTM_ALL}")

    rng = np.random.default_rng(SEED)
    oos_tilt = np.full(N, np.nan)
    rnd_series = np.full((N_PLACEBO, N), np.nan)
    fold_n_elig = {}

    for m in TESTM_ALL:
        t_fold0 = time.time()
        ms_cut = int(con.execute(f"""SELECT min((bucket - bucket%3600000)) FROM alt_flow
            WHERE month={m} AND coin IN {inlist}""").fetchone()[0])
        emb = ms_cut - HOUR
        fmask = np.isfinite(fwH_idx[1]) & (hh < emb)
        con.register("fsrc", {"hms": hh[fmask].astype(np.int64), "fwd": fwH_idx[1][fmask].astype(float)})
        con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
        # score wallets on ALT-only signed flow, train < m (direct query on alt_flow, no wb cache)
        sc = con.execute(f"""WITH wh AS (SELECT wallet, (bucket - bucket%3600000) h, sum(flow_signed) nf
                FROM alt_flow WHERE month<{m} AND coin IN {inlist} GROUP BY wallet, h)
            SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score FROM wh JOIN ftab f ON wh.h=f.hms
            WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
        wal_m = np.asarray([str(x) for x in sc["wallet"]], dtype=object); score_m = sc["score"].astype(float)
        r1, r2 = _prev(_prev(m)), _prev(m)
        act = con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({r1},{r2}) AND coin IN {inlist}
            GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
        active = set(str(x[0]) for x in act)
        elig = np.array([w in active for w in wal_m]); wal_e = wal_m[elig]; sc_e = score_m[elig]
        fold_n_elig[m] = len(wal_e)
        n_eligible = len(wal_e)
        if n_eligible < NSEL:
            _log(f"fold {m}: SKIP, only {n_eligible} eligible"); continue
        order = np.argsort(-sc_e)
        con.register("elig_arr", {"wallet": wal_e.astype(object)})
        fr = con.execute(f"""SELECT wb.wallet, (wb.bucket - wb.bucket%3600000) h, sign(wb.flow_signed) s
            FROM alt_flow wb JOIN elig_arr e USING(wallet)
            WHERE wb.month={m} AND wb.flow_signed<>0 AND wb.coin IN {inlist}""").fetchnumpy(); con.unregister("elig_arr")
        fw_ = np.asarray([str(x) for x in fr["wallet"]], dtype=object)
        fh = ((fr["h"].astype(np.int64) - hmin) // 3600000).astype(int); fs = fr["s"].astype(np.int64)
        uwm, wcm = np.unique(fw_, return_inverse=True); kk = (fh >= 0) & (fh < N); fh, fs, wcm = fh[kk], fs[kk], wcm[kk]
        widx_e = {w: i for i, w in enumerate(wal_e)}
        uwm_rank = np.array([widx_e.get(w, -1) for w in uwm])

        def fold_tilt(wmask_e):
            wmask_u = np.zeros(len(uwm), bool)
            ok2 = uwm_rank >= 0
            wmask_u[ok2] = wmask_e[uwm_rank[ok2]]
            sel = wmask_u[wcm]
            npo = np.bincount(fh[sel & (fs > 0)], minlength=N).astype(float)
            nne = np.bincount(fh[sel & (fs < 0)], minlength=N).astype(float)
            den = npo + nne; return np.where(den > 0, (npo - nne) / den, np.nan)

        cmask_e = np.zeros(n_eligible, bool); cmask_e[order[:NSEL]] = True
        ft = fold_tilt(cmask_e); mh = np.isfinite(ft); oos_tilt[mh] = ft[mh]
        for j in range(N_PLACEBO):
            rmask_e = _rand_mask(rng, n_eligible, NSEL)
            rt = fold_tilt(rmask_e); rnd_series[j, mh] = rt[mh]
        con.execute("DROP TABLE IF EXISTS ftab")
        _log(f"fold {m}: elig {n_eligible:,}, wallets-in-tape {len(uwm):,}  ({time.time()-t_fold0:.1f}s)")

    # ---------------- evaluate (subset x horizon) combos ----------------
    def spear(a, b):
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() < 30: return np.nan, int(m.sum())
        ra = np.argsort(np.argsort(a[m])).astype(float); rb = np.argsort(np.argsort(b[m])).astype(float)
        ra -= ra.mean(); rb -= rb.mean(); d = np.sqrt((ra @ ra) * (rb @ rb))
        return float((ra @ rb) / d) if d > 0 else np.nan, int(m.sum())

    hour_month = np.array([int(datetime.datetime.utcfromtimestamp(hms/1000).strftime("%Y%m")) for hms in hh])
    SUBSETS = {"all7": set(TESTM_ALL), "recent4": set(TESTM_RECENT4)}

    results = []
    n_configs = 0
    for subset_name, subset_months in SUBSETS.items():
        smask = np.isin(hour_month, list(subset_months))
        for H in HS:
            n_configs += 1
            fw = fwH_idx[H]
            inf_ic, n_eff = spear(oos_tilt[smask], fw[smask])
            draws = np.array([spear(rnd_series[j][smask], fw[smask])[0] for j in range(N_PLACEBO)])
            draws = draws[np.isfinite(draws)]
            mu, sd = (float(np.nanmean(draws)), float(np.nanstd(draws))) if len(draws) else (np.nan, np.nan)
            z = (inf_ic - mu) / sd if sd and sd > 0 else np.nan
            t0 = inf_ic * np.sqrt(n_eff) if n_eff > 0 else np.nan
            results.append(dict(nsel=NSEL, subset=subset_name, target="alt_idx", H=H,
                                 informed_ic=inf_ic, placebo_mean=mu, placebo_std=sd,
                                 z_vs_random=z, t_vs_zero=t0, n_eff=n_eff, n_placebo_draws=int(len(draws))))

    results.sort(key=lambda r: (-(r["z_vs_random"] if np.isfinite(r["z_vs_random"]) else -999)))
    print(f"\n=== {n_configs} configs ===")
    print(f"{'subset':>8} {'H':>2} {'IC':>8} {'placebo_mu':>10} {'placebo_sd':>10} {'z_vs_rand':>10} {'t_vs_0':>8} {'n_eff':>6} {'n_draws':>7}")
    for r in results:
        print(f"{r['subset']:>8} {r['H']:>2} {r['informed_ic']:>+8.4f} {r['placebo_mean']:>+10.4f} "
              f"{r['placebo_std']:>10.4f} {r['z_vs_random']:>+10.3f} {r['t_vs_zero']:>+8.3f} {r['n_eff']:>6} {r['n_placebo_draws']:>7}")

    (OUT / "steelman_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {OUT}/steelman_results.json")
    print("fold eligibility counts:", fold_n_elig)


if __name__ == "__main__":
    main()
