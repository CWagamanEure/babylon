"""Convergence — OUR followable measurement on HIS past-only universe (his monthly export).

Reshapes his taker/maker monthly fills into our per-wallet schema and runs followable_returns
per transition. See other_repo_notes/README.txt. Coverage caveat: we can only price the
symbol-named perps (his @N spot/index coins have no candles here) — ~73% of volume.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.followable import followable_returns, load_price_lookups
from babylon.follow.scheduler import _sortino
from babylon.follow.skill import ZERO_HASH, build_basket

_NOTES = Path("other_repo_notes")
_NONZERO = "0x" + "1" * 64
# transition k: (train month file, test month file, universe json key)
_TRANS = [
    ("fills_Feb.parquet", "fills_Mar.parquet", "transition_0_Feb->Mar"),
    ("fills_Mar.parquet", "fills_Apr.parquet", "transition_1_Mar->Apr"),
    ("fills_Apr.parquet", "fills_May.parquet", "transition_2_Apr->May"),
    ("fills_May.parquet", "fills_Jun.parquet", "transition_3_May->Jun"),
]


def _hash_expr() -> pl.Expr:
    # zhash True => zero-hash (TWAP/liquidation, non-conviction) => emit ZERO_HASH
    return pl.when(pl.col("zhash")).then(pl.lit(ZERO_HASH)).otherwise(pl.lit(_NONZERO)).alias("hash")


def reshape_month(path: Path, universe: set[str], priceable: set[str]) -> dict[str, pl.DataFrame]:
    """His one-row-per-trade taker/maker file -> {wallet: per-wallet fills in our schema}.
    A wallet's taker rows keep `side`+crossed=True; its maker rows flip `side`, crossed=False."""
    base = pl.scan_parquet(path).filter(pl.col("coin").is_in(list(priceable)))
    tk = base.filter(pl.col("taker").is_in(list(universe))).select(
        pl.col("taker").alias("wallet"), pl.col("ts").alias("time"), "coin", "px", "sz", "side",
        pl.lit(True).alias("crossed"), "tid", _hash_expr(), pl.lit(0.0).alias("startPosition"))
    mk = base.filter(pl.col("maker").is_in(list(universe))).select(
        pl.col("maker").alias("wallet"), pl.col("ts").alias("time"), "coin", "px", "sz",
        pl.when(pl.col("side") == "B").then(pl.lit("A")).otherwise(pl.lit("B")).alias("side"),
        pl.lit(False).alias("crossed"), "tid", _hash_expr(), pl.lit(0.0).alias("startPosition"))
    long = pl.concat([tk, mk]).collect(engine="streaming")
    # polars 1.x keys as_dict by a (value,) tuple; the callers index by bare wallet string.
    return {(k[0] if isinstance(k, tuple) else k): v
            for k, v in long.partition_by("wallet", as_dict=True).items()}


def _series(df: pl.DataFrame, priceable, lookups, basket, args):
    return followable_returns(df, universe=priceable, lookups=lookups, lag_ms=args.lag_ms,
                              min_hold_ms=args.min_hold_ms, before_ms=None, basket=basket,
                              beta=args.beta)


def _median(r):
    return float(np.median(r)) if r.size else -1e18


def _sort(r):
    return _sortino(r) if r.size >= 2 else -1e18


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candles-dir", type=Path, default=Path("data/follow/candles"))
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--lag-ms", type=int, default=60_000)
    ap.add_argument("--min-hold-ms", type=int, default=3_600_000)
    ap.add_argument("--beta", type=float, default=1.245)
    ap.add_argument("--neutralize", action="store_true")
    ap.add_argument("--only-k", type=int, default=-1, help="run a single transition (smoke)")
    args = ap.parse_args()

    lookups = load_price_lookups(args.candles_dir)
    priceable = set(lookups)
    his_coins = set(pl.scan_parquet(_NOTES / "fills_Feb.parquet")
                    .select(pl.col("coin").unique()).collect(engine="streaming")["coin"].to_list())
    priceable &= his_coins
    basket = build_basket(args.candles_dir, sorted(priceable)) if args.neutralize else None
    univ = {k: set(v) for k, v in json.loads((_NOTES / "past_univ.json").read_text()).items()}
    print(f"priceable_coins={len(priceable)}  neutralize={args.neutralize}  top_n={args.top_n}\n")

    rows = {"median": [], "sortino": []}
    for k, (trainf, testf, key) in enumerate(_TRANS):
        if args.only_k >= 0 and k != args.only_k:
            continue
        u = univ[key]
        train = reshape_month(_NOTES / trainf, u, priceable)
        # diagnostic on transition 0: zhash polarity (conviction should be the majority)
        if k == 0 or args.only_k == 0:
            zt = pl.scan_parquet(_NOTES / trainf).select(pl.col("zhash").mean()).collect(engine="streaming").item()
            print(f"[diag] zhash=True fraction in {trainf}: {zt:.3f} "
                  f"(expect SMALL if it marks TWAP/zero-hash)")
        tr_stat = {}
        for w, df in train.items():
            s = _series(df, priceable, lookups, basket, args)
            tr_stat[w] = (_median(s), _sort(s), s.size)
        del train
        test = reshape_month(_NOTES / testf, u, priceable)
        te_ret = {w: _series(df, priceable, lookups, basket, args) for w, df in test.items()}
        del test

        elig = [w for w in u if tr_stat.get(w, (0, 0, 0))[2] >= 2 and te_ret.get(w) is not None
                and te_ret[w].size >= 1]
        field = np.concatenate([te_ret[w] for w in elig]) if elig else np.empty(0)
        for si, name in enumerate(("median", "sortino")):
            ranked = sorted(elig, key=lambda w: -tr_stat[w][si])  # noqa: B023
            top = ranked[: args.top_n]
            sel = np.concatenate([te_ret[w] for w in top]) if top else np.empty(0)
            edge = float(sel.mean() - field.mean()) if sel.size and field.size else float("nan")
            print(f"k={k} {name:8s} elig={len(elig):4d} sel={sel.mean():+7.1f} "
                  f"field={field.mean():+7.1f} EDGE={edge:+7.1f}bp "
                  f"(sel_rt={sel.size}, field_rt={field.size})")
            rows[name].append(edge)

    print("\n=== POOLED edge-over-field (mean over transitions) ===")
    for name, es in rows.items():
        es = [e for e in es if np.isfinite(e)]
        if es:
            pos = sum(e > 0 for e in es)
            print(f"{name:8s} {np.mean(es):+7.1f}bp  (positive {pos}/{len(es)} transitions)  "
                  f"per-k={[round(e, 1) for e in es]}")
    print("\nHis ref: median +10.7, Sortino +9.6 (neutralized). Convergence toward ~+10-20 => "
          "our +159 was frozen-pool survivorship.")


if __name__ == "__main__":
    main()
