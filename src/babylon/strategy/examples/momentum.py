"""Time-series momentum — an aggressive *taker* trend follower.

Long when price is above its value ``lookback`` bars ago, short when below — it
crosses the spread to chase the trend, so the backtest's taker-only fill model is
faithful to it (a passive/mean-reversion strategy would be mis-modeled by taker
fills; see ``docs/BACKTEST.md``). Signals off top-of-book mid only (mode-agnostic);
emits a direction, the Sizer handles magnitude.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from babylon.engine.context import Context
from babylon.sizing.edge import BootstrapEdgeModel, EdgeModel
from babylon.strategy.base import Strategy


class Momentum(Strategy):
    def __init__(
        self,
        coin: str,
        *,
        lookback: int = 30,
        threshold: float = 0.0,
        prior_mean: float = 0.0,
        prior_std: float = 0.01,
        prior_strength: int = 10,
    ) -> None:
        super().__init__(name=f"mom_{coin}_{lookback}", universe=[coin])
        self._coin = coin
        self._lookback = lookback
        self._threshold = threshold
        self._hist: deque[float] = deque(maxlen=lookback + 1)
        self._prior = (prior_mean, prior_std, prior_strength)

    def make_edge_model(self, coin: str, rng: np.random.Generator) -> EdgeModel:
        mean, std, strength = self._prior
        return BootstrapEdgeModel.from_gaussian_prior(rng, mean=mean, std=std, strength=strength)

    def on_bar(self, ctx: Context) -> None:
        mid = ctx.mid(self._coin)
        if mid is None:
            return
        self._hist.append(float(mid))
        if len(self._hist) <= self._lookback:
            return  # warmup
        ret = self._hist[-1] / self._hist[0] - 1.0
        direction = 1.0 if ret > self._threshold else -1.0 if ret < -self._threshold else 0.0
        ctx.signal(self._coin, direction)
