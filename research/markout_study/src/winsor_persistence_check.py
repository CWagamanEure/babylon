"""
Winsorization/weighting audit of individual_persistence.py's -0.102 Spearman.
Reuses the EXACT same per-close avg-cost ledger as individual_persistence.py, but stores
flat numpy arrays (not python tuples) so we can compute GLOBAL p99 magnitude caps on bps
and recompute eqw / vw persistence with and without winsorization, on the SAME 3541-wallet
universe as out/individual_persistence.parquet (for apples-to-apples comparison).
RAM-careful: numpy float32 buffers, batched tape scan identical to the original script.
"""
import glob
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
    base = pl.read_parquet("out/individual_persistence.parquet")
    uni = base["wallet"].to_list()
    widx = {w: i for i, w in enumerate(uni)}
    NW = len(uni)
    print(f"universe (matched to individual_persistence.parquet): {NW} wallets", flush=True)

    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS) & pl.col("wallet").is_in(set(uni)))

    # accumulate flat numpy chunks: (widx, ts, r, notn) for TRAIN and TEST separately
    tr_chunks = []; te_chunks = []
    uni_sorted = sorted(uni); BATCH = 400
    for bi in range(0, len(uni_sorted), BATCH):
        batch = set(uni_sorted[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch)).select("wallet", "coin", "ts", "px", "sz")
              .collect().sort("ts"))
        tr_w = []; tr_r = []; tr_n = []
        te_w = []; te_r = []; te_n = []
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            g = g.sort("ts")
            wi = widx[wal]
            for t, r, notn in per_close(g["px"].to_numpy(), g["sz"].to_numpy(), g["ts"].to_numpy()):
                if t < TRAIN_HI:
                    tr_w.append(wi); tr_r.append(r); tr_n.append(notn)
                elif t >= TEST_LO:
                    te_w.append(wi); te_r.append(r); te_n.append(notn)
        if tr_w:
            tr_chunks.append((np.array(tr_w, dtype=np.int32), np.array(tr_r, dtype=np.float64), np.array(tr_n, dtype=np.float64)))
        if te_w:
            te_chunks.append((np.array(te_w, dtype=np.int32), np.array(te_r, dtype=np.float64), np.array(te_n, dtype=np.float64)))
        del df, tr_w, tr_r, tr_n, te_w, te_r, te_n
        print(f"  batch {bi//BATCH+1}/{(len(uni_sorted)-1)//BATCH+1} done ({bi+len(batch)} wallets)", flush=True)

    def cat(chunks):
        w = np.concatenate([c[0] for c in chunks])
        r = np.concatenate([c[1] for c in chunks])
        n = np.concatenate([c[2] for c in chunks])
        return w, r, n

    trW, trR, trN = cat(tr_chunks); del tr_chunks
    teW, teR, teN = cat(te_chunks); del te_chunks
    print(f"total closes: train={trW.size:,}  test={teW.size:,}", flush=True)

    def prep(w, r, n):
        good = n > 0
        return w[good], r[good], n[good]
    trW, trR, trN = prep(trW, trR, trN)
    teW, teR, teN = prep(teW, teR, teN)

    trBPS = trR / trN * BP
    teBPS = teR / teN * BP

    def report_extreme(bps, label):
        ab = np.abs(bps)
        for p in (99, 99.9, 99.99):
            print(f"  {label} |bps| p{p}: {np.percentile(ab, p):,.1f}")
        print(f"  {label} max|bps|: {ab.max():,.1f}  min bps: {bps.min():,.1f}  max bps: {bps.max():,.1f}")

    print("\n--- global per-close bps distribution (BEFORE winsorization) ---")
    report_extreme(trBPS, "TRAIN")
    report_extreme(teBPS, "TEST")

    def wallet_stats(w, r, n, bps, NW):
        """vectorized groupby-wallet: n, eqw mean, eqw t, vw."""
        cnt = np.bincount(w, minlength=NW).astype(np.float64)
        s1 = np.bincount(w, weights=bps, minlength=NW)
        s2 = np.bincount(w, weights=bps * bps, minlength=NW)
        sr = np.bincount(w, weights=r, minlength=NW)
        sn = np.bincount(w, weights=n, minlength=NW)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s1 / cnt
            var = s2 / cnt - mean * mean
            var = np.clip(var, 0, None)
            sd = np.sqrt(var)
            t = np.where((cnt > 0) & (sd > 0), mean / (sd / np.sqrt(cnt)), 0.0)
            vw = sr / sn * BP
        ok = cnt >= 20
        return cnt, mean, t, vw, ok

    def winsorize(bps, cap):
        return np.sign(bps) * np.minimum(np.abs(bps), cap)

    cap_tr = np.percentile(np.abs(trBPS), 99)
    cap_te = np.percentile(np.abs(teBPS), 99)
    print(f"\nGLOBAL p99 |bps| caps: train={cap_tr:.1f}bp  test={cap_te:.1f}bp")

    trBPSw = winsorize(trBPS, cap_tr)
    teBPSw = winsorize(teBPS, cap_te)
    trRw = trBPSw / BP * trN   # dollar-consistent winsorized realized $, so vw uses capped contributions
    teRw = teBPSw / BP * teN

    cnt_tr, mtr, ttr, vwtr, ok_tr = wallet_stats(trW, trR, trN, trBPS, NW)
    cnt_te, mte, tte, vwte, ok_te = wallet_stats(teW, teR, teN, teBPS, NW)
    cnt_trw, mtrw, ttrw, vwtrw, _ = wallet_stats(trW, trRw, trN, trBPSw, NW)
    cnt_tew, mtew, ttew, vwtew, _ = wallet_stats(teW, teRw, teN, teBPSw, NW)

    both_ok = ok_tr & ok_te
    print(f"\nwallets with >=20 closes both windows (recomputed): {both_ok.sum()}  (orig file: {NW})")

    def sp(a, b, mask):
        rho, p = spearmanr(a[mask], b[mask])
        return rho, p, mask.sum()

    print("\n=== PERSISTENCE Spearman(train, test), N=%d ===" % both_ok.sum())
    combos = [
        ("RAW   eqw-eqw  (mean bps)      ", mtr, mte),
        ("RAW   vw-vw    (notional-wtd)  ", vwtr, vwte),
        ("RAW   t-t      (eqw t-stat)    ", ttr, tte),
        ("WINS  eqw-eqw  (p99-capped)    ", mtrw, mtew),
        ("WINS  vw-vw    (p99-capped)    ", vwtrw, vwtew),
        ("WINS  t-t      (p99-capped)    ", ttrw, ttew),
    ]
    for lab, a, b in combos:
        rho, p, n = sp(a, b, both_ok)
        print(f"  {lab}: rho={rho:+.4f}  p={p:.2e}  N={n}")

    # sanity: cross-check RAW vw-vw against the original file's stored tr_vw/te_vw (should match ~exactly)
    orig = base.sort("wallet")
    order = np.argsort(uni)  # uni matches base['wallet'] order via widx build; re-derive mapping
    # widx was built off `uni` list order = base['wallet'] order already, so index i corresponds to uni[i]
    orig_trvw = base["tr_vw"].to_numpy(); orig_tevw = base["te_vw"].to_numpy()
    diff = np.nanmax(np.abs(orig_trvw[both_ok] - vwtr[both_ok]))
    print(f"\n[sanity] max|orig tr_vw - recomputed tr_vw| on matched wallets = {diff:.4f} (should be ~0)")

    # also report the top-quartile-by-train-vw OOS mean under raw vs winsorized (deployability lens)
    def topq_oos(trkey, tekey, mask, lab):
        s = np.where(mask)[0]
        thr = np.percentile(trkey[s], 90)
        sel = s[trkey[s] >= thr]
        print(f"  {lab}: top-decile-by-train N={sel.size}  OOS mean={tekey[sel].mean():+.2f}bp  %>0={100*np.mean(tekey[sel]>0):.0f}%")
    print("\n=== top-decile-by-train OOS check ===")
    topq_oos(vwtr, vwte, both_ok, "RAW  vw train -> RAW  vw test ")
    topq_oos(vwtrw, vwtew, both_ok, "WINS vw train -> WINS vw test ")

    out = pl.DataFrame({
        "wallet": uni, "ntr": cnt_tr.astype(int), "nte": cnt_te.astype(int),
        "tr_bps": mtr, "tr_t": ttr, "tr_vw": vwtr, "te_bps": mte, "te_t": tte, "te_vw": vwte,
        "tr_bps_w": mtrw, "tr_t_w": ttrw, "tr_vw_w": vwtrw, "te_bps_w": mtew, "te_t_w": ttew, "te_vw_w": vwtew,
    }).filter(pl.Series(both_ok))
    out.write_parquet("out/winsor_persistence_check.parquet")
    print("\nwrote out/winsor_persistence_check.parquet")


if __name__ == "__main__":
    main()
