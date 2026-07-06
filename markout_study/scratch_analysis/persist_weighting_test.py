"""
Lens: weighting + winsorization + the tr_vw/tr_t sign-contradiction.
Reprocesses the same tape/window/universe as src/individual_persistence.py, but
keeps the RAW per-close (bps, notn) records so we can:
  (a) confirm what the headline -0.102 Spearman is actually computed on
  (b) recompute persistence on winsorized (p99 |bps|) eqw returns
  (c) recompute persistence on winsorized + capital(vw)-weighted returns
"""
import glob, sys
from datetime import datetime, timezone
import numpy as np
import polars as pl
from scipy.stats import spearmanr

COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = ms(2026, 2, 1); TEST_LO = ms(2026, 3, 1)
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))

def per_close(px, sz, ts):
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

def main():
    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS))
    cnt = (lf.filter(pl.col("ts") < TRAIN_HI).group_by("wallet").agg(n=pl.len())
           .filter(pl.col("n") >= 2000).select("wallet").collect())
    uni = sorted(set(cnt["wallet"].to_list()))
    print(f"universe (>=2000 train majors fills): {len(uni)} wallets", flush=True)

    W = {}
    BATCH = 400
    for bi in range(0, len(uni), BATCH):
        batch = set(uni[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch)).select("wallet","coin","ts","px","sz")
              .collect().sort("ts"))
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            g = g.sort("ts")
            d = W.setdefault(wal, {"tr": [], "te": []})
            for t, r, notn in per_close(g["px"].to_numpy(), g["sz"].to_numpy(), g["ts"].to_numpy()):
                if notn <= 0: continue
                bps = r / notn * BP
                if t < TRAIN_HI: d["tr"].append((bps, notn))
                elif t >= TEST_LO: d["te"].append((bps, notn))
        del df
        print(f"  batch {bi//BATCH+1}/{(len(uni)-1)//BATCH+1} done ({bi+len(batch)} wallets)", flush=True)

    # convert to numpy arrays per wallet/window; keep only wallets with >=20 closes both windows
    WN = {}
    all_bps = []  # pooled across ALL wallets, ALL windows -> for global p99 cap
    for wal, d in W.items():
        if len(d["tr"]) < 20 or len(d["te"]) < 20: continue
        tr_b = np.array([x[0] for x in d["tr"]]); tr_n = np.array([x[1] for x in d["tr"]])
        te_b = np.array([x[0] for x in d["te"]]); te_n = np.array([x[1] for x in d["te"]])
        WN[wal] = (tr_b, tr_n, te_b, te_n)
        all_bps.append(tr_b); all_bps.append(te_b)
    del W
    all_bps = np.concatenate(all_bps)
    cap = np.percentile(np.abs(all_bps), 99)
    print(f"\nwallets with >=20 closes both windows: {len(WN)}")
    print(f"pooled per-close bps: N={all_bps.size}  p99(|bps|)={cap:.1f}  "
          f"min={all_bps.min():.1f} max={all_bps.max():.1f}  "
          f"frac(|bps|>1000)={np.mean(np.abs(all_bps)>1000)*100:.3f}%", flush=True)

    rows = []
    for wal, (tr_b, tr_n, te_b, te_n) in WN.items():
        # --- (a) as-built: eqw mean/t, vw = notional-weighted mean (NO winsorization) ---
        tr_eqw = tr_b.mean(); te_eqw = te_b.mean()
        tr_vw = (tr_b * tr_n).sum() / tr_n.sum(); te_vw = (te_b * te_n).sum() / te_n.sum()
        # --- (b) winsorized eqw: cap |bps| at global p99, unweighted mean ---
        tr_b_w = np.clip(tr_b, -cap, cap); te_b_w = np.clip(te_b, -cap, cap)
        tr_eqw_w = tr_b_w.mean(); te_eqw_w = te_b_w.mean()
        # --- (c) winsorized + vw ---
        tr_vw_w = (tr_b_w * tr_n).sum() / tr_n.sum(); te_vw_w = (te_b_w * te_n).sum() / te_n.sum()
        rows.append((wal, tr_b.size, te_b.size, tr_eqw, te_eqw, tr_vw, te_vw,
                     tr_eqw_w, te_eqw_w, tr_vw_w, te_vw_w))

    R = pl.DataFrame(rows, schema=["wallet","ntr","nte","tr_eqw","te_eqw","tr_vw","te_vw",
                                    "tr_eqw_w","te_eqw_w","tr_vw_w","te_vw_w"], orient="row")
    R.write_parquet("scratch_analysis/persist_weighting_test.parquet")

    def rho(a, b): return spearmanr(R[a].to_numpy(), R[b].to_numpy()).correlation
    print(f"\nN wallets = {R.height}\n")
    print(f"(baseline, uncapped) eqw  : Spearman(tr_eqw, te_eqw)   = {rho('tr_eqw','te_eqw'):+.4f}")
    print(f"(baseline, uncapped) vw   : Spearman(tr_vw,  te_vw )  = {rho('tr_vw','te_vw'):+.4f}   <-- this is what individual_persistence.py's headline rho actually is")
    print(f"(a) capital/vw-weighted (uncapped, restated)          = {rho('tr_vw','te_vw'):+.4f}")
    print(f"(b) winsorized p99, EQW (unweighted)                  = {rho('tr_eqw_w','te_eqw_w'):+.4f}")
    print(f"(c) winsorized p99 AND vw-weighted                    = {rho('tr_vw_w','te_vw_w'):+.4f}")

if __name__ == "__main__":
    main()
