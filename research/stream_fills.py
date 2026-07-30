#!/usr/bin/env python3
"""Stream reservoir fills day-by-day -> wallet/coin/intraday aggregates (v2 schema).

Outputs per day:
  data/fills_agg/wallet_day/<d>.parquet   per wallet: taker/maker split, buy/sell/open/close
      notional, signed flow, markouts @5/30/120m (weighted sum, sum, sum-of-squares),
      fees, realized pnl, liquidation notional/count, builder-routed notional, coins,
      first/last active minute, max fill.
  data/fills_agg/coin_flow/<d>.parquet    per wallet x coin: signed/total/open notional,
      fills, 30m markout weighted sum.
  data/fills_agg/coin_5m/<d>.parquet      per coin x 5-min bucket: small-clip (<$1k) and
      large-clip (>=$10k) taker buy/sell notional, distinct small wallets per side,
      liquidation notional.
Markout: side-signed forward return of panel close vs fill price (taker fills only).
"""
import os
from concurrent.futures import ThreadPoolExecutor

import boto3
import numpy as np
import pandas as pd

BASE = "/Users/corywagamaneure/incerto-research/candle-rolloff-fade"
O1, O2, O3 = (f"{BASE}/data/fills_agg/wallet_day", f"{BASE}/data/fills_agg/coin_flow",
              f"{BASE}/data/fills_agg/coin_5m")
for o in (O1, O2, O3):
    os.makedirs(o, exist_ok=True)
z = np.load(f"{BASE}/data/cache_price_matrix.npz", allow_pickle=True)
P, PIDX, COLS = z["P"], pd.DatetimeIndex(z["idx"]), z["cols"]
i0_ms = int(pd.Timestamp(PIDX[0]).value // 10**6)
cpos = {c: j for j, c in enumerate(COLS)}
B = "hydromancer-reservoir"
days = pd.date_range("2025-08-01", "2026-07-22", freq="1D")
COLS_IN = ["coin", "price", "size", "side", "timestamp", "address", "crossed",
           "is_liquidation", "start_position", "realized_pnl", "fee", "builder"]


def do_day(d):
    ds = d.strftime("%Y-%m-%d")
    outs = [f"{O1}/{ds}.parquet", f"{O2}/{ds}.parquet", f"{O3}/{ds}.parquet"]
    if all(os.path.exists(o) for o in outs):
        return
    s3 = boto3.client("s3")
    key = f"by_dex/hyperliquid/fills/perp/all/date={ds}/fills.parquet"
    tmp = f"/tmp/fills_{ds}.parquet"
    try:
        s3.download_file(B, key, tmp, ExtraArgs={"RequestPayer": "requester"})
        f = pd.read_parquet(tmp, columns=COLS_IN)
    except Exception as e:  # noqa: BLE001
        print(f"{ds} MISSING/ERR {type(e).__name__}", flush=True)
        return
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    for c in ("price", "size", "start_position", "realized_pnl", "fee"):
        f[c] = f[c].astype(float)
    f["notional"] = f.price * f["size"].abs()
    f["sgn"] = np.where(f.side == "buy", 1.0, -1.0)
    f["is_open"] = f.start_position * f.sgn >= 0   # extends |position| (or opens from flat)
    f["has_builder"] = f.builder.notna()
    t_ms = f.timestamp.dt.tz_localize(None).to_numpy().astype("datetime64[ms]").astype("int64")
    f["t_min"] = (t_ms - i0_ms) // 60000
    f["j"] = f.coin.map(cpos)

    tk = f[f.crossed == True].copy()
    ok = tk.j.notna() & (tk.t_min >= 0) & (tk.t_min < len(PIDX) - 121)
    tk = tk[ok]
    jj, tt = tk.j.astype(int).to_numpy(), tk.t_min.to_numpy()
    for h in (5, 30, 120):
        mo = tk.sgn.to_numpy() * (P[tt + h, jj] / tk.price.to_numpy() - 1.0)
        tk[f"mo{h}"] = mo
        tk[f"mo{h}w"] = mo * tk.notional.to_numpy()
        tk[f"mo{h}sq"] = mo ** 2
    tk["s_notl"] = tk.sgn * tk.notional
    tk["buy_notl"] = np.where(tk.sgn > 0, tk.notional, 0.0)
    tk["sell_notl"] = np.where(tk.sgn < 0, tk.notional, 0.0)
    tk["open_notl"] = np.where(tk.is_open, tk.notional, 0.0)
    tk["close_notl"] = np.where(~tk.is_open, tk.notional, 0.0)
    tk["liq_notl"] = np.where(tk.is_liquidation, tk.notional, 0.0)
    tk["bld_notl"] = np.where(tk.has_builder, tk.notional, 0.0)
    tk["minute_of_day"] = (tk.t_min % 1440).astype(int)

    agg = dict(n_taker=("price", "size"), taker_notl=("notional", "sum"),
               s_notl=("s_notl", "sum"), buy_notl=("buy_notl", "sum"),
               sell_notl=("sell_notl", "sum"), open_notl=("open_notl", "sum"),
               close_notl=("close_notl", "sum"), liq_notl=("liq_notl", "sum"),
               n_liq=("is_liquidation", "sum"), fee=("fee", "sum"),
               rpnl=("realized_pnl", "sum"), n_coins=("coin", "nunique"),
               max_fill=("notional", "max"), first_min=("minute_of_day", "min"),
               last_min=("minute_of_day", "max"), builder_notl=("bld_notl", "sum"))
    for h in (5, 30, 120):
        agg[f"mo{h}w"] = (f"mo{h}w", "sum")
        agg[f"mo{h}s"] = (f"mo{h}", "sum")
        agg[f"mo{h}sq"] = (f"mo{h}sq", "sum")
    wd = tk.groupby("address").agg(**agg)
    mk = f[f.crossed == False].groupby("address").agg(
        n_maker=("price", "size"), maker_notl=("notional", "sum"), maker_fee=("fee", "sum"))
    wd = wd.join(mk, how="outer").fillna(0.0)
    wd.reset_index().to_parquet(outs[0], index=False)

    cf = tk.groupby(["address", "coin"]).agg(
        s_notl=("s_notl", "sum"), notional=("notional", "sum"),
        open_notl=("open_notl", "sum"), n_fills=("price", "size"),
        mo30w=("mo30w", "sum")).reset_index()
    cf.to_parquet(outs[1], index=False)

    tk["b5"] = (tk.t_min // 5) * 5
    small, big = tk.notional < 1_000, tk.notional >= 10_000
    tk["buy_small"] = np.where(small, tk.buy_notl, 0.0)
    tk["sell_small"] = np.where(small, tk.sell_notl, 0.0)
    tk["buy_big"] = np.where(big, tk.buy_notl, 0.0)
    tk["sell_big"] = np.where(big, tk.sell_notl, 0.0)
    c5 = tk.groupby(["coin", "b5"]).agg(
        buy_small=("buy_small", "sum"), sell_small=("sell_small", "sum"),
        buy_big=("buy_big", "sum"), sell_big=("sell_big", "sum"),
        liq_notl=("liq_notl", "sum"), n_fills=("price", "size")).reset_index()
    nb = (tk[small].groupby(["coin", "b5", "sgn"])["address"].nunique()
          .unstack("sgn").rename(columns={1.0: "nw_buy_small", -1.0: "nw_sell_small"}))
    c5 = c5.merge(nb.reset_index(), on=["coin", "b5"], how="left").fillna(0)
    c5.to_parquet(outs[2], index=False)
    print(f"{ds} ok ({len(tk):,} taker fills, {len(wd):,} wallets, {len(c5):,} coin-5m rows)",
          flush=True)


with ThreadPoolExecutor(max_workers=2) as ex:
    list(ex.map(do_day, days))
print("DONE", flush=True)
