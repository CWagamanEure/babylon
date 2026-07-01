"""Tests for the reworked, candle-symmetric gate feed.

The gate now measures edge-over-field on the SAME ruler for both arms (roster vs train-eligible
field, forward candle-markouts, cluster-bootstrap CI). Realized fills are only the execution
diagnostic + the maxDD source, never the edge measurement.
"""
import numpy as np
import polars as pl
import pytest

from babylon.follow.experiment import ExperimentConfig, Registry, Results, RunManifest
from babylon.follow.gate_feed import (
    RealizedJournal,
    assemble_results,
    cluster_boot_eof,
    eligible_field_markouts,
    equity_curve,
    execution_slippage,
    neutralize_top,
    results_hash,
    roster_markouts,
    run_gate_decision,
)
from babylon.follow.harvest import RealizedRoundTrip

H = 3_600_000


def _rt(wallet="w", coin="BTC", direction=1, raw_bps=50.0, entry_ms=0, exit_ms=6 * H):
    return RealizedRoundTrip(id=f"{wallet}:{coin}:{entry_ms}", wallet=wallet, coin=coin,
                             direction=direction, entry_px=100.0, exit_px=100.0 + raw_bps / 100,
                             entry_ms=entry_ms, exit_ms=exit_ms, raw_bps=raw_bps,
                             entry_lag_ms=900_000)


def _flat_basket():
    return (np.array([0, 6 * H, 12 * H], dtype=np.int64), np.array([1.0, 1.0, 1.0]))


# ── journal + realized-fill helpers (execution diagnostic) ────────────────────────────────────
def test_realized_journal_roundtrip(tmp_path):
    j = RealizedJournal(tmp_path / "realized.jsonl")
    assert j.load() == []
    j.append([_rt(wallet="a", entry_ms=0), _rt(wallet="b", entry_ms=H)])
    j.append([_rt(wallet="c", entry_ms=2 * H)])
    loaded = j.load()
    assert [r.wallet for r in loaded] == ["a", "b", "c"]
    assert loaded[0].raw_bps == 50.0 and loaded[2].entry_ms == 2 * H
    j.append([])
    assert len(j.load()) == 3


def test_neutralize_flat_basket_unchanged():
    top = neutralize_top([_rt(raw_bps=50.0), _rt(raw_bps=-20.0)], _flat_basket(), beta=1.0)
    assert np.allclose(top, [50.0, -20.0])


def test_neutralize_subtracts_rising_basket_for_long():
    basket = (np.array([0, 3 * H, 9 * H], dtype=np.int64), np.array([1.0, 1.0, 1.10]))
    long_rt = _rt(direction=1, raw_bps=200.0, entry_ms=4 * H, exit_ms=10 * H)
    assert neutralize_top([long_rt], basket, beta=1.0)[0] < 200.0
    short_rt = _rt(direction=-1, raw_bps=200.0, entry_ms=4 * H, exit_ms=10 * H)
    assert neutralize_top([short_rt], basket, beta=1.0)[0] > 200.0


def test_equity_curve_and_drawdown():
    from babylon.follow.measure import max_drawdown
    eq = equity_curve(np.array([100.0, -200.0, 100.0]))
    assert eq[0] == 1.0 and len(eq) == 4
    assert max_drawdown(eq) < 0


def test_execution_slippage_reports_realized_minus_candle():
    realized = [_rt(raw_bps=40.0), _rt(raw_bps=60.0)]          # realized mean 50
    roster_mk = {"w": np.array([70.0, 90.0])}                  # candle mean 80
    d = execution_slippage(realized, roster_mk, None)
    assert d["realized_mean_bps"] == 50.0 and d["candle_mean_bps"] == 80.0
    assert d["slippage_bps"] == -30.0                          # execution cost us 30bp vs candle
    assert d["n_realized"] == 2 and d["n_candle"] == 2


def test_results_hash_deterministic_and_sensitive():
    r = Results(n_effective=10, n_nominal=100, top_minus_control_ci_low=5.0,
                top_minus_control_ci_high=15.0, top_vs_poolmean_significant=True, maxdd=-0.1,
                depth_capped_survives=True, max_single_contrib_frac=0.1)
    r2 = Results(n_effective=10, n_nominal=100, top_minus_control_ci_low=6.0,
                 top_minus_control_ci_high=15.0, top_vs_poolmean_significant=True, maxdd=-0.1,
                 depth_capped_survives=True, max_single_contrib_frac=0.1)
    assert results_hash(r) == results_hash(r) and results_hash(r) != results_hash(r2)


# ── the symmetric estimator: cluster_boot_eof + assemble_results ──────────────────────────────
def test_cluster_boot_eof_point_and_ci():
    roster = {"a": np.array([100.0, 100.0]), "b": np.array([100.0])}
    field = {"a": np.array([100.0, 100.0]), "b": np.array([100.0]),
             "x": np.array([0.0, 0.0]), "y": np.array([0.0])}
    point, lo, hi = cluster_boot_eof(roster, field, n_boot=500, seed=0)
    assert point > 0 and lo <= point <= hi                    # roster (100) beats mixed field
    # a field identical to the roster → eof ≈ 0
    p2, lo2, hi2 = cluster_boot_eof(roster, dict(roster), n_boot=500, seed=0)
    assert abs(p2) < 1e-9 and lo2 <= 0 <= hi2


def test_assemble_results_empty_arm_raises():
    cfg = _cfg()
    with pytest.raises(ValueError, match="empty TOP or CONTROL"):
        assemble_results({}, {"x": np.array([1.0])}, realized_net=np.array([50.0, 50.0]),
                         depth_capped_survives=True, config=cfg)
    with pytest.raises(ValueError, match="empty TOP or CONTROL"):
        assemble_results({"a": np.array([1.0])}, {}, realized_net=np.array([50.0, 50.0]),
                         depth_capped_survives=True, config=cfg)


def test_assemble_results_significant_when_roster_beats_field():
    cfg = _cfg(min_n_nominal=1, min_effective_n=1)
    roster = {f"w{i}": np.array([200.0]) for i in range(20)}
    field = {**roster, **{f"f{i}": np.array([0.0]) for i in range(20)}}
    r = assemble_results(roster, field, realized_net=np.array([]),
                         depth_capped_survives=True, config=cfg)
    assert r.n_nominal == 20 and r.top_vs_poolmean_significant and r.top_minus_control_ci_low > 0
    assert 0 <= r.max_single_contrib_frac <= 1


def test_assemble_results_realized_net_ci_profitability_leg():
    cfg = _cfg(min_n_nominal=1, min_effective_n=1)
    roster = {f"w{i}": np.array([200.0]) for i in range(20)}
    field = {**roster, **{f"f{i}": np.array([0.0]) for i in range(20)}}
    # profitable realized net → ci_low > 0
    prof = assemble_results(roster, field, realized_net=np.full(30, 50.0),
                            depth_capped_survives=True, config=cfg)
    assert prof.realized_net_ci_low > 0
    # < 2 realized harvests → unproven → (0, 0), never a spurious pass
    none = assemble_results(roster, field, realized_net=np.array([]),
                            depth_capped_survives=True, config=cfg)
    assert none.realized_net_ci_low == 0.0 and none.realized_net_ci_high == 0.0


# ── field arm construction from fills (train eligibility + forward window) ─────────────────────
def _rise_lookup():
    times = 200 * H + np.arange(-8, 9) * H
    return {"RISE": (times, 100.0 * 1.02 ** np.arange(17)),
            "FLAT": (times, np.full(17, 100.0))}


def _fills(coin, entries):
    n = len(entries)
    return pl.DataFrame({"time": list(entries), "coin": [coin] * n, "px": [100.0] * n,
                         "sz": [1.0] * n, "side": ["B"] * n, "crossed": [True] * n,
                         "startPosition": [0.0] * n, "hash": [f"0x{i}" for i in range(n)],
                         "tid": list(range(n))})


def test_eligible_field_gates_on_train_not_forward():
    look = _rise_lookup()
    t0 = 200 * H

    def prov(w, s, e):
        # `elig` has a train open (t0-3H) AND a forward open; `noise` has ONLY a forward open
        entries = {"elig": [t0 - 3 * H, t0 + 2 * H], "noise": [t0 + 2 * H]}[w]
        f = _fills("RISE", entries)
        return f.filter((pl.col("time") >= s) & (pl.col("time") < e))

    cfg = _cfg(lag_bucket_ms=0, markout_horizon_ms=H, min_positions=1)
    fm = eligible_field_markouts(["elig", "noise"], prov, train_window=(t0 - 30 * _DAY, t0),
                                 forward_window=(t0, t0 + 6 * H), lookups=look, basket=None,
                                 config=cfg)
    assert "elig" in fm and "noise" not in fm       # forward-only activity ≠ eligible


_DAY = 86_400_000


# ── end-to-end driver ─────────────────────────────────────────────────────────────────────────
def _cfg(**over):
    base = dict(
        execution="retail", universe_hash="u0", eligible_pool="p", train_days=30, follow_days=14,
        roll_cadence_days=14, min_hold_ms=3_600_000, min_positions=5, beta=1.0, gross_target=1.0,
        max_coin_frac=0.08, max_wallet_frac=0.05, also_run_uncapped=True, lag_bucket_ms=900_000,
        fee_bps=4.5, impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=1000.0,
        primary_control="pool_mean", secondary_controls=("random",), min_n_nominal=20,
        min_effective_n=2, horizon_cap_days=300, mar_bps=8.0, maxdd_bound=-0.25,
        max_single_contrib_frac=0.20, cost_floor_bps=15.0, selection_signal="markout",
        markout_horizon_ms=6 * H, selection_rank="trimmed_mean")
    base.update(over)
    return ExperimentConfig(**base)


def _commit(tmp_path, cfg, roster):
    reg = Registry(tmp_path / "reg.jsonl")
    m = RunManifest.build(t0_ms=200 * H, edge_weights={w: 0.1 for w in roster},
                          train_cutoff_tids={w: 0 for w in roster}, config=cfg,
                          analysis_script_hash="ah")
    reg.register(m)
    return tmp_path / "reg.jsonl", tmp_path / "decisions.jsonl"


def _world():
    """A committed world: 25 roster wallets trade RISE long (+~200bp forward), 25 field-only
    wallets trade FLAT (~0). Every wallet has a train open (eligible)."""
    t0 = 200 * H
    roster = [f"r{i}" for i in range(25)]
    fieldonly = [f"f{i}" for i in range(25)]

    def prov(w, s, e):
        coin = "RISE" if w.startswith("r") else "FLAT"
        f = _fills(coin, [t0 - 3 * H, t0 + 2 * H])     # 1 train + 1 forward open
        return f.filter((pl.col("time") >= s) & (pl.col("time") < e))

    return roster, fieldonly, prov


def _profit_journal(tmp_path, n=30, bps=50.0):
    """A journal of profitable realized harvests → the profitability leg passes (ci_low > 0)."""
    j = RealizedJournal(tmp_path / "realized.jsonl")
    j.append([_rt(wallet=f"r{i % 25}", entry_ms=i * H, exit_ms=(i + 6) * H, raw_bps=bps)
              for i in range(n)])
    return j


def test_run_gate_decision_go_when_roster_beats_field_and_profitable(tmp_path):
    cfg = _cfg(lag_bucket_ms=0, markout_horizon_ms=H, min_positions=1)
    roster, fieldonly, prov = _world()
    reg_path, log = _commit(tmp_path, cfg, roster)
    v, r = run_gate_decision(
        config=cfg, registry_path=reg_path, decision_log=log, candidates=roster + fieldonly,
        field_fills_provider=prov, lookups=_rise_lookup(), basket=None, now_ms=200 * H + 6 * H,
        depth_capped_survives=True, journal=_profit_journal(tmp_path))
    assert v.decision == "GO"
    assert r.n_nominal == 25 and r.top_minus_control_ci_low >= cfg.mar_bps
    assert r.realized_net_ci_low > 0


def test_run_gate_decision_inconclusive_when_selection_but_no_realized(tmp_path):
    # roster clears MAR on selection skill, but NO realized harvests → profitability unproven
    cfg = _cfg(lag_bucket_ms=0, markout_horizon_ms=H, min_positions=1)
    roster, fieldonly, prov = _world()
    reg_path, log = _commit(tmp_path, cfg, roster)
    v, r = run_gate_decision(
        config=cfg, registry_path=reg_path, decision_log=log, candidates=roster + fieldonly,
        field_fills_provider=prov, lookups=_rise_lookup(), basket=None, now_ms=200 * H + 6 * H,
        depth_capped_survives=True)                            # no journal
    assert v.decision == "INCONCLUSIVE" and r.top_minus_control_ci_low >= cfg.mar_bps
    assert "profitability not yet proven" in v.reasons[0]


def test_run_gate_decision_empty_field_raises_not_go(tmp_path):
    # min_positions unreachable → NO eligible field → must RAISE, never zero-null → GO
    cfg = _cfg(lag_bucket_ms=0, markout_horizon_ms=H, min_positions=10_000)
    roster, fieldonly, prov = _world()
    reg_path, log = _commit(tmp_path, cfg, roster)
    with pytest.raises(ValueError, match="empty TOP or CONTROL"):
        run_gate_decision(
            config=cfg, registry_path=reg_path, decision_log=log, candidates=roster + fieldonly,
            field_fills_provider=prov, lookups=_rise_lookup(), basket=None, now_ms=200 * H + 6 * H,
            depth_capped_survives=True)


def test_run_gate_decision_requires_committed_run(tmp_path):
    cfg = _cfg()
    with pytest.raises(ValueError, match="no committed run"):
        run_gate_decision(
            config=cfg, registry_path=tmp_path / "none.jsonl", decision_log=tmp_path / "d.jsonl",
            candidates=[], field_fills_provider=lambda w, s, e: None, lookups={}, basket=None,
            now_ms=1, depth_capped_survives=True)


def test_run_gate_decision_read_once(tmp_path):
    cfg = _cfg(lag_bucket_ms=0, markout_horizon_ms=H, min_positions=1)
    roster, fieldonly, prov = _world()
    reg_path, log = _commit(tmp_path, cfg, roster)
    kw = dict(config=cfg, registry_path=reg_path, decision_log=log,
              candidates=roster + fieldonly, field_fills_provider=prov, lookups=_rise_lookup(),
              basket=None, now_ms=200 * H + 6 * H, depth_capped_survives=True,
              journal=_profit_journal(tmp_path))
    assert run_gate_decision(**kw)[0].decision == "GO"        # first read = final GO
    with pytest.raises(ValueError, match="read-once|already has a final"):
        run_gate_decision(**kw)


def test_roster_markouts_prices_forward_opens(tmp_path):
    cfg = _cfg(lag_bucket_ms=0, markout_horizon_ms=H, min_positions=1)
    roster, _fieldonly, prov = _world()
    rm = roster_markouts(roster[:3], prov, window=(200 * H, 200 * H + 6 * H),
                         lookups=_rise_lookup(), basket=None, config=cfg)
    assert set(rm) == {"r0", "r1", "r2"}
    assert all(a.size == 1 and a[0] > 100.0 for a in rm.values())   # RISE long ≈ +200bp
