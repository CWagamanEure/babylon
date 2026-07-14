"""PROSECUTE attacks 2,4,5,6 on the 993-wallet cohort (n_train>=300 & n_test>=20)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, polars as pl
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[1]
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
BP = 1e4
COST_BPS = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0, "SPX": 12.0}
H24 = 24 * 3_600_000; LAG = 15 * 60_000

E = pl.read_parquet(SCR / "prosecute_entries.parquet")
tr = E.filter(pl.col("split") == "train"); te = E.filter(pl.col("split") == "test")
trs = tr.group_by("wallet").agg(n=pl.len(), edge=pl.col("neut").mean())
tes = te.group_by("wallet").agg(n_test=pl.len(), edge_test=pl.col("neut").mean())
Wall = trs.join(tes, on="wallet", how="inner")
COH = Wall.filter((pl.col("n") >= 300) & (pl.col("n_test") >= 20))
cohort = set(COH["wallet"].to_list())
print(f"COHORT: {len(cohort)} wallets | baseline corr={np.corrcoef(COH['edge'],COH['edge_test'])[0,1]:.3f} "
      f"| mean test neut={COH['edge_test'].mean()*BP:+.1f}bp")

Ec = E.filter(pl.col("wallet").is_in(cohort))
trc = Ec.filter(pl.col("split") == "train"); tec = Ec.filter(pl.col("split") == "test")

def corr_report(tag, tr_df, te_df, col="neut"):
    a = tr_df.group_by("wallet").agg(e=pl.col(col).mean(), n=pl.len())
    b = te_df.group_by("wallet").agg(e=pl.col(col).mean(), n=pl.len())
    j = a.join(b, on="wallet", suffix="_te").filter((pl.col("n") >= 30) & (pl.col("n_te") >= 20))
    if j.height < 10:
        print(f"  {tag}: too few ({j.height})"); return
    x = j["e"].to_numpy() * BP; y = j["e_te"].to_numpy() * BP
    r = np.corrcoef(x, y)[0, 1]; rs = spearmanr(x, y).statistic
    print(f"  {tag:42s} N={j.height:>4} corr={r:+.3f} spear={rs:+.3f} meanTeEdge={y.mean():+6.1f}bp")
    return r

print("\n" + "="*90 + "\nATTACK 2 — INTRADAY TIMING (coin,hour-of-day,dir cell means removed)\n" + "="*90)
# cell = (coin,hour,dir); cell mean computed on TRAIN field-wide (all entries, not just cohort) to avoid leak
cell_tr = E.filter(pl.col("split") == "train").group_by("coin", "hour", "dir").agg(cm=pl.col("neut").mean())
Ec2 = Ec.join(cell_tr, on=["coin", "hour", "dir"], how="left").with_columns(
    resid=pl.col("neut") - pl.col("cm").fill_null(0.0))
# how much of cohort test edge is pure timing (predicted by cell means)?
tec2 = Ec2.filter(pl.col("split") == "test")
print(f"  cohort test: raw neut mean={tec2['neut'].mean()*BP:+.1f}bp | timing-predicted(cellmean)={tec2['cm'].mean()*BP:+.1f}bp "
      f"| residual(skill) mean={tec2['resid'].mean()*BP:+.1f}bp")
corr_report("baseline neut persistence", trc, tec, "neut")
corr_report("AFTER removing (coin,hour,dir) timing", Ec2.filter(pl.col('split')=='train'), tec2, "resid")

print("\n" + "="*90 + "\nATTACK 4 — OWN-IMPACT (restrict to SMALL-notional entries)\n" + "="*90)
# notional quartiles per coin from train
q = (trc.group_by("coin").agg(q25=pl.col("notl").quantile(0.25), q50=pl.col("notl").quantile(0.5)))
Ecq = Ec.join(q, on="coin", how="left")
small = Ecq.filter(pl.col("notl") <= pl.col("q50"))
tiny = Ecq.filter(pl.col("notl") <= pl.col("q25"))
print(f"  full cohort test neut={tec['neut'].mean()*BP:+.1f}bp")
print(f"  bottom-50% notional test neut={small.filter(pl.col('split')=='test')['neut'].mean()*BP:+.1f}bp")
print(f"  bottom-25% notional test neut={tiny.filter(pl.col('split')=='test')['neut'].mean()*BP:+.1f}bp")
corr_report("persistence, bottom-50% notional only", small.filter(pl.col('split')=='train'), small.filter(pl.col('split')=='test'))
corr_report("persistence, bottom-25% notional only", tiny.filter(pl.col('split')=='train'), tiny.filter(pl.col('split')=='test'))

print("\n" + "="*90 + "\nATTACK 5 — DIRECTION RESIDUAL (net long/short carrying it?)\n" + "="*90)
for tag, df in [("train", trc), ("test", tec)]:
    ws = df.group_by("wallet").agg(long_share=(pl.col("dir") == 1).mean(), edge=pl.col("neut").mean())
    ls = ws["long_share"].to_numpy(); ed = ws["edge"].to_numpy() * BP
    r = np.corrcoef(ls, ed)[0, 1]
    print(f"  {tag}: cohort long_share mean={ls.mean():.2f} | corr(long_share, neut_edge)={r:+.3f}")
# net-long tilt of cohort and whether it explains edge: split by directional bias
COHd = COH.join(trc.group_by("wallet").agg(long_share=(pl.col("dir")==1).mean()), on="wallet")
for lo, hi, lab in [(0.0, 0.4, "net-short"), (0.4, 0.6, "balanced"), (0.6, 1.01, "net-long")]:
    s = COHd.filter((pl.col("long_share") >= lo) & (pl.col("long_share") < hi))
    if s.height >= 10:
        print(f"  {lab:10s} ({s.height:>3} w): test neut={s['edge_test'].mean()*BP:+.1f}bp corr={np.corrcoef(s['edge'],s['edge_test'])[0,1]:+.3f}")

print("\n" + "="*90 + "\nATTACK 6 — COPYABILITY + COST (15-min lag, per-coin cost, funding)\n" + "="*90)
# funding: cumulative hourly rate per coin
fund = pl.read_parquet(ROOT.parent / "scratch_conv/mlscreen/funding.parquet").filter(
    pl.col("coin").is_in(["BTC", "ETH", "SOL", "HYPE"])).sort("coin", "time")
fmap = {}
for c in ["BTC", "ETH", "SOL", "HYPE"]:
    s = fund.filter(pl.col("coin") == c)
    t = s["time"].to_numpy(); r = s["rate"].to_numpy()
    fmap[c] = (t, np.concatenate([[0.0], np.cumsum(r)]))  # cum[i]=sum of first i rates
def fund_drag(coin, b_ts, dir_):
    t, cum = fmap[coin]
    lo = np.searchsorted(t, b_ts + LAG); hi = np.searchsorted(t, b_ts + LAG + H24)
    return dir_ * (cum[np.clip(hi, 0, len(cum)-1)] - cum[np.clip(lo, 0, len(cum)-1)])
rows = tec.select("coin", "b_ts", "dir", "neut", "neut_lag").to_dict(as_series=False)
fd = np.array([fund_drag(c, b, d) for c, b, d in zip(rows["coin"], rows["b_ts"], rows["dir"])])
cost = np.array([COST_BPS[c] / BP for c in rows["coin"]])
neut = np.array(rows["neut"]); neut_lag = np.array(rows["neut_lag"])
net = neut_lag - cost - fd
print(f"  cohort TEST entries: {len(net)}")
print(f"  gross neut (no lag)          = {neut.mean()*BP:+6.2f} bp")
print(f"  + 15-min lag                 = {np.nanmean(neut_lag)*BP:+6.2f} bp")
print(f"  - funding drag (mean)        = {(-fd.mean())*BP:+6.2f} bp  (funding paid mean {fd.mean()*BP:+.2f})")
print(f"  - round-trip cost            = {(-cost.mean())*BP:+6.2f} bp")
print(f"  = NET copyable neut edge     = {np.nanmean(net)*BP:+6.2f} bp")
# per coin net + bootstrap CI on pooled net (cluster by coin-day)
Enet = tec.with_columns(pl.Series("fd", fd), pl.Series("net", net), pl.Series("cd", [f"{c}_{b//86_400_000}" for c,b in zip(rows['coin'],rows['b_ts'])]))
print("  per-coin NET:", {c: round(float(Enet.filter(pl.col('coin')==c)['net'].mean()*BP),1) for c in ['BTC','ETH','SOL','HYPE']})
# cluster bootstrap CI by coin-day
cds = Enet["cd"].to_numpy(); netv = Enet["net"].to_numpy()
uc, inv = np.unique(cds, return_inverse=True)
rng = np.random.default_rng(3); boots = []
# precompute per-cluster sums
import collections
idx_by = collections.defaultdict(list)
for i, k in enumerate(inv): idx_by[k].append(i)
clist = [np.array(v) for v in idx_by.values()]
for _ in range(2000):
    pick = rng.integers(0, len(clist), len(clist))
    sel = np.concatenate([clist[p] for p in pick])
    boots.append(netv[sel].mean())
lo, hi = np.percentile(boots, [2.5, 97.5]) * BP
print(f"  pooled NET {netv.mean()*BP:+.2f}bp  95% CI [{lo:+.2f},{hi:+.2f}] (cluster=coin-day, {len(clist)} clusters)")
