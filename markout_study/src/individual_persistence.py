"""
The user's sharpest question, tested cleanly: forget the cohort/mean — are there INDIVIDUAL wallets with
enough N to not be luck (tight per-wallet CI) whose realized PnL PERSISTS out-of-sample?
Winner's-curse-proof by construction: we restrict to high-N wallets and to those individually significant
in TRAIN (t>=2, t>=3), then ask if they stay positive in TEST. Realized round-trip PnL from the raw tape
(avg-cost ledger) = what a zero-lag copier books. NOT markout (which is beta-contaminated).
Split: TRAIN ts<Feb1 / TEST ts>=Mar1. Majors only.
"""
import glob, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl

COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = ms(2026, 2, 1); TEST_LO = ms(2026, 3, 1)
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))


def per_close(px, sz, ts):
    """avg-cost ledger -> list of (ts, realized_usd, closed_notional) per closing event."""
    q = avg = 0.0; out = []
    for p, s, t in zip(px, sz, ts):
        if q == 0.0 or (s > 0) == (q > 0):
            avg = (avg * abs(q) + p * abs(s)) / (abs(q) + abs(s)); q += s
        else:
            c = min(abs(s), abs(q))
            out.append((t, c * (p - avg) * (1.0 if q > 0 else -1.0), c * p))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0: avg = p
            q = nq
            if abs(q) < 1e-12: q = 0.0; avg = 0.0
    return out


def stats(recs):
    """recs = list of (realized_usd, notional). returns (n, bps_mean_eqw, t, vw_bps)."""
    if len(recs) < 20: return None
    r = np.array([x[0] for x in recs]); notn = np.array([x[1] for x in recs])
    good = notn > 0; r = r[good]; notn = notn[good]
    if r.size < 20: return None
    bps = r / notn * BP
    n = bps.size; mean = bps.mean(); sd = bps.std()
    t = mean / (sd / np.sqrt(n)) if sd > 0 else 0.0
    vw = r.sum() / notn.sum() * BP
    return n, mean, t, vw


def main():
    # universe: >=2000 train fills & >=100 test fills (majors)
    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS))
    cnt = (lf.filter(pl.col("ts") < TRAIN_HI).group_by("wallet").agg(n=pl.len())
           .filter(pl.col("n") >= 2000).select("wallet").collect())
    uni = set(cnt["wallet"].to_list())
    print(f"universe (>=2000 train majors fills): {len(uni)} wallets", flush=True)
    # MEMORY-SAFE: process wallets in batches (1GB box) — reconstruct per batch, keep only aggregates.
    uni = sorted(uni); W = {}
    BATCH = 400
    for bi in range(0, len(uni), BATCH):
        batch = set(uni[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch)).select("wallet","coin","ts","px","sz")
              .collect().sort("ts"))
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            g = g.sort("ts")
            d = W.setdefault(wal, {"tr": [], "te": []})
            for t, r, notn in per_close(g["px"].to_numpy(), g["sz"].to_numpy(), g["ts"].to_numpy()):
                if t < TRAIN_HI: d["tr"].append((r, notn))
                elif t >= TEST_LO: d["te"].append((r, notn))
        del df
        print(f"  batch {bi//BATCH+1}/{(len(uni)-1)//BATCH+1} done ({bi+len(batch)} wallets)", flush=True)
    rows = []
    for wal, d in W.items():
        st, se = stats(d["tr"]), stats(d["te"])
        if st is None or se is None: continue
        rows.append((wal, *st, *se))
    R = pl.DataFrame(rows, schema=["wallet","ntr","tr_bps","tr_t","tr_vw","nte","te_bps","te_t","te_vw"], orient="row")
    print(f"wallets with >=20 closes both windows: {R.height}\n")

    z = R["tr_t"].to_numpy(); yv = R["te_vw"].to_numpy(); yb = R["te_bps"].to_numpy()
    xv = R["tr_vw"].to_numpy()
    def sp(a, b):
        from scipy.stats import spearmanr
        return spearmanr(a, b).correlation
    try: rho = sp(xv, yv)
    except Exception:
        ar = np.argsort(np.argsort(xv)); br = np.argsort(np.argsort(yv))
        rho = np.corrcoef(ar, br)[0,1]
    print(f"PERSISTENCE among high-N wallets: Spearman(train $-bps, test $-bps) = {rho:+.3f}  (N={R.height})")

    print(f"\n{'train selector':28s} {'#':>5s} {'test $-bps mean':>15s} {'%test>0':>8s} {'test bps(eqw)':>13s}")
    def rep(mask, lab):
        s = R.filter(mask)
        if s.height < 5: print(f"  {lab:26s} {s.height:>5d}  (too few)"); return
        tv = s["te_vw"].to_numpy(); tb = s["te_bps"].to_numpy()
        print(f"  {lab:26s} {s.height:>5d} {np.mean(tv):>+14.2f} {100*np.mean(tv>0):>7.0f}% {np.mean(tb):>+12.2f}")
    rep(pl.col("ntr") > 0, "ALL high-N wallets")
    rep(pl.col("tr_vw") > 0, "train profitable (vw>0)")
    rep(pl.col("tr_t") >= 2, "train t>=2 (indiv. signif.)")
    rep(pl.col("tr_t") >= 3, "train t>=3 (tight, ~p<.003)")
    rep(pl.col("tr_t") >= 4, "train t>=4 (very tight)")
    rep((pl.col("tr_t") >= 3) & (pl.col("ntr") >= 500), "t>=3 & >=500 closes")
    # decisive: the individually-significant winners — do they as a group beat zero OOS?
    win = R.filter(pl.col("tr_t") >= 3)
    if win.height >= 5:
        tv = win["te_vw"].to_numpy()
        from numpy.random import default_rng
        rng = default_rng(0)
        bs = np.array([rng.choice(tv, tv.size).mean() for _ in range(5000)])
        print(f"\n  train-t>=3 winners' OOS $-bps: {tv.mean():+.2f}  95%CI [{np.percentile(bs,2.5):+.2f}, {np.percentile(bs,97.5):+.2f}]  (n={tv.size})")
    # show the top individuals by train t
    print("\nTop 15 individual wallets by TRAIN t-stat:")
    top = R.sort("tr_t", descending=True).head(15)
    with pl.Config(tbl_rows=20, fmt_str_lengths=12):
        print(top.select(pl.col("wallet").str.slice(0,10), "ntr",
              pl.col("tr_vw").round(1), pl.col("tr_t").round(1),
              "nte", pl.col("te_vw").round(1), pl.col("te_t").round(1)))
    R.write_parquet("out/individual_persistence.parquet")


if __name__ == "__main__":
    main()
