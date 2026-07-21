"""Burned diagnostic: virtual same-coin sleeves versus one-side-per-coin suppression."""

from __future__ import annotations

import heapq
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from research.data.markout import REPO_ROOT

from . import wallet_coin_t30 as wc
from .efron_bot500 import atomic_json, entry_data_record, file_sha256
from .filtered_quality import _code_sha256, _sha256_json

ARCH = Path(__file__).with_name("SAME_COIN_DIRECTION_POLICY_ARCH.md")
PARENT_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "wallet_coin_t30"
PARENT_REPORT = PARENT_DIR / "book_report.json"
PARENT_ROSTERS = PARENT_DIR / "rosters.json"
PARENT_ENTRIES = PARENT_DIR / "entries"
DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "same_coin_direction_policy"
OUT = DERIVED / "report.json"

BASELINE = "VIRTUAL_SLEEVES"
POLICY = "ONE_SIDE_PER_COIN"
ARMS = (BASELINE, POLICY)
DAY_MS = 86_400_000
START_DAY = int(np.datetime64("2025-11-01", "D").astype(int))
END_DAY = int(np.datetime64("2026-06-30", "D").astype(int))
N_DAYS = END_DAY - START_DAY + 1
START_MS = START_DAY * DAY_MS
END_EXCLUSIVE_MS = (END_DAY + 1) * DAY_MS
N_BOOT = 10_000
BLOCK_DAYS = 7
SEED = 20260722
MATERIAL_USD = 2_500.0
MISSING_BP = 2_000.0
TOL = 1e-12


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "size": path.stat().st_size, "sha256": file_sha256(path)}


def dependency_hashes() -> dict[str, str]:
    return {
        "wallet_coin_t30.py": file_sha256(Path(wc.__file__)),
        **{f"wallet_coin_t30::{k}": v for k, v in wc.dependency_hashes().items()},
    }


def execution_seal() -> dict[str, object]:
    return {
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "dependency_hashes": dependency_hashes(),
        "inputs": input_snapshot(),
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


def input_snapshot() -> dict[str, object]:
    parent = json.loads(PARENT_REPORT.read_text())
    rosters = json.loads(PARENT_ROSTERS.read_text())
    if parent.get("status") != "BURNED_REOPENED_WALLET_COIN_FORENSIC_BOOK":
        raise RuntimeError("parent report is not the frozen successful wallet-coin book")
    if not parent.get("comparative_results_present"):
        raise RuntimeError("parent report has no comparative results")
    if parent.get("positive_promotion_eligible") is not False:
        raise RuntimeError("parent positive-promotion governance changed")
    if parent.get("method_null_eligible") is not False:
        raise RuntimeError("parent method-null governance changed")
    if parent.get("config", {}).get("consensus") != "excluded":
        raise RuntimeError("parent consensus exclusion changed")
    governance = "burned reopened forensic; direction forced unresolved descriptive residual"
    if parent.get("config", {}).get("governance") != governance:
        raise RuntimeError("parent governance text changed")
    if rosters.get("status") != "BURNED_REOPENED_WALLET_COIN_FORENSIC_SELECTOR":
        raise RuntimeError("parent roster artifact is not frozen-successful")
    if rosters.get("positive_promotion_eligible") is not False:
        raise RuntimeError("parent roster positive-promotion governance changed")
    if rosters.get("method_null_eligible") is not False:
        raise RuntimeError("parent roster method-null governance changed")
    if parent["config"].get("roster_report_sha256") != file_sha256(PARENT_ROSTERS):
        raise RuntimeError("parent report does not bind current roster bytes")
    if parent["config"].get("code_sha256") != _code_sha256(Path(wc.__file__)):
        raise RuntimeError("parent wallet-coin runner code changed")
    if parent["config"].get("dependency_hashes") != wc.dependency_hashes():
        raise RuntimeError("parent wallet-coin dependencies changed")

    entries: dict[str, object] = {}
    for fold in wc.FOLDS:
        path = PARENT_ENTRIES / f"entries_{fold}.parquet"
        meta = path.with_suffix(".meta.json")
        expected = parent["config"]["entry_records"][str(fold)]
        current = {
            "parquet": entry_data_record(path),
            "meta_sha256": file_sha256(meta),
        }
        if current != expected:
            raise RuntimeError(f"fold {fold}: promoted entry artifact changed")
        entries[str(fold)] = {"parquet": _record(path), "meta": _record(meta)}
    return {
        "parent_report": _record(PARENT_REPORT),
        "parent_rosters": _record(PARENT_ROSTERS),
        "entries": entries,
        "parent_status": parent["status"],
        "parent_governance": {
            "positive_promotion_eligible": parent["positive_promotion_eligible"],
            "method_null_eligible": parent["method_null_eligible"],
            "consensus": parent["config"]["consensus"],
            "governance": parent["config"]["governance"],
            "roster_positive_promotion_eligible": rosters["positive_promotion_eligible"],
            "roster_method_null_eligible": rosters["method_null_eligible"],
        },
    }


def load_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray]]:
    parent = json.loads(PARENT_REPORT.read_text())
    roster_report = json.loads(PARENT_ROSTERS.read_text())
    parts = [wc.load_entries(PARENT_ENTRIES / f"entries_{fold}.parquet", fold) for fold in wc.FOLDS]
    entries = wc._concat(parts)
    rosters = {
        str(fold): roster_report["folds"][str(fold)]["rosters"]["WALLET_E30"] for fold in wc.FOLDS
    }
    candidates = wc.selected_entries(entries, rosters, "WALLET_E30")
    return parent, rosters, candidates


def validate_candidates(candidates: dict[str, np.ndarray]) -> dict[str, object]:
    n = int(candidates["ts"].size)
    if n == 0:
        raise RuntimeError("empty WALLET_E30 candidate stream")
    if np.unique(candidates["source_id"]).size != n:
        raise RuntimeError("candidate source_id is not unique")
    if not np.all(np.isin(candidates["dir_sign"], (-1.0, 1.0))):
        raise RuntimeError("candidate dir_sign is not exactly +/-1")
    order = np.lexsort(
        (
            candidates["source_id"],
            candidates["notional"],
            candidates["dir_sign"],
            candidates["coin"],
            candidates["wallet"],
            candidates["ts"],
        )
    )
    if not np.array_equal(order, np.arange(n)):
        raise RuntimeError("candidate stream violates canonical global order")

    pair_count = 0
    tie_groups = 0
    groups: dict[tuple[int, str], list[int]] = {}
    for t, c, d in zip(candidates["ts"], candidates["coin"], candidates["dir_sign"], strict=True):
        groups.setdefault((int(t), str(c)), []).append(int(d))
    for dirs_list in groups.values():
        dirs = np.asarray(dirs_list)
        pos, neg = int(np.sum(dirs == 1)), int(np.sum(dirs == -1))
        if pos and neg:
            tie_groups += 1
            pair_count += pos * neg
    return {
        "n_candidates": n,
        "unique_source_ids": True,
        "directions_binary": True,
        "canonical_order": True,
        "same_timestamp_coin_opposite_groups": tie_groups,
        "same_timestamp_coin_opposite_pairs": pair_count,
        "ordered_sha256": wc._ordered_rows_sha(candidates, "gross_bp"),
        "multiset_sha256": wc._rows_sha(candidates, "gross_bp"),
    }


def replay(
    candidates: dict[str, np.ndarray], *, one_side: bool
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, int]]]:
    """Replay an already selected canonical candidate stream from empty state."""
    if np.any(np.diff(candidates["ts"]) < 0):
        raise RuntimeError("candidate stream is not chronological")
    open_wc: set[tuple[str, str]] = set()
    coin_count: dict[str, int] = {}
    coin_dirs: dict[str, dict[int, int]] = {}
    exits: list[tuple[int, int, str, str, int]] = []
    accepted: list[int] = []
    funnels = {
        str(fold): {
            "n_candidates": 0,
            "n_accepted_capacity": 0,
            "n_skip_wallet_coin": 0,
            "n_skip_opposite_direction": 0,
            "n_skip_coin_cap": 0,
        }
        for fold in wc.FOLDS
    }
    for i in range(candidates["ts"].size):
        t = int(candidates["ts"][i])
        while exits and exits[0][0] <= t:
            _expiry, _seq, old_w, old_c, old_d = heapq.heappop(exits)
            if (old_w, old_c) not in open_wc:
                raise RuntimeError("expiry references a non-open wallet-coin sleeve")
            open_wc.remove((old_w, old_c))
            coin_count[old_c] -= 1
            coin_dirs[old_c][old_d] -= 1
            if coin_count[old_c] < 0 or coin_dirs[old_c][old_d] < 0:
                raise RuntimeError("negative open-state count")

        fold = str(int(candidates["fold"][i]))
        row = funnels[fold]
        row["n_candidates"] += 1
        w = str(candidates["wallet"][i])
        c = str(candidates["coin"][i])
        d = int(candidates["dir_sign"][i])
        if (w, c) in open_wc:
            row["n_skip_wallet_coin"] += 1
            continue
        dirs = coin_dirs.setdefault(c, {-1: 0, 1: 0})
        if one_side and dirs[-d] > 0:
            row["n_skip_opposite_direction"] += 1
            continue
        if (coin_count.get(c, 0) + 1) * wc.UNIT_USD > wc.COIN_CAP_USD + 1e-9:
            row["n_skip_coin_cap"] += 1
            continue
        open_wc.add((w, c))
        coin_count[c] = coin_count.get(c, 0) + 1
        dirs[d] += 1
        heapq.heappush(exits, (t + wc.HOLD_MS, i, w, c, d))
        accepted.append(i)
        row["n_accepted_capacity"] += 1

    ii = np.asarray(accepted, dtype=np.int64)
    out = {k: v[ii] for k, v in candidates.items()}
    out["supported"] = np.isfinite(out["gross_bp"])
    out["net_bp"] = out["gross_bp"] - wc.COST_BP
    out["signal_ts"] = out["ts"]
    return out, funnels


def _ids(rows: dict[str, np.ndarray]) -> list[str]:
    return [str(v) for v in rows["source_id"]]


def baseline_and_shadow_checks(
    candidates: dict[str, np.ndarray], rosters: dict[str, Any], parent: dict[str, Any]
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, object], dict[str, object]]:
    baseline, base_funnel = replay(candidates, one_side=False)
    policy, policy_funnel = replay(candidates, one_side=True)

    # Independently reproduce the parent implementation, then require exact row and funnel parity.
    parent_cap, parent_funnel = wc.capacity_book(candidates, rosters, "WALLET_E30")
    normalized_parent = {
        fold: {**values, "n_skip_opposite_direction": 0} for fold, values in parent_funnel.items()
    }
    if _ids(baseline) != _ids(parent_cap) or base_funnel != normalized_parent:
        raise RuntimeError(
            "independent baseline replay does not match parent capacity implementation"
        )
    control = parent["control_book_parity"]["WALLET_E30"]
    base_ordered = wc._ordered_rows_sha(baseline, "gross_bp")
    base_multiset = wc._rows_sha(baseline, "gross_bp")
    if base_ordered != control["ordered_capacity_sha256"]:
        raise RuntimeError("baseline ordered capacity hash does not match frozen parent")
    if base_multiset != control["capacity_multiset_sha256"]:
        raise RuntimeError("baseline capacity multiset hash does not match frozen parent")
    if {
        f: {k: v for k, v in d.items() if k != "n_skip_opposite_direction"}
        for f, d in base_funnel.items()
    } != parent["funnels"]["WALLET_E30"]:
        raise RuntimeError("baseline funnel does not match frozen parent")
    base_supported = wc.supported(baseline)
    if (
        wc._ordered_rows_sha(base_supported, "net_bp")
        != parent["books"]["WALLET_E30"]["supported_ordered_sha256"]
    ):
        raise RuntimeError("baseline supported ordered hash does not match frozen parent")
    if (
        wc._rows_sha(base_supported, "net_bp")
        != parent["books"]["WALLET_E30"]["supported_multiset_sha256"]
    ):
        raise RuntimeError("baseline supported multiset hash does not match frozen parent")

    shadow: dict[str, object] = {}
    for name, values in (
        ("all_nan", np.full(candidates["gross_bp"].shape, np.nan)),
        ("deterministic_noise", np.sin(np.arange(candidates["gross_bp"].size)) * 1e6),
    ):
        altered = {k: v.copy() for k, v in candidates.items()}
        altered["gross_bp"] = values
        sb, sf = replay(altered, one_side=False)
        sp, pf = replay(altered, one_side=True)
        if _ids(sb) != _ids(baseline) or sf != base_funnel:
            raise RuntimeError(f"{name}: baseline acceptance depends on outcome")
        if _ids(sp) != _ids(policy) or pf != policy_funnel:
            raise RuntimeError(f"{name}: one-side acceptance depends on outcome")
        shadow[name] = {
            "baseline_accepted_ids_sha256": _sha256_json(_ids(sb)),
            "policy_accepted_ids_sha256": _sha256_json(_ids(sp)),
            "baseline_funnel_sha256": _sha256_json(sf),
            "policy_funnel_sha256": _sha256_json(pf),
            "pass": True,
        }
    return (
        {BASELINE: baseline, POLICY: policy},
        {BASELINE: base_funnel, POLICY: policy_funnel},
        {
            "parent_capacity_implementation_parity": True,
            "parent_report_hash_parity": True,
            "shadows": shadow,
        },
    )


def daily_pnl(capacity: dict[str, np.ndarray]) -> np.ndarray:
    daily = np.zeros(N_DAYS, dtype=float)
    supported = capacity["supported"]
    exit_day = (capacity["ts"] + wc.HOLD_MS) // DAY_MS
    valid = supported & (exit_day >= START_DAY) & (exit_day <= END_DAY)
    np.add.at(
        daily,
        exit_day[valid].astype(int) - START_DAY,
        capacity["net_bp"][valid] * wc.UNIT_USD / 1e4,
    )
    return daily


def exposure_stats(capacity: dict[str, np.ndarray]) -> dict[str, object]:
    events: dict[int, dict[str, list[tuple[str, int]]]] = {}
    for c, t, d in zip(capacity["coin"], capacity["ts"], capacity["dir_sign"], strict=True):
        entry = int(t)
        exit_ = entry + wc.HOLD_MS
        if entry < END_EXCLUSIVE_MS and exit_ > START_MS:
            events.setdefault(max(entry, START_MS), {"exit": [], "entry": []})["entry"].append(
                (str(c), int(d))
            )
            events.setdefault(min(exit_, END_EXCLUSIVE_MS), {"exit": [], "entry": []})[
                "exit"
            ].append((str(c), int(d)))
    state = {str(c): {-1: 0, 1: 0} for c in wc.MAJORS}
    gross_area = net_area = mixed_coin_area = active_coin_area = mixed_wall = 0.0
    max_gross = max_abs_net = 0.0
    prev = START_MS

    def levels() -> tuple[float, float, int, int]:
        gross_n = sum(v[-1] + v[1] for v in state.values())
        net_n = sum(abs(v[1] - v[-1]) for v in state.values())
        mixed_n = sum(v[-1] > 0 and v[1] > 0 for v in state.values())
        active_n = sum(v[-1] + v[1] > 0 for v in state.values())
        return gross_n * wc.UNIT_USD, net_n * wc.UNIT_USD, int(mixed_n), int(active_n)

    for t in sorted(events):
        if t < START_MS or t > END_EXCLUSIVE_MS:
            continue
        gross, net, mixed, active = levels()
        dt = t - prev
        gross_area += gross * dt
        net_area += net * dt
        mixed_coin_area += mixed * dt
        active_coin_area += active * dt
        mixed_wall += (mixed > 0) * dt
        for c, d in events[t]["exit"]:
            state[c][d] -= 1
            if state[c][d] < 0:
                raise RuntimeError("exposure sweep produced negative state")
        for c, d in events[t]["entry"]:
            state[c][d] += 1
        gross, net, _mixed, _active = levels()
        max_gross = max(max_gross, gross)
        max_abs_net = max(max_abs_net, net)
        prev = t
    if prev < END_EXCLUSIVE_MS:
        gross, net, mixed, active = levels()
        dt = END_EXCLUSIVE_MS - prev
        gross_area += gross * dt
        net_area += net * dt
        mixed_coin_area += mixed * dt
        active_coin_area += active * dt
        mixed_wall += (mixed > 0) * dt
    span = END_EXCLUSIVE_MS - START_MS
    return {
        "average_gross_usd": gross_area / span,
        "average_absolute_net_usd": net_area / span,
        "maximum_gross_usd": max_gross,
        "maximum_absolute_net_usd": max_abs_net,
        "mixed_active_coin_share": mixed_coin_area / active_coin_area if active_coin_area else 0.0,
        "any_book_mixed_wall_time_share": mixed_wall / span,
        "gross_exposure_area_sha256": _sha256_json([gross_area, span]),
        "absolute_net_exposure_area_sha256": _sha256_json([net_area, span]),
    }


def _safe_ratio(num: float, den: float) -> float | None:
    return float(num / den) if den > 0 else None


def book_stats(capacity: dict[str, np.ndarray], daily: np.ndarray) -> dict[str, object]:
    supported = capacity["supported"]
    bp = capacity["net_bp"][supported]
    pnl = bp * wc.UNIT_USD / 1e4
    equity = np.cumsum(daily)
    running_peak = np.maximum.accumulate(np.r_[0.0, equity])
    drawdown = running_peak[1:] - equity
    sd = float(np.std(daily, ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(daily, 0.0) ** 2)))
    positive = float(pnl[pnl > 0].sum())
    negative = float(-pnl[pnl < 0].sum())
    exit_day = (capacity["ts"] + wc.HOLD_MS) // DAY_MS
    months: dict[str, float] = {}
    for month in [
        f"{y:04d}{m:02d}" for y, m in ((2025, 11), (2025, 12), *[(2026, x) for x in range(1, 7)])
    ]:
        lo = int(np.datetime64(f"{month[:4]}-{month[4:]}-01", "D").astype(int))
        if month == "202606":
            hi = END_DAY + 1
        else:
            y, m = int(month[:4]), int(month[4:])
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            hi = int(np.datetime64(f"{ny:04d}-{nm:02d}-01", "D").astype(int))
        mask = supported & (exit_day >= lo) & (exit_day < hi)
        months[month] = float(capacity["net_bp"][mask].sum() * wc.UNIT_USD / 1e4)
    by_fold = {}
    for fold in wc.FOLDS:
        mask = supported & (capacity["fold"] == fold)
        values = capacity["net_bp"][mask]
        by_fold[str(fold)] = {
            "trades": int(mask.sum()),
            "net_usd": float(values.sum() * wc.UNIT_USD / 1e4),
            "net_mean_bp": float(values.mean()) if values.size else None,
        }
    by_coin = {}
    for coin in wc.MAJORS:
        mask = supported & (capacity["coin"] == coin)
        values = capacity["net_bp"][mask]
        by_coin[str(coin)] = {
            "trades": int(mask.sum()),
            "net_usd": float(values.sum() * wc.UNIT_USD / 1e4),
            "net_mean_bp": float(values.mean()) if values.size else None,
        }
    missing = ~supported
    direction = {
        "long": int(np.sum(supported & (capacity["dir_sign"] == 1))),
        "short": int(np.sum(supported & (capacity["dir_sign"] == -1))),
    }
    return {
        "accepted": int(capacity["ts"].size),
        "supported_trades": int(bp.size),
        "missing": int(missing.sum()),
        "missing_rate": float(missing.mean()) if missing.size else None,
        "net_usd": float(pnl.sum()),
        "net_mean_bp_per_trade": float(bp.mean()) if bp.size else None,
        "net_median_bp_per_trade": float(np.median(bp)) if bp.size else None,
        "trade_hit_rate": float(np.mean(bp > 0)) if bp.size else None,
        "active_day_hit_rate": float(np.mean(daily[daily != 0] > 0))
        if np.any(daily != 0)
        else None,
        "profit_factor": _safe_ratio(positive, negative),
        "annualized_sharpe": float(np.mean(daily) / sd * np.sqrt(365)) if sd > 0 else None,
        "annualized_sortino": float(np.mean(daily) / downside * np.sqrt(365))
        if downside > 0
        else None,
        "max_drawdown_usd": float(drawdown.max()) if drawdown.size else 0.0,
        "positive_exit_months": int(sum(v > 0 for v in months.values())),
        "exit_calendar_months": months,
        "entry_fold": by_fold,
        "coin": by_coin,
        "direction": direction,
        "daily_pnl_sha256": _sha256_json(daily.tolist()),
        "daily_pnl_usd": daily.tolist(),
        "accepted_ordered_sha256": wc._ordered_rows_sha(capacity, "gross_bp"),
        "accepted_multiset_sha256": wc._rows_sha(capacity, "gross_bp"),
        "supported_ordered_sha256": wc._ordered_rows_sha(wc.supported(capacity), "net_bp"),
        "supported_multiset_sha256": wc._rows_sha(wc.supported(capacity), "net_bp"),
    }


def parent_headline_parity(stats: dict[str, object], parent: dict[str, Any]) -> dict[str, object]:
    frozen = parent["books"]["WALLET_E30"]
    checks = {
        "accepted": (int(stats["accepted"]), int(frozen["missingness"]["accepted"])),
        "supported": (int(stats["supported_trades"]), int(frozen["n_entries"])),
        "missing": (int(stats["missing"]), int(frozen["missingness"]["missing"])),
        "net_usd": (float(stats["net_usd"]), float(frozen["net_usd"])),
        "net_mean_bp": (
            float(stats["net_mean_bp_per_trade"]),
            float(frozen["net_mean_bp_per_trade"]),
        ),
        "net_median_bp": (
            float(stats["net_median_bp_per_trade"]),
            float(frozen["net_median_bp_per_trade"]),
        ),
        "net_hit_rate": (float(stats["trade_hit_rate"]), float(frozen["net_hit_rate"])),
    }
    for name, (current, expected) in checks.items():
        if name in {"accepted", "supported", "missing"}:
            passed = current == expected
        else:
            passed = math.isclose(current, expected, abs_tol=1e-10, rel_tol=1e-12)
        if not passed:
            raise RuntimeError(
                f"baseline parent headline parity failed for {name}: {current} != {expected}"
            )
    return {
        "pass": True,
        "tolerance": {"absolute": 1e-10, "relative": 1e-12},
        "fields": {name: {"current": pair[0], "parent": pair[1]} for name, pair in checks.items()},
    }


def block_indices(n_days: int = N_DAYS) -> np.ndarray:
    if n_days < BLOCK_DAYS:
        raise ValueError("calendar is shorter than one registered block")
    rng = np.random.default_rng(SEED)
    n_blocks = math.ceil(n_days / BLOCK_DAYS)
    starts = rng.integers(0, n_days - BLOCK_DAYS + 1, size=(N_BOOT, n_blocks))
    offsets = np.arange(BLOCK_DAYS)
    return (starts[:, :, None] + offsets).reshape(N_BOOT, -1)[:, :n_days]


def _mde80(noise: np.ndarray, critical: float, *, positive: bool) -> float:
    def power(x: float) -> float:
        return (
            float(np.mean(noise + x > critical))
            if positive
            else float(np.mean(noise - x < critical))
        )

    lo, hi = 0.0, MATERIAL_USD
    while power(hi) < 0.8:
        hi *= 2.0
        if hi > 1e9:
            raise RuntimeError("MDE search failed to bracket 80% power")
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if power(mid) >= 0.8:
            hi = mid
        else:
            lo = mid
    return math.ceil((hi - 1e-12) * 100.0) / 100.0


def inference(daily_delta: np.ndarray, indices: np.ndarray) -> dict[str, object]:
    d = np.asarray(daily_delta, dtype=float)
    if d.shape != (N_DAYS,) or indices.shape != (N_BOOT, N_DAYS):
        raise ValueError("registered inference dimensions changed")
    sampled = d[indices].sum(axis=1)
    point = float(d.sum())
    ci = np.percentile(sampled, [2.5, 97.5])
    d0 = d - d.mean()
    null_totals = d0[indices].sum(axis=1)
    noise = null_totals - null_totals.mean()
    p = float((1 + np.sum(np.abs(noise) >= abs(point))) / (N_BOOT + 1))
    critical_pos = float(np.percentile(noise, 97.5))
    critical_neg = float(np.percentile(noise, 2.5))
    mde_pos = _mde80(noise, critical_pos, positive=True)
    mde_neg = _mde80(noise, critical_neg, positive=False)
    power_pos = float(np.mean(noise + MATERIAL_USD > critical_pos))
    power_neg = float(np.mean(noise - MATERIAL_USD < critical_neg))
    plus = d0 + MATERIAL_USD / N_DAYS
    minus = d0 - MATERIAL_USD / N_DAYS
    if not math.isclose(float(plus.sum()), MATERIAL_USD, abs_tol=1e-8):
        raise RuntimeError("positive injection point is not exactly registered materiality")
    if not math.isclose(float(minus.sum()), -MATERIAL_USD, abs_tol=1e-8):
        raise RuntimeError("negative injection point is not exactly registered materiality")
    plus_ci = np.percentile(plus[indices].sum(axis=1), [2.5, 97.5])
    minus_ci = np.percentile(minus[indices].sum(axis=1), [2.5, 97.5])
    return {
        "point_usd": point,
        "ci95_usd": [float(ci[0]), float(ci[1])],
        "p_two_sided": p,
        "critical_positive_usd": critical_pos,
        "critical_negative_usd": critical_neg,
        "mde80_positive_usd": mde_pos,
        "mde80_negative_usd": mde_neg,
        "power_at_positive_2500": power_pos,
        "power_at_negative_2500": power_neg,
        "positive_injection": {
            "point_usd": MATERIAL_USD,
            "ci95_usd": [float(plus_ci[0]), float(plus_ci[1])],
            "pass": bool(plus_ci[0] > 0),
        },
        "negative_injection": {
            "point_usd": -MATERIAL_USD,
            "ci95_usd": [float(minus_ci[0]), float(minus_ci[1])],
            "pass": bool(minus_ci[1] < 0),
        },
        "daily_delta_sha256": _sha256_json(d.tolist()),
    }


def missingness(capacity: dict[str, np.ndarray]) -> dict[str, object]:
    miss = ~capacity["supported"]
    per_fold = {}
    for fold in wc.FOLDS:
        mask = capacity["fold"] == fold
        per_fold[str(fold)] = {
            "accepted": int(mask.sum()),
            "missing": int(np.sum(mask & miss)),
            "rate": float(np.mean(miss[mask])) if np.any(mask) else None,
        }
    return {
        "accepted": int(miss.size),
        "missing": int(miss.sum()),
        "rate": float(miss.mean()) if miss.size else None,
        "per_fold": per_fold,
    }


def _identity_map(capacity: dict[str, np.ndarray]) -> dict[str, int]:
    ids = _ids(capacity)
    if len(set(ids)) != len(ids):
        raise RuntimeError("accepted source_id is not unique")
    return {source_id: i for i, source_id in enumerate(ids)}


def missing_bounds(
    policy: dict[str, np.ndarray], baseline: dict[str, np.ndarray], observed_delta: np.ndarray
) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
    pmap, bmap = _identity_map(policy), _identity_map(baseline)
    pmiss = {s for s, i in pmap.items() if not policy["supported"][i]}
    bmiss = {s for s, i in bmap.items() if not baseline["supported"][i]}
    common = sorted(pmiss & bmiss)
    p_only = sorted(pmiss - bmiss)
    b_only = sorted(bmiss - pmiss)
    for source_id in common:
        pi, bi = pmap[source_id], bmap[source_id]
        p_identity = (
            str(policy["wallet"][pi]),
            str(policy["coin"][pi]),
            int(policy["ts"][pi]),
            float(policy["dir_sign"][pi]),
            float(policy["notional"][pi]),
            int(policy["fold"][pi]),
        )
        b_identity = (
            str(baseline["wallet"][bi]),
            str(baseline["coin"][bi]),
            int(baseline["ts"][bi]),
            float(baseline["dir_sign"][bi]),
            float(baseline["notional"][bi]),
            int(baseline["fold"][bi]),
        )
        if p_identity != b_identity:
            raise RuntimeError("shared missing source_id has mismatched canonical identity")
    adverse = observed_delta.copy()
    favorable = observed_delta.copy()
    endpoint_usd = MISSING_BP * wc.UNIT_USD / 1e4

    def add_on_exit(
        daily: np.ndarray, cap: dict[str, np.ndarray], index: int, value: float
    ) -> None:
        day = int((cap["ts"][index] + wc.HOLD_MS) // DAY_MS)
        if START_DAY <= day <= END_DAY:
            daily[day - START_DAY] += value

    for source_id in p_only:
        add_on_exit(adverse, policy, pmap[source_id], -endpoint_usd)
        add_on_exit(favorable, policy, pmap[source_id], endpoint_usd)
    for source_id in b_only:
        add_on_exit(adverse, baseline, bmap[source_id], -endpoint_usd)
        add_on_exit(favorable, baseline, bmap[source_id], endpoint_usd)

    np_accept = policy["ts"].size
    nb_accept = baseline["ts"].size
    known_p = float(np.nansum(np.where(policy["supported"], policy["net_bp"], 0.0))) / np_accept
    known_b = float(np.nansum(np.where(baseline["supported"], baseline["net_bp"], 0.0))) / nb_accept
    low_mean = known_p - known_b
    high_mean = known_p - known_b

    def apply_coef(coef: float) -> None:
        nonlocal low_mean, high_mean
        low_mean += coef * (-MISSING_BP if coef >= 0 else MISSING_BP)
        high_mean += coef * (MISSING_BP if coef >= 0 else -MISSING_BP)

    for _source_id in common:
        apply_coef(1.0 / np_accept - 1.0 / nb_accept)
    for _source_id in p_only:
        apply_coef(1.0 / np_accept)
    for _source_id in b_only:
        apply_coef(-1.0 / nb_accept)

    def arm_stress(cap: dict[str, np.ndarray]) -> dict[str, float]:
        known = float(np.nansum(np.where(cap["supported"], cap["net_bp"], 0.0)))
        nmiss = int(np.sum(~cap["supported"]))
        n = int(cap["ts"].size)
        return {
            "net_usd_low": (known - nmiss * MISSING_BP) * wc.UNIT_USD / 1e4,
            "net_usd_high": (known + nmiss * MISSING_BP) * wc.UNIT_USD / 1e4,
            "mean_bp_low": (known - nmiss * MISSING_BP) / n,
            "mean_bp_high": (known + nmiss * MISSING_BP) / n,
        }

    return (
        {
            "common_missing": len(common),
            "policy_only_missing": len(p_only),
            "baseline_only_missing": len(b_only),
            "common_ordered_sha256": _sha256_json(common),
            "policy_only_ordered_sha256": _sha256_json(p_only),
            "baseline_only_ordered_sha256": _sha256_json(b_only),
            "shared_total_dollar_rows_coupled_and_cancelled": True,
            "mean_bp_delta_bounds": [low_mean, high_mean],
            "absolute_arm_stress": {POLICY: arm_stress(policy), BASELINE: arm_stress(baseline)},
        },
        adverse,
        favorable,
    )


def missing_gates(by_arm: dict[str, dict[str, object]]) -> dict[str, object]:
    rates = [float(by_arm[a]["rate"]) for a in ARMS]
    overall = all(rate <= 0.01 for rate in rates)
    fold_rates = True
    imbalances = {"overall": abs(rates[0] - rates[1]), "per_fold": {}}
    for fold in wc.FOLDS:
        pr = float(by_arm[POLICY]["per_fold"][str(fold)]["rate"])
        br = float(by_arm[BASELINE]["per_fold"][str(fold)]["rate"])
        fold_rates = fold_rates and pr <= 0.02 and br <= 0.02
        imbalances["per_fold"][str(fold)] = abs(pr - br)
    imbalance = imbalances["overall"] <= 0.005
    return {
        "overall_rate_le_1pct": overall,
        "every_fold_rate_le_2pct": fold_rates,
        "overall_arm_imbalance_le_0_5pp": imbalance,
        "per_fold_arm_imbalances_diagnostic_only": True,
        "imbalances": imbalances,
        "pass": bool(overall and fold_rates and imbalance),
    }


def exact_sign_test(deltas: dict[str, float]) -> dict[str, object]:
    values = np.asarray(list(deltas.values()), dtype=float)
    positive = int(np.sum(values > TOL))
    negative = int(np.sum(values < -TOL))
    tied = int(values.size - positive - negative)
    n = positive + negative
    if n:
        tail = sum(math.comb(n, i) for i in range(min(positive, negative) + 1)) / (2**n)
        p = min(1.0, 2.0 * tail)
    else:
        p = None
    return {
        "deltas_usd": deltas,
        "positive": positive,
        "negative": negative,
        "evaluable": n,
        "tied": tied,
        "exact_two_sided_binomial_p": p,
    }


def cross_unit(policy: dict[str, np.ndarray], baseline: dict[str, np.ndarray]) -> dict[str, object]:
    def totals(cap: dict[str, np.ndarray], key: str, units: list[Any]) -> dict[str, float]:
        return {
            str(unit): float(
                cap["net_bp"][cap["supported"] & (cap[key] == unit)].sum() * wc.UNIT_USD / 1e4
            )
            for unit in units
        }

    p_fold, b_fold = (
        totals(policy, "fold", list(wc.FOLDS)),
        totals(baseline, "fold", list(wc.FOLDS)),
    )
    p_coin, b_coin = (
        totals(policy, "coin", list(wc.MAJORS)),
        totals(baseline, "coin", list(wc.MAJORS)),
    )
    return {
        "entry_fold": exact_sign_test({k: p_fold[k] - b_fold[k] for k in p_fold}),
        "coin": exact_sign_test({k: p_coin[k] - b_coin[k] for k in p_coin}),
        "families_pooled": False,
        "significance_gate": False,
    }


def construction_report(
    candidates: dict[str, np.ndarray],
    capacities: dict[str, dict[str, np.ndarray]],
    funnels: dict[str, object],
    checks: dict[str, object],
) -> dict[str, object]:
    arms = {}
    for arm in ARMS:
        cap = capacities[arm]
        arms[arm] = {
            "candidate_ordered_sha256": wc._ordered_rows_sha(candidates, "gross_bp"),
            "candidate_multiset_sha256": wc._rows_sha(candidates, "gross_bp"),
            "accepted_ordered_sha256": wc._ordered_rows_sha(cap, "gross_bp"),
            "accepted_multiset_sha256": wc._rows_sha(cap, "gross_bp"),
            "supported_ordered_sha256": wc._ordered_rows_sha(wc.supported(cap), "net_bp"),
            "supported_multiset_sha256": wc._rows_sha(wc.supported(cap), "net_bp"),
            "funnel": funnels[arm],
            "funnel_sha256": _sha256_json(funnels[arm]),
        }
    if any(
        v != 0
        for d in funnels[BASELINE].values()
        for k, v in d.items()
        if k == "n_skip_opposite_direction"
    ):
        raise RuntimeError("baseline unexpectedly applied the direction policy")
    return {
        "both_arms_replayed_complete_stream_independently": True,
        "gate_order": ["wallet_coin", "opposite_direction", "coin_cap"],
        "exits_before_entries_at_ties": True,
        "arms": arms,
        **checks,
    }


def classify(
    observed: dict[str, object],
    adverse: dict[str, object],
    favorable: dict[str, object],
    gates_pass: bool,
) -> dict[str, object]:
    conservative = [float(adverse["ci95_usd"][0]), float(favorable["ci95_usd"][1])]
    observed_ci = [float(v) for v in observed["ci95_usd"]]
    if conservative[0] > observed_ci[0] + 1e-9 or conservative[1] < observed_ci[1] - 1e-9:
        raise RuntimeError("conservative missingness interval does not contain observed interval")
    all_inf = (observed, adverse, favorable)
    binding = {
        "mde80_positive_usd": max(float(v["mde80_positive_usd"]) for v in all_inf),
        "mde80_negative_usd": max(float(v["mde80_negative_usd"]) for v in all_inf),
        "power_at_positive_2500": min(float(v["power_at_positive_2500"]) for v in all_inf),
        "power_at_negative_2500": min(float(v["power_at_negative_2500"]) for v in all_inf),
        "positive_injection_pass": all(bool(v["positive_injection"]["pass"]) for v in all_inf),
        "negative_injection_pass": all(bool(v["negative_injection"]["pass"]) for v in all_inf),
    }
    negative_control = (
        binding["mde80_negative_usd"] <= MATERIAL_USD
        and binding["power_at_negative_2500"] >= 0.8
        and binding["negative_injection_pass"]
    )
    both_controls = (
        negative_control
        and binding["mde80_positive_usd"] <= MATERIAL_USD
        and binding["power_at_positive_2500"] >= 0.8
        and binding["positive_injection_pass"]
    )
    adverse_claim = bool(
        gates_pass
        and float(favorable["point_usd"]) < 0
        and float(favorable["ci95_usd"][1]) < -MATERIAL_USD
        and negative_control
    )
    equivalent_claim = bool(
        gates_pass
        and conservative[0] > -MATERIAL_USD
        and conservative[1] < MATERIAL_USD
        and both_controls
    )
    if adverse_claim and equivalent_claim:
        raise RuntimeError("registered claim predicates overlap")
    label = (
        "NARROW_POLICY_ADVERSE"
        if adverse_claim
        else "NARROW_POLICY_NO_MATERIAL_EFFECT"
        if equivalent_claim
        else "UNRESOLVED"
    )
    return {
        "materiality_margin_usd": MATERIAL_USD,
        "conservative_missingness_ci95_usd": conservative,
        "binding_controls_across_observed_and_bounds": binding,
        "all_nondirectional_gates_pass": gates_pass,
        "narrow_policy_adverse_predicate": adverse_claim,
        "narrow_policy_no_material_effect_predicate": equivalent_claim,
        "claim": label,
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
    }


def run() -> dict[str, object]:
    _write_nonresult("SAME_COIN_POLICY_PENDING_NO_RESULTS")
    try:
        seal = execution_seal()
        parent, rosters, candidates = load_frozen_inputs()
        candidate_checks = validate_candidates(candidates)
        capacities, funnels, replay_checks = baseline_and_shadow_checks(candidates, rosters, parent)
        construction = construction_report(candidates, capacities, funnels, replay_checks)
        dailies = {arm: daily_pnl(capacities[arm]) for arm in ARMS}
        exposures = {arm: exposure_stats(capacities[arm]) for arm in ARMS}
        if (
            exposures[POLICY]["mixed_active_coin_share"] != 0
            or exposures[POLICY]["any_book_mixed_wall_time_share"] != 0
        ):
            raise RuntimeError("one-side policy retained mixed-direction exposure")
        stats = {arm: book_stats(capacities[arm], dailies[arm]) for arm in ARMS}
        for arm in ARMS:
            stats[arm]["exposure"] = exposures[arm]
            denom = exposures[arm]["maximum_gross_usd"]
            stats[arm]["max_drawdown_share_of_max_gross"] = (
                stats[arm]["max_drawdown_usd"] / denom if denom else None
            )
        construction["parent_headline_arithmetic_parity"] = parent_headline_parity(
            stats[BASELINE], parent
        )

        indices = block_indices()
        observed_daily = dailies[POLICY] - dailies[BASELINE]
        missing_by_arm = {arm: missingness(capacities[arm]) for arm in ARMS}
        miss_gates = missing_gates(missing_by_arm)
        miss_bounds, adverse_daily, favorable_daily = missing_bounds(
            capacities[POLICY], capacities[BASELINE], observed_daily
        )
        inferences = {
            "observed": inference(observed_daily, indices),
            "adverse_missingness": inference(adverse_daily, indices),
            "favorable_missingness": inference(favorable_daily, indices),
        }
        all_construction_gates = bool(
            replay_checks["parent_capacity_implementation_parity"]
            and replay_checks["parent_report_hash_parity"]
            and construction["parent_headline_arithmetic_parity"]["pass"]
            and all(v["pass"] for v in replay_checks["shadows"].values())
            and miss_gates["pass"]
        )
        decision = classify(
            inferences["observed"],
            inferences["adverse_missingness"],
            inferences["favorable_missingness"],
            all_construction_gates,
        )
        delta = {
            "primary": "ONE_SIDE_PER_COIN - VIRTUAL_SLEEVES total net USD",
            "net_usd": stats[POLICY]["net_usd"] - stats[BASELINE]["net_usd"],
            "net_mean_bp_per_trade": stats[POLICY]["net_mean_bp_per_trade"]
            - stats[BASELINE]["net_mean_bp_per_trade"],
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
        if not math.isclose(
            float(delta["net_usd"]), float(inferences["observed"]["point_usd"]), abs_tol=1e-8
        ):
            raise RuntimeError("headline dollar delta does not equal paired daily point")

        report: dict[str, object] = {
            "status": "BURNED_SAME_COIN_EXECUTION_DIAGNOSTIC",
            "comparative_results_present": True,
            "positive_promotion_eligible": False,
            "method_null_eligible": False,
            "final_label": (
                "burned same-coin execution diagnostic; favorable direction always unresolved "
                "and never suggestive/candidate/deployable. Only a powered construction-safe "
                "adverse/no-material-effect "
                "result may earn a narrow policy-scoped negative."
            ),
            "config": {
                "architecture_sha256": seal["architecture_sha256"],
                "code_sha256": seal["code_sha256"],
                "dependency_hashes": seal["dependency_hashes"],
                "arms": list(ARMS),
                "unit_usd": wc.UNIT_USD,
                "coin_cap_usd": wc.COIN_CAP_USD,
                "hold_hours": 8,
                "cost_bp": wc.COST_BP,
                "missing_bound_bp": MISSING_BP,
                "materiality_usd": MATERIAL_USD,
                "calendar": ["2025-11-01", "2026-06-30"],
                "n_days": N_DAYS,
                "bootstrap": {
                    "numpy_rng": "default_rng PCG64",
                    "seed": SEED,
                    "draws": N_BOOT,
                    "noncircular_block_days": BLOCK_DAYS,
                    "blocks_per_draw": math.ceil(N_DAYS / BLOCK_DAYS),
                    "start_support_inclusive": [0, N_DAYS - BLOCK_DAYS],
                    "index_matrix_sha256": _sha256_json(indices.tolist()),
                },
                "consensus": "excluded",
                "bot500_screen": "excluded",
                "input_snapshot": seal["inputs"],
            },
            "candidate_stream": candidate_checks,
            "construction": construction,
            "funnels": funnels,
            "books": stats,
            "delta": delta,
            "cross_unit_combination": cross_unit(capacities[POLICY], capacities[BASELINE]),
            "missingness": {
                "by_arm": missing_by_arm,
                "gates": miss_gates,
                "coupled_bounds": miss_bounds,
            },
            "inference": inferences,
            "decision": decision,
        }
        if execution_seal() != seal:
            raise RuntimeError("execution code, architecture, dependency, or input seal changed")
        atomic_json(OUT, report)
        return report
    except Exception as exc:
        _write_nonresult("SAME_COIN_POLICY_FAILURE", f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    run()
