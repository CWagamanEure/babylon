"""Fixed-horizon markout study — disposition-bias-free edge + OOS metric persistence.

Round-trip scoring throws away wallets that never close in-window (exactly the patient/informed
holder we'd want) and censors open-at-cutoff losers. This scores every POSITION OPENING by its
neutralized return over a FIXED horizon H (entry+lag -> entry+lag+H), regardless of when (or
whether) the wallet closes. No open/closed asymmetry => no disposition bias; never-closers kept.

Each open event also carries `is_leading` (the first open per coin, before any observed close) so
we can measure sensitivity to the startPosition=0 seeding artifact (Audit 11) WITHOUT silently
dropping never-closers.

Modes mirror selci2 (cache reused). extract sweeps several horizons in one pass (pricing is cheap;
the fill read is the cost). ci reports, per (horizon, mode), the selection-aware CI and net
zero-crossing — and is the harness the metric-panel persistence sweep will plug into.

Memory-bounded: chunked subprocesses (see run_selci_fh.sh); reads ONLY per-wallet files.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np

from babylon.follow.fills_source import ParquetFillsProvider
from babylon.follow.followable import _close_at, load_price_lookups
from babylon.follow.scheduler import _sortino
from babylon.follow.skill import _basket_ret_bps, build_basket, open_events as _skill_open_events

_HOUR_MS = 3_600_000


def _close_post(lookup, t, iv=_HOUR_MS):
    """Close of the candle (interval ``iv`` ms) CONTAINING ``t`` — strictly POST-fill pricing.
    The price timestamp (candle close) lies in (t, t+iv], so it can never read a price from
    before the leader's fill. Contrast `_close_at` (last candle fully closed by t), whose price
    timestamp lies in (t-iv, t] — on average iv/2 BEFORE t, i.e. before the fill for lags < iv/2
    (audit/edge3 F2: that stale pricing credits pre-fill run-up + leader impact to the follower).
    Returns (price, close_time_ms) so the basket leg can be aligned to the same instants, or
    None if ``t`` falls in a candle gap (delisting/halt) — bounded staleness in both directions."""
    times, closes = lookup
    i = int(np.searchsorted(times, t, side="right")) - 1
    if i < 0 or i >= closes.size:
        return None
    ct = int(times[i]) + iv
    if ct <= t:  # candle i closed before t: t is inside a gap, no containing candle
        return None
    px = float(closes[i])
    return (px, ct) if px > 0 else None


def _basket_at(basket, t0, t1, iv=_HOUR_MS):
    """Interval-aware clone of skill._basket_ret_bps (which hardcodes hourly): basket index at
    the last grid point fully closed by each t. When t is an exact candle-close instant (what
    `_close_post` returns), this picks exactly that candle's index point, keeping the beta leg
    aligned with the coin leg."""
    times, index = basket
    i0 = int(np.searchsorted(times, t0 - iv, side="right")) - 1
    i1 = int(np.searchsorted(times, t1 - iv, side="right")) - 1
    if i0 < 0 or i1 < 0 or i0 >= index.size or i1 >= index.size or index[i0] <= 0:
        return 0.0
    return float(index[i1] / index[i0] - 1.0) * 1e4


def _jobs(univ, n_k):
    return [(k, w) for k in range(n_k) for w in univ[k]]


def _load_cfg(args):
    univ = {int(k): v for k, v in json.loads(args.universe.read_text()).items()}
    bounds = [int(x) for x in args.boundaries.read_text().split(",")]
    return univ, bounds


def _open_events(times, px, sz, side, crossed, startpos, hashes):
    """Delegates to the SINGLE source of truth (babylon.follow.skill.open_events) so this study
    and live selection (followable.markout_returns) use identical code. Returns the legacy tuple
    shape this script's extract consumes."""
    return [(e.entry_t, e.direction, e.taker_open, e.conviction, e.is_leading, e.notional)
            for e in _skill_open_events(times, px, sz, side, crossed, startpos, hashes)]


def cmd_cache(args):
    lookups = load_price_lookups(args.candles_dir)
    basket = build_basket(args.candles_dir, sorted(set(lookups)))
    args.cache.write_bytes(pickle.dumps((lookups, basket)))
    print(f"cached {len(lookups)} coins + basket -> {args.cache}")


def cmd_njobs(args):
    univ, bounds = _load_cfg(args)
    print(len(_jobs(univ, len(bounds) - 1)))


def cmd_extract(args):
    univ, bounds = _load_cfg(args)
    jobs = _jobs(univ, len(bounds) - 1)[args.start : args.start + args.count]
    lookups, basket = pickle.loads(args.cache.read_bytes())
    coins = set(lookups)
    provider = ParquetFillsProvider(args.fills_dir)
    lags = [int(s * 1000) for s in args.lags]            # seconds -> ms
    horizons = [int(h * _HOUR_MS) for h in args.horizons]
    with args.out.open("a") as fh:
        for k, w in jobs:
            t0, t1 = bounds[k], bounds[k + 1]
            df = provider(w, t0 - args.train_days * 86_400_000, t1)
            if df.height == 0:
                continue
            events = []  # (coin, entry_t, dir, is_leading, notional)
            for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
                c = str(coin)
                if c not in coins:
                    continue
                g = g.sort("time")
                for et, d, topen, conv, lead, notl in _open_events(
                        g["time"].to_numpy(), g["px"].to_numpy(), g["sz"].to_numpy(),
                        g["side"].to_numpy(), g["crossed"].to_numpy(),
                        g["startPosition"].to_numpy(),
                        g["hash"].to_numpy() if "hash" in g.columns else None):
                    if topen and conv:
                        events.append((c, et, d, lead, notl))
            if not events:
                continue
            row = {"k": k, "w": w, "cells": {}}
            for lag in lags:
                for H in horizons:
                    tr_n, tr_t, te_n, te_lead, te_sz, te_t, te_coin = [], [], [], [], [], [], []
                    for c, et, d, lead, notl in events:
                        lk = lookups[c]
                        if args.pricing == "post":
                            pin = _close_post(lk, et + lag, args.candle_ms)
                            pout = _close_post(lk, et + lag + H, args.candle_ms)
                            if pin is None or pout is None:
                                continue
                            (ein, tin), (eout, tout) = pin, pout
                            neut = d * (eout / ein - 1.0) * 1e4 \
                                - d * args.beta * _basket_at(basket, tin, tout, args.candle_ms)
                        else:
                            ein = _close_at(lk, et + lag)
                            eout = _close_at(lk, et + lag + H)
                            if ein is None or eout is None:
                                continue
                            neut = d * (eout / ein - 1.0) * 1e4 \
                                - d * args.beta * _basket_ret_bps(basket, et + lag, et + lag + H)
                        end = et + lag + H
                        if end < t0:
                            tr_n.append(neut); tr_t.append(et)
                        elif t0 <= et + lag and end < t1:
                            te_n.append(neut); te_lead.append(lead)
                            te_sz.append(round(notl, 2)); te_t.append(et); te_coin.append(c)
                    key = f"L{int(lag // 1000)}_H{int(H // _HOUR_MS)}"
                    row["cells"][key] = {"tr": tr_n, "tr_t": tr_t, "te": te_n, "te_lead": te_lead,
                                         "te_sz": te_sz, "te_t": te_t, "te_coin": te_coin}
            fh.write(json.dumps(row) + "\n")
    print(f"[extract] jobs {args.start}..{args.start + len(jobs)} done -> {args.out}")


def _skill(arr, stat):
    a = np.asarray(arr, dtype=np.float64)
    if stat == "median":
        return float(np.median(a)) if a.size else -1e18
    return _sortino(a) if a.size >= 2 else -1e18


def _boot_sel(per_k, n_boot, rng, top_n):
    out = np.full(n_boot, np.nan)
    for b in range(n_boot):
        sel = []
        for wallets in per_k:
            n = len(wallets)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=n)
            picks = sorted(idx, key=lambda i: -wallets[i][0])[:top_n]
            arrs = [wallets[i][1] for i in picks if wallets[i][1].size]
            if arrs:
                sel.append(float(np.concatenate(arrs).mean()))
        if sel:
            out[b] = float(np.mean(sel))
    return out


def _boot_eof(per_k, n_boot, rng, top_n):
    """Bootstrap distribution of edge-OVER-field: each draw resamples wallets within each
    transition, recomputes (selected top-N mean) MINUS (field = all-eligible mean), averaged
    across transitions. Isolates OOS SELECTION SKILL from the population's absolute level."""
    out = np.full(n_boot, np.nan)
    for b in range(n_boot):
        eofs = []
        for wallets in per_k:
            n = len(wallets)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=n)
            field_arrs = [wallets[i][1] for i in idx if wallets[i][1].size]
            picks = sorted(idx, key=lambda i: -wallets[i][0])[:top_n]
            sel_arrs = [wallets[i][1] for i in picks if wallets[i][1].size]
            if field_arrs and sel_arrs:
                eofs.append(float(np.concatenate(sel_arrs).mean())
                            - float(np.concatenate(field_arrs).mean()))
        if eofs:
            out[b] = float(np.mean(eofs))
    return out


def _per_k_breakdown(per_k, top_n):
    """Per-transition (field_mean, selected_mean, edge_over_field). Point estimates."""
    rows = []
    for wallets in per_k:
        if not wallets:
            rows.append(None); continue
        field = np.concatenate([t[1] for t in wallets if t[1].size])
        top = sorted(wallets, key=lambda t: -t[0])[:top_n]
        sel = np.concatenate([t[1] for t in top if t[1].size])
        rows.append((float(field.mean()), float(sel.mean()), float(sel.mean() - field.mean())))
    return rows


def _metric_fns():
    """Pre-registered panel of train-window selection metrics (all computed on the SAME per-wallet
    fixed-horizon return array, so only the SORT KEY varies — eligibility is identical). Each maps a
    1-D array -> scalar skill (higher = better)."""
    def lower_ci(a):  # t-based lower bound of the mean (Audit-recommended: penalize noisy wallets)
        return float(a.mean() - 1.64 * a.std(ddof=1) / np.sqrt(a.size)) if a.size >= 2 else -1e18
    def trimmed(a):
        if a.size < 5:
            return -1e18
        lo, hi = np.percentile(a, [10, 90]); m = a[(a >= lo) & (a <= hi)]
        return float(m.mean()) if m.size else -1e18
    def sharpe(a):
        s = a.std(ddof=1) if a.size >= 2 else 0.0
        return float(a.mean() / s) if s > 1e-9 else -1e18
    def win_rate(a):
        return float((a > 0).mean()) if a.size else -1e18
    def profit_factor(a):
        pos, neg = a[a > 0].sum(), -a[a < 0].sum()
        return float(pos / neg) if neg > 1e-9 else (1e6 if pos > 0 else -1e18)
    def mean_minus_es(a):  # mean penalized by 5% expected shortfall (tail-aware)
        if a.size < 5:
            return -1e18
        es = a[a <= np.percentile(a, 5)].mean()
        return float(a.mean() + 0.5 * es)
    def n_trades(a):
        return float(a.size)
    def log_growth(a):  # geometric / compounding objective — drawdowns hurt (matches the gate)
        if a.size < 2:
            return -1e18
        g = 1.0 + a / 1e4
        if np.any(g <= 0):  # a <=-100% trade => ruin; reject hard
            return -1e18
        return float(np.mean(np.log(g)) * 1e4)
    def calmar(a):  # mean edge per unit of downside-semideviation tail (drawdown-aware, order-free)
        if a.size < 5:
            return -1e18
        dn = a[a < 0]
        sd = np.sqrt(np.mean(dn ** 2)) if dn.size else 1e-9
        return float(a.mean() / sd) if sd > 1e-9 else -1e18
    return {
        "log_growth": log_growth,
        "calmar": calmar,
        "mean": lambda a: float(a.mean()) if a.size else -1e18,
        "median": lambda a: float(np.median(a)) if a.size else -1e18,
        "trimmed10": trimmed,
        "sortino": lambda a: _sortino(a) if a.size >= 2 else -1e18,
        "sharpe": sharpe,
        "lower_ci": lower_ci,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "mean_minus_es": mean_minus_es,
        "n_trades": n_trades,
    }


def _persistence_fns():
    """Time-aware TRAIN-window selection metrics: take (returns, times) -> skill. Test whether a
    wallet's edge being RECENT or CONSISTENT (not just high) predicts OOS better than trimmed-mean.
    All causal (train window only)."""
    def _trim(a):
        if a.size < 5:
            return float(a.mean()) if a.size else -1e18
        lo, hi = np.percentile(a, [10, 90]); m = a[(a >= lo) & (a <= hi)]
        return float(m.mean()) if m.size else -1e18
    def recent_third(a, t):  # trimmed-mean over the most recent 1/3 of the train time span
        if a.size < 8:
            return -1e18
        cut = t.min() + (t.max() - t.min()) * 2 / 3
        r = a[t >= cut]
        return _trim(r) if r.size >= 3 else -1e18
    def recency_weighted(a, t):  # exponentially time-weighted mean (half-life = 1/4 of span)
        if a.size < 5:
            return -1e18
        span = max(t.max() - t.min(), 1)
        w = np.exp(-(t.max() - t) / (span / 4.0))  # newer = heavier (half-life ~ span/4)
        return float(np.average(a, weights=w))
    def consistency(a, t):  # min(early-half, late-half) trimmed edge — penalize collapsing edge
        if a.size < 10:
            return -1e18
        mid = np.median(t)
        e, l = a[t < mid], a[t >= mid]
        if e.size < 3 or l.size < 3:
            return -1e18
        return min(_trim(e), _trim(l))
    def rolling_pos(a, t):  # fraction of time-bins with positive trimmed edge (persistence)
        if a.size < 12:
            return -1e18
        bins = np.linspace(t.min(), t.max() + 1, 7)
        idx = np.digitize(t, bins)
        fr = [(_trim(a[idx == b]) > 0) for b in range(1, 7) if (idx == b).sum() >= 2]
        return float(np.mean(fr)) if fr else -1e18
    def trend(a, t):  # late-half minus early-half trimmed edge (improving = positive)
        if a.size < 10:
            return -1e18
        mid = np.median(t)
        e, l = a[t < mid], a[t >= mid]
        if e.size < 3 or l.size < 3:
            return -1e18
        return _trim(l) - _trim(e)
    return {"recent_third": recent_third, "recency_wt": recency_weighted,
            "consistency": consistency, "rolling_pos": rolling_pos, "trend": trend}


def cmd_persist(args):
    """Persistence-metric panel: does recency/consistency beat plain trimmed-mean OOS? Same pool,
    same eligibility, walk-forward 4 folds, ranked by OOS net log-growth. Includes trimmed-mean as
    the baseline to beat."""
    rows = [json.loads(l) for l in args.out.read_text().splitlines() if l.strip()]
    rng = np.random.default_rng(12345)
    n_k = max(r["k"] for r in rows) + 1
    key = args.cell
    lag_s = int(key[1:].split("_")[0]); H_h = int(key.split("_H")[1])
    base = [[] for _ in range(n_k)]  # (tr_returns, tr_times, te_returns)
    for r in rows:
        cell = r["cells"].get(key)
        if not cell or "tr_t" not in cell:
            continue
        tr = np.asarray(cell["tr"], dtype=np.float64)
        tt = np.asarray(cell["tr_t"], dtype=np.float64)
        te = np.asarray(cell["te"], dtype=np.float64)
        if tr.size >= args.min_train and te.size >= 1 and tt.size == tr.size:
            base[r["k"]].append((tr, tt, te))

    def _lg(arr, cost):
        g = 1.0 + (arr - cost) / 1e4; g = g[g > 0]
        return float(np.mean(np.log(g)) * 1e4) if g.size else -1e18

    def _trim_base(a):
        if a.size < 5:
            return float(a.mean()) if a.size else -1e18
        lo, hi = np.percentile(a, [10, 90]); m = a[(a >= lo) & (a <= hi)]
        return float(m.mean()) if m.size else -1e18

    fns = {"trimmed(baseline)": lambda a, t: _trim_base(a), **_persistence_fns()}
    print(f"PERSISTENCE PANEL @ lag={lag_s}s H={H_h}h  cost={args.cost}bp top_n={args.top_n} "
          f"min_train={args.min_train}  (walk-forward OOS, ranked by net log-growth)")
    print(f"eligible per fold: {[len(b) for b in base]}\n")
    print(f"{'metric':18s} {'net_loggrow':>11} {'arith_eof':>10} {'folds+':>7}  per_fold_net_lg")
    results = []
    for name, fn in fns.items():
        per_k = [[(fn(tr, tt), te) for tr, tt, te in b] for b in base]
        brk = _per_k_breakdown(per_k, args.top_n)
        eof = float(np.mean([b[2] for b in brk if b]))
        lg_folds = []
        for wallets in per_k:
            if not wallets:
                lg_folds.append(None); continue
            top = sorted(wallets, key=lambda t: -t[0])[: args.top_n]
            arr = np.concatenate([t[1] for t in top if t[1].size])
            lg_folds.append(_lg(arr, args.cost))
        lg_vals = [x for x in lg_folds if x is not None]
        net_lg = float(np.mean(lg_vals)) if lg_vals else -1e18
        npos = sum(1 for x in lg_vals if x > 0)
        results.append((net_lg, name, eof, npos, len(lg_vals),
                        [round(x) if x is not None else None for x in lg_folds]))
    for net_lg, name, eof, npos, nf, pf in sorted(results, reverse=True):
        flag = "  (baseline)" if "baseline" in name else ("  <-- beats baseline" if False else "")
        print(f"{name:18s} {net_lg:+11.2f} {eof:+10.1f} {npos:>4}/{nf}  {pf}{flag}")
    print()


def cmd_panel(args):
    """Compare selection metrics OOS at a fixed (lag, horizon) cell. Same pool, same eligibility,
    only the ranking changes. Reports per-metric OOS edge-over-field, fold consistency, bootstrap CI.
    A metric is only credible if it beats the pack AND is positive in all folds."""
    rows = [json.loads(l) for l in args.out.read_text().splitlines() if l.strip()]
    rng = np.random.default_rng(12345)
    n_k = max(r["k"] for r in rows) + 1
    key = args.cell
    lag_s = int(key[1:].split("_")[0]); H_h = int(key.split("_H")[1])
    # build the SHARED eligible set once: (train_array, test_array) per wallet per fold
    base = [[] for _ in range(n_k)]
    for r in rows:
        cell = r["cells"].get(key)
        if not cell:
            continue
        tr = np.asarray(cell["tr"], dtype=np.float64)
        te = np.asarray(cell["te"], dtype=np.float64)
        if tr.size >= args.min_train and te.size >= 1:
            base[r["k"]].append((tr, te))
    def _lg(arr, cost):  # net log-growth (bps-equiv) of a roster's pooled test returns
        g = 1.0 + (arr - cost) / 1e4
        g = g[g > 0]  # a ruinous trade contributes -inf; treat as removed-after-ruin floor
        return float(np.mean(np.log(g)) * 1e4) if g.size else -1e18

    def _field_lg(per_k, cost):
        vals = []
        for wallets in per_k:
            if wallets:
                vals.append(_lg(np.concatenate([t[1] for t in wallets if t[1].size]), cost))
        return float(np.mean(vals)) if vals else float("nan")

    fns = _metric_fns()
    print(f"METRIC PANEL @ lag={lag_s}s H={H_h}h  cost={args.cost}bp top_n={args.top_n} "
          f"min_train={args.min_train}  (neutralized, walk-forward OOS)")
    print(f"eligible per fold: {[len(b) for b in base]}")
    print("SORTED BY OOS NET LOG-GROWTH (the compounding objective — drawdowns penalized)\n")
    print(f"{'metric':14s} {'net_loggrow':>11} {'arith_eof':>10} {'folds_lg+':>9}  per_fold_net_lg")
    results = []
    for name, fn in fns.items():
        per_k = [[(fn(tr), te) for tr, te in b] for b in base]
        brk = _per_k_breakdown(per_k, args.top_n)
        eof = float(np.mean([b[2] for b in brk if b]))
        # per-fold selected roster net log-growth
        lg_folds = []
        for wallets in per_k:
            if not wallets:
                lg_folds.append(None); continue
            top = sorted(wallets, key=lambda t: -t[0])[: args.top_n]
            arr = np.concatenate([t[1] for t in top if t[1].size])
            lg_folds.append(_lg(arr, args.cost))
        lg_vals = [x for x in lg_folds if x is not None]
        net_lg = float(np.mean(lg_vals)) if lg_vals else -1e18
        npos = sum(1 for x in lg_vals if x > 0)
        results.append((net_lg, name, eof, npos, len(lg_vals),
                        [round(x) if x is not None else None for x in lg_folds]))
    field_lg = _field_lg([[(0.0, te) for _, te in b] for b in base], args.cost)
    for net_lg, name, eof, npos, nf, pf in sorted(results, reverse=True):
        flag = "  (baseline)" if name == "sortino" else ("  <-- clean" if npos == nf else "  <-- weak")
        print(f"{name:14s} {net_lg:+11.2f} {eof:+10.1f} {npos:>6}/{nf}  {pf}{flag}")
    print(f"\n  field net log-growth (no selection) = {field_lg:+.2f} bps/trade")
    print()


def cmd_coincost(args):
    """Per-coin cost attribution: does the edge hide in high-spread coins? Select top-50 by
    trimmed-mean (train), then net EACH selected test trade at its OWN coin's round-trip cost
    (spread_bps + 9bp fees) instead of a flat number. Compare flat-cost vs per-coin-cost net
    log-growth, and profile the selected trades' coin costs."""
    rows = [json.loads(l) for l in args.out.read_text().splitlines() if l.strip()]
    n_k = max(r["k"] for r in rows) + 1
    key = args.cell
    lag_s = int(key[1:].split("_")[0]); H_h = int(key.split("_H")[1])
    import polars as pl
    sp = pl.read_parquet(args.spreads)
    cost_of = {c: float(s) + 9.0 for c, s in zip(sp["coin"].to_list(), sp["spread_bps"].to_list())}
    default_cost = float(np.median(list(cost_of.values())))

    def _trim(a):
        if a.size < 5:
            return float(a.mean()) if a.size else -1e18
        lo, hi = np.percentile(a, [10, 90]); m = a[(a >= lo) & (a <= hi)]
        return float(m.mean()) if m.size else -1e18

    def _lg(arr):
        g = 1.0 + arr / 1e4; g = g[g > 0]
        return float(np.mean(np.log(g)) * 1e4) if g.size else -1e18

    # per fold: select top-50 by train trimmed-mean, gather selected test (edge, coin)
    flat_lg, coin_lg, all_costs, covered, n_trades = [], [], [], 0, 0
    for k in range(n_k):
        wallets = []
        for r in rows:
            if r["k"] != k:
                continue
            cell = r["cells"].get(key)
            if not cell or "te_coin" not in cell:
                continue
            tr = np.asarray(cell["tr"], dtype=np.float64)
            te = np.asarray(cell["te"], dtype=np.float64)
            if tr.size >= args.min_train and te.size >= 1:
                wallets.append((_trim(tr), te, cell["te_coin"]))
        if not wallets:
            continue
        top = sorted(wallets, key=lambda x: -x[0])[: args.top_n]
        edges, coins = [], []
        for _, te, tc in top:
            edges.extend(te.tolist()); coins.extend(tc)
        edges = np.asarray(edges)
        costs = np.asarray([cost_of.get(c, default_cost) for c in coins])
        covered += sum(c in cost_of for c in coins); n_trades += len(coins)
        all_costs.append(costs)
        flat_lg.append(_lg(edges - args.cost))          # flat cost
        coin_lg.append(_lg(edges - costs))               # per-coin cost
    ac = np.concatenate(all_costs)
    print(f"PER-COIN COST @ lag={lag_s}s H={H_h}h  top_n={args.top_n} (select by trimmed-mean)")
    print(f"selected trades={n_trades}  coin-cost coverage={covered/max(n_trades,1):.0%}")
    print(f"selected-trade cost profile (bps): p25={np.percentile(ac,25):.1f} "
          f"p50={np.percentile(ac,50):.1f} p75={np.percentile(ac,75):.1f} mean={ac.mean():.1f}\n")
    print(f"flat cost ({args.cost:.0f}bp):   net log-growth per fold = "
          f"{[round(x,1) for x in flat_lg]}  mean={np.mean(flat_lg):+.1f}")
    print(f"PER-COIN cost:        net log-growth per fold = "
          f"{[round(x,1) for x in coin_lg]}  mean={np.mean(coin_lg):+.1f}")
    folds_pos = sum(1 for x in coin_lg if x > 0)
    print(f"\n  per-coin net: {folds_pos}/{len(coin_lg)} folds positive  "
          f"-> {'SURVIVES real per-coin cost' if folds_pos == len(coin_lg) else 'FRAGILE'}")
    print()


def cmd_sizeedge(args):
    """Does a larger-than-usual bet carry more edge? For each wallet, normalize every test entry's
    notional by that wallet's OWN median (relative size), then bucket pooled entries by relative size
    and report mean neutralized edge per bucket. Also per-wallet Spearman(rel_size, edge)."""
    rows = [json.loads(l) for l in args.out.read_text().splitlines() if l.strip()]
    key = args.cell
    lag_s = int(key[1:].split("_")[0]); H_h = int(key.split("_H")[1])
    edges_by_bucket: dict[str, list] = {b: [] for b in ["<0.5x", "0.5-1x", "1-2x", "2-5x", ">5x"]}
    def bucket(r):
        return "<0.5x" if r < 0.5 else "0.5-1x" if r < 1 else "1-2x" if r < 2 else "2-5x" if r < 5 else ">5x"
    corrs = []
    n_wallets = 0
    for r in rows:
        cell = r["cells"].get(key)
        if not cell or "te_sz" not in cell:
            continue
        sz = np.asarray(cell["te_sz"], dtype=np.float64)
        ed = np.asarray(cell["te"], dtype=np.float64)
        if sz.size < args.min_train or np.median(sz) <= 0:
            continue
        n_wallets += 1
        rel = sz / np.median(sz)
        for rr, ee in zip(rel, ed):
            edges_by_bucket[bucket(rr)].append(ee)
        if sz.size >= 8:  # per-wallet rank correlation of size vs edge
            ar, ae = np.argsort(np.argsort(rel)), np.argsort(np.argsort(ed))
            c = np.corrcoef(ar, ae)[0, 1]
            if np.isfinite(c):
                corrs.append(c)
    print(f"SIZE-EDGE @ lag={lag_s}s H={H_h}h  (relative to each wallet's OWN median bet)")
    print(f"wallets={n_wallets}  per-wallet Spearman(size,edge): "
          f"mean={np.mean(corrs):+.3f} median={np.median(corrs):+.3f} "
          f"frac>0={np.mean(np.asarray(corrs) > 0):.2f}  (n={len(corrs)})\n")
    print(f"{'rel_size':10s} {'n':>8} {'mean_edge':>10} {'median':>8}")
    rng = np.random.default_rng(7)
    for b in ["<0.5x", "0.5-1x", "1-2x", "2-5x", ">5x"]:
        a = np.asarray(edges_by_bucket[b], dtype=np.float64)
        if a.size == 0:
            print(f"{b:10s} {0:>8}"); continue
        # bootstrap CI of the bucket mean
        boots = np.array([a[rng.integers(0, a.size, a.size)].mean() for _ in range(400)])
        lo, hi = np.percentile(boots, [5, 95])
        print(f"{b:10s} {a.size:>8} {a.mean():+10.1f} {np.median(a):+8.1f}  90%CI[{lo:+.1f},{hi:+.1f}]")
    print()


def cmd_ci(args):
    rows = [json.loads(l) for l in args.out.read_text().splitlines() if l.strip()]
    rng = np.random.default_rng(12345)
    n_k = max(r["k"] for r in rows) + 1
    cells = sorted({c for r in rows for c in r["cells"]},
                   key=lambda k: (int(k.split("_H")[1]), int(k[1:].split("_")[0])))
    print(f"rows={len(rows)} transitions={n_k} top_n={args.top_n} boot={args.boot} "
          f"stat={args.stat} cost={args.cost}bp drop_leading={args.drop_leading}  (NEUTRALIZED)\n")
    print("LAG-SENSITIVITY: real followable alpha SURVIVES lag; own-flow microstructure DECAYS.\n")
    for key in cells:
        lag_s = int(key[1:].split("_")[0]); H_h = int(key.split("_H")[1])
        per_k = [[] for _ in range(n_k)]
        for r in rows:
            cell = r["cells"].get(key)
            if not cell:
                continue
            trsk = _skill(cell["tr"], args.stat)
            te = np.asarray(cell["te"], dtype=np.float64)
            if args.drop_leading:
                lead = np.asarray(cell["te_lead"], dtype=bool)
                if lead.size == te.size and te.size:
                    te = te[~lead]
            if np.isfinite(trsk) and te.size >= 1:
                per_k[r["k"]].append((trsk, te))
        brk = _per_k_breakdown(per_k, args.top_n)
        if not any(brk):
            print(f"lag={lag_s:>4}s H={H_h}h: no eligible"); continue
        gross = float(np.mean([b[1] for b in brk if b]))
        net = _boot_sel(per_k, args.boot, rng, args.top_n)
        net = net[~np.isnan(net)] - args.cost
        nlo, nhi = np.percentile(net, 5), np.percentile(net, 95)
        be = _boot_eof(per_k, args.boot, rng, args.top_n)
        de = be[~np.isnan(be)]
        elo, ehi = np.percentile(de, 5), np.percentile(de, 95)
        eof = float(np.mean([b[2] for b in brk if b]))
        n_pos = sum(1 for b in brk if b and b[2] > 0); n_fold = sum(1 for b in brk if b)
        surv = "SURVIVES" if elo > 0 else "GONE"
        print(f"lag={lag_s:>4}s H={H_h}h: eof={eof:+6.1f} CI[{elo:+6.1f},{ehi:+6.1f}] {surv:8s} "
              f"folds+{n_pos}/{n_fold}  net@{args.cost:.0f}={(gross-args.cost):+6.1f}"
              f"[{nlo:+6.1f},{nhi:+6.1f}]  per_fold={[round(b[2]) if b else None for b in brk]}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["cache", "njobs", "extract", "ci", "panel", "sizeedge", "persist", "coincost"])
    ap.add_argument("--cell", type=str, default="L900_H6", help="panel: lag×horizon cell, e.g. L900_H6")
    ap.add_argument("--spreads", type=Path, default=Path("data/follow/spreads.parquet"))
    ap.add_argument("--min-train", type=int, default=5, help="panel: min train trades to be eligible")
    ap.add_argument("--fills-dir", type=Path, default=Path("data/follow/fills_his"))
    ap.add_argument("--candles-dir", type=Path, default=Path("data/follow/candles"))
    ap.add_argument("--universe", type=Path, default=Path("scratch_conv/universe_k.json"))
    ap.add_argument("--boundaries", type=Path, default=Path("scratch_conv/boundaries.txt"))
    ap.add_argument("--cache", type=Path, default=Path("scratch_conv/selci_cache.pkl"))
    ap.add_argument("--out", type=Path, default=Path("scratch_conv/selci_fh.jsonl"))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=10_000)
    ap.add_argument("--train-days", type=int, default=31)
    ap.add_argument("--top-n", type=int, default=50)
    ap.add_argument("--beta", type=float, default=1.245)
    ap.add_argument("--lags", type=float, nargs="+", default=[60, 300, 900, 1800],
                    help="detection+exec lags in SECONDS to sweep")
    ap.add_argument("--horizons", type=float, nargs="+", default=[1, 6])
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--stat", choices=["median", "sortino"], default="sortino")
    ap.add_argument("--cost", type=float, default=8.0)
    ap.add_argument("--drop-leading", action="store_true",
                    help="ci: exclude leading-open markouts (Audit 11 seeding sensitivity)")
    ap.add_argument("--candle-ms", type=int, default=_HOUR_MS,
                    help="extract: candle interval of --candles-dir/--cache in ms (post pricing)")
    ap.add_argument("--pricing", choices=["pre", "post"], default="pre",
                    help="extract: 'pre' = last fully-closed candle (legacy; price stamp in "
                         "(t-1h,t], on avg pre-fill for lag<30m); 'post' = containing-candle "
                         "close (strictly post-fill, stamp in (t,t+1h]; audit/edge3 F2)")
    args = ap.parse_args()
    {"cache": cmd_cache, "njobs": cmd_njobs, "extract": cmd_extract, "ci": cmd_ci,
     "panel": cmd_panel, "sizeedge": cmd_sizeedge, "persist": cmd_persist, "coincost": cmd_coincost}[args.mode](args)


if __name__ == "__main__":
    main()
