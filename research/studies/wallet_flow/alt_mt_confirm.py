"""alt_mt_confirm — make-or-break robustness for the alt-complex TIMING signal (alt_markettiming found IC~0.05, z~4).

Two ways a big timing IC lies: (A) it's ONE regime (a single multi-day alt rotation in the 4-month TEST), or (B)
cohort tilt just echoes trailing alt-index momentum (autocorrelation), adding nothing forward. Kill both:
  1. WALK-FORWARD per test month (re-freeze cohort on cross-sectional alignment < m; placebo vs random) at H∈{1,4,8}
     on the BTC/ETH-neutral alt index. Consistent (4/4) or one regime?
  2. MOMENTUM CONTROL: partial correlation of tilt vs forward index, controlling for the TRAILING H-hour index
     return (causal). Does the informed edge survive removing momentum? Placebo too.
Optimized: global wallet int-encoding + per-cohort tilt computed ONCE per fold and reused across horizons.

    .venv/bin/python -m research.studies.wallet_flow.alt_mt_confirm
"""
from __future__ import annotations
import functools, time
import numpy as np
from math import comb
from research.data.db import connect
from research.studies.xsec_statarb.leadlag import rolling_beta
from research.studies.wallet_flow import alt_flow as A

print = functools.partial(print, flush=True)
_T0=time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}")
HS = (1, 4, 8); FOLDS = (202603, 202604, 202605, 202606); K = 300; KF = 200; SEED = 20260710
Wb, MINOBS = 720, 240


def _resid(x, z):
    m = np.isfinite(x) & np.isfinite(z); r = np.full_like(x, np.nan)
    if m.sum() < 30: return r
    Z = np.column_stack([z[m], np.ones(m.sum())]); b = np.linalg.lstsq(Z, x[m], rcond=None)[0]
    r[m] = x[m] - Z @ b; return r
def _spear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30: return np.nan
    ra = np.argsort(np.argsort(a[m])).astype(float); rb = np.argsort(np.argsort(b[m])).astype(float)
    ra -= ra.mean(); rb -= rb.mean(); d = np.sqrt((ra@ra)*(rb@rb)); return (ra@rb)/d if d>0 else np.nan
def _pcorr(x, y, z): return _spear(_resid(x, z), _resid(y, z))


def main():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{A.SCRATCH}/duck_mt2'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False); coins = list(A.FACTORS)+alts
    panel = A.build_resid(con, coins); A.build_cohort_tables(con, coins); A.register_resid(con, panel)
    hours, ci, N = panel["hours"], panel["ci"], panel["N"]; hmin = int(hours[0])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE hb3 AS WITH v AS (SELECT coin,ts,(ts-ts%3600000) h,mid_px
        FROM asset_ctx WHERE coin IN ('{"','".join(coins)}') AND mid_px>0
          AND day NOT IN ({",".join(str(d) for d in A.DROP_DAYS)}))
        SELECT coin,h,arg_max(mid_px,ts) mid FROM v GROUP BY coin,h""")
    d = con.execute("SELECT coin,h,mid FROM hb3").fetchnumpy()
    ca = np.asarray(d["coin"],dtype=object); ha = d["h"].astype(np.int64); C=len(coins)
    Lp = np.full((N,C), np.nan); rr=((ha-hmin)//3600000).astype(int); cc=np.array([ci[str(x)] for x in ca])
    ok=(rr>=0)&(rr<N); Lp[rr[ok],cc[ok]]=np.log(d["mid"].astype(float)[ok]); R=np.diff(Lp,axis=0,prepend=np.nan)
    btc,eth = R[:,ci["BTC"]], R[:,ci["ETH"]]; eth_o = eth-rolling_beta(eth,btc,Wb,MINOBS)*btc
    idx = np.nanmean(R[:,[ci[c] for c in alts]],axis=1)
    idx = idx-rolling_beta(idx,btc,Wb,MINOBS)*btc; idx = idx-rolling_beta(idx,eth_o,Wb,MINOBS)*eth_o
    cs = np.where(np.isfinite(idx),idx,0.0)
    def fwd(H):
        o=np.full(N,np.nan); [o.__setitem__(h,cs[h+1:h+1+H].sum()) for h in range(N-H)]; return o
    def trail(H):
        o=np.full(N,np.nan); [o.__setitem__(h,cs[max(0,h-H+1):h+1].sum()) for h in range(N)]; return o

    rows = con.execute("SELECT wb.wallet,wb.h,wb.mth,wb.flow FROM awb wb WHERE wb.flow<>0").fetchnumpy()
    rw=np.asarray([str(x) for x in rows["wallet"]],dtype=object); rh=rows["h"].astype(np.int64)
    rmth=rows["mth"].astype(np.int64); rf=rows["flow"].astype(float); hour_of=((rh-hmin)//3600000).astype(int)
    g=(hour_of>=0)&(hour_of<N); rw,rmth,rf,hour_of = rw[g],rmth[g],rf[g],hour_of[g]
    uniq_w, rw_code = np.unique(rw, return_inverse=True); U=len(uniq_w)
    wcode = {w:i for i,w in enumerate(uniq_w)}
    posr, negr = rf>0, rf<0
    _log(f"rows={len(rf):,} uniq wallets={U:,}")

    def freeze(before_m):
        emb = int(con.execute(f"SELECT min(h) FROM aresid WHERE month>={before_m}").fetchone()[0]) - A.H*3600000
        q = con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM awb wb
            JOIN aresid r ON wb.coin=r.coin AND wb.h=r.h WHERE wb.mth<{before_m} AND wb.h<{emb}
            AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
            SELECT wallet, avg(a) al FROM j GROUP BY wallet HAVING count(*)>={A.MIN_TRAIN_BKT}""").fetchnumpy()
        pool=np.asarray([str(x) for x in q["wallet"]],dtype=object); al=q["al"].astype(float)
        code2pool=np.full(U,-1,np.int64)
        for i,w in enumerate(pool):
            c=wcode.get(w,-1)
            if c>=0: code2pool[c]=i
        pio=code2pool[rw_code]                      # per-row pool index (-1 if not in pool), vectorized
        return pool, al, pio

    def tilt(pio, mask, hmask):
        valid = pio>=0; sel=np.zeros(len(pio),bool); sel[valid]=mask[pio[valid]]
        npos=np.bincount(hour_of[sel&posr],minlength=N).astype(float)
        nneg=np.bincount(hour_of[sel&negr],minlength=N).astype(float)
        den=npos+nneg; t=np.where(den>0,(npos-nneg)/np.maximum(den,1),np.nan); t[~hmask]=np.nan; return t

    print("=== (1) WALK-FORWARD: informed tilt→fwd neutral-alt-index, per month, vs random ===")
    rng=np.random.default_rng(SEED); fwH={H:fwd(H) for H in HS}
    perfold={}
    for m in FOLDS:
        pool,al,pio=freeze(m); ncoh=int(round(0.20*len(pool))); inf=al>=np.quantile(al,0.80)
        hmask=np.zeros(N,bool); hmask[np.unique(hour_of[rmth==m])]=True
        it=tilt(pio,inf,hmask)
        rts=[tilt(pio,_mkmask(rng,len(pool),ncoh),hmask) for _ in range(KF)]
        perfold[m]=(it,rts); _log(f"fold {m} tilts done (pool={len(pool):,})")
    for H in HS:
        zs=[]
        for m in FOLDS:
            it,rts=perfold[m]; ici=_spear(it,fwH[H]); null=np.array([_spear(rt,fwH[H]) for rt in rts])
            mu,sd=np.nanmean(null),np.nanstd(null); z=(ici-mu)/sd if sd>0 else np.nan; zs.append(z)
            print(f"  H={H}h {m}: informed IC {ici:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}")
        zs=np.array(zs); npos=int((zs>0).sum()); ps=sum(comb(4,i) for i in range(npos,5))/16
        print(f"    -> H={H}h: {npos}/4 folds z>0, sign-p={ps:.3f}, mean z={zs.mean():+.2f}\n")

    print("=== (2) MOMENTUM CONTROL (full TEST, production cohort): tilt→fwd | trailing-H index return ===")
    pool,al,pio=freeze(A.TEST_MONTH); ncoh=int(round(0.20*len(pool))); inf=al>=np.quantile(al,0.80)
    hmask=np.zeros(N,bool); hmask[np.unique(hour_of[rmth>=A.TEST_MONTH])]=True
    it=tilt(pio,inf,hmask); rts=[tilt(pio,_mkmask(rng,len(pool),ncoh),hmask) for _ in range(K)]
    for H in HS:
        fw=fwH[H]; tr=trail(H); raw=_spear(it,fw); pc=_pcorr(it,fw,tr)
        null=np.array([_pcorr(rt,fw,tr) for rt in rts]); mu,sd=np.nanmean(null),np.nanstd(null)
        z=(pc-mu)/sd if sd>0 else np.nan; p=(1+np.sum(null>=pc))/(K+1)
        print(f"  H={H}h: raw IC {raw:+.4f}  |  momentum-controlled {pc:+.4f}  random {mu:+.4f}±{sd:.4f}  z={z:+.2f}  p={p:.4f}")


def _mkmask(rng, n, k):
    m=np.zeros(n,bool); m[rng.choice(n,k,replace=False)]=True; return m


if __name__ == "__main__":
    main()
