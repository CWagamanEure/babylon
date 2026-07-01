"""Memory-bounded selection-aware bootstrap (two-stage) — settles Audit 07's zero-crossing.

WHY two stages: polars retains ~50 MB/wallet of freed pool memory that macOS never reclaims,
so extracting the full ~6000 (transition,wallet) jobs in one process would need ~75 GB. Instead
we extract in CHUNKED SUBPROCESSES (each exits → OS reclaims all of it), persisting only the tiny
priced arrays, then run the bootstrap on those (cheap — the CI math was already proven light).

Modes:
  cache   — read the 191 candle files once, pickle (lookups, basket) to a cache file (~1s reload).
  njobs   — print the total number of (transition, wallet) jobs (deterministic order).
  extract — process jobs[start:start+count]; append one JSON line per eligible wallet:
            {k, w, dir:{trsk,ter[]}, neut:{trsk,ter[]}}. Reads ONLY per-wallet files.
  ci      — load all extract output; report, per mode, CI_fixed (selection-once) vs
            CI_sel (selection re-run inside each draw) and P(net>0) over a cost grid.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.fills_source import ParquetFillsProvider
from babylon.follow.followable import load_price_lookups
from babylon.follow.skill import Position, ZERO_HASH, _REL_TOL, build_basket
from edge_sweep import _skill, extract_positions, price  # identical estimator as the validated sweep

_DAY_MS = 86_400_000


def _jobs(univ: dict[int, list], n_k: int) -> list[tuple[int, str]]:
    """Deterministic flat job list over (transition, wallet)."""
    return [(k, w) for k in range(n_k) for w in univ[k]]


def _load_cfg(args):
    univ = {int(k): v for k, v in json.loads(args.universe.read_text()).items()}
    bounds = [int(x) for x in args.boundaries.read_text().split(",")]
    return univ, bounds


def cmd_cache(args):
    lookups = load_price_lookups(args.candles_dir)
    basket = build_basket(args.candles_dir, sorted(set(lookups)))
    args.cache.write_bytes(pickle.dumps((lookups, basket)))
    print(f"cached {len(lookups)} coins + basket -> {args.cache}")


def cmd_njobs(args):
    univ, bounds = _load_cfg(args)
    print(len(_jobs(univ, len(bounds) - 1)))


def _recon_open(times, px, sz, side, crossed, startpos, hashes):
    """skill.reconstruct, but ALSO returns the final OPEN lot (dir, entry_t, topen, conv) if the
    position is non-flat at the end of the window — so the caller can MTM it at the cutoff
    instead of silently dropping it (Audit 09 disposition fix). Body kept bit-for-bit identical
    to skill.reconstruct so closed RTs are unchanged."""
    signed = np.where(side == "B", sz, -sz)
    out, op_open = [], None
    def _conv(i):
        return hashes is None or str(hashes[i]) != ZERO_HASH
    pos = float(startpos[0]) if startpos is not None and len(startpos) else 0.0
    maxabs = abs(pos); tol = max(_REL_TOL * maxabs, 1e-15)
    valid = abs(pos) < tol
    en = es = xn = xs = 0.0; et = 0; topen = conv = False
    for i in range(times.size):
        d = float(signed[i]); maxabs = max(maxabs, abs(pos + d)); tol = max(_REL_TOL * maxabs, 1e-15)
        if pos == 0.0 or (d > 0) == (pos > 0):
            if pos == 0.0:
                et, topen, conv, en, es, valid = int(times[i]), bool(crossed[i]), _conv(i), 0.0, 0.0, True
            en += abs(d) * float(px[i]); es += abs(d); pos += d
        else:
            held_dir = 1 if pos > 0 else -1
            close = min(abs(d), abs(pos)); xn += close * float(px[i]); xs += close
            pos += close if pos < 0 else -close
            if abs(pos) < tol:
                if valid and es > 0 and xs > 0:
                    out.append(Position(held_dir, en / es, xn / xs, et, int(times[i]), topen, conv))
                en = es = xn = xs = 0.0; pos = 0.0
                leftover = abs(d) - close
                if leftover > tol:
                    et, topen, conv, valid = int(times[i]), bool(crossed[i]), _conv(i), True
                    en, es = leftover * float(px[i]), leftover
                    pos = leftover if d > 0 else -leftover
    if valid and es > 0 and abs(pos) > tol:  # dangling open lot at window end
        op_open = (1 if pos > 0 else -1, en / es, et, topen, conv)
    return out, op_open


def _extract_fixed(df, coins, lookups, min_hold_ms, t0, t1):
    """Leading-holdout (drop first RT/coin — Audit 11 proxy) + dangling-MTM at cutoff t1
    (Audit 09). Returns (train, test) lists of (coin, Position)."""
    tr, te = [], []
    if df.height == 0:
        return tr, te
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        c = str(coin)
        if c not in coins or c not in lookups:
            continue
        g = g.sort("time")
        closed, op_open = _recon_open(
            g["time"].to_numpy(), g["px"].to_numpy(), g["sz"].to_numpy(), g["side"].to_numpy(),
            g["crossed"].to_numpy(), g["startPosition"].to_numpy(),
            g["hash"].to_numpy() if "hash" in g.columns else None)
        closed = closed[1:]  # Audit 11: drop leading position (possible pre-window seed artifact)
        for p in closed:
            if not p.taker_open or not p.conviction_open or p.hold_ms < min_hold_ms:
                continue
            (tr if p.exit_t < t0 else te).append((c, p))  # closed RTs have exit_t < t1
        if op_open is not None:  # Audit 09: MTM the open lot at cutoff t1
            d, epx, et, topen, conv = op_open
            mtm = Position(d, epx, epx, et, t1, topen, conv)
            if topen and conv and mtm.hold_ms >= min_hold_ms:
                te.append((c, mtm))  # open-at-cutoff scored as a test observation
    return tr, te


def cmd_extract(args):
    univ, bounds = _load_cfg(args)
    jobs = _jobs(univ, len(bounds) - 1)[args.start : args.start + args.count]
    lookups, basket = pickle.loads(args.cache.read_bytes())
    coins = set(lookups)
    provider = ParquetFillsProvider(args.fills_dir)
    lag = args.lag
    with args.out.open("a") as fh:
        for k, w in jobs:
            t0, t1 = bounds[k], bounds[k + 1]
            df = provider(w, t0 - args.train_days * _DAY_MS, t1)
            if args.fixes:
                tr, te = _extract_fixed(df, coins, lookups, args.min_hold_ms, t0, t1)
            else:
                pos = extract_positions(df, coins, lookups, args.min_hold_ms)
                tr = [(c, p) for c, p in pos if p.exit_t < t0]
                te = [(c, p) for c, p in pos if t0 <= p.exit_t < t1]
            if not (tr or te):
                continue
            row = {"k": k, "w": w}
            for mode, bk in (("dir", None), ("neut", basket)):
                trsk = _skill(price(tr, lookups, lag, bk, args.beta), args.stat)
                ter = price(te, lookups, lag, bk, args.beta)
                row[mode] = {"trsk": trsk, "ter": ter.tolist()}
            fh.write(json.dumps(row) + "\n")
    print(f"[extract] jobs {args.start}..{args.start + len(jobs)} done -> {args.out}")


def _boot_fixed(sel_arrays, n_boot, rng):
    """Original: selection fixed; resample selected per-wallet arrays (wallet-cluster). Returns
    bootstrap distribution of the GROSS selected mean (cost subtracted later)."""
    arrays = [a for a in sel_arrays if a.size]
    if len(arrays) < 2:
        return np.full(n_boot, np.nan)
    idx = np.arange(len(arrays))
    out = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(idx, size=len(arrays), replace=True)
        out[b] = np.concatenate([arrays[j] for j in pick]).mean()
    return out


def _boot_sel(per_k, n_boot, rng, top_n):
    """Corrected: resample eligible wallets within each transition, RE-RUN top-N selection on the
    resample, average per-transition selected means. Returns bootstrap dist of the GROSS mean."""
    out = np.full(n_boot, np.nan)
    for b in range(n_boot):
        per_k_sel = []
        for wallets in per_k:
            n = len(wallets)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=n)
            picks = sorted(idx, key=lambda i: -wallets[i][0])[:top_n]
            arrs = [wallets[i][1] for i in picks if wallets[i][1].size]
            if arrs:
                per_k_sel.append(float(np.concatenate(arrs).mean()))
        if per_k_sel:
            out[b] = float(np.mean(per_k_sel))
    return out


def cmd_ci(args):
    rows = [json.loads(line) for line in args.out.read_text().splitlines() if line.strip()]
    rng = np.random.default_rng(12345)
    n_k = max(r["k"] for r in rows) + 1
    print(f"rows={len(rows)} transitions={n_k} top_n={args.top_n} boot={args.boot} "
          f"stat={args.stat} lag={args.lag/1000:.0f}s\n")
    for mode in ("dir", "neut"):
        per_k, sel_arrays, sel_means = [[] for _ in range(n_k)], [], []
        for r in rows:
            trsk = r[mode]["trsk"]
            ter = np.asarray(r[mode]["ter"], dtype=np.float64)
            # eligibility: >=2 train RTs (trsk finite) AND >=1 test RT
            if np.isfinite(trsk) and ter.size >= 1:
                per_k[r["k"]].append((trsk, ter))
        for wallets in per_k:
            if not wallets:
                continue
            top = sorted(wallets, key=lambda t: -t[0])[: args.top_n]
            arrs = [t[1] for t in top if t[1].size]
            if arrs:
                sel_means.append(float(np.concatenate(arrs).mean()))
                sel_arrays.extend(arrs)
        if not sel_means:
            print(f"{mode}: no eligible wallets")
            continue
        gross = float(np.mean(sel_means))
        bf = _boot_fixed(sel_arrays, args.boot, rng)
        bs = _boot_sel(per_k, args.boot, rng, args.top_n)
        print(f"=== {mode} ===  gross selected mean = {gross:+.1f} bp")
        for tag, dist in (("CI_fixed (too narrow)", bf), ("CI_sel   (corrected)", bs)):
            d = dist[~np.isnan(dist)]
            lo, hi = np.percentile(d, 5), np.percentile(d, 95)
            print(f"  {tag}: gross 90% CI [{lo:+6.1f}, {hi:+6.1f}]  width={hi-lo:5.1f}")
        # zero-crossing of NET over a cost grid, using the CORRECTED distribution
        ds = bs[~np.isnan(bs)]
        print("  NET zero-crossing (corrected CI), by round-trip cost:")
        for cost in args.costs:
            net = ds - cost
            lo, hi = np.percentile(net, 5), np.percentile(net, 95)
            verdict = "ABOVE 0" if lo > 0 else ("BELOW 0" if hi < 0 else "CROSSES 0")
            print(f"    cost={cost:5.1f}bp  net 90% CI [{lo:+6.1f}, {hi:+6.1f}]  "
                  f"P(net>0)={float(np.mean(net > 0)):.2f}  -> {verdict}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["cache", "njobs", "extract", "ci"])
    ap.add_argument("--fills-dir", type=Path, default=Path("data/follow/fills_his"))
    ap.add_argument("--candles-dir", type=Path, default=Path("data/follow/candles"))
    ap.add_argument("--universe", type=Path, default=Path("scratch_conv/universe_k.json"))
    ap.add_argument("--boundaries", type=Path, default=Path("scratch_conv/boundaries.txt"))
    ap.add_argument("--cache", type=Path, default=Path("scratch_conv/selci_cache.pkl"))
    ap.add_argument("--out", type=Path, default=Path("scratch_conv/selci_rows.jsonl"))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=10_000)
    ap.add_argument("--train-days", type=int, default=31)
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--min-hold-ms", type=int, default=3_600_000)
    ap.add_argument("--beta", type=float, default=1.245)
    ap.add_argument("--lag", type=int, default=60_000)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--stat", choices=["median", "sortino"], default="sortino")
    ap.add_argument("--costs", type=float, nargs="+", default=[8.0, 12.0, 16.0, 20.0])
    ap.add_argument("--fixes", action="store_true",
                    help="apply Audit 11 leading-holdout + Audit 09 dangling-MTM")
    args = ap.parse_args()
    {"cache": cmd_cache, "njobs": cmd_njobs, "extract": cmd_extract, "ci": cmd_ci}[args.mode](args)


if __name__ == "__main__":
    main()
