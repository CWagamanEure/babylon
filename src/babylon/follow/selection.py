"""Selection adapter — the real `returns_fn`/`cutoff_fn` for the RollScheduler.

At each roll T0 it fetches a candidate wallet's TRAIN-window fills (via an injected
provider — REST userFillsByTime live, or cached parquet) and turns them into the per-
round-trip DIRECTIONAL followable returns (followable.py) + the wallet's last train-window
tid (the seam-guard cutoff). This is the last real-data piece between the built system and
a live run; the provider is injected so it stays testable without the network.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import polars as pl

from babylon.follow.experiment import ExperimentConfig
from babylon.follow.followable import followable_returns, markout_returns

_DAY_MS = 86_400_000
# (wallet, start_ms, end_ms) -> the wallet's fills in [start, end); empty frame if none
FillsProvider = Callable[[str, int, int], pl.DataFrame]


class SelectionAdapter:
    def __init__(
        self, fills_provider: FillsProvider, *, universe: set[str],
        lookups: dict[str, tuple[np.ndarray, np.ndarray]], config: ExperimentConfig,
        basket: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> None:
        self._fp = fills_provider
        self._universe = set(universe)
        self._lookups = lookups
        self._cfg = config
        self._basket = basket          # None ⇒ directional (the gated measure)
        self._train_ms = config.train_days * _DAY_MS
        # SINGLE-entry cache: returns_fn + cutoff_fn for the SAME wallet share one read,
        # then it's evicted — so a roll holds ONE wallet's fills at a time, not all 1404
        # (the whole pool at once OOMs a small box). Requires the scheduler to process a
        # wallet's returns + cutoff consecutively.
        self._cache_key: tuple[str, int] | None = None
        self._cache_df: pl.DataFrame | None = None

    def set_lookups(self, lookups: dict[str, tuple[np.ndarray, np.ndarray]]) -> None:
        """Swap in fresh candle lookups for the next roll (live multi-month runs)."""
        self._lookups = lookups

    def set_basket(self, basket: tuple[np.ndarray, np.ndarray] | None) -> None:
        """Swap in a fresh neutralizing basket for the next roll (markout path)."""
        self._basket = basket

    def _df(self, wallet: str, t0_ms: int) -> pl.DataFrame:
        key = (wallet, t0_ms)
        if key != self._cache_key:                 # evict the previous wallet (bound memory)
            self._cache_df = self._fp(wallet, t0_ms - self._train_ms, t0_ms)
            self._cache_key = key
        assert self._cache_df is not None
        return self._cache_df

    def returns_fn(self, wallet: str, t0_ms: int) -> np.ndarray:
        df = self._df(wallet, t0_ms)
        if df is None or df.height == 0:
            return np.empty(0, dtype=np.float64)
        if self._cfg.selection_signal == "markout":
            # validated fixed-horizon edge: per-entry markout, NO universe gate (default None =
            # all candle coins = exactly the validated study), neutralized via the basket.
            return markout_returns(
                df, lookups=self._lookups, lag_ms=self._cfg.lag_bucket_ms,
                horizon_ms=self._cfg.markout_horizon_ms, before_ms=t0_ms,
                basket=self._basket, beta=self._cfg.beta)
        return followable_returns(
            df, universe=self._universe, lookups=self._lookups,
            lag_ms=self._cfg.lag_bucket_ms, min_hold_ms=self._cfg.min_hold_ms,
            before_ms=t0_ms, basket=self._basket, beta=self._cfg.beta)

    def activity_fn(self, wallet: str, t0_ms: int) -> int:
        """Raw FILL count in [t0−train, t0) — the disposition-free eligibility gate (a
        re-test showed gating on closed-round-trip count re-introduces disposition bias)."""
        df = self._df(wallet, t0_ms)
        if df is None or df.height == 0:
            return 0
        lo = t0_ms - self._train_ms
        return int(df.filter((pl.col("time") >= lo) & (pl.col("time") < t0_ms)).height)

    def cutoff_fn(self, wallet: str, t0_ms: int) -> int:
        df = self._df(wallet, t0_ms)
        if df is None or df.height == 0:
            return 0
        sub = df.filter(pl.col("time") < t0_ms)
        if sub.height == 0:
            return 0
        mx = sub["tid"].max()
        return int(mx) if isinstance(mx, (int, float)) else 0

    def reset(self) -> None:
        """Drop the per-roll fetch cache (call between rolls so a new T0 re-fetches)."""
        self._cache_key = None
        self._cache_df = None
