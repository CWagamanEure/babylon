"""Out-of-sample calibration of the FOLLOWABLE edge, with control arms.

The in-sample +90bp is measured on the May-Jun selection window — a prior, not
validation. This walk-forward is the next rung: rank wallets by followable skill on
a TRAIN window, then measure their FOLLOWABLE edge (candle-marked, lagged,
neutralized, taker, non-TWAP, ≥min_hold) on a DISJOINT FOLLOW window. The claim is
**top-quintile − control**, NOT top > 0 — because an up-alt regime makes everyone
positive. Control arms (same coins/window):
- bottom quintile (train) — if top ≈ bottom forward, selection has no predictive value.
- a random sample of the ranked pool — the "follow any long-hold wallet" null.

If top materially beats both controls out-of-sample, the live experiment is worth
building. If not, it isn't.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

from babylon.follow.followable import followable_skill, load_price_lookups, rank_followable
from babylon.follow.skill import build_basket


@dataclass(frozen=True, slots=True)
class OOSResult:
    n_ranked_train: int  # wallets with ≥min_positions followable round-trips on train
    n_measured_follow: int  # of those, how many also clear min on the follow window
    top_follow_median: float  # train-top-quintile median followable bps on FOLLOW
    bottom_follow_median: float  # train-bottom-quintile, on FOLLOW
    random_follow_median: float  # random-of-ranked, on FOLLOW
    top_minus_bottom: float
    top_minus_random: float
    top_follow_positive_frac: float
    rank_corr: float  # Spearman(train followable bps, follow followable bps)


def calibrate(
    fills_dir: Path, candles_dir: Path, universe: set[str],
    train: tuple[int, int], follow: tuple[int, int], *,
    lag_ms: int = 300_000, min_hold_ms: int = 3_600_000, beta: float = 1.0,
    min_positions: int = 10, liquid_spread_bps: float = 8.0,
    spreads: dict[str, float] | None = None, seed: int = 0,
) -> OOSResult:
    sp = spreads or {}
    liquid = [c for c in universe if sp.get(c, 0.0) < liquid_spread_bps] or list(universe)
    basket = build_basket(candles_dir, liquid)
    lookups = load_price_lookups(candles_dir)

    train_rank = rank_followable(
        fills_dir, *train, universe=universe, lookups=lookups, basket=basket,
        lag_ms=lag_ms, min_hold_ms=min_hold_ms, beta=beta, min_positions=min_positions)
    if train_rank.is_empty():
        return OOSResult(0, 0, 0, 0, 0, 0, 0, 0, 0)

    # Follow-window followable skill for each train-ranked wallet.
    follow_bps: dict[str, float] = {}
    for wallet in train_rank["wallet"].to_list():
        f = fills_dir / f"{wallet}.parquet"
        df = pl.read_parquet(f).filter(
            (pl.col("time") >= follow[0]) & (pl.col("time") < follow[1]))
        if df.height == 0:
            continue
        sk = followable_skill(wallet, df, universe=universe, lookups=lookups, basket=basket,
                              lag_ms=lag_ms, min_hold_ms=min_hold_ms, beta=beta)
        if sk.n_positions >= min_positions:
            follow_bps[wallet] = sk.median_bps

    j = train_rank.filter(pl.col("wallet").is_in(list(follow_bps))).with_columns(
        follow_bps=pl.col("wallet").replace_strict(follow_bps, default=None))
    if j.height < 5:
        return OOSResult(train_rank.height, j.height, 0, 0, 0, 0, 0, 0, 0)

    n = j.height
    top = j.filter(pl.col("top_quintile"))["follow_bps"].to_numpy()
    bottom = j.sort("median_bps")["follow_bps"].to_numpy()[: n // 5]
    rng = np.random.default_rng(seed)
    rand = j["follow_bps"].to_numpy()[rng.permutation(n)[: max(1, n // 5)]]
    tr = j["median_bps"].to_numpy()
    fo = j["follow_bps"].to_numpy()
    tm, bm, rm = float(np.median(top)), float(np.median(bottom)), float(np.median(rand))
    return OOSResult(
        n_ranked_train=train_rank.height, n_measured_follow=n,
        top_follow_median=tm, bottom_follow_median=bm, random_follow_median=rm,
        top_minus_bottom=tm - bm, top_minus_random=tm - rm,
        top_follow_positive_frac=float(np.mean(top > 0)) if top.size else 0.0,
        rank_corr=float(np.corrcoef(_rank(tr), _rank(fo))[0, 1]),
    )


@dataclass(frozen=True, slots=True)
class RollStep:
    train_start: int
    follow_start: int
    n: int
    top: float       # top-quintile followable median on this follow step
    bottom: float
    long_short: float  # top − bottom (the regime-neutral cross-sectional spread)


def rolling_calibrate(
    fills_dir: Path, candles_dir: Path, universe: set[str],
    start_ms: int, end_ms: int, *, train_ms: int, step_ms: int,
    lag_ms: int = 300_000, min_hold_ms: int = 3_600_000, beta: float = 1.0,
    min_positions: int = 6, liquid_spread_bps: float = 8.0,
    spreads: dict[str, float] | None = None,
) -> list[RollStep]:
    """Walk-forward with ROLLING re-selection: each step, re-rank on the trailing
    ``train_ms`` window and measure the (re-selected) top/bottom quintiles' FOLLOWABLE
    edge on the next ``step_ms``. Tests both the rolling-informed-list idea and the
    long-short (top−bottom) spread per regime — reusing the SAME measurement, no
    pipeline reproduction. The basket/lookups are built once."""
    sp = spreads or {}
    liquid = [c for c in universe if sp.get(c, 0.0) < liquid_spread_bps] or list(universe)
    basket = build_basket(candles_dir, liquid)
    lookups = load_price_lookups(candles_dir)

    def follow_med(wallets: list[str], window: tuple[int, int]) -> dict[str, float]:
        out: dict[str, float] = {}
        for w in wallets:
            df = pl.read_parquet(fills_dir / f"{w}.parquet").filter(
                (pl.col("time") >= window[0]) & (pl.col("time") < window[1]))
            if df.height == 0:
                continue
            sk = followable_skill(w, df, universe=universe, lookups=lookups, basket=basket,
                                  lag_ms=lag_ms, min_hold_ms=min_hold_ms, beta=beta)
            if sk.n_positions >= min_positions:
                out[w] = sk.median_bps
        return out

    steps: list[RollStep] = []
    t = start_ms
    while t + train_ms + step_ms <= end_ms:
        train, follow = (t, t + train_ms), (t + train_ms, t + train_ms + step_ms)
        rank = rank_followable(
            fills_dir, *train, universe=universe, lookups=lookups, basket=basket,
            lag_ms=lag_ms, min_hold_ms=min_hold_ms, beta=beta, min_positions=min_positions)
        if not rank.is_empty():
            fb = follow_med(rank["wallet"].to_list(), follow)
            j = rank.filter(pl.col("wallet").is_in(list(fb))).with_columns(
                fbps=pl.col("wallet").replace_strict(fb, default=None)).sort("median_bps",
                                                                             descending=True)
            if j.height >= 10:
                q = j.height // 5
                top = float(np.median(j["fbps"].to_numpy()[:q]))
                bot = float(np.median(j["fbps"].to_numpy()[-q:]))
                steps.append(RollStep(t, follow[0], j.height, top, bot, top - bot))
        t += step_ms
    return steps


def _rank(a: np.ndarray) -> np.ndarray:
    order = a.argsort()
    r = np.empty_like(order, dtype=np.float64)
    r[order] = np.arange(a.size, dtype=np.float64)
    return r
