"""
export_xsec_cohort — freeze the DEPLOYABLE V-trail cross-sectional cohort for the forward paper follower.

Trains the V-trail skill weights on the FULL tape (all months, recency-gated to the last 2), keeps the top-1500
by weight (the pollable cohort validated in xsec_pollable_validate: retains +3.2-3.8 bp/hr maker, 7/7 folds), and
writes data/derived/xsec_book/cohort.json = { cohort wallet addresses, per-wallet skill weight W, the 45-alt PIT
universe, per-alt impact half-spread, as_of_hour_ms, shas }. The follower (xsec_book_main.py) loads this, polls
these wallets hourly, computes S_a = Σ_w W_w · q_trail_{w,a} live, and logs the signal + prices.

Monthly refresh: re-run (recency gate auto-rolls to the newest 2 tape months), scp cohort.json, restart the unit.
Run: .venv/bin/python -m research.studies.wallet_flow.export_xsec_cohort
"""
from __future__ import annotations
import time, json, hashlib
from pathlib import Path
import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

H_TRAIN = 4
N_COHORT = 1500
OUT = Path("data/derived/xsec_book"); DUCK_TMP = f"{A.SCRATCH}/duck_xs_export"


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
    N = panel["N"]; hmin = int(hours[0])
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    _log(f"universe {n_alt} alts")

    inlist = "('" + "','".join(alt_names) + "')"
    hs_rows = con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(mid_px,0)*1e4/2.0) hs
        FROM asset_ctx WHERE coin IN {inlist} AND month>=202603
          AND impact_ask_px>0 AND impact_bid_px>0 AND mid_px>0 GROUP BY coin""").fetchall()
    halfspread = {c: round(float(h), 3) for c, h in hs_rows}

    A.build_cohort_tables(con, coins)      # creates awb (wallet-bucket) + aagg used below
    # flow rows + q_trail (identical construction) + wallet<->wcode map
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
    U4 = S0.xsec_rank(S0.fwd_sum(resid, H_TRAIN), alt_cols)[:, alt_cols]
    u_row = U4[r, ccode]

    # TRAIN W on the FULL tape (all rows), recency-gated to the last 2 tape months (mirrors run_horizon's recipe)
    months = sorted(set(int(x) for x in np.unique(mth)))
    rm = tuple(months[-2:])
    rec = np.isin(mth, rm)
    kk = np.unique(wcode[rec].astype(np.int64) * (N + 100) + r[rec].astype(np.int64))
    elig_w = np.bincount((kk // (N + 100)).astype(np.int64), minlength=nW)
    elig = elig_w >= S0.MIN_RECENT_H
    tr = np.isfinite(u_row)
    wt, ut, qt = wcode[tr], u_row[tr], q_trail[tr]
    n_i = np.bincount(wt, minlength=nW).astype(float)
    g = np.bincount(wt, weights=qt * ut, minlength=nW) / np.where(n_i > 0, n_i, 1)
    lam = np.median(n_i[n_i > 0])
    theta = g * n_i / (n_i + lam)
    W = np.where((n_i >= S0.MIN_TRAIN_OBS) & elig, np.maximum(0.0, theta), 0.0)
    pos = np.nonzero(W > 0)[0]
    top = pos[np.argsort(W[pos])[::-1][:N_COHORT]]
    _log(f"W>0 pool {len(pos):,}; recency-gated (months {rm}); top-{N_COHORT} by W")

    # map wcode -> wallet address
    w2a = {int(wc): a for a, wc in con.execute("SELECT wallet, wcode FROM wid").fetchall()}
    cohort = {w2a[int(wc)]: round(float(W[wc]), 8) for wc in top}
    asof = int(hours[-1]) + 3600000            # first genuinely-OOS hour = after the last tape hour
    manifest = {"as_of_hour_ms": asof, "h_train": H_TRAIN, "n_cohort": len(cohort), "recent_months": list(rm),
                "min_recent_h": S0.MIN_RECENT_H, "univ_formation": A.UNIV_FORMATION,
                "universe": alt_names, "impact_halfspread_bp": halfspread,
                "book": {"type": "decile_long_short", "q1": 0.10, "q2": 0.15, "reb_hours": 4,
                         "predictor": "V-trail(trailing24h demean, size-blind)", "neutralization": "L2 offline"},
                "note": "S_a = sum_w W_w * q_trail_{w,a}; rank across active alts; decile L/S; PnL computed OFFLINE."}
    universe_sha = hashlib.sha256("|".join(alt_names).encode()).hexdigest()[:16]
    cohort_sha = hashlib.sha256("|".join(sorted(cohort)).encode()).hexdigest()[:16]
    manifest.update({"universe_sha": universe_sha, "cohort_sha": cohort_sha})
    (OUT / "cohort.json").write_text(json.dumps({"cohort_weights": cohort, **manifest}, indent=2))
    _log(f"wrote {OUT/'cohort.json'}  cohort_sha={cohort_sha} universe_sha={universe_sha} "
         f"n={len(cohort)} as_of={asof}")
    print("DONE.")


if __name__ == "__main__":
    run()
