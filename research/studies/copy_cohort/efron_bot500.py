"""Burned post-hoc Efron top-30 diagnostic with a pre-fit 500 fills/day screen."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import warnings
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT

from . import lake
from .alt_fresh_validate import MAJORS, STALE_MS, _ctx_parts
from .dynamic_t_book import compare
from .dynamic_t_quality import FOLDS, ND_MIN, formation_months
from .filtered_quality import _code_sha256, _sha256_json
from .informed import t_to_z, two_groups
from .nested_t_book import (
    COIN_CAP_USD,
    COST_BP,
    HOLD_MS,
    MAX_FOLD_LOSS,
    MAX_IMBALANCE,
    MAX_LOSS,
    MISSING_BOUND_BP,
    NOTIONAL_MIN,
    SELECTOR_ARCH_SHA256,
    UNIT_USD,
    _ctx_records,
    _day_epoch,
    book_stats,
    bounded,
    concat,
    concentration,
    load_entries,
    missing_stats,
    raw_stats,
    validate_roster_report,
)
from .nested_t_book import OUT as PARENT_BOOK
from .nested_t_filter import ARCH as PARENT_ARCH
from .nested_t_filter import CAP, normalized_x, topk
from .nested_t_filter import OUT as PARENT_ROSTERS

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "efron_bot500"
ENTRIES = DERIVED / "entries"
ROSTERS = DERIVED / "rosters.json"
OUT = DERIVED / "book_report.json"
ARCH = Path(__file__).with_name("EFRON_BOT500_ARCH.md")

ARMS = ("E30", "E_BOT500")
TOP_K = 30
BOT_MAX = 500.0
N_BOOT = 10_000
SEED = 20260720
POINT_TOL = 1e-10


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True))
    tmp.replace(path)


def entry_data_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def bound_entry_meta(path: Path, spec: dict[str, object]) -> dict[str, object]:
    return {"spec": spec, "data": entry_data_record(path)}


def entry_cache_valid(path: Path, meta: Path, spec: dict[str, object]) -> bool:
    if not path.exists() or not meta.exists():
        return False
    try:
        payload = json.loads(meta.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("spec") == spec and payload.get("data") == entry_data_record(path))


def write_nonresult(status: str, error: str | None = None) -> None:
    payload: dict[str, object] = {
        "status": status,
        "comparative_results_present": False,
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
    }
    if error is not None:
        payload["error"] = error
    atomic_json(OUT, payload)


def write_roster_nonresult(status: str, error: str | None = None) -> None:
    payload: dict[str, object] = {
        "status": status,
        "rosters_present": False,
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
    }
    if error is not None:
        payload["error"] = error
    atomic_json(ROSTERS, payload)


def grouped_scores(
    wallet: np.ndarray, x: np.ndarray, fills_per_day: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    wallets, starts, counts = np.unique(wallet, return_index=True, return_counts=True)
    expected = np.r_[0, np.cumsum(counts[:-1])]
    if not np.array_equal(starts, expected):
        raise RuntimeError("panel wallets are not contiguous and ordered")
    mean = np.add.reduceat(x, starts) / counts
    centered = x - np.repeat(mean, counts)
    ss = np.add.reduceat(centered * centered, starts)
    sd = np.full(wallets.size, np.nan)
    enough = counts >= ND_MIN
    sd[enough] = np.sqrt(ss[enough] / (counts[enough] - 1))
    score = np.full(wallets.size, np.nan)
    good = enough & np.isfinite(sd) & (sd > 0)
    score[good] = mean[good] / (sd[good] / np.sqrt(counts[good]))
    group_fpd = fills_per_day[starts]
    if not np.allclose(fills_per_day, np.repeat(group_fpd, counts), atol=1e-12, rtol=1e-12):
        raise RuntimeError("fills/day changes within wallet")
    return wallets, counts.astype(float), sd, score, group_fpd


def load_panel_scores(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    d = pq.read_table(
        path,
        columns=["wallet", "day", "day_pnl", "day_notional", "fills_per_day"],
    ).to_pydict()
    wallet = np.asarray(d["wallet"], str)
    day = np.asarray(d["day"], np.int64)
    if np.any((wallet[1:] == wallet[:-1]) & (day[1:] <= day[:-1])):
        raise RuntimeError("duplicate or non-increasing wallet/day panel rows")
    x = np.asarray(
        [normalized_x(p, n) for p, n in zip(d["day_pnl"], d["day_notional"], strict=True)]
    )
    wallets, nd, _sd, score, fpd = grouped_scores(wallet, x, np.asarray(d["fills_per_day"], float))
    return wallets, nd, score, fpd


def independent_fpd(con, fold: int, wallets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE eb_eligible AS SELECT * FROM (SELECT UNNEST(?) wallet)",
        [wallets.tolist()],
    )
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in formation_months(fold))
    d = con.execute(f"""
      SELECT lower(d.wallet) AS wallet,
        SUM(d.n_fills)::DOUBLE/COUNT(DISTINCT d.day)::DOUBLE AS fills_per_day
      FROM read_parquet([{globs}]) d JOIN eb_eligible e ON lower(d.wallet)=e.wallet
      GROUP BY lower(d.wallet) ORDER BY wallet
    """).fetchnumpy()
    return d["wallet"].astype(str), np.asarray(d["fills_per_day"], float)


def efron_roster(
    wallets: np.ndarray,
    nd: np.ndarray,
    score: np.ndarray,
    mask: np.ndarray,
    *,
    fit_fn: Callable[[np.ndarray], dict] = two_groups,
) -> tuple[list[str], dict[str, object]]:
    use = np.asarray(mask, bool) & np.isfinite(score)
    w, n, t = wallets[use], nd[use], score[use]
    if w.size < TOP_K:
        raise RuntimeError(f"Efron pool only {w.size}")
    z = t_to_z(t, n - 1)
    if z.shape != t.shape or np.any(~np.isfinite(z)):
        raise RuntimeError("Efron z transform lost/nonfinite members")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fit = fit_fn(z)
    if caught:
        raise RuntimeError(f"Efron fit warning: {caught[0].message}")
    p = np.asarray(fit.get("p_informed"), float)
    params = [float(fit.get(k, math.nan)) for k in ("mu0", "sigma0", "pi0")]
    if (
        p.shape != z.shape
        or np.any(~np.isfinite(p))
        or np.any(~np.isfinite(params))
        or params[1] <= 0
    ):
        raise RuntimeError("Efron fit is nonfinite or incomplete")
    positive = t > 0
    if positive.sum() < TOP_K:
        raise RuntimeError(f"positive-t Efron pool only {positive.sum()}")
    ww, pp, tt = w[positive], p[positive], t[positive]
    roster = ww[np.lexsort((ww, -tt, -pp))[:TOP_K]].tolist()
    fit_input = [
        {"wallet": str(a), "nd": int(b), "t": float(c), "z": float(d)}
        for a, b, c, d in zip(w, n, t, z, strict=True)
    ]
    return roster, {
        "n_fit": int(w.size),
        "n_positive_t": int(positive.sum()),
        "mu0": params[0],
        "sigma0": params[1],
        "pi0": params[2],
        "ordered_input_sha256": _sha256_json(fit_input),
    }


def validate_parents(con, parent: dict[str, object]) -> dict[str, object]:
    validate_roster_report(con, parent)
    book = json.loads(PARENT_BOOK.read_text())
    if book.get("status") != "BURNED_PARITY_LOCKED_BOOK_DIAGNOSTIC":
        raise RuntimeError("parent nested book is not successful")
    if book["config"].get("rosters_sha256") != file_sha256(PARENT_ROSTERS):
        raise RuntimeError("parent book does not bind current selector file")
    parent_book_code = Path(__file__).with_name("nested_t_book.py")
    if book["config"].get("code_sha256") != _code_sha256(parent_book_code):
        raise RuntimeError("parent book code hash is stale")
    if book["config"].get("architecture_sha256") != file_sha256(PARENT_ARCH):
        raise RuntimeError("parent amended architecture hash is stale")
    inference = Path(__file__).with_name("dynamic_t_book.py")
    if book["config"].get("inference_dependency_sha256") != file_sha256(inference):
        raise RuntimeError("parent inference dependency is stale")
    if parent["config"].get("architecture_sha256") != SELECTOR_ARCH_SHA256:
        raise RuntimeError("parent selector architecture is not frozen original")
    return book


def build_rosters(con) -> dict[str, object]:
    parent = json.loads(PARENT_ROSTERS.read_text())
    parent_book = validate_parents(con, parent)
    report: dict[str, object] = {
        "status": "BURNED_POSTHOC_EFRON_BOT500_SELECTOR",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "config": {
            "arms": list(ARMS),
            "bot_max": BOT_MAX,
            "cap": float(CAP),
            "nd_min": ND_MIN,
            "architecture_sha256": file_sha256(ARCH),
            "code_sha256": _code_sha256(Path(__file__)),
            "extension_inference_sha256": file_sha256(
                Path(__file__).with_name("dynamic_t_book.py")
            ),
            "parent_rosters_file_sha256": file_sha256(PARENT_ROSTERS),
            "parent_book_file_sha256": file_sha256(PARENT_BOOK),
            "parent_book_code_sha256": parent_book["config"]["code_sha256"],
            "parent_inference_sha256": parent_book["config"]["inference_dependency_sha256"],
            "parent_selector_architecture_sha256": SELECTOR_ARCH_SHA256,
            "parent_amended_architecture_sha256": file_sha256(PARENT_ARCH),
            "consensus": "excluded",
        },
        "folds": {},
    }
    for fold in FOLDS:
        print(f"[Efron BOT500 selector] {fold}", flush=True)
        item = parent["folds"][str(fold)]
        panel = Path(item["panel_path"])
        panel_sha = file_sha256(panel)
        panel_meta_sha = file_sha256(panel.with_suffix(".meta.json"))
        source_lineage = lake.validated_lineage(
            con, formation_months(fold), ("alt_universe_wallet_coin_day",)
        )
        if source_lineage != item["panel_source_lineage"]:
            raise RuntimeError(f"fold {fold}: parent formation lineage changed")
        wallets, nd, score, fpd = load_panel_scores(panel)
        if panel_sha != file_sha256(panel) or panel_meta_sha != file_sha256(
            panel.with_suffix(".meta.json")
        ):
            raise RuntimeError(f"fold {fold}: panel mutated while scoring")
        eligible = np.isfinite(score)
        ew, efpd = wallets[eligible], fpd[eligible]
        ow, ofpd = independent_fpd(con, fold, ew)
        post_lineage = lake.validated_lineage(
            con, formation_months(fold), ("alt_universe_wallet_coin_day",)
        )
        if post_lineage != source_lineage:
            raise RuntimeError(f"fold {fold}: formation source mutated during BOT500 oracle")
        if not np.array_equal(ew, ow) or not np.allclose(efpd, ofpd, atol=1e-12, rtol=1e-12):
            raise RuntimeError(f"fold {fold}: independent fills/day parity failed")
        if not np.array_equal(efpd <= BOT_MAX, ofpd <= BOT_MAX):
            raise RuntimeError(f"fold {fold}: BOT500 mask parity failed")
        e30, fit_all = efron_roster(wallets, nd, score, eligible)
        if e30 != item["rosters"]["STATIC_E30"]:
            raise RuntimeError(f"fold {fold}: unscreened Efron roster parity failed")
        bot = eligible & np.isfinite(fpd) & (fpd <= BOT_MAX)
        direct_bot = topk(wallets, score, bot)
        if direct_bot != item["rosters"]["STATIC_BOT500_T30"]:
            raise RuntimeError(f"fold {fold}: direct BOT500 roster parity failed")
        ebot, fit_bot = efron_roster(wallets, nd, score, bot)
        selected_fpd = {str(w): float(fpd[np.searchsorted(wallets, w)]) for w in ebot}
        if any(v > BOT_MAX for v in selected_fpd.values()):
            raise RuntimeError(f"fold {fold}: BOT500 selected an excluded wallet")
        rosters = {"E30": e30, "E_BOT500": ebot}
        if any(len(v) != TOP_K or len(set(v)) != TOP_K for v in rosters.values()):
            raise RuntimeError(f"fold {fold}: exact top-30 invariant failed")
        report["folds"][str(fold)] = {
            "panel_path": str(panel),
            "panel_file_sha256": panel_sha,
            "panel_meta_sha256": panel_meta_sha,
            "formation_source_lineage": source_lineage,
            "n_eligible": int(eligible.sum()),
            "n_bot_eligible": int(bot.sum()),
            "n_excluded_gt500": int(np.sum(eligible & ~bot)),
            "fpd_oracle_max_abs_diff": float(np.max(np.abs(efpd - ofpd))),
            "rosters": rosters,
            "overlap": len(set(e30) & set(ebot)),
            "selected_bot_fills_per_day": selected_fpd,
            "fit_E30": fit_all,
            "fit_E_BOT500": fit_bot,
        }
    report["rosters_sha256"] = _sha256_json(
        {f: item["rosters"] for f, item in report["folds"].items()}
    )
    if report["config"]["parent_rosters_file_sha256"] != file_sha256(PARENT_ROSTERS):
        raise RuntimeError("parent selector changed during child selection")
    if report["config"]["parent_book_file_sha256"] != file_sha256(PARENT_BOOK):
        raise RuntimeError("parent book changed during child selection")
    for fold in FOLDS:
        item = report["folds"][str(fold)]
        if item["panel_file_sha256"] != file_sha256(Path(item["panel_path"])):
            raise RuntimeError(f"fold {fold}: panel changed before roster publication")
        if item["panel_meta_sha256"] != file_sha256(
            Path(item["panel_path"]).with_suffix(".meta.json")
        ):
            raise RuntimeError(f"fold {fold}: panel meta changed before roster publication")
        current = lake.validated_lineage(
            con, formation_months(fold), ("alt_universe_wallet_coin_day",)
        )
        if current != item["formation_source_lineage"]:
            raise RuntimeError(f"fold {fold}: formation source changed before roster publication")
    atomic_json(ROSTERS, report)
    return report


def common_cutoff(con, context_paths: list[str]) -> tuple[dict[str, int], int]:
    ctx_list = ",".join(f"'{p}'" for p in context_paths)
    majors = ",".join(f"'{c}'" for c in MAJORS)
    rows = con.execute(f"""
      SELECT coin,max(ts)::BIGINT FROM read_parquet([{ctx_list}])
      WHERE mid_px IS NOT NULL AND coin IN ({majors}) GROUP BY coin ORDER BY coin
    """).fetchall()
    if sorted(str(r[0]) for r in rows) != sorted(MAJORS):
        raise RuntimeError("context cutoff lacks all majors")
    maxima = {str(c): int(ts) for c, ts in rows}
    return maxima, min(maxima.values()) - HOLD_MS


def cache_entries(con, fold: int, rosters: dict[str, list[str]], roster_sha: str) -> Path:
    ENTRIES.mkdir(parents=True, exist_ok=True)
    path = ENTRIES / f"entries_{fold}.parquet"
    meta = ENTRIES / f"entries_{fold}.meta.json"
    wallets = sorted({w for arm in ARMS for w in rosters[arm]})
    context_paths = _ctx_parts(fold)
    context = _ctx_records(context_paths)
    maxima, cutoff = common_cutoff(con, context_paths)
    lineage = lake.validated_lineage(con, [fold], ("alt_universe_open_entries",))
    spec = {
        "schema": "efron-bot500-entry-v1",
        "fold": fold,
        "wallets": wallets,
        "wallets_sha256": _sha256_json(wallets),
        "arm_rosters_sha256": _sha256_json({a: rosters[a] for a in ARMS}),
        "roster_report_file_sha256": roster_sha,
        "source_lineage": lineage,
        "context": context,
        "context_sha256": _sha256_json(context),
        "context_max_ts_by_coin": maxima,
        "common_cutoff": cutoff,
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "config": {
            "majors": list(MAJORS),
            "notional_min": NOTIONAL_MIN,
            "hold_ms": HOLD_MS,
            "stale_ms": STALE_MS,
        },
    }
    if entry_cache_valid(path, meta, spec):
        return path
    con.execute(
        "CREATE OR REPLACE TEMP TABLE eb_wallet AS SELECT * FROM (SELECT UNNEST(?) wallet)",
        [wallets],
    )
    ctx_list = ",".join(f"'{p}'" for p in context_paths)
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH ent AS (
        SELECT lower(o.wallet) AS wallet,o.coin,o.ts,o.dir_sign,
          CAST(o.notl AS DOUBLE) AS notional
        FROM read_parquet('{lake.ope_month_glob(fold)}') o
        JOIN eb_wallet w ON lower(o.wallet)=w.wallet
        WHERE o.coin IN ({majors}) AND CAST(o.notl AS DOUBLE)>={NOTIONAL_MIN}
          AND o.ts<={cutoff}
      ), ctx AS (
        SELECT coin,ts,mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL
      ), p0 AS (
        SELECT ent.*,ctx.mid_px AS px0,ctx.ts AS px0_ts
        FROM ent ASOF LEFT JOIN ctx ON ent.coin=ctx.coin AND ent.ts>=ctx.ts
      ), p8 AS (
        SELECT p0.*,ctx.mid_px AS px8,ctx.ts AS px8_ts
        FROM p0 ASOF LEFT JOIN ctx ON p0.coin=ctx.coin AND (p0.ts+{HOLD_MS})>=ctx.ts
      )
      SELECT *,CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0>0
          AND ts-px0_ts<={STALE_MS} AND ts+{HOLD_MS}-px8_ts<={STALE_MS}
        THEN dir_sign*(px8-px0)/px0*1e4 END AS gross_bp,
        {cutoff}::BIGINT AS common_cutoff
      FROM p8 ORDER BY ts,wallet,coin,dir_sign,notional
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post_lineage = lake.validated_lineage(con, [fold], ("alt_universe_open_entries",))
    post_context = _ctx_records(context_paths)
    if post_lineage != lineage or post_context != context:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: evaluation source/context mutated during build")
    tmp.replace(path)
    atomic_json(meta, bound_entry_meta(path, spec))
    return path


def selected_raw_global(
    entries: dict[str, np.ndarray], rosters: dict[str, list[str]]
) -> dict[str, np.ndarray]:
    sets = {str(f): set(rosters[str(f)]) for f in FOLDS}
    selected = np.asarray(
        [
            str(w) in sets[str(int(f))]
            for w, f in zip(entries["wallet"], entries["fold"], strict=True)
        ]
    )
    m = selected & np.isfinite(entries["gross_bp"])
    return {
        "wallet": entries["wallet"][m],
        "fold": entries["fold"][m],
        "gross_bp": entries["gross_bp"][m],
    }


def capacity_book_global(
    entries: dict[str, np.ndarray], rosters: dict[str, list[str]]
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, int]]]:
    if np.any(np.diff(entries["ts"]) < 0):
        raise RuntimeError("global entry stream is not chronological")
    sets = {str(f): set(rosters[str(f)]) for f in FOLDS}
    use = np.asarray(
        [
            str(w) in sets[str(int(f))]
            for w, f in zip(entries["wallet"], entries["fold"], strict=True)
        ]
    )
    idx = np.flatnonzero(use)
    open_wc: set[tuple[str, str]] = set()
    coin_gross: dict[str, float] = {}
    exits: list[tuple[int, str, str]] = []
    accepted: list[int] = []
    funnels = {
        str(f): {
            "n_candidates": 0,
            "n_accepted_capacity": 0,
            "n_skip_wallet_coin": 0,
            "n_skip_coin_cap": 0,
        }
        for f in FOLDS
    }
    for i in idx:
        t = int(entries["ts"][i])
        fold = str(int(entries["fold"][i]))
        funnels[fold]["n_candidates"] += 1
        while exits and exits[0][0] <= t:
            _, old_wallet, old_coin = heapq.heappop(exits)
            open_wc.discard((old_wallet, old_coin))
            coin_gross[old_coin] = coin_gross.get(old_coin, 0.0) - UNIT_USD
        wallet, coin = str(entries["wallet"][i]), str(entries["coin"][i])
        if (wallet, coin) in open_wc:
            funnels[fold]["n_skip_wallet_coin"] += 1
            continue
        if coin_gross.get(coin, 0.0) + UNIT_USD > COIN_CAP_USD + 1e-9:
            funnels[fold]["n_skip_coin_cap"] += 1
            continue
        open_wc.add((wallet, coin))
        coin_gross[coin] = coin_gross.get(coin, 0.0) + UNIT_USD
        heapq.heappush(exits, (t + HOLD_MS, wallet, coin))
        accepted.append(int(i))
        funnels[fold]["n_accepted_capacity"] += 1
    ii = np.asarray(accepted, np.int64)
    out = {k: v[ii] for k, v in entries.items()}
    out["supported"] = np.isfinite(out["gross_bp"])
    out["net_bp"] = out["gross_bp"] - COST_BP
    return out, funnels


def supported_book(capacity: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    m = capacity["supported"]
    return {k: v[m] for k, v in capacity.items()}


def rate_gates(a: dict[str, object], b: dict[str, object]) -> bool:
    fold_rates = []
    for fold in FOLDS:
        for arm in (a, b):
            value = arm["per_fold"].get(str(fold), {}).get("rate")
            if value is None or not np.isfinite(float(value)):
                return False
            fold_rates.append(float(value))
    return bool(
        a["rate"] <= MAX_LOSS
        and b["rate"] <= MAX_LOSS
        and max(fold_rates, default=0.0) <= MAX_FOLD_LOSS
        and abs(a["rate"] - b["rate"]) <= MAX_IMBALANCE
    )


def power_pass(value: object) -> bool:
    return bool(value is not None and np.isfinite(float(value)) and float(value) >= 0.8)


def validate_final_snapshot(
    con,
    roster_report: dict[str, object],
    roster_file_sha: str,
    entry_meta_sha: dict[str, str],
    entry_file_records: dict[str, dict[str, object]],
) -> None:
    if file_sha256(ROSTERS) != roster_file_sha:
        raise RuntimeError("child roster artifact changed during outcome run")
    config = roster_report["config"]
    if config["architecture_sha256"] != file_sha256(ARCH):
        raise RuntimeError("extension architecture changed during run")
    if config["code_sha256"] != _code_sha256(Path(__file__)):
        raise RuntimeError("extension code changed during run")
    if config["extension_inference_sha256"] != file_sha256(
        Path(__file__).with_name("dynamic_t_book.py")
    ):
        raise RuntimeError("extension inference code changed during run")
    if config["parent_rosters_file_sha256"] != file_sha256(PARENT_ROSTERS):
        raise RuntimeError("parent selector changed during outcome run")
    if config["parent_book_file_sha256"] != file_sha256(PARENT_BOOK):
        raise RuntimeError("parent book changed during outcome run")
    parent = json.loads(PARENT_ROSTERS.read_text())
    validate_parents(con, parent)
    for fold in FOLDS:
        item = roster_report["folds"][str(fold)]
        panel = Path(item["panel_path"])
        if item["panel_file_sha256"] != file_sha256(panel):
            raise RuntimeError(f"fold {fold}: panel changed during outcome run")
        if item["panel_meta_sha256"] != file_sha256(panel.with_suffix(".meta.json")):
            raise RuntimeError(f"fold {fold}: panel meta changed during outcome run")
        current_formation = lake.validated_lineage(
            con, formation_months(fold), ("alt_universe_wallet_coin_day",)
        )
        if current_formation != item["formation_source_lineage"]:
            raise RuntimeError(f"fold {fold}: formation source changed during outcome run")
        meta = ENTRIES / f"entries_{fold}.meta.json"
        entry = ENTRIES / f"entries_{fold}.parquet"
        if file_sha256(meta) != entry_meta_sha[str(fold)]:
            raise RuntimeError(f"fold {fold}: entry sidecar changed during outcome run")
        payload = json.loads(meta.read_text())
        spec = payload.get("spec", {})
        current_entry_record = entry_data_record(entry)
        if (
            payload.get("data") != current_entry_record
            or entry_file_records[str(fold)] != current_entry_record
        ):
            raise RuntimeError(f"fold {fold}: entry parquet changed during outcome run")
        current_eval = lake.validated_lineage(con, [fold], ("alt_universe_open_entries",))
        if spec["source_lineage"] != current_eval or spec["context"] != _ctx_records(
            _ctx_parts(fold)
        ):
            raise RuntimeError(f"fold {fold}: evaluation source/context changed during run")


def _run() -> dict[str, object]:
    write_roster_nonresult("SELECTOR_PARITY_PENDING_NO_ROSTERS")
    write_nonresult("SELECTOR_PARITY_PENDING_NO_RESULTS")
    con = None
    try:
        con = lake.connect(mem="4GB", threads=2)
        roster_report = build_rosters(con)
    except Exception as exc:
        if con is not None:
            con.close()
        write_roster_nonresult("SELECTOR_PARITY_FAILURE", f"{type(exc).__name__}: {exc}")
        write_nonresult("SELECTOR_PARITY_FAILURE", f"{type(exc).__name__}: {exc}")
        raise
    write_nonresult("SELECTOR_PARITY_PASSED_OUTCOMES_PENDING")
    roster_file_sha = file_sha256(ROSTERS)
    entry_parts = []
    entry_meta_sha: dict[str, str] = {}
    entry_file_records: dict[str, dict[str, object]] = {}
    try:
        for fold in FOLDS:
            print(f"[Efron BOT500 book] {fold}", flush=True)
            rosters = roster_report["folds"][str(fold)]["rosters"]
            entry_path = cache_entries(con, fold, rosters, roster_file_sha)
            entry_meta_sha[str(fold)] = file_sha256(entry_path.with_suffix(".meta.json"))
            entry_file_records[str(fold)] = entry_data_record(entry_path)
            entry_parts.append(load_entries(entry_path, fold))
    except Exception as exc:
        con.close()
        write_nonresult("OUTCOME_BUILD_FAILURE_NO_RESULTS", f"{type(exc).__name__}: {exc}")
        raise
    con.close()
    entries = concat(entry_parts)
    rosters_by_arm = {
        arm: {str(fold): roster_report["folds"][str(fold)]["rosters"][arm] for fold in FOLDS}
        for arm in ARMS
    }
    capacity: dict[str, dict[str, np.ndarray]] = {}
    books: dict[str, dict[str, np.ndarray]] = {}
    raw_books: dict[str, dict[str, np.ndarray]] = {}
    arm_funnels: dict[str, dict[str, dict[str, int]]] = {}
    for arm in ARMS:
        raw_books[arm] = selected_raw_global(entries, rosters_by_arm[arm])
        capacity[arm], arm_funnels[arm] = capacity_book_global(entries, rosters_by_arm[arm])
        books[arm] = supported_book(capacity[arm])
    funnels = {str(fold): {arm: arm_funnels[arm][str(fold)] for arm in ARMS} for fold in FOLDS}
    lo, hi = _day_epoch(20251101), _day_epoch(20260630)
    result = compare(books["E_BOT500"], books["E30"], SEED, lo, hi, n_boot=N_BOOT)
    ma, mb = missing_stats(capacity["E_BOT500"]), missing_stats(capacity["E30"])
    rate_ok = rate_gates(ma, mb)
    adverse = compare(
        bounded(capacity["E_BOT500"], -MISSING_BOUND_BP),
        bounded(capacity["E30"], MISSING_BOUND_BP),
        SEED + 100,
        lo,
        hi,
        n_boot=N_BOOT,
    )
    favorable_a = bounded(capacity["E_BOT500"], MISSING_BOUND_BP)
    favorable_b = bounded(capacity["E30"], -MISSING_BOUND_BP)
    favorable = compare(
        favorable_a,
        favorable_b,
        SEED + 200,
        lo,
        hi,
        n_boot=N_BOOT,
    )
    injected_a = {k: v.copy() for k, v in books["E_BOT500"].items()}
    injected_b = {k: v.copy() for k, v in books["E30"].items()}
    injected_a["net_bp"] = injected_a["net_bp"] - injected_a["net_bp"].mean() + 5.0
    injected_b["net_bp"] = injected_b["net_bp"] - injected_b["net_bp"].mean()
    injected = compare(injected_a, injected_b, SEED + 300, lo, hi, n_boot=N_BOOT)
    injected_pass = bool(
        injected.get("crossed_ci95")
        and abs(injected["delta_bp"] - 5.0) <= POINT_TOL
        and injected["crossed_ci95"][0] > 0
    )
    favorable_injected_a = {k: v.copy() for k, v in favorable_a.items()}
    favorable_injected_b = {k: v.copy() for k, v in favorable_b.items()}
    favorable_injected_a["net_bp"] = (
        favorable_injected_a["net_bp"] - favorable_injected_a["net_bp"].mean() + 5.0
    )
    favorable_injected_b["net_bp"] = (
        favorable_injected_b["net_bp"] - favorable_injected_b["net_bp"].mean()
    )
    favorable_injected = compare(
        favorable_injected_a,
        favorable_injected_b,
        SEED + 400,
        lo,
        hi,
        n_boot=N_BOOT,
    )
    favorable_injected_pass = bool(
        favorable_injected.get("crossed_ci95")
        and abs(favorable_injected["delta_bp"] - 5.0) <= POINT_TOL
        and favorable_injected["crossed_ci95"][0] > 0
    )
    positive_sensitivity = bool(
        rate_ok
        and result.get("crossed_ci95")
        and adverse.get("crossed_ci95")
        and result["crossed_ci95"][0] > 0
        and adverse["crossed_ci95"][0] > 0
        and injected_pass
    )
    null_sensitivity = bool(
        rate_ok
        and result.get("crossed_ci95")
        and favorable.get("crossed_ci95")
        and result["crossed_ci95"][1] < 5
        and favorable["crossed_ci95"][1] < 5
        and result.get("crossed_mde80_bp") is not None
        and result["crossed_mde80_bp"] <= 5
        and power_pass(result.get("crossed_power_at_plus5"))
        and favorable.get("crossed_mde80_bp") is not None
        and favorable["crossed_mde80_bp"] <= 5
        and power_pass(favorable.get("crossed_power_at_plus5"))
        and injected_pass
        and favorable_injected_pass
    )
    result["missingness"] = {
        "arm_E_BOT500": ma,
        "arm_E30": mb,
        "rate_gates_pass": rate_ok,
        "adverse_bound": adverse,
        "favorable_bound": favorable,
    }
    result["injected_plus5"] = {
        "point": injected.get("delta_bp"),
        "crossed_ci95": injected.get("crossed_ci95"),
        "injected_control_pass": injected_pass,
        "analytical_power_pass": power_pass(result.get("crossed_power_at_plus5")),
        "favorable_bound": {
            "point": favorable_injected.get("delta_bp"),
            "crossed_ci95": favorable_injected.get("crossed_ci95"),
            "injected_control_pass": favorable_injected_pass,
            "analytical_power_pass": power_pass(favorable.get("crossed_power_at_plus5")),
        },
    }
    result["concentration"] = concentration(books["E_BOT500"], books["E30"])
    result["positive_sensitivity_pass"] = positive_sensitivity
    result["null_sensitivity_pass"] = null_sensitivity
    result["positive_promotion_eligible"] = False
    result["method_null_eligible"] = False
    actual_powered = bool(
        result.get("crossed_mde80_bp") is not None
        and result["crossed_mde80_bp"] <= 5
        and power_pass(result.get("crossed_power_at_plus5"))
        and injected_pass
    )
    if not rate_ok:
        result["verdict_status"] = "MISSINGNESS_UNRESOLVED"
    elif positive_sensitivity or null_sensitivity:
        result["verdict_status"] = "BURNED_DIRECTION_ONLY"
    elif not actual_powered:
        result["verdict_status"] = "INCONCLUSIVE_UNDERPOWERED"
    else:
        result["verdict_status"] = "INCONCLUSIVE"
    report: dict[str, object] = {
        "status": "BURNED_POSTHOC_EFRON_BOT500_BOOK_DIAGNOSTIC",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "config": {
            "arms": list(ARMS),
            "primary": "E_BOT500__minus__E30",
            "bot_max": BOT_MAX,
            "unit_usd": UNIT_USD,
            "coin_cap_usd": COIN_CAP_USD,
            "hold_h": HOLD_MS / 3_600_000,
            "cost_bp": COST_BP,
            "n_boot": N_BOOT,
            "seed": SEED,
            "architecture_sha256": file_sha256(ARCH),
            "code_sha256": _code_sha256(Path(__file__)),
            "inference_dependency_sha256": roster_report["config"]["extension_inference_sha256"],
            "roster_report_file_sha256": roster_file_sha,
            "parent_rosters_file_sha256": roster_report["config"]["parent_rosters_file_sha256"],
            "parent_book_file_sha256": roster_report["config"]["parent_book_file_sha256"],
            "entry_meta_sha256": entry_meta_sha,
            "entry_parquet": entry_file_records,
            "consensus": "excluded",
        },
        "selector": roster_report,
        "funnels": funnels,
        "books": {
            arm: {
                **book_stats(books[arm]),
                "missingness": missing_stats(capacity[arm]),
                "raw": raw_stats(raw_books[arm]),
            }
            for arm in ARMS
        },
        "primary": result,
    }
    final_con = lake.connect(mem="2GB", threads=2)
    try:
        validate_final_snapshot(
            final_con,
            roster_report,
            roster_file_sha,
            entry_meta_sha,
            entry_file_records,
        )
    finally:
        final_con.close()
    atomic_json(OUT, report)
    return report


def run() -> dict[str, object]:
    try:
        return _run()
    except Exception as exc:
        try:
            current = json.loads(OUT.read_text()) if OUT.exists() else {}
        except Exception:
            current = {}
        if current.get("status") not in {
            "SELECTOR_PARITY_FAILURE",
            "OUTCOME_BUILD_FAILURE_NO_RESULTS",
        }:
            write_nonresult("RUN_FAILURE_NO_RESULTS", f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    run()
