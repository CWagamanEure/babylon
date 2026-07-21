"""Burned diagnostic: reject WALLET_E30 entries with strict-prior notional CR > 50."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from research.data.markout import REPO_ROOT

from . import lake
from . import same_coin_direction_policy as sc
from . import wallet_coin_t30 as wc
from .dynamic_t_quality import formation_months
from .efron_bot500 import atomic_json, file_sha256
from .filtered_quality import _code_sha256, _sha256_json

ARCH = Path(__file__).with_name("NOTIONAL_CR50_FILTER_ARCH.md")
DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "notional_cr50_filter"
SCALES = DERIVED / "formation_scales.json"
SCALES_META = DERIVED / "formation_scales.meta.json"
OUT = DERIVED / "report.json"

BASELINE = sc.BASELINE
POLICY = "CR50"
ARMS = (BASELINE, POLICY)
CR_LIMIT = Decimal(50)
NOTIONAL_MIN = Decimal("250")
TOL = 1e-8


def dependency_hashes() -> dict[str, str]:
    paths = {
        "lake.py": Path(lake.__file__),
        "same_coin_direction_policy.py": Path(sc.__file__),
        "wallet_coin_t30.py": Path(wc.__file__),
        "dynamic_t_quality.py": Path(__file__).with_name("dynamic_t_quality.py"),
    }
    return {name: file_sha256(path) for name, path in paths.items()}


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "size": path.stat().st_size, "sha256": file_sha256(path)}


def base_execution_seal() -> dict[str, object]:
    return {
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "dependency_hashes": dependency_hashes(),
        "parent_inputs": sc.input_snapshot(),
    }


def execution_seal() -> dict[str, object]:
    return {
        **base_execution_seal(),
        "formation_scales": _record(SCALES),
        "formation_scales_meta": _record(SCALES_META),
    }


def _write_nonresult(status: str, error: str | None = None) -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "status": status,
        "comparative_results_present": False,
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
    }
    if error is not None:
        payload["error"] = error
    atomic_json(OUT, payload)


def canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def continuous_median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal(2)


def fold_start_ms(fold: int) -> int:
    text = str(fold)
    return int(np.datetime64(f"{text[:4]}-{text[4:]}-01T00:00:00", "ms").astype(np.int64))


def expected_roster_rows(rosters: dict[str, Any]) -> list[dict[str, object]]:
    rows = []
    for fold in wc.FOLDS:
        wallets = [str(w).lower() for w in rosters[str(fold)]]
        if len(wallets) != 30 or len(set(wallets)) != 30:
            raise RuntimeError(f"fold {fold}: expected exactly 30 unique WALLET_E30 wallets")
        months = formation_months(fold)
        for wallet in sorted(wallets):
            rows.append(
                {
                    "fold": int(fold),
                    "wallet": wallet,
                    "formation_months": months,
                    "formation_start_ms": fold_start_ms(months[0]),
                    "formation_end_ms": fold_start_ms(fold),
                }
            )
    if len(rows) != 30 * len(wc.FOLDS):
        raise RuntimeError("formation-scale expected key count changed")
    return rows


def scale_spec(rosters: dict[str, Any], lineage: dict[str, object]) -> dict[str, object]:
    expected = expected_roster_rows(rosters)
    return {
        "schema": "wallet-e30-cr50-formation-scale-v1",
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "dependency_hashes": dependency_hashes(),
        "parent_roster_sha256": file_sha256(sc.PARENT_ROSTERS),
        "roster_keys_sha256": _sha256_json([[row["fold"], row["wallet"]] for row in expected]),
        "formation_months": {str(fold): formation_months(fold) for fold in wc.FOLDS},
        "source_lineage": lineage,
        "config": {
            "majors": list(wc.MAJORS),
            "wallet_normalization": "lowercase",
            "notional_floor_decimal": canonical_decimal(NOTIONAL_MIN),
            "source_notional_type": "DECIMAL(38,10)",
            "median": "continuous exact; even n arithmetic midpoint; <=11 decimal places",
            "duckdb_oracle_input_type": "DECIMAL(38,11)",
            "cr_limit_decimal": canonical_decimal(CR_LIMIT),
            "candidate_conversion": "Decimal(repr(float(promoted_notional)))",
            "comparison": "candidate_decimal <= 50 * typical_decimal",
            "undefined_scale": "pass_through",
        },
    }


def _register_roster(con, expected: list[dict[str, object]]) -> None:
    con.register(
        "cr_roster_src",
        {
            "fold": np.asarray([row["fold"] for row in expected], dtype=np.int64),
            "wallet": np.asarray([row["wallet"] for row in expected], dtype=str),
            "lo_ms": np.asarray([row["formation_start_ms"] for row in expected], dtype=np.int64),
            "hi_ms": np.asarray([row["formation_end_ms"] for row in expected], dtype=np.int64),
        },
    )
    con.execute(
        "CREATE OR REPLACE TEMP TABLE cr_roster AS "
        "SELECT fold, lower(wallet) wallet, lo_ms, hi_ms FROM cr_roster_src"
    )
    con.unregister("cr_roster_src")


def _source_globs() -> list[str]:
    months = sorted({month for fold in wc.FOLDS for month in formation_months(fold)})
    return [lake.ope_month_glob(month) for month in months]


def _python_oracle(con, expected: list[dict[str, object]]) -> list[dict[str, object]]:
    _register_roster(con, expected)
    globs = ",".join(f"'{value}'" for value in _source_globs())
    majors = ",".join(f"'{coin}'" for coin in wc.MAJORS)
    rows = con.execute(f"""
      SELECT r.fold,r.wallet,CAST(CAST(o.notl AS DECIMAL(38,10)) AS VARCHAR) AS notional
      FROM read_parquet([{globs}]) o
      JOIN cr_roster r ON lower(o.wallet)=r.wallet AND o.ts>=r.lo_ms AND o.ts<r.hi_ms
      WHERE o.coin IN ({majors})
        AND CAST(o.notl AS DECIMAL(38,10))>=CAST('{NOTIONAL_MIN}' AS DECIMAL(38,10))
      ORDER BY r.fold,r.wallet,CAST(o.notl AS DECIMAL(38,10)),o.ts
    """).fetchall()
    grouped: dict[tuple[int, str], list[Decimal]] = defaultdict(list)
    for fold, wallet, notional in rows:
        grouped[(int(fold), str(wallet).lower())].append(Decimal(str(notional)))
    output = []
    for row in expected:
        key = (int(row["fold"]), str(row["wallet"]))
        values = grouped.get(key, [])
        median = continuous_median(values)
        output.append(
            {
                **row,
                "n_formation": len(values),
                "typical_decimal": None if median is None else canonical_decimal(median),
            }
        )
    return output


def _duckdb_oracle(con, expected: list[dict[str, object]]) -> list[dict[str, object]]:
    _register_roster(con, expected)
    globs = ",".join(f"'{value}'" for value in _source_globs())
    majors = ",".join(f"'{coin}'" for coin in wc.MAJORS)
    rows = con.execute(f"""
      WITH matched AS (
        SELECT r.fold,r.wallet,CAST(o.notl AS DECIMAL(38,10)) AS notional
        FROM read_parquet([{globs}]) o
        JOIN cr_roster r ON lower(o.wallet)=r.wallet AND o.ts>=r.lo_ms AND o.ts<r.hi_ms
        WHERE o.coin IN ({majors})
          AND CAST(o.notl AS DECIMAL(38,10))>=CAST('{NOTIONAL_MIN}' AS DECIMAL(38,10))
      )
      SELECT fold,wallet,count(*) AS n_formation,
        CAST(median(CAST(notional AS DECIMAL(38,11))) AS VARCHAR) AS typical_decimal
      FROM matched GROUP BY fold,wallet ORDER BY fold,wallet
    """).fetchall()
    by_key = {
        (int(fold), str(wallet).lower()): (int(count), canonical_decimal(Decimal(str(median))))
        for fold, wallet, count, median in rows
    }
    output = []
    for row in expected:
        count, median = by_key.get((int(row["fold"]), str(row["wallet"])), (0, None))
        output.append({**row, "n_formation": count, "typical_decimal": median})
    return output


def validate_scale_rows(rows: list[dict[str, object]], expected: list[dict[str, object]]) -> None:
    expected_keys = [(int(row["fold"]), str(row["wallet"])) for row in expected]
    got_keys = [(int(row["fold"]), str(row["wallet"])) for row in rows]
    if len(rows) != 240 or len(set(got_keys)) != 240 or got_keys != expected_keys:
        raise RuntimeError("formation-scale cache has missing, extra, duplicate, or unordered keys")
    for row in rows:
        if int(row["n_formation"]) < 0:
            raise RuntimeError("negative formation count")
        typical = row["typical_decimal"]
        if int(row["n_formation"]) == 0 and typical is not None:
            raise RuntimeError("zero-history row has a typical notional")
        if int(row["n_formation"]) > 0 and (typical is None or Decimal(str(typical)) <= 0):
            raise RuntimeError("positive-history row lacks a positive typical notional")


def recompute_scale_oracles(
    con, rosters: dict[str, Any]
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    expected = expected_roster_rows(rosters)
    months = sorted({month for fold in wc.FOLDS for month in formation_months(fold)})
    pre = lake.validated_lineage(con, months, ("alt_universe_open_entries",))
    python_rows = _python_oracle(con, expected)
    duckdb_rows = _duckdb_oracle(con, expected)
    post = lake.validated_lineage(con, months, ("alt_universe_open_entries",))
    if pre != post:
        raise RuntimeError("formation source lineage mutated between independent oracle queries")
    validate_scale_rows(python_rows, expected)
    validate_scale_rows(duckdb_rows, expected)
    if python_rows != duckdb_rows:
        raise RuntimeError("Python and DuckDB formation median/count oracles disagree")
    return (
        python_rows,
        pre,
        {
            "python_ordered_rows_sha256": _sha256_json(python_rows),
            "duckdb_ordered_rows_sha256": _sha256_json(duckdb_rows),
            "exact_parity": True,
        },
    )


def build_and_validate_scale_cache(con, rosters: dict[str, Any]) -> dict[str, object]:
    DERIVED.mkdir(parents=True, exist_ok=True)
    rows, lineage, oracle = recompute_scale_oracles(con, rosters)
    spec = scale_spec(rosters, lineage)
    payload = {
        "status": "CR50_FORMATION_SCALES_EXACT",
        "spec": spec,
        "rows": rows,
        "ordered_rows_sha256": _sha256_json(rows),
        "oracle": oracle,
    }
    atomic_json(SCALES, payload)
    atomic_json(
        SCALES_META,
        {
            "schema": "cr50-formation-scale-meta-v1",
            "cache": _record(SCALES),
            "spec_sha256": _sha256_json(spec),
            "ordered_rows_sha256": payload["ordered_rows_sha256"],
        },
    )
    validate_scale_cache_bytes(rosters, rows, lineage)
    return payload


def validate_scale_cache_bytes(
    rosters: dict[str, Any], oracle_rows: list[dict[str, object]], lineage: dict[str, object]
) -> None:
    payload = json.loads(SCALES.read_text())
    meta = json.loads(SCALES_META.read_text())
    expected = expected_roster_rows(rosters)
    validate_scale_rows(payload.get("rows", []), expected)
    if payload.get("status") != "CR50_FORMATION_SCALES_EXACT":
        raise RuntimeError("formation-scale cache status changed")
    if payload.get("spec") != scale_spec(rosters, lineage):
        raise RuntimeError("formation-scale cache spec changed")
    if payload.get("rows") != oracle_rows:
        raise RuntimeError("formation-scale cache rows differ from live oracle")
    if payload.get("ordered_rows_sha256") != _sha256_json(oracle_rows):
        raise RuntimeError("formation-scale ordered-row hash changed")
    if meta.get("cache") != _record(SCALES):
        raise RuntimeError("formation-scale metadata does not bind cache bytes")
    if meta.get("spec_sha256") != _sha256_json(payload["spec"]):
        raise RuntimeError("formation-scale metadata spec hash changed")
    if meta.get("ordered_rows_sha256") != payload["ordered_rows_sha256"]:
        raise RuntimeError("formation-scale metadata row hash changed")


def attach_cr(
    candidates: dict[str, np.ndarray], scale_rows: list[dict[str, object]]
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    scales = {(int(row["fold"]), str(row["wallet"])): row["typical_decimal"] for row in scale_rows}
    n = candidates["ts"].size
    typical = np.empty(n, dtype=object)
    cr = np.full(n, np.nan, dtype=float)
    has_scale = np.zeros(n, dtype=bool)
    keep = np.ones(n, dtype=bool)
    for i in range(n):
        key = (int(candidates["fold"][i]), str(candidates["wallet"][i]).lower())
        if key not in scales:
            raise RuntimeError(f"candidate has no expected scale-cache key: {key}")
        value = scales[key]
        typical[i] = value
        if value is None:
            continue
        med = Decimal(str(value))
        if med <= 0:
            continue
        candidate = Decimal(repr(float(candidates["notional"][i])))
        has_scale[i] = True
        cr[i] = float(candidate / med)
        keep[i] = candidate <= CR_LIMIT * med
    out = {k: v.copy() for k, v in candidates.items()}
    out["typical_decimal"] = typical
    out["cr"] = cr
    out["has_scale"] = has_scale
    out["cr50_keep"] = keep
    return out, keep


def _ids(rows: dict[str, np.ndarray]) -> list[str]:
    return [str(value) for value in rows["source_id"]]


def filtered_replay(
    annotated: dict[str, np.ndarray], keep: np.ndarray
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, int]]]:
    filtered = {k: v[keep] for k, v in annotated.items()}
    return sc.replay(filtered, one_side=False)


def replay_and_shadow_checks(
    parent: dict[str, Any],
    rosters: dict[str, Any],
    candidates: dict[str, np.ndarray],
    scale_rows: list[dict[str, object]],
) -> tuple[
    dict[str, dict[str, np.ndarray]], dict[str, object], dict[str, object], dict[str, np.ndarray]
]:
    baseline_arms, baseline_funnels, parent_checks = sc.baseline_and_shadow_checks(
        candidates, rosters, parent
    )
    baseline = baseline_arms[BASELINE]
    annotated, keep = attach_cr(candidates, scale_rows)
    policy, policy_funnel = filtered_replay(annotated, keep)
    rejected = {k: v[~keep] for k, v in annotated.items()}
    shadows = {}
    for name, outcomes in (
        ("all_nan", np.full(candidates["gross_bp"].shape, np.nan)),
        ("deterministic_noise", np.cos(np.arange(candidates["gross_bp"].size)) * 1e6),
    ):
        changed = {k: v.copy() for k, v in candidates.items()}
        changed["gross_bp"] = outcomes
        shadow_annotated, shadow_keep = attach_cr(changed, scale_rows)
        shadow_policy, shadow_funnel = filtered_replay(shadow_annotated, shadow_keep)
        if not np.array_equal(shadow_annotated["has_scale"], annotated["has_scale"]):
            raise RuntimeError(f"{name}: scale availability depends on outcomes")
        if not np.array_equal(shadow_annotated["typical_decimal"], annotated["typical_decimal"]):
            raise RuntimeError(f"{name}: typical notional depends on outcomes")
        if not np.array_equal(shadow_annotated["cr"], annotated["cr"], equal_nan=True):
            raise RuntimeError(f"{name}: CR values depend on outcomes")
        if not np.array_equal(shadow_keep, keep):
            raise RuntimeError(f"{name}: CR decisions depend on outcomes")
        if _ids(shadow_policy) != _ids(policy) or shadow_funnel != policy_funnel:
            raise RuntimeError(f"{name}: CR50 capacity acceptance depends on outcomes")
        shadows[name] = {
            "cr_sha256": _sha256_json(
                [
                    None if not np.isfinite(value) else float(value)
                    for value in shadow_annotated["cr"]
                ]
            ),
            "typical_decimal_sha256": _sha256_json(shadow_annotated["typical_decimal"].tolist()),
            "keep_mask_sha256": _sha256_json(shadow_keep.tolist()),
            "rejected_ids_sha256": _sha256_json(
                _ids({k: v[~shadow_keep] for k, v in shadow_annotated.items()})
            ),
            "accepted_ids_sha256": _sha256_json(_ids(shadow_policy)),
            "funnel_sha256": _sha256_json(shadow_funnel),
            "pass": True,
        }
    checks = {
        **{key: value for key, value in parent_checks.items() if key != "shadows"},
        "baseline_shadows": parent_checks["shadows"],
        "cr_values_outcome_blind": True,
        "filter_decisions_outcome_blind": True,
        "cr50_shadows": shadows,
    }
    return (
        {BASELINE: baseline, POLICY: policy},
        {BASELINE: baseline_funnels[BASELINE], POLICY: policy_funnel},
        checks,
        {"annotated": annotated, "keep": keep, "rejected": rejected},
    )


def _count(values: np.ndarray) -> dict[str, int]:
    return {str(value): int(np.sum(values == value)) for value in np.unique(values)}


def filter_diagnostics(bundle: dict[str, np.ndarray]) -> dict[str, object]:
    annotated = bundle["annotated"]
    keep = bundle["keep"]
    rejected = bundle["rejected"]
    finite = annotated["has_scale"]
    cr = annotated["cr"][finite]
    quantiles = [0, 0.5, 0.9, 0.95, 0.99, 1.0]
    return {
        "n_candidates": int(keep.size),
        "n_with_scale": int(finite.sum()),
        "n_scale_passthrough": int((~finite).sum()),
        "scale_coverage": float(finite.mean()),
        "n_kept": int(keep.sum()),
        "n_rejected": int((~keep).sum()),
        "rejected_rate": float((~keep).mean()),
        "cr_quantiles": {str(q): float(np.quantile(cr, q)) if cr.size else None for q in quantiles},
        "max_kept_cr": float(np.nanmax(annotated["cr"][keep])) if np.any(finite & keep) else None,
        "min_rejected_cr": float(np.nanmin(rejected["cr"])) if rejected["cr"].size else None,
        "by_fold": _count(rejected["fold"]),
        "by_coin": _count(rejected["coin"]),
        "by_direction": _count(rejected["dir_sign"]),
        "by_wallet": _count(rejected["wallet"]),
        "rejected_source_ids_sha256": _sha256_json(_ids(rejected)),
        "keep_mask_sha256": _sha256_json(keep.tolist()),
        "annotated_cr_sha256": _sha256_json(
            [None if not np.isfinite(value) else float(value) for value in annotated["cr"]]
        ),
    }


def wallet_concentration(
    policy: dict[str, np.ndarray], baseline: dict[str, np.ndarray], primary_delta: float
) -> dict[str, object]:
    wallets = sorted(set(policy["wallet"].astype(str)) | set(baseline["wallet"].astype(str)))

    def dollars(cap: dict[str, np.ndarray], wallet: str) -> float:
        mask = cap["supported"] & (cap["wallet"] == wallet)
        return float(cap["net_bp"][mask].sum() * wc.UNIT_USD / 1e4)

    contributions = [
        {"wallet": wallet, "net_usd_delta": dollars(policy, wallet) - dollars(baseline, wallet)}
        for wallet in wallets
    ]
    if not math.isclose(
        sum(row["net_usd_delta"] for row in contributions), primary_delta, abs_tol=TOL
    ):
        raise RuntimeError("wallet contributions do not sum to primary dollar delta")
    ranked = sorted(contributions, key=lambda row: (-abs(row["net_usd_delta"]), row["wallet"]))
    denominator = sum(abs(row["net_usd_delta"]) for row in ranked)
    top5_share = (
        sum(abs(row["net_usd_delta"]) for row in ranked[:5]) / denominator if denominator else 0.0
    )
    leave = {}
    removed = 0.0
    for k, row in enumerate(ranked[:5], start=1):
        removed += row["net_usd_delta"]
        leave[str(k)] = primary_delta - removed
    return {
        "definition": "fixed-book additive; no capacity replay",
        "contributions": ranked,
        "sum_contributions_usd": sum(row["net_usd_delta"] for row in ranked),
        "absolute_contribution_denominator_usd": denominator,
        "top5_abs_share": top5_share,
        "adverse_breadth_gate_le_0_50": top5_share <= 0.50,
        "cumulative_leave_top_k_delta_usd": leave,
    }


def missing_gates(by_arm: dict[str, dict[str, object]]) -> dict[str, object]:
    rates = [by_arm[arm]["rate"] for arm in ARMS]
    if any(rate is None for rate in rates):
        return {
            "overall_rate_le_1pct": False,
            "every_fold_rate_le_2pct": False,
            "overall_arm_imbalance_le_0_5pp": False,
            "per_fold_arm_imbalances_diagnostic_only": True,
            "imbalances": {"overall": None, "per_fold": {}},
            "pass": False,
        }
    numeric_rates = [float(rate) for rate in rates]
    overall = all(rate <= 0.01 for rate in numeric_rates)
    fold_rates = True
    imbalances: dict[str, object] = {
        "overall": abs(numeric_rates[0] - numeric_rates[1]),
        "per_fold": {},
    }
    for fold in wc.FOLDS:
        fold_key = str(fold)
        arm_rates = [by_arm[arm]["per_fold"][fold_key]["rate"] for arm in ARMS]
        if any(rate is None for rate in arm_rates):
            fold_rates = False
            imbalances["per_fold"][fold_key] = None
            continue
        baseline_rate, policy_rate = (float(rate) for rate in arm_rates)
        fold_rates = fold_rates and baseline_rate <= 0.02 and policy_rate <= 0.02
        imbalances["per_fold"][fold_key] = abs(baseline_rate - policy_rate)
    imbalance = float(imbalances["overall"]) <= 0.005
    return {
        "overall_rate_le_1pct": overall,
        "every_fold_rate_le_2pct": fold_rates,
        "overall_arm_imbalance_le_0_5pp": imbalance,
        "per_fold_arm_imbalances_diagnostic_only": True,
        "imbalances": imbalances,
        "pass": bool(overall and fold_rates and imbalance),
    }


def missing_bounds(
    policy: dict[str, np.ndarray], baseline: dict[str, np.ndarray], observed_delta: np.ndarray
) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
    bounds, adverse, favorable = sc.missing_bounds(policy, baseline, observed_delta)
    stresses = bounds["absolute_arm_stress"]
    if set(stresses) != {sc.POLICY, sc.BASELINE}:
        raise RuntimeError("inherited missing-bound arm labels changed")
    bounds["absolute_arm_stress"] = {
        POLICY: stresses[sc.POLICY],
        BASELINE: stresses[sc.BASELINE],
    }
    return bounds, adverse, favorable


def classify_with_concentration(
    observed: dict[str, object],
    adverse: dict[str, object],
    favorable: dict[str, object],
    gates_pass: bool,
    concentration: dict[str, object],
) -> dict[str, object]:
    base = sc.classify(observed, adverse, favorable, gates_pass)
    if (
        base["narrow_policy_adverse_predicate"]
        and not concentration["adverse_breadth_gate_le_0_50"]
    ):
        base["narrow_policy_adverse_predicate"] = False
        base["claim"] = "UNRESOLVED"
    base["wallet_concentration_adverse_gate_pass"] = concentration["adverse_breadth_gate_le_0_50"]
    base["concentration_diagnostic_only_for_equivalence"] = True
    return base


def construction_report(
    candidates: dict[str, np.ndarray],
    capacities: dict[str, dict[str, np.ndarray]],
    funnels: dict[str, object],
    checks: dict[str, object],
    filter_info: dict[str, object],
) -> dict[str, object]:
    result = {
        "both_arms_replayed_from_empty_state": True,
        "filter_before_capacity": True,
        "opposite_direction_sleeves_allowed": True,
        "parent_checks": checks,
        "candidate_ordered_sha256": wc._ordered_rows_sha(candidates, "gross_bp"),
        "candidate_multiset_sha256": wc._rows_sha(candidates, "gross_bp"),
        "filter": filter_info,
        "arms": {},
    }
    for arm in ARMS:
        cap = capacities[arm]
        result["arms"][arm] = {
            "accepted_ordered_sha256": wc._ordered_rows_sha(cap, "gross_bp"),
            "accepted_multiset_sha256": wc._rows_sha(cap, "gross_bp"),
            "supported_ordered_sha256": wc._ordered_rows_sha(wc.supported(cap), "net_bp"),
            "supported_multiset_sha256": wc._rows_sha(wc.supported(cap), "net_bp"),
            "funnel_sha256": _sha256_json(funnels[arm]),
        }
    return result


def run() -> dict[str, object]:
    _write_nonresult("CR50_FILTER_PENDING_NO_RESULTS")
    con = None
    try:
        initial_base_seal = base_execution_seal()
        parent, rosters, candidates = sc.load_frozen_inputs()
        sc.validate_candidates(candidates)
        con = lake.connect(mem="4GB", threads=2)
        scale_payload = build_and_validate_scale_cache(con, rosters)
        initial_seal = execution_seal()
        if base_execution_seal() != initial_base_seal:
            raise RuntimeError("execution base seal changed during formation-cache build")

        capacities, funnels, replay_checks, filter_bundle = replay_and_shadow_checks(
            parent, rosters, candidates, scale_payload["rows"]
        )
        filter_info = filter_diagnostics(filter_bundle)
        dailies = {arm: sc.daily_pnl(capacities[arm]) for arm in ARMS}
        exposures = {arm: sc.exposure_stats(capacities[arm]) for arm in ARMS}
        stats = {arm: sc.book_stats(capacities[arm], dailies[arm]) for arm in ARMS}
        for arm in ARMS:
            stats[arm]["exposure"] = exposures[arm]
            max_gross = exposures[arm]["maximum_gross_usd"]
            stats[arm]["max_drawdown_share_of_max_gross"] = (
                stats[arm]["max_drawdown_usd"] / max_gross if max_gross else None
            )
        headline_parity = sc.parent_headline_parity(stats[BASELINE], parent)
        construction = construction_report(
            candidates, capacities, funnels, replay_checks, filter_info
        )
        construction["parent_headline_arithmetic_parity"] = headline_parity

        delta = {
            "primary": "CR50 - VIRTUAL_SLEEVES total net USD",
            "net_usd": stats[POLICY]["net_usd"] - stats[BASELINE]["net_usd"],
            "net_mean_bp_per_trade": stats[POLICY]["net_mean_bp_per_trade"]
            - stats[BASELINE]["net_mean_bp_per_trade"],
            "net_median_bp_per_trade": stats[POLICY]["net_median_bp_per_trade"]
            - stats[BASELINE]["net_median_bp_per_trade"],
            "annualized_sharpe": stats[POLICY]["annualized_sharpe"]
            - stats[BASELINE]["annualized_sharpe"],
            "annualized_sortino": stats[POLICY]["annualized_sortino"]
            - stats[BASELINE]["annualized_sortino"],
            "accepted_trades": stats[POLICY]["accepted"] - stats[BASELINE]["accepted"],
            "supported_trades": stats[POLICY]["supported_trades"]
            - stats[BASELINE]["supported_trades"],
            "average_gross_usd": exposures[POLICY]["average_gross_usd"]
            - exposures[BASELINE]["average_gross_usd"],
            "average_absolute_net_usd": exposures[POLICY]["average_absolute_net_usd"]
            - exposures[BASELINE]["average_absolute_net_usd"],
        }
        concentration = wallet_concentration(
            capacities[POLICY], capacities[BASELINE], float(delta["net_usd"])
        )
        indices = sc.block_indices()
        observed_daily = dailies[POLICY] - dailies[BASELINE]
        missing_by_arm = {arm: sc.missingness(capacities[arm]) for arm in ARMS}
        missing_gates_result = missing_gates(missing_by_arm)
        missing_bounds_result, adverse_daily, favorable_daily = missing_bounds(
            capacities[POLICY], capacities[BASELINE], observed_daily
        )
        inference = {
            "observed": sc.inference(observed_daily, indices),
            "adverse_missingness": sc.inference(adverse_daily, indices),
            "favorable_missingness": sc.inference(favorable_daily, indices),
        }
        if not math.isclose(
            float(delta["net_usd"]), float(inference["observed"]["point_usd"]), abs_tol=TOL
        ):
            raise RuntimeError("headline dollar delta differs from paired daily point")
        construction_gates = bool(
            headline_parity["pass"]
            and replay_checks["parent_capacity_implementation_parity"]
            and replay_checks["parent_report_hash_parity"]
            and replay_checks["cr_values_outcome_blind"]
            and replay_checks["filter_decisions_outcome_blind"]
            and all(value["pass"] for value in replay_checks["baseline_shadows"].values())
            and all(value["pass"] for value in replay_checks["cr50_shadows"].values())
            and missing_gates_result["pass"]
        )
        decision = classify_with_concentration(
            inference["observed"],
            inference["adverse_missingness"],
            inference["favorable_missingness"],
            construction_gates,
            concentration,
        )

        # Mandatory live re-query after all outcome calculations; never trust cache bytes alone.
        final_rows, final_lineage, final_oracle = recompute_scale_oracles(con, rosters)
        validate_scale_cache_bytes(rosters, final_rows, final_lineage)
        if final_rows != scale_payload["rows"] or final_oracle != scale_payload["oracle"]:
            raise RuntimeError("formation-scale content oracle changed before publication")

        report: dict[str, object] = {
            "status": "BURNED_CR50_ENTRY_FILTER_DIAGNOSTIC",
            "comparative_results_present": True,
            "positive_promotion_eligible": False,
            "method_null_eligible": False,
            "final_label": (
                "burned CR<=50 entry-filter diagnostic; favorable point is unresolved descriptive "
                "residual, not established or deployable"
            ),
            "config": {
                "architecture_sha256": initial_seal["architecture_sha256"],
                "code_sha256": initial_seal["code_sha256"],
                "dependency_hashes": initial_seal["dependency_hashes"],
                "parent_inputs": initial_seal["parent_inputs"],
                "formation_scales": initial_seal["formation_scales"],
                "formation_scales_meta": initial_seal["formation_scales_meta"],
                "cr_limit": 50,
                "typical": "prior-three-full-month pooled-majors exact continuous median",
                "notional_min_usd": 250,
                "undefined_scale": "pass_through",
                "consensus": "excluded",
                "bot500_screen": "excluded",
                "same_coin_direction_policy": "excluded",
                "unit_usd": wc.UNIT_USD,
                "hold_hours": 8,
                "cost_bp": wc.COST_BP,
                "bootstrap": {
                    "numpy_rng": "default_rng PCG64",
                    "seed": sc.SEED,
                    "draws": sc.N_BOOT,
                    "noncircular_block_days": sc.BLOCK_DAYS,
                    "index_matrix_sha256": _sha256_json(indices.tolist()),
                },
            },
            "formation_scale_cache": {
                "status": scale_payload["status"],
                "spec": scale_payload["spec"],
                "ordered_rows_sha256": scale_payload["ordered_rows_sha256"],
                "oracle": scale_payload["oracle"],
                "n_rows": len(scale_payload["rows"]),
                "final_live_oracle": final_oracle,
            },
            "construction": construction,
            "funnels": funnels,
            "books": stats,
            "delta": delta,
            "wallet_concentration": concentration,
            "cross_unit_combination": sc.cross_unit(capacities[POLICY], capacities[BASELINE]),
            "missingness": {
                "by_arm": missing_by_arm,
                "gates": missing_gates_result,
                "coupled_bounds": missing_bounds_result,
            },
            "inference": inference,
            "decision": decision,
        }
        publication_months = sorted(
            {month for fold in wc.FOLDS for month in formation_months(fold)}
        )
        publication_lineage = lake.validated_lineage(
            con, publication_months, ("alt_universe_open_entries",)
        )
        if (
            publication_lineage != final_lineage
            or publication_lineage != scale_payload["spec"]["source_lineage"]
        ):
            raise RuntimeError("formation source lineage changed at publication boundary")
        report["formation_scale_cache"]["publication_boundary_lineage"] = publication_lineage
        if execution_seal() != initial_seal:
            raise RuntimeError(
                "execution code, architecture, dependency, input, or cache seal changed"
            )
        atomic_json(OUT, report)
        return report
    except Exception as exc:
        _write_nonresult("CR50_FILTER_FAILURE", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if con is not None:
            con.close()


if __name__ == "__main__":
    run()
