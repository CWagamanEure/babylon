import numpy as np
import polars as pl

from babylon.follow.experiment import ExperimentConfig
from babylon.follow.followable import followable_returns
from babylon.follow.selection import SelectionAdapter

# hourly candles (HL's finest); _close_at looks back one full candle (no look-ahead).
# Marks: entry at 3h → close@2h = 100; exit at 5h → close@4h = 110 ⇒ +1000bp long.
H = 3_600_000
LOOK = {"TESTC": (np.array([0, H, 2 * H, 3 * H, 4 * H, 5 * H]),
                  np.array([90.0, 95.0, 100.0, 105.0, 110.0, 115.0]))}


def _fills(entry_t=3 * H, exit_t=5 * H, tids=(10, 20), px=(100.0, 110.0)):
    # one taker-opened, conviction (real hash) long round-trip on TESTC
    return pl.DataFrame({
        "time": [entry_t, exit_t], "coin": ["TESTC", "TESTC"], "px": list(px),
        "sz": [1.0, 1.0], "side": ["B", "A"], "crossed": [True, True],
        "startPosition": [0.0, 1.0], "hash": ["0xreal", "0xreal"], "tid": list(tids),
    })


def _cfg(**over):
    base = dict(
        execution="retail", universe_hash="u0", eligible_pool="p", train_days=1,
        follow_days=14, roll_cadence_days=14, min_hold_ms=0, min_positions=6, beta=1.245,
        gross_target=1.0, max_coin_frac=0.08, max_wallet_frac=0.05, also_run_uncapped=True,
        lag_bucket_ms=0, fee_bps=4.5, impact_bps=6.0, max_depth_frac=0.25,
        target_notional_usd=1_000.0, primary_control="pool_mean",
        secondary_controls=("random",), min_n_nominal=1500, min_effective_n=120,
        horizon_cap_days=300, mar_bps=8.0, maxdd_bound=-0.25, max_single_contrib_frac=0.20,
        cost_floor_bps=15.0)
    base.update(over)
    return ExperimentConfig(**base)


def test_followable_returns_directional():
    r = followable_returns(_fills(), universe={"TESTC"}, lookups=LOOK, lag_ms=0, min_hold_ms=0)
    assert len(r) == 1 and abs(r[0] - 1000.0) < 1.0   # long, candle 100→110 = +1000bp


def test_followable_returns_short_direction():
    # sell-to-open (short), buy-to-close; candle rises 100→110 → a short LOSES ~1000bp
    df = pl.DataFrame({
        "time": [3 * H, 5 * H], "coin": ["TESTC", "TESTC"], "px": [100.0, 110.0],
        "sz": [1.0, 1.0], "side": ["A", "B"], "crossed": [True, True],
        "startPosition": [0.0, -1.0], "hash": ["0xreal", "0xreal"], "tid": [1, 2]})
    r = followable_returns(df, universe={"TESTC"}, lookups=LOOK, lag_ms=0, min_hold_ms=0)
    assert len(r) == 1 and abs(r[0] - (-1000.0)) < 1.0


def test_seam_guard_excludes_open_roundtrip():
    df = _fills()
    before = followable_returns(df, universe={"TESTC"}, lookups=LOOK, lag_ms=0,
                                min_hold_ms=0, before_ms=4 * H)   # exit 5h ≥ 4h → out
    after = followable_returns(df, universe={"TESTC"}, lookups=LOOK, lag_ms=0,
                               min_hold_ms=0, before_ms=6 * H)     # exit 5h < 6h → in
    assert len(before) == 0 and len(after) == 1


def test_selection_adapter_returns_and_cutoff():
    adapter = SelectionAdapter(lambda w, s, e: _fills(tids=(10, 20)),
                               universe={"TESTC"}, lookups=LOOK, config=_cfg())
    r = adapter.returns_fn("w1", t0_ms=6 * H)
    assert len(r) == 1 and abs(r[0] - 1000.0) < 1.0
    assert adapter.cutoff_fn("w1", t0_ms=6 * H) == 20    # max tid with time < t0


def test_selection_adapter_empty_wallet():
    empty = pl.DataFrame(schema=_fills().schema)
    adapter = SelectionAdapter(lambda w, s, e: empty, universe={"TESTC"}, lookups=LOOK,
                               config=_cfg())
    assert adapter.returns_fn("w1", 6 * H).size == 0 and adapter.cutoff_fn("w1", 6 * H) == 0
