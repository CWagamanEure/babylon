import numpy as np

from babylon.follow.strategy import FollowStrategy
from babylon.follow.watcher import WalletWatcher
from babylon.sizing.edge import FrozenEdge


class _FakeSource:
    async def user_fills_by_time(self, a, s, e):
        return []

    async def clearinghouse_state(self, a):
        return {"assetPositions": []}


class _Ctx:
    def __init__(self):
        self.sig = {}

    def signal(self, coin, direction):
        self.sig[coin] = direction


def test_frozen_edge_does_not_adapt():
    e = FrozenEdge.from_gaussian(np.random.default_rng(0), mean=0.002, std=0.01, strength=20)
    before = e.estimate()
    for _ in range(100):
        e.update(-0.5)  # would crush a live model; frozen ignores it
    after = e.estimate()
    assert np.array_equal(before.draws, after.draws)
    assert after.n_effective == 20 and abs(float(after.draws.mean()) - 0.002) < 0.002


def test_frozen_edge_state_roundtrip():
    e = FrozenEdge.from_gaussian(np.random.default_rng(1), mean=0.001, std=0.02, strength=15)
    st = e.estimate()
    e2 = FrozenEdge([0.0], 0)
    e2.from_state(e.to_state())
    assert np.array_equal(e2.estimate().draws, st.draws) and e2.estimate().n_effective == 15


def test_follow_strategy_emits_edge_weighted_consensus():
    w = WalletWatcher(_FakeSource(), ["a", "b"], min_interval_s=0.0)
    w._pos = {"a": {"BTC": 5.0, "SOL": -1.0}, "b": {"BTC": 2.0, "SOL": 3.0}}
    strat = FollowStrategy(w, {"a": 0.6, "b": 0.4}, ["BTC", "SOL", "ETH"],
                           edge_mean=0.001, edge_std=0.01)
    ctx = _Ctx()
    strat.on_bar(ctx)  # type: ignore[arg-type]
    # consensus VALUE: BTC 0.6+0.4 = +1.0 ; SOL -0.6+0.4 = -0.2 ; ETH flat → no signal
    assert ctx.sig["BTC"] == 1.0 and abs(ctx.sig["SOL"] - (-0.2)) < 1e-12
    assert "ETH" not in ctx.sig


def test_fixed_fraction_sizer_ignores_edge_units():
    from decimal import Decimal

    from babylon.sizing.sizer import FixedFractionSizer
    s = FixedFractionSizer(per_coin_fraction=0.1)
    huge = FrozenEdge.from_gaussian(np.random.default_rng(0), mean=0.5, std=0.01, strength=20)
    # full consensus → 10% of budget regardless of the (huge) edge — no Kelly knife-edge
    sz = s.target_size(edge=huge.estimate(), direction=1.0,
                       budget_equity=Decimal(100_000), mark_price=Decimal(100))
    assert sz == Decimal(100)  # 0.1 × 100000 / 100
    # half-strength consensus, short → scaled by magnitude
    sz2 = s.target_size(edge=FrozenEdge([0.0], 0).estimate(), direction=-0.5,
                        budget_equity=Decimal(100_000), mark_price=Decimal(100))
    assert sz2 == Decimal(-50)
    # flat → no position
    assert s.target_size(edge=huge.estimate(), direction=0.0,
                         budget_equity=Decimal(100_000), mark_price=Decimal(100)) == Decimal(0)


def test_follow_strategy_edge_model_is_frozen():
    w = WalletWatcher(_FakeSource(), ["a"], min_interval_s=0.0)
    strat = FollowStrategy(w, {"a": 1.0}, ["BTC"], edge_mean=0.003, edge_std=0.01)
    m = strat.make_edge_model("BTC", np.random.default_rng(0))
    assert isinstance(m, FrozenEdge)
    e0 = m.estimate()
    m.update(1.0)
    assert np.array_equal(m.estimate().draws, e0.draws)  # no-op
