import numpy as np

from babylon.follow.weights import kelly_weights


def test_higher_edge_gets_more_weight():
    rng = np.random.default_rng(0)
    rets = {
        "good": rng.normal(40, 100, 500),   # higher mean, same vol (tight: mean reliably +)
        "weak": rng.normal(15, 100, 500),
        "noisy": rng.normal(40, 300, 500),  # same mean as good, more vol → less weight
    }
    w = kelly_weights(rets, fractional=0.25, max_frac=0.9)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["good"] > w["weak"]    # higher edge
    assert w["good"] > w["noisy"]   # same edge, lower variance


def test_negative_edge_dropped():
    rng = np.random.default_rng(1)
    w = kelly_weights({"a": rng.normal(30, 150, 200), "loser": rng.normal(-20, 150, 200)})
    assert "loser" not in w and "a" in w


def test_cap_binds_and_normalizes():
    rng = np.random.default_rng(2)
    # 50 wallets, one with a huge edge; cap at 5% must bind on it
    rets = {f"w{i}": rng.normal(15, 200, 100) for i in range(50)}
    rets["whale"] = rng.normal(500, 100, 100)
    w = kelly_weights(rets, max_frac=0.05)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert max(w.values()) <= 0.05 + 1e-9
    assert w["whale"] == max(w.values())  # still the largest, just capped


def test_few_wallets_equal_weight_when_cap_infeasible():
    rng = np.random.default_rng(3)
    w = kelly_weights({"a": rng.normal(30, 150, 100), "b": rng.normal(20, 150, 100)},
                      max_frac=0.05)  # 2 wallets can't sum to 1 at 5% each
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(abs(v - 0.5) < 1e-9 for v in w.values())


def test_empty_and_no_edge():
    assert kelly_weights({}) == {}
    assert kelly_weights({"a": np.array([5.0])}) == {}  # <2 obs
