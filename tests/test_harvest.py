"""Unit tests for HarvestLedger — the event-driven 6h tranche state machine."""
import pytest

from babylon.follow.harvest import HarvestLedger, TrancheState

H = 3_600_000
SIX_H = 6 * H
LAG = 900_000   # 15 min


def _ledger(**over):
    kw = dict(entry_lag_ms=LAG, horizon_ms=SIX_H)
    kw.update(over)
    return HarvestLedger(**kw)


def test_full_lifecycle_long():
    led = _ledger()
    open_t = 1_000_000
    assert led.on_open_event(event_id="e1", wallet="w", coin="BTC", direction=1,
                             notional=1000.0, open_event_ms=open_t)
    # not due until open_t + LAG
    assert led.due_entries(open_t + LAG - 1) == []
    due = led.due_entries(open_t + LAG)
    assert [t.id for t in due] == ["e1"]
    # entry fills at 100; the 6h clock starts from the ENTRY FILL time, not the open event
    entry_fill_t = open_t + LAG + 5000
    led.on_entry_fill("e1", fill_px=100.0, fill_ms=entry_fill_t)
    t = led.open_tranches()[0]
    assert t.state is TrancheState.OPEN and t.expiry_ms == entry_fill_t + SIX_H
    # no exit due before expiry
    assert led.due_exits(entry_fill_t + SIX_H - 1) == []
    assert [t.id for t in led.due_exits(entry_fill_t + SIX_H)] == ["e1"]
    # exit fills at 105 -> +500bp long
    rt = led.on_exit_fill("e1", fill_px=105.0, fill_ms=entry_fill_t + SIX_H)
    assert abs(rt.raw_bps - 500.0) < 1e-6 and rt.direction == 1
    assert rt.entry_lag_ms == entry_fill_t - open_t   # realized lag recorded
    assert led.gross_open_notional() == 0.0           # closed, no exposure


def test_min_tranche_lets_realistic_harvest_size_through():
    # regression: min_tranche must be scaled to the harvest BASE (~$10 = budget·base_frac), NOT
    # 0.02·target_notional ($1000 → a $20 floor that capped out EVERY $3-15 tranche → 0 trades).
    led = _ledger(min_tranche_notional=1.0)                       # 0.1 · $10 base
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1,
                      notional=12.0, open_event_ms=0)             # a typical tail-aware tranche
    due = led.due_entries(LAG)
    assert [t.id for t in due] == ["e"] and due[0].notional == 12.0   # enters, not capped


def test_min_tranche_still_caps_dust():
    led = _ledger(min_tranche_notional=1.0)
    led.on_open_event(event_id="d", wallet="w", coin="BTC", direction=1,
                      notional=0.5, open_event_ms=0)              # below the $1 floor
    assert led.due_entries(LAG) == []                             # dust still capped


def test_entry_deadline_cancels_stale_pending():
    # a PENDING that can't enter within max_entry_lag of its target is cancelled (contaminated
    # window + leak), and counted in coverage — not held forever.
    led = _ledger(max_entry_lag_ms=1000)
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1,
                      notional=10.0, open_event_ms=0)                 # entry_target = LAG
    assert led.due_entries(LAG + 2000) == []                         # 2000 > 1000 past target
    assert led.coverage()["entry_expired"] == 1


def test_entry_deadline_lets_ontime_enter():
    led = _ledger(max_entry_lag_ms=1000)
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1,
                      notional=10.0, open_event_ms=0)
    assert [t.id for t in led.due_entries(LAG + 500)] == ["e"]       # 500 < 1000 → enters


def test_coverage_counts_and_survives_roundtrip():
    led = _ledger(max_gross_notional=5.0, min_tranche_notional=1.0)
    led.on_open_event(event_id="a", wallet="w", coin="BTC", direction=1,
                      notional=5.0, open_event_ms=0)                  # fills gross
    led.on_open_event(event_id="b", wallet="w", coin="BTC", direction=1,
                      notional=5.0, open_event_ms=0)                  # no room → capped
    assert [t.id for t in led.due_entries(LAG)] == ["a"]
    assert led.coverage()["registered"] == 2 and led.coverage()["capped"] == 1
    led2 = _ledger()
    led2.from_state(led.to_state())                                  # coverage is cumulative
    assert led2.coverage()["registered"] == 2 and led2.coverage()["capped"] == 1


def test_short_direction_bps_sign():
    led = _ledger(entry_lag_ms=0)
    led.on_open_event(event_id="s", wallet="w", coin="ETH", direction=-1, notional=500.0,
                      open_event_ms=0)
    led.due_entries(0)
    led.on_entry_fill("s", fill_px=100.0, fill_ms=0)
    rt = led.on_exit_fill("s", fill_px=110.0, fill_ms=SIX_H)  # price up 10% → short LOSES 1000bp
    assert abs(rt.raw_bps - (-1000.0)) < 1e-6


def test_clock_starts_at_entry_fill_not_open_or_target():
    # if we detect/enter LATE, the 6h still runs from the actual entry fill
    led = _ledger()
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1, notional=1.0,
                      open_event_ms=0)
    late = LAG + 10 * H                       # entered 10h after target
    led.due_entries(late)
    led.on_entry_fill("e", fill_px=1.0, fill_ms=late)
    assert led.open_tranches()[0].expiry_ms == late + SIX_H


def test_idempotent_open_event():
    led = _ledger()
    assert led.on_open_event(event_id="dup", wallet="w", coin="BTC", direction=1,
                             notional=1000.0, open_event_ms=0)
    assert not led.on_open_event(event_id="dup", wallet="w", coin="BTC", direction=1,
                                 notional=9999.0, open_event_ms=0)   # re-seen poll → ignored
    assert len([t for t in led.due_entries(LAG)]) == 1


def test_rejects_bad_event():
    led = _ledger()
    assert not led.on_open_event(event_id="z", wallet="w", coin="BTC", direction=0,
                                 notional=100.0, open_event_ms=0)  # dir 0
    assert not led.on_open_event(event_id="z2", wallet="w", coin="BTC", direction=1,
                                 notional=0.0, open_event_ms=0)    # notional 0


def test_per_coin_cap_scales_down():
    led = _ledger(entry_lag_ms=0, max_coin_notional=1500.0)
    led.on_open_event(event_id="a", wallet="w1", coin="BTC", direction=1, notional=1000.0,
                      open_event_ms=0)
    led.on_open_event(event_id="b", wallet="w2", coin="BTC", direction=1, notional=1000.0,
                      open_event_ms=0)
    due = led.due_entries(0)
    # first takes 1000, second scaled to the remaining 500 under the 1500 coin cap
    sizes = {t.id: t.notional for t in due}
    assert sizes == {"a": 1000.0, "b": 500.0}


def test_gross_cap_cancels_below_min():
    led = _ledger(entry_lag_ms=0, max_gross_notional=1000.0, min_tranche_notional=100.0)
    led.on_open_event(event_id="a", wallet="w", coin="BTC", direction=1, notional=950.0,
                      open_event_ms=0)
    led.on_open_event(event_id="b", wallet="w", coin="ETH", direction=1, notional=950.0,
                      open_event_ms=0)
    due = led.due_entries(0)
    # a takes 950; b has only 50 room < min(100) → cancelled, not returned
    assert [t.id for t in due] == ["a"]
    assert led._tranches["b"].state is TrancheState.CANCELLED  # noqa: SLF001


def test_cap_uses_only_open_exposure_not_pending():
    # a PENDING (not-yet-entered) tranche must NOT consume cap room from a due one
    led = _ledger(max_coin_notional=1000.0)
    led.on_open_event(event_id="early", wallet="w", coin="BTC", direction=1, notional=1000.0,
                      open_event_ms=0)             # due at LAG
    led.on_open_event(event_id="later", wallet="w", coin="BTC", direction=1, notional=1000.0,
                      open_event_ms=10 * H)        # due much later, still PENDING now
    due = led.due_entries(LAG)
    assert [t.id for t in due] == ["early"] and due[0].notional == 1000.0  # full, not halved


def test_due_exits_retries_until_filled():
    led = _ledger(entry_lag_ms=0)
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1, notional=1.0,
                      open_event_ms=0)
    led.due_entries(0)
    led.on_entry_fill("e", fill_px=1.0, fill_ms=0)
    assert [t.id for t in led.due_exits(SIX_H)] == ["e"]     # due
    # caller's exit order didn't fill → still OPEN → still due next tick
    assert [t.id for t in led.due_exits(SIX_H + H)] == ["e"]
    led.on_exit_fill("e", fill_px=1.0, fill_ms=SIX_H + H)
    assert led.due_exits(SIX_H + 2 * H) == []                # closed → gone


def test_on_entry_failed_drops_no_exposure():
    led = _ledger(entry_lag_ms=0)
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1, notional=1000.0,
                      open_event_ms=0)
    led.due_entries(0)
    led.on_entry_failed("e")
    assert led._tranches["e"].state is TrancheState.CANCELLED  # noqa: SLF001
    assert led.gross_open_notional() == 0.0
    assert led.due_exits(10 * SIX_H) == []


def test_exposure_and_target_net_only_count_open():
    led = _ledger(entry_lag_ms=0)
    led.on_open_event(event_id="L", wallet="w1", coin="BTC", direction=1, notional=600.0,
                      open_event_ms=0)
    led.on_open_event(event_id="S", wallet="w2", coin="BTC", direction=-1, notional=400.0,
                      open_event_ms=0)
    led.due_entries(0)
    led.on_entry_fill("L", fill_px=100.0, fill_ms=0)
    led.on_entry_fill("S", fill_px=100.0, fill_ms=0)
    assert led.coin_open_notional("BTC") == 1000.0       # gross (both legs)
    assert led.target_net("BTC") == 200.0                # net (600 long − 400 short)
    assert led.gross_open_notional() == 1000.0


def test_drain_and_prune():
    led = _ledger(entry_lag_ms=0)
    for i in range(3):
        led.on_open_event(event_id=f"e{i}", wallet="w", coin="BTC", direction=1, notional=1.0,
                          open_event_ms=0)
    led.due_entries(0)
    for i in range(3):
        led.on_entry_fill(f"e{i}", fill_px=1.0, fill_ms=0)
        led.on_exit_fill(f"e{i}", fill_px=1.0 + i * 0.01, fill_ms=SIX_H)
    drained = led.drain_realized()
    assert len(drained) == 3 and led.drain_realized() == []   # drained once
    assert led.prune_closed() == 3                            # all terminal removed
    assert led._tranches == {}                                # noqa: SLF001


def test_exit_requires_positive_entry_price():
    led = _ledger(entry_lag_ms=0)
    led.on_open_event(event_id="e", wallet="w", coin="BTC", direction=1, notional=1.0,
                      open_event_ms=0)
    led.due_entries(0)
    led.on_entry_fill("e", fill_px=0.0, fill_ms=0)   # degenerate
    with pytest.raises(AssertionError):
        led.on_exit_fill("e", fill_px=1.0, fill_ms=SIX_H)
