import numpy as np

from babylon.follow.capture.stepper import Close, CoinStepper, Open, reconstruct_via_stepper
from babylon.follow.skill import ZERO_HASH, reconstruct


def _rand_fills(rng, n):
    times = np.sort(rng.integers(1_000, 1_000_000, n))
    px = rng.uniform(10, 200, n)
    sz = rng.uniform(0.1, 5.0, n).round(3)
    side = rng.choice(["B", "A"], n)
    crossed = rng.random(n) > 0.3
    hashes = np.where(rng.random(n) > 0.15, "0xreal", ZERO_HASH)
    return times, px, sz, side, crossed, hashes


def test_stepper_matches_batch_reconstruct_fuzz():
    # the load-bearing invariant: the incremental stepper reproduces the batch state machine
    for seed in range(200):
        rng = np.random.default_rng(seed)
        args = _rand_fills(rng, int(rng.integers(2, 40)))
        startpos = np.array([0.0])
        a = reconstruct(*args[:5], startpos, args[5])
        b = reconstruct_via_stepper(*args[:5], startpos, args[5])
        assert len(a) == len(b), f"seed {seed}: {len(a)} vs {len(b)} round-trips"
        for pa, pb in zip(a, b):
            assert pa.direction == pb.direction
            assert abs(pa.entry_px - pb.entry_px) < 1e-9 and abs(pa.exit_px - pb.exit_px) < 1e-9
            assert pa.entry_t == pb.entry_t and pa.exit_t == pb.exit_t
            assert pa.taker_open == pb.taker_open and pa.conviction_open == pb.conviction_open


def test_stepper_matches_with_seeded_startpos():
    # a position open before observation must be reconstructed-but-not-emitted (valid=False)
    for seed in range(80):
        rng = np.random.default_rng(seed + 1000)
        args = _rand_fills(rng, int(rng.integers(2, 30)))
        startpos = np.array([float(rng.choice([-3.0, -1.0, 2.0, 5.0]))])
        a = reconstruct(*args[:5], startpos, args[5])
        b = reconstruct_via_stepper(*args[:5], startpos, args[5])
        assert len(a) == len(b)


def test_emits_open_on_entry_and_close_on_flat():
    st = CoinStepper("ZEC")
    ev1 = st.step(100, px=100.0, sz=1.0, side="B", crossed=True, hsh="0xr")  # open long
    assert len(ev1) == 1 and isinstance(ev1[0], Open) and ev1[0].direction == 1
    assert ev1[0].entry_t == 100 and ev1[0].taker_open and ev1[0].conviction
    ev2 = st.step(200, px=110.0, sz=1.0, side="A", crossed=True, hsh="0xr")  # close
    assert len(ev2) == 1 and isinstance(ev2[0], Close)
    assert ev2[0].entry_t == 100 and ev2[0].exit_t == 200 and ev2[0].valid


def test_flip_emits_close_then_open():
    st = CoinStepper("ZEC")
    st.step(100, 100.0, 1.0, "B", True, "0xr")                  # long 1
    ev = st.step(200, 105.0, 3.0, "A", True, "0xr")             # sell 3 → close long, open short 2
    assert len(ev) == 2 and isinstance(ev[0], Close) and isinstance(ev[1], Open)
    assert ev[0].direction == 1 and ev[1].direction == -1 and ev[1].entry_t == 200


def test_seeded_position_produces_no_scorable_roundtrip():
    st = CoinStepper("ZEC", startpos=2.0)                       # opened before we watched
    ev = st.step(300, 100.0, 2.0, "A", True, "0xr")            # closes the pre-existing long
    # no entry was observed (no Open, no entry basis) → nothing scorable emitted
    assert not [e for e in ev if isinstance(e, Close) and e.valid]


def test_seeded_then_added_close_flagged_unmarkable():
    st = CoinStepper("ZEC", startpos=2.0)                       # seeded long (unobserved open)
    st.step(250, 100.0, 1.0, "B", True, "0xr")                 # add to it → es>0 but still invalid
    ev = st.step(300, 110.0, 3.0, "A", True, "0xr")           # close all 3
    closes = [e for e in ev if isinstance(e, Close)]
    assert closes and not closes[0].valid                      # emitted with valid=False → drop
