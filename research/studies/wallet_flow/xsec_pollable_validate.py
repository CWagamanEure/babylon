"""
xsec_pollable_validate — does the V-trail decile MAKER positive survive concentration to a POLLABLE cohort?

A live follower can poll ~1500 wallets/hour, not the ~7k with W>0. Concentrating a breadth signal can kill it
(the alt-timing top-150 went dormant exactly this way). Before building the follower we MUST confirm the top-K-by-
skill-weight cohort retains the maker positive from the concentrated book (Result 10). Reuses run_horizon's NEW
`topk_by_w` (keeps only the top-K wallets by frozen train-W) + the concentrated-book simulator/scenarios.

Run: .venv/bin/python -m research.studies.wallet_flow.xsec_pollable_validate
"""
from __future__ import annotations
import time, json
from pathlib import Path
import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

H_TRAIN = 4
REB = 4
KS = (None, 2500, 1500, 1000)     # None = full W>0 baseline
OUT = Path("data/derived/xsec_pollable_validate")
DUCK_TMP = f"{A.SCRATCH}/duck_xs_poll"
SHOW = ("taker_top_smallclip", "maker_earn_a30", "maker_earn_a50")


def run():
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins)
    resid, hours, ci = panel["resid"], panel["hours"], panel["ci"]
    panel_month = panel["month"]; N = panel["N"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    LAG_ac = S0.trailing_resid_mom(resid)[:, alt_cols]
    _log(f"resid ({N}h, {n_alt} alts)")

    inlist = "('" + "','".join(alt_names) + "')"
    hs_rows = con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(mid_px,0)*1e4/2.0) hs
        FROM asset_ctx WHERE coin IN {inlist} AND month>=202603
          AND impact_ask_px>0 AND impact_bid_px>0 AND mid_px>0 GROUP BY coin""").fetchall()
    hs_by_name = {c: float(h) for c, h in hs_rows}
    halfspread = {i: hs_by_name.get(alt_names[i], 3.25) for i in range(n_alt)}
    hs_default = float(np.median(list(hs_by_name.values())))

    A.build_cohort_tables(con, coins)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    acx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS SELECT wallet,(row_number() OVER (ORDER BY wallet))-1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h-{hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.flow>0 THEN 1 WHEN wb.flow<0 THEN -1 ELSE 0 END AS s
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin WHERE wb.flow<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); s = rows["s"].astype(np.int8)
    keep = (r >= 0) & (r < N); wcode, ccode, r, mth, s = wcode[keep], ccode[keep], r[keep], mth[keep], s[keep]
    del rows
    _q, q_trail = ADJ.build_q_fixed(wcode, r, s.astype(np.float64), N)
    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    U4 = S0.xsec_rank(S0.fwd_sum(resid, H_TRAIN), alt_cols)[:, alt_cols]

    full_set = set(range(n_alt))
    res = {"reb": REB, "book": "decile pooled", "impact_hs_median_bp": hs_default, "by_K": {}}
    print("\n============ POLLABILITY: pooled decile maker book vs cohort size K (reb=4) ============")
    for K in KS:
        _log(f"train V-trail topk={K} ...")
        R, Cc, Uc, Smat = S0.run_horizon(H_TRAIN, wcode, ccode, r, mth, q_trail, U4, LAG_ac, nW, folds,
                                         first_row, (CROWD, LAG_ac, np.zeros((N, n_alt))),
                                         do_placebos=False, seed=S0.SEED, topk_by_w=K)
        Smat = Smat.astype(np.float32)
        crowd = CROWD[R, Cc].copy(); lag = LAG_ac[R, Cc].copy()
        for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
        s_inf = S0.residualize(Smat[:, :1], np.column_stack([crowd, lag]), R)[:, 0].astype(np.float64)
        xs_by = {}
        for i in range(len(R)):
            if not np.isfinite(s_inf[i]): continue
            t = int(R[i]); xs_by.setdefault(t, ([], [])); xs_by[t][0].append(int(Cc[i])); xs_by[t][1].append(s_inf[i])
        xs_arr = {t: (np.array(v[0]), np.array(v[1])) for t, v in xs_by.items()}
        hour_month = {int(t): int(panel_month[t]) for t in xs_arr}
        all_hours = np.array(sorted(xs_arr), dtype=np.int64)
        FVr = S0.fwd_sum(resid, REB)[:, alt_cols]
        fvb = {t: {int(nm): float(FVr[t, nm]) * 1e4 for nm in xs_arr[t][0]} for t in xs_arr}
        elig = {t: full_set for t in xs_arr}
        sim = CB.simulate_raw(all_hours, xs_arr, fvb, halfspread, hs_default, REB, 0.10, 0.15, elig)
        hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
        entry = {"n_steps": int(len(hrs)), "gross_bp_per_hr": float((sim["gross"] / REB).mean()),
                 "mean_turnover": float(sim["turn"].mean()), "scenarios": {}}
        for lab, mult, fee, mode in CB.SCENARIOS:
            netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
            ci95 = CB._dayblock_ci(netph, hrs, hours)
            pf = {int(m): float(netph[shm == m].mean()) for m in sorted(set(shm.tolist()))}
            st = ADJ.sign_test([v for v in pf.values()])
            entry["scenarios"][lab] = {"net": float(netph.mean()), "ci95": ci95,
                                       "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                       "n_folds": len(pf), "sign_p": st["p"]}
        res["by_K"][str(K)] = entry
        klab = "FULL" if K is None else f"K={K}"
        print(f"  {klab:7s} gross {entry['gross_bp_per_hr']:+.3f}/hr turn {entry['mean_turnover']:.2f} n={entry['n_steps']}")
        for lab in SHOW:
            sc = entry["scenarios"][lab]; c = sc["ci95"]
            print(f"      {lab:20s} net {sc['net']:+.3f}/hr CI[{c[0]:+.3f},{c[1]:+.3f}] "
                  f"folds {sc['folds_pos']}/{sc['n_folds']}+ signp {sc['sign_p']:.3f}")
        del Smat, s_inf

    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    print("\nDONE.")


if __name__ == "__main__":
    run()
