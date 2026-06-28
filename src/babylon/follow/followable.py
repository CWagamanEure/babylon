"""The FOLLOWABLE edge — what a real follower earns, not the wallet's own edge.

The wallet's per-round-trip return is priced at their own (sub-second) fill. A
follower sees the trade `lag` later and enters/exits at the market price THEN — so
the honest number marks entry at the candle close at `entry_t + lag` and exit at
`exit_t + lag`, neutralized against the alt basket over that window. The swarm
showed this is the crux: marking a >8h edge at candle-close + lag instead of the
wallet's fill collapses it toward the cost floor for HFT wallets — the whole point
of selecting LONG-HOLD wallets is that this collapse is small for multi-hour holds.

Restricted to taker-opened, non-TWAP, ≥ `min_hold_ms` positions in the universe.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.skill import (
    WalletSkill,
    _basket_ret_bps,
    _positions_for,
)


def load_price_lookups(candles_dir: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """coin → (candle open_times, closes) for at-or-before price lookups."""
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for f in sorted(candles_dir.glob("*.parquet")):
        df = pl.read_parquet(f).sort("time")
        out[f.stem] = (df["time"].to_numpy(), df["close"].to_numpy())
    return out


def _close_at(lookup: tuple[np.ndarray, np.ndarray], t: int) -> float | None:
    """Close of the candle in effect at time ``t`` (most recent at-or-before)."""
    times, closes = lookup
    i = int(np.searchsorted(times, t, side="right")) - 1
    if i < 0 or i >= closes.size:
        return None
    px = float(closes[i])
    return px if px > 0 else None


def followable_skill(
    wallet: str, df: pl.DataFrame, *,
    universe: set[str], lookups: dict[str, tuple[np.ndarray, np.ndarray]],
    basket: tuple[np.ndarray, np.ndarray] | None,
    lag_ms: int, min_hold_ms: int, beta: float = 1.0,
    taker_only: bool = True, conviction_only: bool = True,
) -> WalletSkill:
    """Median neutralized FOLLOWER return (candle-close, lagged) per round-trip."""
    bps: list[float] = []
    coins = 0
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        c = str(coin)
        if c not in universe or c not in lookups:
            continue
        lookup = lookups[c]
        got = False
        for p in _positions_for(g):
            if (taker_only and not p.taker_open) or (conviction_only and not p.conviction_open):
                continue
            if p.hold_ms < min_hold_ms:
                continue
            ein = _close_at(lookup, p.entry_t + lag_ms)
            eout = _close_at(lookup, p.exit_t + lag_ms)
            if ein is None or eout is None:
                continue  # follower couldn't have priced it
            raw = p.direction * (eout / ein - 1.0) * 1e4
            if basket is not None:
                raw -= p.direction * beta * _basket_ret_bps(
                    basket, p.entry_t + lag_ms, p.exit_t + lag_ms)
            bps.append(raw)
            got = True
        coins += got
    if not bps:
        return WalletSkill(wallet, 0.0, 0.0, 0, 0)
    arr = np.asarray(bps, dtype=np.float64)
    return WalletSkill(wallet, float(np.median(arr)), float(arr.mean()), arr.size, coins)


def rank_followable(
    fills_dir: Path, start_ms: int, end_ms: int, *,
    universe: set[str], lookups: dict[str, tuple[np.ndarray, np.ndarray]],
    basket: tuple[np.ndarray, np.ndarray] | None = None,
    lag_ms: int = 300_000, min_hold_ms: int = 3_600_000, beta: float = 1.0,
    min_positions: int = 10,
) -> pl.DataFrame:
    """Rank wallets by median followable bps (default: 5-min lag, ≥1h holds)."""
    rows = []
    for f in sorted(fills_dir.glob("*.parquet")):
        df = pl.read_parquet(f).filter(
            (pl.col("time") >= start_ms) & (pl.col("time") < end_ms)
        )
        if df.height == 0:
            continue
        sk = followable_skill(
            f.stem, df, universe=universe, lookups=lookups, basket=basket,
            lag_ms=lag_ms, min_hold_ms=min_hold_ms, beta=beta)
        if sk.n_positions >= min_positions:
            rows.append(sk)
    if not rows:
        return pl.DataFrame()
    out = pl.DataFrame([{
        "wallet": s.wallet, "median_bps": s.median_bps, "mean_bps": s.mean_bps,
        "n_positions": s.n_positions, "n_coins": s.n_coins,
    } for s in rows]).sort("median_bps", descending=True)
    n = out.height
    return out.with_columns(
        rank=pl.int_range(1, n + 1), top_quintile=pl.int_range(0, n) < (n // 5))
