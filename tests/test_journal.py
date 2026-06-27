from decimal import Decimal

import pytest

from babylon.core import Order, TimeInForce
from babylon.journal.journal import Journal, from_e8, to_e8


def _order(coin="BTC", size="1.5", cloid="r:BTC:1"):
    return Order(coin=coin, size=Decimal(size), price=None,
                 reduce_only=False, tif=TimeInForce.IOC, cloid=cloid)


def _journal(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.connect()
    j.begin_run("r1", started_ms=1000, network="testnet", seed=7, roster=["s1", "s2"])
    return j


def test_e8_roundtrip_exact():
    for s in ["0", "1.5", "-0.00000001", "60000.12345678", "-123.456"]:
        assert from_e8(to_e8(Decimal(s))) == Decimal(s)
    assert to_e8(None) is None and from_e8(None) is None


def test_order_then_fill_roundtrip(tmp_path):
    j = _journal(tmp_path)
    oid = j.record_order(_order(), {"s1": Decimal("1.0"), "s2": Decimal("0.5")},
                         run_id="r1", tick=1, now=1000, wall=1000)
    assert oid > 0
    j.record_fill(order_id=oid, cloid="r:BTC:1", coin="BTC", price=Decimal("60000"),
                  shares=[("s1", Decimal("1.0")), ("s2", Decimal("0.5"))],
                  run_id="r1", tick=1, now=1001, wall=1001)
    q = "SELECT strategy, size_e8, price_e8 FROM fills ORDER BY strategy"
    rows = j._c.execute(q).fetchall()
    assert rows == [("s1", to_e8(Decimal("1.0")), to_e8(Decimal("60000"))),
                    ("s2", to_e8(Decimal("0.5")), to_e8(Decimal("60000")))]
    sq = "SELECT status, filled_e8 FROM orders WHERE order_id=?"
    assert j._c.execute(sq, (oid,)).fetchone() == ("FILLED", to_e8(Decimal("1.5")))


def test_fill_replay_is_idempotent(tmp_path):
    j = _journal(tmp_path)
    oid = j.record_order(_order(), {"s1": Decimal("1.5")},
                         run_id="r1", tick=1, now=1000, wall=1000)
    # Re-inserting the SAME (seq, strategy) must be a no-op (ON CONFLICT DO NOTHING).
    j.record_fill(order_id=oid, cloid="r:BTC:1", coin="BTC", price=Decimal("60000"),
                  shares=[("s1", Decimal("1.5"))], run_id="r1", tick=1, now=1001, wall=1001)
    seq = j._c.execute("SELECT seq FROM fills").fetchone()[0]
    j._c.execute(
        "INSERT INTO fills(run_id,seq,ts_ms,coin,strategy,size_e8,price_e8) "
        "VALUES('r1',?,1,'BTC','s1',999,1) ON CONFLICT(seq,strategy) DO NOTHING", (seq,))
    rows = j._c.execute(
        "SELECT size_e8 FROM fills WHERE seq=? AND strategy='s1'", (seq,)).fetchall()
    assert rows == [(to_e8(Decimal("1.5")),)]  # original kept, dup dropped


def test_snapshot_single_cut_and_latest(tmp_path):
    j = _journal(tmp_path)
    j.snapshot(run_id="r1", applied_seq=5, ts_ms=1,
               parts={("ledger", ""): b"L1", ("edge", "BTC/s1"): b"E1"})
    j.snapshot(run_id="r1", applied_seq=12, ts_ms=2,
               parts={("ledger", ""): b"L2", ("edge", "BTC/s1"): b"E2"})
    got = j.latest_snapshot()
    assert got is not None
    applied_seq, parts = got
    assert applied_seq == 12
    # Latest snapshot has ALL components at the one cut (the v2 split bug).
    assert parts[("ledger", "")] == b"L2" and parts[("edge", "BTC/s1")] == b"E2"


def test_replay_after_seq_ordered(tmp_path):
    j = _journal(tmp_path)
    j.record_order(_order(cloid="r:BTC:1"), {"s1": Decimal("1")},
                   run_id="r1", tick=1, now=1, wall=1)
    j.record_order(_order(cloid="r:BTC:2"), {"s1": Decimal("1")},
                   run_id="r1", tick=2, now=2, wall=2)
    seqs = [seq for seq, _kind, _payload in j.replay_events(0)]
    assert seqs == sorted(seqs) and len(seqs) == 2


def test_flock_refuses_second_writer(tmp_path):
    j1 = Journal(tmp_path / "j.db")
    j1.connect()
    j2 = Journal(tmp_path / "j.db")
    with pytest.raises(RuntimeError, match="another writer"):
        j2.connect()
    j1.close()
