"""
Feasibility visual data: per-wallet distribution of HOLD TIME x SAMPLE SIZE, reconciling that (a) hold is
heterogeneous within a wallet (so we bucket per-trade, not average), and (b) copyability needs TAKER-OPENED
round-trips (so we track entry-taker-share per close and only count taker-opened legs).

One serial, batched, streaming tape pass. Emits a small per-wallet parquet -> plotted in a notebook.
Whole-window (train+test) for a robust hold/size picture. Dust floor: closed notional >= $100.
"""
import glob, sys
from datetime import datetime, timezone
import numpy as np
import polars as pl

COINS = ["BTC", "ETH", "SOL", "HYPE"]
TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
MIN_NOTL = 100.0
HR = 3.6e6  # ms per hour
# hold bands (hours): <0.25, 0.25-1, 1-4, 4-24, 24-72, >72
BANDS = [(0.0, 0.25), (0.25, 1.0), (1.0, 4.0), (4.0, 24.0), (24.0, 72.0), (72.0, 1e9)]
BAND_LABELS = ["lt15m", "15m_1h", "1_4h", "4_24h", "24_72h", "gt72h"]


def ledger(px, sz, ts, cr):
    """avg-cost ledger with entry-taker-share tracking of the OPEN inventory.
    Yields per close: (realized_notional>0 kept upstream) -> (notl, hold_h, open_taker_share).
    open_tot/open_tk = notional pools of currently-open inventory (pooled avg-cost)."""
    q = avg = avg_ts = 0.0
    open_tot = open_tk = 0.0
    out = []
    for p, s, t, c in zip(px, sz, ts, cr):
        fill_notl = abs(s) * p
        if q == 0.0 or (s > 0) == (q > 0):                 # open / add (same side or from flat)
            w = abs(q) + abs(s)
            avg = (avg * abs(q) + p * abs(s)) / w
            avg_ts = (avg_ts * abs(q) + t * abs(s)) / w
            open_tot += fill_notl
            open_tk += fill_notl if c else 0.0
            q += s
        else:                                              # reduce / close / flip
            close = min(abs(s), abs(q))
            frac = close / abs(q)
            ots = (open_tk / open_tot) if open_tot > 1e-12 else np.nan
            notl = close * p
            hold_h = (t - avg_ts) / HR
            if notl >= MIN_NOTL:
                out.append((notl, hold_h, ots))
            nq = q + s
            if abs(nq) < 1e-12:                            # flat
                q = 0.0; avg = 0.0; avg_ts = 0.0; open_tot = 0.0; open_tk = 0.0
            elif (nq > 0) != (q > 0):                      # flip -> residual opens new side at this (taker c) fill
                q = nq; avg = p; avg_ts = t
                open_tot = abs(nq) * p; open_tk = open_tot if c else 0.0
            else:                                          # partial reduce -> scale open pools down
                q = nq; open_tot *= (1 - frac); open_tk *= (1 - frac)
    return out


def main():
    lf = pl.scan_parquet(TAPE).filter(pl.col("coin").is_in(COINS))
    cnt = (lf.group_by("wallet").agg(n=pl.len()).filter(pl.col("n") >= 200)
           .select("wallet").collect(engine="streaming"))
    uni = sorted(set(cnt["wallet"].to_list()))
    print(f"universe (>=200 majors fills): {len(uni)} wallets", flush=True)

    rows = []
    BATCH = 150
    nb = (len(uni) - 1) // BATCH + 1
    for bi in range(0, len(uni), BATCH):
        batch = set(uni[bi:bi + BATCH])
        df = (lf.filter(pl.col("wallet").is_in(batch))
              .select("wallet", "coin", "ts", "px", "sz", "crossed").collect().sort(["ts"]))
        # accumulate per-wallet across its coins
        acc = {}
        for (wal, coin), g in df.group_by(["wallet", "coin"], maintain_order=True):
            g = g.sort("ts")
            px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); tsr = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
            a = acc.setdefault(wal, {"closes": [], "fill_notl": 0.0, "fill_tk": 0.0})
            fn = np.abs(sz) * px
            a["fill_notl"] += float(fn.sum()); a["fill_tk"] += float(fn[cr.astype(bool)].sum())
            a["closes"].extend(ledger(px, sz, tsr, cr))
        for wal, a in acc.items():
            cl = a["closes"]
            if not cl:
                continue
            notl = np.array([x[0] for x in cl]); hold = np.array([x[1] for x in cl])
            ots = np.array([x[2] for x in cl])
            taker_share = a["fill_tk"] / a["fill_notl"] if a["fill_notl"] > 0 else np.nan
            n_close_all = int(notl.size)
            tk_mask = np.isfinite(ots) & (ots > 0.5) & (hold > 0)      # taker-OPENED round-trips
            tkh = hold[tk_mask]
            n_tk = int(tkh.size)
            # per-band counts among taker-opened
            band_ct = []
            for lo, hi in BANDS:
                band_ct.append(int(((tkh >= lo) & (tkh < hi)).sum()))
            if n_tk >= 1:
                med_h = float(np.median(tkh)); p25 = float(np.percentile(tkh, 25)); p75 = float(np.percentile(tkh, 75))
            else:
                med_h = p25 = p75 = np.nan
            n_copyable = band_ct[2] + band_ct[3]                       # holds in [1h,24h], taker-opened
            rows.append((wal, n_close_all, float(taker_share), n_tk, med_h, p25, p75, n_copyable, *band_ct))
        del df, acc
        print(f"  batch {bi//BATCH+1}/{nb} ({bi+len(batch)} wallets) rows={len(rows)}", flush=True)

    cols = ["wallet", "n_close_all", "taker_share", "n_tk_close", "med_hold_h", "p25_hold_h", "p75_hold_h",
            "n_copyable"] + [f"nb_{l}" for l in BAND_LABELS]
    R = pl.DataFrame(rows, schema=cols, orient="row")
    R.write_parquet("out/hold_size_dist.parquet")
    print(f"\nwrote {R.height} wallets -> out/hold_size_dist.parquet", flush=True)
    print(f"  wallets with n_copyable >= 100 : {int((R['n_copyable'] >= 100).sum())}", flush=True)
    print(f"  ...and taker_share >= 0.7      : {int(((R['n_copyable'] >= 100) & (R['taker_share'] >= 0.7)).sum())}", flush=True)


if __name__ == "__main__":
    main()
