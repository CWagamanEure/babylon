"""export_timing_cohort — freeze the live alt-complex-timing cohort + basket + config for the paper follower.

Ranks wallets by TIMING skill (hourly directional lean aligned with the forward BTC/ETH-neutral alt-index move) on
ALL available data, and exports the top-N pollable list + the tight tradeable basket + the book config. The follower
polls these wallets live, computes the tilt, and paper-trades — so any period AFTER the export's as-of date is a
genuine forward out-of-sample record. Re-run monthly to refresh (re-rank on the extended tape).

    .venv/bin/python -m research.studies.wallet_flow.export_timing_cohort
"""
from __future__ import annotations
import functools, warnings, json, hashlib
from pathlib import Path
import numpy as np
warnings.filterwarnings("ignore"); np.seterr(all="ignore")
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
# RECENCY GATE (fixes the dormant-cohort bug — mean-score top-150 was 13/150 live): eligibility = wallets active
# in the last 2 tape months (≥MIN_RECENT_H alt-hours), then top-N by timing score. Signal is a live BREADTH effect
# → N~1500 (recency-gated WF: top-1500 ≈ z+2 @H1, 3/4 folds; top-150 live ≈ z+0.5). Pollable ~1/sec → ~25min/sweep.
Wb, MINOBS = 720, 240; MINH = 20; N_COHORT = 1500; N_BACKUP = 2500; HS_MAX = 3.0; NBASK = 7
MIN_RECENT_H = 40; RECENT_MONTHS = (202605, 202606)
OUT = Path("data/derived/alt_timing")


def main():
    con=connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_ex'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts=A.universe(con,A.UNIV_FORMATION,include_majors=False); coins=list(A.FACTORS)+alts
    panel=A.build_resid(con,coins); A.build_cohort_tables(con,coins)
    hours,ci,N=panel["hours"],panel["ci"],panel["N"]; hmin=int(hours[0]); hh=hours.astype(np.int64)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hbe AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d=con.execute("SELECT coin,h,mid FROM hbe").fetchnumpy()
    ca=np.asarray(d["coin"],dtype=object); ha=d["h"].astype(np.int64); C=len(coins)
    Lp=np.full((N,C),np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth=R[:,ci["BTC"]],R[:,ci["ETH"]]; eth_o=eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    idx=np.nanmean(R[:,[ci[c] for c in alts]],axis=1)
    idx=idx-rolling_beta(idx,btc,Wb,MINOBS)*btc; idx=idx-rolling_beta(idx,eth_o,Wb,MINOBS)*eth_o
    cs=np.where(np.isfinite(idx),idx,0.0); fwd1=np.array([cs[h+1] if h<N-1 else np.nan for h in range(N)])

    # score on ALL available hours with a defined forward return
    fin=np.isfinite(fwd1)
    con.register("fsrc",{"hms":hh[fin].astype(np.int64),"fwd":fwd1[fin].astype(float)})
    con.execute("CREATE OR REPLACE TEMP TABLE ftab AS SELECT * FROM fsrc"); con.unregister("fsrc")
    sc=con.execute(f"""WITH wh AS (SELECT wallet,h,sum(flow) nf FROM awb GROUP BY wallet,h)
        SELECT wh.wallet, avg(sign(wh.nf)*f.fwd) score, count(*) nh FROM wh JOIN ftab f ON wh.h=f.hms
        WHERE wh.nf<>0 GROUP BY wh.wallet HAVING count(*)>={MINH}""").fetchnumpy()
    wal=np.asarray([str(x) for x in sc["wallet"]],dtype=object); score=sc["score"].astype(float)
    # RECENCY GATE: restrict the ranked pool to wallets active in the last RECENT_MONTHS (≥MIN_RECENT_H alt-hours).
    # Without this, mean-score selection picks wallets whose good-timing era was early and who have since churned out
    # (dry-run census: top-150-by-mean-score was 13/150 live). Recently-active wallets are ~93% still live.
    inlist="('"+"','".join(alts)+"')"; rm=",".join(str(m) for m in RECENT_MONTHS)
    act=con.execute(f"""SELECT wallet FROM alt_flow WHERE month IN ({rm}) AND coin IN {inlist}
        GROUP BY wallet HAVING count(DISTINCT (bucket - bucket%3600000)) >= {MIN_RECENT_H}""").fetchall()
    active=set(str(x[0]) for x in act)
    elig=np.array([w in active for w in wal]); wal_e=wal[elig]; score_e=score[elig]
    order=np.argsort(-score_e); cohort=[wal_e[i] for i in order[:N_COHORT]]; backup=[wal_e[i] for i in order[:N_BACKUP]]
    print(f"  recency gate: {len(wal_e):,} of {len(wal):,} scored wallets active in {RECENT_MONTHS} (≥{MIN_RECENT_H}h)")
    asof=int(hh[fin].max())

    # tight liquid basket + per-coin half-spread (as-of TRAIN liquidity)
    hsr=con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(impact_bid_px+impact_ask_px,0)*2*1e4) hs
        FROM asset_ctx WHERE coin IN ('{"','".join(alts)}') AND impact_bid_px>0 AND impact_ask_px>0
          AND day>={A.UNIV_FORMATION} GROUP BY coin""").fetchall()
    hsm={r[0]:float(r[1]) for r in hsr}
    basket=[c for c in alts if hsm.get(c,99)<=HS_MAX][:NBASK]

    manifest={
        "as_of_hour_ms": asof, "n_scored_pool": int(len(wal)),
        "cohort_size": N_COHORT, "config": {
            "signal": "aggregate breadth tilt (#long-#short)/#active over the alt universe, per hour",
            "smooth_hours": 8, "position": "sign(smoothed tilt)", "primary_horizon_h": 8,
            "target": "BTC/ETH-neutralized equal-weight tradeable basket return",
        },
        "basket": basket, "basket_half_spread_bp": {c: round(hsm[c],2) for c in basket},
        "hedge": list(A.FACTORS), "alt_universe": alts,
        "note": "PAPER ONLY. Forward test of the alt-complex-timing signal (FINDINGS Result 9). "
                "Cohort = top-N wallets by TIMING skill; any hour after as_of is genuine OOS.",
    }
    manifest["cohort_sha"] = hashlib.sha256(("|".join(sorted(cohort))).encode()).hexdigest()[:16]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/"cohort.json").write_text(json.dumps({"cohort": cohort, "backup_300": backup, **manifest}, indent=2))
    print(f"exported {OUT/'cohort.json'}")
    print(f"  as_of hour_ms={asof}  scored pool={len(wal):,}  cohort_sha={manifest['cohort_sha']}")
    print(f"  basket ({len(basket)}): {basket}  avg hs {np.mean([hsm[c] for c in basket]):.2f} bp")
    print(f"  top-5 scores: "+", ".join(f"{score_e[i]:.2e}" for i in order[:5]))
    print(f"  cohort[:3]: {cohort[:3]}")


if __name__=="__main__":
    main()
