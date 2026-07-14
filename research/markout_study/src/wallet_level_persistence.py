"""
WALLET-LEVEL (pooled across all majors) persistence — fixes the per-coin fragmentation that split good
diversified wallets into sub-threshold pieces. Each wallet's FULL major-coin record is pooled; effective-N
clusters by (coin,day) so same-day cross-coin bets count separately (not over-shrunk). Then: do high-N,
well-estimated (effective-t) wallets persist OOS — and WHO are they?

Split: TRAIN Aug'25-Jan'26 / EMBARGO Feb / TEST Mar-Jun'26. dir-signed 24h post-fill markout (leak-free).
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
    rng = np.random.default_rng(11)
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
        parts.append(ec.with_columns(pl.Series("mk", d * fwd[i]),
                                     pl.Series("cd", [f"{c}_{v}" for v in (b // 86_400_000)]))
                     .filter(pl.col("mk").is_finite()))
    E = pl.concat(parts)
    # light winsor at p99.9 (kill only extreme fat-finger, keep genuine big correct calls) + report median too
    cap = float(np.nanpercentile(np.abs(E.filter(pl.col("b_ts") < TRAIN_HI)["mk"].to_numpy()), 99.9))
    E = E.with_columns(pl.col("mk").clip(-cap, cap))
    tr = E.filter(pl.col("b_ts") < TRAIN_HI); te = E.filter(pl.col("b_ts") >= TEST_LO)

    trs = tr.group_by("wallet").agg(
        n=pl.len(), ncd=pl.col("cd").n_unique(), edge=pl.col("mk").mean(),
        med=pl.col("mk").median(), sd=pl.col("mk").std()).with_columns(
        t_eff=pl.col("edge") / (pl.col("sd") / pl.col("ncd").sqrt()))
    tes = te.group_by("wallet").agg(n_test=pl.len(), edge_test=pl.col("mk").mean(),
                                    med_test=pl.col("mk").median())
    W = trs.join(tes, on="wallet", how="left")
    Wt = W.filter(pl.col("n_test").is_not_null() & (pl.col("n_test") >= 20))

    print(f"{'='*84}\nWALLET-LEVEL persistence (pooled across majors) — do well-estimated wallets persist OOS?\n{'='*84}")
    for th in [100, 300, 500, 1000, 2000]:
        print(f"  wallets with pooled n_train>={th}: {W.filter(pl.col('n')>=th).height}"
              f"  (test-active: {Wt.filter(pl.col('n')>=th).height})")

    print(f"\n{'subset':34s} {'#':>5s} {'%pos test':>9s} {'mean test bp':>12s} {'null mean':>10s} {'perm p':>8s}")
    def report(sub, label, base):
        if sub.height < 3:
            print(f"  {label:32s} {sub.height:>5d}   (too few)"); return
        te_e = sub["edge_test"].to_numpy() * BP
        bte = base["edge_test"].to_numpy() * BP
        # permutation: draw sub.height random test-edges from the base pool, is observed mean exceeded?
        nul = np.array([np.nanmean(rng.choice(bte, sub.height, replace=False)) for _ in range(5000)])
        p = float(np.mean(nul >= np.nanmean(te_e)))
        print(f"  {label:32s} {sub.height:>5d} {100*np.mean(te_e>0):>8.0f}% {np.nanmean(te_e):>+11.1f} "
              f"{np.nanmean(bte):>+9.1f} {p:>8.3f}")
    for th in [300, 500, 1000]:
        base = Wt.filter(pl.col("n") >= th)
        report(Wt.filter((pl.col("n") >= th) & (pl.col("t_eff") >= 2.0)), f"n>={th} & t_eff>=2", base)
        report(Wt.filter((pl.col("n") >= th) & (pl.col("t_eff") >= 3.0)), f"n>={th} & t_eff>=3", base)

    # continuous: does effective-t predict test edge among well-sampled wallets? (all of them, not a tail)
    for th in [300, 500]:
        s = Wt.filter(pl.col("n") >= th)
        z = s["t_eff"].to_numpy(); y = s["edge_test"].to_numpy() * BP
        ok = np.isfinite(z) & np.isfinite(y); z, y = z[ok], y[ok]
        slope = np.cov(z, y)[0, 1] / np.var(z)
        nul = np.array([np.cov(rng.permutation(z), y)[0, 1] / np.var(z) for _ in range(3000)])
        print(f"  [continuous n>={th}] slope test-edge on t_eff = {slope:+.2f} bp per t-unit, perm p={np.mean(nul>=slope):.3f} (N={z.size})")

    # ---- WHO are they: the actual high-conviction wallets, and do they hold up ----
    cand = Wt.filter((pl.col("n") >= 500) & (pl.col("t_eff") >= 2.0)).sort("t_eff", descending=True)
    print(f"\n{'-'*84}\nHigh-conviction wallets (pooled n_train>=500, effective t>=2): {cand.height} found")
    with pl.Config(tbl_rows=40, fmt_str_lengths=14):
        print(cand.select(
            (pl.col("wallet").str.slice(0, 10)).alias("wallet"), "n", "ncd",
            (pl.col("edge") * BP).round(1).alias("tr_edge"), (pl.col("med") * BP).round(1).alias("tr_med"),
            pl.col("t_eff").round(1), "n_test",
            (pl.col("edge_test") * BP).round(1).alias("te_edge"),
            (pl.col("med_test") * BP).round(1).alias("te_med")))
    W.write_parquet(OUT / "wallet_level_persistence.parquet")
    print(f"\n-> out/wallet_level_persistence.parquet")


if __name__ == "__main__":
    main()
