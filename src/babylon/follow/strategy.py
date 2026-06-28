"""FollowStrategy — one AGGREGATE consensus strategy that mirrors the followed
wallets' net positions.

Per the live-follow audit (docs/LIVE_FOLLOW.md §9b), v1 is a SINGLE strategy (not one
per wallet — that blows up the engine's O(S·C²) tick loop and the 1/N budget
deadband). Its per-coin signal is the **edge-weighted consensus** of the followed
wallets' position signs (read from the WalletWatcher), and its EdgeModel is FROZEN at
T0 (no online adaptation, so the forward measurement isn't contaminated). Per-wallet
attribution is reconstructed offline from the journaled watcher positions, not here.
"""

from __future__ import annotations

import numpy as np

from babylon.engine.context import Context
from babylon.follow.watcher import WalletWatcher
from babylon.sizing.edge import EdgeModel, FrozenEdge
from babylon.strategy.base import Strategy


class FollowStrategy(Strategy):
    def __init__(
        self, watcher: WalletWatcher, weights: dict[str, float], universe: list[str], *,
        edge_mean: float, edge_std: float, edge_strength: int = 20,
    ) -> None:
        super().__init__(name="follow", universe=sorted(set(universe)))
        self._watcher = watcher
        self._weights = weights  # wallet → frozen edge weight (Σ = 1)
        self._prior = (edge_mean, edge_std, edge_strength)

    def make_edge_model(self, coin: str, rng: np.random.Generator) -> EdgeModel:
        mean, std, strength = self._prior
        return FrozenEdge.from_gaussian(rng, mean=mean, std=std, strength=strength)

    def on_bar(self, ctx: Context) -> None:
        for coin in self.universe:
            c = self._watcher.consensus_sign(coin, self._weights)
            if c != 0.0:
                # Emit the consensus VALUE (sign = direction, |magnitude| ≤ 1 = how much
                # of the followed edge-weighted book agrees) so a FixedFractionSizer can
                # scale by conviction; the engine uses its sign for direction.
                ctx.signal(coin, c)
            # flat consensus → emit nothing (skip the engine's cold-edge path)
