"""
Does OOS persistence STRENGTHEN with sample size? — testing the intuition that a few very-high-N, consistently
positive-markout wallets genuinely persist and are being drowned by small-N winner's-curse noise in the aggregate.
Also: is the t-stat inflated by autocorrelation (raw-N vs effective/day-clustered N)?

Split = Stage E: TRAIN Aug'25-Jan'26 / EMBARGO Feb / TEST Mar-Jun'26. Per-entry dir-signed 24h markout (post-fill,
leak-free). Per (wallet,coin): train N, edge, raw t-stat, DAY-clustered (effective-N) t-stat; test edge.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]; H24 = 24 * 3_600_000; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1); TEST_LO = _ms(2026, 3, 1)


def main():
    rng = np.random.default_rng(7)
    lk = _load_bars()
    parts = []
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        e = _next_bar_close_vec(L, bt); x = _next_bar_close_vec(L, bt + H24)
        with np.errstate(all="ignore"): fwd = x / e - 1.0
        fwd[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter(pl.col("coin") == c).select("wallet", "b_ts", "dir").collect())
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(np.float64)
        i = np.clip(np.searchsorted(bt, b), 0, bt.size - 1)
        mk = d * fwd[i]
        day = (b // 86_400_000)
        parts.append(ec.with_columns(pl.Series("coin", [c] * ec.height), pl.Series("mk", mk),
                                     pl.Series("day", day)).filter(pl.col("mk").is_finite()))
    E = pl.concat(parts)
    # winsorize per-entry markout at train p99.5 magnitude (tames the "one huge lucky trade" the user flagged)
    cap = float(np.nanpercentile(np.abs(E.filter(pl.col("b_ts") < TRAIN_HI)["mk"].to_numpy()), 99.5))
    E = E.with_columns(pl.col("mk").clip(-cap, cap))
    tr = E.filter(pl.col("b_ts") < TRAIN_HI); te = E.filter(pl.col("b_ts") >= TEST_LO)

    # ---- train stats per (wallet,coin): raw + day-clustered (effective-N) ----
    trd = tr.group_by("wallet", "coin", "day").agg(dmk=pl.col("mk").mean())   # day means
    tr_day = trd.group_by("wallet", "coin").agg(
        nday=pl.len(), edge_day=pl.col("dmk").mean(), sd_day=pl.col("dmk").std())
    tr_raw = tr.group_by("wallet", "coin").agg(
        n=pl.len(), edge=pl.col("mk").mean(), sd=pl.col("mk").std())
    trs = tr_raw.join(tr_day, on=["wallet", "coin"]).with_columns(
        t_raw=pl.col("edge") / (pl.col("sd") / pl.col("n").sqrt()),
        t_eff=pl.col("edge_day") / (pl.col("sd_day") / pl.col("nday").sqrt()))
    tes = te.group_by("wallet", "coin").agg(n_test=pl.len(), edge_test=pl.col("mk").mean())
    W = trs.join(tes, on=["wallet", "coin"], how="left")   # left: keep train wallets even if test-inactive

    print(f"{'='*82}\nHIGH-N PERSISTENCE — does OOS edge persistence strengthen with sample size?\n{'='*82}")
    print(f"train wallet-coins: {W.height} | with >=1 test entry: {W.filter(pl.col('n_test').is_not_null()).height}")

    # ---- persistence by N bin: does train_edge predict test_edge better for large N? ----
    Wt = W.filter(pl.col("n_test").is_not_null() & (pl.col("n_test") >= 10))
    bins = [(30, 100), (100, 300), (300, 1000), (1000, 10**9)]
    print(f"\n{'N_train bin':14s} {'#wallets':>8s} {'corr(train,test)edge':>20s} {'top-tstat-quintile test edge (bps)':>34s}")
    for lo, hi in bins:
        s = Wt.filter((pl.col("n") >= lo) & (pl.col("n") < hi))
        if s.height < 20:
            print(f"{f'[{lo},{hi})':14s} {s.height:>8d}   (too few)"); continue
        tr_e = s["edge"].to_numpy(); te_e = s["edge_test"].to_numpy()
        corr = np.corrcoef(tr_e, te_e)[0, 1]
        # top quintile by EFFECTIVE t-stat within the bin -> their mean test edge
        thr = np.nanpercentile(s["t_eff"].to_numpy(), 80)
        top = s.filter(pl.col("t_eff") >= thr)
        print(f"{f'[{lo},{hi})':14s} {s.height:>8d} {corr:>20.3f} {top['edge_test'].mean()*BP:>28.1f}  (n={top.height})")

    # ---- the user's subset: very-high-N, well-estimated-positive (effective t), do THEY persist? ----
    print(f"\n{'-'*82}\nWELL-ESTIMATED subset (n_train>=500 AND effective t_eff>=2): do they persist OOS?")
    hi = Wt.filter((pl.col("n") >= 500) & (pl.col("t_eff") >= 2.0))
    if hi.height:
        te_e = hi["edge_test"].to_numpy() * BP
        # null: random wallets matched on n_test count
        rand = Wt.filter(pl.col("n") >= 500).sample(min(hi.height * 20, Wt.filter(pl.col('n')>=500).height), seed=7)
        print(f"  {hi.height} wallet-coins qualify. test edge: mean {np.nanmean(te_e):+.1f} bps, "
              f"median {np.nanmedian(te_e):+.1f}, %positive {100*np.mean(te_e>0):.0f}%")
        print(f"  null (all n>=500 wallets) test edge: mean {rand['edge_test'].mean()*BP:+.1f}, "
              f"%positive {100*(rand['edge_test']>0).mean():.0f}%")
    else:
        print("  none qualify (n>=500 & t_eff>=2).")

    # ---- raw vs effective t-stat: how much is autocorrelation inflating the 'stars'? ----
    print(f"\n{'-'*82}\nt-stat INFLATION by autocorrelation (raw-N vs day-clustered effective-N):")
    topraw = W.filter(pl.col("n") >= 200).sort("t_raw", descending=True).head(200)
    print(f"  top-200 by RAW t-stat (n>=200): median raw t = {topraw['t_raw'].median():.2f}, "
          f"median EFFECTIVE t = {topraw['t_eff'].median():.2f}  "
          f"(shrink {topraw['t_raw'].median()/max(topraw['t_eff'].median(),1e-9):.1f}x)")
    print(f"  median trades/day for these = {(topraw['n']/topraw['nday']).median():.1f}  "
          f"(high => trades are autocorrelated => raw t-stat overstated)")

    # ---- individual: the actual candidate wallets (well-estimated, persist, plausibly copyable) ----
    cand = Wt.filter((pl.col("n") >= 300) & (pl.col("t_eff") >= 2.0) & (pl.col("edge_test") > 0)).sort(
        "t_eff", descending=True).head(15)
    print(f"\n{'-'*82}\nTop candidate wallets (n_train>=300, effective t>=2, POSITIVE test edge) — {cand.height} shown:")
    print(cand.select("coin", pl.col("n"), pl.col("nday"), (pl.col("edge") * BP).round(1).alias("tr_edge_bp"),
                      pl.col("t_raw").round(1), pl.col("t_eff").round(1),
                      pl.col("n_test"), (pl.col("edge_test") * BP).round(1).alias("te_edge_bp")))
    W.write_parquet(OUT / "highn_persistence.parquet")
    print(f"\n-> out/highn_persistence.parquet")


if __name__ == "__main__":
    main()
