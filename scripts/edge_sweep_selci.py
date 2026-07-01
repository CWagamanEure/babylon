"""Selection-aware bootstrap CI — settles Audit 07's zero-crossing question.

The original edge_sweep `_boot_ci` resamples the ALREADY-SELECTED top-N wallets, so its CI
ignores selection uncertainty (which wallets land in the top-N is itself random) → too narrow.

This script reports, per (lag, mode), BOTH:
  * CI_fixed  — original estimator (selection done once, resample selected arrays)   [too narrow]
  * CI_sel    — corrected: re-run selection INSIDE each bootstrap draw                [honest]
so you can read directly how much the interval widens and whether net excludes zero.

Memory-bounded by construction: per-wallet (train_skill scalar, test_array) are extracted ONCE
(tiny); each bootstrap draw only resamples wallet indices and transiently concatenates the small
test arrays. Holds nothing month-sized — runs in well under 1 GB. Reads ONLY the cheap per-wallet
files via ParquetFillsProvider; never the monthly parquets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.fills_source import ParquetFillsProvider
from babylon.follow.followable import load_price_lookups
from babylon.follow.skill import build_basket

# Reuse the exact extraction + pricing + skill from the validated sweep (identical estimator).
from edge_sweep import _skill, extract_positions, price  # type: ignore

_DAY_MS = 86_400_000


def boot_ci_fixed(sel_arrays, n_boot, rng, cost):
    """Original estimator: selection fixed, resample the selected per-wallet arrays (wallet-cluster)."""
    arrays = [a for a in sel_arrays if a.size]
    if len(arrays) < 2:
        return (float("nan"), float("nan"))
    idx = np.arange(len(arrays))
    means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(idx, size=len(arrays), replace=True)
        means[b] = np.concatenate([arrays[j] for j in pick]).mean() - cost
    return (float(np.percentile(means, 5)), float(np.percentile(means, 95)))


def boot_ci_selection(per_k, n_boot, rng, cost, top_n):
    """Corrected: each draw resamples eligible wallets WITHIN each transition, RE-RUNS selection
    (rank by train skill, take top-N) on the resampled set, pools selected test returns, averages
    the per-transition selected means, subtracts cost. per_k[k] = list of (trsk_scalar, ter_array).
    """
    means = np.full(n_boot, np.nan)
    for b in range(n_boot):
        per_k_sel = []
        for wallets in per_k:
            n = len(wallets)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=n)  # resample wallets with replacement
            picks = sorted(idx, key=lambda i: -wallets[i][0])[:top_n]  # re-select top-N by skill
            arrs = [wallets[i][1] for i in picks if wallets[i][1].size]
            if arrs:
                per_k_sel.append(float(np.concatenate(arrs).mean()))
        if per_k_sel:
            means[b] = float(np.mean(per_k_sel)) - cost
    lo, hi = float(np.nanpercentile(means, 5)), float(np.nanpercentile(means, 95))
    frac_pos = float(np.mean(means[~np.isnan(means)] > 0)) if np.any(~np.isnan(means)) else float("nan")
    return lo, hi, frac_pos


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
    ap.add_argument("--cost-bps", type=float, default=8.0)
    ap.add_argument("--lags", type=str, default="60000")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--stat", choices=["median", "sortino"], default="sortino")
    ap.add_argument("--max-wallets", type=int, default=0, help="0=all; >0 caps wallets/transition for a smoke")
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
          f"boot={args.boot} max_wallets={args.max_wallets or 'all'}\n")

    # One-time extraction (tiny per-wallet position lists).
    positions: dict[int, dict] = {}
    for k in range(len(bounds) - 1):
        t0, t1 = bounds[k], bounds[k + 1]
        train_lo = t0 - args.train_days * _DAY_MS
        pw = {}
        wl = univ[k][: args.max_wallets] if args.max_wallets else univ[k]
        for w in wl:
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
            sel_means, sel_arrays_pooled = [], []
            per_k = []  # corrected-CI input: per transition, list of (trsk, ter) for eligible wallets
            for k in range(len(bounds) - 1):
                trsk, ter = {}, {}
                for w, (tr, te) in positions[k].items():
                    trsk[w] = _skill(price(tr, lookups, lag, bk, args.beta), args.stat)
                    ter[w] = price(te, lookups, lag, bk, args.beta)
                elig = [w for w, (tr, te) in positions[k].items()
                        if len(tr) >= 2 and ter[w].size >= 1]
                if not elig:
                    per_k.append([])
                    continue
                top = sorted(elig, key=lambda w: -trsk[w])[: args.top_n]
                sel = np.concatenate([ter[w] for w in top]) if top else np.empty(0)
                if sel.size:
                    sel_means.append(sel.mean())
                sel_arrays_pooled.extend(ter[w] for w in top)
                per_k.append([(trsk[w], ter[w]) for w in elig])
            if not sel_means:
                continue
            sm = float(np.mean(sel_means))
            net = sm - args.cost_bps
            lo_f, hi_f = boot_ci_fixed(sel_arrays_pooled, args.boot, rng, args.cost_bps)
            lo_s, hi_s, fpos = boot_ci_selection(per_k, args.boot, rng, args.cost_bps, args.top_n)
            cross = "CROSSES 0" if lo_s <= 0 <= hi_s else ("ABOVE 0" if lo_s > 0 else "BELOW 0")
            print(f"lag={lag/1000:5.0f}s {mname:11s} sel={sm:+6.1f} net={net:+6.1f}")
            print(f"    CI_fixed (too narrow) [{lo_f:+6.1f}, {hi_f:+6.1f}]  width={hi_f-lo_f:5.1f}")
            print(f"    CI_sel   (corrected)  [{lo_s:+6.1f}, {hi_s:+6.1f}]  width={hi_s-lo_s:5.1f}"
                  f"  P(net>0)={fpos:.2f}  -> {cross}")
        print()


if __name__ == "__main__":
    main()
