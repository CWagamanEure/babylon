from __future__ import annotations

from decimal import Decimal

import duckdb
import numpy as np
import pytest

from research.studies.copy_cohort import dynamic_t_book as dtb
from research.studies.copy_cohort import lake
from research.studies.copy_cohort.dynamic_t_book import (
    DAY_MS,
    HOLD_MS,
    STALE_MS,
    _arm_fold,
    _context_records,
    _resample_delta,
    _validate_context_content,
    accept_book,
    add_missingness_sensitivity,
    common_context_cutoff,
    common_support_sql,
    compare,
    consensus_other_counts,
    finalize_decision_flags,
    holm_adjust,
    holm_adjust_null,
    online_quarantined,
    validate_context_day_sets,
    validate_roster_profile,
)
from research.studies.copy_cohort.dynamic_t_quality import (
    HL21_PROFILE,
    HL60_PROFILE,
    Panel,
    _cache_spec,
    ew_t,
    formation_months,
    hac_t,
    latest_shock_index,
    normalized_x,
    score_panel,
    topk,
    weighted_stats,
)
from research.studies.copy_cohort.filtered_quality import _sha256_json


def test_equal_weight_stats_reduce_to_ordinary_sample_stats():
    x = np.array([1.0, 2.0, 4.0, 8.0])
    mu, var, neff = weighted_stats(x, np.zeros(x.size), half_life=21.0)
    assert np.isclose(mu, x.mean())
    assert np.isclose(var, x.var(ddof=1))
    assert np.isclose(neff, x.size)


def test_ew_t_rewards_recent_improvement_relative_to_recent_decline():
    ordinal = np.arange(100, 140)
    improving = np.r_[np.full(20, -1.0), np.full(20, 2.0)]
    declining = improving[::-1]
    a, _ = ew_t(improving, ordinal, 139, half_life=21.0)
    b, _ = ew_t(declining, ordinal, 139, half_life=21.0)
    assert a > b


def test_hac_score_is_finite_on_persistent_signal():
    x = np.linspace(1.0, 3.0, 40) + np.sin(np.arange(40))
    ordinal = np.arange(100, 140)
    assert np.isfinite(hac_t(x, ordinal, 139, weighted=False, half_life=21.0))
    assert np.isfinite(hac_t(x, ordinal, 139, weighted=True, half_life=21.0))


def test_frozen_half_life_profiles_change_all_weighted_scores_and_isolate_paths():
    ordinal = np.arange(60, 140)
    x = np.r_[np.full(40, -2.0), np.full(40, 3.0)] + np.sin(np.arange(80))
    ew21, _ = ew_t(x, ordinal, 139, half_life=HL21_PROFILE.half_life_days)
    ew60, _ = ew_t(x, ordinal, 139, half_life=HL60_PROFILE.half_life_days)
    hac21 = hac_t(
        x, ordinal, 139, weighted=True, half_life=HL21_PROFILE.half_life_days
    )
    hac60 = hac_t(
        x, ordinal, 139, weighted=True, half_life=HL60_PROFILE.half_life_days
    )
    assert not np.isclose(ew21, ew60)
    assert not np.isclose(hac21, hac60)
    assert HL21_PROFILE.derived != HL60_PROFILE.derived
    assert HL21_PROFILE.rosters != HL60_PROFILE.rosters


def test_book_rejects_roster_from_different_frozen_profile():
    roster = {
        "architecture": HL21_PROFILE.architecture,
        "config": {
            "experiment_id": HL21_PROFILE.experiment_id,
            "half_life_days": HL21_PROFILE.half_life_days,
        },
    }
    with pytest.raises(RuntimeError, match="roster/profile mismatch"):
        validate_roster_profile(roster, HL60_PROFILE)


def test_latest_shock_retains_most_recent_shock_day():
    x = np.array([100.0, -11_000.0, 50.0, 60.0])
    liq = np.array([0, 0, 1, 0])
    assert latest_shock_index(x, liq, np.arange(4)) == 2


def test_topk_fails_loudly_on_short_finite_roster():
    with np.testing.assert_raises(RuntimeError):
        topk(np.array(["a", "b"]), np.array([1.0, np.nan]), 2)


def test_topk_is_exact_and_uses_wallet_ascending_tie_break():
    wallets = np.array([f"w{i:02d}" for i in range(35)])[::-1]
    assert topk(wallets, np.ones(35)) == [f"w{i:02d}" for i in range(30)]


def test_online_quarantine_starts_next_day_and_is_inclusive_day30():
    shocks = {"w": [100]}
    assert not online_quarantined("w", 100 * DAY_MS, shocks)
    assert online_quarantined("w", 101 * DAY_MS, shocks)
    assert online_quarantined("w", 130 * DAY_MS, shocks)
    assert not online_quarantined("w", 131 * DAY_MS, shocks)


def test_acceptance_wallet_cap_and_exit_equals_entry_boundary():
    ent = {
        "wallet": np.array(["w"] * 6),
        "coin": np.array([f"c{i}" for i in range(6)]),
        "signal_ts": np.zeros(6, np.int64),
        "entry_ts": np.zeros(6, np.int64),
        "exit_ts": np.full(6, 10, np.int64),
        "dir": np.ones(6, np.int64),
    }
    keep, funnel = accept_book(ent)
    assert keep.size == 4
    assert funnel["n_wallet_cap_skip"] == 2

    boundary = {"wallet": np.array(["w", "w"]), "coin": np.array(["BTC", "BTC"]),
                "signal_ts": np.array([0, 10]), "entry_ts": np.array([0, 10]),
                "exit_ts": np.array([10, 20]), "dir": np.ones(2, np.int64)}
    keep, _ = accept_book(boundary)
    assert keep.tolist() == [0, 1]


def test_consensus_is_strict_prior_and_distinct_other():
    entries = {"wallet": np.array(["a", "a"]), "coin": np.array(["BTC", "BTC"]),
               "signal_ts": np.array([10, 20]), "dir": np.array([1, 1])}
    signals = {"wallet": np.array(["a", "b"]), "coin": np.array(["BTC", "BTC"]),
               "ts": np.array([5, 15]), "dir": np.array([1, 1])}
    assert consensus_other_counts(entries, signals, {"a", "b"}).tolist() == [0, 1]


def test_forward_asof_uses_first_quote_after_signal():
    con = duckdb.connect()
    row = con.execute("""WITH e(t) AS (VALUES (5)), x(t,p) AS (VALUES (4,40),(6,60),(7,70))
                         SELECT x.t,x.p FROM e ASOF LEFT JOIN x ON e.t<x.t""").fetchone()
    assert row == (6, 60)


def test_crossed_resampling_preserves_constant_paired_shift():
    n = 100
    wallet = np.array([f"w{i % 10}" for i in range(n)])
    ts = np.arange(n, dtype=np.int64) * DAY_MS
    base = np.sin(np.arange(n)) * 10
    a = {"wallet": wallet, "signal_ts": ts, "net_bp": base + 5}
    b = {"wallet": wallet, "signal_ts": ts, "net_bp": base}
    got, invalid = _resample_delta(
        a, b, np.random.default_rng(4), "crossed", 0, n - 1, n_boot=300)
    assert np.allclose(got, 5.0)
    assert invalid == 0


def test_holm_adjustment_is_monotone_in_sorted_p_values():
    r = {"b": {"crossed_p_two_sided": .03}, "a": {"crossed_p_two_sided": .01},
         "c": {"crossed_p_two_sided": .04}}
    holm_adjust(r)
    assert r["a"]["holm_q"] <= r["b"]["holm_q"] <= r["c"]["holm_q"]


def test_secondary_method_null_requires_separate_null_holm_family():
    base = {
        "inference_status": "ESTIMABLE", "delta_bp": 0.0, "crossed_ci95": [-1.0, 1.0],
        "crossed_mde80_bp": 2.0, "plus5_control_pass": True, "holm_q": 1.0,
        "missingness": {"rate_gates_pass": True, "computation_status": "VALID",
                        "positive_sensitivity_pass": False, "null_sensitivity_pass": True,
                        "p_null_plus5_intersection_union": .01},
    }
    secondary = {k: {**base, "missingness": dict(base["missingness"])}
                 for k in ("a", "b", "c", "d")}
    finalize_decision_flags(dict(base), secondary)
    assert not any(v["method_null_eligible"] for v in secondary.values())
    holm_adjust_null(secondary)
    finalize_decision_flags(dict(base), secondary)
    assert all(v["method_null_eligible"] for v in secondary.values())


def test_positive_direction_does_not_require_plus5_power_but_burned_run_cannot_promote():
    result = {
        "inference_status": "ESTIMABLE", "delta_bp": 30.0,
        "crossed_ci95": [10.0, 50.0], "crossed_mde80_bp": 40.0,
        "plus5_control_pass": False,
        "missingness": {
            "rate_gates_pass": True, "computation_status": "VALID",
            "positive_sensitivity_pass": True, "null_sensitivity_pass": False,
        },
    }
    formal = {**result, "missingness": dict(result["missingness"])}
    finalize_decision_flags(formal, {})
    assert formal["within_run_positive_direction"]
    assert formal["positive_promotion_eligible"]

    burned = {**result, "missingness": dict(result["missingness"])}
    finalize_decision_flags(burned, {}, formal_eligibility=False)
    assert burned["within_run_positive_direction"]
    assert not burned["positive_promotion_eligible"]
    assert not burned["method_null_eligible"]
    assert burned["verdict_status"] == "BURNED_ADAPTIVE_CANDIDATE_DIAGNOSTIC"


def test_method_null_explicitly_requires_plus5_control():
    result = {
        "inference_status": "ESTIMABLE", "delta_bp": 0.0,
        "crossed_ci95": [-1.0, 1.0], "crossed_mde80_bp": 2.0,
        "plus5_control_pass": False,
        "missingness": {
            "rate_gates_pass": True, "computation_status": "VALID",
            "positive_sensitivity_pass": False, "null_sensitivity_pass": True,
        },
    }
    finalize_decision_flags(result, {})
    assert not result["within_run_null_resolution_pass"]
    assert not result["method_null_eligible"]


def _panel(wallet_specs: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]) -> Panel:
    wallet = np.concatenate([np.full(x.size, w) for w, x, _, _ in wallet_specs])
    x = np.concatenate([x for _, x, _, _ in wallet_specs]).astype(float)
    ordinal = np.concatenate([o for _, _, o, _ in wallet_specs]).astype(np.int64)
    liq = np.concatenate([q for _, _, _, q in wallet_specs]).astype(float)
    day = np.array([int(f"202501{(i % 28) + 1:02d}") for i in range(x.size)])
    return Panel(
        wallet=wallet, day=day, ordinal=ordinal, x=x, n_liq=liq,
        n_open_flat=np.ones(x.size), fills_per_day=np.full(x.size, 50.0),
        taker_share=np.full(x.size, .5), start_ordinal=20, end_ordinal=119,
    )


def test_common_hac_copy_pools_and_no_shock_validity_are_identical():
    specs = []
    ords = np.arange(40, 120, 4)
    for i in range(40):
        specs.append((f"w{i:02d}", 2 + np.sin(np.arange(20) + i), ords, np.zeros(20)))
    specs.append(("sparse", np.linspace(1, 2, 8), np.arange(91, 123, 4), np.zeros(8)))
    scores, diag = score_panel(_panel(specs), half_life_days=21.0)
    assert diag["n_common"] == 40
    assert diag["n_shock_valid"] == 40
    assert np.array_equal(scores["TSTAT_COMMON30"][0], scores["EW_T30"][0])
    assert np.array_equal(scores["HAC_T30"][0], scores["EW_HAC_T30"][0])
    assert np.array_equal(scores["TSTAT_COPY30"][0], scores["EW_T_COPY30"][0])
    assert "sparse" not in scores["EW_T_SHOCK30"][0]

    inactive_specs = specs[:-1] + [
        ("inactive", 2 + np.sin(np.arange(20)), np.arange(10, 50, 2), np.zeros(20))
    ]
    inactive_scores, _ = score_panel(_panel(inactive_specs), half_life_days=21.0)
    assert "inactive" in inactive_scores["TSTAT30"][0]
    assert "inactive" not in inactive_scores["TSTAT_COMMON30"][0]


def test_copyability_boundaries_and_missing_activity_are_fail_closed():
    ords = np.arange(40, 120, 4)
    specs = [(f"w{i:02d}", 2 + np.sin(np.arange(20) + i), ords, np.zeros(20))
             for i in range(35)]
    panel = _panel(specs)
    for idx, (fpd, taker) in enumerate(((np.nan, .5), (1000.0, .1),
                                        (1000.0001, .5), (50, .0999))):
        panel.fills_per_day[idx * 20:(idx + 1) * 20] = fpd
        panel.taker_share[idx * 20:(idx + 1) * 20] = taker
    scores, _ = score_panel(panel, half_life_days=21.0)
    copy_wallets = set(scores["EW_T_COPY30"][0])
    assert "w00" not in copy_wallets
    assert "w01" in copy_wallets
    assert "w02" not in copy_wallets
    assert "w03" not in copy_wallets


def test_formation_shock_reset_retains_old_shock_and_quarantines_recent_one():
    specs = []
    ords = np.arange(40, 120, 4)
    for i in range(43):
        q = np.zeros(20)
        if i == 0:
            q[0] = 1
        if i == 1:
            q[-1] = 1
        specs.append((f"w{i:02d}", 2 + np.sin(np.arange(20) + i), ords, q))
    scores, _ = score_panel(_panel(specs), half_life_days=21.0)
    shock_wallets = set(scores["EW_T_SHOCK30"][0])
    assert "w00" in shock_wallets
    assert "w01" not in shock_wallets


def test_end_to_end_ew_selector_recovers_recent_quality_and_shock_gate():
    specs = []
    ords = np.arange(60, 120, 2)
    for i in range(40):
        if i < 30:
            x = np.r_[np.full(15, -2.0), np.full(15, 5.0)] + np.sin(np.arange(30))
        else:
            x = np.r_[np.full(15, 8.0), np.full(15, -5.0)] + np.sin(np.arange(30))
        q = np.zeros(30)
        if i == 0:
            q[-1] = 1
        specs.append((f"w{i:02d}", x, ords, q))
    scores, _ = score_panel(_panel(specs), half_life_days=21.0)
    ew_roster = set(topk(*scores["EW_T30"]))
    assert ew_roster == {f"w{i:02d}" for i in range(30)}
    assert "w00" not in set(scores["EW_T_SHOCK30"][0])


def test_decimal_normalization_and_exact_split_threshold():
    assert normalized_x(Decimal("123.456789012345"), Decimal("50000")) == float(
        Decimal("123.456789012345")
    )
    assert normalized_x(Decimal("200000"), Decimal("200000")) == 100000.0
    con = duckdb.connect()
    rows = con.execute("""
      WITH x(wallet,coin,ts,dir_sign,notl) AS (
        VALUES ('w','BTC',1,1,CAST('100.000000000001' AS DECIMAL(38,12))),
               ('w','BTC',1,1,CAST('149.999999999999' AS DECIMAL(38,12))),
               ('z','BTC',1,1,CAST('249.999999999999' AS DECIMAL(38,12)))
      )
      SELECT wallet,SUM(notl) AS n,SUM(notl)>=CAST(250 AS DECIMAL(38,12)) AS pass
      FROM x GROUP BY wallet ORDER BY wallet
    """).fetchall()
    assert rows == [("w", Decimal("250.000000000000"), True),
                    ("z", Decimal("249.999999999999"), False)]


def test_coin_cap_is_twenty_equal_sized_positions():
    n = 25
    ent = {"wallet": np.array([f"w{i}" for i in range(n)]),
           "coin": np.array(["BTC"] * n), "signal_ts": np.zeros(n, np.int64),
           "entry_ts": np.zeros(n, np.int64), "exit_ts": np.full(n, 10, np.int64),
           "dir": np.ones(n, np.int64)}
    keep, funnel = accept_book(ent)
    assert keep.size == 20
    assert funnel["n_coin_cap_skip"] == 5


def test_context_registered_days_cutoff_and_per_major_gap(tmp_path):
    validate_context_day_sets(
        202511, list(range(20251101, 20251131)), [20251201, 20251202, 20251203])
    with pytest.raises(RuntimeError):
        validate_context_day_sets(202511, list(range(20251101, 20251130)),
                                  [20251201, 20251202, 20251203])
    validate_context_day_sets(202606, list(range(20260601, 20260630)), [])
    with pytest.raises(RuntimeError):
        validate_context_day_sets(202606, list(range(20260601, 20260631)), [])
    mx = {c: 1_000_000_000 for c in ("BTC", "ETH", "SOL", "HYPE")}
    assert common_context_cutoff(mx) == 1_000_000_000 - HOLD_MS - 2 * STALE_MS

    con = duckdb.connect()
    day = 20_000
    path = tmp_path / "ctx.parquet"
    con.execute(f"""COPY (
      SELECT coin,({day}::BIGINT*{DAY_MS}+i*60000)::BIGINT AS ts,1.0::DOUBLE AS mid_px
      FROM UNNEST(['BTC','ETH','SOL','HYPE']) t(coin),range(1440) r(i)
    ) TO '{path.as_posix()}' (FORMAT PARQUET)""")
    got = _validate_context_content(con, f"'{path.as_posix()}'", [20241004])
    assert got["max_gap_ms"] == 60_000
    bad = tmp_path / "bad.parquet"
    con.execute(f"""COPY (SELECT * FROM read_parquet('{path.as_posix()}')
      WHERE NOT (coin='ETH' AND ts={day}::BIGINT*{DAY_MS}+60000))
      TO '{bad.as_posix()}' (FORMAT PARQUET)""")
    bad_cov = _validate_context_content(con, f"'{bad.as_posix()}'", [20241004])
    assert bad_cov["n_major_days_with_gap_gt_stale"] > 0

    boundary = tmp_path / "boundary.parquet"
    con.execute(f"""COPY (
      WITH coins AS (SELECT * FROM UNNEST(['BTC','ETH','SOL','HYPE']) t(coin)),
      ticks AS (
        SELECT {day}::BIGINT*{DAY_MS}+i*60000 AS ts FROM range(1439) r(i)
        UNION ALL SELECT ({day}+1)::BIGINT*{DAY_MS}-90000
        UNION ALL SELECT ({day}+1)::BIGINT*{DAY_MS}+90000
        UNION ALL SELECT ({day}+1)::BIGINT*{DAY_MS}+i*60000 FROM range(2,1440) r(i)
      ) SELECT coin,ts,1.0::DOUBLE AS mid_px FROM coins,ticks
    ) TO '{boundary.as_posix()}' (FORMAT PARQUET)""")
    boundary_cov = _validate_context_content(
        con, f"'{boundary.as_posix()}'", [20241004, 20241005])
    assert boundary_cov["n_major_days_with_gap_gt_stale"] > 0

    original = _context_records([str(path)])[0]["sha256"]
    path.write_bytes(path.read_bytes() + b"content mutation")
    assert _context_records([str(path)])[0]["sha256"] != original


def test_all_four_major_support_fails_on_unrelated_entry_or_exit_gap():
    con = duckdb.connect()
    ctes, last, expr = common_support_sql()

    def supported(hype_entry: int, hype_exit_delay: int) -> bool:
        rows = []
        for coin in ("BTC", "ETH", "SOL", "HYPE"):
            entry = hype_entry if coin == "HYPE" else 10
            delay = hype_exit_delay if coin == "HYPE" else 10
            rows.extend([(coin, entry), (coin, entry + HOLD_MS + delay)])
        con.execute("CREATE OR REPLACE TEMP TABLE ctx(coin VARCHAR,ts BIGINT)")
        con.executemany("INSERT INTO ctx VALUES (?,?)", rows)
        return bool(con.execute(f"""WITH ent(ts) AS (VALUES (0)),{ctes}
          SELECT COALESCE({expr},FALSE) FROM {last}""").fetchone()[0])

    assert supported(10, 10)
    assert not supported(STALE_MS + 1, 10)
    assert not supported(10, STALE_MS + 1)


def test_exact_may30_partial_exception_preserves_full_may31(tmp_path):
    con = duckdb.connect()
    may30 = 20_603
    path = tmp_path / "may.parquet"
    con.execute(f"""COPY (
      WITH coins AS (SELECT * FROM UNNEST(['BTC','ETH','SOL','HYPE']) t(coin)),
      ticks AS (
        SELECT {may30}::BIGINT*{DAY_MS}+i*60000 AS ts FROM range(418) r(i)
        UNION ALL
        SELECT ({may30}+1)::BIGINT*{DAY_MS}+i*60000 AS ts FROM range(1440) r(i)
      ) SELECT coin,ts,1.0::DOUBLE AS mid_px FROM coins,ticks
    ) TO '{path.as_posix()}' (FORMAT PARQUET)""")
    cov = _validate_context_content(
        con, f"'{path.as_posix()}'", [20260530, 20260531])
    assert len(cov["partial_major_days"]) == 4
    mx = dict(con.execute(f"SELECT coin,MAX(ts) FROM read_parquet('{path.as_posix()}') "
                          "GROUP BY coin").fetchall())
    assert common_context_cutoff(mx) > (may30 + 1) * DAY_MS
    with pytest.raises(RuntimeError):
        _validate_context_content(con, f"'{path.as_posix()}'", [20260529, 20260531])
    full = tmp_path / "may_full.parquet"
    con.execute(f"""COPY (
      SELECT coin,{may30}::BIGINT*{DAY_MS}+i*60000 AS ts,1.0::DOUBLE AS mid_px
      FROM UNNEST(['BTC','ETH','SOL','HYPE']) t(coin),range(1440) r(i)
    ) TO '{full.as_posix()}' (FORMAT PARQUET)""")
    with pytest.raises(RuntimeError):
        _validate_context_content(con, f"'{full.as_posix()}'", [20260530])


def test_priceability_precedes_capacity_and_funnel_conserves():
    entries = {
        "wallet": np.array(["w", "w"]), "coin": np.array(["BTC", "BTC"]),
        "signal_ts": np.array([0, 10]), "entry_ts": np.array([1, 11]),
        "exit_ts": np.array([20, 30]), "dir_sign": np.ones(2, np.int64),
        "notl": np.array([300.0, 300.0]), "gross_bp": np.array([np.nan, 10.0]),
        "entry_supported": np.array([False, True]),
        "common_outcome_support": np.array([False, True]),
    }
    signals = {
        "wallet": np.array(["w", "w"]), "coin": np.array(["BTC", "BTC"]),
        "ts": np.array([0, 10]), "dir_sign": np.ones(2, np.int64),
        "notl": np.array([300.0, 300.0]), "is_ambiguous": np.zeros(2, bool),
        "passes_cutoff": np.ones(2, bool),
    }
    out, f = _arm_fold(entries, signals, ["w"], 202511, {}, False)
    assert out["signal_ts"].tolist() == [0]
    assert not out["entry_context_available"][0]
    assert f["n_threshold_candidates"] == (
        f["n_online_quarantine"] + f["n_capacity_candidates"])
    assert f["n_capacity_candidates"] == (
        f["n_accepted_capacity"] + f["n_wallet_coin_skip"]
        + f["n_wallet_cap_skip"] + f["n_coin_cap_skip"])
    assert f["n_accepted_capacity"] == (
        f["n_accepted"] + f["n_common_support_excluded_after_accept"]
        + f["n_defensive_exit_failure"])


def test_missing_entry_reserves_before_later_cross_coin_wallet_capacity():
    t = np.array([1_000, 1_000, 1_000, 1_100, 1_110], np.int64)
    entries = {
        "wallet": np.array(["w"] * 5),
        "coin": np.array(["c0", "c1", "c2", "BTC", "ETH"]),
        "signal_ts": t, "entry_ts": np.array([1_001, 1_001, 1_001, 1_200, 1_111]),
        "exit_ts": t + HOLD_MS, "dir_sign": np.ones(5, np.int64),
        "notl": np.full(5, 300.0), "gross_bp": np.array([1., 1., 1., np.nan, 1.]),
        "entry_supported": np.array([True, True, True, False, True]),
        "common_outcome_support": np.array([True, True, True, False, True]),
    }
    signals = {
        "wallet": entries["wallet"], "coin": entries["coin"], "ts": t,
        "dir_sign": entries["dir_sign"], "notl": entries["notl"],
        "is_ambiguous": np.zeros(5, bool), "passes_cutoff": np.ones(5, bool),
    }
    out, f = _arm_fold(entries, signals, ["w"], 202511, {}, False)
    assert out["signal_ts"].tolist() == [1_000, 1_000, 1_000, 1_100]
    assert f["n_entry_context_reserved"] == 1
    assert f["n_wallet_cap_skip"] == 1


def test_outcome_support_never_backfills_or_changes_consensus():
    t = np.array([0, 1, HOLD_MS + 1, HOLD_MS + STALE_MS], np.int64)
    base = {
        "wallet": np.array(["w"] * 4), "coin": np.array(["BTC"] * 4),
        "signal_ts": t, "entry_ts": t, "exit_ts": t + HOLD_MS,
        "dir_sign": np.ones(4, np.int64), "notl": np.full(4, 300.0),
        "gross_bp": np.full(4, 10.0), "entry_supported": np.ones(4, bool),
        "common_outcome_support": np.array([False, True, True, True]),
    }
    signals = {
        "wallet": np.array(["w", "other"]), "coin": np.array(["BTC", "BTC"]),
        "ts": np.array([0, -1]), "dir_sign": np.ones(2, np.int64),
        "notl": np.array([300.0, 100.0]), "is_ambiguous": np.zeros(2, bool),
        "passes_cutoff": np.ones(2, bool),
    }
    a, fa = _arm_fold(base, signals, ["w", "other"], 202511, {}, False)
    changed = {k: v.copy() for k, v in base.items()}
    changed["common_outcome_support"][:] = True
    b, fb = _arm_fold(changed, signals, ["w", "other"], 202511, {}, False)
    assert a["signal_ts"].tolist() == b["signal_ts"].tolist() == [0, HOLD_MS + STALE_MS]
    assert a["smart"].tolist() == b["smart"].tolist()
    assert fa["n_accepted_capacity"] == fb["n_accepted_capacity"] == 2
    assert fa["n_common_support_excluded_after_accept"] == 1


def test_lineage_fails_on_missing_day_and_changes_with_derived_etag(monkeypatch):
    expected = lake.expected_iso_days([202511])
    state = {"etag": "a"}
    monkeypatch.setattr(lake, "_derived_head", lambda dataset, day: {
        "key": f"{dataset}/{day}", "etag": state["etag"], "size": 1})

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Con:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, *_args):
            return Result(self.rows)

    rows = [(d.replace("-", ""), "ok", "src", 1, 2, "commit", "now") for d in expected]
    a = lake.validated_lineage(Con(rows), [202511], ("d",))["sha256"]
    state["etag"] = "b"
    b = lake.validated_lineage(Con(rows), [202511], ("d",))["sha256"]
    assert a != b
    with pytest.raises(RuntimeError):
        lake.validated_lineage(Con(rows[:-1]), [202511], ("d",))


def test_production_selector_cache_spec_changes_with_lineage(monkeypatch):
    state = {"sha256": "a"}
    monkeypatch.setattr(lake, "validated_lineage", lambda *_args: {
        "sha256": state["sha256"], "objects": [], "months": [202508, 202509, 202510]})
    a = _cache_spec(object(), 202511, profile=HL21_PROFILE)
    state["sha256"] = "b"
    b = _cache_spec(object(), 202511, profile=HL21_PROFILE)
    assert _sha256_json(a) != _sha256_json(b)


def test_selector_cache_spec_is_bound_to_frozen_half_life_profile(monkeypatch):
    monkeypatch.setattr(lake, "validated_lineage", lambda *_args: {
        "sha256": "same", "objects": [], "months": [202508, 202509, 202510]})
    a = _cache_spec(object(), 202511, profile=HL21_PROFILE)
    b = _cache_spec(object(), 202511, profile=HL60_PROFILE)
    assert a["experiment_id"] == "hl21"
    assert b["experiment_id"] == "hl60"
    assert b["half_life_days"] == 60.0
    assert _sha256_json(a) != _sha256_json(b)


def _inference_book(edge: float, seed: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    wallets = np.array([f"w{i:02d}" for i in range(20)])
    block = np.arange(20)
    w = np.repeat(wallets, block.size)
    b = np.tile(block, wallets.size)
    ts = (20_000 + b * 7) * DAY_MS
    wallet_effect = np.repeat(rng.normal(0, 8, wallets.size), block.size)
    time_effect = np.tile(rng.normal(0, 8, block.size), wallets.size)
    net = wallet_effect + time_effect + rng.normal(0, 20, w.size) + edge
    return {"wallet": w, "coin": np.array(["BTC"] * w.size), "signal_ts": ts,
            "net_bp": net, "fold": np.full(w.size, 202511)}


def test_noisy_plus5_end_to_end_power_zero_edge_and_sparse_gates():
    base = _inference_book(0, 1)
    plus = {k: v.copy() for k, v in base.items()}
    rng = np.random.default_rng(3)
    arm_wallet = np.repeat(rng.normal(0, 1.5, 20), 20)
    arm_time = np.tile(rng.normal(0, 1.5, 20), 20)
    plus["net_bp"] = base["net_bp"] + 5 + arm_wallet + arm_time + rng.normal(0, 5, 400)
    got = compare(plus, base, 4, 20_000, 20_000 + 19 * 7, n_boot=1_000)
    assert got["inference_status"] == "ESTIMABLE"
    assert got["delta_bp"] > 0
    assert got["plus5_control_pass"]
    assert got["crossed_ci95"][0] > 0
    assert got["crossed_mde80_bp"] <= 5
    assert got["crossed_p_two_sided"] < .05
    zero = compare(base, base, 6, 20_000, 20_000 + 19 * 7, n_boot=1_000)
    assert not (zero["crossed_ci95"][0] > 0)
    sparse = {k: v[:5] for k, v in base.items()}
    nope = compare(sparse, base, 7, 20_000, 20_000 + 19 * 7, n_boot=100)
    assert nope["inference_status"] == "SPARSE_NOT_ESTIMABLE"
    assert nope["crossed_ci95"] is None


def test_crossed_invalid_draws_fail_closed_without_retry_conditioning(monkeypatch):
    blocks = np.arange(10)
    a = {"wallet": np.array([f"a{i}" for i in blocks]),
         "coin": np.array(["BTC"] * 10),
         "signal_ts": (30_000 + blocks * 7) * DAY_MS,
         "net_bp": np.ones(10), "fold": np.full(10, 202511)}
    b = {"wallet": np.array([f"b{i}" for i in blocks]),
         "coin": np.array(["BTC"] * 10),
         "signal_ts": (30_000 + blocks * 7) * DAY_MS,
         "net_bp": np.zeros(10), "fold": np.full(10, 202511)}
    monkeypatch.setattr(dtb, "_resample_delta", lambda *_args, **_kwargs: (
        np.ones(98), .02))
    got = compare(a, b, 12, 30_000, 30_000 + 69, n_boot=100)
    assert got["inference_status"] == "SPARSE_NOT_ESTIMABLE"
    assert got["invalid_draw_fraction"]["crossed"] > .01


def test_missingness_rate_bounds_and_top_level_decision_gates():
    base = _inference_book(0, 21)
    plus = {k: v.copy() for k, v in base.items()}
    plus["net_bp"] = base["net_bp"] + 8

    def capacity(book):
        out = {k: v.copy() for k, v in book.items()}
        out["outcome_supported"] = np.ones(book["wallet"].size, bool)
        out["actual_outcome_available"] = np.ones(book["wallet"].size, bool)
        out["entry_context_available"] = np.ones(book["wallet"].size, bool)
        return out

    cap_a, cap_b = capacity(plus), capacity(base)
    result = compare(plus, base, 22, 20_000, 20_000 + 19 * 7, n_boot=400)
    add_missingness_sensitivity(
        result, cap_a, cap_b, plus, base, 23, 20_000, 20_000 + 19 * 7, n_boot=400)
    finalize_decision_flags(result, {})
    assert result["missingness"]["rate_gates_pass"]
    assert result["positive_promotion_eligible"]

    boundary_a, boundary_b = capacity(plus), capacity(base)
    boundary_a["outcome_supported"][:4] = False
    boundary_b["outcome_supported"][:4] = False
    at_boundary = compare(plus, base, 24, 20_000, 20_000 + 19 * 7, n_boot=200)
    add_missingness_sensitivity(
        at_boundary, boundary_a, boundary_b, plus, base, 25,
        20_000, 20_000 + 19 * 7, n_boot=200)
    assert at_boundary["missingness"]["rate_gates_pass"]

    failed_a, failed_b = capacity(plus), capacity(base)
    failed_a["outcome_supported"][:5] = False
    failed_b["outcome_supported"][:5] = False
    failed = compare(plus, base, 26, 20_000, 20_000 + 19 * 7, n_boot=200)
    add_missingness_sensitivity(
        failed, failed_a, failed_b, plus, base, 27,
        20_000, 20_000 + 19 * 7, n_boot=200)
    finalize_decision_flags(failed, {})
    assert not failed["missingness"]["rate_gates_pass"]
    assert failed["verdict_status"] == "MISSINGNESS_UNRESOLVED"
    assert not failed["positive_promotion_eligible"]

    bounded_a = capacity(plus)
    bounded_a["net_bp"][0] = np.nan
    bounded_a["actual_outcome_available"][0] = False
    actual_bounded = {k: v[1:] for k, v in plus.items()}
    bounded_result = compare(plus, base, 28, 20_000, 20_000 + 19 * 7, n_boot=200)
    add_missingness_sensitivity(
        bounded_result, bounded_a, cap_b, actual_bounded, base, 29,
        20_000, 20_000 + 19 * 7, n_boot=200)
    miss = bounded_result["missingness"]
    assert miss["adverse_lower_crossed_ci95"][0] < miss["favorable_upper_crossed_ci95"][0]


def test_formation_months_are_strictly_prior_and_cache_dependency_hash_mutates():
    assert formation_months(202601) == [202510, 202511, 202512]
    a = {"roster": ["a"], "ctx": "x", "code": "1"}
    assert _sha256_json(a) != _sha256_json({**a, "roster": ["b"]})
    assert _sha256_json(a) != _sha256_json({**a, "ctx": "y"})
