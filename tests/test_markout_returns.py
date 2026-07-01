"""Parity + correctness for the validated fixed-horizon selection signal.

`markout_returns` (live selection) and `selci_fh` (the offline study that validated the edge) both
build on `skill.open_events` — the single source of truth. These tests pin (a) open_events' state
machine on the cases the audit cared about, and (b) that markout_returns reproduces a hand-computed
fixed-horizon markout, so live ≡ what was validated.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from babylon.follow.followable import _close_at, markout_returns
from babylon.follow.skill import _basket_ret_bps, open_events

_SCHEMA = {
    "time": pl.Int64, "coin": pl.Utf8, "px": pl.Float64, "sz": pl.Float64, "side": pl.Utf8,
    "crossed": pl.Boolean, "startPosition": pl.Float64, "hash": pl.Utf8, "tid": pl.Int64,
}


def _fills(rows):
    return pl.DataFrame(
        [{"time": t, "coin": c, "px": p, "sz": s, "side": sd, "crossed": cr,
          "startPosition": sp, "hash": h, "tid": i}
         for i, (t, c, p, s, sd, cr, sp, h) in enumerate(rows)],
        schema=_SCHEMA,
    )


def _ev(rows):
    g = _fills(rows).sort("time")
    return open_events(g["time"].to_numpy(), g["px"].to_numpy(), g["sz"].to_numpy(),
                       g["side"].to_numpy(), g["crossed"].to_numpy(),
                       g["startPosition"].to_numpy(), g["hash"].to_numpy())


# ---- open_events state machine ----

def test_single_open_from_flat():
    ev = _ev([(0, "X", 100.0, 1.0, "B", True, 0.0, "0xreal")])
    assert len(ev) == 1
    assert ev[0].direction == 1 and ev[0].is_leading is True
    assert ev[0].notional == 100.0  # |1| * 100


def test_add_does_not_emit_second_event():
    # open long, then scale in same side -> ONE event (one entry signal per position)
    ev = _ev([(0, "X", 100.0, 1.0, "B", True, 0.0, "0xa"),
              (1, "X", 110.0, 2.0, "B", True, 0.0, "0xb")])
    assert len(ev) == 1 and ev[0].direction == 1


def test_flip_emits_two_events_second_not_leading():
    # long 1, then sell 3 -> close long, open short (leftover 2). TWO events.
    ev = _ev([(0, "X", 100.0, 1.0, "B", True, 0.0, "0xa"),
              (10, "X", 100.0, 3.0, "A", True, 0.0, "0xb")])
    assert len(ev) == 2
    assert ev[0].direction == 1 and ev[0].is_leading is True
    assert ev[1].direction == -1 and ev[1].is_leading is False  # follows an observed close
    assert ev[1].notional == 200.0  # leftover 2 * 100


def test_open_after_close_not_leading():
    # open long, fully close, open again -> second open is NOT leading (we observed a flat)
    ev = _ev([(0, "X", 100.0, 1.0, "B", True, 0.0, "0xa"),
              (5, "X", 100.0, 1.0, "A", True, 0.0, "0xb"),
              (9, "X", 100.0, 1.0, "B", True, 0.0, "0xc")])
    assert len(ev) == 2
    assert ev[0].is_leading is True and ev[1].is_leading is False


def test_conviction_flag_from_zero_hash():
    ev = _ev([(0, "X", 100.0, 1.0, "B", True, 0.0, "0x" + "0" * 64)])  # TWAP/liquidation marker
    assert ev[0].conviction is False


# ---- markout_returns pricing ----

def _lookups(coin, times, closes):
    return {coin: (np.asarray(times, dtype=np.int64), np.asarray(closes, dtype=np.float64))}


def test_markout_fixed_horizon_value():
    # hourly candles. _close_at(t) = close of the last candle FULLY closed by t (index =
    # searchsorted(times, t - CANDLE, "right") - 1). Entry at 2H, lag 0, horizon H:
    #   ein  = _close_at(2H) -> times[i] <= H  -> closes[2]
    #   eout = _close_at(3H) -> times[i] <= 2H -> closes[3]
    H = 3_600_000
    lk = _lookups("X", [-H, 0, H, 2 * H, 3 * H], [80.0, 90.0, 100.0, 110.0, 120.0])
    df = _fills([(2 * H, "X", 100.0, 1.0, "B", True, 0.0, "0xreal")])  # long entry at t=2H
    # raw = +1 * (closes[3]/closes[2] - 1) * 1e4 = (110/100 - 1) * 1e4 = +1000 bps
    r = markout_returns(df, universe={"X"}, lookups=lk, lag_ms=0, horizon_ms=H)
    assert r.size == 1
    assert abs(r[0] - 1000.0) < 1e-6


def test_markout_seam_guard_excludes_window_straddling_t0():
    H = 3_600_000
    lk = _lookups("X", [0, H, 2 * H, 3 * H], [100.0, 110.0, 121.0, 130.0])
    df = _fills([(2 * H, "X", 110.0, 1.0, "B", True, 0.0, "0xreal")])
    # full window ends at entry+lag+H = 3H; before_ms just under 3H -> excluded
    r = markout_returns(df, universe={"X"}, lookups=lk, lag_ms=0, horizon_ms=H, before_ms=3 * H - 1)
    assert r.size == 0
    # before_ms above the window end -> included
    r2 = markout_returns(df, universe={"X"}, lookups=lk, lag_ms=0, horizon_ms=H, before_ms=3 * H + 1)
    assert r2.size == 1


def test_markout_drop_leading_excludes_first_open():
    H = 3_600_000
    lk = _lookups("X", [0, H, 2 * H, 3 * H, 4 * H], [100.0, 110.0, 121.0, 130.0, 140.0])
    df = _fills([(2 * H, "X", 110.0, 1.0, "B", True, 0.0, "0xreal")])  # only a leading open
    kept = markout_returns(df, universe={"X"}, lookups=lk, lag_ms=0, horizon_ms=H)
    dropped = markout_returns(df, universe={"X"}, lookups=lk, lag_ms=0, horizon_ms=H, drop_leading=True)
    assert kept.size == 1 and dropped.size == 0


def test_markout_skips_unpriceable_coin():
    H = 3_600_000
    lk = _lookups("X", [0, H, 2 * H], [100.0, 110.0, 121.0])
    df = _fills([(2 * H, "Y", 110.0, 1.0, "B", True, 0.0, "0xreal")])  # coin Y not in lookups
    r = markout_returns(df, lookups=lk, lag_ms=0, horizon_ms=H)
    assert r.size == 0


# ---- A2 fix: default universe=None must price ALL candle coins (incl. majors), matching selci_fh ----

def test_default_universe_does_not_drop_majors():
    H = 3_600_000
    lk = {**_lookups("X", [-H, 0, H, 2 * H, 3 * H], [80.0, 90.0, 100.0, 110.0, 120.0]),
          **_lookups("BTC", [-H, 0, H, 2 * H, 3 * H], [80.0, 90.0, 100.0, 110.0, 120.0])}
    df = _fills([(2 * H, "BTC", 100.0, 1.0, "B", True, 0.0, "0xreal")])  # a major-coin entry
    # default (universe=None) prices it — selci_fh validated on all candle coins, not a sub-universe
    assert markout_returns(df, lookups=lk, lag_ms=0, horizon_ms=H).size == 1
    # an explicit restrictive universe deliberately drops it (a DIFFERENT, non-validated rule)
    assert markout_returns(df, lookups=lk, lag_ms=0, horizon_ms=H, universe={"X"}).size == 0


# ---- A4 coverage: deployed config — neutralized, lag!=0, multi-coin, never-closer ----

def _selci_fh_reference(df, lookups, lag, H, basket, beta, before_ms):
    """Inline replica of selci_fh.cmd_extract's pricing (the VALIDATED path) to pin live ≡ study.
    Mirrors: per-coin open_events -> conviction filter -> fixed-horizon candle markout -> neutralize
    -> seam classify by window end. If markout_returns matches this, live == what was validated."""
    out = []
    for (coin,), g in df.sort("time").group_by("coin", maintain_order=True):
        c = str(coin)
        if c not in lookups:
            continue
        g = g.sort("time")
        for e in open_events(g["time"].to_numpy(), g["px"].to_numpy(), g["sz"].to_numpy(),
                             g["side"].to_numpy(), g["crossed"].to_numpy(),
                             g["startPosition"].to_numpy(), g["hash"].to_numpy()):
            if not (e.taker_open and e.conviction):
                continue
            end = e.entry_t + lag + H
            if before_ms is not None and end >= before_ms:
                continue
            ein = _close_at(lookups[c], e.entry_t + lag)
            eout = _close_at(lookups[c], end)
            if ein is None or eout is None:
                continue
            raw = e.direction * (eout / ein - 1.0) * 1e4
            raw -= e.direction * beta * _basket_ret_bps(basket, e.entry_t + lag, end)
            out.append(raw)
    return np.asarray(out, dtype=np.float64)


def test_live_equals_validated_neutralized_multicoin_lagged():
    from babylon.follow.skill import _basket_ret_bps  # noqa: F401 (used via reference)
    H, lag = 3_600_000, 900_000  # 6h horizon would need more candles; use 1 candle H + 15min lag shape
    tg = [i * H for i in range(-1, 8)]
    lk = {**_lookups("X", tg, [80, 85, 90, 100, 110, 121, 130, 140, 150]),
          **_lookups("ALT", tg, [50, 55, 60, 66, 70, 77, 80, 88, 90])}
    basket = (np.asarray(tg, dtype=np.int64),
              np.asarray([100, 101, 102, 103, 104, 105, 106, 107, 108], dtype=np.float64))
    df = _fills([
        (3 * H, "X", 100.0, 1.0, "B", True, 0.0, "0xa"),     # X long
        (3 * H, "X", 100.0, 2.0, "A", True, 0.0, "0xb"),     # flip to short (2 events on X)
        (4 * H, "ALT", 70.0, 5.0, "A", True, 0.0, "0xc"),    # ALT short, never closes (never-closer)
    ])
    ref = _selci_fh_reference(df, lk, lag, H, basket, 1.245, before_ms=None)
    got = markout_returns(df, lookups=lk, lag_ms=lag, horizon_ms=H, basket=basket, beta=1.245)
    assert got.size == ref.size and got.size >= 2
    assert np.allclose(got, ref), f"live diverges from validated:\n got={got}\n ref={ref}"


def test_never_closer_is_scored():
    H = 3_600_000
    lk = _lookups("X", [i * H for i in range(-1, 6)], [80, 90, 100, 110, 121, 130, 140])
    df = _fills([(2 * H, "X", 100.0, 1.0, "B", True, 0.0, "0xreal")])  # opens, NEVER closes
    # round-trip pricing would drop this; fixed-horizon scores it
    assert markout_returns(df, lookups=lk, lag_ms=0, horizon_ms=H).size == 1


def test_directional_vs_neutralized_differ():
    H = 3_600_000
    tg = [i * H for i in range(-1, 5)]
    lk = _lookups("X", tg, [80, 90, 100, 110, 121, 130])
    basket = (np.asarray(tg, dtype=np.int64), np.asarray([100, 105, 110, 115, 120, 125], dtype=np.float64))
    df = _fills([(2 * H, "X", 100.0, 1.0, "B", True, 0.0, "0xreal")])
    d = markout_returns(df, lookups=lk, lag_ms=0, horizon_ms=H)
    n = markout_returns(df, lookups=lk, lag_ms=0, horizon_ms=H, basket=basket, beta=1.0)
    assert d.size == n.size == 1
    assert not np.isclose(d[0], n[0])  # neutralization actually subtracts the basket move
