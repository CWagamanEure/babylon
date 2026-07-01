"""Convergence test — run OUR followable measurement on the OTHER repo's past-only universe.

Cross-repo replication: the other investigation found ~+17 bp/RT selected / +10.7 bp/RT
edge-over-field on a PAST-ONLY, full-population universe (top-1500 by cumulative past
notional per transition). Our bake-off found +159 bp/RT neutralized on the FROZEN 1404
survivor pool. The 10x gap is hypothesised to be frozen-pool survivorship inflation. This
runs OUR code (followable_returns: candle-lagged directional/neutralized per-RT markout) on
HIS universe — if our number collapses toward ~+15-20, that's an INDEPENDENT (different
code, different repo) confirmation of the edge + the diagnosis.

INPUTS (from his export):
  --fills-dir    per-wallet parquet {wallet}.parquet, schema time,coin,px,sz,side,crossed,
                 startPosition,hash,tid  (same as ours — ParquetFillsProvider reads it)
  --candles-dir  hourly candles covering his universe's coins + span (ours may suffice; the
                 runner reports any coin it can't price)
  --universe     JSON {"<k>": ["0xwallet", ...]} = past_univ[k] per-transition membership
  --boundaries   comma-separated month-edge timestamps in ms, len = K+1; transition k trains
                 on [b_k - train_days, b_k), tests on [b_k, b_{k+1}), universe = past_univ[k]

  --self-smoke   ignore the above; run on OUR fills/candles with all-wallets-as-universe and
                 auto monthly boundaries — validates the machinery before his data arrives.

OUTPUT: per-transition + pooled  {selected mean, field mean, edge-over-field, Spearman}  for
median and Sortino-floored ranking, directional and neutralized. Compare edge-over-field to
his +10.7.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.fills_source import ParquetFillsProvider
from babylon.follow.followable import followable_returns, load_price_lookups
from babylon.follow.scheduler import _sortino
from babylon.follow.skill import build_basket

_DAY_MS = 86_400_000


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation without scipy (Pearson on ranks)."""
    if x.size < 4:
        return float("nan")
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def _median(r: np.ndarray) -> float:
    return float(np.median(r)) if r.size else -1e18


_STATS = {"median": _median, "sortino": lambda r: _sortino(r) if r.size >= 2 else -1e18}


def _wallet_returns(provider, wallet, lo, hi, *, universe, lookups, basket, args):
    df = provider(wallet, lo, hi)
    if df.height == 0:
        return np.empty(0)
    return followable_returns(
        df, universe=universe, lookups=lookups, lag_ms=args.lag_ms,
        min_hold_ms=args.min_hold_ms, before_ms=hi, basket=basket, beta=args.beta)


def run_transition(k, train_lo, t_k, t_next, wallets, provider, universe, lookups, basket, args):
    """One transition: rank `wallets` on [train_lo, t_k) skill, measure top-N on [t_k, t_next)
    vs the whole universe (field). Returns dict per stat."""
    train_r = {w: _wallet_returns(provider, w, train_lo, t_k, universe=universe,
                                  lookups=lookups, basket=basket, args=args) for w in wallets}
    test_r = {w: _wallet_returns(provider, w, t_k, t_next, universe=universe,
                                 lookups=lookups, basket=basket, args=args) for w in wallets}
    # eligibility: scorable train (>=2 RT) AND any test RT to contribute to the field
    elig = [w for w in wallets if train_r[w].size >= 2 and test_r[w].size >= 1]
    field = np.concatenate([test_r[w] for w in elig]) if elig else np.empty(0)
    out = {}
    for name, fn in _STATS.items():
        ranked = sorted(elig, key=lambda w: -fn(train_r[w]))
        top = ranked[: args.top_n]
        sel = np.concatenate([test_r[w] for w in top]) if top else np.empty(0)
        # Spearman of (train stat, mean test return) across the eligible universe
        xs = np.array([fn(train_r[w]) for w in elig])
        ys = np.array([float(test_r[w].mean()) for w in elig])
        rho = _spearman(xs, ys)
        out[name] = {
            "n_elig": len(elig), "n_sel": len(top),
            "sel_mean": float(sel.mean()) if sel.size else float("nan"),
            "field_mean": float(field.mean()) if field.size else float("nan"),
            "edge": float(sel.mean() - field.mean()) if sel.size and field.size else float("nan"),
            "rho": rho, "n_sel_rt": sel.size, "n_field_rt": field.size}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fills-dir", type=Path, default=Path("data/follow/fills"))
    ap.add_argument("--candles-dir", type=Path, default=Path("data/follow/candles"))
    ap.add_argument("--universe", type=Path)
    ap.add_argument("--boundaries", type=str, help="comma-sep month-edge ms, len K+1")
    ap.add_argument("--train-days", type=int, default=30)
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--lag-ms", type=int, default=60_000)
    ap.add_argument("--min-hold-ms", type=int, default=3_600_000)
    ap.add_argument("--beta", type=float, default=1.245)
    ap.add_argument("--neutralize", action="store_true", help="de-market via alt basket")
    ap.add_argument("--self-smoke", action="store_true")
    args = ap.parse_args()

    lookups = load_price_lookups(args.candles_dir)
    coins = set(lookups)
    basket = build_basket(args.candles_dir, sorted(coins)) if args.neutralize else None
    provider = ParquetFillsProvider(args.fills_dir)

    if args.self_smoke:
        all_w = [p.stem for p in args.fills_dir.glob("*.parquet")]
        # auto monthly boundaries across the data span (use a sample to find min/max time)
        t = pl.read_parquet(args.fills_dir / f"{all_w[0]}.parquet")["time"]
        lo, hi = int(t.min()), int(t.max())
        bounds = list(range(lo + args.train_days * _DAY_MS, hi, 30 * _DAY_MS)) + [hi]
        univ_by_k = {k: all_w for k in range(len(bounds) - 1)}
        print(f"[self-smoke] {len(all_w)} wallets, {len(bounds)-1} transitions, "
              f"neutralize={args.neutralize}")
    else:
        if not (args.universe and args.boundaries):
            ap.error("need --universe and --boundaries (or --self-smoke)")
        raw = json.loads(args.universe.read_text())
        univ_by_k = {int(k): v for k, v in raw.items()}
        bounds = [int(x) for x in args.boundaries.split(",")]

    print(f"coins_priced={len(coins)}  basket={'on' if basket else 'off'}\n")
    rows = []
    for k in range(len(bounds) - 1):
        if k not in univ_by_k:
            continue
        train_lo = bounds[k] - args.train_days * _DAY_MS
        res = run_transition(k, train_lo, bounds[k], bounds[k + 1], univ_by_k[k],
                             provider, coins, lookups, basket, args)
        for stat, r in res.items():
            print(f"k={k} {stat:8s} elig={r['n_elig']:5d} sel_mean={r['sel_mean']:+8.1f} "
                  f"field={r['field_mean']:+7.1f} EDGE={r['edge']:+7.1f}bp rho={r['rho']:+.3f} "
                  f"(sel_rt={r['n_sel_rt']}, field_rt={r['n_field_rt']})")
            rows.append((stat, r))
    print("\n=== POOLED (mean over transitions) ===")
    for stat in _STATS:
        es = [r["edge"] for s, r in rows if s == stat and np.isfinite(r["edge"])]
        rhos = [r["rho"] for s, r in rows if s == stat and np.isfinite(r["rho"])]
        sels = [r["sel_mean"] for s, r in rows if s == stat and np.isfinite(r["sel_mean"])]
        if es:
            print(f"{stat:8s} selected={np.mean(sels):+7.1f}bp  "
                  f"edge-over-field={np.mean(es):+7.1f}bp  "
                  f"mean_rho={np.mean(rhos):+.3f}  (n_transitions={len(es)})")
    print("\nCompare edge-over-field to his +10.7 bp/RT. Convergence => frozen-pool inflation "
          "confirmed; our +159 was the survivor pool.")


if __name__ == "__main__":
    main()
