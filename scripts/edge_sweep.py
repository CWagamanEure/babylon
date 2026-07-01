"""Edge sweep — pin the real DEPLOYABLE followable edge from per-wallet files.

Reads data/follow/fills_his/{wallet}.parquet (from split_his_fills.py) and runs OUR
followable measure on the PAST-ONLY universe, sweeping the operating point:
    lag (detection+exec latency)  x  {directional, neutralized}
For each transition we extract each wallet's round-trip positions ONCE (lag-independent),
then RE-PRICE them cheaply at every lag/mode. Per setting: rank wallets by train skill,
select top-N, measure their test return.

Reports, per (lag, mode):
  * SELECTED return  = the deployable P&L proxy (what the followed book earns, gross)
  * NET selected     = selected - round-trip cost   (the number that decides tradeability)
  * edge-over-field  = selected - field             (skill vs the pool; cost-invariant)
  with a WALLET-CLUSTER bootstrap 90% CI (we pick wallets, so we resample wallets).

Caveat: his export carries no true startPosition (seeded 0), so a position open before a
wallet's first in-window fill is mis-seeded — identical to convergence_his, so comparable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.fills_source import ParquetFillsProvider
from babylon.follow.followable import _close_at, load_price_lookups
from babylon.follow.scheduler import _sortino
from babylon.follow.skill import _basket_ret_bps, _positions_for, build_basket

_DAY_MS = 86_400_000


def extract_positions(df: pl.DataFrame, coins: set[str], lookups: dict, min_hold_ms: int):
    """Lag-independent: taker-opened, conviction, priceable, >= min_hold round-trips.
    Returns list of (coin, Position)."""
    out = []
    if df.height == 0:
        return out
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        c = str(coin)
        if c not in coins or c not in lookups:
            continue
        for p in _positions_for(g):
            if not p.taker_open or not p.conviction_open or p.hold_ms < min_hold_ms:
                continue
            out.append((c, p))
    return out


def price(positions, lookups, lag_ms, basket, beta):
    """Re-price extracted positions at a given lag/mode -> per-RT bps array."""
    bps = []
    for c, p in positions:
        lk = lookups[c]
        ein = _close_at(lk, p.entry_t + lag_ms)
        eout = _close_at(lk, p.exit_t + lag_ms)
        if ein is None or eout is None:
            continue
        raw = p.direction * (eout / ein - 1.0) * 1e4
        if basket is not None:
            raw -= p.direction * beta * _basket_ret_bps(basket, p.entry_t + lag_ms, p.exit_t + lag_ms)
        bps.append(raw)
    return np.asarray(bps, dtype=np.float64)


def _skill(r, stat):
    if stat == "median":
        return float(np.median(r)) if r.size else -1e18
    return _sortino(r) if r.size >= 2 else -1e18


def _boot_ci(arrays, n_boot, rng, cost):
    """Wallet-cluster bootstrap: resample the per-wallet test arrays with replacement,
    pool, take the mean. Returns (lo, hi) 90% CI of the NET selected mean."""
    arrays = [a for a in arrays if a.size]
    if len(arrays) < 2:
        return (float("nan"), float("nan"))
    means = np.empty(n_boot)
    idx = np.arange(len(arrays))
    for b in range(n_boot):
        pick = rng.choice(idx, size=len(arrays), replace=True)
        pooled = np.concatenate([arrays[j] for j in pick])
        means[b] = pooled.mean() - cost
    return (float(np.percentile(means, 5)), float(np.percentile(means, 95)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fills-dir", type=Path, default=Path("data/follow/fills_his"))
    ap.add_argument("--candles-dir", type=Path, default=Path("data/follow/candles"))
    ap.add_argument("--universe", type=Path, default=Path("scratch_conv/universe_k.json"))
    ap.add_argument("--boundaries", type=Path, default=Path("scratch_conv/boundaries.txt"))
    ap.add_argument("--train-days", type=int, default=31)
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--min-hold-ms", type=int, default=3_600_000)
    ap.add_argument("--beta", type=float, default=1.245)
    ap.add_argument("--cost-bps", type=float, default=8.0, help="round-trip cost (fees+spread)")
    ap.add_argument("--lags", type=str, default="0,30000,60000,300000,900000")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--stat", choices=["median", "sortino"], default="median")
    args = ap.parse_args()

    rng = np.random.default_rng(12345)
    lags = [int(x) for x in args.lags.split(",")]
    lookups = load_price_lookups(args.candles_dir)
    coins = set(lookups)
    basket = build_basket(args.candles_dir, sorted(coins))
    provider = ParquetFillsProvider(args.fills_dir)
    univ = {int(k): v for k, v in json.loads(args.universe.read_text()).items()}
    bounds = [int(x) for x in args.boundaries.read_text().split(",")]
    print(f"coins={len(coins)} top_n={args.top_n} cost={args.cost_bps}bp stat={args.stat} "
          f"min_hold={args.min_hold_ms/3.6e6:.0f}h\n")

    # positions[k][w] = (train_positions, test_positions); extracted ONCE per transition
    positions: dict[int, dict] = {}
    for k in range(len(bounds) - 1):
        t0, t1 = bounds[k], bounds[k + 1]
        train_lo = t0 - args.train_days * _DAY_MS
        pw = {}
        for w in univ[k]:
            df = provider(w, train_lo, t1)
            pos = extract_positions(df, coins, lookups, args.min_hold_ms)
            tr = [(c, p) for c, p in pos if p.exit_t < t0]
            te = [(c, p) for c, p in pos if t0 <= p.exit_t < t1]
            if tr or te:
                pw[w] = (tr, te)
        positions[k] = pw
        print(f"[extract] k={k} wallets_with_rts={len(pw)}")
    print()

    modes = [("directional", None), ("neutralized", basket)]
    for lag in lags:
        for mname, bk in modes:
            per_k_sel, sel_arrays_pooled, sel_means, field_means = [], [], [], []
            for k in range(len(bounds) - 1):
                trsk, ter = {}, {}
                for w, (tr, te) in positions[k].items():
                    trsk[w] = _skill(price(tr, lookups, lag, bk, args.beta), args.stat)
                    ter[w] = price(te, lookups, lag, bk, args.beta)
                elig = [w for w, (tr, te) in positions[k].items()
                        if len(tr) >= 2 and ter[w].size >= 1]
                if not elig:
                    continue
                field = np.concatenate([ter[w] for w in elig])
                top = sorted(elig, key=lambda w: -trsk[w])[: args.top_n]
                sel = np.concatenate([ter[w] for w in top]) if top else np.empty(0)
                per_k_sel.append(sel.mean() if sel.size else float("nan"))
                sel_means.append(sel.mean() if sel.size else np.nan)
                field_means.append(field.mean() if field.size else np.nan)
                sel_arrays_pooled.extend(ter[w] for w in top)
            if not sel_means:
                continue
            sm = float(np.nanmean(sel_means))
            fm = float(np.nanmean(field_means))
            net = sm - args.cost_bps
            lo, hi = _boot_ci(sel_arrays_pooled, args.boot, rng, args.cost_bps)
            print(f"lag={lag/1000:6.0f}s {mname:11s} sel={sm:+7.1f} net={net:+7.1f} "
                  f"[{lo:+6.1f},{hi:+6.1f}]90%  edge_v_field={sm-fm:+7.1f}  "
                  f"per_k_sel={[round(x,1) for x in per_k_sel]}")
        print()


if __name__ == "__main__":
    main()
