"""Synthetic fixtures for module 1 (episodes). Covers audit-flagged edge cases. Firewalled: no real data."""
import random
from decimal import Decimal
from gate_a.common import ticks, signed_ticks, is_liq_origin, MAJORS, SZD
from gate_a.episodes import build_episodes, classify, INCREASE, REDUCE, CLOSE, FLIP

NONZERO = "0x" + "1" * 64
ZERO = "0x" + "0" * 64
W = "0xAaA0000000000000000000000000000000000001"


def stream(coin, steps, init="0"):
    """Build a chained fill list; start_position is the exact running position before each fill."""
    pos = Decimal(init); out = []; ts0 = 1_000_000; tid = 1
    for s in steps:
        out.append(dict(ts=s.get("ts", ts0), side=s["side"], sz=s["sz"], px=s["px"],
                        start_position=str(pos), dir=s.get("dir", "Open Long"),
                        hash=s.get("hash", NONZERO), liq_user=s.get("liq_user"),
                        wallet=s.get("wallet", W), tid=s.get("tid", tid)))
        pos += Decimal(s["sz"]) if s["side"] == "B" else -Decimal(s["sz"])
        ts0 = s.get("ts", ts0) + s.get("dt", 60_000); tid += 1
    return out


# ---------- classify: exact-decimal zero-crossing (no epsilon) ----------
def test_classify_close_vs_one_ulp_reduce():
    # SOL szDecimals=2: 1.00 long, sell 0.99 -> residual 0.01 (1 ULP) => REDUCE, never CLOSE
    assert classify(ticks("1.00", "SOL"), signed_ticks("A", "0.99", "SOL")) == REDUCE
    # sell exactly 1.00 -> exactly flat => CLOSE
    assert classify(ticks("1.00", "SOL"), signed_ticks("A", "1.00", "SOL")) == CLOSE
    # add same side => INCREASE ; overshoot opposite => FLIP
    assert classify(ticks("1.00", "SOL"), signed_ticks("B", "0.50", "SOL")) == INCREASE
    assert classify(ticks("1.00", "SOL"), signed_ticks("A", "1.50", "SOL")) == FLIP


def test_float_noise_quantizes_to_exact():
    # archive float64 round-trip noise must quantize to the exact protocol value
    assert ticks("985263.5699999999", "HYPE") == ticks("985263.57", "HYPE") == 98526357
    # a noisy start_position that is really flat => classified from exactly-zero
    assert classify(ticks("0.0000000001", "HYPE"), signed_ticks("B", "1.00", "HYPE")) == INCREASE


# ---------- open / dust / gap ----------
def test_simple_open_close_one_episode():
    ep, q = build_episodes(stream("BTC", [
        {"side": "B", "sz": "1", "px": "60000"},      # open long $60k
        {"side": "A", "sz": "1", "px": "60000"}]), "BTC")   # close
    assert q is None and ep == [(1_000_000, 1)]


def test_dust_increase_never_opens():
    ep, q = build_episodes(stream("BTC", [{"side": "B", "sz": "0.001", "px": "60000"}]), "BTC")  # $60 < $100
    assert ep == []


def test_gap_extend_within_30min_vs_new_beyond():
    within = build_episodes(stream("BTC", [
        {"side": "B", "sz": "1", "px": "60000"},
        {"side": "B", "sz": "1", "px": "60000", "dt": 20 * 60_000}]), "BTC")[0]
    assert within == [(1_000_000, 1)]                     # extended -> one episode
    beyond = build_episodes(stream("BTC", [
        {"side": "B", "sz": "1", "px": "60000"},
        {"side": "B", "sz": "1", "px": "60000", "ts": 1_000_000 + 40 * 60_000}]), "BTC")[0]
    assert len(beyond) == 2                                # new episode past gap


def test_reduce_floor_is_peak_relative():
    # peak notional $2000 -> floor = max($100, 10%*2000=$200)
    # a $150 reduce is below floor -> episode NOT terminated -> later same-dir add extends (1 episode)
    one = build_episodes(stream("SOL", [
        {"side": "B", "sz": "100", "px": "20"},          # open $2000, peak 2000
        {"side": "A", "sz": "7.5", "px": "20"},          # reduce $150 < $200 floor -> no terminate
        {"side": "B", "sz": "1", "px": "20", "dt": 60_000}]), "SOL")[0]   # $20<dust? no: notional=$20<100 dust -> won't open anyway
    # use a >=$100 add to test extend vs new:
    one2 = build_episodes(stream("SOL", [
        {"side": "B", "sz": "100", "px": "20"},
        {"side": "A", "sz": "7.5", "px": "20"},          # $150 reduce, below floor
        {"side": "B", "sz": "10", "px": "20", "dt": 60_000}]), "SOL")[0]  # $200 add, same dir, within gap
    assert len(one2) == 1                                  # not terminated => extended
    two = build_episodes(stream("SOL", [
        {"side": "B", "sz": "100", "px": "20"},
        {"side": "A", "sz": "12.5", "px": "20"},         # $250 reduce >= $200 floor -> terminate
        {"side": "B", "sz": "10", "px": "20", "dt": 60_000}]), "SOL")[0]  # add after terminate -> new
    assert len(two) == 2


# ---------- flip + R1 dust-wins ----------
def test_flip_residual_above_dust_opens():
    ep = build_episodes(stream("SOL", [
        {"side": "B", "sz": "100", "px": "20"},          # long 100
        {"side": "A", "sz": "125", "px": "20"}]), "SOL")[0]  # flip to short 25 => residual $500
    assert len(ep) == 2 and ep[1][1] == -1                # prior terminated, new short opens


def test_flip_residual_below_dust_no_open_R1():
    ep = build_episodes(stream("SOL", [
        {"side": "B", "sz": "100", "px": "20"},          # long 100
        {"side": "A", "sz": "102", "px": "20"}]), "SOL")[0]  # flip to short 2 => residual $40 < $100
    assert ep == [(1_000_000, 1)]                          # only the original open; residual does NOT open


# ---------- flags: update ledger, never open; reduce still terminates ----------
def test_zhash_twap_does_not_open_but_reduce_terminates():
    # a zhash open must not create an episode
    ep = build_episodes(stream("BTC", [{"side": "B", "sz": "1", "px": "60000", "hash": ZERO}]), "BTC")[0]
    assert ep == []
    # unflagged open, then a flagged (zhash) reduce that meets the floor still terminates
    ep2 = build_episodes(stream("BTC", [
        {"side": "B", "sz": "1", "px": "60000"},
        {"side": "A", "sz": "1", "px": "60000", "hash": ZERO}]), "BTC")[0]
    assert ep2 == [(1_000_000, 1)]                         # opened once, then terminated (no re-open)


def test_vault_dir_does_not_open():
    ep = build_episodes(stream("HYPE", [
        {"side": "B", "sz": "100", "px": "25", "dir": "Net Child Vaults"}]), "HYPE")[0]
    assert ep == []


def test_liq_forced_suppressed_but_counterparty_opens():
    # forced party: liquidatedUser == wallet -> suppressed
    forced = build_episodes(stream("BTC", [
        {"side": "B", "sz": "1", "px": "60000", "liq_user": W}]), "BTC")[0]
    assert forced == []
    # counterparty: liquidatedUser != wallet -> ordinary fill, MUST open
    cp = build_episodes(stream("BTC", [
        {"side": "B", "sz": "1", "px": "60000", "liq_user": "0xDEADbeef" + "0" * 32}]), "BTC")[0]
    assert cp == [(1_000_000, 1)]


def test_liq_user_lowercase_hex_match():
    assert is_liq_origin(W.upper(), W.lower()) is True     # checksummed vs lowercase still matches


# ---------- quarantine ----------
def test_nonzero_first_qbefore_not_quarantined():
    # wallet starts the window already long 5 BTC -> exactly classifiable, NOT quarantined
    ep, q = build_episodes(stream("BTC", [
        {"side": "A", "sz": "1", "px": "60000"}], init="5"), "BTC")   # reduce a pre-existing long
    assert q is None                                       # <- the load-bearing negative case


def test_quarantine_missing_startpos():
    f = stream("BTC", [{"side": "B", "sz": "1", "px": "60000"}])
    f[0]["start_position"] = None
    assert build_episodes(f, "BTC")[1] == "missing_startpos"


def test_quarantine_chain_break():
    f = stream("BTC", [{"side": "B", "sz": "1", "px": "60000"}, {"side": "B", "sz": "1", "px": "60000"}])
    f[1]["start_position"] = "0.5"                          # should be 1.0
    assert build_episodes(f, "BTC")[1] == "chain_break"


def test_quarantine_self_cross_same_tid():
    f = stream("BTC", [{"side": "B", "sz": "1", "px": "60000", "tid": 42},
                       {"side": "A", "sz": "1", "px": "60000", "tid": 42}])
    assert build_episodes(f, "BTC")[1] == "self_cross_anomaly"


def test_quarantine_missing_hours():
    f = stream("BTC", [{"side": "B", "sz": "1", "px": "60000"}])
    assert build_episodes(f, "BTC", missing_hours=True)[1] == "missing_hourly_object"


# ---------- determinism ----------
def test_determinism():
    f = stream("SOL", [{"side": "B", "sz": "100", "px": "20"}, {"side": "A", "sz": "50", "px": "21"},
                       {"side": "A", "sz": "60", "px": "19"}])
    assert build_episodes(f, "SOL") == build_episodes(f, "SOL")


# ---------- property invariant: ledger identity + no mutation over random streams ----------
def _random_stream(coin, n, rng):
    """Random chained buys/sells (quantized to szDecimals), random flags. Always chain-consistent
    by construction, so a correct builder never quarantines it."""
    szd = SZD[coin]; pos = Decimal(0); out = []; ts = 1_000_000
    for i in range(n):
        side = rng.choice("BA")
        sz = (Decimal(rng.randint(1, 5000)) / (Decimal(10) ** rng.randint(0, szd)))
        sz = sz.quantize(Decimal(10) ** -szd)
        if sz == 0:
            sz = Decimal(10) ** -szd
        px = str(Decimal(rng.randint(1, 60000)))
        h = ("0x" + "0" * 64) if rng.random() < 0.1 else ("0x" + "1" * 64)
        lu = W if rng.random() < 0.05 else None
        d = "Net Child Vaults" if rng.random() < 0.02 else "Open Long"
        out.append(dict(ts=ts, side=side, sz=str(sz), px=px, start_position=str(pos),
                        dir=d, hash=h, liq_user=lu, wallet=W, tid=i + 1))
        pos += sz if side == "B" else -sz
        ts += rng.choice([60_000, 20 * 60_000, 40 * 60_000])
    return out


def test_ledger_invariant_property():
    rng = random.Random(20260706)                          # fixed seed -> deterministic property test
    for _ in range(600):
        coin = rng.choice(MAJORS)
        fills = _random_stream(coin, rng.randint(1, 25), rng)
        snapshot = [dict(f) for f in fills]
        eps, q = build_episodes(fills, coin)
        # (1) build_episodes NEVER mutates the position ledger / input fills
        assert fills == snapshot
        # (2) exact ledger identity holds for every step: q_after == start_position + signed_fill,
        #     and the chain is consistent so a well-formed stream is never quarantined
        for k in range(len(fills) - 1):
            qa = ticks(fills[k]["start_position"], coin) + signed_ticks(fills[k]["side"], fills[k]["sz"], coin)
            assert ticks(fills[k + 1]["start_position"], coin) == qa
        assert q is None
        # (3) determinism on a fresh copy
        assert build_episodes([dict(f) for f in fills], coin)[0] == eps
