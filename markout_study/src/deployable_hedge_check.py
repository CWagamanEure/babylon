"""
DECISIVE OVER-CLAIM CHECK. The top-decile coin-DAY-neut OOS edge is +67bp while RAW is ~+6bp — so +61bp
comes purely from subtracting the coin's day-average forward return. The task frames neut as "what a
beta-hedged copier captures." That is an ASSUMPTION. Two tests decide whether the +67bp is a deployable,
implementable P&L or a benchmark-construction artifact:

  (A) INDEX-BETA-HEDGED markout: bh = d*(fwd_coin - beta_c * fwd_index), index = EW majors basket, beta
      fit on TRAIN 5-min returns. This is a P&L a real market-neutral copier can actually book (short the
      index against each copied trade). If bh ~= +67 -> deployable. If bh ~= raw (~0) -> the coin-day-neut
      is NOT index-hedgeable and the +67 is an accounting artifact of an un-tradeable benchmark.
  (B) TEST-EPOCH sub-period stability: split TEST into two halves; is the top-decile edge positive in BOTH?
      (single-epoch fragility guard).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]
H24 = 24 * 3_600_000; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1); TEST_LO = _ms(2026, 3, 1); TEST_MID = _ms(2026, 5, 1)


def main():
    rng = np.random.default_rng(20260705)
    lk = _load_bars()
    # ---- shared 5-min grid across majors (intersect bar-times) to build an EW index ----
    bts = {c: lk[c][0].astype(np.int64) for c in COINS}
    common = set(bts["BTC"])
    for c in COINS[1:]:
        common &= set(bts[c])
    gt = np.array(sorted(common), dtype=np.int64)
    px = {}
    for c in COINS:
        L = lk[c]; idx = np.searchsorted(L[0].astype(np.int64), gt)
        px[c] = L[1][idx].astype(np.float64)
    logr = {c: np.concatenate([[0.0], np.diff(np.log(px[c]))]) for c in COINS}
    def fwd24_series(price, t):
        j = np.clip(np.searchsorted(gt, t + H24), 0, gt.size - 1)
        with np.errstate(all="ignore"):
            return price[j] / price - 1.0
    # LEAVE-ONE-OUT index per coin (hedge each coin against the OTHER three) — avoids self-inclusion
    # deflating the hedge (audit note); this is the FAIR / steelman hedge for the positive.
    trm = gt < TRAIN_HI; beta = {}; idx_fwd_loo = {}
    for c in COINS:
        others = [o for o in COINS if o != c]
        ilr = np.mean([logr[o] for o in others], axis=0)
        ipx = np.exp(np.cumsum(ilr))
        idx_fwd_loo[c] = fwd24_series(ipx, gt)
        a = logr[c][trm]; b = ilr[trm]; ok = np.isfinite(a) & np.isfinite(b)
        beta[c] = float(np.cov(a[ok], b[ok])[0, 1] / np.var(b[ok]))
    print(f"per-coin beta to leave-one-out index (train): " + "  ".join(f"{c} {beta[c]:.2f}" for c in COINS))

    # ---- build per-entry: raw, coin-day-neut, index-beta-hedged 24h markout ----
    parts = []
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        e = _next_bar_close_vec(L, bt); x = _next_bar_close_vec(L, bt + H24)
        with np.errstate(all="ignore"): fwd = x / e - 1.0
        fwd[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
        day = bt // 86_400_000
        bg = pl.DataFrame({"d": day, "f": fwd}).filter(pl.col("f").is_finite())
        dmean = dict(zip(*bg.group_by("d").agg(pl.col("f").mean()).to_dict(as_series=False).values()))
        # leave-one-out index fwd aligned to THIS coin's entry bars
        gi = np.clip(np.searchsorted(gt, bt), 0, gt.size - 1)
        idxf_coin = idx_fwd_loo[c][gi]
        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter(pl.col("coin") == c).select("wallet", "b_ts", "dir").collect())
        b = ec["b_ts"].to_numpy(); dd = ec["dir"].to_numpy().astype(np.float64)
        i = np.clip(np.searchsorted(bt, b), 0, bt.size - 1)
        raw = dd * fwd[i]
        eday = b // 86_400_000
        dben = np.array([dmean.get(k, np.nan) for k in eday])
        neut = raw - dd * dben
        bh = dd * (fwd[i] - beta[c] * idxf_coin[i])                # index-beta-hedged P&L (bookable)
        parts.append(ec.with_columns(pl.Series("coin", [c]*ec.height), pl.Series("raw", raw),
                                     pl.Series("neut", neut), pl.Series("bh", bh)))
    E = pl.concat(parts)
    trn = E.filter(pl.col("b_ts") < TRAIN_HI)
    for col in ["raw", "neut", "bh"]:
        v = trn[col].to_numpy(); cap = float(np.nanpercentile(np.abs(v[np.isfinite(v)]), 99.5))
        E = E.with_columns(pl.col(col).clip(-cap, cap))
    E = E.filter(pl.col("raw").is_finite() & pl.col("neut").is_finite())

    # ---- re-derive the top decile exactly as deployable_edge.py (rank on train coin-day-neut t-stat) ----
    tr = E.filter(pl.col("b_ts") < TRAIN_HI)
    cl = tr.group_by("wallet", "coin", pl.col("b_ts")//86_400_000).agg(cm=pl.col("neut").mean())
    cls = cl.group_by("wallet").agg(ncl=pl.len(), cedge=pl.col("cm").mean(), csd=pl.col("cm").std())
    n = tr.group_by("wallet").agg(n=pl.len())
    W = n.join(cls, on="wallet").filter(pl.col("n") >= 300).with_columns(
        t_eff=pl.col("cedge")/(pl.col("csd")/pl.col("ncl").sqrt())).filter(pl.col("t_eff").is_finite())
    W = W.with_columns(((pl.col("t_eff").rank()-1)/pl.col("t_eff").len()*10).floor().clip(0,9).cast(pl.Int64).alias("dec"))
    topwall = set(W.filter(pl.col("dec") == 9)["wallet"].to_list())
    te = E.filter((pl.col("b_ts") >= TEST_LO) & pl.col("wallet").is_in(topwall) & pl.col("bh").is_finite())

    nm = lambda s: float(np.nanmean(s.to_numpy()))
    print(f"\n{'='*78}\n(A) DEPLOYABILITY: what a market-neutral copier can ACTUALLY book (top decile, {te.height} entries)")
    print(f"{'='*78}")
    print(f"  RAW markout (copy, no hedge)            : {nm(te['raw'])*BP:+.1f} bp")
    print(f"  coin-DAY-NEUT (the +67 headline metric) : {nm(te['neut'])*BP:+.1f} bp")
    print(f"  INDEX-BETA-HEDGED (bookable P&L)        : {nm(te['bh'])*BP:+.1f} bp   <-- the real hedged edge")
    # cluster CI (coin-week) on the bookable bh
    te = te.with_columns((pl.col("b_ts").cast(pl.Datetime("ms")).dt.week()).alias("wk"),
                         (pl.col("coin")+"_"+ (pl.col("b_ts")//(7*86_400_000)).cast(pl.Utf8)).alias("cw"))
    g = te.group_by("cw").agg(s=pl.col("bh").sum(), c=pl.len())
    s = g["s"].to_numpy(); cc = g["c"].to_numpy(); m = s.size
    bsamp = np.array([s[p].sum()/cc[p].sum() for p in (rng.integers(0,m,m) for _ in range(5000))])*BP
    print(f"  index-beta-hedged 95% CI (coin-week)    : [{np.percentile(bsamp,2.5):+.1f}, {np.percentile(bsamp,97.5):+.1f}] bp")
    mean_cost = float(np.mean([COST_BPS[c] for c in te['coin'].to_list()]))
    print(f"  mean cost {mean_cost:.1f}bp -> NET index-beta-hedged: {nm(te['bh'])*BP - mean_cost:+.1f} bp")
    print(f"\n  per-coin index-beta-hedged (bookable):")
    print(te.group_by("coin").agg(n=pl.len(), bh=(pl.col('bh').fill_nan(None).mean()*BP).round(1),
                                  neut=(pl.col('neut').fill_nan(None).mean()*BP).round(1),
                                  raw=(pl.col('raw').fill_nan(None).mean()*BP).round(1)).sort("coin"))

    # ---- (B) test-epoch sub-period stability ----
    print(f"\n{'='*78}\n(B) SINGLE-EPOCH GUARD: top-decile neut edge in each half of TEST")
    print(f"{'='*78}")
    for lab, sub in [("Mar-Apr", te.filter(pl.col("b_ts") < TEST_MID)),
                     ("May-Jun", te.filter(pl.col("b_ts") >= TEST_MID))]:
        print(f"  {lab}: n={sub.height:6d}  neut {nm(sub['neut'])*BP:+.1f}bp  "
              f"bh {nm(sub['bh'])*BP:+.1f}bp  raw {nm(sub['raw'])*BP:+.1f}bp")

    # ---- (C) MECHANISM: neut = raw - d*daymean ; the +61 comes from -d*daymean (day-drift-against-direction) ----
    te2 = te.with_columns((pl.col("neut") - pl.col("raw")).alias("mns_ddm"))   # = -d*daymean
    print(f"\n{'='*78}\n(C) MECHANISM — top-decile decomposition (neut = raw + (-d*daymean)):")
    print(f"{'='*78}")
    print(f"  mean RAW markout          : {nm(te['raw'])*BP:+.1f} bp  (the copyable component)")
    print(f"  mean (-d*coin_day_mean)    : {nm(te2['mns_ddm'])*BP:+.1f} bp  (the un-tradeable benchmark subtraction)")
    print(f"  => the headline neut edge is ~{100*nm(te2['mns_ddm'])/max(nm(te['neut']),1e-9):.0f}% a persistent")
    print(f"     lean-against-the-daily-drift STYLE, not bookable trade P&L.")


if __name__ == "__main__":
    main()
