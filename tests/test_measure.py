import numpy as np

from babylon.follow.experiment import ExperimentConfig, Registry, RunManifest, decide
from babylon.follow.measure import (
    RollingEdgeMonitor, block_bootstrap_ci, effective_n, max_drawdown, measure,
    single_contrib_frac,
)


def _cfg(**over):
    base = dict(
        execution="retail", universe_hash="u0", eligible_pool="longhold_taker_conviction",
        train_days=30, follow_days=14, roll_cadence_days=14, min_hold_ms=3_600_000,
        min_positions=6, beta=1.245, gross_target=1.0, max_coin_frac=0.08,
        max_wallet_frac=0.05, also_run_uncapped=True, lag_bucket_ms=60_000, fee_bps=4.5,
        impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=1_000.0,
        primary_control="pool_mean", secondary_controls=("random", "sign_shuffle"),
        min_n_nominal=1500, min_effective_n=120, horizon_cap_days=300, mar_bps=8.0,
        maxdd_bound=-0.25, max_single_contrib_frac=0.20, cost_floor_bps=15.0,
    )
    base.update(over)
    return ExperimentConfig(**base)


def test_max_drawdown():
    assert max_drawdown(np.array([100, 120, 90, 110])) == (90 - 120) / 120
    assert max_drawdown(np.array([100, 110, 120])) == 0.0


def test_block_bootstrap_ci_separates_signal_from_noise():
    rng = np.random.default_rng(0)
    pos = block_bootstrap_ci(rng.normal(20, 50, 1500), block=10)
    zero = block_bootstrap_ci(rng.normal(0, 50, 1500), block=10)
    mid = lambda ci: (ci[0] + ci[1]) / 2
    assert pos[0] > 5 and mid(pos) > 15    # clear positive edge: CI well above 0
    assert abs(mid(zero)) < 5              # no edge: CI centred near 0
    assert zero[0] < pos[0]                # noise shows no comparable lower-bound edge


def test_effective_n_drops_with_autocorrelation():
    rng = np.random.default_rng(1)
    iid = rng.normal(0, 1, 2000)
    # AR(1) ρ≈0.7 series → strongly autocorrelated
    ar = np.zeros(2000); e = rng.normal(0, 1, 2000)
    for i in range(1, 2000):
        ar[i] = 0.7 * ar[i - 1] + e[i]
    assert effective_n(iid) > 1500                  # ~iid: effective ≈ nominal
    assert effective_n(ar) < 600                    # autocorrelated: far fewer effective obs


def test_single_contrib_frac():
    assert abs(single_contrib_frac({"a": 6, "b": 2, "c": 2}) - 0.6) < 1e-9
    assert single_contrib_frac({}) == 0.0


def test_measure_builds_valid_results():
    rng = np.random.default_rng(2)
    top, ctrl = rng.normal(25, 90, 2000), rng.normal(0, 90, 2000)
    eq = 1000 + np.cumsum(top) * 0.01
    contrib = {f"w{i}": 10.0 for i in range(6)}     # even spread → low concentration
    r = measure(top, ctrl, eq, contrib, block=10, depth_capped_survives=True)
    r.validate()
    assert r.n_nominal == 2000 and r.top_minus_control_ci_low <= r.top_minus_control_ci_high
    assert r.max_single_contrib_frac < 0.20


def _committed(tmp_path, cfg):
    reg = Registry(tmp_path / "reg.jsonl")
    m = RunManifest.build(t0_ms=1, edge_weights={"a": 0.5, "b": 0.5},
                          train_cutoff_tids={"a": 1, "b": 2}, config=cfg, analysis_script_hash="ah")
    rid = reg.register(m)
    return reg, rid, tmp_path / "dec.jsonl"


def test_measure_to_decide_go(tmp_path):
    cfg = _cfg()
    reg, rid, log = _committed(tmp_path, cfg)
    rng = np.random.default_rng(3)
    top, ctrl = rng.normal(30, 80, 2000), rng.normal(0, 80, 2000)   # strong, well-powered edge
    eq = 1000 + np.cumsum(top - ctrl) * 0.005
    r = measure(top, ctrl, eq, {f"w{i}": 5.0 for i in range(8)}, block=10,
                depth_capped_survives=True)
    v = decide(cfg, r, registry=reg, run_id=rid, decision_log=log, results_hash="rh")
    assert v.decision == "GO" and r.top_minus_control_ci_low >= cfg.mar_bps


def test_measure_to_decide_inconclusive_when_underpowered(tmp_path):
    cfg = _cfg()
    reg, rid, log = _committed(tmp_path, cfg)
    rng = np.random.default_rng(4)
    top, ctrl = rng.normal(10, 80, 2000), rng.normal(0, 80, 2000)   # +10bp: real but < MAR 8? near
    r = measure(top, ctrl, 1000 + np.cumsum(top) * 0.01, {f"w{i}": 5.0 for i in range(8)},
                block=10, depth_capped_survives=True)
    v = decide(cfg, r, registry=reg, run_id=rid, decision_log=log, results_hash="rh")
    # significant vs pool-mean (CI>0) but lower bound straddles MAR → not a pass
    assert v.decision == "INCONCLUSIVE" and r.top_vs_poolmean_significant


def test_rolling_monitor_observe_only():
    mon = RollingEdgeMonitor(block=5)
    assert mon.estimate()["n"] == 0
    rng = np.random.default_rng(5)
    for t, c in zip(rng.normal(15, 40, 300), rng.normal(0, 40, 300)):
        mon.observe(t, c)
    est = mon.estimate()
    assert est["n"] == 300 and est["mean"] > 0 and est["ci"][0] < est["mean"] < est["ci"][1] + 1e9
