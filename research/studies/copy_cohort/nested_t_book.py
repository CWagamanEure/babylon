"""Capacity-before-outcome 8h book for parity-locked nested-t rosters."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT

from . import lake
from .adaptive_rq_filter import exact_context_paths
from .alt_fresh_validate import MAJORS, STALE_MS, _ctx_parts
from .backtest_book import MAJN, entry_sizes, load_candidates, simulate
from .dynamic_t_book import compare
from .dynamic_t_quality import FOLDS, formation_months
from .filtered_quality import _code_sha256, _sha256_json
from .nested_t_filter import ARCH, ARMS, dependency_hashes
from .nested_t_filter import OUT as ROSTERS

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "nested_t_filter"
ENTRIES = DERIVED / "entries"
OUT = DERIVED / "book_report.json"

UNIT_USD = 5_000.0
COIN_CAP_USD = 50_000.0
NOTIONAL_MIN = 250.0
TOP_K = 30
HOLD_MS = 8 * 3_600_000
COST_BP = 5.5
MISSING_BOUND_BP = 2_000.0
MAX_LOSS = 0.01
MAX_FOLD_LOSS = 0.02
MAX_IMBALANCE = 0.005
N_BOOT = 10_000
SEED = 20260719
DAY_MS = 86_400_000

PRIMARY = "KF120__minus__STATIC"
SELECTOR_ARCH_SHA256 = "c81ba7933d3d58e1f3bb3c73aeb3053865d23004f7502a926a6f03858ae32d2c"
CONTRASTS = {
    PRIMARY: ("KF120_T30", "STATIC_T30"),
    "KF60__minus__STATIC": ("KF60_T30", "STATIC_T30"),
    "KF120__minus__KF60": ("KF120_T30", "KF60_T30"),
    "R_VOL__minus__KF60": ("KF60_R_VOL_T30", "KF60_T30"),
    "R_BREADTH__minus__KF60": ("KF60_R_BREADTH_T30", "KF60_T30"),
    "BLOWUP__minus__KF60": ("KF60_BLOWUP_T30", "KF60_T30"),
    "ALL__minus__KF120": ("KF120_ALL_T30", "KF120_T30"),
    "BOT500__minus__STATIC": ("STATIC_BOT500_T30", "STATIC_T30"),
    "ALL_BOT500__minus__BOT500": ("KF120_ALL_BOT500_T30", "STATIC_BOT500_T30"),
}


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _day_epoch(day: int) -> int:
    s = str(int(day))
    return int(datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=UTC).timestamp() // 86400)


def _ctx_records(paths: list[str]) -> list[dict[str, object]]:
    return [
        {"path": p, "size": Path(p).stat().st_size, "sha256": _file_sha256(Path(p))} for p in paths
    ]


def common_cutoff(maxima: list[tuple[str, int]]) -> tuple[dict[str, int], int]:
    if sorted(str(row[0]) for row in maxima) != sorted(MAJORS):
        raise RuntimeError("common cutoff lacks all four majors")
    max_by_coin = {str(coin): int(ts) for coin, ts in maxima}
    return max_by_coin, min(max_by_coin.values()) - HOLD_MS


def cache_entries(con, fold: int, fold_rosters: dict[str, list[str]], roster_sha: str) -> Path:
    ENTRIES.mkdir(parents=True, exist_ok=True)
    path = ENTRIES / f"entries_{fold}.parquet"
    meta = ENTRIES / f"entries_{fold}.meta.json"
    ctx_paths = _ctx_parts(fold)
    ctx = _ctx_records(ctx_paths)
    wallets = sorted({w for members in fold_rosters.values() for w in members})
    ctx_list = ",".join(f"'{p}'" for p in ctx_paths)
    majors = ",".join(f"'{c}'" for c in MAJORS)
    maxima = con.execute(f"""
        SELECT coin,max(ts)::BIGINT AS max_ts FROM read_parquet([{ctx_list}])
        WHERE mid_px IS NOT NULL AND coin IN ({majors}) GROUP BY coin ORDER BY coin
    """).fetchall()
    try:
        max_by_coin, cutoff = common_cutoff(maxima)
    except RuntimeError as exc:
        raise RuntimeError(f"fold {fold}: {exc}") from exc
    spec = {
        "schema": "nested-t-entry-v1-capacity-before-outcome",
        "fold": fold,
        "wallets": wallets,
        "wallets_sha256": _sha256_json(wallets),
        "rosters_sha256": roster_sha,
        "source_lineage": lake.validated_lineage(con, [fold], ("alt_universe_open_entries",)),
        "context": ctx,
        "context_sha256": _sha256_json(ctx),
        "context_max_ts_by_coin": max_by_coin,
        "common_cutoff": cutoff,
        "architecture_sha256": _file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "config": {
            "majors": list(MAJORS),
            "notional_min": NOTIONAL_MIN,
            "hold_ms": HOLD_MS,
            "stale_ms": STALE_MS,
        },
    }
    if path.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return path
    con.execute(
        "CREATE OR REPLACE TEMP TABLE nt_wallet AS SELECT * FROM (SELECT UNNEST(?) wallet)",
        [wallets],
    )
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH ent AS (
        SELECT lower(o.wallet) AS wallet,o.coin,o.ts,o.dir_sign,
          CAST(o.notl AS DOUBLE) AS notional
        FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN nt_wallet w
          ON lower(o.wallet)=w.wallet
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
    post = lake.validated_lineage(con, [fold], ("alt_universe_open_entries",))
    if post["sha256"] != spec["source_lineage"]["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: open-entry source mutated")
    tmp.replace(path)
    mt = meta.with_suffix(".json.tmp")
    mt.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mt.replace(meta)
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
        "gross_bp": np.asarray([math.nan if v is None else float(v) for v in d["gross_bp"]]),
        "fold": np.full(n, fold, np.int64),
    }
    order = np.lexsort(
        (np.arange(n), out["notional"], out["dir_sign"], out["coin"], out["wallet"], out["ts"])
    )
    return {k: v[order] for k, v in out.items()}


def literal_legacy_entries(con, fold: int, members: list[str]) -> dict[str, np.ndarray]:
    """Fresh literal majors_native 8h query, intentionally without comparative cutoff."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE nt_legacy_wallet AS "
        "SELECT * FROM (SELECT UNNEST(?) wallet, UNNEST(?) rk)",
        [members, list(range(len(members)))],
    )
    ctx_list = ",".join(f"'{p}'" for p in _ctx_parts(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    d = con.execute(f"""
      WITH ent AS (
        SELECT lower(o.wallet) AS wallet,w.rk,o.coin,o.ts,o.dir_sign,
          CAST(o.notl AS DOUBLE) AS notional
        FROM read_parquet('{lake.ope_month_glob(fold)}') o
        JOIN nt_legacy_wallet w ON lower(o.wallet)=w.wallet
        WHERE o.coin IN ({majors}) AND CAST(o.notl AS DOUBLE)>={NOTIONAL_MIN}
      ), ctx AS (
        SELECT coin,ts,mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL
      ), p0 AS (
        SELECT ent.*,ctx.mid_px AS px0,ctx.ts AS px0_ts
        FROM ent ASOF LEFT JOIN ctx ON ent.coin=ctx.coin AND ent.ts>=ctx.ts
      ), p8 AS (
        SELECT p0.*,ctx.mid_px AS px8,ctx.ts AS px8_ts
        FROM p0 ASOF LEFT JOIN ctx ON p0.coin=ctx.coin AND (p0.ts+{HOLD_MS})>=ctx.ts
      )
      SELECT wallet,coin,ts,dir_sign,notional,
        CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0>0
          AND ts-px0_ts<={STALE_MS} AND ts+{HOLD_MS}-px8_ts<={STALE_MS}
          THEN dir_sign*(px8-px0)/px0*1e4 END AS mk,
        {fold}::BIGINT AS fold
      FROM p8 ORDER BY ts,wallet,coin,dir_sign,notional
    """).fetchnumpy()
    raw_mk = d["mk"]
    mk = np.asarray(raw_mk.filled(np.nan) if np.ma.isMaskedArray(raw_mk) else raw_mk, float)
    finite = np.isfinite(mk)
    return {
        "wallet": d["wallet"].astype(str)[finite],
        "coin": d["coin"].astype(str)[finite],
        "ts": np.asarray(d["ts"], np.int64)[finite],
        "dir_sign": np.asarray(d["dir_sign"], float)[finite],
        "notional": np.asarray(d["notional"], float)[finite],
        "mk": mk[finite],
        "fold": np.full(int(finite.sum()), fold, np.int64),
    }


def independent_current_legacy_entries(con, fold: int, members: list[str]) -> dict[str, np.ndarray]:
    """Independent full historical horizon chain on the current immutable sources."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE nt_oracle_wallet AS "
        "SELECT * FROM (SELECT UNNEST(?) wallet, UNNEST(?) rk)",
        [members, list(range(len(members)))],
    )
    ctx_list = ",".join(f"'{p}'" for p in _ctx_parts(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    joins = []
    previous = "p0"
    for hour in (1, 4, 8, 24, 48):
        joins.append(
            f"p{hour} AS (SELECT {previous}.*,c.mid_px AS px{hour},c.ts AS px{hour}_ts "
            f"FROM {previous} ASOF LEFT JOIN ctx c ON {previous}.coin=c.coin "
            f"AND ({previous}.ts+{hour * 3_600_000})>=c.ts)"
        )
        previous = f"p{hour}"
    d = con.execute(f"""
      WITH ent AS (
        SELECT o.wallet,w.rk,o.coin,o.ts,o.dir_sign,CAST(o.notl AS DOUBLE) AS notional
        FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN nt_oracle_wallet w USING(wallet)
        WHERE o.coin IN ({majors}) AND CAST(o.notl AS DOUBLE)>={NOTIONAL_MIN}
      ), ctx AS (
        SELECT coin,ts,mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL
      ), p0 AS (
        SELECT ent.*,c.mid_px AS px0,c.ts AS px0_ts
        FROM ent ASOF LEFT JOIN ctx c ON ent.coin=c.coin AND ent.ts>=c.ts
      ), {",".join(joins)}
      SELECT wallet,coin,ts,dir_sign,notional,
        CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0>0
          AND ts-px0_ts<={STALE_MS} AND ts+{HOLD_MS}-px8_ts<={STALE_MS}
          THEN dir_sign*(px8-px0)/px0*1e4 END AS mk,
        {fold}::BIGINT AS fold
      FROM p48 ORDER BY ts,wallet,coin,dir_sign,notional
    """).fetchnumpy()
    raw_mk = d["mk"]
    mk = np.asarray(raw_mk.filled(np.nan) if np.ma.isMaskedArray(raw_mk) else raw_mk, float)
    finite = np.isfinite(mk)
    return {
        "wallet": d["wallet"].astype(str)[finite],
        "coin": d["coin"].astype(str)[finite],
        "ts": np.asarray(d["ts"], np.int64)[finite],
        "dir_sign": np.asarray(d["dir_sign"], float)[finite],
        "notional": np.asarray(d["notional"], float)[finite],
        "mk": mk[finite],
        "fold": np.full(int(finite.sum()), fold, np.int64),
    }


def capacity_book(
    entries: dict[str, np.ndarray], members: list[str]
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    member_set = set(members)
    use = np.asarray([w in member_set for w in entries["wallet"]], bool)
    idx = np.flatnonzero(use)
    open_wc: set[tuple[str, str]] = set()
    coin_gross: dict[str, float] = {}
    exits: list[tuple[int, str, str]] = []
    accepted: list[int] = []
    skip_wc = skip_coin = 0
    for i in idx:
        t = int(entries["ts"][i])
        while exits and exits[0][0] <= t:
            _, w, c = heapq.heappop(exits)
            open_wc.discard((w, c))
            coin_gross[c] = coin_gross.get(c, 0.0) - UNIT_USD
        w, c = str(entries["wallet"][i]), str(entries["coin"][i])
        if (w, c) in open_wc:
            skip_wc += 1
            continue
        if coin_gross.get(c, 0.0) + UNIT_USD > COIN_CAP_USD + 1e-9:
            skip_coin += 1
            continue
        open_wc.add((w, c))
        coin_gross[c] = coin_gross.get(c, 0.0) + UNIT_USD
        heapq.heappush(exits, (t + HOLD_MS, w, c))
        accepted.append(int(i))
    ii = np.asarray(accepted, np.int64)
    out = {k: v[ii] for k, v in entries.items()}
    out["supported"] = np.isfinite(out["gross_bp"])
    out["net_bp"] = out["gross_bp"] - COST_BP
    return out, {
        "n_candidates": int(idx.size),
        "n_accepted_capacity": int(ii.size),
        "n_skip_wallet_coin": skip_wc,
        "n_skip_coin_cap": skip_coin,
    }


def concat(
    parts: list[dict[str, np.ndarray]], supported_only: bool = False
) -> dict[str, np.ndarray]:
    keys = parts[0].keys()
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    if supported_only:
        m = out["supported"]
        out = {k: v[m] for k, v in out.items()}
    out["signal_ts"] = out["ts"]
    return out


def selected_raw(entries: dict[str, np.ndarray], members: list[str]) -> dict[str, np.ndarray]:
    member_set = set(members)
    m = np.asarray([w in member_set for w in entries["wallet"]]) & np.isfinite(entries["gross_bp"])
    return {
        "wallet": entries["wallet"][m],
        "fold": entries["fold"][m],
        "gross_bp": entries["gross_bp"][m],
    }


def raw_stats(raw: dict[str, np.ndarray]) -> dict[str, object]:
    bp = raw["gross_bp"]
    robust = None
    if bp.size:
        limit = float(np.percentile(np.abs(bp), 95))
        clipped = np.clip(bp, -limit, limit)
        key = np.char.add(np.char.add(raw["wallet"], "|"), raw["fold"].astype(str))
        _, inv, count = np.unique(key, return_inverse=True, return_counts=True)
        keep = count[inv] >= 3
        if keep.any():
            _, inv2 = np.unique(key[keep], return_inverse=True)
            wf = np.bincount(inv2, weights=clipped[keep]) / np.bincount(inv2)
            robust = {
                "p95_abs_limit_bp": limit,
                "n_entries": int(keep.sum()),
                "n_wallet_folds": int(wf.size),
                "wallet_fold_equal_point_bp": float(wf.mean()),
            }
    return {
        "n_entries": int(bp.size),
        "gross_mean_bp": float(bp.mean()) if bp.size else None,
        "gross_median_bp": float(np.median(bp)) if bp.size else None,
        "hit_rate": float((bp > 0).mean()) if bp.size else None,
        "registered_robust": robust,
    }


def book_stats(book: dict[str, np.ndarray]) -> dict[str, object]:
    bp = book["net_bp"]
    n = bp.size
    by_fold = {
        str(f): float(bp[book["fold"] == f].mean()) if np.any(book["fold"] == f) else None
        for f in FOLDS
    }
    by_coin = {
        c: float(bp[book["coin"] == c].mean()) if np.any(book["coin"] == c) else None
        for c in MAJORS
    }
    return {
        "n_entries": int(n),
        "net_bp_per_entry": float(bp.mean()) if n else None,
        "net_usd": float(bp.sum() * UNIT_USD / 1e4),
        "per_fold": by_fold,
        "per_coin": by_coin,
    }


def missing_stats(cap: dict[str, np.ndarray]) -> dict[str, object]:
    miss = ~cap["supported"]
    n = miss.size
    per_fold = {
        str(f): {
            "accepted": int(np.sum(cap["fold"] == f)),
            "missing": int(np.sum((cap["fold"] == f) & miss)),
            "rate": float(np.mean(miss[cap["fold"] == f])) if np.any(cap["fold"] == f) else None,
        }
        for f in FOLDS
    }

    def strata(values: np.ndarray) -> dict[str, dict[str, object]]:
        out = {}
        for value in np.unique(values):
            m = values == value
            out[str(value)] = {
                "accepted": int(m.sum()),
                "missing": int(np.sum(m & miss)),
                "rate": float(np.mean(miss[m])),
            }
        return out

    return {
        "accepted": int(n),
        "missing": int(miss.sum()),
        "rate": float(miss.mean()) if n else None,
        "per_fold": per_fold,
        "by_coin": strata(cap["coin"]),
        "by_wallet": strata(cap["wallet"]),
    }


def bounded(cap: dict[str, np.ndarray], value: float) -> dict[str, np.ndarray]:
    out = {k: v.copy() for k, v in cap.items()}
    out["net_bp"][~out["supported"]] = value
    return out


def concentration(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> dict[str, object]:
    wallets = sorted(set(a["wallet"]) | set(b["wallet"]))
    contrib = []
    for w in wallets:
        ca = float(a["net_bp"][a["wallet"] == w].sum() / max(a["net_bp"].size, 1))
        cb = float(b["net_bp"][b["wallet"] == w].sum() / max(b["net_bp"].size, 1))
        contrib.append(ca - cb)
    av = np.abs(np.asarray(contrib))
    den = float(av.sum())
    share = float(np.sort(av)[-5:].sum() / den) if den > 0 else 0.0
    return {
        "n_contributing_wallets": int(np.sum(av > 0)),
        "top5_abs_share": share,
        "concentrated": share > 0.5,
        "sum_contribution": float(np.sum(contrib)),
    }


def holm(results: dict[str, dict[str, object]], field: str, out_field: str) -> None:
    def p_of(name: str) -> float:
        value = results[name].get(field)
        return float(value) if value is not None and np.isfinite(float(value)) else 1.0

    names = sorted(results, key=lambda k: (p_of(k), k))
    running = 0.0
    m = len(names)
    for rank, name in enumerate(names):
        running = max(running, (m - rank) * p_of(name))
        results[name][out_field] = (
            min(1.0, running) if results[name].get(field) is not None else None
        )


def _sorted_rows(rows: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    order = np.lexsort((rows["mk"], rows["notional"], rows["coin"], rows["wallet"], rows["ts"]))
    return {k: v[order] for k, v in rows.items()}


def legacy_oracle_rows() -> dict[str, np.ndarray]:
    parts = []
    for fold in FOLDS:
        d = pq.read_table(
            MAJN / f"entries_{fold}.parquet", columns=["wallet", "coin", "ts", "notl", "mk8", "rk"]
        ).to_pydict()
        rk = np.asarray(d["rk"], int)
        mk = np.asarray([math.nan if v is None else float(v) for v in d["mk8"]])
        m = (rk < TOP_K) & np.isfinite(mk)
        parts.append(
            {
                "wallet": np.asarray(d["wallet"], str)[m],
                "coin": np.asarray(d["coin"], str)[m],
                "ts": np.asarray(d["ts"], np.int64)[m],
                "notional": np.asarray(d["notl"], float)[m],
                "mk": mk[m],
                "fold": np.full(int(m.sum()), fold, np.int64),
            }
        )
    return _sorted_rows({k: np.concatenate([p[k] for p in parts]) for k in parts[0]})


def _assert_rows_equal(
    candidate: dict[str, np.ndarray], oracle: dict[str, np.ndarray], label: str
) -> None:
    a, b = _sorted_rows(candidate), _sorted_rows(oracle)
    if a["wallet"].size != b["wallet"].size:
        raise RuntimeError(f"{label}: row count {a['wallet'].size}!={b['wallet'].size}")
    for key in ("wallet", "coin", "ts", "fold"):
        if not np.array_equal(a[key], b[key]):
            raise RuntimeError(f"{label}: {key} multiset mismatch")
    for key in ("notional", "mk"):
        if not np.allclose(a[key], b[key], atol=1e-10, rtol=1e-12):
            raise RuntimeError(f"{label}: {key} max diff {np.max(np.abs(a[key] - b[key]))}")
    if "dir_sign" in a and "dir_sign" in b and not np.array_equal(a["dir_sign"], b["dir_sign"]):
        raise RuntimeError(f"{label}: direction multiset mismatch")


def historical_subset(
    current: dict[str, np.ndarray], old: dict[str, np.ndarray]
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    positions: dict[tuple[object, ...], deque[int]] = defaultdict(deque)
    for i in range(current["ts"].size):
        key = (
            str(current["wallet"][i]),
            str(current["coin"][i]),
            int(current["ts"][i]),
            float(current["notional"][i]),
            int(current["fold"][i]),
        )
        positions[key].append(i)
    selected = []
    for i in range(old["ts"].size):
        key = (
            str(old["wallet"][i]),
            str(old["coin"][i]),
            int(old["ts"][i]),
            float(old["notional"][i]),
            int(old["fold"][i]),
        )
        if not positions[key]:
            raise RuntimeError(f"historical cache row absent from refreshed query: {key}")
        selected.append(positions[key].popleft())
    selected_arr = np.asarray(selected, np.int64)
    keep = np.ones(current["ts"].size, bool)
    keep[selected_arr] = False
    subset = {k: v[selected_arr] for k, v in current.items()}
    return subset, np.flatnonzero(keep)


def legacy_parity(
    new_rows: dict[str, np.ndarray], current_oracle: dict[str, np.ndarray]
) -> dict[str, object]:
    _assert_rows_equal(new_rows, current_oracle, "refreshed literal-entry parity")
    oracle_rows = legacy_oracle_rows()
    old_subset, extra_idx = historical_subset(new_rows, oracle_rows)
    _assert_rows_equal(old_subset, oracle_rows, "historical-cache subset parity")
    key = np.char.add(
        np.char.add(np.char.add(new_rows["wallet"], "|"), new_rows["coin"]),
        np.char.add("|", new_rows["ts"].astype(str)),
    )
    _, inv, count = np.unique(key, return_inverse=True, return_counts=True)
    duplicates = int(np.sum(count > 1))
    opposing = int(
        sum(np.unique(new_rows["dir_sign"][inv == j]).size > 1 for j in np.flatnonzero(count > 1))
    )
    if opposing:
        raise RuntimeError(f"legacy parity has {opposing} opposing-direction tied keys")
    old = load_candidates()["B"]
    new = {
        "wallet": old_subset["wallet"],
        "coin": old_subset["coin"],
        "ts": old_subset["ts"],
        "mk": old_subset["mk"],
        "fold": old_subset["fold"],
    }
    order = np.lexsort((new["coin"], new["wallet"], new["ts"]))
    new = {k: v[order] for k, v in new.items()}
    old_sim = simulate(old, entry_sizes(old, "B", "S1", np.ones(old["ts"].size)), "B")
    new_sim = simulate(new, entry_sizes(new, "B", "S1", np.ones(new["ts"].size)), "B")
    old_acc = {
        "wallet": old_sim["wallet"],
        "coin": old_sim["coin"],
        "ts": old_sim["ts"],
        "notional": old_sim["size"],
        "mk": old_sim["mk"],
        "fold": old_sim["fold"],
    }
    new_acc = {
        "wallet": new_sim["wallet"],
        "coin": new_sim["coin"],
        "ts": new_sim["ts"],
        "notional": new_sim["size"],
        "mk": new_sim["mk"],
        "fold": new_sim["fold"],
    }
    _assert_rows_equal(new_acc, old_acc, "legacy accepted-row parity")
    for key in ("n_skip_wc", "n_skip_cap"):
        if new_sim[key] != old_sim[key]:
            raise RuntimeError(f"legacy Book-B {key} parity failed")
    new_mean = float(np.mean(new_sim["mk"] - COST_BP))
    old_mean = float(np.mean(old_sim["mk"] - COST_BP))
    if not math.isclose(new_mean, old_mean, abs_tol=1e-10, rel_tol=1e-12):
        raise RuntimeError("legacy Book-B unrounded mean parity failed")
    refreshed = {
        "wallet": new_rows["wallet"],
        "coin": new_rows["coin"],
        "ts": new_rows["ts"],
        "mk": new_rows["mk"],
        "fold": new_rows["fold"],
    }
    refreshed_order = np.lexsort((refreshed["coin"], refreshed["wallet"], refreshed["ts"]))
    refreshed = {k: v[refreshed_order] for k, v in refreshed.items()}
    refreshed_sim = simulate(
        refreshed,
        entry_sizes(refreshed, "B", "S1", np.ones(refreshed["ts"].size)),
        "B",
    )
    return {
        "historical_cache_raw_finite_entries": int(oracle_rows["wallet"].size),
        "refreshed_raw_finite_entries": int(new_rows["wallet"].size),
        "refreshed_additions": int(extra_idx.size),
        "refreshed_additions_per_fold": {
            str(f): int(np.sum(new_rows["fold"][extra_idx] == f)) for f in FOLDS
        },
        "n_duplicate_wallet_coin_ts_keys": duplicates,
        "n_opposing_mark_keys": opposing,
        "historical_book": {
            "n_entries": int(new_sim["idx"].size),
            "net_bp_per_entry": new_mean,
            "n_skip_wallet_coin": int(new_sim["n_skip_wc"]),
            "n_skip_coin": int(new_sim["n_skip_cap"]),
        },
        "refreshed_book": {
            "n_entries": int(refreshed_sim["idx"].size),
            "net_bp_per_entry": float(np.mean(refreshed_sim["mk"] - COST_BP)),
            "n_skip_wallet_coin": int(refreshed_sim["n_skip_wc"]),
            "n_skip_coin": int(refreshed_sim["n_skip_cap"]),
        },
    }


def validate_roster_report(con, report: dict[str, object]) -> None:
    config = report.get("config", {})
    if config.get("architecture_sha256") != SELECTOR_ARCH_SHA256:
        raise RuntimeError("selector does not bind the frozen pre-amendment architecture")
    selector = Path(__file__).with_name("nested_t_filter.py")
    if config.get("code_sha256") != _code_sha256(selector):
        raise RuntimeError("stale selector code hash")
    if config.get("dependency_hashes") != dependency_hashes():
        raise RuntimeError("stale selector dependency hashes")
    expected_roster_sha = _sha256_json({f: v["rosters"] for f, v in report["folds"].items()})
    if report.get("rosters_sha256") != expected_roster_sha:
        raise RuntimeError("selector internal roster hash mismatch")
    for fold in FOLDS:
        item = report["folds"][str(fold)]
        panel = Path(item["panel_path"])
        meta = panel.with_suffix(".meta.json")
        if _file_sha256(meta) != item.get("panel_meta_sha256"):
            raise RuntimeError(f"fold {fold}: stale panel meta")
        spec = json.loads(meta.read_text())
        if spec.get("architecture_sha256") != SELECTOR_ARCH_SHA256:
            raise RuntimeError(f"fold {fold}: panel does not bind frozen selector architecture")
        current = lake.validated_lineage(
            con, formation_months(fold), ("alt_universe_wallet_coin_day",)
        )
        if spec.get("source_lineage") != current or item.get("panel_source_lineage") != current:
            raise RuntimeError(f"fold {fold}: stale selector source lineage")
        if spec.get("context_sha256") != item.get("panel_context_sha256"):
            raise RuntimeError(f"fold {fold}: stale selector context")
        current_context = _ctx_records(
            [str(p) for p in exact_context_paths(formation_months(fold))]
        )
        if spec.get("context") != current_context:
            raise RuntimeError(f"fold {fold}: current selector context changed")
        if spec.get("dependency_hashes") != dependency_hashes():
            raise RuntimeError(f"fold {fold}: stale panel dependency hashes")
        ref = Path(item["reference_path"]).with_suffix(".meta.json")
        if _file_sha256(ref) != item.get("reference_meta_sha256"):
            raise RuntimeError(f"fold {fold}: stale selector reference")


def write_nonresult_status(status: str, error: str | None = None) -> None:
    payload = {
        "status": status,
        "comparative_results_present": False,
        "architecture_sha256": _file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
    }
    if error is not None:
        payload["error"] = error
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True))
    tmp.replace(OUT)


def run() -> dict[str, object]:
    write_nonresult_status("PARITY_PENDING_NO_RESULTS")
    con = None
    try:
        roster_report = json.loads(ROSTERS.read_text())
        if roster_report.get("status") != "BURNED_PARITY_LOCKED_SELECTOR_DIAGNOSTIC":
            raise RuntimeError("selector artifact is not parity-locked")
        roster_sha = _file_sha256(ROSTERS)
        con = lake.connect(mem="4GB", threads=2)
        validate_roster_report(con, roster_report)
        legacy_rows = []
        legacy_oracle = []
        for fold in FOLDS:
            print(f"[nested legacy parity] {fold}", flush=True)
            legacy_members = roster_report["folds"][str(fold)]["rosters"]["LEGACY_STATIC_T30"]
            legacy_rows.append(literal_legacy_entries(con, fold, legacy_members))
            legacy_oracle.append(independent_current_legacy_entries(con, fold, legacy_members))
        legacy_new = {k: np.concatenate([p[k] for p in legacy_rows]) for k in legacy_rows[0]}
        current_oracle = {
            k: np.concatenate([p[k] for p in legacy_oracle]) for k in legacy_oracle[0]
        }
        parity = legacy_parity(legacy_new, current_oracle)
    except Exception as exc:
        if con is not None:
            con.close()
        write_nonresult_status("PARITY_FAILURE", f"{type(exc).__name__}: {exc}")
        raise
    write_nonresult_status("PARITY_PASSED_OUTCOMES_PENDING")
    parts = {arm: [] for arm in ARMS}
    raw_parts = {arm: [] for arm in ARMS}
    funnels = {}
    for fold in FOLDS:
        print(f"[nested book] {fold}", flush=True)
        rosters = roster_report["folds"][str(fold)]["rosters"]
        ent = load_entries(cache_entries(con, fold, rosters, roster_sha), fold)
        funnels[str(fold)] = {}
        for arm in ARMS:
            raw_parts[arm].append(selected_raw(ent, rosters[arm]))
            cap, fun = capacity_book(ent, rosters[arm])
            parts[arm].append(cap)
            funnels[str(fold)][arm] = fun
    con.close()
    capacity = {a: concat(parts[a]) for a in ARMS}
    books = {a: concat(parts[a], supported_only=True) for a in ARMS}
    raw_books = {
        a: {k: np.concatenate([p[k] for p in raw_parts[a]]) for k in raw_parts[a][0]} for a in ARMS
    }
    calendar_lo, calendar_hi = _day_epoch(20251101), _day_epoch(20260630)
    report: dict[str, object] = {
        "status": "BURNED_PARITY_LOCKED_BOOK_DIAGNOSTIC",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "config": {
            "unit_usd": UNIT_USD,
            "coin_cap_usd": COIN_CAP_USD,
            "hold_h": 8,
            "cost_bp": COST_BP,
            "n_boot": N_BOOT,
            "seed": SEED,
            "missing_bound_bp": MISSING_BOUND_BP,
            "consensus": "excluded",
            "rosters_sha256": roster_sha,
            "architecture_sha256": _file_sha256(ARCH),
            "code_sha256": _code_sha256(Path(__file__)),
            "inference_dependency_sha256": _file_sha256(
                Path(__file__).with_name("dynamic_t_book.py")
            ),
        },
        "legacy_book_b_parity": parity,
        "funnels": funnels,
        "books": {},
        "contrasts": {},
    }
    for arm in ARMS:
        report["books"][arm] = {
            **book_stats(books[arm]),
            "missingness": missing_stats(capacity[arm]),
            "raw": raw_stats(raw_books[arm]),
        }
    for index, (name, (aa, bb)) in enumerate(CONTRASTS.items()):
        result = compare(
            books[aa], books[bb], SEED + index, calendar_lo, calendar_hi, n_boot=N_BOOT
        )
        ma, mb = missing_stats(capacity[aa]), missing_stats(capacity[bb])
        rates = [v["rate"] for v in ma["per_fold"].values() if v["rate"] is not None]
        rates += [v["rate"] for v in mb["per_fold"].values() if v["rate"] is not None]
        rate_ok = (
            ma["rate"] <= MAX_LOSS
            and mb["rate"] <= MAX_LOSS
            and max(rates, default=0) <= MAX_FOLD_LOSS
            and abs(ma["rate"] - mb["rate"]) <= MAX_IMBALANCE
        )
        low = compare(
            bounded(capacity[aa], -MISSING_BOUND_BP),
            bounded(capacity[bb], MISSING_BOUND_BP),
            SEED + 100 + index,
            calendar_lo,
            calendar_hi,
            n_boot=N_BOOT,
        )
        high = compare(
            bounded(capacity[aa], MISSING_BOUND_BP),
            bounded(capacity[bb], -MISSING_BOUND_BP),
            SEED + 200 + index,
            calendar_lo,
            calendar_hi,
            n_boot=N_BOOT,
        )
        ac = {k: v.copy() for k, v in books[aa].items()}
        bc = {k: v.copy() for k, v in books[bb].items()}
        ac["net_bp"] = ac["net_bp"] - ac["net_bp"].mean() + 5.0
        bc["net_bp"] = bc["net_bp"] - bc["net_bp"].mean()
        injected = compare(ac, bc, SEED + 300 + index, calendar_lo, calendar_hi, n_boot=N_BOOT)
        result["missingness"] = {
            "arm_a": ma,
            "arm_b": mb,
            "rate_gates_pass": bool(rate_ok),
            "adverse_crossed_ci95": low.get("crossed_ci95"),
            "favorable_crossed_ci95": high.get("crossed_ci95"),
        }
        main_pos = (
            result.get("crossed_p_two_sided", 1.0)
            if result.get("delta_bp", -math.inf) > 0
            and result.get("crossed_p_two_sided") is not None
            else 1.0
        )
        adverse_pos = (
            low.get("crossed_p_two_sided", 1.0)
            if low.get("delta_bp", -math.inf) > 0 and low.get("crossed_p_two_sided") is not None
            else 1.0
        )
        result["positive_iut_p"] = max(main_pos, adverse_pos)
        main_null = result.get("p_null_plus5_one_sided")
        fav_null = high.get("p_null_plus5_one_sided")
        result["null_iut_p"] = (
            max(float(main_null), float(fav_null))
            if main_null is not None and fav_null is not None
            else None
        )
        result["injected_plus5"] = {
            "point": injected.get("delta_bp"),
            "crossed_ci95": injected.get("crossed_ci95"),
            "pass": bool(
                injected.get("crossed_ci95")
                and injected["crossed_ci95"][0] > 0
                and abs(injected["delta_bp"] - 5) < 1e-10
            ),
        }
        result["concentration"] = concentration(books[aa], books[bb])
        result["positive_promotion_eligible"] = False
        result["method_null_eligible"] = False
        positive_sensitivity = bool(low.get("crossed_ci95") and low["crossed_ci95"][0] > 0)
        null_sensitivity = bool(
            high.get("crossed_ci95")
            and high["crossed_ci95"][1] < 5
            and result.get("crossed_mde80_bp") is not None
            and result["crossed_mde80_bp"] <= 5
            and high.get("crossed_mde80_bp") is not None
            and high["crossed_mde80_bp"] <= 5
        )
        result["missingness"]["positive_sensitivity_pass"] = positive_sensitivity
        result["missingness"]["null_sensitivity_pass"] = null_sensitivity
        result["verdict_status"] = (
            "BURNED_DIRECTION_ONLY"
            if rate_ok and (positive_sensitivity or null_sensitivity)
            else "MISSINGNESS_UNRESOLVED"
        )
        report["contrasts"][name] = result
    secondary = {k: v for k, v in report["contrasts"].items() if k != PRIMARY}
    holm(secondary, "positive_iut_p", "positive_iut_holm_q")
    holm(secondary, "null_iut_p", "null_iut_holm_q")
    report["primary"] = report["contrasts"][PRIMARY]
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=1, sort_keys=True))
    tmp.replace(OUT)
    return report


if __name__ == "__main__":
    run()
