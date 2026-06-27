"""Moving-average crossover — a toy strategy to exercise the pipeline end-to-end.

Long when the fast MA is above the slow MA, short when below. Emits only a
*direction*; the Sizer handles magnitude. Seeds a deliberately weak Gaussian edge
prior so it can size something on day one (a real strategy would seed from a
backtest).
"""

from __future__ import annotations

from collections import deque

import numpy as np

from babylon.engine.context import Context
from babylon.sizing.edge import BootstrapEdgeModel, EdgeModel
from babylon.strategy.base import Strategy


class MACrossover(Strategy):
    def __init__(
        self,
        coin: str,
        *,
        fast: int = 10,
        slow: int = 30,
        prior_mean: float = 0.0005,
        prior_std: float = 0.01,
        prior_n: int = 40,
    ) -> None:
        super().__init__(name=f"ma_{coin}_{fast}_{slow}", universe=[coin])
        self._coin = coin
        self._fast = fast
        self._slow = slow
        self._hist: deque[float] = deque(maxlen=slow)
        self._prior = (prior_mean, prior_std, prior_n)

    def make_edge_model(self, coin: str, rng: np.random.Generator) -> EdgeModel:
        mean, std, n = self._prior
        return BootstrapEdgeModel.from_gaussian_prior(rng, mean=mean, std=std, n=n)

    def on_bar(self, ctx: Context) -> None:
        mid = ctx.mid(self._coin)
        if mid is None:
            return
        self._hist.append(float(mid))
        if len(self._hist) < self._slow:
            return  # warmup
        prices = np.asarray(self._hist, dtype=np.float64)
        fast_ma = float(prices[-self._fast :].mean())
        slow_ma = float(prices.mean())
        direction = 1.0 if fast_ma > slow_ma else -1.0 if fast_ma < slow_ma else 0.0
        ctx.signal(self._coin, direction)
