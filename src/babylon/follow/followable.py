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
    open_events,
)


def load_price_lookups(candles_dir: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """coin → (candle open_times, closes) for at-or-before price lookups."""
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for f in sorted(candles_dir.glob("*.parquet")):
        df = pl.read_parquet(f).sort("time")
        out[f.stem] = (df["time"].to_numpy(), df["close"].to_numpy())
    return out


_CANDLE_MS = 3_600_000  # hourly candles (HL's finest with full history)


def _close_at(lookup: tuple[np.ndarray, np.ndarray], t: int) -> float | None:
    """Close of the last candle FULLY CLOSED by time ``t`` — NO look-ahead. A follower
    at ``t`` can only know prices through the most recently *completed* candle; the
    candle *containing* ``t`` doesn't close until up to an interval later, so pricing
    at its close (the old behaviour) read an end-of-hour price up to ~1h in the future."""
    times, closes = lookup
    i = int(np.searchsorted(times, t - _CANDLE_MS, side="right")) - 1
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


def followable_returns(
    df: pl.DataFrame, *, universe: set[str],
    lookups: dict[str, tuple[np.ndarray, np.ndarray]], lag_ms: int, min_hold_ms: int,
    before_ms: int | None = None, basket: tuple[np.ndarray, np.ndarray] | None = None,
    beta: float = 1.0, taker_only: bool = True, conviction_only: bool = True,
) -> np.ndarray:
    """Per-round-trip follower returns (bps), as `followable_skill` but returning the raw
    array — for selection ranking + Kelly weighting. `basket=None` ⇒ the DIRECTIONAL
    (deployed/gated) measure; pass a basket for the diagnostic neutralized series.
    `before_ms` restricts to round-trips fully CLOSED before it (the rolling-seam guard so a
    trade straddling T0 can't leak into training)."""
    bps: list[float] = []
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        c = str(coin)
        if c not in universe or c not in lookups:
            continue
        lookup = lookups[c]
        for p in _positions_for(g):
            if (taker_only and not p.taker_open) or (conviction_only and not p.conviction_open):
                continue
            if p.hold_ms < min_hold_ms:
                continue
            if before_ms is not None and p.exit_t >= before_ms:
                continue  # seam guard: only round-trips closed before T0
            ein = _close_at(lookup, p.entry_t + lag_ms)
            eout = _close_at(lookup, p.exit_t + lag_ms)
            if ein is None or eout is None:
                continue
            raw = p.direction * (eout / ein - 1.0) * 1e4
            if basket is not None:
                raw -= p.direction * beta * _basket_ret_bps(
                    basket, p.entry_t + lag_ms, p.exit_t + lag_ms)
            bps.append(raw)
    return np.asarray(bps, dtype=np.float64)


def markout_returns(
    df: pl.DataFrame, *,
    lookups: dict[str, tuple[np.ndarray, np.ndarray]], lag_ms: int, horizon_ms: int,
    universe: set[str] | None = None,
    before_ms: int | None = None, basket: tuple[np.ndarray, np.ndarray] | None = None,
    beta: float = 1.0, taker_only: bool = True, conviction_only: bool = True,
    drop_leading: bool = False,
) -> np.ndarray:
    """Per-ENTRY FIXED-HORIZON markout returns (bps) — the validated selection signal
    (see audit/EDGE_INVESTIGATION.md). For every position OPENING, mark the neutralized return
    from ``entry_t + lag_ms`` to ``entry_t + lag_ms + horizon_ms`` at candle close — regardless of
    when the wallet closes. This keeps never-closers and carries NO open/closed disposition bias,
    unlike ``followable_returns`` (round-trip, which the study showed yields no edge).

    ``universe=None`` (DEFAULT) prices every candle-priceable coin — this is what the validated
    study (`selci_fh`) did, so the default reproduces it EXACTLY. Pass an explicit ``universe`` ONLY
    to deliberately restrict the coin set (a different rule than was validated). [Change-audit A2:
    the prior mandatory ``universe`` arg silently dropped majors vs the validated array.]
    ``before_ms`` seam guard: include only entries whose FULL markout window finished before T0
    (``entry+lag+horizon < before_ms``), so a window straddling T0 can't leak into training.
    ``drop_leading`` excludes the first (startPos-seed-suspect) open per coin (Audit 11 sensitivity).
    ``basket=None`` ⇒ directional; pass a basket for the deployed NEUTRALIZED signal."""
    bps: list[float] = []
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        c = str(coin)
        if c not in lookups or (universe is not None and c not in universe):
            continue
        lookup = lookups[c]
        g = g.sort("time")
        for e in open_events(
            g["time"].to_numpy(), g["px"].to_numpy(), g["sz"].to_numpy(),
            g["side"].to_numpy(), g["crossed"].to_numpy(), g["startPosition"].to_numpy(),
            g["hash"].to_numpy() if "hash" in g.columns else None,
        ):
            if (taker_only and not e.taker_open) or (conviction_only and not e.conviction):
                continue
            if drop_leading and e.is_leading:
                continue
            end = e.entry_t + lag_ms + horizon_ms
            if before_ms is not None and end >= before_ms:
                continue  # seam guard: full markout window must finish before T0
            ein = _close_at(lookup, e.entry_t + lag_ms)
            eout = _close_at(lookup, end)
            if ein is None or eout is None:
                continue
            raw = e.direction * (eout / ein - 1.0) * 1e4
            if basket is not None:
                raw -= e.direction * beta * _basket_ret_bps(basket, e.entry_t + lag_ms, end)
            bps.append(raw)
    return np.asarray(bps, dtype=np.float64)


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
