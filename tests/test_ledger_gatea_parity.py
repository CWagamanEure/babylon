"""P9d cross-lane parity: research.data.ledger MUST agree with markout_study.gate_a.

`research/data/ledger.py` deliberately RE-IMPLEMENTS the exact-tick position math instead of importing
`gate_a` (that duplication is what holds the firewall — the research lane must be reachable without
pulling the frozen lane in). The cost of duplication is drift risk: an edit to either copy could silently
diverge. `ledger.py`'s docstring promises "a cross-lane equality test (P9d) asserts they agree" — THIS is
that test. It is a verification harness (not production code of either lane), so importing both here does
not breach the firewall; it enforces it.

If this test fails, the two implementations have diverged — reconcile them (or update this test if the
divergence is intentional and documented).

Run:  .venv/bin/pytest tests/test_ledger_gatea_parity.py -q
"""
from __future__ import annotations
import pytest

from research.data import ledger
from markout_study.gate_a import common as gc
from markout_study.gate_a import episodes as ge

COINS = ["BTC", "ETH", "SOL", "HYPE"]
# decimal-string sizes spanning sub-tick noise, exact ticks, and large positions
SIZES = ["0", "0.00001", "0.5", "1", "1.23456", "1.234564", "1.234565", "10", "12345.6789", "0.999999995"]
# (q_before, signed_fill) tick pairs covering INCREASE / REDUCE / CLOSE / FLIP and both directions
QB_SF = [
    (0, 100), (0, -100),               # open long / short from flat
    (100, 50), (-100, -50),            # increase same side
    (100, -30), (-100, 30),            # reduce
    (100, -100), (-100, 100),          # exact close
    (100, -250), (-100, 250),          # flip through zero
    (100, -100), (1, -1),              # close to exactly zero
    (5, -5), (5, -3), (5, -8),         # small-magnitude edges
]


def test_szd_dicts_agree():
    assert dict(ledger.SZD) == dict(gc.SZD), "szDecimals diverged between lanes"


@pytest.mark.parametrize("coin", COINS)
@pytest.mark.parametrize("s", SIZES)
def test_ticks_agree(coin, s):
    assert ledger.ticks(s, coin) == gc.ticks(s, coin)


@pytest.mark.parametrize("coin", COINS)
@pytest.mark.parametrize("s", SIZES)
@pytest.mark.parametrize("side", ["B", "A"])
def test_signed_fill_ticks_agree(coin, s, side):
    assert ledger.signed_fill_ticks(side, s, coin) == gc.signed_ticks(side, s, coin)


@pytest.mark.parametrize("qb,sf", QB_SF)
def test_classify_agrees(qb, sf):
    # ledger.classify returns a Transition(.cls=...); gate_a.episodes.classify returns the class string.
    assert ledger.classify(qb, sf).cls == ge.classify(qb, sf)


def test_classify_agrees_random_grid():
    # dense sweep so a divergent branch can't hide between the hand-picked cases above
    for qb in range(-20, 21):
        for sf in range(-20, 21):
            if sf == 0:
                continue
            assert ledger.classify(qb, sf).cls == ge.classify(qb, sf), (qb, sf)


@pytest.mark.parametrize("h,expect", [(ledger.ZERO_HASH, True), ("0x" + "1" * 64, False)])
def test_is_zhash_agrees(h, expect):
    assert ledger.is_zhash(h) == gc.is_zhash(h) == expect


def test_is_liq_origin_agrees():
    w = "0xABCdef0000000000000000000000000000000001"
    assert ledger.is_liq_origin(w.lower(), w) == gc.is_liq_origin(w.lower(), w) is True
    assert ledger.is_liq_origin(None, w) == gc.is_liq_origin(None, w) is False
    assert ledger.is_liq_origin("0xffff", w) == gc.is_liq_origin("0xffff", w) is False


@pytest.mark.parametrize("d,expect", [("Net Child Vaults", True), ("Open Long", False), (None, False)])
def test_is_vault_agrees(d, expect):
    # ledger.is_vault tolerates None; gate_a.common.is_vault is typed str — compare on the string cases,
    # and assert ledger handles the None sentinel (a real fill can carry dir=None).
    if d is None:
        assert ledger.is_vault(d) is False
    else:
        assert ledger.is_vault(d) == gc.is_vault(d) == expect
