"""Copy-portfolio backtest — what WE would have made following a set of wallets.

Hourly long-short simulation: each followed wallet i carries an edge weight w_i
(from its TRAIN-window skill). At each hour the wallets' net positions define a
consensus direction per coin — ``signal[c] = Σ_i w_i · sign(posᵢ[c])`` — which we
normalise to a constant gross exposure of ``kelly_fraction`` (fractional Kelly on
the wallets' edge, no leverage). We mark on hourly candle closes and charge
``cost_bps`` per side on every rebalance turnover. The resulting return series goes
through the same metrics + 'is-it-real' gate as every other Babylon backtest.

Honest scope: hourly rebalance (under-counts intra-hour churn → slightly optimistic
on cost); fills assumed at the candle close + a flat cost (no per-coin spread / real
fill); no funding/liquidation. A sanity-check on whether skill persists into
followable PnL, NOT validation — that's the live forward test.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.skill import rank_wallets
from babylon.stats.gate import GateResult, log_growth_gate
from babylon.stats.metrics import Metrics, compute_metrics

_HOUR_MS = 3_600_000


@dataclass(frozen=True, slots=True)
class CopyResult:
    n_wallets: int
    n_coins: int
    n_hours: int
    avg_gross: float  # mean deployed gross exposure (≤ kelly_fraction)
    turnover_per_day: float  # mean daily one-way turnover (× equity)
    cost_drag_total: float  # total log-growth lost to costs
    metrics: Metrics
    gate: GateResult


def _hourly_positions(fills: pl.DataFrame, hours: np.ndarray) -> dict[str, np.ndarray]:
    """Per-coin signed position of one wallet, sampled (forward-filled) on the grid."""
    out: dict[str, np.ndarray] = {}
    signed = pl.when(pl.col("side") == "B").then(pl.col("sz")).otherwise(-pl.col("sz"))
    fills = fills.with_columns(_signed=signed)
    for (coin,), g in fills.sort("time").group_by("coin", maintain_order=True):
        t = g["time"].to_numpy()
        cum = np.cumsum(g["_signed"].to_numpy())
        idx = np.searchsorted(t, hours, side="right") - 1
        out[str(coin)] = np.where(idx >= 0, cum[idx.clip(min=0)], 0.0)
    return out


def _price_grid(candles_dir: Path, coin: str, hours: np.ndarray) -> np.ndarray | None:
    f = candles_dir / f"{coin}.parquet"
    if not f.exists():
        return None
    df = pl.read_parquet(f).sort("time")
    t, c = df["time"].to_numpy(), df["close"].to_numpy()
    idx = np.searchsorted(t, hours, side="right") - 1
    px = np.where(idx >= 0, c[idx.clip(min=0)], np.nan)
    return px if np.isfinite(px).any() else None


def copy_backtest(
    edges: dict[str, float], fills_dir: Path, candles_dir: Path,
    start_ms: int, end_ms: int, *,
    kelly_fraction: float = 0.5, cost_bps: float = 20.0, equity0: float = 100_000.0,
) -> CopyResult:
    hours = np.arange(start_ms, end_ms, _HOUR_MS)
    h = hours.size
    # Edge weights: clip to ≥0 (don't follow a wallet's negative edge), normalise.
    ew = {w: max(0.0, e) for w, e in edges.items()}
    total = sum(ew.values()) or 1.0
    ew = {w: v / total for w, v in ew.items() if v > 0}

    signal: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(h))
    used_wallets = 0
    for wallet, weight in ew.items():
        f = fills_dir / f"{wallet}.parquet"
        if not f.exists():
            continue
        df = pl.read_parquet(f).filter((pl.col("time") >= start_ms) & (pl.col("time") < end_ms))
        if df.height == 0:
            continue
        used_wallets += 1
        for coin, pos in _hourly_positions(df, hours).items():
            signal[coin] += weight * np.sign(pos)

    # Keep only coins we have prices for.
    coins, prices = [], []
    for c in sorted(signal):
        px = _price_grid(candles_dir, c, hours)
        if px is not None:
            coins.append(c)
            prices.append(px)
    if not coins:
        return CopyResult(used_wallets, 0, h, 0.0, 0.0, 0.0,
                          compute_metrics(np.array([equity0])), log_growth_gate(np.array([]),
                          np.random.default_rng(0)))

    sig = np.column_stack([signal[c] for c in coins])  # [H, C] edge-weighted direction
    px = np.column_stack(prices)  # [H, C]
    px = _ffill_nan(px)
    gross = np.abs(sig).sum(axis=1)
    weight = kelly_fraction * np.divide(sig, np.where(gross > 0, gross, 1.0)[:, None])  # [H,C]

    ret = np.zeros_like(px)
    ret[:-1] = np.where(px[:-1] > 0, px[1:] / px[:-1] - 1.0, 0.0)
    ret = np.nan_to_num(ret)
    turnover = np.abs(np.diff(weight, axis=0, prepend=weight[:1])).sum(axis=1)
    gross_ret = (weight * ret).sum(axis=1)
    cost = cost_bps * 1e-4 * turnover
    port_ret = gross_ret - cost
    equity = equity0 * np.cumprod(1.0 + port_ret)

    cost_drag = float(np.log1p(gross_ret + 1e-12).sum() - np.log1p(port_ret).sum())
    return CopyResult(
        n_wallets=used_wallets, n_coins=len(coins), n_hours=h,
        avg_gross=float(np.abs(weight).sum(axis=1).mean()),
        turnover_per_day=float(turnover.mean() * 24),
        cost_drag_total=cost_drag,
        metrics=compute_metrics(equity),
        gate=log_growth_gate(port_ret, np.random.default_rng(0)),
    )


def run_walkforward(
    fills_dir: Path, candles_dir: Path,
    train: tuple[int, int], follow: tuple[int, int], *,
    min_positions: int = 20, **kw: float,
) -> tuple[CopyResult, int]:
    """Full pipeline: rank skill on the TRAIN window, follow the train-top-quintile
    on the FOLLOW window. Returns (result, n_pool) where n_pool is the ranked pool
    size the quintile was drawn from. The selector is the train ranking — NEVER the
    in-sample CSV."""
    rank = rank_wallets(fills_dir, *train, min_positions=min_positions)
    top = rank.filter(pl.col("top_quintile"))
    edges = {r["wallet"]: float(r["median_bps"]) for r in top.to_dicts()}
    result = copy_backtest(edges, fills_dir, candles_dir, follow[0], follow[1], **kw)
    return result, rank.height


def _ffill_nan(a: np.ndarray) -> np.ndarray:
    """Forward-fill NaNs down each column (a coin's price before its first candle)."""
    out = a.copy()
    for j in range(out.shape[1]):
        col = out[:, j]
        last = np.nan
        for i in range(col.size):
            if np.isnan(col[i]):
                col[i] = last
            else:
                last = col[i]
    return np.asarray(np.nan_to_num(out), dtype=np.float64)
