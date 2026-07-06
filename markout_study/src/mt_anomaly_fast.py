import glob
from datetime import datetime, timezone
import numpy as np
import polars as pl

COINS = ["BTC","ETH","SOL","HYPE"]; BP=1e4
def ms(y,m,d): return int(datetime(y,m,d,tzinfo=timezone.utc).timestamp()*1000)
TRAIN_HI = ms(2026,2,1); TEST_LO = ms(2026,3,1)
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
ANOM = ['0x0ddf9bae2af4b874b96d287a5ad42eb47138a902','0x5fffee2555a15899ad656c1a80f1b35cd0b2c0c1',
        '0xb28cf8649d1cda2975d290f04ea4cc4db7b3828e','0x00c511ab1b583f4efab3608d0897d377c4de47a6',
        '0x95995f302ad58138d791ce49f9f3b1274e80c60a','0xff4cd3826ecee12acd4329aada4a2d3419fc463c',
        '0xb676a78f19227ffe9a97db93263fce675e547dbf','0xe056eebc2c7acfc782d47ebe18ad71735480f72a']

def closes_full(px, sz, ts, cr):
    q=avg=0.0; out=[]
    for p,s,t,c in zip(px,sz,ts,cr):
        if q==0.0 or (s>0)==(q>0):
            avg=(avg*abs(q)+p*abs(s))/(abs(q)+abs(s)); q+=s
        else:
            close=min(abs(s),abs(q))
            out.append((t, close*(p-avg)*(1.0 if q>0 else -1.0), close*p))
            nq=q+s
            if (nq>0)!=(q>0) and nq!=0.0: avg=p
            q=nq
            if abs(q)<1e-12: q=0.0; avg=0.0
    return out

def closes_taker(px, sz, ts, cr):
    m = cr.astype(bool)
    if not m.any(): return []
    px,sz,ts = px[m], sz[m], ts[m]
    return closes_full(px, sz, ts, np.ones(px.size, dtype=bool))  # reuse recurrence, cr unused inside

def stats(recs):
    if len(recs) < 5: return (len(recs), np.nan, np.nan, np.nan)
    r = np.array([x[1] for x in recs]); n_ = np.array([x[2] for x in recs])
    good = n_>0; r=r[good]; n_=n_[good]
    if r.size < 5: return (r.size, np.nan, np.nan, np.nan)
    bps = r/n_*BP
    mean=bps.mean(); sd=bps.std()
    t = mean/(sd/np.sqrt(bps.size)) if sd>0 else 0.0
    vw = r.sum()/n_.sum()*BP
    return bps.size, mean, t, vw

lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS)).filter(pl.col("wallet").is_in(ANOM))
df = lf.select("wallet","coin","ts","tid","px","sz","crossed").collect().sort(["ts","tid"])
print(f"rows fetched: {df.height}")

rows = []
for wal, g in df.group_by("wallet", maintain_order=True):
    wal = wal[0]
    trF=[]; teF=[]; trT=[]; teT=[]
    mk_n=tk_n=0; mk_v=tk_v=0.0
    for (coin,), gg in g.group_by(["coin"], maintain_order=True):
        gg = gg.sort(["ts","tid"])
        px=gg["px"].to_numpy(); sz=gg["sz"].to_numpy(); ts=gg["ts"].to_numpy(); cr=gg["crossed"].to_numpy()
        trm = ts < TRAIN_HI
        notl = (np.abs(sz)*px)
        crt = cr[trm]; notlt = notl[trm]
        mk_n += int((~crt).sum()); tk_n += int(crt.sum())
        mk_v += float(notlt[~crt].sum()); tk_v += float(notlt[crt].sum())
        for t,r,nn in closes_full(px,sz,ts,cr):
            if t < TRAIN_HI: trF.append((t,r,nn))
            elif t >= TEST_LO: teF.append((t,r,nn))
        for t,r,nn in closes_taker(px,sz,ts,cr):
            if t < TRAIN_HI: trT.append((t,r,nn))
            elif t >= TEST_LO: teT.append((t,r,nn))
    mkshare_v = mk_v/(mk_v+tk_v) if (mk_v+tk_v)>0 else np.nan
    ntrF,trF_m,trF_t,trF_vw = stats(trF); nteF,teF_m,teF_t,teF_vw = stats(teF)
    ntrT,trT_m,trT_t,trT_vw = stats(trT); nteT,teT_m,teT_t,teT_vw = stats(teT)
    rows.append((wal, mk_n+tk_n, mkshare_v, ntrF,trF_vw,trF_t, nteF,teF_vw,teF_t,
                 ntrT,trT_vw,trT_t, nteT,teT_vw,teT_t))

cols=["wallet","trN","mkshare_v","ntrF","trF_vw","trF_t","nteF","teF_vw","teF_t",
      "ntrT","trT_vw","trT_t","nteT","teT_vw","teT_t"]
R = pl.DataFrame(rows, schema=cols, orient="row")
with pl.Config(tbl_cols=20, tbl_rows=20, fmt_str_lengths=14):
    print(R)
R.write_parquet("out/mt_anomaly_fast.parquet")
