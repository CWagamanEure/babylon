import numpy as np
import pytest

from babylon.follow.experiment import ExperimentConfig, Registry
from babylon.follow.scheduler import RollScheduler, select_roster


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


def _returns(seed, mu, n=60, sd=20):
    return np.random.default_rng(seed).normal(mu, sd, n)


def test_select_ranks_top_quintile_and_weights():
    # 10 wallets, well-separated descending edge; top quintile (frac 0.2) = top 2
    rets = {f"w{i}": _returns(i, 300 - i * 30) for i in range(10)}
    cuts = {f"w{i}": 1000 + i for i in range(10)}
    roster, weights, cutoffs = select_roster(rets, cuts, top_quintile_frac=0.2, min_positions=6)
    assert set(roster) == {"w0", "w1"}                  # the two best by median
    assert abs(sum(weights.values()) - 1.0) < 1e-9 or all(v <= 0.05 for v in weights.values())
    assert cutoffs == {"w0": 1000, "w1": 1001}          # seam tids carried for the roster only


def test_select_caps_roster_size():
    rets = {f"w{i}": _returns(i, 300 - i * 4) for i in range(40)}
    cuts = {f"w{i}": i for i in range(40)}
    roster, w, _ = select_roster(rets, cuts, top_quintile_frac=1.0, min_positions=6,
                                 max_roster_size=10)
    assert len(roster) == 10 and all(v <= 0.05 + 1e-12 for v in w.values())  # top-10 only


def test_select_drops_thin_wallets():
    rets = {"good": _returns(1, 40, n=40), "thin": _returns(2, 99, n=3)}  # thin has best mean but <min
    roster, _, _ = select_roster(rets, {"good": 1, "thin": 2}, top_quintile_frac=1.0, min_positions=6)
    assert roster == ["good"]                            # thin excluded despite a higher mean


def test_select_empty_when_none_eligible():
    roster, w, c = select_roster({"a": _returns(1, 50, n=2)}, {"a": 1}, min_positions=6)
    assert roster == [] and w == {} and c == {}


def test_roll_registers_immutable_manifest(tmp_path):
    reg = Registry(tmp_path / "reg.jsonl")
    cfg = _cfg()
    rets = {f"w{i}": _returns(i, 50 - i * 5) for i in range(8)}
    cuts = {f"w{i}": 2000 + i for i in range(8)}
    sched = RollScheduler(list(rets), lambda w, t: rets[w], lambda w, t: cuts[w], cfg, reg,
                          analysis_script_hash="ah", top_quintile_frac=0.25)
    roster, weights, rid = sched.roll(t0_ms=10_000)
    assert roster and rid.startswith("run_")
    # idempotent: re-rolling the identical selection at the same T0 returns the same run_id
    assert sched.roll(t0_ms=10_000)[2] == rid
    # a DIFFERENT selection at the same T0 is refused (immutable pre-registration)
    other = RollScheduler(list(rets), lambda w, t: _returns(w.__hash__() % 7 + 99, 30),
                          lambda w, t: cuts[w], cfg, reg, analysis_script_hash="ah")
    with pytest.raises(ValueError, match="immutable"):
        other.roll(t0_ms=10_000)


def test_roll_distinct_t0_distinct_run(tmp_path):
    reg = Registry(tmp_path / "reg.jsonl")
    cfg = _cfg()
    rets = {f"w{i}": _returns(i, 50 - i * 5) for i in range(8)}
    sched = RollScheduler(list(rets), lambda w, t: rets[w], lambda w, t: 1, cfg, reg,
                          analysis_script_hash="ah", top_quintile_frac=0.25)
    rid1 = sched.roll(t0_ms=10_000)[2]
    rid2 = sched.roll(t0_ms=20_000)[2]                  # next sub-period → new manifest
    assert rid1 != rid2


def test_roll_empty_roster_raises(tmp_path):
    reg = Registry(tmp_path / "reg.jsonl")
    sched = RollScheduler(["a"], lambda w, t: _returns(1, 50, n=2), lambda w, t: 1,
                          _cfg(), reg, analysis_script_hash="ah")
    with pytest.raises(ValueError, match="empty roster"):
        sched.roll(t0_ms=10_000)
