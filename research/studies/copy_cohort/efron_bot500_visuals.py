# ruff: noqa: E501
"""Rendered diagnostic atlas for the burned Efron BOT500 study."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import math
import platform
import shutil
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyarrow
import pyarrow.parquet as pq
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import ListedColormap

from research.data.markout import REPO_ROOT

from .dynamic_t_quality import FOLDS, formation_months
from .efron_bot500 import (
    ARCH as STUDY_ARCH,
)
from .efron_bot500 import (
    ARMS,
    BOT_MAX,
    COIN_CAP_USD,
    COST_BP,
    ENTRIES,
    HOLD_MS,
    NOTIONAL_MIN,
    PARENT_BOOK,
    PARENT_ROSTERS,
    ROSTERS,
    STALE_MS,
    TOP_K,
    UNIT_USD,
    book_stats,
    capacity_book_global,
    concat,
    entry_data_record,
    file_sha256,
    grouped_scores,
    load_entries,
    missing_stats,
    normalized_x,
    raw_stats,
    selected_raw_global,
    supported_book,
)
from .efron_bot500 import (
    OUT as BOOK_REPORT,
)
from .filtered_quality import _code_sha256, _sha256_json
from .informed import t_to_z

SPEC = Path(__file__).with_name("EFRON_BOT500_VISUALS_SPEC.md")
ROOT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "efron_bot500" / "visuals"
LATEST = ROOT / "latest.json"
COINS = ("BTC", "ETH", "SOL", "HYPE")
COLORS = {"E30": "#2563eb", "E_BOT500": "#f97316"}
DISPLAY = {"E30": "Standard Efron", "E_BOT500": "BOT500 Efron"}
WATERMARK = "BURNED POST-HOC • UNDERPOWERED • MISSINGNESS UNRESOLVED • NON-DEPLOYABLE"
DOMINANT_WALLET = "0xa1b6d8efbcb2fb750a84dbc05649fa4968034f04"
DAY_MS = 86_400_000


def sha256(path: Path) -> str:
    return file_sha256(path)


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def input_record(path: Path) -> dict[str, object]:
    return {"path": repo_rel(path), "size": path.stat().st_size, "sha256": sha256(path)}


def next_month(fold: int) -> int:
    year, month = divmod(fold, 100)
    if month == 12:
        return (year + 1) * 100 + 1
    return year * 100 + month + 1


def month_ms(fold: int) -> tuple[int, int]:
    year, month = divmod(fold, 100)
    start = int(datetime(year, month, 1, tzinfo=UTC).timestamp() * 1000)
    nxt = next_month(fold)
    y2, m2 = divmod(nxt, 100)
    end = int(datetime(y2, m2, 1, tzinfo=UTC).timestamp() * 1000)
    return start, end


def assert_close(actual: float, expected: float, label: str, tol: float = 1e-10) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=tol, abs_tol=tol):
        raise RuntimeError(f"{label}: {actual} != {expected}")


def cohort_from_panel(path: Path, fold: int) -> dict[str, np.ndarray | float]:
    columns = [
        "wallet",
        "day",
        "day_pnl",
        "day_notional",
        "btc_notional",
        "eth_notional",
        "sol_notional",
        "hype_notional",
        "n_liq",
        "n_open_flat",
        "fills_per_day",
    ]
    d = pq.read_table(path, columns=columns).to_pydict()
    wallet_rows = np.asarray(d["wallet"], str)
    day = np.asarray(d["day"], np.int64)
    if day.min() < formation_months(fold)[0] * 100 + 1 or day.max() >= fold * 100 + 1:
        raise RuntimeError(f"fold {fold}: formation panel timing violation")
    x = np.asarray(
        [normalized_x(p, n) for p, n in zip(d["day_pnl"], d["day_notional"], strict=True)]
    )
    fpd_rows = np.asarray(d["fills_per_day"], float)
    wallets, nd, sd, t, fpd = grouped_scores(wallet_rows, x, fpd_rows)
    _, starts, counts = np.unique(wallet_rows, return_index=True, return_counts=True)
    mean_x = np.add.reduceat(x, starts) / counts
    day_notional = np.asarray(d["day_notional"], float)
    total_notional = np.add.reduceat(day_notional, starts)
    coin_share = []
    for coin in COINS:
        value = np.asarray(d[f"{coin.lower()}_notional"], float)
        coin_share.append(np.add.reduceat(value, starts) / np.maximum(total_notional, 1e-300))
    n_liq = np.add.reduceat(np.asarray(d["n_liq"], float), starts)
    n_open = np.add.reduceat(np.asarray(d["n_open_flat"], float), starts)
    means_row = np.repeat(mean_x, counts)
    centered = x - means_row
    same = wallet_rows[1:] == wallet_rows[:-1]
    a, b = centered[:-1][same], centered[1:][same]
    lag_corr = float(np.corrcoef(a, b)[0, 1]) if a.size > 2 else math.nan
    eligible = np.isfinite(t)
    z = np.full(t.size, np.nan)
    z[eligible] = t_to_z(t[eligible], nd[eligible] - 1)
    return {
        "wallet": wallets,
        "nd": nd,
        "sd": sd,
        "mean_x": mean_x,
        "t": t,
        "z": z,
        "fpd": fpd,
        "eligible": eligible,
        "coin_share": np.column_stack(coin_share),
        "n_liq": n_liq,
        "n_open": n_open,
        "lag_corr": lag_corr,
    }


def ordered_input_hash(cohort: dict[str, np.ndarray | float], mask: np.ndarray) -> str:
    wallet = np.asarray(cohort["wallet"])[mask]
    nd = np.asarray(cohort["nd"])[mask]
    t = np.asarray(cohort["t"])[mask]
    z = np.asarray(cohort["z"])[mask]
    rows = [
        {"wallet": str(a), "nd": int(b), "t": float(c), "z": float(d)}
        for a, b, c, d in zip(wallet, nd, t, z, strict=True)
    ]
    return _sha256_json(rows)


def collect_input_paths() -> list[Path]:
    paths = [
        BOOK_REPORT,
        ROSTERS,
        STUDY_ARCH,
        Path(__file__).with_name("efron_bot500.py"),
        Path(__file__).with_name("dynamic_t_book.py"),
        PARENT_BOOK,
        PARENT_ROSTERS,
        SPEC,
        Path(__file__),
        Path(__file__).with_name("adaptive_rq_filter.py"),
        Path(__file__).with_name("alt_fresh_validate.py"),
        Path(__file__).with_name("backtest_book.py"),
        Path(__file__).with_name("dynamic_t_quality.py"),
        Path(__file__).with_name("filtered_quality.py"),
        Path(__file__).with_name("informed.py"),
        Path(__file__).with_name("nested_t_book.py"),
        Path(__file__).with_name("nested_t_filter.py"),
        Path(__file__).with_name("lake.py"),
        Path(__file__).with_name("majors_native.py"),
        Path(__file__).with_name("ksweep.py"),
        REPO_ROOT / "research" / "lib" / "stats.py",
        REPO_ROOT / "research" / "lib" / "cv.py",
        REPO_ROOT / "research" / "data" / "markout.py",
        REPO_ROOT / "research" / "data" / "schema.py",
    ]
    for fold in FOLDS:
        paths.extend(
            [
                ENTRIES / f"entries_{fold}.parquet",
                ENTRIES / f"entries_{fold}.meta.json",
                REPO_ROOT
                / "data"
                / "derived"
                / "copy_cohort"
                / "nested_t_filter"
                / "panels"
                / f"daily_{fold}.parquet",
                REPO_ROOT
                / "data"
                / "derived"
                / "copy_cohort"
                / "nested_t_filter"
                / "panels"
                / f"daily_{fold}.meta.json",
            ]
        )
    unique = {p.resolve(): p for p in paths}
    return [unique[k] for k in sorted(unique, key=str)]


def wallet_contributions(
    a: dict[str, np.ndarray], b: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    wallets = np.asarray(sorted(set(a["wallet"]) | set(b["wallet"])), str)
    ca = np.asarray(
        [a["net_bp"][a["wallet"] == w].sum() / max(a["net_bp"].size, 1) for w in wallets]
    )
    cb = np.asarray(
        [b["net_bp"][b["wallet"] == w].sum() / max(b["net_bp"].size, 1) for w in wallets]
    )
    return {"wallet": wallets, "a": ca, "b": cb, "delta": ca - cb}


def load_and_validate() -> dict[str, object]:
    allowed_paths = collect_input_paths()
    inputs_before = [input_record(p) for p in allowed_paths]
    report = json.loads(BOOK_REPORT.read_text())
    rosters = json.loads(ROSTERS.read_text())
    if report.get("status") != "BURNED_POSTHOC_EFRON_BOT500_BOOK_DIAGNOSTIC":
        raise RuntimeError("book report is not successful")
    if rosters.get("status") != "BURNED_POSTHOC_EFRON_BOT500_SELECTOR":
        raise RuntimeError("roster report is not successful")
    for obj in (report, rosters):
        if (
            obj.get("positive_promotion_eligible") is not False
            or obj.get("method_null_eligible") is not False
        ):
            raise RuntimeError("eligibility firewall is not hard false")
    if (
        report["config"].get("consensus") != "excluded"
        or rosters["config"].get("consensus") != "excluded"
    ):
        raise RuntimeError("consensus firewall failed")
    if report.get("selector") != rosters:
        raise RuntimeError("embedded selector differs from roster artifact")
    primary = report.get("primary", {})
    if (
        primary.get("positive_promotion_eligible") is not False
        or primary.get("method_null_eligible") is not False
    ):
        raise RuntimeError("primary eligibility firewall is not hard false")
    expected_folds = {str(f) for f in FOLDS}
    expected_arms = set(ARMS)
    if set(rosters.get("folds", {})) != expected_folds:
        raise RuntimeError("selector fold set is not exact")
    if set(report.get("funnels", {})) != expected_folds:
        raise RuntimeError("book funnel fold set is not exact")
    if set(report.get("books", {})) != expected_arms:
        raise RuntimeError("book arm set is not exact")
    if set(rosters.get("config", {}).get("arms", [])) != expected_arms:
        raise RuntimeError("selector config arm set is not exact")
    if (
        tuple(report.get("config", {}).get("arms", [])) != ARMS
        or tuple(rosters.get("config", {}).get("arms", [])) != ARMS
    ):
        raise RuntimeError("configured arm order is not exact")
    if (
        set(report["config"].get("entry_parquet", {})) != expected_folds
        or set(report["config"].get("entry_meta_sha256", {})) != expected_folds
    ):
        raise RuntimeError("entry binding fold sets are not exact")
    expected_report_config = {
        "bot_max": BOT_MAX,
        "unit_usd": UNIT_USD,
        "coin_cap_usd": COIN_CAP_USD,
        "hold_h": HOLD_MS / 3_600_000,
        "cost_bp": COST_BP,
        "primary": "E_BOT500__minus__E30",
        "n_boot": 10_000,
        "seed": 20260720,
        "consensus": "excluded",
    }
    if any(report["config"].get(k) != v for k, v in expected_report_config.items()):
        raise RuntimeError("book report constants changed")
    if primary.get("verdict_status") != "MISSINGNESS_UNRESOLVED":
        raise RuntimeError("book verdict no longer matches visual watermark")
    for fold in FOLDS:
        item = rosters["folds"][str(fold)]
        if set(item.get("rosters", {})) != expected_arms:
            raise RuntimeError(f"fold {fold}: roster arm set is not exact")
        if set(report["funnels"][str(fold)]) != expected_arms:
            raise RuntimeError(f"fold {fold}: funnel arm set is not exact")
        for arm in ARMS:
            members = item["rosters"][arm]
            if len(members) != TOP_K or len(set(members)) != TOP_K:
                raise RuntimeError(f"fold {fold}/{arm}: roster is not exactly 30 unique wallets")
    if report["config"].get("roster_report_file_sha256") != sha256(ROSTERS):
        raise RuntimeError("book does not bind current roster artifact")
    if report["config"].get("architecture_sha256") != sha256(STUDY_ARCH):
        raise RuntimeError("study architecture hash is stale")
    if report["config"].get("code_sha256") != _code_sha256(
        Path(__file__).with_name("efron_bot500.py")
    ):
        raise RuntimeError("study code hash is stale")
    if report["config"].get("inference_dependency_sha256") != sha256(
        Path(__file__).with_name("dynamic_t_book.py")
    ):
        raise RuntimeError("inference hash is stale")
    if report["config"].get("parent_book_file_sha256") != sha256(PARENT_BOOK):
        raise RuntimeError("parent book hash is stale")
    if report["config"].get("parent_rosters_file_sha256") != sha256(PARENT_ROSTERS):
        raise RuntimeError("parent roster hash is stale")

    cohorts: dict[str, dict[str, np.ndarray | float]] = {}
    parts = []
    for fold in FOLDS:
        key = str(fold)
        panel = (
            REPO_ROOT
            / "data"
            / "derived"
            / "copy_cohort"
            / "nested_t_filter"
            / "panels"
            / f"daily_{fold}.parquet"
        )
        item = rosters["folds"][key]
        if Path(item["panel_path"]).resolve() != panel.resolve():
            raise RuntimeError(f"fold {fold}: noncanonical panel path")
        if item["panel_file_sha256"] != sha256(panel):
            raise RuntimeError(f"fold {fold}: panel hash changed")
        if item["panel_meta_sha256"] != sha256(panel.with_suffix(".meta.json")):
            raise RuntimeError(f"fold {fold}: panel meta hash changed")
        cohort = cohort_from_panel(panel, fold)
        eligible = np.asarray(cohort["eligible"], bool)
        bot = eligible & (np.asarray(cohort["fpd"], float) <= BOT_MAX)
        if int(eligible.sum()) != item["n_eligible"] or int(bot.sum()) != item["n_bot_eligible"]:
            raise RuntimeError(f"fold {fold}: selector population count mismatch")
        if int(np.sum(eligible & ~bot)) != item["n_excluded_gt500"]:
            raise RuntimeError(f"fold {fold}: exclusion count mismatch")
        if ordered_input_hash(cohort, eligible) != item["fit_E30"]["ordered_input_sha256"]:
            raise RuntimeError(f"fold {fold}: E30 ordered input mismatch")
        if ordered_input_hash(cohort, bot) != item["fit_E_BOT500"]["ordered_input_sha256"]:
            raise RuntimeError(f"fold {fold}: BOT500 ordered input mismatch")
        if len(set(item["rosters"]["E30"]) & set(item["rosters"]["E_BOT500"])) != item["overlap"]:
            raise RuntimeError(f"fold {fold}: roster overlap mismatch")
        selected_fpd = item.get("selected_bot_fills_per_day", {})
        if set(selected_fpd) != set(item["rosters"]["E_BOT500"]) or any(
            not np.isfinite(float(v)) or float(v) > BOT_MAX for v in selected_fpd.values()
        ):
            raise RuntimeError(f"fold {fold}: selected BOT500 activity invariant failed")
        cohort_wallets = np.asarray(cohort["wallet"])
        for wallet, saved_fpd in selected_fpd.items():
            idx = int(np.searchsorted(cohort_wallets, wallet))
            if (
                idx >= cohort_wallets.size
                or cohort_wallets[idx] != wallet
                or not math.isclose(
                    float(np.asarray(cohort["fpd"])[idx]),
                    float(saved_fpd),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            ):
                raise RuntimeError(f"fold {fold}: selected BOT500 fills/day mismatch")
        cohorts[key] = cohort

        entry = ENTRIES / f"entries_{fold}.parquet"
        meta_path = ENTRIES / f"entries_{fold}.meta.json"
        payload = json.loads(meta_path.read_text())
        expected_data = entry_data_record(entry)
        if payload.get("data") != expected_data:
            raise RuntimeError(f"fold {fold}: sidecar entry binding failed")
        if report["config"]["entry_parquet"][key] != expected_data:
            raise RuntimeError(f"fold {fold}: book entry binding failed")
        if report["config"]["entry_meta_sha256"][key] != sha256(meta_path):
            raise RuntimeError(f"fold {fold}: book sidecar binding failed")
        spec = payload["spec"]
        if spec.get("fold") != fold or spec.get("source_lineage", {}).get("months") != [fold]:
            raise RuntimeError(f"fold {fold}: evaluation lineage timing mismatch")
        fold_rosters = item["rosters"]
        expected_wallets = sorted({w for arm in ARMS for w in fold_rosters[arm]})
        maxima = spec.get("context_max_ts_by_coin", {})
        expected_sidecar_config = {
            "majors": list(COINS),
            "notional_min": NOTIONAL_MIN,
            "hold_ms": HOLD_MS,
            "stale_ms": STALE_MS,
        }
        if (
            spec.get("schema") != "efron-bot500-entry-v1"
            or spec.get("architecture_sha256") != sha256(STUDY_ARCH)
            or spec.get("code_sha256") != report["config"]["code_sha256"]
            or spec.get("roster_report_file_sha256") != sha256(ROSTERS)
            or spec.get("wallets") != expected_wallets
            or spec.get("wallets_sha256") != _sha256_json(expected_wallets)
            or spec.get("arm_rosters_sha256")
            != _sha256_json({arm: fold_rosters[arm] for arm in ARMS})
            or set(maxima) != set(COINS)
            or spec.get("config") != expected_sidecar_config
            or spec.get("context_sha256") != _sha256_json(spec.get("context", []))
            or set(spec.get("source_lineage", {}).get("datasets", []))
            != {"alt_universe_open_entries"}
            or int(spec.get("common_cutoff", -1)) != min(int(v) for v in maxima.values()) - HOLD_MS
        ):
            raise RuntimeError(f"fold {fold}: entry sidecar semantic contract failed")
        tab = pq.read_table(
            entry,
            columns=["ts", "px0_ts", "px8_ts", "gross_bp", "common_cutoff"],
        ).to_pydict()
        ts = np.asarray(tab["ts"], np.int64)
        start, end = month_ms(fold)
        if ts.size and (ts.min() < start or ts.max() >= end):
            raise RuntimeError(f"fold {fold}: entry outside evaluation month")
        cutoff = np.asarray(tab["common_cutoff"], np.int64)
        if ts.size and (np.any(ts > cutoff) or np.unique(cutoff).size != 1):
            raise RuntimeError(f"fold {fold}: entry cutoff violation")
        if ts.size and int(cutoff[0]) != int(spec["common_cutoff"]):
            raise RuntimeError(f"fold {fold}: entry cutoff differs from sidecar")
        gross = np.asarray([math.nan if v is None else float(v) for v in tab["gross_bp"]])
        px0_ts = np.asarray([math.nan if v is None else float(v) for v in tab["px0_ts"]])
        px8_ts = np.asarray([math.nan if v is None else float(v) for v in tab["px8_ts"]])
        supported = np.isfinite(gross)
        if np.any(
            (px0_ts[supported] > ts[supported])
            | (ts[supported] - px0_ts[supported] > STALE_MS)
            | (px8_ts[supported] > ts[supported] + HOLD_MS)
            | (ts[supported] + HOLD_MS - px8_ts[supported] > STALE_MS)
        ):
            raise RuntimeError(f"fold {fold}: backward-ASOF timing/staleness violation")
        parts.append(load_entries(entry, fold))

    entries = concat(parts)
    rosters_by_arm = {
        arm: {str(f): rosters["folds"][str(f)]["rosters"][arm] for f in FOLDS} for arm in ARMS
    }
    capacity, books, raw, funnels = {}, {}, {}, {}
    for arm in ARMS:
        raw[arm] = selected_raw_global(entries, rosters_by_arm[arm])
        capacity[arm], funnels[arm] = capacity_book_global(entries, rosters_by_arm[arm])
        books[arm] = supported_book(capacity[arm])
        saved = report["books"][arm]
        assert_close(books[arm]["net_bp"].mean(), saved["net_bp_per_entry"], f"{arm} mean")
        if books[arm]["net_bp"].size != saved["n_entries"]:
            raise RuntimeError(f"{arm}: supported entry count mismatch")
        assert_close(
            books[arm]["net_bp"].sum() * UNIT_USD / 1e4,
            saved["net_usd"],
            f"{arm} dollars",
        )
        for fold in FOLDS:
            if funnels[arm][str(fold)] != report["funnels"][str(fold)][arm]:
                raise RuntimeError(f"{arm}/{fold}: funnel mismatch")
        computed_book = book_stats(books[arm])
        saved_book = {k: saved[k] for k in computed_book}
        if computed_book != saved_book:
            raise RuntimeError(f"{arm}: full book statistics mismatch")
        if raw_stats(raw[arm]) != saved["raw"]:
            raise RuntimeError(f"{arm}: raw statistics mismatch")
        if missing_stats(capacity[arm]) != saved["missingness"]:
            raise RuntimeError(f"{arm}: missingness statistics mismatch")
    delta = books["E_BOT500"]["net_bp"].mean() - books["E30"]["net_bp"].mean()
    assert_close(delta, report["primary"]["delta_bp"], "primary delta")
    contrib = wallet_contributions(books["E_BOT500"], books["E30"])
    assert_close(np.asarray(contrib["delta"]).sum(), delta, "wallet contribution sum")
    abs_share = (
        np.sort(np.abs(np.asarray(contrib["delta"])))[-5:].sum()
        / np.abs(np.asarray(contrib["delta"])).sum()
    )
    assert_close(abs_share, report["primary"]["concentration"]["top5_abs_share"], "top5 share")
    inputs_after_load = [input_record(p) for p in allowed_paths]
    if inputs_after_load != inputs_before:
        raise RuntimeError("study input changed while being loaded")
    return {
        "report": report,
        "rosters": rosters,
        "cohorts": cohorts,
        "entries": entries,
        "capacity": capacity,
        "books": books,
        "raw": raw,
        "funnels": funnels,
        "contrib": contrib,
        "inputs": inputs_before,
    }


def style_axis(ax, title: str, schema: str) -> None:
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", pad=12)
    ax.text(
        0,
        1.01,
        schema,
        transform=ax.transAxes,
        fontsize=6.7,
        color="#64748b",
        va="bottom",
    )
    ax.grid(True, alpha=0.18, linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)


def new_page(title: str, digest: str) -> tuple[plt.Figure, np.ndarray]:
    fig, axes = plt.subplots(3, 2, figsize=(16, 13), constrained_layout=False)
    fig.subplots_adjust(top=0.90, bottom=0.065, hspace=0.48, wspace=0.22)
    fig.suptitle(title, x=0.055, y=0.965, ha="left", fontsize=20, fontweight="bold")
    fig.text(0.055, 0.938, "Majors: BTC / ETH / SOL / HYPE • 2025-11 through 2026-06", fontsize=9)
    fig.text(
        0.055,
        0.018,
        f"{WATERMARK}  •  generation {digest}",
        fontsize=5.7,
        color="#b91c1c",
        fontweight="bold",
    )
    return fig, axes.ravel()


def normal_pdf(x: np.ndarray, mu: float = 0.0, sigma: float = 1.0) -> np.ndarray:
    return np.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * np.sqrt(2 * np.pi))


def empirical_survival_abs(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(np.abs(np.asarray(values, float)))
    x = x[np.isfinite(x)]
    return x, (x.size - np.arange(x.size)) / max(x.size, 1)


def qq_points(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    y = np.sort(np.asarray(values, float))
    y = y[np.isfinite(y)]
    p = (np.arange(y.size) + 0.5) / y.size
    q = np.asarray([NormalDist().inv_cdf(float(v)) for v in p])
    y = (y - y.mean()) / max(y.std(ddof=1), 1e-12)
    return q, y


def wallet_fold_robust(raw: dict[str, np.ndarray]) -> tuple[float, float, int]:
    bp = raw["gross_bp"]
    limit = float(np.percentile(np.abs(bp), 95))
    clipped = np.clip(bp, -limit, limit)
    key = np.char.add(np.char.add(raw["wallet"], "|"), raw["fold"].astype(str))
    _, inv, count = np.unique(key, return_inverse=True, return_counts=True)
    keep = count[inv] >= 3
    _, inv2 = np.unique(key[keep], return_inverse=True)
    wf = np.bincount(inv2, weights=clipped[keep]) / np.bincount(inv2)
    return float(wf.mean()), limit, int(wf.size)


def dates_from_ms(ts: np.ndarray, offset: int = 0) -> np.ndarray:
    return np.asarray(
        [datetime.fromtimestamp((int(v) + offset) / 1000, tz=UTC) for v in np.asarray(ts)]
    )


def page_executive(data: dict[str, object], digest: str) -> plt.Figure:
    report, books, raw = data["report"], data["books"], data["raw"]
    fig, ax = new_page("1 · Executive diagnostic overview", digest)
    p = report["primary"]
    ax[0].axis("off")
    status = [
        ("REGISTERED STATUS", p["verdict_status"]),
        ("BOT500 − E30", f"{p['delta_bp']:+.2f} bp / entry"),
        ("Crossed 95% CI", f"[{p['crossed_ci95'][0]:+.2f}, {p['crossed_ci95'][1]:+.2f}]"),
        (
            "MDE80 / +5 power",
            f"{p['crossed_mde80_bp']:.2f} bp / {100 * p['crossed_power_at_plus5']:.1f}%",
        ),
        ("Fold / coin signs", f"{p['folds_positive']}/8 • {p['coins_positive']}/4"),
        ("Top-5 abs contribution", f"{100 * p['concentration']['top5_abs_share']:.1f}%"),
        (
            "Observed +5 injection",
            f"CI [{p['injected_plus5']['crossed_ci95'][0]:+.2f}, "
            f"{p['injected_plus5']['crossed_ci95'][1]:+.2f}] FAIL",
        ),
        (
            "Favorable MDE / power",
            f"{p['missingness']['favorable_bound']['crossed_mde80_bp']:.2f}bp / "
            f"{100 * p['missingness']['favorable_bound']['crossed_power_at_plus5']:.1f}%",
        ),
        (
            "Favorable +5 injection",
            f"CI [{p['injected_plus5']['favorable_bound']['crossed_ci95'][0]:+.2f}, "
            f"{p['injected_plus5']['favorable_bound']['crossed_ci95'][1]:+.2f}] FAIL",
        ),
        (
            "May missingness",
            f"E30 {100 * report['books']['E30']['missingness']['per_fold']['202605']['rate']:.2f}% / "
            f"BOT {100 * report['books']['E_BOT500']['missingness']['per_fold']['202605']['rate']:.2f}% FAIL",
        ),
        ("Promotion / method-null", "FALSE / FALSE"),
        ("Consensus", "EXCLUDED"),
    ]
    for i, (label, value) in enumerate(status):
        y = 0.97 - i * 0.078
        ax[0].text(0.02, y, label, fontsize=6.8, color="#64748b", va="top")
        ax[0].text(
            0.43,
            y,
            value,
            fontsize=9.5 if i < 3 else 7.8,
            fontweight="bold",
            color="#b91c1c" if i == 0 else "#0f172a",
            va="top",
        )

    style_axis(
        ax[1],
        "Inference forest: observed and missing-outcome constructions",
        "Registered contrast • crossed wallet × fixed-7d bootstrap • net bp/entry",
    )
    rows = [
        ("Observed", p),
        ("Adverse", p["missingness"]["adverse_bound"]),
        ("Favorable", p["missingness"]["favorable_bound"]),
    ]
    for i, (_name, item) in enumerate(rows):
        lo, hi = item["crossed_ci95"]
        point = item["delta_bp"]
        ax[1].errorbar(point, i, xerr=[[point - lo], [hi - point]], fmt="o", capsize=4)
    ax[1].axvline(0, color="black", linewidth=1)
    ax[1].axvline(5, color="#16a34a", linestyle="--", label="+5bp care effect")
    ax[1].set_yticks(range(3), [r[0] for r in rows])
    ax[1].invert_yaxis()
    ax[1].set_xlabel("BOT500 − Standard (bp)")
    ax[1].legend(fontsize=8)

    style_axis(
        ax[2],
        "Estimator ladder exposes the weighting reversal",
        "Raw=gross; robust=arm-specific p95 winsor + wallet-fold equal; capacity=supported net",
    )
    categories = ["Raw equal-entry", "Raw robust WF", "Capacity book"]
    x = np.arange(3)
    width = 0.36
    robust = {}
    values = {}
    for arm in ARMS:
        robust[arm] = wallet_fold_robust(raw[arm])
        values[arm] = [
            float(raw[arm]["gross_bp"].mean()),
            robust[arm][0],
            float(books[arm]["net_bp"].mean()),
        ]
    for j, arm in enumerate(ARMS):
        ax[2].bar(x + (j - 0.5) * width, values[arm], width, color=COLORS[arm], label=DISPLAY[arm])
        for xi, yi in zip(x + (j - 0.5) * width, values[arm], strict=True):
            ax[2].text(
                xi, yi, f"{yi:.1f}", ha="center", va="bottom" if yi >= 0 else "top", fontsize=7
            )
    ax[2].axhline(0, color="black", linewidth=0.8)
    ax[2].set_xticks(x, categories)
    ax[2].set_ylabel("bp")
    ax[2].legend(fontsize=8)
    ax[2].text(
        0.01,
        0.02,
        f"Winsor limits: E30 ±{robust['E30'][1]:.1f}bp (nWF={robust['E30'][2]}), "
        f"BOT ±{robust['E_BOT500'][1]:.1f}bp (nWF={robust['E_BOT500'][2]})",
        transform=ax[2].transAxes,
        fontsize=7,
    )

    style_axis(
        ax[3],
        "Fold means: dependence and instability are visible",
        "Capacity-accepted, supported outcomes • net of 5.5bp • equal entry • descriptive folds",
    )
    folds = [str(f) for f in FOLDS]
    xx = np.arange(len(folds))
    for j, arm in enumerate(ARMS):
        vals = [report["books"][arm]["per_fold"][f] for f in folds]
        ax[3].bar(xx + (j - 0.5) * width, vals, width, color=COLORS[arm], label=DISPLAY[arm])
    ax[3].axhline(0, color="black", linewidth=0.8)
    ax[3].set_xticks(xx, [f[4:] for f in folds], rotation=45)
    ax[3].set_ylabel("net bp / entry")
    ax[3].legend(fontsize=8)

    style_axis(
        ax[4],
        "Chronological supported markout PnL and markout-path drawdown",
        "$5k entries • net 5.5bp • timestamp=signal+8h • missing omitted and counted elsewhere",
    )
    dd_ax = ax[4].twinx()
    for arm in ARMS:
        book = books[arm]
        order = np.argsort(book["ts"], kind="stable")
        pnl = book["net_bp"][order] * UNIT_USD / 1e4
        cum = np.r_[0.0, np.cumsum(pnl)]
        dates = np.r_[
            dates_from_ms(book["ts"][order], HOLD_MS)[0], dates_from_ms(book["ts"][order], HOLD_MS)
        ]
        drawdown = cum - np.maximum.accumulate(cum)
        missing = int(np.sum(~data["capacity"][arm]["supported"]))
        ax[4].plot(
            dates,
            cum,
            color=COLORS[arm],
            label=f"{DISPLAY[arm]} supported n={book['net_bp'].size}; missing accepted={missing}",
        )
        dd_ax.plot(dates, drawdown, color=COLORS[arm], alpha=0.22, linestyle="--")
    ax[4].set_ylabel("cumulative markout PnL ($)")
    dd_ax.set_ylabel("markout-path drawdown ($)", color="#64748b")
    ax[4].legend(fontsize=8, loc="upper left")

    style_axis(
        ax[5],
        "Paired fixed-7d contrast path",
        "Equal occupied calendar blocks anchored 2025-11-01 • cumulative block mean difference • not PnL",
    )
    anchor = month_ms(202511)[0]
    block_values = {}
    for arm in ARMS:
        book = books[arm]
        ids = ((book["ts"] - anchor) // (7 * DAY_MS)).astype(int)
        block_values[arm] = {i: float(book["net_bp"][ids == i].mean()) for i in np.unique(ids)}
    common = sorted(set(block_values["E30"]) & set(block_values["E_BOT500"]))
    delta = np.asarray([block_values["E_BOT500"][i] - block_values["E30"][i] for i in common])
    ax[5].plot(np.arange(1, len(common) + 1), np.cumsum(delta), color="#7c3aed", marker="o", ms=3)
    ax[5].axhline(0, color="black", linewidth=0.8)
    ax[5].set_xlabel("occupied fixed 7-day block")
    ax[5].set_ylabel("cumulative equal-block delta (bp)")
    ax[5].yaxis.set_label_position("right")
    ax[5].yaxis.tick_right()
    ax[5].text(
        0.01,
        0.03,
        f"n={len(common)} blocks • May missingness gate FAIL • injected +5 CI crosses zero",
        transform=ax[5].transAxes,
        fontsize=7,
        color="#b91c1c",
    )
    return fig


def page_returns(data: dict[str, object], digest: str) -> plt.Figure:
    books, raw = data["books"], data["raw"]
    fig, ax = new_page("2 · Returns, tails, and Gaussian-assumption diagnostics", digest)
    all_bp = np.concatenate([books[a]["net_bp"] for a in ARMS])
    lo, hi = np.percentile(all_bp, [0.5, 99.5])
    bins = np.linspace(lo, hi, 80)
    style_axis(
        ax[0],
        "Supported return distribution (central 99%)",
        "Capacity-supported rows • net 5.5bp • equal entry • common bins • overflow counted",
    )
    for arm in ARMS:
        bp = books[arm]["net_bp"]
        central = bp[(bp >= lo) & (bp <= hi)]
        ax[0].hist(
            central,
            bins=bins,
            density=True,
            alpha=0.42,
            color=COLORS[arm],
            label=DISPLAY[arm],
        )
        overflow = int(np.sum((bp < lo) | (bp > hi)))
        ax[0].text(
            0.98,
            0.90 - 0.08 * list(ARMS).index(arm),
            f"{DISPLAY[arm]} overflow={overflow}",
            transform=ax[0].transAxes,
            ha="right",
            fontsize=7,
            color=COLORS[arm],
        )
    ax[0].axvline(0, color="black", linewidth=0.8)
    ax[0].set_xlabel("net bp")
    ax[0].legend(fontsize=8)

    style_axis(
        ax[1],
        "Normal QQ: heavy tails and skew",
        "Capacity-supported net bp • standardized within arm • reference only, not a model test",
    )
    qlim = 0.0
    for arm in ARMS:
        q, y = qq_points(books[arm]["net_bp"])
        ax[1].plot(q, y, color=COLORS[arm], alpha=0.8, label=DISPLAY[arm])
        qlim = max(qlim, float(np.max(np.abs(np.r_[q, y]))))
    qlim = min(12.0, qlim)
    ax[1].plot([-qlim, qlim], [-qlim, qlim], color="black", linestyle="--", linewidth=0.8)
    ax[1].set_xlim(-4, 4)
    ax[1].set_xlabel("standard-normal quantile")
    ax[1].set_ylabel("standardized empirical quantile")
    ax[1].legend(fontsize=8)

    style_axis(
        ax[2],
        "Absolute-tail survival",
        "Capacity-supported net bp • equal entry • full finite tails • log-log axes",
    )
    for arm in ARMS:
        x, surv = empirical_survival_abs(books[arm]["net_bp"])
        keep = x > 0
        ax[2].loglog(x[keep], surv[keep], color=COLORS[arm], label=DISPLAY[arm])
    ax[2].set_xlabel("|net bp|")
    ax[2].set_ylabel("P(|return| ≥ x)")
    ax[2].legend(fontsize=8)

    style_axis(
        ax[3],
        "Absolute return-magnitude concentration",
        "Nonnegative mass=|supported net bp| • entries sorted largest first • not signed Lorenz",
    )
    for arm in ARMS:
        mass = np.sort(np.abs(books[arm]["net_bp"]))[::-1]
        share_x = np.arange(1, mass.size + 1) / mass.size
        share_y = np.cumsum(mass) / mass.sum()
        ax[3].plot(share_x, share_y, color=COLORS[arm], label=DISPLAY[arm])
    ax[3].plot([0, 1], [0, 1], color="black", linestyle="--", linewidth=0.7)
    ax[3].set_xlabel("fraction of entries, largest |return| first")
    ax[3].set_ylabel("fraction of total |net bp|")
    ax[3].legend(fontsize=8)

    style_axis(
        ax[4],
        "Raw candidate versus capacity-supported signed quantiles",
        "Both gross bp • all finite rows/tails retained • solid=raw selected; dashed=capacity-supported",
    )
    for arm in ARMS:
        for values, linestyle, label in (
            (raw[arm]["gross_bp"], "-", f"{DISPLAY[arm]} raw"),
            (books[arm]["net_bp"] + COST_BP, "--", f"{DISPLAY[arm]} capacity"),
        ):
            y = np.sort(values)
            q = (np.arange(y.size) + 0.5) / y.size
            ax[4].plot(q, y, color=COLORS[arm], linestyle=linestyle, alpha=0.8, label=label)
    ax[4].axhline(0, color="black", linewidth=0.8)
    ax[4].set_yscale("symlog", linthresh=100)
    ax[4].set_xlabel("empirical quantile")
    ax[4].set_ylabel("gross bp (symlog; full signed tails)")
    ax[4].legend(fontsize=6.8, ncol=2)

    slot = ax[5].get_subplotspec()
    ax[5].remove()
    sub = slot.subgridspec(1, 2, wspace=0.34)
    fold_ax, coin_ax = fig.add_subplot(sub[0, 0]), fig.add_subplot(sub[0, 1])
    for target, groups, title in (
        (fold_ax, FOLDS, "Fold distributions"),
        (coin_ax, COINS, "Coin distributions"),
    ):
        style_axis(
            target,
            title,
            "Supported net bp • equal entry • fliers hidden here; full tails above",
        )
        positions, arrays, colors, tick_pos, tick_labels = [], [], [], [], []
        pos = 1
        for group in groups:
            tick_pos.append(pos + 0.5)
            tick_labels.append(str(group)[4:] if isinstance(group, int) else str(group))
            for arm in ARMS:
                field = "fold" if isinstance(group, int) else "coin"
                m = books[arm][field] == group
                positions.append(pos)
                arrays.append(books[arm]["net_bp"][m])
                colors.append(COLORS[arm])
                pos += 1
            pos += 1
        bp2 = target.boxplot(
            arrays,
            positions=positions,
            widths=0.72,
            showfliers=False,
            patch_artist=True,
        )
        for patch_box, color in zip(bp2["boxes"], colors, strict=True):
            patch_box.set_facecolor(color)
            patch_box.set_alpha(0.48)
        target.set_xticks(tick_pos, tick_labels, rotation=45)
        target.axhline(0, color="black", linewidth=0.8)
        target.set_ylabel("net bp")
    return fig


def pooled_cohort(data: dict[str, object]) -> dict[str, np.ndarray]:
    cohorts = data["cohorts"]
    keys = (
        "wallet",
        "nd",
        "sd",
        "mean_x",
        "t",
        "z",
        "fpd",
        "eligible",
        "coin_share",
        "n_liq",
        "n_open",
    )
    return {k: np.concatenate([np.asarray(cohorts[str(f)][k]) for f in FOLDS]) for k in keys}


def selected_cohort_rows(data: dict[str, object], arm: str) -> dict[str, np.ndarray]:
    values: dict[str, list[np.ndarray]] = {
        k: [] for k in ("wallet", "fold", "nd", "t", "z", "fpd", "mean_x", "sd", "coin_share")
    }
    for fold in FOLDS:
        key = str(fold)
        cohort = data["cohorts"][key]
        wallets = np.asarray(cohort["wallet"])
        members = data["rosters"]["folds"][key]["rosters"][arm]
        idx = np.searchsorted(wallets, members)
        if np.any(idx >= wallets.size) or not np.array_equal(wallets[idx], members):
            raise RuntimeError(f"fold {fold}/{arm}: selected wallet missing from cohort")
        values["wallet"].append(wallets[idx])
        values["fold"].append(np.full(TOP_K, fold))
        for name in ("nd", "t", "z", "fpd", "mean_x", "sd", "coin_share"):
            values[name].append(np.asarray(cohort[name])[idx])
    return {k: np.concatenate(v) for k, v in values.items()}


def page_cohort(data: dict[str, object], digest: str) -> plt.Figure:
    pooled = pooled_cohort(data)
    selected = {arm: selected_cohort_rows(data, arm) for arm in ARMS}
    eligible = pooled["eligible"].astype(bool)
    fig, ax = new_page("3 · Full formation cohort and selection geometry", digest)
    folds = [str(f) for f in FOLDS]
    xx = np.arange(len(folds))
    eligible_n = np.asarray([data["rosters"]["folds"][f]["n_eligible"] for f in folds])
    excluded_n = np.asarray([data["rosters"]["folds"][f]["n_excluded_gt500"] for f in folds])
    style_axis(
        ax[0],
        "Eligible pool and BOT500 exclusions",
        "Formation-only wallet-days • ordinary t eligibility • counts",
    )
    ax[0].bar(xx, eligible_n, color="#cbd5e1", label="eligible")
    ax[0].bar(xx, excluded_n, color="#ef4444", label=">500 excluded")
    ax[0].set_xticks(xx, [f[4:] for f in folds], rotation=45)
    ax[0].set_ylabel("wallet-folds")
    ax[0].legend(fontsize=8)

    style_axis(
        ax[1],
        "Formation fills/day distribution",
        "All eligible wallet-folds • all-coin activity • log x • fixed threshold",
    )
    fpd = pooled["fpd"][eligible]
    bins = np.logspace(np.log10(max(fpd.min(), 0.1)), np.log10(fpd.max()), 90)
    ax[1].hist(fpd, bins=bins, color="#64748b", alpha=0.75)
    ax[1].axvline(BOT_MAX, color="#ef4444", linestyle="--", label="500 fills/day")
    ax[1].set_xscale("log")
    ax[1].set_xlabel("all-coin fills / active day")
    ax[1].set_ylabel("eligible wallet-fold count")
    ax[1].legend(fontsize=8)

    style_axis(
        ax[2],
        "Ordinary active-day t-stat distribution",
        "All eligible wallet-folds • $100k-turnover-normalized daily PnL • central 99.5% shown",
    )
    t = pooled["t"][eligible]
    lim = np.percentile(np.abs(t), 99.5)
    central_t = t[np.abs(t) <= lim]
    ax[2].hist(central_t, bins=100, color="#334155", alpha=0.78)
    ax[2].axvline(0, color="black", linewidth=0.8)
    ax[2].set_xlabel("formation t-stat (out-of-range omitted and counted)")
    ax[2].text(
        0.98,
        0.92,
        f"overflow={np.sum(np.abs(t) > lim)}",
        transform=ax[2].transAxes,
        ha="right",
        fontsize=7,
    )

    style_axis(
        ax[3],
        "Activity versus formation t-stat",
        "All eligible wallet-folds hexbin; top-30 overlays • log fills/day • display t clipped ±12",
    )
    show_t = np.abs(t) <= 12
    ax[3].hexbin(
        np.log10(fpd[show_t]),
        t[show_t],
        gridsize=70,
        bins="log",
        cmap="Greys",
        mincnt=1,
    )
    for arm in ARMS:
        ax[3].scatter(
            np.log10(selected[arm]["fpd"]),
            selected[arm]["t"],
            s=12,
            alpha=0.5,
            color=COLORS[arm],
            label=DISPLAY[arm],
        )
    ax[3].axvline(np.log10(BOT_MAX), color="#ef4444", linestyle="--")
    ax[3].set_xlabel("log10(all-coin fills/day)")
    ax[3].set_ylabel("formation t-stat")
    ax[3].set_ylim(-12, 12)
    ax[3].legend(fontsize=7)

    style_axis(
        ax[4],
        "Active days versus formation t-stat",
        "All eligible wallet-folds hexbin • selected overlays • t clipped ±12",
    )
    ax[4].hexbin(
        pooled["nd"][eligible][show_t],
        t[show_t],
        gridsize=70,
        bins="log",
        cmap="Greys",
        mincnt=1,
    )
    for arm in ARMS:
        ax[4].scatter(
            selected[arm]["nd"],
            selected[arm]["t"],
            s=12,
            alpha=0.5,
            color=COLORS[arm],
        )
    ax[4].set_xlabel("active formation days")
    ax[4].set_ylabel("formation t-stat")
    ax[4].set_ylim(-12, 12)

    slot = ax[5].get_subplotspec()
    ax[5].remove()
    sub = slot.subgridspec(1, 2, wspace=0.36)
    geom_ax, mix_ax = fig.add_subplot(sub[0, 0]), fig.add_subplot(sub[0, 1])
    style_axis(
        geom_ax,
        "Mean–volatility geometry",
        "Eligible wallet-folds • x=log10 SD • y=signed log10(1+|mean|)",
    )
    eligible_mean = pooled["mean_x"][eligible]
    geom_ax.hexbin(
        np.log10(pooled["sd"][eligible]),
        np.sign(eligible_mean) * np.log10(1.0 + np.abs(eligible_mean)),
        gridsize=65,
        bins="log",
        cmap="Greys",
        mincnt=1,
    )
    for arm in ARMS:
        selected_mean = selected[arm]["mean_x"]
        geom_ax.scatter(
            np.log10(selected[arm]["sd"]),
            np.sign(selected_mean) * np.log10(1.0 + np.abs(selected_mean)),
            s=12,
            alpha=0.5,
            color=COLORS[arm],
        )
    geom_ax.set_xlabel("log10 SD turnover-normalized PnL ($)")
    geom_ax.set_ylabel("signed log10(1+|mean PnL|)")
    style_axis(
        mix_ax,
        "Full-cohort formation mix",
        "Mean wallet major-notional share • equal eligible wallet-fold • full vs <=500 pool",
    )
    masks = [eligible, eligible & (pooled["fpd"] <= BOT_MAX)]
    bottom = np.zeros(2)
    coin_colors = ["#f59e0b", "#3b82f6", "#22c55e", "#a855f7"]
    for j, coin in enumerate(COINS):
        vals = [float(pooled["coin_share"][mask, j].mean()) for mask in masks]
        mix_ax.bar(np.arange(2), vals, bottom=bottom, color=coin_colors[j], label=coin)
        bottom += vals
    mix_ax.set_xticks(np.arange(2), ["Full eligible", "≤500 pool"], rotation=20)
    mix_ax.set_ylabel("mean formation notional share")
    mix_ax.legend(fontsize=6, ncol=2)
    return fig


def normal_survival(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    return np.asarray([0.5 * math.erfc((float(v) - mu) / (sigma * math.sqrt(2))) for v in x])


def page_efron(data: dict[str, object], digest: str) -> plt.Figure:
    rosters, cohorts = data["rosters"], data["cohorts"]
    fig, ax = new_page("4 · Efron empirical-null and selector-assumption diagnostics", digest)
    fig.subplots_adjust(wspace=0.30)
    fold = "202511"
    cohort = cohorts[fold]
    eligible = np.asarray(cohort["eligible"], bool)
    bot = eligible & (np.asarray(cohort["fpd"]) <= BOT_MAX)
    z_all = np.asarray(cohort["z"])[eligible]
    z_bot = np.asarray(cohort["z"])[bot]
    fit_all = rosters["folds"][fold]["fit_E30"]
    fit_bot = rosters["folds"][fold]["fit_E_BOT500"]
    style_axis(
        ax[0],
        "November z and frozen-null overlay",
        "Formation eligible wallets • exact Student-t→z • density • no probability-calibration claim",
    )
    bins = np.linspace(-8.0001, 8.0001, 100)
    ax[0].hist(z_all, bins=bins, density=True, color=COLORS["E30"], alpha=0.25, label="E30 pool")
    ax[0].hist(
        z_bot,
        bins=bins,
        density=True,
        histtype="step",
        linewidth=1.2,
        color=COLORS["E_BOT500"],
        label="BOT500 pool",
    )
    grid = np.linspace(-8, 8, 500)
    ax[0].plot(grid, normal_pdf(grid), color="black", linestyle="--", label="N(0,1)")
    ax[0].plot(
        grid,
        fit_all["pi0"] * normal_pdf(grid, fit_all["mu0"], fit_all["sigma0"]),
        color=COLORS["E30"],
        linewidth=2,
        label="frozen E30 π0-weighted null component",
    )
    ax[0].plot(
        grid,
        fit_bot["pi0"] * normal_pdf(grid, fit_bot["mu0"], fit_bot["sigma0"]),
        color=COLORS["E_BOT500"],
        linewidth=2,
        label="frozen BOT π0-weighted null component",
    )
    ax[0].set_xlabel("formation z")
    ax[0].legend(fontsize=7)

    style_axis(
        ax[1],
        "Positive-tail survival vs null",
        "November formation pool • empirical survival and frozen empirical-null survival • log y",
    )
    for arm, z, fit in (("E30", z_all, fit_all), ("E_BOT500", z_bot, fit_bot)):
        x = np.linspace(0, np.max(z), 140)
        emp = np.asarray([np.mean(z >= v) for v in x])
        null = fit["pi0"] * normal_survival(x, fit["mu0"], fit["sigma0"])
        ax[1].semilogy(x, emp, color=COLORS[arm], label=f"{DISPLAY[arm]} empirical")
        ax[1].semilogy(
            x, null, color=COLORS[arm], linestyle="--", alpha=0.7, label=f"{DISPLAY[arm]} null"
        )
    ax[1].set_xlabel("z threshold")
    ax[1].set_ylabel("survival probability")
    ax[1].legend(fontsize=6.8, ncol=2)

    style_axis(
        ax[2],
        "Empirical-null location and width through folds",
        "Saved fit parameters only • no renderer refit • formation cross-section",
    )
    xx = np.arange(len(FOLDS))
    for arm, fit_key in (("E30", "fit_E30"), ("E_BOT500", "fit_E_BOT500")):
        mu = [rosters["folds"][str(f)][fit_key]["mu0"] for f in FOLDS]
        sigma = [rosters["folds"][str(f)][fit_key]["sigma0"] for f in FOLDS]
        ax[2].plot(xx, mu, marker="o", color=COLORS[arm], label=f"{DISPLAY[arm]} μ0")
        ax[2].plot(
            xx, sigma, marker="s", linestyle="--", color=COLORS[arm], label=f"{DISPLAY[arm]} σ0"
        )
    ax[2].axhline(0, color="black", linewidth=0.6)
    ax[2].axhline(1, color="black", linewidth=0.6, linestyle="--")
    ax[2].set_xticks(xx, [str(f)[4:] for f in FOLDS], rotation=45)
    ax[2].legend(fontsize=7, ncol=2)

    style_axis(
        ax[3],
        "Estimated null mass and excluded population",
        "Saved pi0 plus deterministic >500 rate • descriptive fold series",
    )
    rate_ax = ax[3].twinx()
    for arm, fit_key in (("E30", "fit_E30"), ("E_BOT500", "fit_E_BOT500")):
        pi0 = [rosters["folds"][str(f)][fit_key]["pi0"] for f in FOLDS]
        ax[3].plot(xx, pi0, marker="o", color=COLORS[arm], label=f"{DISPLAY[arm]} π0")
    excluded = [
        rosters["folds"][str(f)]["n_excluded_gt500"] / rosters["folds"][str(f)]["n_eligible"]
        for f in FOLDS
    ]
    rate_ax.bar(xx, np.asarray(excluded) * 100, alpha=0.16, color="#ef4444", label="excluded %")
    ax[3].set_xticks(xx, [str(f)[4:] for f in FOLDS], rotation=45)
    ax[3].set_ylabel("pi0")
    rate_ax.set_ylabel("excluded (%)")
    ax[3].legend(fontsize=7, loc="upper left")

    slot = ax[4].get_subplotspec()
    ax[4].remove()
    sub = slot.subgridspec(1, 2, wspace=0.36)
    z_ax, rank_ax = fig.add_subplot(sub[0, 0]), fig.add_subplot(sub[0, 1])
    style_axis(
        z_ax,
        "Stored-rank z coordinates",
        "Stored top-30 • frozen formation z • all folds",
    )
    selected = {arm: selected_cohort_rows(data, arm) for arm in ARMS}
    for arm in ARMS:
        ranks = np.tile(np.arange(1, TOP_K + 1), len(FOLDS))
        z_ax.scatter(
            ranks, selected[arm]["z"], s=10, alpha=0.42, color=COLORS[arm], label=DISPLAY[arm]
        )
    z_ax.set_xlabel("stored rank")
    z_ax.set_ylabel("formation z")
    z_ax.legend(fontsize=6)
    style_axis(
        rank_ax,
        "Shared-wallet rank shifts",
        "Shared selected wallet-folds • stored ranks only",
    )
    fold_colors = plt.cm.viridis(np.linspace(0.05, 0.95, len(FOLDS)))
    for color, fold_value in zip(fold_colors, FOLDS, strict=True):
        item = rosters["folds"][str(fold_value)]["rosters"]
        e_rank = {w: i + 1 for i, w in enumerate(item["E30"])}
        b_rank = {w: i + 1 for i, w in enumerate(item["E_BOT500"])}
        shared = sorted(set(e_rank) & set(b_rank))
        rank_ax.scatter(
            [e_rank[w] for w in shared],
            [b_rank[w] for w in shared],
            s=11,
            alpha=0.55,
            color=color,
        )
    rank_ax.plot([1, 30], [1, 30], color="black", linestyle="--", linewidth=0.7)
    rank_ax.set_xlabel("E30 stored rank")
    rank_ax.set_ylabel("BOT500 stored rank")

    style_axis(
        ax[5],
        "Within-wallet active-day dependence",
        "Wallet-mean-centered daily PnL • pooled lag-1 • iid diagnostic",
    )
    lag = [float(cohorts[str(f)]["lag_corr"]) for f in FOLDS]
    ax[5].bar(xx, lag, color="#7c3aed", alpha=0.75)
    ax[5].axhline(0, color="black", linewidth=0.8)
    ax[5].set_xticks(xx, [str(f)[4:] for f in FOLDS], rotation=45)
    ax[5].set_ylabel("pooled within-wallet lag-1 correlation")
    ax[5].text(
        0.01,
        0.03,
        "Empirical null repairs cross-sectional shape; it does not make daily PnL iid/Gaussian.",
        transform=ax[5].transAxes,
        fontsize=7,
        color="#b91c1c",
    )
    return fig


def page_roster(data: dict[str, object], digest: str) -> plt.Figure:
    rosters = data["rosters"]
    selected = {arm: selected_cohort_rows(data, arm) for arm in ARMS}
    fig, ax = new_page("5 · Roster dynamics and cohort composition", digest)
    all_wallets = sorted(
        {w for f in FOLDS for arm in ARMS for w in rosters["folds"][str(f)]["rosters"][arm]}
    )
    frequency = Counter(
        w for f in FOLDS for arm in ARMS for w in rosters["folds"][str(f)]["rosters"][arm]
    )
    ordered = sorted(all_wallets, key=lambda w: (-frequency[w], w))
    matrix = np.zeros((len(ordered), len(FOLDS)), dtype=int)
    for j, fold in enumerate(FOLDS):
        e = set(rosters["folds"][str(fold)]["rosters"]["E30"])
        b = set(rosters["folds"][str(fold)]["rosters"]["E_BOT500"])
        for i, wallet in enumerate(ordered):
            matrix[i, j] = (1 if wallet in e else 0) + (2 if wallet in b else 0)
    style_axis(
        ax[0],
        "Wallet × fold membership map",
        "All selected wallets • 0 absent / blue E30 / orange BOT / purple both • rows sorted persistence",
    )
    cmap = ListedColormap(["#ffffff", COLORS["E30"], COLORS["E_BOT500"], "#7c3aed"])
    ax[0].imshow(matrix, aspect="auto", interpolation="nearest", cmap=cmap, vmin=0, vmax=3)
    ax[0].set_xticks(np.arange(len(FOLDS)), [str(f)[4:] for f in FOLDS], rotation=45)
    ax[0].set_ylabel(f"{len(ordered)} unique selected wallets")
    if DOMINANT_WALLET in ordered:
        ax[0].axhline(ordered.index(DOMINANT_WALLET), color="#ef4444", linewidth=1.5)

    style_axis(
        ax[1],
        "Same-fold E30/BOT roster overlap",
        "Stored top-30 membership • overlap out of 30 • no full-pool refit ranks",
    )
    overlap = np.asarray([rosters["folds"][str(f)]["overlap"] for f in FOLDS])
    ax[1].bar(np.arange(len(FOLDS)), overlap, color="#7c3aed")
    ax[1].set_ylim(0, 30)
    ax[1].set_xticks(np.arange(len(FOLDS)), [str(f)[4:] for f in FOLDS], rotation=45)
    ax[1].set_ylabel("shared wallets / 30")

    style_axis(
        ax[2],
        "Selected activity by fold",
        "Formation selected wallet-folds • all-coin fills/active-day • log y • equal wallet-fold",
    )
    positions, arrays, colors = [], [], []
    pos = 1
    for fold in FOLDS:
        for arm in ARMS:
            m = selected[arm]["fold"] == fold
            positions.append(pos)
            arrays.append(selected[arm]["fpd"][m])
            colors.append(COLORS[arm])
            pos += 1
        pos += 1
    bp = ax[2].boxplot(arrays, positions=positions, showfliers=True, widths=0.7, patch_artist=True)
    for patch_box, color in zip(bp["boxes"], colors, strict=True):
        patch_box.set_facecolor(color)
        patch_box.set_alpha(0.45)
    ax[2].axhline(BOT_MAX, color="#ef4444", linestyle="--")
    ax[2].set_yscale("log")
    ax[2].set_xticks(np.arange(1.5, pos, 3), [str(f)[4:] for f in FOLDS], rotation=45)
    ax[2].set_ylabel("fills/day")

    style_axis(
        ax[3],
        "Selected formation t-stat and active days",
        "Top-30 wallet-folds • x=active days, y=t • equal selected wallet-fold",
    )
    for arm in ARMS:
        ax[3].scatter(
            selected[arm]["nd"],
            selected[arm]["t"],
            s=18,
            alpha=0.55,
            color=COLORS[arm],
            label=DISPLAY[arm],
        )
    ax[3].set_xlabel("active formation days")
    ax[3].set_ylabel("formation t-stat")
    ax[3].legend(fontsize=7)

    style_axis(
        ax[4],
        "Selected formation notional mix",
        "Top-30 wallet-folds • mean wallet formation share • equal wallet-fold • descriptive",
    )
    bottom = np.zeros(2)
    x = np.arange(2)
    coin_colors = ["#f59e0b", "#3b82f6", "#22c55e", "#a855f7"]
    for j, coin in enumerate(COINS):
        vals = [selected[arm]["coin_share"][:, j].mean() for arm in ARMS]
        ax[4].bar(x, vals, bottom=bottom, color=coin_colors[j], label=coin)
        bottom += vals
    ax[4].set_xticks(x, [DISPLAY[a] for a in ARMS])
    ax[4].set_ylabel("mean formation notional share")
    ax[4].legend(fontsize=7, ncol=4)

    style_axis(
        ax[5],
        "Registered November dominant wallet",
        "Mechanically pre-registered diagnostic • formation fills/day and stored membership • not a new anecdote",
    )
    fpd_vals, labels, codes = [], [], []
    for fold in FOLDS:
        key = str(fold)
        cohort = data["cohorts"][key]
        wallets = np.asarray(cohort["wallet"])
        idx = np.searchsorted(wallets, DOMINANT_WALLET)
        if idx < wallets.size and wallets[idx] == DOMINANT_WALLET:
            fpd_vals.append(float(np.asarray(cohort["fpd"])[idx]))
        else:
            fpd_vals.append(math.nan)
        e = DOMINANT_WALLET in rosters["folds"][key]["rosters"]["E30"]
        b = DOMINANT_WALLET in rosters["folds"][key]["rosters"]["E_BOT500"]
        codes.append((1 if e else 0) + (2 if b else 0))
        labels.append(key[4:])
    ax[5].bar(np.arange(len(FOLDS)), np.nan_to_num(fpd_vals), color=[cmap(c / 3) for c in codes])
    ax[5].axhline(BOT_MAX, color="#ef4444", linestyle="--", label="500 cutoff")
    ax[5].set_xticks(np.arange(len(FOLDS)), labels, rotation=45)
    ax[5].set_ylabel("formation fills/day")
    ax[5].legend(fontsize=7)
    ax[5].text(
        0.02,
        0.92,
        "Nov: 116.75 fills/day • E30 rank 2 • BOT rank 1",
        transform=ax[5].transAxes,
        fontsize=8,
        fontweight="bold",
    )
    contribution = np.asarray(data["contrib"]["delta"])
    contribution_wallets = np.asarray(data["contrib"]["wallet"])
    top5 = np.argsort(np.abs(contribution))[::-1][:5]
    top5_text = "Top-5 |contrast| contributors:\n" + "  ".join(
        f"{contribution_wallets[i][:6]}…{contribution_wallets[i][-4:]} {contribution[i]:+.1f}bp"
        for i in top5
    )
    ax[5].text(
        0.02,
        0.73,
        top5_text,
        transform=ax[5].transAxes,
        fontsize=5.8,
        color="#475569",
        va="top",
        wrap=True,
    )
    return fig


def page_execution(data: dict[str, object], digest: str) -> plt.Figure:
    report, capacity, funnels = data["report"], data["capacity"], data["funnels"]
    fig, ax = new_page("6 · Execution capacity, timing, and missing outcomes", digest)
    fig.subplots_adjust(wspace=0.34)
    xx = np.arange(len(FOLDS))
    width = 0.36
    style_axis(
        ax[0],
        "Candidate → accepted capacity funnel",
        "Selected entry candidates • global chronological capacity • counts by signal fold",
    )
    for j, arm in enumerate(ARMS):
        candidates = np.asarray([funnels[arm][str(f)]["n_candidates"] for f in FOLDS])
        accepted = np.asarray([funnels[arm][str(f)]["n_accepted_capacity"] for f in FOLDS])
        ax[0].bar(xx + (j - 0.5) * width, candidates, width, color=COLORS[arm], alpha=0.20)
        ax[0].bar(
            xx + (j - 0.5) * width,
            accepted,
            width,
            color=COLORS[arm],
            label=f"{DISPLAY[arm]} accepted",
        )
    ax[0].set_xticks(xx, [str(f)[4:] for f in FOLDS], rotation=45)
    ax[0].set_ylabel("rows (pale=candidates, solid=accepted)")
    ax[0].legend(fontsize=7)

    style_axis(
        ax[1],
        "Capacity acceptance and wallet×coin skips",
        "Candidates and accepted include unsupported outcomes • global state carries across folds",
    )
    acceptance_rates = {}
    for arm in ARMS:
        cand = np.asarray([funnels[arm][str(f)]["n_candidates"] for f in FOLDS])
        acc = np.asarray([funnels[arm][str(f)]["n_accepted_capacity"] for f in FOLDS])
        skip = np.asarray([funnels[arm][str(f)]["n_skip_wallet_coin"] for f in FOLDS])
        skip_coin = np.asarray([funnels[arm][str(f)]["n_skip_coin_cap"] for f in FOLDS])
        acceptance_rates[arm] = acc / cand * 100
        ax[1].plot(
            xx, acc / cand * 100, marker="o", color=COLORS[arm], label=f"{DISPLAY[arm]} accept"
        )
        ax[1].plot(
            xx,
            skip / cand * 100,
            linestyle="--",
            color=COLORS[arm],
            alpha=0.7,
            label=f"{DISPLAY[arm]} WC skip",
        )
        ax[1].plot(
            xx,
            skip_coin / cand * 100,
            linestyle=":",
            color=COLORS[arm],
            alpha=0.8,
            label=f"{DISPLAY[arm]} coin-cap skip",
        )
    ax[1].plot(
        xx,
        acceptance_rates["E_BOT500"] - acceptance_rates["E30"],
        color="#7c3aed",
        marker="D",
        linewidth=1.2,
        label="BOT−E30 accept-rate pp",
    )
    ax[1].set_xticks(xx, [str(f)[4:] for f in FOLDS], rotation=45)
    ax[1].set_ylabel("percent of candidates")
    ax[1].legend(fontsize=6.8, ncol=2)

    style_axis(
        ax[2],
        "Missingness by fold (supported/missing)",
        "Capacity-accepted rows • color=missing rate • text=supported/missing • May >2% gate",
    )
    fold_rates = np.zeros((2, len(FOLDS)))
    fold_counts = []
    for i, arm in enumerate(ARMS):
        strata = report["books"][arm]["missingness"]["per_fold"]
        cells = [strata[str(f)] for f in FOLDS]
        fold_rates[i] = [cell["rate"] * 100 for cell in cells]
        fold_counts.append(cells)
    image = ax[2].imshow(fold_rates, aspect="auto", cmap="Reds", vmin=0)
    fold_dark = 0.60 * float(np.max(fold_rates))
    for i in range(2):
        for j in range(len(FOLDS)):
            cell = fold_counts[i][j]
            ax[2].text(
                j,
                i,
                f"{cell['accepted'] - cell['missing']}/{cell['missing']}",
                ha="center",
                va="center",
                fontsize=6.3,
                color="white" if fold_rates[i, j] >= fold_dark else "black",
            )
    ax[2].set_xticks(xx, [str(f)[4:] for f in FOLDS], rotation=45)
    ax[2].set_yticks(np.arange(2), [DISPLAY[a] for a in ARMS])
    fig.colorbar(image, ax=ax[2], fraction=0.025, pad=0.02, label="missing (%)")

    style_axis(
        ax[3],
        "Missingness by coin (supported/missing)",
        "Capacity-accepted rows • color=missing rate • text=supported/missing • descriptive coins",
    )
    coin_rates = np.zeros((2, len(COINS)))
    coin_counts = []
    for i, arm in enumerate(ARMS):
        strata = report["books"][arm]["missingness"]["by_coin"]
        cells = [strata[c] for c in COINS]
        coin_rates[i] = [cell["rate"] * 100 for cell in cells]
        coin_counts.append(cells)
    image2 = ax[3].imshow(coin_rates, aspect="auto", cmap="Reds", vmin=0)
    coin_dark = 0.60 * float(np.max(coin_rates))
    for i in range(2):
        for j in range(len(COINS)):
            cell = coin_counts[i][j]
            ax[3].text(
                j,
                i,
                f"{cell['accepted'] - cell['missing']}/{cell['missing']}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if coin_rates[i, j] >= coin_dark else "black",
            )
    ax[3].set_xticks(np.arange(len(COINS)), COINS)
    ax[3].set_yticks(np.arange(2), [DISPLAY[a] for a in ARMS])
    fig.colorbar(image2, ax=ax[3], fraction=0.025, pad=0.02, label="missing (%)")

    slot = ax[4].get_subplotspec()
    ax[4].remove()
    sub = slot.subgridspec(1, 2, wspace=0.48)
    hour_ax, dow_ax = fig.add_subplot(sub[0, 0]), fig.add_subplot(sub[0, 1])
    style_axis(
        hour_ax,
        "Accepted UTC-hour mix",
        "Capacity-accepted incl missing • UTC hour • equal row",
    )
    hours = np.arange(24)
    for arm in ARMS:
        ts = capacity[arm]["ts"]
        h = ((ts // 3_600_000) % 24).astype(int)
        counts = np.bincount(h, minlength=24)
        hour_ax.plot(
            hours,
            counts / counts.sum() * 100,
            color=COLORS[arm],
            marker="o",
            ms=3,
            label=DISPLAY[arm],
        )
    hour_ax.set_xlabel("UTC hour")
    hour_ax.set_ylabel("accepted rows (%)")
    hour_ax.set_xticks(np.arange(0, 24, 4))
    hour_ax.legend(fontsize=6)
    style_axis(
        dow_ax,
        "Accepted weekday mix",
        "Capacity-accepted incl missing • UTC weekday • equal row",
    )
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for arm in ARMS:
        dow = np.asarray(
            [datetime.fromtimestamp(int(v) / 1000, tz=UTC).weekday() for v in capacity[arm]["ts"]]
        )
        counts = np.bincount(dow, minlength=7)
        dow_ax.plot(
            np.arange(7),
            counts / counts.sum() * 100,
            color=COLORS[arm],
            marker="o",
            ms=3,
            label=DISPLAY[arm],
        )
    dow_ax.set_xticks(np.arange(7), weekdays, rotation=45)
    dow_ax.set_ylabel("accepted rows (%)")
    dow_ax.legend(fontsize=6)

    style_axis(
        ax[5],
        "Accepted coin × direction mix",
        "All capacity-accepted rows incl missing • count share • direction=taker wallet trade direction",
    )
    labels = [f"{c} L" for c in COINS] + [f"{c} S" for c in COINS]
    x = np.arange(len(labels))
    for j, arm in enumerate(ARMS):
        cap = capacity[arm]
        counts = []
        for sign in (1, -1):
            for coin in COINS:
                counts.append(int(np.sum((cap["coin"] == coin) & (cap["dir_sign"] == sign))))
        values = np.asarray(counts) / max(np.sum(counts), 1) * 100
        ax[5].bar(x + (j - 0.5) * width, values, width, color=COLORS[arm], label=DISPLAY[arm])
    ax[5].set_xticks(x, labels, rotation=45)
    ax[5].set_ylabel("accepted rows (%)")
    ax[5].legend(fontsize=7)
    return fig


def page_wallets(data: dict[str, object], digest: str) -> plt.Figure:
    books, contrib = data["books"], data["contrib"]
    fig, ax = new_page("7 · Wallet dependence, contribution concentration, and sensitivity", digest)
    style_axis(
        ax[0],
        "Wallet mean return versus sample size",
        "Capacity-supported net bp • one point per wallet/arm • x log entries • size shown explicitly",
    )
    wallet_stats = {}
    for arm in ARMS:
        book = books[arm]
        wallets, inv, counts = np.unique(book["wallet"], return_inverse=True, return_counts=True)
        means = np.bincount(inv, weights=book["net_bp"]) / counts
        wallet_stats[arm] = {"wallet": wallets, "count": counts, "mean": means}
        ax[0].scatter(
            counts,
            means,
            s=14 + np.sqrt(counts) * 2,
            alpha=0.5,
            color=COLORS[arm],
            label=DISPLAY[arm],
        )
    ax[0].set_xscale("log")
    ax[0].axhline(0, color="black", linewidth=0.8)
    ax[0].set_xlabel("supported entries per wallet (log)")
    ax[0].set_ylabel("wallet mean net bp")
    ax[0].legend(fontsize=7)

    delta = np.asarray(contrib["delta"])
    wallets = np.asarray(contrib["wallet"])
    order = np.argsort(np.abs(delta))[::-1]
    top = order[:20]
    style_axis(
        ax[1],
        "Largest exact wallet contrast contributions",
        "Contribution to arm mean difference • original denominators • mechanically top |contribution| wallets",
    )
    labels = [wallets[i][:6] + "…" + wallets[i][-4:] for i in top][::-1]
    vals = delta[top][::-1]
    ax[1].barh(np.arange(len(top)), vals, color=["#16a34a" if v > 0 else "#dc2626" for v in vals])
    ax[1].set_yticks(np.arange(len(top)), labels, fontsize=6)
    ax[1].axvline(0, color="black", linewidth=0.8)
    ax[1].set_xlabel("BOT500 − E30 contribution (bp)")

    style_axis(
        ax[2],
        "Absolute wallet-contribution concentration",
        "Nonnegative mass=|exact wallet contrast contribution| • wallets largest first",
    )
    mass = np.abs(delta[order])
    ax[2].plot(
        np.arange(1, mass.size + 1) / mass.size, np.cumsum(mass) / mass.sum(), color="#7c3aed"
    )
    ax[2].axhline(0.5, color="#ef4444", linestyle="--")
    ax[2].axvline(5 / mass.size, color="#ef4444", linestyle="--")
    ax[2].set_xlabel("fraction of contributing wallets")
    ax[2].set_ylabel("fraction of |contrast contribution|")
    ax[2].text(
        0.55,
        0.15,
        f"top 5 = {100 * data['report']['primary']['concentration']['top5_abs_share']:.1f}%",
        transform=ax[2].transAxes,
        fontsize=9,
        color="#b91c1c",
    )

    style_axis(
        ax[3],
        "Leave-k largest contributors sensitivity",
        "Rank once by original |contribution| • remove same wallets both arms • re-denominate means • post-hoc descriptive",
    )
    ks = np.arange(0, min(25, wallets.size) + 1)
    residual = []
    for k in ks:
        remove = set(wallets[order[:k]])
        means = []
        for arm in ("E_BOT500", "E30"):
            keep = np.asarray([w not in remove for w in books[arm]["wallet"]])
            means.append(float(books[arm]["net_bp"][keep].mean()) if keep.any() else math.nan)
        residual.append(means[0] - means[1])
    ax[3].plot(ks, residual, color="#7c3aed", marker="o", ms=3)
    ax[3].axhline(0, color="black", linewidth=0.8)
    ax[3].set_xlabel("largest |contribution| wallets removed")
    ax[3].set_ylabel("re-denominated contrast (bp)")

    style_axis(
        ax[4],
        "Wallet-level outcome dispersion",
        "Capacity-supported net bp • wallet means • equal wallet, not entry • no minimum-n claim",
    )
    arrays = [wallet_stats[a]["mean"] for a in ARMS]
    bp = ax[4].boxplot(
        arrays,
        tick_labels=[DISPLAY[a] for a in ARMS],
        showfliers=True,
        patch_artist=True,
    )
    for patch_box, arm in zip(bp["boxes"], ARMS, strict=True):
        patch_box.set_facecolor(COLORS[arm])
        patch_box.set_alpha(0.45)
    ax[4].axhline(0, color="black", linewidth=0.8)
    ax[4].set_ylabel("wallet mean net bp")

    style_axis(
        ax[5],
        "Roster persistence versus observed wallet return",
        "Capacity-supported net bp • x=folds selected • one wallet/arm • sample size varies",
    )
    for arm in ARMS:
        freq = Counter(w for f in FOLDS for w in data["rosters"]["folds"][str(f)]["rosters"][arm])
        stat = wallet_stats[arm]
        x = np.asarray([freq[w] for w in stat["wallet"]])
        ax[5].scatter(
            x,
            stat["mean"],
            s=12 + np.sqrt(stat["count"]) * 2,
            alpha=0.5,
            color=COLORS[arm],
            label=DISPLAY[arm],
        )
    ax[5].axhline(0, color="black", linewidth=0.8)
    ax[5].set_xlabel("folds selected (1–8)")
    ax[5].set_ylabel("wallet mean supported net bp")
    ax[5].legend(fontsize=7)
    return fig


def html_report(page_files: list[Path], digest: str, data: dict[str, object]) -> str:
    report = data["report"]
    cards = []
    for i, path in enumerate(page_files, 1):
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        cards.append(
            f'<section id="p{i}"><h2>Page {i}</h2><img alt="diagnostic atlas page {i}" '
            f'src="data:image/png;base64,{encoded}"></section>'
        )
    nav = " ".join(f'<a href="#p{i}">{i}</a>' for i in range(1, len(page_files) + 1))
    p = report["primary"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Efron BOT500 diagnostic atlas</title><style>
body{{margin:0;background:#e2e8f0;color:#0f172a;font-family:Arial,sans-serif}}header{{position:sticky;top:0;background:#0f172a;color:white;padding:14px 4%;z-index:2}}header a{{color:#93c5fd;margin:0 7px}}main{{max-width:1500px;margin:auto;padding:22px}}.warning{{background:#fee2e2;border-left:6px solid #b91c1c;padding:14px;margin-bottom:18px}}section{{background:white;margin:20px 0;padding:15px;box-shadow:0 2px 10px #94a3b8}}img{{display:block;width:100%;height:auto}}small{{color:#cbd5e1}}
</style></head><body><header><b>Efron BOT500 diagnostic atlas</b> &nbsp; {nav}<br><small>{html.escape(WATERMARK)} • generation {digest}</small></header><main>
<div class="warning"><b>{html.escape(p["verdict_status"])}</b>: registered BOT500−E30 {p["delta_bp"]:+.2f}bp, crossed CI [{p["crossed_ci95"][0]:+.2f},{p["crossed_ci95"][1]:+.2f}], MDE80 {p["crossed_mde80_bp"]:.2f}bp, +5bp power {100 * p["crossed_power_at_plus5"]:.1f}%. Visual cuts are burned dependent diagnostics, not new tests.</div>
{"".join(cards)}</main></body></html>"""


def atomic_latest(payload: dict[str, object]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = LATEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(LATEST)


def assert_inputs_current(inputs: list[dict[str, object]]) -> None:
    current = [input_record(REPO_ROOT / item["path"]) for item in inputs]
    if current != inputs:
        raise RuntimeError("study input changed before visual publication")


def bound_book_sha(inputs: list[dict[str, object]]) -> str:
    target = repo_rel(BOOK_REPORT)
    matches = [str(item["sha256"]) for item in inputs if item["path"] == target]
    if len(matches) != 1:
        raise RuntimeError("generation inputs do not bind exactly one book report")
    return matches[0]


def publish_latest(generation_dir: Path, digest: str, inputs: list[dict[str, object]]) -> None:
    assert_inputs_current(inputs)
    atomic_latest(
        {
            "status": "CURRENT_VERIFIED_GENERATION",
            "generation": generation_dir.name,
            "generation_digest": digest,
            "book_report_sha256": bound_book_sha(inputs),
            "manifest_sha256": sha256(generation_dir / "visual_manifest.json"),
        }
    )


def validate_existing_generation(
    generation_dir: Path, digest: str, inputs: list[dict[str, object]]
) -> None:
    manifest_path = generation_dir / "visual_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("existing visual generation lacks manifest")
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("status") != "BURNED_POSTHOC_VISUAL_DIAGNOSTIC_ATLAS"
        or manifest.get("generation_digest") != digest
        or manifest.get("inputs") != inputs
        or manifest.get("watermark") != WATERMARK
        or manifest.get("consensus") != "excluded"
        or manifest.get("positive_promotion_eligible") is not False
        or manifest.get("method_null_eligible") is not False
        or manifest.get("visual_spec_sha256") != sha256(SPEC)
        or manifest.get("visual_code_sha256") != sha256(Path(__file__))
    ):
        raise RuntimeError("existing visual generation manifest contract failed")
    expected_names = {
        "01_executive_overview.png",
        "02_returns_and_tails.png",
        "03_formation_cohort.png",
        "04_efron_assumptions.png",
        "05_roster_dynamics.png",
        "06_capacity_missingness.png",
        "07_wallet_dependence.png",
        "diagnostic_atlas.pdf",
        "index.html",
    }
    records = manifest.get("outputs", [])
    if len(records) != len(expected_names) or {r.get("path") for r in records} != expected_names:
        raise RuntimeError("existing visual generation output set is not exact")
    actual_entries = list(generation_dir.iterdir())
    actual_names = {p.name for p in actual_entries}
    if any(not p.is_file() for p in actual_entries) or actual_names != expected_names | {
        "visual_manifest.json"
    }:
        raise RuntimeError("existing visual generation contains unbound files")
    for record in records:
        path = generation_dir / str(record["path"])
        current = {"path": path.name, "size": path.stat().st_size, "sha256": sha256(path)}
        if current != record:
            raise RuntimeError(f"existing visual output integrity failed: {path.name}")
    page = (generation_dir / "index.html").read_text(encoding="utf-8")
    if page.count("data:image/png;base64,") != 7 or digest not in page or WATERMARK not in page:
        raise RuntimeError("existing embedded HTML contract failed")


def render() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    data = load_and_validate()
    inputs_before = data["inputs"]
    digest = hashlib.sha256(canonical_json(inputs_before).encode()).hexdigest()
    generation = f"generation-{digest}"
    final_dir = ROOT / generation
    if final_dir.exists():
        validate_existing_generation(final_dir, digest, inputs_before)
        publish_latest(final_dir, digest, inputs_before)
        return final_dir
    staging = Path(tempfile.mkdtemp(prefix=f".{generation}-", dir=ROOT))
    pages = [
        ("01_executive_overview.png", page_executive),
        ("02_returns_and_tails.png", page_returns),
        ("03_formation_cohort.png", page_cohort),
        ("04_efron_assumptions.png", page_efron),
        ("05_roster_dynamics.png", page_roster),
        ("06_capacity_missingness.png", page_execution),
        ("07_wallet_dependence.png", page_wallets),
    ]
    page_paths: list[Path] = []
    pdf_path = staging / "diagnostic_atlas.pdf"
    try:
        with PdfPages(pdf_path) as pdf:
            for filename, builder in pages:
                fig = builder(data, digest)
                path = staging / filename
                fig.savefig(path, dpi=170, facecolor="white")
                pdf.savefig(fig, facecolor="white")
                plt.close(fig)
                page_paths.append(path)
        index_path = staging / "index.html"
        index_path.write_text(html_report(page_paths, digest, data), encoding="utf-8")
        inputs_after = [input_record(REPO_ROOT / item["path"]) for item in inputs_before]
        if inputs_after != inputs_before:
            raise RuntimeError("study input changed during rendering")
        output_records = [input_record(p) for p in [*page_paths, pdf_path, index_path]]
        # Output records are repo-relative only after publication; stage paths are normalized here.
        for record, path in zip(output_records, [*page_paths, pdf_path, index_path], strict=True):
            record["path"] = path.name
        manifest = {
            "status": "BURNED_POSTHOC_VISUAL_DIAGNOSTIC_ATLAS",
            "generation_digest": digest,
            "watermark": WATERMARK,
            "consensus": "excluded",
            "positive_promotion_eligible": False,
            "method_null_eligible": False,
            "visual_spec_sha256": sha256(SPEC),
            "visual_code_sha256": sha256(Path(__file__)),
            "inputs": inputs_before,
            "outputs": output_records,
            "reconciliation": {
                "selector_ordered_input_hashes": "PASS_16_OF_16",
                "global_capacity_funnels": "PASS_16_OF_16",
                "book_totals": "PASS_2_OF_2",
                "primary_delta": "PASS",
                "wallet_contribution_sum_and_top5": "PASS",
            },
            "software": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "matplotlib": matplotlib.__version__,
                "pyarrow": pyarrow.__version__,
            },
        }
        manifest_path = staging / "visual_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        staging.replace(final_dir)
        validate_existing_generation(final_dir, digest, inputs_before)
        publish_latest(final_dir, digest, inputs_before)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final_dir


if __name__ == "__main__":
    print(render())
