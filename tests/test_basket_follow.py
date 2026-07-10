"""Tests for the rolling-WF basket paper follower (basket_main + the per-tranche horizon and
basket-filter extensions to HarvestLedger / HarvestRunner)."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from babylon.execution.fill_model import Book
from babylon.execution.paper import PaperExecutor
from babylon.follow.basket_main import HORIZON_MS, load_basket
from babylon.follow.harvest import HarvestLedger, TrancheState
from babylon.follow.harvest_runner import HarvestRunner
from babylon.follow.skill import OpenEvent

H = 3_600_000


def _book(mid=100.0, sz=1000.0):
    return Book(bid_px=(mid - 0.05,), bid_sz=(sz,), ask_px=(mid + 0.05,), ask_sz=(sz,))


def _ev(direction=1, t=0, taker=True, conv=True, leading=False, tid=0):
    return OpenEvent(entry_t=t, direction=direction, taker_open=taker, conviction=conv,
                     is_leading=leading, notional=1000.0, tid=tid)


# ── per-tranche horizon (HarvestLedger) ────────────────────────────────────────────────────
def test_ledger_per_tranche_horizon_overrides_global():
    led = HarvestLedger(entry_lag_ms=0, horizon_ms=8 * H)
    led.on_open_event(event_id="a", wallet="w", coin="BTC", direction=1, notional=10.0,
                      open_event_ms=0, horizon_ms=2 * H)
    led.on_open_event(event_id="b", wallet="w", coin="ETH", direction=1, notional=10.0,
                      open_event_ms=0)                        # no override → global 8h
    led.on_entry_fill("a", 100.0, 1000)
    led.on_entry_fill("b", 100.0, 1000)
    ts = {t.id: t for t in led.open_tranches()}
    assert ts["a"].expiry_ms == 1000 + 2 * H                  # per-tranche
    assert ts["b"].expiry_ms == 1000 + 8 * H                  # ledger global


def test_ledger_horizon_survives_state_roundtrip():
    led = HarvestLedger(entry_lag_ms=0, horizon_ms=8 * H)
    led.on_open_event(event_id="a", wallet="w", coin="BTC", direction=1, notional=10.0,
                      open_event_ms=0, horizon_ms=H)
    led2 = HarvestLedger(entry_lag_ms=0, horizon_ms=8 * H)
    led2.from_state(led.to_state())
    led2.on_entry_fill("a", 100.0, 500)
    assert led2.open_tranches()[0].expiry_ms == 500 + H


def test_ledger_old_snapshot_without_horizon_field_resumes():
    led = HarvestLedger(entry_lag_ms=0, horizon_ms=8 * H)
    led.on_open_event(event_id="a", wallet="w", coin="BTC", direction=1, notional=10.0,
                      open_event_ms=0)
    st = led.to_state()
    for t in st["tranches"]:                                  # simulate a pre-upgrade snapshot
        t.pop("horizon_ms", None)
    led2 = HarvestLedger(entry_lag_ms=0, horizon_ms=8 * H)
    led2.from_state(st)
    led2.on_entry_fill("a", 100.0, 0)
    assert led2.open_tranches()[0].expiry_ms == 8 * H


# ── basket filter (HarvestRunner.ingest_opens) ─────────────────────────────────────────────
def _runner(basket, skip_leading=False):
    led = HarvestLedger(entry_lag_ms=0, horizon_ms=8 * H)
    r = HarvestRunner(led, {"0xw": 50.0, "0xv": 50.0}, PaperExecutor(),
                      universe={"BTC", "ETH", "HYPE"}, basket=basket, skip_leading=skip_leading,
                      taker_only=False, conviction_only=False)
    return r, led


def test_basket_filters_pairs_and_assigns_frozen_horizon():
    basket = {("0xw", "BTC"): 2 * H}
    r, led = _runner(basket)
    assert r.ingest_opens("0xw", [("BTC", _ev(tid=1))]) == 1          # in basket → registered
    assert r.ingest_opens("0xw", [("ETH", _ev(tid=2))]) == 0          # wallet ok, coin not in ITS row
    assert r.ingest_opens("0xv", [("BTC", _ev(tid=3))]) == 0          # coin ok, wallet not in basket
    led.on_entry_fill([t for t in led.due_entries(0)][0].id, 100.0, 0)
    assert led.open_tranches()[0].expiry_ms == 2 * H                  # the row's frozen horizon


def test_basket_estimand_parity_filters():
    basket = {("0xw", "BTC"): H}
    r, _ = _runner(basket)
    # NO event-level taker/TWAP filter (wallet-level in discovery) → maker/TWAP opens register
    assert r.ingest_opens("0xw", [("BTC", _ev(taker=False, conv=False, tid=1))]) == 1
    # LIVE mode keeps leading opens: per-poll batching makes nearly every true flat→open the
    # first fill of its batch (verified live 2026-07-09 — skipping them dropped ALL entries).
    assert r.ingest_opens("0xw", [("BTC", _ev(leading=True, tid=2))]) == 1


def test_skip_leading_flag_still_works_when_enabled():
    r, _ = _runner({("0xw", "BTC"): H}, skip_leading=True)
    assert r.ingest_opens("0xw", [("BTC", _ev(leading=True, tid=1))]) == 0
    assert r.ingest_opens("0xw", [("BTC", _ev(leading=False, tid=2))]) == 1


def test_basket_tranche_full_cycle_exits_on_own_clock():
    basket = {("0xw", "BTC"): 2 * H}
    r, led = _runner(basket)
    r.ingest_opens("0xw", [("BTC", _ev(direction=1, t=0, tid=1))])
    r.on_book("BTC", _book(100.0), 0)
    rep = r.step(0)
    assert rep.entries == 1
    r.on_book("BTC", _book(101.0), 2 * H + 1)                          # 2h later, price +1%
    rep = r.step(2 * H + 1)
    assert rep.exits == 1
    rt = rep.realized[0]
    assert rt.wallet == "0xw" and rt.coin == "BTC" and rt.raw_bps > 0
    assert rt.exit_ms - rt.entry_ms == 2 * H + 1                       # held ITS horizon, not 8h


# ── basket loader ──────────────────────────────────────────────────────────────────────────
def test_load_basket_roundtrip(tmp_path: Path):
    rows = [{"rank": 1, "wallet": "0xa", "coin": "BTC", "horizon": "1h",
             "disc_p": 0.001, "disc_gross_bp": 20.0},
            {"rank": 2, "wallet": "0xb", "coin": "HYPE", "horizon": "8h",
             "disc_p": 0.001, "disc_gross_bp": 50.0}]
    p = tmp_path / "basket.parquet"
    pq.write_table(pa.Table.from_pylist(rows), p)
    basket, roster, universe, digest = load_basket(p)
    assert basket == {("0xa", "BTC"): HORIZON_MS["1h"], ("0xb", "HYPE"): HORIZON_MS["8h"]}
    assert roster == ["0xa", "0xb"] and universe == ["BTC", "HYPE"]
    assert len(digest) == 16


# ── refresh seam (audit F2/F3): new basket + old checkpoint ────────────────────────────────
def test_refresh_seam_new_wallet_polls_and_dropped_coin_still_exits():
    import asyncio
    from babylon.follow.watcher import WalletWatcher

    class _Src:
        async def user_fills_by_time(self, addr, since, now):
            return []
        async def clearinghouse_state(self, addr):
            return {"assetPositions": []}

    # epoch 1: wallet A on HYPE, open tranche, checkpoint
    led1 = HarvestLedger(entry_lag_ms=0, horizon_ms=2 * H)
    r1 = HarvestRunner(led1, {"0xa": 50.0}, PaperExecutor(), universe={"HYPE"},
                       watcher=WalletWatcher(_Src(), ["0xa"], min_interval_s=0.0),
                       basket={("0xa", "HYPE"): 2 * H}, taker_only=False, conviction_only=False)
    r1.ingest_opens("0xa", [("HYPE", _ev(t=0, tid=1))])
    r1.on_book("HYPE", _book(50.0), 0)
    assert r1.step(0).entries == 1
    st = r1.to_state()

    # epoch 2: basket dropped HYPE and wallet A; new wallet B on BTC. Restore old checkpoint.
    led2 = HarvestLedger(entry_lag_ms=0, horizon_ms=2 * H)
    w2 = WalletWatcher(_Src(), ["0xb"], min_interval_s=0.0)
    r2 = HarvestRunner(led2, {"0xb": 50.0}, PaperExecutor(), universe={"BTC"},
                       watcher=w2, roster=["0xb"], basket={("0xb", "BTC"): H},
                       taker_only=False, conviction_only=False)
    r2.from_state(st)
    w2.update_roster(["0xb"], since_ms=123)          # the F2 fix basket_main now applies
    # F2: polling the NEW wallet must not KeyError
    asyncio.run(w2.poll_wallet("0xb", now_ms=1000))
    assert w2._cursor["0xb"] == 123
    # F3: feed universe must include the orphaned HYPE (open tranche) so its exit can fill
    assert "HYPE" in r2.feed_universe() and "BTC" in r2.feed_universe()
    r2.on_book("HYPE", _book(51.0), 2 * H + 1)
    rep = r2.step(2 * H + 1)
    assert rep.exits == 1                             # orphaned tranche exits on its clock


# ── cost accounting pin (audit F1): what raw_bps actually contains ─────────────────────────
def test_raw_bps_embeds_fee_and_impact_roundtrip():
    led = HarvestLedger(entry_lag_ms=0, horizon_ms=H)
    ex = PaperExecutor(taker_fee_bps=4.5, impact_bps=1.0)
    r = HarvestRunner(led, {"0xw": 50.0}, ex, universe={"BTC"},
                      basket={("0xw", "BTC"): H}, taker_only=False, conviction_only=False)
    r.ingest_opens("0xw", [("BTC", _ev(direction=1, t=0, tid=1))])
    book = _book(100.0, sz=1e9)                       # constant mid 100, spread 0.10 (10bp)
    r.on_book("BTC", book, 0)
    assert r.step(0).entries == 1
    r.on_book("BTC", book, H + 1)                     # same book at exit: zero price move
    rt = r.step(H + 1).realized[0]
    # at constant mid: raw_bps ≈ −(spread 10bp + 2×(4.5+1.0)=11bp) ≈ −21bp — costs are EMBEDDED
    assert -22.5 < rt.raw_bps < -19.5, rt.raw_bps
    # the audit's un-fold recovers the pre-cost VWAP return (≈ −spread only)
    f = (4.5 + 1.0) / 1e4
    d = rt.direction
    gross_vwap = d * ((rt.exit_px / (1 - d * f)) / (rt.entry_px / (1 + d * f)) - 1) * 1e4
    assert -10.5 < gross_vwap < -9.5, gross_vwap      # spread only, fee+impact removed exactly
