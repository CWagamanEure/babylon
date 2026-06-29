import json

import pytest

from babylon.follow.experiment import (
    ExperimentConfig, RunManifest, Registry, Results, decide,
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


def _manifest(cfg, t0=1000):
    return RunManifest.build(t0_ms=t0, edge_weights={"0xa": 0.5, "0xb": 0.5},
                             train_cutoff_tids={"0xa": 1, "0xb": 2}, config=cfg,
                             analysis_script_hash="ah")


def _res(**over):
    base = dict(n_effective=150, n_nominal=1600, top_minus_control_ci_low=10.0,
                top_minus_control_ci_high=30.0, top_vs_poolmean_significant=True, maxdd=-0.18,
                depth_capped_survives=True, max_single_contrib_frac=0.12)
    base.update(over)
    return Results(**base)


def _setup(tmp_path, cfg=None):
    cfg = cfg or _cfg()
    reg = Registry(tmp_path / "reg.jsonl")
    m = _manifest(cfg)
    rid = reg.register(m)
    return cfg, reg, rid, tmp_path / "decisions.jsonl"


def test_config_validates_and_hashes():
    c = _cfg(); c.validate()
    assert c.hash() == _cfg().hash() and _cfg(mar_bps=10.0).hash() != c.hash()


def test_config_rejects_nonsense():
    for bad in (dict(maxdd_bound=0.25), dict(mar_bps=0.0), dict(max_single_contrib_frac=1.0),
                dict(min_effective_n=10_000_000), dict(secondary_controls=()), dict(beta=float("nan"))):
        with pytest.raises(AssertionError):
            _cfg(**bad).validate()


def test_run_id_sensitive_and_order_invariant():
    cfg = _cfg()
    m1 = RunManifest.build(t0_ms=1, edge_weights={"a": .5, "b": .5}, train_cutoff_tids={"a": 1, "b": 2}, config=cfg, analysis_script_hash="ah")
    m2 = RunManifest.build(t0_ms=1, edge_weights={"a": .5, "c": .5}, train_cutoff_tids={"a": 1, "c": 2}, config=cfg, analysis_script_hash="ah")
    m3 = RunManifest.build(t0_ms=1, edge_weights={"b": .5, "a": .5}, train_cutoff_tids={"b": 2, "a": 1}, config=cfg, analysis_script_hash="ah")
    assert m1.run_id() != m2.run_id() and m1.run_id() == m3.run_id()


def test_manifest_rejects_nonfinite_weights():
    with pytest.raises(AssertionError):
        RunManifest.build(t0_ms=1, edge_weights={"a": float("inf")}, train_cutoff_tids={"a": 1},
                          config=_cfg(), analysis_script_hash="ah")


def test_registry_blocks_rerank_and_detects_tamper(tmp_path):
    cfg, reg, rid, _ = _setup(tmp_path)
    assert reg.register(_manifest(cfg)) == rid                     # idempotent
    rerank = RunManifest.build(t0_ms=1000, edge_weights={"0xz": 1.0}, train_cutoff_tids={"0xz": 9},
                               config=cfg, analysis_script_hash="ah")
    with pytest.raises(ValueError, match="immutable"):
        reg.register(rerank)
    with pytest.raises(ValueError, match="clean-OOS"):
        reg.verify_resume(rerank)
    # tamper the manifest body in place, keep the run_id -> chain/derive check must catch it
    p = tmp_path / "reg.jsonl"
    rec = json.loads(p.read_text().splitlines()[0])
    body = json.loads(rec["body"]); body["manifest"]["roster"] = ["0xEVIL"]
    rec["body"] = json.dumps(body, sort_keys=True, separators=(",", ":"))
    p.write_text(json.dumps(rec, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="tampered"):
        reg.committed(1000)


def test_decide_requires_committed_run(tmp_path):
    cfg, reg, rid, log = _setup(tmp_path)
    with pytest.raises(ValueError, match="not in the registry"):
        decide(cfg, _res(), registry=reg, run_id="run_bogus", decision_log=log, results_hash="rh")


def test_decide_rejects_posthoc_config_change(tmp_path):
    cfg, reg, rid, log = _setup(tmp_path)
    cheaper = _cfg(mar_bps=2.0)  # lower the bar after the fact
    with pytest.raises(ValueError, match="post-hoc"):
        decide(cheaper, _res(top_minus_control_ci_low=5.0), registry=reg, run_id=rid,
               decision_log=log, results_hash="rh")


def test_decide_recomputes_min_n(tmp_path):
    cfg, reg, rid, log = _setup(tmp_path)
    v = decide(cfg, _res(n_nominal=10, n_effective=2), registry=reg, run_id=rid,
               decision_log=log, results_hash="rh")
    assert v.decision == "INCONCLUSIVE"  # below min-n regardless of a great CI


def test_decide_read_once(tmp_path):
    cfg, reg, rid, log = _setup(tmp_path)
    assert decide(cfg, _res(), registry=reg, run_id=rid, decision_log=log, results_hash="r1").decision == "GO"
    with pytest.raises(ValueError, match="read-once"):
        decide(cfg, _res(top_minus_control_ci_low=20.0), registry=reg, run_id=rid,
               decision_log=log, results_hash="r2")  # second read refused


def test_decision_rule_outcomes(tmp_path):
    cfg, reg, rid, log = _setup(tmp_path)
    # straddle -> INCONCLUSIVE
    assert decide(cfg, _res(top_minus_control_ci_low=3.0), registry=reg, run_id=rid,
                  decision_log=log, results_hash="a").decision == "INCONCLUSIVE"


def test_no_go_conditions(tmp_path):
    for over in (dict(top_minus_control_ci_low=-5.0, top_minus_control_ci_high=-1.0),
                 dict(top_vs_poolmean_significant=False),
                 dict(depth_capped_survives=False), dict(maxdd=-0.40),
                 dict(max_single_contrib_frac=0.35)):
        cfg, reg, rid, log = _setup(tmp_path / json.dumps(over, sort_keys=True).replace("/", "_"))
        assert decide(cfg, _res(**over), registry=reg, run_id=rid, decision_log=log,
                      results_hash="x").decision == "NO_GO"
