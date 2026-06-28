"""Re-derive each follow-wallet's skill from its fills, over a chosen window.

Skill = the wallet's per-round-trip realized return in basis points. We reconstruct
positions per coin from the fill stream (open → … → flat is one position; a sign
flip closes one and opens the next), summing HL's per-fill ``closedPnl`` for the
realized PnL and the opening notional for the denominator. The per-wallet statistic
is the MEDIAN per-position bps (robust to the fat right tail), matching the column
in ``follow_wallets.csv`` so the re-derived ranking can be sanity-checked against it.

CRITICAL (walk-forward): always derive skill on a TRAIN window and follow the top
quintile on a DISJOINT later window — ranking and testing on the same data is the
selection bias this is built to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

_FLAT = 1e-9


@dataclass(frozen=True, slots=True)
class WalletSkill:
    wallet: str
    median_bps: float
    mean_bps: float
    n_positions: int
    n_coins: int


def _coin_positions(px: list[float], sz: list[float], side: list[str],
                    closed: list[float]) -> list[tuple[float, float]]:
    """Round-trip positions for one coin → list of (realized_pnl, opening_notional)."""
    out: list[tuple[float, float]] = []
    pos = 0.0
    realized = 0.0
    open_notional = 0.0
    for p, s, sd, cl in zip(px, sz, side, closed, strict=True):
        delta = s if sd == "B" else -s
        if pos != 0.0 and (delta < 0) != (pos < 0):  # opposite sign → closing (maybe flip)
            realized += cl
            close_amt = min(abs(delta), abs(pos))
            leftover = abs(delta) - close_amt
            pos += close_amt if pos < 0 else -close_amt
            if abs(pos) < _FLAT:  # position fully closed
                if open_notional > 0:
                    out.append((realized, open_notional))
                realized, open_notional = 0.0, 0.0
                if leftover > _FLAT:  # flip → open the opposite side
                    open_notional += leftover * p
                    pos = leftover if delta > 0 else -leftover
        else:  # opening (same sign, or from flat)
            open_notional += abs(delta) * p
            pos += delta
            realized += cl  # ~0 on opens; harmless
    return out


def wallet_skill(wallet: str, df: pl.DataFrame) -> WalletSkill:
    """Skill stats for one wallet over the fills in ``df`` (already window-filtered)."""
    bps: list[float] = []
    coins = 0
    for _coin, g in df.sort("time").group_by("coin", maintain_order=True):
        positions = _coin_positions(
            g["px"].to_list(), g["sz"].to_list(), g["side"].to_list(), g["closedPnl"].to_list()
        )
        rets = [pnl / notion * 1e4 for pnl, notion in positions if notion > 0]
        if rets:
            coins += 1
            bps.extend(rets)
    if not bps:
        return WalletSkill(wallet, 0.0, 0.0, 0, 0)
    arr = np.asarray(bps, dtype=np.float64)
    return WalletSkill(wallet, float(np.median(arr)), float(arr.mean()), arr.size, coins)


def rank_wallets(
    fills_dir: Path, start_ms: int, end_ms: int, *, min_positions: int = 20
) -> pl.DataFrame:
    """Rank every fetched wallet by median per-position bps over [start_ms, end_ms].
    Wallets with < ``min_positions`` completed round-trips are dropped (noisy)."""
    rows = []
    for f in sorted(fills_dir.glob("*.parquet")):
        wallet = f.stem
        df = pl.read_parquet(f).filter(
            (pl.col("time") >= start_ms) & (pl.col("time") < end_ms)
        )
        if df.height == 0:
            continue
        sk = wallet_skill(wallet, df)
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
