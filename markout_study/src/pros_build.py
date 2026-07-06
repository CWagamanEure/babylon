"""Prosecution harness — extract per-entry arrays ONCE for the 4 majors, save to npz.
For COHORT entries: b_ts, coin_id, dir, cohort-consensus (trailing 30m same-dir),
all-wallet-consensus (trailing 30m same-dir, any wallet), dip, cost, fwd returns on a fine grid.
Also dump ALL-wallet entries per coin (b_ts,dir,allcons) for the generic-crowding proxy.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, "src")
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT = Path("out"); COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
WIN = 30 * 60_000
CID = {c: i for i, c in enumerate(COINS)}
# fine horizon grid (hours)
HRS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 20, 24]
HMS = np.array([h * 3_600_000 for h in HRS], dtype=np.int64)


def fwd(L, t, h):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + int(h))
    with np.errstate(all="ignore"):
        r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def trailing_cons(b, d):
    """trailing same-dir count in (t-WIN, t) for each entry (b sorted asc)."""
    cons = np.zeros(b.size)
    for sgn in (1.0, -1.0):
        idx = np.where(d == sgn)[0]; tb = b[idx]
        pos = np.arange(idx.size)
        cons[idx] = (pos - np.searchsorted(tb, tb - WIN)).astype(float)
    return cons


def allwallet_cons_at(ball, dall, bq, dq):
    """for query entries (bq,dq), trailing same-dir count among ALL-wallet entries (ball,dall) in (t-WIN,t).
    ball sorted asc. Count entries strictly before t with same dir within WIN. Uses searchsorted."""
    out = np.zeros(bq.size)
    for sgn in (1.0, -1.0):
        m = dall == sgn
        tb = ball[m]  # already sorted since ball sorted and boolean mask preserves order
        qi = np.where(dq == sgn)[0]
        t = bq[qi]
        hi = np.searchsorted(tb, t, side="left")      # entries strictly before t (excl same ms ties w/ left)
        lo = np.searchsorted(tb, t - WIN, side="left")
        out[qi] = (hi - lo).astype(float)
    return out


def main():
    cohort = set(Path("out/cohort_wallets.txt").read_text().split("\n"))
    lk = _load_bars()
    COH = {}  # coin -> dict of arrays
    ALL = {}
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64); cl = L[1]
        # ALL-wallet entries this coin
        qa = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter(pl.col("coin") == c).select("b_ts", "dir").sort("b_ts").collect())
        ball = qa["b_ts"].to_numpy(); dall = qa["dir"].to_numpy().astype(float)
        allcons = trailing_cons(ball, dall)
        ALL[c] = {"b": ball, "d": dall, "cons": allcons}
        # COHORT entries this coin
        qc = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter((pl.col("coin") == c) & pl.col("wallet").is_in(cohort))
              .select("b_ts", "dir").sort("b_ts").collect())
        b = qc["b_ts"].to_numpy(); d = qc["dir"].to_numpy().astype(float)
        cohcons = trailing_cons(b, d)
        allc_at = allwallet_cons_at(ball, dall, b, d)
        # dip (preceding 1h) on bars
        i = np.clip(np.searchsorted(bt, b), 0, bt.size - 1); j = np.clip(i - 12, 0, bt.size - 1)
        with np.errstate(all="ignore"):
            dip = d * (cl[i] / cl[j] - 1.0) * BP
        # fwd returns fine grid, signed, in bp
        R = np.full((b.size, HMS.size), np.nan)
        for k, h in enumerate(HMS):
            R[:, k] = d * fwd(L, b, h) * BP
        COH[c] = {"b": b, "d": d, "cohcons": cohcons, "allcons_at": allc_at,
                  "dip": dip, "cost": np.full(b.size, COST_BPS[c]),
                  "cid": np.full(b.size, CID[c]), "R": R}
        print(f"{c}: cohort n={b.size}  all n={ball.size}")
    # concat cohort
    def cat(key):
        return np.concatenate([COH[c][key] for c in COINS])
    np.savez(OUT / "pros_arrays.npz",
             b=cat("b"), d=cat("d"), cohcons=cat("cohcons"), allcons_at=cat("allcons_at"),
             dip=cat("dip"), cost=cat("cost"), cid=cat("cid"), R=np.concatenate([COH[c]["R"] for c in COINS]),
             hrs=np.array(HRS), coins=np.array(COINS))
    # generic proxy arrays: for ALL entries per coin, compute fwd returns (sample to keep size manageable)
    for c in COINS:
        L = lk[c]; A = ALL[c]
        b = A["b"]; d = A["d"]
        R = np.full((b.size, HMS.size), np.nan)
        for k, h in enumerate(HMS):
            R[:, k] = d * fwd(L, b, h) * BP
        np.savez(OUT / f"pros_all_{c}.npz", b=b, d=d, cons=A["cons"],
                 cost=np.full(b.size, COST_BPS[c]), R=R, hrs=np.array(HRS))
        print(f"saved all {c}")
    print("DONE")


if __name__ == "__main__":
    main()
