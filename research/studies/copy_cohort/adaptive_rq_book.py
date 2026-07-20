"""Conditional causal top-30 book for the powered adaptive R/Q diagnostic."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from . import lake
from .adaptive_rq_filter import (
    ARCH,
    ARMS,
    CONTRASTS,
    DERIVED,
    HALF_LIFE,
    PRIMARY,
    PROFILE_ID,
    SCORES,
    SECONDARIES,
)
from .adaptive_rq_filter import (
    OUT as FACTOR_OUT,
)
from .dynamic_t_book import (
    BLOCK_DAYS,
    COIN_CAP_USD,
    COST_BP,
    HOLD_MS,
    MISSING_RETURN_BOUND_BP,
    N_BOOT,
    NOTL_MIN,
    SEED,
    TOP_HALF,
    UNIT_USD,
    WALLET_CAP_USD,
    _arm_fold,
    _book_stats,
    _cache_fold,
    _concat,
    _day_epoch,
    _read,
    add_missingness_sensitivity,
    compare,
    finalize_decision_flags,
    holm_adjust,
    holm_adjust_null,
    shock_days,
)
from .dynamic_t_quality import FOLDS, StudyProfile, topk
from .filtered_quality import _code_sha256, _sha256_json

ROSTERS = DERIVED / "rosters.json"
ENTRIES = DERIVED / "entries"
OUT = DERIVED / "book_report.json"
PROFILE = StudyProfile(PROFILE_ID, HALF_LIFE, ARCH.name, DERIVED)
SHOCK_ARMS = {"KF60_BLOWUP", "KF60_ALL"}


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_factor_gate(report: dict[str, object]) -> None:
    """Fail closed unless this exact frozen factor run authorized the book."""
    expected = {
        "profile_id": PROFILE_ID,
        "architecture": ARCH.name,
        "architecture_sha256": _file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__).with_name("adaptive_rq_filter.py")),
        "conditional_book_action": "RUN_DIRECTION_INDEPENDENT",
        "primary_resolution_capable": True,
    }
    got = {key: report.get(key) for key in expected}
    if got != expected:
        raise RuntimeError(f"factor power/lineage gate failed: got={got}, expected={expected}")
    cfg = report.get("config", {})
    expected_config = {
        "arms": list(ARMS),
        "contrasts": {key: list(value) for key, value in CONTRASTS.items()},
        "profile_id": PROFILE_ID,
        "primary": PRIMARY,
        "n_boot": N_BOOT,
        "care_bp_day": 5.0,
        "min_active_base": 200,
        "min_formation_pool": 30,
        "min_arm_coin": 30,
        "min_fold_coverage": 0.90,
    }
    got_config = {key: cfg.get(key) for key in expected_config}
    if got_config != expected_config:
        raise RuntimeError(
            f"factor frozen config mismatch: got={got_config}, expected={expected_config}"
        )
    primary = report.get("results", {}).get(PRIMARY, {})
    if not primary.get("resolution_capable"):
        raise RuntimeError("nested factor primary does not authorize conditional book")
    score_hashes = report.get("score_files_sha256")
    if set(score_hashes or {}) != {str(fold) for fold in FOLDS}:
        raise RuntimeError("factor report lacks the complete per-fold score hash registry")


def roster_from_score(path: Path, arm: str) -> list[str]:
    table = pq.read_table(
        path, columns=["wallet", f"score__{arm}", f"eligible__{arm}"]
    ).to_pydict()
    wallets = np.asarray(table["wallet"], str)
    score = np.asarray(table[f"score__{arm}"], float)
    eligible = np.asarray(table[f"eligible__{arm}"], bool)
    masked = np.where(eligible, score, np.nan)
    return topk(wallets, masked)


def materialize_rosters(
    factor_sha256: str, authorized_score_hashes: dict[str, str]
) -> tuple[dict[str, object], dict[str, str]]:
    score_hashes: dict[str, str] = {}
    folds: dict[str, object] = {}
    for fold in FOLDS:
        path = SCORES / f"scores_{fold}.parquet"
        if not path.exists():
            raise RuntimeError(f"missing frozen score artifact: {path}")
        score_hashes[str(fold)] = _file_sha256(path)
        if score_hashes[str(fold)] != authorized_score_hashes.get(str(fold)):
            raise RuntimeError(f"fold {fold}: score artifact is not bound to factor report")
        rosters = {arm: roster_from_score(path, arm) for arm in ARMS}
        if any(len(v) != 30 or len(set(v)) != 30 for v in rosters.values()):
            raise RuntimeError(f"fold {fold}: exact unique top-30 invariant failed")
        folds[str(fold)] = {
            "score_path": str(path),
            "score_sha256": score_hashes[str(fold)],
            "rosters": rosters,
        }
    payload: dict[str, object] = {
        "status": "BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC",
        "architecture": ARCH.name,
        "architecture_sha256": _file_sha256(ARCH),
        "config": {
            "experiment_id": PROFILE_ID,
            "half_life_days": HALF_LIFE,
            "arms": list(ARMS),
            "top_k": 30,
            "ranking": "score descending; wallet ascending deterministic tie-break",
        },
        "factor_report_sha256": factor_sha256,
        "folds": folds,
    }
    tmp = ROSTERS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True))
    tmp.replace(ROSTERS)
    return payload, score_hashes


def _verify_sources(factor_sha: str, score_hashes: dict[str, str]) -> None:
    if _file_sha256(FACTOR_OUT) != factor_sha:
        raise RuntimeError("factor report mutated during book materialization")
    for fold, expected in score_hashes.items():
        if _file_sha256(SCORES / f"scores_{fold}.parquet") != expected:
            raise RuntimeError(f"score artifact {fold} mutated during book materialization")


def add_contrast_concentration(
    result: dict[str, object], a: dict[str, np.ndarray], b: dict[str, np.ndarray]
) -> None:
    """Report wallet concentration in the contrast, rather than in either arm."""
    contributions: dict[str, float] = {}
    for book, sign in ((a, 1.0), (b, -1.0)):
        n = int(book["net_bp"].size)
        if n == 0:
            result["contrast_concentration"] = {
                "n_contributing_wallets": 0,
                "top5_wallet_abs_contribution_share": None,
            }
            return
        for wallet in np.unique(book["wallet"]):
            value = float(np.sum(book["net_bp"][book["wallet"] == wallet]))
            key = str(wallet)
            contributions[key] = contributions.get(key, 0.0) + sign * value / n
    values = np.asarray(list(contributions.values()), float)
    if not np.isclose(float(values.sum()), float(result["delta_bp"]), atol=1e-10):
        raise RuntimeError("wallet contrast contributions do not sum to point estimate")
    absolute = np.abs(values)
    denom = float(absolute.sum())
    result["contrast_concentration"] = {
        "n_contributing_wallets": len(contributions),
        "top5_wallet_abs_contribution_share": (
            float(np.sort(absolute)[-5:].sum() / denom) if denom > 0 else None
        ),
    }


def run(*, n_boot: int = N_BOOT) -> dict[str, object]:
    if n_boot != N_BOOT:
        raise RuntimeError(f"frozen adaptive book requires n_boot={N_BOOT}")
    factor_bytes = FACTOR_OUT.read_bytes()
    factor_sha = hashlib.sha256(factor_bytes).hexdigest()
    report = json.loads(factor_bytes)
    validate_factor_gate(report)
    rosters, score_hashes = materialize_rosters(
        factor_sha, report["score_files_sha256"]
    )

    con = lake.connect()
    parts = {arm: [] for arm in ARMS}
    funnels: dict[str, dict[str, object]] = {arm: {} for arm in ARMS}
    cache_hashes: dict[str, str] = {}
    fold_cutoffs: dict[str, int] = {}
    for fold in FOLDS:
        fold_rosters = rosters["folds"][str(fold)]["rosters"]
        union = sorted({wallet for arm in ARMS for wallet in fold_rosters[arm]})
        print(f"[adaptive-rq book] fold {fold}: {len(union)} union wallets", flush=True)
        ep, sp, qp = _cache_fold(
            con, fold, union, entries_dir=ENTRIES, profile=PROFILE
        )
        meta_path = ENTRIES / f"cache_{fold}.meta.json"
        meta = json.loads(meta_path.read_text())
        cache_hashes[str(fold)] = _sha256_json(meta)
        fold_cutoffs[str(fold)] = int(meta["common_signal_cutoff_ms"])
        entries, signals, shocks = _read(ep), _read(sp), _read(qp)
        online = shock_days(shocks)
        for arm in ARMS:
            arm_part, funnel = _arm_fold(
                entries,
                signals,
                fold_rosters[arm],
                fold,
                online,
                arm in SHOCK_ARMS,
            )
            parts[arm].append(arm_part)
            funnels[arm][str(fold)] = funnel
            print(f"  {arm}: accepted={funnel['n_accepted']}", flush=True)
    con.close()
    _verify_sources(factor_sha, score_hashes)

    capacity = {arm: _concat(parts[arm], kind="capacity") for arm in ARMS}
    actual = {arm: _concat(parts[arm], kind="actual") for arm in ARMS}
    books = {arm: _concat(parts[arm], kind="supported") for arm in ARMS}
    calendar_lo = _day_epoch(20251101)
    calendar_hi = fold_cutoffs["202606"] // 86_400_000

    code_paths = (
        Path(__file__),
        Path(__file__).with_name("adaptive_rq_filter.py"),
        Path(__file__).with_name("dynamic_t_book.py"),
        Path(__file__).with_name("dynamic_t_quality.py"),
        Path(__file__).with_name("alt_fresh_validate.py"),
        Path(__file__).with_name("filtered_quality.py"),
    )
    result: dict[str, object] = {
        "status": "BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC",
        "verdict_eligible": False,
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "factor_gate": {
            "primary_resolution_capable": True,
            "conditional_book_action": "RUN_DIRECTION_INDEPENDENT",
            "factor_report_sha256": factor_sha,
        },
        "config": {
            "profile_id": PROFILE_ID,
            "architecture": ARCH.name,
            "architecture_sha256": _file_sha256(ARCH),
            "arms": list(ARMS),
            "contrasts": {key: list(value) for key, value in CONTRASTS.items()},
            "unit_usd": UNIT_USD,
            "wallet_cap_usd": WALLET_CAP_USD,
            "coin_cap_usd": COIN_CAP_USD,
            "notional_min": NOTL_MIN,
            "hold_h": HOLD_MS / 3_600_000,
            "cost_bp": COST_BP,
            "n_boot": n_boot,
            "block_days": BLOCK_DAYS,
            "seed": SEED,
            "top_half_unused": TOP_HALF,
            "consensus_overlay": "excluded",
            "evaluation_calendar_epoch_days": [calendar_lo, calendar_hi],
            "fold_common_cutoffs_ms": fold_cutoffs,
            "code_commit": lake.git_describe(),
            "code_sha256": _code_sha256(*code_paths),
            "rosters_sha256": _file_sha256(ROSTERS),
            "score_sha256": score_hashes,
            "fold_cache_spec_sha256": cache_hashes,
            "missing_return_bound_bp": MISSING_RETURN_BOUND_BP,
        },
        "funnels": funnels,
        "books": {},
        "primary": {},
        "secondary": {},
    }
    for index, arm in enumerate(ARMS):
        result["books"][arm] = _book_stats(
            books[arm], SEED + 100 + index, calendar_lo, calendar_hi
        )
        print(
            f"{arm}: n={books[arm]['net_bp'].size:,} "
            f"net={result['books'][arm].get('net_bp_per_entry', float('nan')):+.2f}bp",
            flush=True,
        )

    arm_a, arm_b = CONTRASTS[PRIMARY]
    primary = compare(
        books[arm_a], books[arm_b], SEED, calendar_lo, calendar_hi, n_boot
    )
    add_contrast_concentration(primary, books[arm_a], books[arm_b])
    add_missingness_sensitivity(
        primary,
        capacity[arm_a],
        capacity[arm_b],
        actual[arm_a],
        actual[arm_b],
        SEED + 1_000,
        calendar_lo,
        calendar_hi,
        n_boot,
    )
    secondary: dict[str, dict[str, object]] = {}
    for index, (name, (left, right)) in enumerate(SECONDARIES.items()):
        comparison = compare(
            books[left],
            books[right],
            SEED + 10 + 10 * index,
            calendar_lo,
            calendar_hi,
            n_boot,
        )
        add_contrast_concentration(comparison, books[left], books[right])
        add_missingness_sensitivity(
            comparison,
            capacity[left],
            capacity[right],
            actual[left],
            actual[right],
            SEED + 2_000 + 10 * index,
            calendar_lo,
            calendar_hi,
            n_boot,
        )
        secondary[name] = comparison
    holm_adjust(secondary)
    holm_adjust_null(secondary)
    finalize_decision_flags(primary, secondary, formal_eligibility=False)
    for comparison in (primary, *secondary.values()):
        comparison["verdict_status"] = "BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC"
    result["primary"] = primary
    result["secondary"] = secondary
    _verify_sources(factor_sha, score_hashes)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=1, sort_keys=True))
    tmp.replace(OUT)
    print("PRIMARY:", primary, flush=True)
    print(f"-> {OUT}", flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(
        "Generic execution is disabled; use `python -m "
        "research.studies.copy_cohort.adaptive_rq_book_run`."
    )
