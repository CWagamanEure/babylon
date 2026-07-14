"""
EDA prep — precompute the entry-level aggregates the notebook needs that are NOT in the
stage-2/3 artifacts, so the notebook stays fast and does no heavy recompute.

Produces (in out/):
  eda_field_dir.parquet    : per (coin,horizon) raw-vs-winsorized field mean + long/short split
  eda_winnerscurse.parquet : per candidate-eligible (wallet,coin): train-half peak vs held-out
                             value at the SAME horizon (the regression-to-mean illustration)
All markout uses the SAME winsor caps as stage 2 (loaded from winsor_caps.parquet).
"""
import sys
from glob import glob
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import MAJORS, H_LABELS, H_MS, MIN_ENTRIES, COST_BPS, markout_ret, apply_winsor, _load_bars

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = sorted(glob(str(ROOT / "out/entries/part_*.parquet")))
OUT = ROOT / "out"
H = H_MS.size


def main():
    lookups = _load_bars()
    caps = {(r["coin"], r["horizon"]): r["cap"]
            for r in pl.read_parquet(OUT / "winsor_caps.parquet").iter_rows(named=True)}
    field_rows, wc_rows = [], []
    for coin in MAJORS:
        df = (pl.scan_parquet(ENTRIES).filter(pl.col("coin") == coin)
              .select("wallet", "b_ts", "dir", "entry_px", "notl").collect().sort(["wallet", "b_ts"]))
        if df.height == 0:
            continue
        lk = lookups[coin]; cost = COST_BPS[coin]
        wallet = df["wallet"].to_numpy(); b_ts = df["b_ts"].to_numpy()
        d = df["dir"].to_numpy(); entry_px = df["entry_px"].to_numpy(); notl = df["notl"].to_numpy()
        ret_raw = markout_ret(lk, b_ts, d, entry_px)
        ret_w = ret_raw.copy()
        for j in range(H):
            ret_w[:, j] = apply_winsor(ret_raw[:, j], caps.get((coin, H_LABELS[j])))
        # field raw vs winsor + long/short (winsorized)
        for j in range(H):
            raw = ret_raw[:, j]; w = ret_w[:, j]; fin = np.isfinite(raw)
            lo = fin & (d > 0); sh = fin & (d < 0)
            field_rows.append(dict(
                coin=coin, horizon=H_LABELS[j],
                field_raw_bps=float(np.nanmean(raw) * 1e4) if fin.any() else None,
                field_wins_bps=float(np.nanmean(w) * 1e4) if fin.any() else None,
                long_bps=float(np.mean(w[lo]) * 1e4) if lo.any() else None,
                short_bps=float(np.mean(w[sh]) * 1e4) if sh.any() else None,
                n_long=int(lo.sum()), n_short=int(sh.sum())))
        # winner's curse: train-half peak vs held-out value at same horizon
        common = np.isfinite(ret_w).all(axis=1)
        uniq, start = np.unique(wallet, return_index=True)
        bounds = np.append(start, wallet.size)
        for wi in range(uniq.size):
            s, e = bounds[wi], bounds[wi + 1]
            cm = common[s:e]
            if cm.sum() < 2 * MIN_ENTRIES:
                continue
            r_c = ret_w[s:e][cm]; nt = notl[s:e][cm]
            n = r_c.shape[0]; half = n // 2
            vw_tr = (r_c[:half] * nt[:half, None]).sum(0) / nt[:half].sum() * 1e4
            hs = int(np.nanargmax(vw_tr))
            vw_te = (r_c[half:, hs] * nt[half:]).sum() / nt[half:].sum() * 1e4
            wc_rows.append(dict(coin=coin, wallet=str(uniq[wi]), h_star=H_LABELS[hs],
                                train_peak_bps=float(vw_tr[hs]),
                                heldout_bps=float(vw_te), heldout_net_bps=float(vw_te - cost)))
        print(f"{coin}: field+winnerscurse done ({len(wc_rows)} wc rows cum)", flush=True)

    pl.DataFrame(field_rows).write_parquet(OUT / "eda_field_dir.parquet")
    pl.DataFrame(wc_rows).write_parquet(OUT / "eda_winnerscurse.parquet")
    print(f"DONE -> eda_field_dir ({len(field_rows)}) / eda_winnerscurse ({len(wc_rows)}) in {OUT}", flush=True)


if __name__ == "__main__":
    main()
