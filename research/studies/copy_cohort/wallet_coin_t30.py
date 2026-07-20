"""Burned forensic wallet×coin top-30 majors selector and fixed 8h capacity book."""

from __future__ import annotations

import heapq
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT

from . import lake
from .alt_fresh_validate import MAJORS, STALE_MS, _ctx_parts
from .dynamic_t_book import compare
from .dynamic_t_quality import FOLDS, formation_months
from .efron_bot500 import ENTRIES as EFRON_ENTRIES
from .efron_bot500 import (
    PARENT_BOOK as EFRON_PARENT_BOOK,
)
from .efron_bot500 import (
    PARENT_ROSTERS as NESTED_ROSTERS,
)
from .efron_bot500 import (
    ROSTERS as EFRON_ROSTERS,
)
from .efron_bot500 import (
    atomic_json,
    bound_entry_meta,
    common_cutoff,
    efron_roster,
    entry_cache_valid,
    entry_data_record,
    file_sha256,
    rate_gates,
    validate_parents,
)
from .efron_bot500 import (
    load_panel_scores as load_parent_scores,
)
from .filtered_quality import _code_sha256, _sha256_json
from .nested_t_book import ENTRIES as NESTED_ENTRIES
from .nested_t_book import (
    bounded,
    concentration,
    holm,
    missing_stats,
    raw_stats,
)
from .nested_t_book import (
    capacity_book as parent_capacity_book,
)
from .nested_t_book import (
    load_entries as load_parent_entries,
)

ARCH = Path(__file__).with_name("WALLET_COIN_T30_ARCH.md")
DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "wallet_coin_t30"
PANELS = DERIVED / "panels"
ENTRIES = DERIVED / "entries"
PENDING_ENTRIES = DERIVED / "pending_entries"
ROSTERS = DERIVED / "rosters.json"
OUT = DERIVED / "book_report.json"

CAP = 100_000.0
ND_MIN = 15
TOP_K = 30
NOTIONAL_MIN = 250.0
UNIT_USD = 5_000.0
COIN_CAP_USD = 50_000.0
HOLD_MS = 8 * 3_600_000
COST_BP = 5.5
MISSING_BOUND_BP = 2_000.0
N_BOOT = 10_000
SEED = 20260721
DAY_MS = 86_400_000
POINT_TOL = 1e-10

ARMS = (
    "PAIR_T30",
    "WALLET_T30",
    "PAIR_E30",
    "WALLET_E30",
    "PAIR_T30_WALLETDAYCAP",
)
PAIR_ARMS = {"PAIR_T30", "PAIR_E30", "PAIR_T30_WALLETDAYCAP"}
CONTRASTS = {
    "PAIR_T30__minus__WALLET_T30": ("PAIR_T30", "WALLET_T30", SEED),
    "PAIR_E30__minus__WALLET_E30": ("PAIR_E30", "WALLET_E30", SEED + 1),
    "PAIR_T30_WALLETDAYCAP__minus__WALLET_T30": (
        "PAIR_T30_WALLETDAYCAP",
        "WALLET_T30",
        SEED + 2,
    ),
    "PAIR_T30__minus__PAIR_T30_WALLETDAYCAP": (
        "PAIR_T30",
        "PAIR_T30_WALLETDAYCAP",
        SEED + 3,
    ),
}
PRIMARY = "PAIR_T30__minus__WALLET_T30"


def dependency_hashes() -> dict[str, str]:
    names = (
        "alt_fresh_validate.py",
        "dynamic_t_book.py",
        "dynamic_t_quality.py",
        "efron_bot500.py",
        "filtered_quality.py",
        "informed.py",
        "lake.py",
        "nested_t_book.py",
        "nested_t_filter.py",
    )
    return {name: file_sha256(Path(__file__).with_name(name)) for name in names}


def _file_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "size": path.stat().st_size, "sha256": file_sha256(path)}


def _ctx_records(paths: list[str]) -> list[dict[str, object]]:
    return [_file_record(Path(p)) for p in paths]


def _write_nonresult(path: Path, status: str, error: str | None = None) -> None:
    payload: dict[str, object] = {
        "status": status,
        "comparative_results_present": False,
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
    }
    if error is not None:
        payload["error"] = error
    atomic_json(path, payload)


def _panel_spec(con, fold: int) -> dict[str, object]:
    return {
        "schema": "wallet-coin-t30-panel-v1",
        "fold": fold,
        "formation_months": formation_months(fold),
        "source_lineage": lake.validated_lineage(
            con, formation_months(fold), ("alt_universe_wallet_coin_day",)
        ),
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "dependencies": dependency_hashes(),
        "config": {
            "majors": list(MAJORS),
            "cap": CAP,
            "nd_min": ND_MIN,
            "pair_x": "pair_day_pnl*min(1,100000/pair_day_notional)",
            "walletdaycap_x": "pair_day_pnl*min(1,100000/wallet_day_majors_notional)",
            "fee": "sum(pnl)-sum(fee)",
        },
    }


def cache_pair_panel(con, fold: int) -> Path:
    PANELS.mkdir(parents=True, exist_ok=True)
    path = PANELS / f"pair_daily_{fold}.parquet"
    meta = path.with_suffix(".meta.json")
    spec = _panel_spec(con, fold)
    if entry_cache_valid(path, meta, spec):
        return path
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in formation_months(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH pair_day AS (
        SELECT lower(wallet) AS wallet,coin,day,
          SUM(CAST(pnl AS DECIMAL(38,10)))-SUM(CAST(fee AS DECIMAL(38,10))) AS pair_pnl,
          SUM(CAST(notional AS DECIMAL(38,20))) AS pair_notional
        FROM read_parquet([{globs}]) WHERE coin IN ({majors})
        GROUP BY lower(wallet),coin,day
      ), wallet_day AS (
        SELECT wallet,day,SUM(pair_pnl) AS wallet_pnl,SUM(pair_notional) AS wallet_notional
        FROM pair_day GROUP BY wallet,day
      )
      SELECT p.wallet,p.coin,p.day,p.pair_pnl,p.pair_notional,
        w.wallet_pnl,w.wallet_notional,
        CAST(p.pair_pnl*LEAST(1::DECIMAL(38,20),
          CAST({CAP} AS DECIMAL(38,20))/GREATEST(p.pair_notional,1e-12::DECIMAL(38,20)))
          AS DOUBLE) AS x_pair,
        CAST(p.pair_pnl*LEAST(1::DECIMAL(38,20),
          CAST({CAP} AS DECIMAL(38,20))/GREATEST(w.wallet_notional,1e-12::DECIMAL(38,20)))
          AS DOUBLE) AS x_walletdaycap
      FROM pair_day p JOIN wallet_day w USING(wallet,day)
      ORDER BY wallet,coin,day
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post = lake.validated_lineage(con, formation_months(fold), ("alt_universe_wallet_coin_day",))
    if post != spec["source_lineage"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: formation source mutated during pair-panel build")
    tmp.replace(path)
    atomic_json(meta, bound_entry_meta(path, spec))
    return path


def validate_panel_cache(con, fold: int, path: Path) -> None:
    meta = path.with_suffix(".meta.json")
    payload = json.loads(meta.read_text())
    if payload.get("spec") != _panel_spec(con, fold):
        raise RuntimeError(f"fold {fold}: pair-panel spec/lineage changed after load")
    if payload.get("data") != entry_data_record(path):
        raise RuntimeError(f"fold {fold}: pair-panel bytes changed after load")


def _group_scores(
    keys: np.ndarray, x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    keys = np.asarray(keys, str)
    x = np.asarray(x, float)
    unique, starts, counts = np.unique(keys, return_index=True, return_counts=True)
    expected = np.r_[0, np.cumsum(counts[:-1])]
    if not np.array_equal(starts, expected):
        raise RuntimeError("score keys are not sorted contiguously")
    mean = np.add.reduceat(x, starts) / counts
    centered = x - np.repeat(mean, counts)
    ss = np.add.reduceat(centered * centered, starts)
    sd = np.full(unique.size, np.nan)
    enough = counts >= ND_MIN
    sd[enough] = np.sqrt(ss[enough] / (counts[enough] - 1))
    t = np.full(unique.size, np.nan)
    good = enough & np.isfinite(sd) & (sd > 0)
    t[good] = mean[good] / (sd[good] / np.sqrt(counts[good]))
    return unique, counts.astype(float), mean, sd, t


def _top_pairs(keys: np.ndarray, score: np.ndarray) -> list[tuple[str, str]]:
    good = np.isfinite(score)
    kk, ss = keys[good], score[good]
    wallet = np.asarray([v.split("\x1f", 1)[0] for v in kk])
    coin = np.asarray([v.split("\x1f", 1)[1] for v in kk])
    if kk.size < TOP_K:
        raise RuntimeError(f"pair pool only {kk.size}")
    order = np.lexsort((coin, wallet, -ss))[:TOP_K]
    return [(str(wallet[i]), str(coin[i])) for i in order]


def _efron_pairs(
    keys: np.ndarray, nd: np.ndarray, score: np.ndarray
) -> tuple[list[tuple[str, str]], dict[str, object]]:
    eligible = np.isfinite(score)
    roster, fit = efron_roster(keys, nd, score, eligible)
    pairs = [tuple(v.split("\x1f", 1)) for v in roster]
    return [(str(w), str(c)) for w, c in pairs], fit


def _parent_wallet_daily(path: Path) -> dict[str, np.ndarray]:
    d = pq.read_table(path, columns=["wallet", "day", "day_pnl", "day_notional"]).to_pydict()
    return {
        "wallet": np.asarray(d["wallet"], str),
        "day": np.asarray(d["day"], np.int64),
        "pnl": np.asarray([float(v) for v in d["day_pnl"]], float),
        "notional": np.asarray([float(v) for v in d["day_notional"]], float),
    }


def _pair_panel_arrays(path: Path) -> dict[str, np.ndarray]:
    d = pq.read_table(path).to_pydict()
    return {
        "wallet": np.asarray(d["wallet"], str),
        "coin": np.asarray(d["coin"], str),
        "day": np.asarray(d["day"], np.int64),
        "pair_pnl": np.asarray([float(v) for v in d["pair_pnl"]], float),
        "pair_notional": np.asarray([float(v) for v in d["pair_notional"]], float),
        "wallet_pnl": np.asarray([float(v) for v in d["wallet_pnl"]], float),
        "wallet_notional": np.asarray([float(v) for v in d["wallet_notional"]], float),
        "x_pair": np.asarray(d["x_pair"], float),
        "x_walletdaycap": np.asarray(d["x_walletdaycap"], float),
    }


def _wallet_rows_from_pairs(d: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    key = np.char.add(np.char.add(d["wallet"], "\x1f"), d["day"].astype(str))
    unique, first, inv = np.unique(key, return_index=True, return_inverse=True)
    del unique
    order = np.lexsort((d["day"][first], d["wallet"][first]))
    return {
        "wallet": d["wallet"][first][order],
        "day": d["day"][first][order],
        "pnl": np.bincount(inv, weights=d["pair_pnl"])[order],
        "notional": np.bincount(inv, weights=d["pair_notional"])[order],
    }


def _wallet_x(pnl: np.ndarray, notional: np.ndarray) -> np.ndarray:
    return pnl * np.minimum(1.0, CAP / np.maximum(notional, 1e-12))


def _score_hash(
    keys: np.ndarray, nd: np.ndarray, mean: np.ndarray, sd: np.ndarray, t: np.ndarray
) -> str:
    rows = [
        {
            "key": str(k),
            "nd": int(n),
            "mean": float(m),
            "sd": float(s),
            "t": float(v),
        }
        for k, n, m, s, v in zip(keys, nd, mean, sd, t, strict=True)
        if np.isfinite(v)
    ]
    return _sha256_json(rows)


def build_rosters(con) -> dict[str, object]:
    nested = json.loads(NESTED_ROSTERS.read_text())
    validate_parents(con, nested)
    saved_efron = json.loads(EFRON_ROSTERS.read_text())
    if saved_efron.get("status") != "BURNED_POSTHOC_EFRON_BOT500_SELECTOR":
        raise RuntimeError("saved Efron roster artifact is not successful")
    report: dict[str, object] = {
        "status": "BURNED_REOPENED_WALLET_COIN_FORENSIC_SELECTOR",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "config": {
            "arms": list(ARMS),
            "majors": list(MAJORS),
            "cap": CAP,
            "nd_min": ND_MIN,
            "top_k": TOP_K,
            "architecture_sha256": file_sha256(ARCH),
            "code_sha256": _code_sha256(Path(__file__)),
            "dependency_hashes": dependency_hashes(),
            "parent_nested_rosters_sha256": file_sha256(NESTED_ROSTERS),
            "parent_efron_rosters_sha256": file_sha256(EFRON_ROSTERS),
            "parent_book_sha256": file_sha256(EFRON_PARENT_BOOK),
            "consensus": "excluded",
        },
        "folds": {},
    }
    for fold in FOLDS:
        print(f"[wallet-coin selector] {fold}", flush=True)
        panel = cache_pair_panel(con, fold)
        d = _pair_panel_arrays(panel)
        ours = _wallet_rows_from_pairs(d)
        parent_path = Path(nested["folds"][str(fold)]["panel_path"])
        parent = _parent_wallet_daily(parent_path)
        if not np.array_equal(ours["wallet"], parent["wallet"]) or not np.array_equal(
            ours["day"], parent["day"]
        ):
            raise RuntimeError(f"fold {fold}: full wallet-day identity parity failed")
        pnl_diff = float(np.max(np.abs(ours["pnl"] - parent["pnl"])))
        notl_diff = float(np.max(np.abs(ours["notional"] - parent["notional"])))
        if not np.allclose(ours["pnl"], parent["pnl"], atol=1e-9, rtol=1e-12):
            raise RuntimeError(f"fold {fold}: wallet-day PnL parity failed {pnl_diff}")
        if not np.allclose(ours["notional"], parent["notional"], atol=1e-9, rtol=1e-12):
            raise RuntimeError(f"fold {fold}: wallet-day notional parity failed {notl_diff}")
        wx = _wallet_x(ours["pnl"], ours["notional"])
        wkeys, wnd, wmean, wsd, wt = _group_scores(ours["wallet"], wx)
        parent_x = _wallet_x(parent["pnl"], parent["notional"])
        if not np.allclose(wx, parent_x, atol=1e-9, rtol=1e-12):
            raise RuntimeError(f"fold {fold}: wallet-day normalized-x parity failed")
        pw, pnd, pmean, psd, pwt = _group_scores(parent["wallet"], parent_x)
        for name, left, right in (
            ("wallet", wkeys, pw),
            ("nd", wnd, pnd),
            ("mean", wmean, pmean),
            ("sd", wsd, psd),
            ("t", wt, pwt),
        ):
            same = (
                np.array_equal(left, right)
                if name == "wallet"
                else np.allclose(left, right, atol=1e-9, rtol=1e-12, equal_nan=True)
            )
            if not same:
                raise RuntimeError(f"fold {fold}: full-pool {name} parity failed")
        # Controls use the parent's exact score representation after the independent
        # reconstruction above has established numerical equivalence. Re-aggregating
        # pair rows changes a few terminal float bits and must not silently change the
        # frozen Efron input hash.
        control_w, control_nd, control_t, _control_fpd = load_parent_scores(parent_path)
        if (
            not np.array_equal(control_w, wkeys)
            or not np.array_equal(control_nd.astype(np.int64), wnd)
            or not np.allclose(control_t, wt, atol=1e-9, rtol=1e-12, equal_nan=True)
        ):
            raise RuntimeError(f"fold {fold}: authoritative wallet control score parity failed")
        goodw = np.isfinite(control_t)
        wallet_t30 = control_w[goodw][
            np.lexsort((control_w[goodw], -control_t[goodw]))[:TOP_K]
        ].tolist()
        saved_t30 = nested["folds"][str(fold)]["rosters"]["STATIC_T30"]
        if wallet_t30 != saved_t30:
            raise RuntimeError(f"fold {fold}: WALLET_T30 roster parity failed")
        wallet_e30, wallet_fit = efron_roster(control_w, control_nd, control_t, goodw)
        saved_e30 = saved_efron["folds"][str(fold)]["rosters"]["E30"]
        saved_fit = saved_efron["folds"][str(fold)]["fit_E30"]
        if wallet_e30 != saved_e30:
            raise RuntimeError(f"fold {fold}: WALLET_E30 roster parity failed")
        for name in ("ordered_input_sha256", "n_fit", "n_positive_t"):
            if wallet_fit[name] != saved_fit[name]:
                raise RuntimeError(f"fold {fold}: Efron full-pool {name} parity failed")
        for name in ("mu0", "sigma0", "pi0"):
            if not math.isclose(wallet_fit[name], saved_fit[name], abs_tol=1e-12, rel_tol=1e-12):
                raise RuntimeError(f"fold {fold}: Efron fit {name} parity failed")

        pkey = np.char.add(np.char.add(d["wallet"], "\x1f"), d["coin"])
        pair_key, pnd, pmean, psd, pt = _group_scores(pkey, d["x_pair"])
        pair_t30 = _top_pairs(pair_key, pt)
        pair_e30, pair_fit = _efron_pairs(pair_key, pnd, pt)
        cap_key, cnd, cmean, csd, ct = _group_scores(pkey, d["x_walletdaycap"])
        if not np.array_equal(pair_key, cap_key) or not np.array_equal(pnd, cnd):
            raise RuntimeError(f"fold {fold}: pair cap construction pool mismatch")
        pair_cap = _top_pairs(cap_key, ct)
        eligible_pair_counts = Counter(v.split("\x1f", 1)[0] for v in pair_key[np.isfinite(pt)])
        rosters: dict[str, Any] = {
            "PAIR_T30": [{"wallet": w, "coin": c} for w, c in pair_t30],
            "WALLET_T30": wallet_t30,
            "PAIR_E30": [{"wallet": w, "coin": c} for w, c in pair_e30],
            "WALLET_E30": wallet_e30,
            "PAIR_T30_WALLETDAYCAP": [{"wallet": w, "coin": c} for w, c in pair_cap],
        }
        for arm in ARMS:
            vals = rosters[arm]
            if len(vals) != TOP_K or len({json.dumps(v, sort_keys=True) for v in vals}) != TOP_K:
                raise RuntimeError(f"fold {fold}: {arm} exact top-30 invariant failed")
        report["folds"][str(fold)] = {
            "formation_source_lineage": _panel_spec(con, fold)["source_lineage"],
            "pair_panel": _file_record(panel),
            "pair_panel_meta_sha256": file_sha256(panel.with_suffix(".meta.json")),
            "wallet_day_parity": {
                "n_rows": int(ours["wallet"].size),
                "max_abs_pnl": pnl_diff,
                "max_abs_notional": notl_diff,
                "score_hash": _score_hash(wkeys, wnd, wmean, wsd, wt),
                "parent_panel_sha256": file_sha256(parent_path),
            },
            "pair_pool": {
                "n_total_pairs": int(pair_key.size),
                "n_eligible_pairs": int(np.isfinite(pt).sum()),
                "n_eligible_wallets": int(
                    np.unique([v.split("\x1f", 1)[0] for v in pair_key[np.isfinite(pt)]]).size
                ),
                "score_hash_paircap": _score_hash(pair_key, pnd, pmean, psd, pt),
                "score_hash_walletdaycap": _score_hash(cap_key, cnd, cmean, csd, ct),
                "eligible_pairs_per_wallet": dict(sorted(eligible_pair_counts.items())),
            },
            "fits": {"WALLET_E30": wallet_fit, "PAIR_E30": pair_fit},
            "rosters": rosters,
            "unique_selected_wallets": {
                arm: len(
                    {v["wallet"] for v in rosters[arm]} if arm in PAIR_ARMS else set(rosters[arm])
                )
                for arm in ARMS
            },
        }
        validate_panel_cache(con, fold, panel)
    for fold in FOLDS:
        item = report["folds"][str(fold)]
        validate_panel_cache(con, fold, Path(item["pair_panel"]["path"]))
    if report["config"]["dependency_hashes"] != dependency_hashes():
        raise RuntimeError("selector dependencies changed before roster publication")
    if report["config"]["parent_nested_rosters_sha256"] != file_sha256(NESTED_ROSTERS):
        raise RuntimeError("nested parent changed before roster publication")
    if report["config"]["parent_efron_rosters_sha256"] != file_sha256(EFRON_ROSTERS):
        raise RuntimeError("Efron parent changed before roster publication")
    report["rosters_sha256"] = _sha256_json(
        {fold: item["rosters"] for fold, item in report["folds"].items()}
    )
    atomic_json(ROSTERS, report)
    return report


def _entry_spec(
    con, fold: int, fold_rosters: dict[str, Any], roster_file_sha: str
) -> tuple[dict[str, object], int, list[str]]:
    wallets = sorted(
        {
            v["wallet"] if arm in PAIR_ARMS else v
            for arm, roster in fold_rosters.items()
            for v in roster
        }
    )
    context_paths = _ctx_parts(fold)
    maxima, cutoff = common_cutoff(con, context_paths)
    spec = {
        "schema": "wallet-coin-t30-entry-v1-source-identity",
        "fold": fold,
        "wallets": wallets,
        "wallets_sha256": _sha256_json(wallets),
        "arm_rosters_sha256": _sha256_json(fold_rosters),
        "roster_report_file_sha256": roster_file_sha,
        "source_lineage": lake.validated_lineage(con, [fold], ("alt_universe_open_entries",)),
        "context": _ctx_records(context_paths),
        "context_max_ts_by_coin": maxima,
        "common_cutoff": cutoff,
        "architecture_sha256": file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "dependency_hashes": dependency_hashes(),
        "config": {
            "majors": list(MAJORS),
            "notional_min": NOTIONAL_MIN,
            "hold_ms": HOLD_MS,
            "stale_ms": STALE_MS,
            "order": ["ts", "wallet", "coin", "dir_sign", "notional", "source_id"],
        },
    }
    return spec, cutoff, context_paths


def cache_entries(
    con,
    fold: int,
    fold_rosters: dict[str, Any],
    roster_sha: str,
    *,
    directory: Path = PENDING_ENTRIES,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"entries_{fold}.parquet"
    meta = path.with_suffix(".meta.json")
    spec, cutoff, context_paths = _entry_spec(con, fold, fold_rosters, roster_sha)
    if entry_cache_valid(path, meta, spec):
        return path
    con.execute(
        "CREATE OR REPLACE TEMP TABLE wc_wallet AS SELECT UNNEST(?) wallet", [spec["wallets"]]
    )
    ctx_list = ",".join(f"'{p}'" for p in context_paths)
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH ent AS (
        SELECT lower(o.wallet) AS wallet,o.coin,o.ts,o.dir_sign,
          CAST(o.notl AS DOUBLE) AS notional,
          o.filename||'#'||CAST(o.file_row_number AS VARCHAR) AS source_id
        FROM read_parquet('{lake.ope_month_glob(fold)}',filename=true,file_row_number=true) o
        JOIN wc_wallet w ON lower(o.wallet)=w.wallet
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
      FROM p8 ORDER BY ts,wallet,coin,dir_sign,notional,source_id
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post = lake.validated_lineage(con, [fold], ("alt_universe_open_entries",))
    if post != spec["source_lineage"] or _ctx_records(context_paths) != spec["context"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: evaluation source/context mutated")
    tmp.replace(path)
    atomic_json(meta, bound_entry_meta(path, spec))
    return path


def load_entries(path: Path, fold: int) -> dict[str, np.ndarray]:
    d = pq.read_table(path).to_pydict()
    n = len(d["wallet"])
    out = {
        "wallet": np.asarray(d["wallet"], str),
        "coin": np.asarray(d["coin"], str),
        "ts": np.asarray(d["ts"], np.int64),
        "dir_sign": np.asarray(d["dir_sign"], float),
        "notional": np.asarray(d["notional"], float),
        "source_id": np.asarray(d["source_id"], str),
        "gross_bp": np.asarray([math.nan if v is None else float(v) for v in d["gross_bp"]]),
        "fold": np.full(n, fold, np.int64),
    }
    order = np.lexsort(
        (
            out["source_id"],
            out["notional"],
            out["dir_sign"],
            out["coin"],
            out["wallet"],
            out["ts"],
        )
    )
    return {k: v[order] for k, v in out.items()}


def validate_entry_cache(
    con,
    fold: int,
    path: Path,
    fold_rosters: dict[str, Any],
    roster_sha: str,
) -> None:
    payload = json.loads(path.with_suffix(".meta.json").read_text())
    expected, _cutoff, _context = _entry_spec(con, fold, fold_rosters, roster_sha)
    if payload.get("spec") != expected:
        raise RuntimeError(f"fold {fold}: entry spec/lineage/context changed after load")
    if payload.get("data") != entry_data_record(path):
        raise RuntimeError(f"fold {fold}: entry bytes changed after load")


def promote_entries(paths: dict[str, Path]) -> dict[str, dict[str, object]]:
    ENTRIES.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, object]] = {}
    for fold in FOLDS:
        source = paths[str(fold)]
        source_meta = source.with_suffix(".meta.json")
        spec = json.loads(source_meta.read_text())["spec"]
        target = ENTRIES / source.name
        target_meta = target.with_suffix(".meta.json")
        source.replace(target)
        atomic_json(target_meta, bound_entry_meta(target, spec))
        source_meta.unlink(missing_ok=True)
        records[str(fold)] = {
            "parquet": entry_data_record(target),
            "meta_sha256": file_sha256(target_meta),
        }
    return records


def _concat(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    out = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    order = np.lexsort(
        (out["source_id"], out["notional"], out["dir_sign"], out["coin"], out["wallet"], out["ts"])
    )
    return {k: v[order] for k, v in out.items()}


def _arm_mask(entries: dict[str, np.ndarray], rosters: dict[str, Any], arm: str) -> np.ndarray:
    by_fold = {str(f): rosters[str(f)] for f in FOLDS}
    if arm in PAIR_ARMS:
        sets = {f: {(v["wallet"], v["coin"]) for v in roster} for f, roster in by_fold.items()}
        return np.asarray(
            [
                (str(w), str(c)) in sets[str(int(f))]
                for w, c, f in zip(entries["wallet"], entries["coin"], entries["fold"], strict=True)
            ],
            bool,
        )
    sets = {f: set(roster) for f, roster in by_fold.items()}
    return np.asarray(
        [
            str(w) in sets[str(int(f))]
            for w, f in zip(entries["wallet"], entries["fold"], strict=True)
        ],
        bool,
    )


def selected_raw(
    entries: dict[str, np.ndarray], rosters: dict[str, Any], arm: str
) -> dict[str, np.ndarray]:
    m = _arm_mask(entries, rosters, arm) & np.isfinite(entries["gross_bp"])
    return {
        "wallet": entries["wallet"][m],
        "fold": entries["fold"][m],
        "gross_bp": entries["gross_bp"][m],
    }


def selected_entries(
    entries: dict[str, np.ndarray], rosters: dict[str, Any], arm: str
) -> dict[str, np.ndarray]:
    m = _arm_mask(entries, rosters, arm)
    return {k: v[m] for k, v in entries.items()}


def capacity_book(
    entries: dict[str, np.ndarray], rosters: dict[str, Any], arm: str
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, int]]]:
    if np.any(np.diff(entries["ts"]) < 0):
        raise RuntimeError("entry stream is not chronological")
    idx = np.flatnonzero(_arm_mask(entries, rosters, arm))
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
            _, ow, oc = heapq.heappop(exits)
            open_wc.discard((ow, oc))
            coin_gross[oc] = coin_gross.get(oc, 0.0) - UNIT_USD
        w, c = str(entries["wallet"][i]), str(entries["coin"][i])
        if (w, c) in open_wc:
            funnels[fold]["n_skip_wallet_coin"] += 1
            continue
        if coin_gross.get(c, 0.0) + UNIT_USD > COIN_CAP_USD + 1e-9:
            funnels[fold]["n_skip_coin_cap"] += 1
            continue
        open_wc.add((w, c))
        coin_gross[c] = coin_gross.get(c, 0.0) + UNIT_USD
        heapq.heappush(exits, (t + HOLD_MS, w, c))
        accepted.append(int(i))
        funnels[fold]["n_accepted_capacity"] += 1
    ii = np.asarray(accepted, np.int64)
    out = {k: v[ii] for k, v in entries.items()}
    out["supported"] = np.isfinite(out["gross_bp"])
    out["net_bp"] = out["gross_bp"] - COST_BP
    out["signal_ts"] = out["ts"]
    return out, funnels


def supported(cap: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {k: v[cap["supported"]] for k, v in cap.items()}


def _canonical_rows(rows: dict[str, np.ndarray], *, outcome: str) -> list[tuple[Any, ...]]:
    value = rows[outcome]
    return sorted(
        (
            str(rows["wallet"][i]),
            str(rows["coin"][i]),
            int(rows["ts"][i]),
            float(rows["dir_sign"][i]),
            float(rows["notional"][i]),
            None if not np.isfinite(float(value[i])) else float(value[i]),
            int(rows["fold"][i]),
        )
        for i in range(rows["wallet"].size)
    )


def _assert_canonical_equal(
    a: dict[str, np.ndarray], b: dict[str, np.ndarray], label: str, *, outcome: str
) -> None:
    aa, bb = _canonical_rows(a, outcome=outcome), _canonical_rows(b, outcome=outcome)
    if len(aa) != len(bb):
        raise RuntimeError(f"{label}: row count {len(aa)} != {len(bb)}")
    for x, y in zip(aa, bb, strict=True):
        if x[:5] != y[:5] or x[6] != y[6]:
            raise RuntimeError(f"{label}: row identity mismatch")
        if (x[5] is None) != (y[5] is None) or (
            x[5] is not None and not math.isclose(x[5], y[5], abs_tol=1e-10, rel_tol=1e-12)
        ):
            raise RuntimeError(f"{label}: outcome mismatch")


def _rows_sha(rows: dict[str, np.ndarray], outcome: str) -> str:
    return _sha256_json(_canonical_rows(rows, outcome=outcome))


def _ordered_rows_sha(rows: dict[str, np.ndarray], outcome: str) -> str:
    payload = [
        {
            "source_id": str(rows["source_id"][i]),
            "wallet": str(rows["wallet"][i]),
            "coin": str(rows["coin"][i]),
            "ts": int(rows["ts"][i]),
            "dir_sign": float(rows["dir_sign"][i]),
            "notional": float(rows["notional"][i]),
            outcome: (
                None if not np.isfinite(float(rows[outcome][i])) else float(rows[outcome][i])
            ),
            "fold": int(rows["fold"][i]),
        }
        for i in range(rows["wallet"].size)
    ]
    return _sha256_json(payload)


def _pair_oracle(
    con, fold: int, fold_rosters: dict[str, Any], entries: dict[str, np.ndarray]
) -> dict[str, object]:
    pairs = sorted({(v["wallet"], v["coin"]) for arm in PAIR_ARMS for v in fold_rosters[arm]})
    con.execute(
        "CREATE OR REPLACE TEMP TABLE wc_pair_oracle AS SELECT UNNEST(?) wallet,UNNEST(?) coin",
        [[w for w, _ in pairs], [c for _, c in pairs]],
    )
    _maxima, cutoff = common_cutoff(con, _ctx_parts(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    rows = con.execute(f"""
      SELECT lower(o.wallet),o.coin,o.ts,o.dir_sign,CAST(o.notl AS DOUBLE),
        o.filename||'#'||CAST(o.file_row_number AS VARCHAR) AS source_id
      FROM read_parquet('{lake.ope_month_glob(fold)}',filename=true,file_row_number=true) o
      JOIN wc_pair_oracle s ON lower(o.wallet)=s.wallet AND o.coin=s.coin
      WHERE o.coin IN ({majors}) AND CAST(o.notl AS DOUBLE)>={NOTIONAL_MIN} AND o.ts<={cutoff}
      ORDER BY o.ts,lower(o.wallet),o.coin,o.dir_sign,CAST(o.notl AS DOUBLE),source_id
    """).fetchall()
    expected_rows = [
        (str(r[5]), str(r[0]), str(r[1]), int(r[2]), float(r[3]), float(r[4])) for r in rows
    ]
    expected = [r[0] for r in expected_rows]
    pair_set = set(pairs)
    got_rows = [
        (
            str(entries["source_id"][i]),
            str(entries["wallet"][i]),
            str(entries["coin"][i]),
            int(entries["ts"][i]),
            float(entries["dir_sign"][i]),
            float(entries["notional"][i]),
        )
        for i in range(entries["wallet"].size)
        if (str(entries["wallet"][i]), str(entries["coin"][i])) in pair_set
    ]
    got = [r[0] for r in got_rows]
    ce, cg = Counter(expected), Counter(got)
    missing = sum((ce - cg).values())
    extra = sum((cg - ce).values())
    duplicate_expected = sum(v - 1 for v in ce.values() if v > 1)
    duplicate_got = sum(v - 1 for v in cg.values() if v > 1)
    order_mismatch = expected_rows != got_rows
    if missing or extra or duplicate_expected or duplicate_got or order_mismatch:
        raise RuntimeError(
            f"fold {fold}: pair completeness failed missing={missing} extra={extra} "
            f"dup_expected={duplicate_expected} dup_got={duplicate_got} "
            f"order_mismatch={order_mismatch}"
        )
    return {
        "n_expected": len(expected),
        "n_emitted": len(got),
        "missing": missing,
        "extra": extra,
        "duplicate_expected": duplicate_expected,
        "duplicate_emitted": duplicate_got,
        "order_mismatch": order_mismatch,
        "oracle_ordered_rows_sha256": _sha256_json(expected_rows),
        "emitted_ordered_rows_sha256": _sha256_json(got_rows),
    }


def _parent_entry_parts(base: Path) -> list[dict[str, np.ndarray]]:
    return [load_parent_entries(base / f"entries_{f}.parquet", f) for f in FOLDS]


def _parent_global(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    keys = parts[0].keys()
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    if "ts" not in out:
        out["ts"] = out["signal_ts"]
    return out


def _wallet_control_source_oracle(
    con,
    fold: int,
    members: list[str],
    entries: dict[str, np.ndarray],
) -> dict[str, object]:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE wc_control_wallet AS SELECT UNNEST(?) wallet",
        [members],
    )
    _maxima, cutoff = common_cutoff(con, _ctx_parts(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    rows = con.execute(f"""
      SELECT o.filename||'#'||CAST(o.file_row_number AS VARCHAR) AS source_id,
        lower(o.wallet),o.coin,o.ts,o.dir_sign,CAST(o.notl AS DOUBLE)
      FROM read_parquet('{lake.ope_month_glob(fold)}',filename=true,file_row_number=true) o
      JOIN wc_control_wallet s ON lower(o.wallet)=s.wallet
      WHERE o.coin IN ({majors}) AND CAST(o.notl AS DOUBLE)>={NOTIONAL_MIN} AND o.ts<={cutoff}
      ORDER BY o.ts,lower(o.wallet),o.coin,o.dir_sign,CAST(o.notl AS DOUBLE),source_id
    """).fetchall()
    expected = [
        (str(r[0]), str(r[1]), str(r[2]), int(r[3]), float(r[4]), float(r[5])) for r in rows
    ]
    member_set = set(members)
    got = [
        (
            str(entries["source_id"][i]),
            str(entries["wallet"][i]),
            str(entries["coin"][i]),
            int(entries["ts"][i]),
            float(entries["dir_sign"][i]),
            float(entries["notional"][i]),
        )
        for i in range(entries["wallet"].size)
        if str(entries["wallet"][i]) in member_set
    ]
    if expected != got:
        raise RuntimeError(f"fold {fold}: wallet-control source identity/order parity failed")
    return {
        "n_rows": len(expected),
        "oracle_ordered_rows_sha256": _sha256_json(expected),
        "emitted_ordered_rows_sha256": _sha256_json(got),
    }


def control_parity(
    con,
    entries: dict[str, np.ndarray],
    rosters: dict[str, Any],
    entry_paths: dict[str, Path],
) -> dict[str, object]:
    # E30: exact globally continuous published construction.
    eparts = _parent_entry_parts(EFRON_ENTRIES)
    olde = _parent_global(eparts)
    saved_e = json.loads(EFRON_ROSTERS.read_text())
    old_erosters = {str(f): saved_e["folds"][str(f)]["rosters"]["E30"] for f in FOLDS}
    from .efron_bot500 import capacity_book_global as old_global_cap

    old_esel_mask = np.asarray(
        [
            str(w) in set(old_erosters[str(int(f))])
            for w, f in zip(olde["wallet"], olde["fold"], strict=True)
        ]
    )
    old_esel = {k: v[old_esel_mask] for k, v in olde.items()}
    new_esel = selected_entries(entries, rosters["WALLET_E30"], "WALLET_E30")
    _assert_canonical_equal(
        new_esel, old_esel, "WALLET_E30 pre-capacity parity", outcome="gross_bp"
    )
    old_ecap, old_efun = old_global_cap(olde, old_erosters)
    new_ecap, new_efun = capacity_book(entries, rosters["WALLET_E30"], "WALLET_E30")
    _assert_canonical_equal(new_ecap, old_ecap, "WALLET_E30 global book parity", outcome="gross_bp")
    if new_efun != old_efun:
        raise RuntimeError("WALLET_E30 global funnel parity failed")

    # T30: exact source/outcome equality plus fold-reset parent-capacity replay.
    # The main book remains globally continuous.
    nparts = _parent_entry_parts(NESTED_ENTRIES)
    old_t_parts = []
    new_t_parts = []
    fold_fun_old: dict[str, object] = {}
    fold_fun_new: dict[str, object] = {}
    saved_n = json.loads(NESTED_ROSTERS.read_text())
    old_t_rosters = {str(f): saved_n["folds"][str(f)]["rosters"]["STATIC_T30"] for f in FOLDS}
    old_t_global_entries = _parent_global(nparts)
    old_t_mask = np.asarray(
        [
            str(w) in set(old_t_rosters[str(int(f))])
            for w, f in zip(
                old_t_global_entries["wallet"], old_t_global_entries["fold"], strict=True
            )
        ]
    )
    old_t_selected = {k: v[old_t_mask] for k, v in old_t_global_entries.items()}
    new_t_selected = selected_entries(entries, rosters["WALLET_T30"], "WALLET_T30")
    _assert_canonical_equal(
        new_t_selected,
        old_t_selected,
        "WALLET_T30 pre-capacity parity",
        outcome="gross_bp",
    )
    old_t_global_cap, old_t_global_fun = capacity_book(
        old_t_global_entries, old_t_rosters, "WALLET_T30"
    )
    new_t_global_cap, new_t_global_fun = capacity_book(entries, rosters["WALLET_T30"], "WALLET_T30")
    _assert_canonical_equal(
        new_t_global_cap,
        old_t_global_cap,
        "WALLET_T30 global control oracle parity",
        outcome="gross_bp",
    )
    if new_t_global_fun != old_t_global_fun:
        raise RuntimeError("WALLET_T30 global control oracle funnel parity failed")
    for fold, oldent in zip(FOLDS, nparts, strict=True):
        members = saved_n["folds"][str(fold)]["rosters"]["STATIC_T30"]
        oldcap, ofun = parent_capacity_book(oldent, members)
        fold_mask = entries["fold"] == fold
        fold_entries = {k: v[fold_mask] for k, v in entries.items()}
        one_roster = {str(f): ([] if f != fold else members) for f in FOLDS}
        newcap, nfun_all = capacity_book(fold_entries, one_roster, "WALLET_T30")
        old_t_parts.append(oldcap)
        new_t_parts.append(newcap)
        fold_fun_old[str(fold)] = ofun
        fold_fun_new[str(fold)] = nfun_all[str(fold)]
    old_t = {k: np.concatenate([p[k] for p in old_t_parts]) for k in old_t_parts[0]}
    new_t = {k: np.concatenate([p[k] for p in new_t_parts]) for k in new_t_parts[0]}
    _assert_canonical_equal(new_t, old_t, "WALLET_T30 fold-reset book parity", outcome="gross_bp")
    if fold_fun_old != fold_fun_new:
        raise RuntimeError("WALLET_T30 fold-reset funnel parity failed")
    cutoff_checks = {}
    source_checks: dict[str, object] = {"WALLET_E30": {}, "WALLET_T30": {}}
    for fold in FOLDS:
        new_spec = json.loads(entry_paths[str(fold)].with_suffix(".meta.json").read_text())["spec"]
        e_spec = json.loads((EFRON_ENTRIES / f"entries_{fold}.meta.json").read_text())["spec"]
        n_spec = json.loads((NESTED_ENTRIES / f"entries_{fold}.meta.json").read_text())
        n_cutoff = n_spec.get("common_cutoff")
        if new_spec["common_cutoff"] != e_spec["common_cutoff"] or (
            n_cutoff is not None and new_spec["common_cutoff"] != n_cutoff
        ):
            raise RuntimeError(f"fold {fold}: control common-cutoff parity failed")
        cutoff_checks[str(fold)] = int(new_spec["common_cutoff"])
        fold_entries = {k: v[entries["fold"] == fold] for k, v in entries.items()}
        source_checks["WALLET_E30"][str(fold)] = _wallet_control_source_oracle(
            con, fold, rosters["WALLET_E30"][str(fold)], fold_entries
        )
        source_checks["WALLET_T30"][str(fold)] = _wallet_control_source_oracle(
            con, fold, rosters["WALLET_T30"][str(fold)], fold_entries
        )
    return {
        "WALLET_E30": {
            "pre_capacity_multiset_sha256": _rows_sha(new_esel, "gross_bp"),
            "capacity_multiset_sha256": _rows_sha(new_ecap, "gross_bp"),
            "ordered_capacity_sha256": _ordered_rows_sha(new_ecap, "gross_bp"),
            "funnels_exact": True,
            "n_accepted": int(new_ecap["wallet"].size),
        },
        "WALLET_T30_global": {
            "pre_capacity_multiset_sha256": _rows_sha(new_t_selected, "gross_bp"),
            "capacity_multiset_sha256": _rows_sha(new_t_global_cap, "gross_bp"),
            "ordered_capacity_sha256": _ordered_rows_sha(new_t_global_cap, "gross_bp"),
            "funnels_exact": True,
            "n_accepted": int(new_t_global_cap["wallet"].size),
        },
        "WALLET_T30_fold_reset": {
            "ordered_capacity_sha256": _rows_sha(new_t, "gross_bp"),
            "funnels_exact": True,
            "n_accepted": int(new_t["wallet"].size),
            "note": (
                "parity layer resets capacity by fold exactly like nested parent; "
                "main study is global"
            ),
        },
        "common_cutoff_by_fold": cutoff_checks,
        "source_identity_order": source_checks,
    }


def _book_stats(book: dict[str, np.ndarray]) -> dict[str, object]:
    bp = book["net_bp"]
    per_fold: dict[str, float | None] = {}
    for fold in FOLDS:
        m = book["fold"] == fold
        per_fold[str(fold)] = float(bp[m].mean()) if m.any() else None
    per_coin = {
        c: float(bp[book["coin"] == c].mean()) if np.any(book["coin"] == c) else None
        for c in MAJORS
    }
    positive = sum(v is not None and v > 0 for v in per_fold.values())
    evaluable = sum(v is not None for v in per_fold.values())
    return {
        "n_entries": int(bp.size),
        "n_wallets": int(np.unique(book["wallet"]).size),
        "n_pairs": int(np.unique(np.char.add(np.char.add(book["wallet"], "|"), book["coin"])).size),
        "net_mean_bp_per_trade": float(bp.mean()) if bp.size else None,
        "net_median_bp_per_trade": float(np.median(bp)) if bp.size else None,
        "net_hit_rate": float((bp > 0).mean()) if bp.size else None,
        "net_usd": float(bp.sum() * UNIT_USD / 1e4),
        "per_fold_net_mean_bp": per_fold,
        "positive_months": positive,
        "evaluable_months": evaluable,
        "calendar_months": len(FOLDS),
        "positive_months_label": f"{positive}/{evaluable}, {evaluable}/{len(FOLDS)} evaluable",
        "per_coin_net_mean_bp": per_coin,
        "supported_multiset_sha256": _rows_sha(book, "net_bp"),
        "supported_ordered_sha256": _ordered_rows_sha(book, "net_bp"),
    }


def _pair_cluster_book(book: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    out = {k: v.copy() for k, v in book.items()}
    out["wallet"] = np.char.add(np.char.add(out["wallet"], "|"), out["coin"])
    return out


def _concentration_details(
    a: dict[str, np.ndarray], b: dict[str, np.ndarray], *, pair: bool
) -> dict[str, object]:
    def labels(book: dict[str, np.ndarray]) -> np.ndarray:
        if pair:
            return np.char.add(np.char.add(book["wallet"], "|"), book["coin"])
        return book["wallet"]

    la, lb = labels(a), labels(b)
    units = sorted(set(la) | set(lb))
    rows = []
    for unit in units:
        ca = float(a["net_bp"][la == unit].sum() / max(a["net_bp"].size, 1))
        cb = float(b["net_bp"][lb == unit].sum() / max(b["net_bp"].size, 1))
        rows.append({"unit": str(unit), "contribution_bp": ca - cb})
    rows.sort(key=lambda row: (-abs(row["contribution_bp"]), row["unit"]))
    den = sum(abs(row["contribution_bp"]) for row in rows)
    for row in rows[:5]:
        row["share_of_absolute"] = abs(row["contribution_bp"]) / den if den else 0.0
    return {
        "n_contributing": sum(abs(row["contribution_bp"]) > 0 for row in rows),
        "top5_abs_share": (
            sum(abs(row["contribution_bp"]) for row in rows[:5]) / den if den else 0.0
        ),
        "top5": rows[:5],
    }


def pair_seat_support(
    entries: dict[str, np.ndarray],
    capacity: dict[str, np.ndarray],
    rosters: dict[str, Any],
    arm: str,
) -> dict[str, object] | None:
    if arm not in PAIR_ARMS:
        return None
    per_fold: dict[str, object] = {}
    total_zero_candidate = total_zero_supported = 0
    for fold in FOLDS:
        seats = rosters[str(fold)]
        rows = []
        for rank, seat in enumerate(seats, start=1):
            em = (
                (entries["fold"] == fold)
                & (entries["wallet"] == seat["wallet"])
                & (entries["coin"] == seat["coin"])
            )
            cm = (
                (capacity["fold"] == fold)
                & (capacity["wallet"] == seat["wallet"])
                & (capacity["coin"] == seat["coin"])
            )
            candidate = int(em.sum())
            accepted = int(cm.sum())
            supported_n = int(np.sum(cm & capacity["supported"]))
            missing = accepted - supported_n
            total_zero_candidate += candidate == 0
            total_zero_supported += supported_n == 0
            rows.append(
                {
                    "rank": rank,
                    "wallet": seat["wallet"],
                    "coin": seat["coin"],
                    "candidates": candidate,
                    "accepted_capacity": accepted,
                    "supported": supported_n,
                    "missing": missing,
                }
            )
        per_fold[str(fold)] = {
            "seats": rows,
            "zero_candidate_seats": sum(row["candidates"] == 0 for row in rows),
            "zero_supported_seats": sum(row["supported"] == 0 for row in rows),
        }
    return {
        "per_fold": per_fold,
        "zero_candidate_seats_total": total_zero_candidate,
        "zero_supported_seats_total": total_zero_supported,
        "total_seats": TOP_K * len(FOLDS),
    }


def _dual_compare(
    a: dict[str, np.ndarray], b: dict[str, np.ndarray], seed: int, lo: int, hi: int
) -> dict[str, object]:
    wallet = compare(a, b, seed, lo, hi, n_boot=N_BOOT)
    pair = compare(_pair_cluster_book(a), _pair_cluster_book(b), seed, lo, hi, n_boot=N_BOOT)
    if wallet.get("crossed_ci95") is None or pair.get("crossed_ci95") is None:
        return {"wallet_family": wallet, "pair_family": pair, "binding": None}
    wci, pci = wallet["crossed_ci95"], pair["crossed_ci95"]
    binding = {
        "delta_bp": wallet["delta_bp"],
        "crossed_ci95_envelope": [min(wci[0], pci[0]), max(wci[1], pci[1])],
        "mde80_bp": max(wallet["crossed_mde80_bp"], pair["crossed_mde80_bp"]),
        "power_at_plus5": min(wallet["crossed_power_at_plus5"], pair["crossed_power_at_plus5"]),
        "p_two_sided": max(wallet["crossed_p_two_sided"], pair["crossed_p_two_sided"]),
        "p_null_plus5": max(wallet["p_null_plus5_one_sided"], pair["p_null_plus5_one_sided"]),
    }
    return {"wallet_family": wallet, "pair_family": pair, "binding": binding}


def _dual_injected(
    a: dict[str, np.ndarray], b: dict[str, np.ndarray], seed: int, lo: int, hi: int
) -> dict[str, object]:
    aa, bb = {k: v.copy() for k, v in a.items()}, {k: v.copy() for k, v in b.items()}
    aa["net_bp"] = aa["net_bp"] - aa["net_bp"].mean() + 5.0
    bb["net_bp"] = bb["net_bp"] - bb["net_bp"].mean()
    out = _dual_compare(aa, bb, seed, lo, hi)
    bind = out.get("binding")
    passed = bool(
        bind and abs(bind["delta_bp"] - 5.0) <= POINT_TOL and bind["crossed_ci95_envelope"][0] > 0
    )
    out["pass"] = passed
    return out


def _contrast(
    a: dict[str, np.ndarray],
    b: dict[str, np.ndarray],
    cap_a: dict[str, np.ndarray],
    cap_b: dict[str, np.ndarray],
    seed: int,
    lo: int,
    hi: int,
) -> dict[str, object]:
    actual_a, actual_b = supported(cap_a), supported(cap_b)
    actual_a_sha, actual_b_sha = _rows_sha(actual_a, "net_bp"), _rows_sha(actual_b, "net_bp")
    primary_a_sha, primary_b_sha = _rows_sha(a, "net_bp"), _rows_sha(b, "net_bp")
    if actual_a_sha != primary_a_sha or actual_b_sha != primary_b_sha:
        raise RuntimeError("all-actual and primary-supported row masks diverged")
    observed = _dual_compare(a, b, seed, lo, hi)
    adverse_a, adverse_b = bounded(cap_a, -MISSING_BOUND_BP), bounded(cap_b, MISSING_BOUND_BP)
    favorable_a, favorable_b = bounded(cap_a, MISSING_BOUND_BP), bounded(cap_b, -MISSING_BOUND_BP)
    adverse = _dual_compare(adverse_a, adverse_b, seed + 100, lo, hi)
    favorable = _dual_compare(favorable_a, favorable_b, seed + 200, lo, hi)
    injected = _dual_injected(a, b, seed + 300, lo, hi)
    favorable_injected = _dual_injected(favorable_a, favorable_b, seed + 400, lo, hi)
    ma, mb = missing_stats(cap_a), missing_stats(cap_b)
    rates_ok = rate_gates(ma, mb)
    ob, ad, fav = observed.get("binding"), adverse.get("binding"), favorable.get("binding")
    positive_diag = bool(
        rates_ok
        and ob
        and ad
        and ob["crossed_ci95_envelope"][0] > 0
        and ad["crossed_ci95_envelope"][0] > 0
        and injected["pass"]
    )
    null_diag = bool(
        rates_ok
        and ob
        and fav
        and ob["crossed_ci95_envelope"][1] < 5
        and fav["crossed_ci95_envelope"][1] < 5
        and ob["mde80_bp"] <= 5
        and fav["mde80_bp"] <= 5
        and ob["power_at_plus5"] >= 0.8
        and fav["power_at_plus5"] >= 0.8
        and injected["pass"]
        and favorable_injected["pass"]
    )
    if not rates_ok:
        verdict = "MISSINGNESS_UNRESOLVED"
    elif not ob or ob["mde80_bp"] > 5 or ob["power_at_plus5"] < 0.8:
        verdict = "INCONCLUSIVE_UNDERPOWERED"
    else:
        verdict = "BURNED_DIRECTION_DIAGNOSTIC_ONLY"
    return {
        "observed": observed,
        "all_actual": {
            "identical_to_primary_supported": True,
            "arm_a_independent_sha256": actual_a_sha,
            "arm_a_primary_sha256": primary_a_sha,
            "arm_b_independent_sha256": actual_b_sha,
            "arm_b_primary_sha256": primary_b_sha,
        },
        "missingness": {
            "arm_a": ma,
            "arm_b": mb,
            "rate_gates_pass": rates_ok,
            "adverse": adverse,
            "favorable": favorable,
        },
        "injected_plus5": injected,
        "favorable_injected_plus5": favorable_injected,
        "positive_sensitivity_pass": positive_diag,
        "null_sensitivity_pass": null_diag,
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "verdict_status": verdict,
        "positive_iut_p": (
            max(ob["p_two_sided"], ad["p_two_sided"])
            if ob and ad and ob["delta_bp"] > 0 and ad["delta_bp"] > 0
            else 1.0
        ),
        "null_iut_p": max(ob["p_null_plus5"], fav["p_null_plus5"]) if ob and fav else None,
        "wallet_concentration": concentration(a, b),
        "pair_concentration": concentration(_pair_cluster_book(a), _pair_cluster_book(b)),
        "wallet_concentration_details": _concentration_details(a, b, pair=False),
        "pair_concentration_details": _concentration_details(a, b, pair=True),
    }


def validate_final_snapshot(
    con,
    roster_report: dict[str, object],
    roster_sha: str,
    entry_records: dict[str, object],
) -> None:
    if file_sha256(ROSTERS) != roster_sha:
        raise RuntimeError("roster artifact changed before final publication")
    config = roster_report["config"]
    if config["architecture_sha256"] != file_sha256(ARCH):
        raise RuntimeError("architecture changed before final publication")
    if config["code_sha256"] != _code_sha256(Path(__file__)):
        raise RuntimeError("code changed before final publication")
    if config["dependency_hashes"] != dependency_hashes():
        raise RuntimeError("dependencies changed before final publication")
    if config["parent_nested_rosters_sha256"] != file_sha256(NESTED_ROSTERS):
        raise RuntimeError("nested parent changed before final publication")
    if config["parent_efron_rosters_sha256"] != file_sha256(EFRON_ROSTERS):
        raise RuntimeError("Efron parent changed before final publication")
    if config["parent_book_sha256"] != file_sha256(EFRON_PARENT_BOOK):
        raise RuntimeError("parent book changed before final publication")
    for fold in FOLDS:
        item = roster_report["folds"][str(fold)]
        validate_panel_cache(con, fold, Path(item["pair_panel"]["path"]))
        path = ENTRIES / f"entries_{fold}.parquet"
        validate_entry_cache(con, fold, path, item["rosters"], roster_sha)
        current = {
            "parquet": entry_data_record(path),
            "meta_sha256": file_sha256(path.with_suffix(".meta.json")),
        }
        if current != entry_records[str(fold)]:
            raise RuntimeError(f"fold {fold}: entry artifact changed before final publication")


def apply_secondary_holm(contrasts: dict[str, dict[str, object]]) -> None:
    def significant(q: object) -> bool:
        if q is None:
            return False
        value = float(q)
        return bool(np.isfinite(value) and value <= 0.05)

    secondary = {k: v for k, v in contrasts.items() if k != PRIMARY}
    holm(secondary, "positive_iut_p", "positive_iut_holm_q")
    holm(secondary, "null_iut_p", "null_iut_holm_q")
    for result in secondary.values():
        result["positive_sensitivity_pass_unadjusted"] = result["positive_sensitivity_pass"]
        result["null_sensitivity_pass_unadjusted"] = result["null_sensitivity_pass"]
        result["positive_sensitivity_pass"] = bool(
            result["positive_sensitivity_pass_unadjusted"]
            and significant(result.get("positive_iut_holm_q"))
        )
        result["null_sensitivity_pass"] = bool(
            result["null_sensitivity_pass_unadjusted"]
            and significant(result.get("null_iut_holm_q"))
        )


def run() -> dict[str, object]:
    DERIVED.mkdir(parents=True, exist_ok=True)
    if PENDING_ENTRIES.exists():
        shutil.rmtree(PENDING_ENTRIES)
    PENDING_ENTRIES.mkdir(parents=True, exist_ok=True)
    _write_nonresult(ROSTERS, "SELECTOR_PARITY_PENDING_NO_ROSTERS")
    _write_nonresult(OUT, "SELECTOR_PARITY_PENDING_NO_RESULTS")
    con = lake.connect(mem="4GB", threads=2)
    try:
        roster_report = build_rosters(con)
    except Exception as exc:
        con.close()
        _write_nonresult(ROSTERS, "SELECTOR_PARITY_FAILURE", f"{type(exc).__name__}: {exc}")
        _write_nonresult(OUT, "SELECTOR_PARITY_FAILURE", f"{type(exc).__name__}: {exc}")
        raise
    _write_nonresult(OUT, "SELECTOR_PARITY_PASSED_OUTCOMES_PENDING")
    roster_sha = file_sha256(ROSTERS)
    entry_parts = []
    pending_paths: dict[str, Path] = {}
    pair_oracles: dict[str, object] = {}
    try:
        for fold in FOLDS:
            print(f"[wallet-coin book] {fold}", flush=True)
            fold_rosters = roster_report["folds"][str(fold)]["rosters"]
            path = cache_entries(con, fold, fold_rosters, roster_sha, directory=PENDING_ENTRIES)
            part = load_entries(path, fold)
            validate_entry_cache(con, fold, path, fold_rosters, roster_sha)
            pair_oracles[str(fold)] = _pair_oracle(con, fold, fold_rosters, part)
            entry_parts.append(part)
            pending_paths[str(fold)] = path
        entries = _concat(entry_parts)
        rosters_by_arm = {
            arm: {str(f): roster_report["folds"][str(f)]["rosters"][arm] for f in FOLDS}
            for arm in ARMS
        }
        parity = control_parity(con, entries, rosters_by_arm, pending_paths)
        for fold in FOLDS:
            fold_rosters = roster_report["folds"][str(fold)]["rosters"]
            validate_entry_cache(con, fold, pending_paths[str(fold)], fold_rosters, roster_sha)
            validate_panel_cache(
                con,
                fold,
                Path(roster_report["folds"][str(fold)]["pair_panel"]["path"]),
            )
        if (
            file_sha256(ROSTERS) != roster_sha
            or dependency_hashes() != roster_report["config"]["dependency_hashes"]
        ):
            raise RuntimeError("roster/dependency snapshot changed before entry promotion")
        entry_records = promote_entries(pending_paths)
        for fold in FOLDS:
            validate_entry_cache(
                con,
                fold,
                ENTRIES / f"entries_{fold}.parquet",
                roster_report["folds"][str(fold)]["rosters"],
                roster_sha,
            )
    except Exception as exc:
        con.close()
        if PENDING_ENTRIES.exists():
            shutil.rmtree(PENDING_ENTRIES)
        _write_nonresult(OUT, "OUTCOME_BUILD_OR_PARITY_FAILURE", f"{type(exc).__name__}: {exc}")
        raise
    con.close()
    if PENDING_ENTRIES.exists():
        shutil.rmtree(PENDING_ENTRIES)

    capacities: dict[str, dict[str, np.ndarray]] = {}
    books: dict[str, dict[str, np.ndarray]] = {}
    raw: dict[str, dict[str, np.ndarray]] = {}
    funnels: dict[str, object] = {}
    for arm in ARMS:
        raw[arm] = selected_raw(entries, rosters_by_arm[arm], arm)
        capacities[arm], funnels[arm] = capacity_book(entries, rosters_by_arm[arm], arm)
        books[arm] = supported(capacities[arm])

    lo = int(np.datetime64("2025-11-01", "D").astype(int))
    hi = int(np.datetime64("2026-06-30", "D").astype(int))
    contrasts: dict[str, dict[str, object]] = {}
    for name, (aa, bb, seed) in CONTRASTS.items():
        contrasts[name] = _contrast(
            books[aa], books[bb], capacities[aa], capacities[bb], seed, lo, hi
        )
    apply_secondary_holm(contrasts)

    final_con = lake.connect(mem="2GB", threads=1)
    try:
        validate_final_snapshot(final_con, roster_report, roster_sha, entry_records)
    finally:
        final_con.close()

    report: dict[str, object] = {
        "status": "BURNED_REOPENED_WALLET_COIN_FORENSIC_BOOK",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "comparative_results_present": True,
        "config": {
            "arms": list(ARMS),
            "contrasts": {k: [a, b, s] for k, (a, b, s) in CONTRASTS.items()},
            "unit_usd": UNIT_USD,
            "coin_cap_usd": COIN_CAP_USD,
            "hold_h": 8,
            "cost_bp": COST_BP,
            "n_boot": N_BOOT,
            "missing_bound_net_bp": MISSING_BOUND_BP,
            "architecture_sha256": file_sha256(ARCH),
            "code_sha256": _code_sha256(Path(__file__)),
            "dependency_hashes": dependency_hashes(),
            "inference_dependency_sha256": file_sha256(
                Path(__file__).with_name("dynamic_t_book.py")
            ),
            "roster_report_sha256": roster_sha,
            "entry_records": entry_records,
            "consensus": "excluded",
            "governance": (
                "burned reopened forensic; direction forced unresolved descriptive residual"
            ),
        },
        "selector": roster_report,
        "pair_entry_completeness": pair_oracles,
        "control_book_parity": parity,
        "funnels": funnels,
        "books": {
            arm: {
                **_book_stats(books[arm]),
                "missingness": missing_stats(capacities[arm]),
                "raw_gross": raw_stats(raw[arm]),
                "pair_seat_support": pair_seat_support(
                    entries, capacities[arm], rosters_by_arm[arm], arm
                ),
            }
            for arm in ARMS
        },
        "contrasts": contrasts,
        "primary": contrasts[PRIMARY],
    }
    atomic_json(OUT, report)
    return report


if __name__ == "__main__":
    run()
