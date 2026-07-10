"""Live fuel map + ANTICIPATION signal v2 (P(reach zone), not the crude underwater proxy).

Streams fills in TIME order (causal), maintains each wallet's position + entry-VWAP (validated:
closed_pnl reconciles to sub-cent). Every SNAP_MIN minutes emits standing fuel: each open position's
liquidation zone is placed at entry*(1+DELTA) using the calibrated liq-distance, and its notional is
weighted by the VOL-SCALED PROBABILITY that price reaches that zone within H_REACH minutes
(barrier hitting prob from trailing realized vol). fuel_below = reachable forced-sell fuel (underwater
longs near their trigger); fuel_above = reachable forced-buy fuel. The magnet thesis: price is drawn to
the heavier reachable side. Prospective (only fills ts<snapshot). Also calibrates DELTA from realized liqs.

  .venv/bin/python -m research.studies.liq_fuel_map.fuel_map build SOL
"""
import os
import sys
import math
import numpy as np
import polars as pl
from research.data.db import connect

EPS = 1e-9
SNAP_MIN = 15
H_REACH = 30                 # minutes: horizon for P(reach zone)
DELTA_L = -0.03              # long liq ~3% below entry (calib notional-wtd median)
DELTA_S = 0.03               # short liq ~3% above entry
SQRT2 = math.sqrt(2.0)
SQRTH = math.sqrt(H_REACH)


_A = (0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429)
_P = 0.3275911


def _ncdf(z):                          # vectorized normal CDF (Abramowitz-Stegun erf, ~1e-7)
    y = np.abs(z) / SQRT2
    t = 1.0 / (1.0 + _P * y)
    poly = t * (_A[0] + t * (_A[1] + t * (_A[2] + t * (_A[3] + t * _A[4]))))
    erf = np.sign(z) * (1.0 - poly * np.exp(-y * y))
    return 0.5 * (1.0 + erf)


def _price_sigma(coin, con):
    t = con.execute(f"""SELECT (ts - ts%60000) m, any_value(oracle_px) px FROM asset_ctx
                        WHERE coin='{coin}' AND oracle_px>0 GROUP BY (ts-ts%60000) ORDER BY 1""").to_arrow_table()
    ms = t["m"].to_numpy(zero_copy_only=False).astype("int64")
    px = t["px"].to_numpy(zero_copy_only=False).astype(float)
    price = dict(zip(ms, px))
    r = np.diff(np.log(px))                                   # 1-min log returns, aligned to ms[1:]
    sig = pl.Series(r).rolling_std(window_size=60).to_numpy() # trailing-60min 1-min-return std
    sigma = dict(zip(ms[1:], sig))
    return price, sigma


def build(coin):
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1500MB'; SET threads=2")
    price, sigma = _price_sigma(coin, con)
    days = [r[0] for r in con.execute(f"SELECT DISTINCT day FROM fills WHERE coin='{coin}' ORDER BY day").fetchall()]
    state = {}
    snaps = []
    deltas = []
    next_snap = None
    for day in days:
        q = f"""SELECT wallet, CASE WHEN side='B' THEN 1.0 ELSE -1.0 END s, sz_d::DOUBLE sz, px_d::DOUBLE px,
                       start_position_d::DOUBLE sp, liq_mark_px_d::DOUBLE lmp, is_liq_origin liq,
                       (ts - ts%60000) AS m
                FROM fills WHERE coin='{coin}' AND day={day} ORDER BY ts, event_index"""
        t = con.execute(q).to_arrow_table()
        W = t["wallet"].to_numpy(zero_copy_only=False)
        Sg = t["s"].to_numpy(zero_copy_only=False).astype(float)
        SZ = t["sz"].to_numpy(zero_copy_only=False).astype(float)
        PX = t["px"].to_numpy(zero_copy_only=False).astype(float)
        SP = t["sp"].to_numpy(zero_copy_only=False).astype(float)
        LMP = t["lmp"].to_numpy(zero_copy_only=False).astype(float)
        LIQ = t["liq"].to_numpy(zero_copy_only=False); M = t["m"].to_numpy(zero_copy_only=False).astype("int64")
        if next_snap is None and len(M):
            next_snap = (int(M[0]) // (SNAP_MIN * 60000)) * (SNAP_MIN * 60000) + SNAP_MIN * 60000
        for i in range(len(W)):
            m = int(M[i])
            while next_snap is not None and m >= next_snap:
                _snapshot(next_snap, price, sigma, state, snaps)
                next_snap += SNAP_MIN * 60000
            w = W[i]; ssz = Sg[i] * SZ[i]; p = PX[i]
            if w not in state:
                state[w] = [SP[i], None, abs(SP[i]) > EPS]
            st = state[w]; pb = st[0]; nb = pb + ssz
            if abs(pb) < EPS:
                st[1] = p; st[2] = False
            elif (pb > 0) == (ssz > 0):
                if st[1] is not None:
                    st[1] = (st[1] * abs(pb) + p * abs(ssz)) / (abs(pb) + abs(ssz))
            else:
                closed = min(abs(ssz), abs(pb))
                if LIQ[i] and st[1] is not None and not st[2] and LMP[i] == LMP[i] and st[1] > 0:
                    deltas.append(((LMP[i] - st[1]) / st[1], closed * p, 1.0 if pb > 0 else -1.0))
                if abs(ssz) > abs(pb) + EPS:
                    st[1] = p; st[2] = False
                elif abs(nb) < EPS:
                    st[1] = None
            if abs(nb) < EPS:
                del state[w]                # drop flat positions -> book stays ~open-only, fast snapshots
            else:
                st[0] = nb
        if day % 100 == 1:
            print(f"[fuel] {coin} {day//100}: {len(snaps)} snaps so far")
    out_dir = os.path.join(os.path.dirname(__file__), "out")
    pl.DataFrame(snaps, schema=["snap_m", "price", "fuel_below", "fuel_above", "u1", "u2", "n_open"],
                 orient="row").write_parquet(os.path.join(out_dir, f"fuel_series_{coin}.parquet"))
    dl = np.array([d for d, _, _ in deltas]); dn = np.array([n for _, n, _ in deltas])
    sgn = np.array([s for _, _, s in deltas])
    dL = dl[sgn > 0]; dS = dl[sgn < 0]
    print(f"[fuel] wrote {len(snaps)} snaps; delta n={len(dl)}  long_med={np.median(dL):.4f}  "
          f"short_med={np.median(dS):.4f}  (DELTA_L/S used = {DELTA_L}/{DELTA_S})")


def _snapshot(snap_m, price, sigma, state, snaps):
    p = price.get(snap_m); s1 = sigma.get(snap_m)
    if p is None or p <= 0 or s1 is None or not (s1 > 0):
        return
    sh = s1 * SQRTH
    posv = []; vwv = []
    for pos, vwap, cens in state.values():                     # book is open-only; skip censored
        if not cens and vwap is not None and vwap > 0:
            posv.append(pos); vwv.append(vwap)
    if not posv:
        snaps.append((snap_m, p, 0.0, 0.0, 0.0, 0.0, 0)); return
    pos = np.asarray(posv); vw = np.asarray(vwv)
    ntl = np.abs(pos) * p
    liq = np.where(pos > 0, vw * (1 + DELTA_L), vw * (1 + DELTA_S))
    dist = np.where(pos > 0, (p - liq) / p, (liq - p) / p)      # >0 = not yet triggered
    preach = 2.0 * (1.0 - _ncdf(dist / sh))
    contrib = ntl * preach
    fb = float(contrib[(pos > 0) & (liq < p)].sum())           # reachable forced-sell fuel below
    fa = float(contrib[(pos < 0) & (liq > p)].sum())           # reachable forced-buy fuel above
    snaps.append((snap_m, p, fb, fa, 0.0, 0.0, len(posv)))


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2] if len(sys.argv) > 2 else "SOL")
