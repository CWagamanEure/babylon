"""
Stage 2 — per-(wallet, coin, horizon) markout statistics + field baseline + coverage + winsor
caps (ARCHITECTURE v3 §4.4-4.6, §6).

Reads out/entries/part_*.parquet. Per MAJOR coin: recompute markout, winsorize MAGNITUDE at
p99 per (coin,horizon) (sign re-applied) for EDGE estimators, keep risk denominators on
UN-winsorized ret; aggregate per-(wallet,horizon) via numpy bincount (no giant melt -> RAM
safe). ALT coins (>=ALT_MIN_BARS bars, non-major) feed a pooled (ALT,horizon) field row.
Winsor caps are persisted so optimal_exit uses the identical thresholds.

Outputs: markout_stats.parquet, field_by_coin_horizon.parquet, coverage_report.parquet,
         winsor_caps.parquet
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import (MAJORS, H_LABELS, H_MS, MIN_ENTRIES, COST_BPS, ALT_MIN_BARS,
                      markout_ret, winsor_cap, apply_winsor, _load_bars)

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = sorted(glob(str(ROOT / "out/entries/part_*.parquet")))
OUT = ROOT / "out"
SORTINO_K = 0.15
EPS = 1e-9
H = H_MS.size


def coin_entries(coin):
    return (pl.scan_parquet(ENTRIES).filter(pl.col("coin") == coin)
            .select("wallet", "b_ts", "dir", "entry_px", "notl").collect())


def ret_and_winsor(coin, lk):
    """Returns (df, ret_raw(n,12), ret_w(n,12), caps[12]) or None if empty."""
    df = coin_entries(coin)
    if df.height == 0:
        return None
    b_ts = df["b_ts"].to_numpy(); d = df["dir"].to_numpy(); entry_px = df["entry_px"].to_numpy()
    ret_raw = markout_ret(lk, b_ts, d, entry_px)
    ret_w = ret_raw.copy()
    caps = []
    for j in range(H):
        cap = winsor_cap(ret_raw[:, j])
        caps.append(cap)
        ret_w[:, j] = apply_winsor(ret_raw[:, j], cap)
    return df, ret_raw, ret_w, caps


def field_and_cov_rows(coin, ret_raw, ret_w, caps):
    frows, crows = [], []
    for j in range(H):
        raw = ret_raw[:, j]; w = ret_w[:, j]; fin = np.isfinite(raw)
        neg = raw[fin & (raw < 0)]
        frows.append(dict(coin=coin, horizon=H_LABELS[j], n=int(fin.sum()),
                          field_mean_bps=float(np.nanmean(w) * 1e4) if fin.any() else None,
                          field_median_bps=float(np.nanmedian(raw) * 1e4) if fin.any() else None,
                          field_dd_bps=float(np.std(neg, ddof=1) * 1e4) if neg.size >= 5 else None))
        crows.append(dict(coin=coin, horizon=H_LABELS[j], n_total=int(raw.size),
                          valid_frac=float(fin.mean()),
                          winsor_cap_bps=None if caps[j] is None else caps[j] * 1e4,
                          clip_frac=float((np.abs(raw[fin]) > caps[j]).mean()) if (caps[j] and fin.any()) else None))
    return frows, crows


def wallet_stats(coin, df, ret_raw, ret_w, field_dd):
    """Per-(wallet,horizon) stats via bincount (memory-light). Returns list[dict]."""
    wallet = df["wallet"].to_numpy(); notl = df["notl"].to_numpy(); b_ts = df["b_ts"].to_numpy()
    uniq, inv = np.unique(wallet, return_inverse=True)
    W = uniq.size
    n_total = np.bincount(inv, minlength=W).astype(np.float64)      # entries per wallet (this coin)
    span = np.zeros(W); mn = np.full(W, np.inf); mx = np.full(W, -np.inf)
    np.minimum.at(mn, inv, b_ts); np.maximum.at(mx, inv, b_ts)
    span = np.maximum(mx - mn, 1.0)
    cost = COST_BPS[coin]
    rows = []
    for j in range(H):
        raw = ret_raw[:, j]; w = ret_w[:, j]; fin = np.isfinite(raw)
        iv = inv[fin]; wn = notl[fin]; wj = w[fin]; rj = raw[fin]
        cnt = np.bincount(iv, minlength=W)
        sum_notl = np.bincount(iv, weights=wn, minlength=W)
        sum_mkusd = np.bincount(iv, weights=wj * wn, minlength=W)
        sum_w = np.bincount(iv, weights=wj, minlength=W)
        sum_r = np.bincount(iv, weights=rj, minlength=W)
        sum_r2 = np.bincount(iv, weights=rj * rj, minlength=W)
        hits = np.bincount(iv, weights=(rj > 0).astype(float), minlength=W)
        negmask = rj < 0
        nneg = np.bincount(iv, weights=negmask.astype(float), minlength=W)
        sum_neg = np.bincount(iv, weights=np.where(negmask, rj, 0.0), minlength=W)
        sum_neg2 = np.bincount(iv, weights=np.where(negmask, rj * rj, 0.0), minlength=W)
        keep = cnt >= MIN_ENTRIES
        if not keep.any():
            continue
        idx = np.nonzero(keep)[0]
        c = cnt[idx].astype(np.float64)
        mean_w_bps = sum_w[idx] / c * 1e4
        std_raw_bps = np.sqrt(np.maximum(sum_r2[idx] - sum_r[idx] ** 2 / c, 0.0) / np.maximum(c - 1, 1)) * 1e4
        vol = sum_notl[idx]
        vw_bps = np.where(vol > 0, sum_mkusd[idx] / np.where(vol > 0, vol, 1) * 1e4, np.nan)
        nn = nneg[idx]
        dd_wallet = np.where(nn >= 5, np.sqrt(np.maximum(sum_neg2[idx] - sum_neg[idx] ** 2 / np.maximum(nn, 1), 0.0)
                                              / np.maximum(nn - 1, 1)) * 1e4, np.nan)
        fdd = 0.0 if np.isnan(field_dd[j]) else field_dd[j]
        denom = np.maximum.reduce([np.nan_to_num(dd_wallet, nan=0.0), np.full(idx.size, SORTINO_K * fdd), np.full(idx.size, EPS)])
        sortino = np.where(nn >= 5, mean_w_bps / denom, np.nan)
        sharpe = np.where(std_raw_bps > 0, mean_w_bps / std_raw_bps, np.nan)
        n_eff = np.minimum(c, np.maximum(span[idx] / float(H_MS[j]), 1.0))
        for k, wi in enumerate(idx):
            rows.append(dict(
                wallet=str(uniq[wi]), coin=coin, horizon=H_LABELS[j],
                n=int(c[k]), n_eff=float(n_eff[k]), volume=float(vol[k]),
                vw_edge_bps=None if np.isnan(vw_bps[k]) else float(vw_bps[k]),
                net_exec_bps=None if np.isnan(vw_bps[k]) else float(vw_bps[k] - cost),
                exec_quality=None if vol[k] <= 0 else float(sum_mkusd[idx][k] / vol[k]),
                avg_edge_bps=float(mean_w_bps[k]),
                hit_rate=float(hits[wi] / c[k]),
                sharpe=None if np.isnan(sharpe[k]) else float(sharpe[k]),
                sortino=None if np.isnan(sortino[k]) else float(sortino[k]),
                cum_pnl_gross=float(sum_mkusd[idx][k]),
                coverage=float(c[k] / n_total[wi]),
            ))
    return rows


def main():
    assert ENTRIES, "run build_entries.py first"
    lookups = _load_bars()
    all_coins = (pl.scan_parquet(ENTRIES).select("coin").unique().collect())["coin"].to_list()
    alt_coins = [c for c in all_coins if c not in MAJORS
                 and lookups.get(c) is not None and lookups[c][0].size >= ALT_MIN_BARS]

    stat_rows, field_rows, cov_rows, cap_rows = [], [], [], []
    # --- MAJORS: full per-wallet stats ---
    for coin in MAJORS:
        rw = ret_and_winsor(coin, lookups[coin])
        if rw is None:
            print(f"{coin}: no entries", flush=True); continue
        df, ret_raw, ret_w, caps = rw
        field_dd = np.array([np.std(ret_raw[:, j][np.isfinite(ret_raw[:, j]) & (ret_raw[:, j] < 0)], ddof=1) * 1e4
                             if np.isfinite(ret_raw[:, j]).sum() and (ret_raw[:, j][np.isfinite(ret_raw[:, j])] < 0).sum() >= 5
                             else np.nan for j in range(H)])
        fr, cr = field_and_cov_rows(coin, ret_raw, ret_w, caps)
        field_rows += fr; cov_rows += cr
        cap_rows += [dict(coin=coin, horizon=H_LABELS[j], cap=caps[j]) for j in range(H)]
        stat_rows += wallet_stats(coin, df, ret_raw, ret_w, field_dd)
        print(f"{coin}: {df.height:,} entries", flush=True)

    # --- ALT: pooled field baseline only (memory-safe, one coin at a time) ---
    pool_sum = np.zeros(H); pool_cnt = np.zeros(H)
    for coin in alt_coins:
        rw = ret_and_winsor(coin, lookups[coin])
        if rw is None:
            continue
        _, ret_raw, ret_w, caps = rw
        cap_rows += [dict(coin=coin, horizon=H_LABELS[j], cap=caps[j]) for j in range(H)]
        for j in range(H):
            w = ret_w[:, j]; fin = np.isfinite(w)
            pool_sum[j] += float(np.nansum(w[fin])); pool_cnt[j] += int(fin.sum())
    for j in range(H):
        field_rows.append(dict(coin="ALT", horizon=H_LABELS[j], n=int(pool_cnt[j]),
                               field_mean_bps=float(pool_sum[j] / pool_cnt[j] * 1e4) if pool_cnt[j] else None,
                               field_median_bps=None, field_dd_bps=None))  # pooled MEAN only (median not streamable)
    print(f"ALT: pooled over {len(alt_coins)} coins", flush=True)

    if stat_rows:
        pl.DataFrame(stat_rows).sort(["coin", "wallet", "horizon"]).write_parquet(OUT / "markout_stats.parquet")
    pl.DataFrame(field_rows).sort(["coin", "horizon"]).write_parquet(OUT / "field_by_coin_horizon.parquet")
    pl.DataFrame(cov_rows).sort(["coin", "horizon"]).write_parquet(OUT / "coverage_report.parquet")
    pl.DataFrame(cap_rows).write_parquet(OUT / "winsor_caps.parquet")
    print(f"DONE -> markout_stats / field / coverage / winsor_caps in {OUT}", flush=True)


if __name__ == "__main__":
    main()
