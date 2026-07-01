"""Re-derive each follow-wallet's skill from its fills — measured correctly.

Skill = MEDIAN per-round-trip return in bps, MARKET-NEUTRALIZED against the
equal-weight liquid-alt basket (the raw number is mostly beta — big but fake; the
neutralized number is the real, smaller edge). A "position" is flat→open→…→flat
(or a sign flip) tracked in signed CONTRACTS with a RELATIVE flat tolerance
(absolute fails on billion-supply meme alts). Only TAKER-opened positions count
(crossing the spread = conviction; maker opens are liquidity provision and dilute).
Coins are restricted to the alt universe (majors/spot/junk leak noise).

neut_bps = dir·(coin_ret − β·basket_ret) over the hold, β default 1.

CRITICAL (walk-forward): rank skill on a TRAIN window, follow the top quintile on a
DISJOINT later window — selection on the same data is the bias this avoids.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

_REL_TOL = 1e-9  # flat when |net| < _REL_TOL · max|net| (relative — meme-coin safe)


ZERO_HASH = "0x" + "0" * 64  # TWAP slice / liquidation marker (mechanical, not conviction)


@dataclass(frozen=True, slots=True)
class Position:
    direction: int  # +1 long / -1 short
    entry_px: float
    exit_px: float
    entry_t: int
    exit_t: int
    taker_open: bool  # opening fill crossed the spread (conviction)
    conviction_open: bool = True  # opening fill has a real hash (not TWAP/liquidation)

    @property
    def raw_bps(self) -> float:
        if self.entry_px <= 0:
            return 0.0
        return self.direction * (self.exit_px - self.entry_px) / self.entry_px * 1e4

    @property
    def hold_ms(self) -> int:
        return self.exit_t - self.entry_t


@dataclass(frozen=True, slots=True)
class WalletSkill:
    wallet: str
    median_bps: float
    mean_bps: float
    n_positions: int
    n_coins: int


def reconstruct(
    times: np.ndarray, px: np.ndarray, sz: np.ndarray, side: np.ndarray,
    crossed: np.ndarray, startpos: np.ndarray | None = None,
    hashes: np.ndarray | None = None,
) -> list[Position]:
    """Round-trip positions for one coin (signed-contract state machine).

    Seeded from ``startpos[0]`` (the position BEFORE the first fill) — if the window
    opens mid-position the leading position's open is pre-window/unobserved, so it is
    reconstructed but NOT emitted (its entry basis is unknown). ``pos`` is reset to
    EXACT 0 on close so a within-tolerance float residual can't leak the prior
    position's entry_t/taker_open into the next one.

    The flat-tolerance is anchored to a RUNNING (causal) max|pos|, not the full-sequence
    cumsum max — so this batch reconstructor is bit-for-bit identical to the streaming
    ``capture.CoinStepper`` (a future-dependent tol can't be reproduced live; see
    test_capture_stepper's adversarial fuzz).
    """
    signed = np.where(side == "B", sz, -sz)
    out: list[Position] = []
    def _conv(i: int) -> bool:
        return hashes is None or str(hashes[i]) != ZERO_HASH

    pos = float(startpos[0]) if startpos is not None and startpos.size else 0.0
    maxabs = abs(pos)
    tol = max(_REL_TOL * maxabs, 1e-15)
    valid = abs(pos) < tol  # only emit positions whose open we actually observed
    en = es = xn = xs = 0.0  # entry/exit notional & size of the OPEN position
    et = 0
    topen = conv = False
    for i in range(times.size):
        d = float(signed[i])
        maxabs = max(maxabs, abs(pos + d))
        tol = max(_REL_TOL * maxabs, 1e-15)
        if pos == 0.0 or (d > 0) == (pos > 0):  # opening (from flat, or adding same side)
            if pos == 0.0:
                et, topen, conv, en, es, valid = (
                    int(times[i]), bool(crossed[i]), _conv(i), 0.0, 0.0, True)
            en += abs(d) * float(px[i])
            es += abs(d)
            pos += d
        else:  # opposite sign → closing (maybe a flip)
            held_dir = 1 if pos > 0 else -1
            close = min(abs(d), abs(pos))
            xn += close * float(px[i])
            xs += close
            pos += close if pos < 0 else -close
            if abs(pos) < tol:  # position closed
                if valid and es > 0 and xs > 0:
                    out.append(
                        Position(held_dir, en / es, xn / xs, et, int(times[i]), topen, conv))
                en = es = xn = xs = 0.0
                pos = 0.0  # exact flat — don't let a float residual stale the next open
                leftover = abs(d) - close
                if leftover > tol:  # flip → open the opposite side
                    et, topen, conv, valid = (
                        int(times[i]), bool(crossed[i]), _conv(i), True)
                    en, es = leftover * float(px[i]), leftover
                    pos = leftover if d > 0 else -leftover
    return out


def _positions_for(coin_group: pl.DataFrame) -> list[Position]:
    g = coin_group.sort("time")
    return reconstruct(
        g["time"].to_numpy(), g["px"].to_numpy(), g["sz"].to_numpy(),
        g["side"].to_numpy(), g["crossed"].to_numpy(), g["startPosition"].to_numpy(),
        g["hash"].to_numpy() if "hash" in g.columns else None,
    )


@dataclass(frozen=True, slots=True)
class OpenEvent:
    entry_t: int
    direction: int       # +1 long / -1 short
    taker_open: bool     # opening fill crossed the spread (conviction)
    conviction: bool     # opening fill has a real hash (not TWAP/liquidation)
    is_leading: bool     # first open per coin, BEFORE any observed close (startPos-seed suspect)
    notional: float      # |opening fill| * px — the bet size at entry
    tid: int = 0         # originating fill's trade id (0 when unknown, e.g. the offline study)


def open_events(
    times: np.ndarray, px: np.ndarray, sz: np.ndarray, side: np.ndarray,
    crossed: np.ndarray, startpos: np.ndarray | None = None,
    hashes: np.ndarray | None = None, tids: np.ndarray | None = None,
) -> list[OpenEvent]:
    """One event per POSITION OPENING (flat→position or flip) for one coin — the SINGLE source of
    truth shared by live selection (followable.markout_returns) and the offline study (selci_fh),
    so live ≡ validated by construction. Adds (same-side scale-in) do NOT emit (one entry signal
    per position). The flat-state machine is bit-for-bit identical to ``reconstruct``;
    ``is_leading`` flags the first open before any observed close (startPosition=0 seed, Audit 11),
    surfaced WITHOUT dropping never-closers."""
    signed = np.where(side == "B", sz, -sz)
    ev: list[OpenEvent] = []
    def _conv(i: int) -> bool:
        return hashes is None or str(hashes[i]) != ZERO_HASH
    def _tid(i: int) -> int:
        return int(tids[i]) if tids is not None else 0
    pos = float(startpos[0]) if startpos is not None and startpos.size else 0.0
    maxabs = abs(pos)
    tol = max(_REL_TOL * maxabs, 1e-15)
    seen_close = False
    for i in range(times.size):
        d = float(signed[i])
        maxabs = max(maxabs, abs(pos + d))
        tol = max(_REL_TOL * maxabs, 1e-15)
        if pos == 0.0 or (d > 0) == (pos > 0):              # open (from flat) or add same side
            if pos == 0.0:                                  # NEW position from flat
                ev.append(OpenEvent(int(times[i]), 1 if d > 0 else -1, bool(crossed[i]),
                                    _conv(i), not seen_close, abs(d) * float(px[i]), _tid(i)))
            pos += d
        else:                                               # opposite sign → closing (maybe a flip)
            close = min(abs(d), abs(pos))
            pos += close if pos < 0 else -close
            if abs(pos) < tol:                              # position closed
                seen_close = True
                pos = 0.0
                leftover = abs(d) - close
                if leftover > tol:                          # flip → open the opposite side (clean)
                    ev.append(OpenEvent(int(times[i]), 1 if d > 0 else -1, bool(crossed[i]),
                                        _conv(i), False, leftover * float(px[i]), _tid(i)))
                    pos = leftover if d > 0 else -leftover
    return ev


def wallet_skill(
    wallet: str, df: pl.DataFrame, *,
    universe: set[str], basket: tuple[np.ndarray, np.ndarray] | None,
    taker_only: bool = True, conviction_only: bool = True, min_hold_ms: int = 0,
    beta: float = 1.0,
) -> WalletSkill:
    """Median neutralized round-trip bps over taker-opened, non-TWAP positions in the
    universe. ``min_hold_ms`` restricts to holds at least that long (the followable
    subset)."""
    bps: list[float] = []
    coins = 0
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        if str(coin) not in universe:
            continue  # majors / spot / junk excluded
        got = False
        for p in _positions_for(g):
            if taker_only and not p.taker_open:
                continue
            if conviction_only and not p.conviction_open:
                continue  # TWAP slice / liquidation, not conviction
            if p.hold_ms < min_hold_ms:
                continue
            neut = p.raw_bps
            if basket is not None:
                neut -= p.direction * beta * _basket_ret_bps(basket, p.entry_t, p.exit_t)
            bps.append(neut)
            got = True
        coins += got
    if not bps:
        return WalletSkill(wallet, 0.0, 0.0, 0, 0)
    arr = np.asarray(bps, dtype=np.float64)
    return WalletSkill(wallet, float(np.median(arr)), float(arr.mean()), arr.size, coins)


def build_basket(candles_dir: Path, coins: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Equal-weight hourly return index of the given (liquid) coins → (times, index)."""
    series = {}
    for c in coins:
        f = candles_dir / f"{c}.parquet"
        if f.exists():
            df = pl.read_parquet(f).sort("time")
            series[c] = (df["time"].to_numpy(), df["close"].to_numpy())
    return basket_from_series(series)


def basket_from_series(
    series: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Equal-weight hourly return index from already-loaded (times, close) series → the same
    (times, index) build_basket returns. Lets the live runner neutralize against the candle
    lookups it already holds (no parquet re-read, tracks the per-roll refresh)."""
    if not series:
        return np.array([0]), np.array([1.0])
    grid = np.unique(np.concatenate([t for t, _ in series.values()]))
    rets = np.zeros(grid.size)
    counts = np.zeros(grid.size)
    for t, close in series.values():
        idx = np.searchsorted(grid, t)
        aligned = np.full(grid.size, np.nan)
        aligned[idx] = close
        aligned = _ffill(aligned)
        # NaN (not 0) before a coin's first candle so it's EXCLUDED from the
        # equal-weight average — counting a not-yet-listed coin's flat 0-returns
        # dilutes the basket and under-neutralizes across listing events.
        r = np.full(grid.size, np.nan)
        r[1:] = np.where(aligned[:-1] > 0, aligned[1:] / aligned[:-1] - 1.0, np.nan)
        good = np.isfinite(r)
        rets[good] += r[good]
        counts[good] += 1
    avg = np.where(counts > 0, rets / np.maximum(counts, 1), 0.0)
    return grid, np.cumprod(1.0 + avg)


def _basket_ret_bps(basket: tuple[np.ndarray, np.ndarray], t0: int, t1: int) -> float:
    times, index = basket
    # last FULLY-CLOSED hourly point at each end (no look-ahead — matches _close_at).
    i0 = int(np.searchsorted(times, t0 - 3_600_000, side="right")) - 1
    i1 = int(np.searchsorted(times, t1 - 3_600_000, side="right")) - 1
    if i0 < 0 or i1 < 0 or i0 >= index.size or i1 >= index.size or index[i0] <= 0:
        return 0.0
    return float(index[i1] / index[i0] - 1.0) * 1e4


def _ffill(a: np.ndarray) -> np.ndarray:
    last = np.nan
    for i in range(a.size):
        if np.isnan(a[i]):
            a[i] = last
        else:
            last = a[i]
    return a


def rank_wallets(
    fills_dir: Path, start_ms: int, end_ms: int, *,
    universe: set[str], basket: tuple[np.ndarray, np.ndarray] | None = None,
    taker_only: bool = True, conviction_only: bool = True, min_hold_ms: int = 0,
    beta: float = 1.0, min_positions: int = 20,
) -> pl.DataFrame:
    """Rank wallets by median neutralized bps over [start_ms, end_ms]."""
    rows = []
    for f in sorted(fills_dir.glob("*.parquet")):
        df = pl.read_parquet(f).filter(
            (pl.col("time") >= start_ms) & (pl.col("time") < end_ms)
        )
        if df.height == 0:
            continue
        sk = wallet_skill(f.stem, df, universe=universe, basket=basket,
                          taker_only=taker_only, conviction_only=conviction_only,
                          min_hold_ms=min_hold_ms, beta=beta)
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
        rank=pl.int_range(1, n + 1),
        top_quintile=pl.int_range(0, n) < (n // 5),
    )
