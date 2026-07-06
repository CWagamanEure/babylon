"""
Reconstruct the persistent-skill cohort's ACTUAL trading from the raw fill tape (all fills, signed size +
price) — average-cost position ledger per (wallet, coin). Answers directly, not by markout inference:
  - do they actually make money (realized + open MTM), and in bps of volume?
  - how long do they hold (are they scalpers)?
  - do they enter as takers but EXIT as makers (the liquidity/execution-edge signature)?
Descriptive of their full record (in-sample inclusive) — the OOS skill claim is the separate +0.61 result.
"""
import glob
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, "src")
from mkcommon import _load_bars

COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))


def reconstruct(px, sz, ts, crossed, last_px):
    """average-cost ledger. returns realized$, open-MTM$, gross$, n_roundtrips, hold_ms list,
    closing-fill maker share (weighted by closed size)."""
    q = 0.0; avg = 0.0; avg_ts = 0.0; realized = 0.0; gross = 0.0
    holds = []; close_mk_sz = 0.0; close_sz_tot = 0.0
    for p, s, t, cr in zip(px, sz, ts, crossed):
        gross += abs(s) * p
        if q == 0.0 or (s > 0) == (q > 0):                      # open / add same direction
            avg = (avg * abs(q) + p * abs(s)) / (abs(q) + abs(s)); avg_ts = (avg_ts * abs(q) + t * abs(s)) / (abs(q) + abs(s)); q += s
        else:                                                    # reduce / close / flip
            close = min(abs(s), abs(q))
            realized += close * (p - avg) * (1.0 if q > 0 else -1.0)
            holds.append((t - avg_ts, close)); close_sz_tot += close
            if not cr: close_mk_sz += close                      # crossed=False => resting/maker exit
            newq = q + s
            if (newq > 0) != (q > 0) and newq != 0.0:            # flipped through zero
                avg = p; avg_ts = t
            q = newq
            if abs(q) < 1e-12: q = 0.0; avg = 0.0; avg_ts = 0.0
    open_mtm = abs(q) * (last_px - avg) * (1.0 if q > 0 else -1.0) if q != 0.0 else 0.0
    return realized, open_mtm, gross, len(holds), holds, close_mk_sz, close_sz_tot


def main():
    cohort = set(Path("out/cohort_wallets.txt").read_text().split("\n"))
    lk = _load_bars(); last = {c: float(lk[c][1][np.isfinite(lk[c][1])][-1]) for c in COINS}
    df = (pl.scan_parquet(TAPE).filter(pl.col("wallet").is_in(cohort) & pl.col("coin").is_in(COINS))
          .select("wallet", "coin", "ts", "px", "sz", "crossed").collect().sort("ts"))
    print(f"cohort={len(cohort)} wallets · {df.height:,} major fills\n")

    # per-wallet aggregate
    per_w = {}
    allhold = []; tot_r = tot_o = tot_g = 0.0; entry_taker = 0; entry_tot = 0
    cmk = ctot = 0.0
    for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
        g = g.sort("ts")
        px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); ts = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
        r, o, gr, nrt, holds, cm, ct = reconstruct(px, sz, ts, cr, last[coin])
        d = per_w.setdefault(wal, [0.0, 0.0, 0.0, 0]); d[0] += r; d[1] += o; d[2] += gr; d[3] += nrt
        tot_r += r; tot_o += o; tot_g += gr; allhold += holds; cmk += cm; ctot += ct
        # entry aggressor share: opening fills = first fill of each direction-run; approx via all crossed share
        entry_taker += int(cr.sum()); entry_tot += cr.size

    pnl_bps = (tot_r + tot_o) / tot_g * BP
    real_bps = tot_r / tot_g * BP
    wr = np.array([(v[0] + v[1]) for v in per_w.values()])
    print(f"{'='*70}")
    print(f"REALIZED trading PnL (price only):   ${tot_r:>14,.0f}   ({real_bps:+.2f} bps of volume)")
    print(f"  + open-position mark-to-market:    ${tot_o:>14,.0f}")
    print(f"= TOTAL PnL:                         ${tot_r+tot_o:>14,.0f}   ({pnl_bps:+.2f} bps of volume)")
    print(f"gross volume traded (majors):        ${tot_g:>14,.0f}")
    print(f"wallets net-profitable:              {int(np.mean(wr>0)*100)}%  ({int((wr>0).sum())}/{len(wr)})")
    # holding period (size-weighted median)
    hd = np.array([h for h, _ in allhold]); hw = np.array([w for _, w in allhold])
    order = np.argsort(hd); cum = np.cumsum(hw[order]); med_h = hd[order][np.searchsorted(cum, cum[-1]/2)]
    print(f"\nround-trips: {len(allhold):,}   size-weighted median holding = {med_h/3_600_000:.2f} h "
          f"({med_h/60_000:.0f} min)")
    print(f"pctile holds (h): p25={np.percentile(hd,25)/3.6e6:.2f}  p50={np.percentile(hd,50)/3.6e6:.2f}  "
          f"p75={np.percentile(hd,75)/3.6e6:.2f}")
    print(f"\naggressor (taker) share of ALL fills:      {entry_taker/entry_tot*100:.0f}%")
    print(f"maker share of CLOSING fills (sz-wtd):     {cmk/ctot*100:.0f}%   "
          f"(high => they EXIT by providing liquidity)")


if __name__ == "__main__":
    main()
