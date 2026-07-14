"""
Stage 3 — per-(wallet, coin) optimal-exit roll-up: the goal deliverable (ARCHITECTURE v3 §4.7).

Defeats a size-blind peak AND a winner's-curse peak:
  1. COMMON ENTRY SET: only entries valid at EVERY horizon (argmax compares same entries).
  2. WINSORIZED DEPLOYABLE curve: h_star = argmax_h vw_edge_bps, using the SAME per-(coin,
     horizon) p99 magnitude caps as stage 2 (loaded from winsor_caps.parquet), so this artifact
     and markout_stats agree and an outlier can't win the argmax.
  3. HELD-OUT peak: h_star chosen on the wallet's first time-half; peak_net_bps evaluated on the
     held-out second half (debiases the max). Candidacy requires BOTH halves >= MIN_ENTRIES.
  4. STABILITY: moving-block bootstrap on the held-out half; peak_stable iff LOWER CI of
     net_exec_bps(h_star) > 0 AND it beats the coin-field baseline at h_star.

Output: out/optimal_exit.parquet
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import (MAJORS, H_LABELS, H_MS, MIN_ENTRIES, COST_BPS,
                      markout_ret, apply_winsor, _load_bars)

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = sorted(glob(str(ROOT / "out/entries/part_*.parquet")))
OUT = ROOT / "out"
R_BOOT = 1000
SEED = 20260704
H = H_MS.size


def block_boot_lo(ret_w_hs, notl, block, rng, cost, r=R_BOOT, q=5.0):
    """5th-percentile of net_exec_bps (vw) under a moving-block bootstrap over the entry seq."""
    n = ret_w_hs.size
    if n < MIN_ENTRIES:
        return np.nan
    nblocks = int(np.ceil(n / block))
    starts_pool = max(1, n - block + 1)
    vals = np.empty(r)
    for i in range(r):
        starts = rng.integers(0, starts_pool, size=nblocks)
        idx = (starts[:, None] + np.arange(block)[None, :]).reshape(-1)[:n]
        num = np.sum(ret_w_hs[idx] * notl[idx]); den = np.sum(notl[idx])
        vals[i] = (num / den * 1e4 - cost) if den > 0 else np.nan
    return float(np.nanpercentile(vals, q))


def main():
    assert ENTRIES, "run build_entries.py first"
    fpath = OUT / "field_by_coin_horizon.parquet"
    cpath = OUT / "winsor_caps.parquet"
    assert fpath.exists(), "field_by_coin_horizon.parquet missing — run markout_stats.py first"
    assert cpath.exists(), "winsor_caps.parquet missing — run markout_stats.py first"
    lookups = _load_bars()
    rng = np.random.default_rng(SEED)
    field = {(r["coin"], r["horizon"]): (r["field_median_bps"] or 0.0)
             for r in pl.read_parquet(fpath).iter_rows(named=True)}
    caps_df = pl.read_parquet(cpath)
    caps = {(r["coin"], r["horizon"]): r["cap"] for r in caps_df.iter_rows(named=True)}

    rows = []
    for coin in MAJORS:
        df = (pl.scan_parquet(ENTRIES).filter(pl.col("coin") == coin)
              .select("wallet", "b_ts", "dir", "entry_px", "notl").collect().sort(["wallet", "b_ts"]))
        if df.height == 0:
            continue
        lk = lookups[coin]; cost = COST_BPS[coin]
        wallet = df["wallet"].to_numpy(); b_ts = df["b_ts"].to_numpy()
        d = df["dir"].to_numpy(); entry_px = df["entry_px"].to_numpy(); notl = df["notl"].to_numpy()
        ret = markout_ret(lk, b_ts, d, entry_px)                       # raw (n,12)
        for j in range(H):                                            # winsorize with SAME caps as stage 2
            ret[:, j] = apply_winsor(ret[:, j], caps.get((coin, H_LABELS[j])))
        common = np.isfinite(ret).all(axis=1)
        uniq, start = np.unique(wallet, return_index=True)
        bounds = np.append(start, wallet.size)
        for wi in range(uniq.size):
            s, e = bounds[wi], bounds[wi + 1]
            cm = common[s:e]; n_total = e - s
            if cm.sum() < MIN_ENTRIES:
                continue
            r_c = ret[s:e][cm]; nt = notl[s:e][cm]; bt = b_ts[s:e][cm]  # common set, time-ordered
            n = r_c.shape[0]; half = n // 2
            cov = n / n_total
            vw_full = (r_c * nt[:, None]).sum(0) / nt.sum() * 1e4
            hs_full = int(np.nanargmax(vw_full))
            base = dict(wallet=str(uniq[wi]), coin=coin, n=int(n), volume=float(nt.sum()), coverage=float(cov))
            if half < MIN_ENTRIES or (n - half) < MIN_ENTRIES:         # insufficient evidence for held-out
                rows.append({**base, "h_star": H_LABELS[hs_full], "peak_net_bps": None,
                             "peak_net_lo": None, "n_eff": None, "peak_stable": False, "beats_field": None})
                continue
            tr_r, tr_n = r_c[:half], nt[:half]
            te_r, te_n, te_bt = r_c[half:], nt[half:], bt[half:]
            vw_tr = (tr_r * tr_n[:, None]).sum(0) / tr_n.sum() * 1e4
            hs = int(np.nanargmax(vw_tr))
            vw_te = (te_r[:, hs] * te_n).sum() / te_n.sum() * 1e4
            peak_net = vw_te - cost
            span = max(1, int(np.ptp(te_bt)))
            block = int(np.clip(round((n - half) * H_MS[hs] / span), 1, n - half))
            lo = block_boot_lo(te_r[:, hs], te_n, block, rng, cost)
            n_eff = float(min(n - half, max(span / float(H_MS[hs]), 1.0)))
            fld = field.get((coin, H_LABELS[hs]), 0.0)
            beats = peak_net > fld
            rows.append({**base, "h_star": H_LABELS[hs], "peak_net_bps": float(peak_net),
                         "peak_net_lo": None if np.isnan(lo) else float(lo), "n_eff": n_eff,
                         "peak_stable": bool((lo > 0) and beats), "beats_field": bool(beats)})
        print(f"{coin}: {int(common.sum()):,} common entries -> "
              f"{sum(1 for r in rows if r['coin'] == coin):,} wallet rows", flush=True)

    res = pl.DataFrame(rows).sort(["coin", "wallet"])
    res.write_parquet(OUT / "optimal_exit.parquet")
    stable = res.filter(pl.col("peak_stable"))
    print(f"\nDONE -> optimal_exit.parquet | {res.height:,} (wallet,coin) rows | "
          f"{stable.height:,} peak_stable candidates", flush=True)
    if stable.height:
        print(stable.group_by("coin").agg(pl.len().alias("n_stable"),
              pl.col("peak_net_bps").median().alias("med_peak_net_bps")).sort("coin"))


if __name__ == "__main__":
    main()
