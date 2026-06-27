"""Per-strategy position recording: current holdings + historical fills, queryable."""

from decimal import Decimal

from babylon.journal.journal import Journal


def _journal(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1, network="testnet", seed=1, roster=["alpha", "beta"])
    return j


def test_register_strategy_and_query(tmp_path):
    j = _journal(tmp_path)
    j.register_strategy("alpha", universe=["BTC", "ETH"], budget=Decimal("0.6"),
                        status="paper", now=10)
    j.register_strategy("beta", universe=["SOL"], budget=Decimal("0.4"),
                        status="probation", now=10)
    strats = {s["strategy"]: s for s in j.strategies()}
    assert strats["alpha"]["universe"] == ["BTC", "ETH"]
    assert strats["alpha"]["budget"] == "0.6"
    assert strats["beta"]["status"] == "probation"
    # re-register bumps last_seen, keeps first_seen
    j.register_strategy("alpha", universe=["BTC"], budget=Decimal("0.7"), status="full", now=20)
    a = next(s for s in j.strategies() if s["strategy"] == "alpha")
    assert a["status"] == "full" and a["first_seen_ms"] == 10 and a["last_seen_ms"] == 20


def test_current_positions_per_strategy(tmp_path):
    j = _journal(tmp_path)
    j.register_strategy("alpha", universe=["BTC"], budget=Decimal("1"), status="paper", now=1)
    j.register_strategy("beta", universe=["BTC"], budget=Decimal("1"), status="paper", now=1)
    # alpha long 2 BTC, beta short 0.5 BTC (net 1.5 on the exchange; per-strat tracked)
    j.write_positions(applied_seq=5, ts_ms=2, rows=[
        ("alpha", "BTC", Decimal("2"), Decimal("60000"), Decimal("120")),
        ("beta", "BTC", Decimal("-0.5"), Decimal("61000"), Decimal("-10")),
    ])
    pos = {p["strategy"]: p for p in j.current_positions()}
    assert pos["alpha"]["size"] == Decimal("2") and pos["alpha"]["realized"] == Decimal("120")
    assert pos["beta"]["size"] == Decimal("-0.5")
    # filter to one strategy
    assert [p["coin"] for p in j.current_positions("alpha")] == ["BTC"]


def test_historical_fills_attributed_per_strategy(tmp_path):
    j = _journal(tmp_path)
    oid = j.record_order(
        _order(), {"alpha": Decimal("1"), "beta": Decimal("0.5")},
        run_id="r1", tick=1, now=100, wall=100,
    )
    j.record_fill(order_id=oid, cloid="r:BTC:1", coin="BTC", price=Decimal("60000"),
                  shares=[("alpha", Decimal("1")), ("beta", Decimal("0.5"))],
                  run_id="r1", tick=1, now=100, wall=100)
    j.record_fill(order_id=oid, cloid="r:BTC:1", coin="BTC", price=Decimal("60500"),
                  shares=[("alpha", Decimal("-1"))], run_id="r1", tick=2, now=200, wall=200)
    alpha_fills = j.fills_for("alpha")
    assert len(alpha_fills) == 2  # alpha's full trade history
    assert [f["size"] for f in alpha_fills] == [Decimal("-1"), Decimal("1")]  # newest first
    assert len(j.fills_for("beta")) == 1
    assert j.fills_for("alpha", coin="BTC")[0]["price"] == Decimal("60500")


def test_strategy_summary_rollup(tmp_path):
    j = _journal(tmp_path)
    j.register_strategy("alpha", universe=["BTC"], budget=Decimal("1"), status="paper", now=1)
    j.write_positions(applied_seq=1, ts_ms=1, rows=[
        ("alpha", "BTC", Decimal("1"), Decimal("60000"), Decimal("50")),
        ("alpha", "ETH", Decimal("0"), Decimal("0"), Decimal("25")),  # closed, realized kept
    ])
    oid = j.record_order(_order(), {"alpha": Decimal("1")}, run_id="r1", tick=1, now=1, wall=1)
    j.record_fill(order_id=oid, cloid="r:BTC:1", coin="BTC", price=Decimal("60000"),
                  shares=[("alpha", Decimal("1"))], run_id="r1", tick=1, now=1, wall=1)
    s = next(x for x in j.strategy_summary() if x["strategy"] == "alpha")
    assert s["n_fills"] == 1
    assert s["realized_pnl"] == Decimal("75")  # 50 + 25
    assert s["open_coins"] == 1  # BTC open, ETH closed


def _order():
    from babylon.core import Order, TimeInForce
    return Order(coin="BTC", size=Decimal("1.5"), price=None,
                 reduce_only=False, tif=TimeInForce.IOC, cloid="r:BTC:1")
