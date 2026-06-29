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
        impact_bps=6.0, max_depth_frac=0.25, target_notional_usd=50_000.0,
        primary_control="pool_mean", secondary_controls=("random", "sign_shuffle"),
        min_n_nominal=1500, min_effective_n=120, horizon_cap_days=300, mar_bps=8.0,
        maxdd_bound=-0.25, max_single_contrib_frac=0.20,
    )
    base.update(over)
    return ExperimentConfig(**base)


def _res(**over):
    base = dict(
        reached_min_n=True, n_effective=150, top_minus_control_ci_low=10.0,
        top_minus_control_ci_high=30.0, top_vs_poolmean_significant=True, maxdd=-0.18,
        depth_capped_survives=True, max_single_contrib_frac=0.12,
    )
    base.update(over)
    return Results(**base)


def test_config_validates_and_hashes_deterministically():
    c = _cfg(); c.validate()
    assert c.hash() == _cfg().hash()
    assert _cfg(mar_bps=10.0).hash() != c.hash()  # any change -> new hash


def test_config_rejects_nonsense():
    with pytest.raises(AssertionError):
        _cfg(maxdd_bound=0.25).validate()        # must be negative
    with pytest.raises(AssertionError):
        _cfg(primary_control="random").validate()  # must be pool_mean


def test_run_id_changes_with_roster_and_tids():
    m1 = RunManifest(1000, ("0xa", "0xb"), {"0xa": 0.5, "0xb": 0.5}, {"0xa": 1, "0xb": 2}, "ch", "ah")
    m2 = RunManifest(1000, ("0xa", "0xc"), {"0xa": 0.5, "0xc": 0.5}, {"0xa": 1, "0xc": 2}, "ch", "ah")
    m3 = RunManifest(1000, ("0xa", "0xb"), {"0xa": 0.5, "0xb": 0.5}, {"0xa": 1, "0xb": 9}, "ch", "ah")
    assert m1.run_id() != m2.run_id()  # different roster
    assert m1.run_id() != m3.run_id()  # different train-cutoff tid (seam guard)
    assert m1.run_id() == RunManifest(1000, ("0xa", "0xb"), {"0xb": 0.5, "0xa": 0.5},
                                      {"0xb": 2, "0xa": 1}, "ch", "ah").run_id()  # order-invariant


def test_registry_blocks_silent_rerank(tmp_path):
    reg = Registry(tmp_path / "reg.jsonl")
    m = RunManifest(1000, ("0xa",), {"0xa": 1.0}, {"0xa": 1}, "ch", "ah")
    rid = reg.register(m)
    assert reg.register(m) == rid                       # idempotent
    rerank = RunManifest(1000, ("0xb",), {"0xb": 1.0}, {"0xb": 5}, "ch", "ah")  # same T0, new roster
    with pytest.raises(ValueError, match="immutable"):
        reg.register(rerank)
    with pytest.raises(ValueError, match="clean-OOS"):
        reg.verify_resume(rerank)
    reg.verify_resume(m)                                # the committed one resumes fine


def test_decision_no_peeking_before_min_n():
    assert decide(_cfg(), _res(reached_min_n=False)).decision == "INCONCLUSIVE"


def test_decision_go():
    v = decide(_cfg(), _res(top_minus_control_ci_low=10.0))
    assert v.decision == "GO"


def test_decision_inconclusive_straddle():
    # CI lower bound below MAR but upper bound positive -> underpowered, not a pass
    v = decide(_cfg(), _res(top_minus_control_ci_low=3.0, top_minus_control_ci_high=20.0))
    assert v.decision == "INCONCLUSIVE"


def test_decision_no_go_conditions():
    assert decide(_cfg(), _res(top_minus_control_ci_high=-1.0)).decision == "NO_GO"   # no edge
    assert decide(_cfg(), _res(top_vs_poolmean_significant=False)).decision == "NO_GO"  # = follow everyone
    assert decide(_cfg(), _res(depth_capped_survives=False)).decision == "NO_GO"       # capacity
    assert decide(_cfg(), _res(maxdd=-0.40)).decision == "NO_GO"                       # DD breach
    assert decide(_cfg(), _res(max_single_contrib_frac=0.35)).decision == "NO_GO"      # ZEC-style concentration
