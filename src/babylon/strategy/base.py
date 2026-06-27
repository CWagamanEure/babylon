"""Strategy ABC.

A strategy expresses *direction* (via `ctx.signal`), never size — the Sizer
decides magnitude from the strategy's EdgeModel. ``edge_prior`` lets a strategy
seed its EdgeModel (e.g. from a backtest); the engine owns the model and updates
it with realized unit returns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from babylon.engine.context import Context
from babylon.sizing.edge import BootstrapEdgeModel, EdgeModel


class Strategy(ABC):
    def __init__(self, name: str, universe: list[str]) -> None:
        self.name = name
        self.universe = universe

    def make_edge_model(self, coin: str, rng: np.random.Generator) -> EdgeModel:
        """Construct this strategy's EdgeModel for a coin. Override to seed a
        backtest prior; default is an uninformative (cold-start ≈ 0) model."""
        return BootstrapEdgeModel()

    def on_start(self, ctx: Context) -> None:  # noqa: B027 — optional hook
        pass

    @abstractmethod
    def on_bar(self, ctx: Context) -> None:
        """Called each evaluation tick; emit directions via ``ctx.signal``."""

    def on_stop(self, ctx: Context) -> None:  # noqa: B027 — optional hook
        pass
