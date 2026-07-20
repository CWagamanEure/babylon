"""Strictly causal 8h entry-book evaluation for dynamic t-quality rosters."""
from __future__ import annotations

import calendar
import hashlib
import heapq
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from . import lake
from .alt_fresh_validate import MAJORS, STALE_MS, _ctx_parts
from .dynamic_t_quality import (
    BLOWUP_USD,
    DERIVED,
    FOLDS,
    QUARANTINE_DAYS,
    StudyProfile,
    normalized_x,
)
from .dynamic_t_quality import _cache_spec as _selector_cache_spec
from .filtered_quality import _code_sha256, _sha256_json

ENTRIES = DERIVED / "entries"
OUT = DERIVED / "book_report.json"
UNIT_USD = 2_500.0
WALLET_CAP_USD = 10_000.0
COIN_CAP_USD = 50_000.0
NOTL_MIN = 250.0
HOLD_MS = 8 * 3_600_000
COST_BP = 5.5
N_BOOT = 10_000
BLOCK_DAYS = 7
SEED = 20260718
TOP_HALF = 15
DAY_MS = 86_400_000
MIN_INFER_WALLETS = 10
MIN_INFER_BLOCKS = 10
MAX_INVALID_BOOT_FRAC = 0.01
MISSING_RETURN_BOUND_BP = 2_000.0
MAX_SUPPORT_LOSS = 0.01
MAX_FOLD_SUPPORT_LOSS = 0.02
MAX_SUPPORT_RATE_IMBALANCE = 0.005
PARTIAL_CONTEXT_EXCEPTION = {20260530: {"count": 418, "last_offset_ms": 25_020_000}}
SHOCK_ARMS = {"EW_T_SHOCK30", "TSTAT_COPY30", "EW_T_COPY30"}
ARMS = (
    "TSTAT30", "TSTAT_COMMON30", "EW_T30", "HAC_T30", "EW_HAC_T30",
    "EW_T_SHOCK30", "TSTAT_COPY30", "EW_T_COPY30", "PUBLISHED_MAJORS30",
)


def _next_month(month: int) -> int:
    y, m = divmod(month, 100)
    return (y + 1) * 100 + 1 if m == 12 else month + 1


def _day_epoch(day: int) -> int:
    s = str(int(day))
    dt = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=UTC)
    return int(dt.timestamp() // 86_400)


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _context_records(paths: list[str]) -> list[dict[str, object]]:
    return [{"path": p, "size": Path(p).stat().st_size,
             "sha256": _file_sha256(p)} for p in paths]


def common_support_sql(base: str = "ent", ctx: str = "ctx") -> tuple[str, str, str]:
    """Build audited all-four-major ASOF CTEs and their common support expression."""
    ctes, checks = [], []
    prev = base
    for coin in MAJORS:
        tag = coin.lower()
        e0, e8 = f"s_{tag}_0", f"s_{tag}_8"
        ctes.append(
            f"{e0} AS (SELECT {prev}.*,c.ts AS {tag}_entry "
            f"FROM {prev} ASOF LEFT JOIN (SELECT ts FROM {ctx} WHERE coin='{coin}') c "
            f"ON {prev}.ts<c.ts)"
        )
        ctes.append(
            f"{e8} AS (SELECT {e0}.*,c.ts AS {tag}_exit "
            f"FROM {e0} ASOF LEFT JOIN (SELECT ts FROM {ctx} WHERE coin='{coin}') c "
            f"ON ({e0}.{tag}_entry+{HOLD_MS})<=c.ts)"
        )
        checks.append(
            f"({tag}_entry-ts)<={STALE_MS} AND "
            f"({tag}_exit-({tag}_entry+{HOLD_MS}))<={STALE_MS}"
        )
        prev = e8
    return ",".join(ctes), prev, " AND ".join(checks)


def validate_context_day_sets(fold: int, eval_days: list[int], next_days: list[int]) -> None:
    """Fail closed: only the registered June final fold may be truncated."""
    nmonth = calendar.monthrange(fold // 100, fold % 100)[1]
    expected_eval = list(range(fold * 100 + 1, fold * 100 + nmonth + 1))
    if fold == 202606:
        expected_eval = list(range(20260601, 20260630))
    if eval_days != expected_eval:
        raise RuntimeError(
            f"fold {fold}: evaluation context coverage {eval_days} != {expected_eval}"
        )
    expected_next = [] if fold == 202606 else list(range(_next_month(fold) * 100 + 1,
                                                              _next_month(fold) * 100 + 4))
    if next_days != expected_next:
        raise RuntimeError(
            f"fold {fold}: next-month context coverage {next_days} != {expected_next}"
        )


def common_context_cutoff(max_by_coin: dict[str, int]) -> int:
    if set(max_by_coin) != set(MAJORS):
        raise RuntimeError(f"context lacks a major: {max_by_coin}")
    return min(max_by_coin.values()) - HOLD_MS - 2 * STALE_MS


def _validate_context_content(con, ctx_list: str, days: list[int]) -> dict[str, object]:
    """Require daily endpoints; record interior gaps for the common outcome-support mask."""
    majors = ",".join(f"'{c}'" for c in MAJORS)
    rows = con.execute(f"""
      WITH x AS (
        SELECT coin,ts,ts-LAG(ts) OVER (PARTITION BY coin ORDER BY ts) AS gap
        FROM read_parquet([{ctx_list}]) WHERE coin IN ({majors}) AND mid_px IS NOT NULL
      )
      SELECT coin,ts//{DAY_MS} AS epoch_day,COUNT(*),MIN(ts),MAX(ts),MAX(gap)
      FROM x GROUP BY coin,epoch_day ORDER BY coin,epoch_day
    """).fetchall()
    got = {(str(c), int(d)): (int(n), int(lo), int(hi), int(gap or 0))
           for c, d, n, lo, hi, gap in rows}
    failures = []
    gaps = []
    partials = []
    for day in days:
        epoch = _day_epoch(day)
        lo, hi = epoch * DAY_MS, (epoch + 1) * DAY_MS
        for coin in MAJORS:
            v = got.get((coin, epoch))
            endpoint_ok = (v is not None and v[1] <= lo + STALE_MS
                           and v[2] >= hi - STALE_MS)
            exception = PARTIAL_CONTEXT_EXCEPTION.get(day)
            exact_partial = (v is not None and exception is not None
                             and v[0] == exception["count"] and v[1] == lo
                             and v[2] == lo + exception["last_offset_ms"])
            if exception is not None:
                if not exact_partial:
                    failures.append((coin, day, v))
                else:
                    partials.append((coin, day, v[0], v[1], v[2]))
            elif not endpoint_ok:
                failures.append((coin, day, v))
            if v is not None and v[3] > STALE_MS:
                gaps.append((coin, day, v[3]))
    if failures:
        raise RuntimeError(f"context major/day continuity failed: {failures[:8]}")
    return {"n_major_days": len(got), "max_gap_ms": max(v[3] for v in got.values()),
            "n_major_days_with_gap_gt_stale": len(gaps), "gap_days": gaps,
            "partial_major_days": partials}


def _cache_fold(con, fold: int, wallets: list[str], *, entries_dir: Path,
                profile: StudyProfile) -> tuple[Path, Path, Path]:
    entries_dir.mkdir(parents=True, exist_ok=True)
    ep = entries_dir / f"entries_{fold}.parquet"
    sp = entries_dir / f"signals_{fold}.parquet"
    qp = entries_dir / f"shock_days_{fold}.parquet"
    meta = entries_dir / f"cache_{fold}.meta.json"
    ctx = sorted(_ctx_parts(fold))
    if not ctx:
        raise RuntimeError(f"fold {fold}: no context")
    eval_days = sorted(int(Path(p).parent.name.removeprefix("day=")) for p in ctx
                       if f"month={fold}" in p)
    nxt = _next_month(fold)
    next_days = sorted(int(Path(p).parent.name.removeprefix("day=")) for p in ctx
                       if f"month={nxt}" in p)
    validate_context_day_sets(fold, eval_days, next_days)
    ctx_list = ",".join(f"'{p}'" for p in ctx)
    majors = ",".join(f"'{c}'" for c in MAJORS)
    max_rows = con.execute(
        f"""SELECT coin, MAX(ts) FROM read_parquet([{ctx_list}])
            WHERE coin IN ({majors}) AND mid_px IS NOT NULL GROUP BY coin"""
    ).fetchall()
    max_by_coin = {str(c): int(t) for c, t in max_rows}
    cutoff = common_context_cutoff(max_by_coin)
    ctx_coverage = _validate_context_content(con, ctx_list, eval_days + next_days)
    ctx_files = _context_records(ctx)
    code_paths = (Path(__file__), Path(__file__).with_name("dynamic_t_quality.py"),
                  Path(__file__).with_name("alt_fresh_validate.py"),
                  Path(__file__).with_name("filtered_quality.py"))
    spec = {
        "cache_schema": "dynamic-t-book-v4", "fold": fold,
        "experiment_id": profile.experiment_id,
        "half_life_days": profile.half_life_days,
        "architecture": profile.architecture,
        "roster_sha256": _sha256_json(sorted(wallets)), "n_union_wallets": len(set(wallets)),
        "source_lineage": lake.validated_lineage(
            con, [fold], ("alt_universe_wallet_coin_day", "alt_universe_open_entries")
        ),
        "ctx_files": ctx_files, "ctx_files_sha256": _sha256_json(ctx_files),
        "evaluation_days": eval_days, "next_month_days": next_days,
        "evaluation_month_complete": fold != 202606,
        "registered_final_fold_truncation": fold == 202606,
        "context_coverage": ctx_coverage,
        "ctx_max_by_coin": max_by_coin, "common_signal_cutoff_ms": cutoff,
        "cutoff_formula": "min major max_ctx - hold_ms - 2*stale_ms",
        "code_sha256": _code_sha256(*code_paths),
        "config": {"majors": list(MAJORS), "notional_min": NOTL_MIN, "hold_ms": HOLD_MS,
                   "stale_ms": STALE_MS, "entry": "first ctx strictly after signal",
                   "exit": "first ctx at/after entry_exec+hold"},
    }
    if (ep.exists() and sp.exists() and qp.exists() and meta.exists()
            and json.loads(meta.read_text()) == spec):
        return ep, sp, qp

    con.execute("CREATE OR REPLACE TEMP TABLE dt_wallets AS SELECT UNNEST(?) AS wallet",
                [sorted(wallets)])
    raw = f"""
      SELECT o.wallet, o.coin, o.ts, o.dir_sign,
             SUM(CAST(o.notl AS DECIMAL(38,12))) AS notl_dec
      FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN dt_wallets USING(wallet)
      WHERE o.coin IN ({majors})
      GROUP BY o.wallet, o.coin, o.ts, o.dir_sign
    """
    amb = """SELECT wallet, coin, ts FROM blk GROUP BY wallet, coin, ts
             HAVING COUNT(DISTINCT dir_sign)>1"""
    stmp = sp.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH blk AS ({raw}), amb AS ({amb})
      SELECT b.wallet,b.coin,b.ts,b.dir_sign,CAST(b.notl_dec AS DOUBLE) AS notl,
             (a.wallet IS NOT NULL) AS is_ambiguous,(b.ts <= {cutoff}) AS passes_cutoff
      FROM blk b LEFT JOIN amb a USING(wallet,coin,ts)
      ORDER BY b.ts,b.wallet,b.coin,b.dir_sign
    ) TO '{stmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    stmp.replace(sp)

    support_sql, support_last, support_expr = common_support_sql()
    etmp = ep.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH blk AS ({raw}), amb AS ({amb}),
      ent AS (
        SELECT b.* FROM blk b ANTI JOIN amb a USING(wallet,coin,ts)
        WHERE b.ts <= {cutoff} AND b.notl_dec >= CAST({NOTL_MIN} AS DECIMAL(38,12))
      ), ctx AS (
        SELECT coin,ts,mid_px FROM read_parquet([{ctx_list}])
        WHERE coin IN ({majors}) AND mid_px IS NOT NULL
      ), {support_sql}, supported AS (
        SELECT *,COALESCE({support_expr},FALSE) AS common_outcome_support FROM {support_last}
      ), p0 AS (
        SELECT e.*,c.mid_px AS px0,c.ts AS entry_ts
        FROM supported e ASOF LEFT JOIN ctx c ON e.coin=c.coin AND e.ts<c.ts
      ), p8 AS (
        SELECT p0.*,c.mid_px AS px8,c.ts AS exit_ts
        FROM p0 ASOF LEFT JOIN ctx c
          ON p0.coin=c.coin AND (p0.entry_ts+{HOLD_MS})<=c.ts
      )
      SELECT wallet,coin,ts AS signal_ts,dir_sign,CAST(notl_dec AS DOUBLE) AS notl,
             entry_ts,exit_ts,common_outcome_support,
             COALESCE(px0 IS NOT NULL AND px0>0 AND entry_ts-ts<={STALE_MS},FALSE)
               AS entry_supported,
             CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0>0
                    AND entry_ts-ts <= {STALE_MS}
                    AND exit_ts-(entry_ts+{HOLD_MS}) <= {STALE_MS}
                  THEN dir_sign*(px8-px0)/px0*1e4 END AS gross_bp
      FROM p8 ORDER BY signal_ts,wallet,coin,dir_sign
    ) TO '{etmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    etmp.replace(ep)

    qtmp = qp.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH wd AS (
        SELECT d.wallet,d.day,
          SUM(CAST(d.pnl AS DECIMAL(38,12)))
            -SUM(CAST(d.fee AS DECIMAL(38,12)))
            -SUM(COALESCE(CAST(d.builder_fee AS DECIMAL(38,12)),0)) AS net_pnl,
          SUM(CAST(d.notional AS DECIMAL(38,12))) AS day_notional,
          SUM(d.n_liq)::BIGINT AS n_liq
        FROM read_parquet('{lake.wcd_month_glob(fold)}') d JOIN dt_wallets USING(wallet)
        WHERE d.coin IN ({majors}) GROUP BY d.wallet,d.day
      )
      SELECT wallet,day,n_liq,net_pnl,day_notional
      FROM wd WHERE day_notional>0 ORDER BY wallet,day
    ) TO '{qtmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    qtmp.replace(qp)
    post_lineage = lake.validated_lineage(
        con, [fold], ("alt_universe_wallet_coin_day", "alt_universe_open_entries")
    )
    post_ctx = _context_records(ctx)
    if (post_lineage["sha256"] != spec["source_lineage"]["sha256"]
            or post_ctx != ctx_files):
        for bad in (ep, sp, qp):
            bad.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: source/context mutated during materialization")
    mtmp = meta.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mtmp.replace(meta)
    return ep, sp, qp


def _read(path: Path) -> dict[str, np.ndarray]:
    d = pq.read_table(path).to_pydict()
    out = {k: np.asarray(v) for k, v in d.items()}
    for k in ("wallet", "coin"):
        if k in out:
            out[k] = out[k].astype(str)
    for k in ("ts", "signal_ts", "entry_ts", "exit_ts", "dir_sign", "day", "n_liq"):
        if k in out:
            out[k] = out[k].astype(np.int64)
    for k in ("notl", "gross_bp", "x"):
        if k in out:
            out[k] = np.asarray(out[k], float)
    if "is_ambiguous" in out:
        out["is_ambiguous"] = out["is_ambiguous"].astype(bool)
    if "passes_cutoff" in out:
        out["passes_cutoff"] = out["passes_cutoff"].astype(bool)
    for k in ("common_outcome_support", "entry_supported"):
        if k in out:
            out[k] = out[k].astype(bool)
    return out


def shock_days(shocks: dict[str, np.ndarray]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    x = np.array([normalized_x(p, n) for p, n in
                  zip(shocks["net_pnl"], shocks["day_notional"], strict=True)], float)
    m = (shocks["n_liq"] > 0) | (x <= -BLOWUP_USD)
    for w, day in zip(shocks["wallet"][m], shocks["day"][m], strict=True):
        out.setdefault(str(w), []).append(_day_epoch(int(day)))
    return out


def online_quarantined(wallet: str, signal_ts: int, by_wallet: dict[str, list[int]]) -> bool:
    entry_day = int(signal_ts // DAY_MS)
    return any(s + 1 <= entry_day <= s + QUARANTINE_DAYS for s in by_wallet.get(wallet, []))


def accept_book(ent: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, int]]:
    order = np.lexsort((ent["dir"], ent["coin"], ent["wallet"], ent["signal_ts"],
                        ent["entry_ts"]))
    wc_until: dict[tuple[str, str], int] = {}
    wh: dict[str, list[int]] = {}
    ch: dict[str, list[int]] = {}
    keep: list[int] = []
    f = {"n_wallet_coin_skip": 0, "n_wallet_cap_skip": 0, "n_coin_cap_skip": 0}
    for i in order:
        w, c = str(ent["wallet"][i]), str(ent["coin"][i])
        t, ex = int(ent["entry_ts"][i]), int(ent["exit_ts"][i])
        hw, hc = wh.setdefault(w, []), ch.setdefault(c, [])
        while hw and hw[0] <= t:
            heapq.heappop(hw)
        while hc and hc[0] <= t:
            heapq.heappop(hc)
        if wc_until.get((w, c), -1) > t:
            f["n_wallet_coin_skip"] += 1
            continue
        if (len(hw) + 1) * UNIT_USD > WALLET_CAP_USD:
            f["n_wallet_cap_skip"] += 1
            continue
        if (len(hc) + 1) * UNIT_USD > COIN_CAP_USD:
            f["n_coin_cap_skip"] += 1
            continue
        wc_until[(w, c)] = ex
        heapq.heappush(hw, ex)
        heapq.heappush(hc, ex)
        keep.append(int(i))
    return np.asarray(keep, np.int64), f


def consensus_other_counts(entries: dict[str, np.ndarray], signals: dict[str, np.ndarray],
                           top_half: set[str]) -> np.ndarray:
    out = np.zeros(entries["signal_ts"].size, np.int64)
    ekey = np.char.add(np.char.add(entries["coin"], "|"), entries["dir"].astype(str))
    skey = np.char.add(np.char.add(signals["coin"], "|"), signals["dir"].astype(str))
    win = 6 * 3_600_000
    for key in np.unique(ekey):
        ei, si = np.flatnonzero(ekey == key), np.flatnonzero(skey == key)
        eo = ei[np.argsort(entries["signal_ts"][ei], kind="stable")]
        so = si[np.argsort(signals["ts"][si], kind="stable")]
        last: dict[str, int] = {}
        j = 0
        for idx in eo:
            t, w = int(entries["signal_ts"][idx]), str(entries["wallet"][idx])
            while j < so.size and int(signals["ts"][so[j]]) < t:
                last[str(signals["wallet"][so[j]])] = int(signals["ts"][so[j]])
                j += 1
            out[idx] = sum(sw != w and sw in top_half and lt >= t - win
                           for sw, lt in last.items())
    return out


def _arm_fold(entries: dict[str, np.ndarray], signals: dict[str, np.ndarray],
              roster: list[str], fold: int, online_shocks: dict[str, list[int]],
              apply_shock: bool) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    rset = set(roster)
    in_arm = np.array([w in rset for w in entries["wallet"]])
    entry_ok = entries["entry_supported"] & np.isfinite(entries["entry_ts"])
    q = np.zeros(entries["wallet"].size, bool)
    if apply_shock:
        q = np.array([online_quarantined(str(w), int(t), online_shocks)
                      for w, t in zip(entries["wallet"], entries["signal_ts"], strict=True)])
    m = in_arm & ~q
    cap_entry = np.where(entry_ok[m], entries["entry_ts"][m], entries["signal_ts"][m])
    cap_exit = np.where(
        entry_ok[m], entries["entry_ts"][m] + HOLD_MS + STALE_MS,
        entries["signal_ts"][m] + HOLD_MS + 2 * STALE_MS,
    )
    e = {
        "wallet": entries["wallet"][m], "coin": entries["coin"][m],
        "signal_ts": entries["signal_ts"][m], "entry_ts": cap_entry,
        "exit_ts": cap_exit,
        "actual_exit_ts": entries["exit_ts"][m], "dir": entries["dir_sign"][m],
        "gross_bp": entries["gross_bp"][m],
        "outcome_supported": entries["common_outcome_support"][m],
        "entry_context_available": entry_ok[m],
    }
    sr = np.array([w in rset for w in signals["wallet"]])
    amb = signals["is_ambiguous"]
    cutoff = signals["passes_cutoff"]
    sm = sr & cutoff & ~amb
    sig = {"wallet": signals["wallet"][sm], "coin": signals["coin"][sm],
           "ts": signals["ts"][sm], "dir": signals["dir_sign"][sm]}
    acc, skips = accept_book(e)
    cons = consensus_other_counts(e, sig, set(roster[:TOP_HALF]))
    accepted = np.zeros(e["wallet"].size, bool)
    accepted[acc] = True
    smart = cons >= 1
    out = {k: v[accepted] for k, v in e.items()}
    out["net_bp"] = out.pop("gross_bp") - COST_BP
    out["fold"] = np.full(out["wallet"].size, fold, np.int64)
    out["smart"] = smart[accepted]
    out["actual_outcome_available"] = np.isfinite(out["net_bp"])
    amb_keys = np.unique(np.char.add(
        np.char.add(np.char.add(signals["wallet"][sr & cutoff], "|"),
                    signals["coin"][sr & cutoff]),
        np.char.add("|", signals["ts"][sr & cutoff].astype(str)),
    )[amb[sr & cutoff]]).size
    return out, {
        "n_collapsed_pre_ambiguity": int(sr.sum()),
        "n_common_cutoff_excluded": int(np.sum(sr & ~cutoff)),
        "n_ambiguous_keys_dropped": int(amb_keys),
        "n_ambiguous_direction_rows_dropped": int(np.sum(sr & cutoff & amb)),
        "n_collapsed_signals": int(sm.sum()),
        "n_below_250": int(np.sum(sm & (signals["notl"] < NOTL_MIN))),
        "n_threshold_candidates": int(np.sum(in_arm)),
        "n_entry_context_reserved": int(np.sum(in_arm & ~entry_ok & ~q)),
        "entry_context_reserved_rate": (float(np.sum(in_arm & ~entry_ok & ~q) / in_arm.sum())
                                         if in_arm.any() else None),
        "n_online_quarantine": int(np.sum(in_arm & q)),
        "n_capacity_candidates": int(m.sum()), **skips,
        "n_accepted_capacity": int(acc.size),
        "n_common_support_excluded_after_accept": int(np.sum(
            accepted & ~e["outcome_supported"])),
        "n_defensive_exit_failure": int(np.sum(
            accepted & e["outcome_supported"] & ~np.isfinite(e["gross_bp"]))),
        "n_accepted": int(np.sum(accepted & e["outcome_supported"]
                                 & np.isfinite(e["gross_bp"]))),
        "n_smart_capacity": int(np.sum(accepted & smart)),
        "n_smart": int(np.sum(accepted & smart & e["outcome_supported"]
                              & np.isfinite(e["gross_bp"]))),
    }


def _concat(parts: list[dict[str, np.ndarray]], smart: bool = False,
            kind: str = "supported") -> dict[str, np.ndarray]:
    keys = ("wallet", "coin", "signal_ts", "entry_ts", "exit_ts", "actual_exit_ts",
            "dir", "net_bp", "fold", "smart", "outcome_supported",
            "actual_outcome_available", "entry_context_available")
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    if kind == "supported":
        m = out["outcome_supported"] & out["actual_outcome_available"]
    elif kind == "actual":
        m = out["actual_outcome_available"]
    elif kind == "capacity":
        m = np.ones(out["wallet"].size, bool)
    else:
        raise ValueError(f"unknown concat kind {kind}")
    if smart:
        m &= out["smart"]
    return {k: v[m] for k, v in out.items()}


def _point(book: dict[str, np.ndarray]) -> float:
    return float(np.mean(book["net_bp"])) if book["net_bp"].size else math.nan


def _resample_delta(a: dict[str, np.ndarray], b: dict[str, np.ndarray], rng,
                    mode: str, calendar_lo: int, calendar_hi: int,
                    n_boot: int = N_BOOT) -> tuple[np.ndarray, float]:
    wallets = np.unique(np.concatenate([a["wallet"], b["wallet"]]))
    wi = {w: i for i, w in enumerate(wallets)}
    aw = np.array([wi[w] for w in a["wallet"]], np.int64)
    bw = np.array([wi[w] for w in b["wallet"]], np.int64)
    nday = calendar_hi - calendar_lo + 1
    ad = a["signal_ts"] // DAY_MS - calendar_lo
    bd = b["signal_ts"] // DAY_MS - calendar_lo
    if nday <= 0 or np.any((ad < 0) | (ad >= nday)) or np.any((bd < 0) | (bd >= nday)):
        raise RuntimeError("book rows outside frozen evaluation calendar")
    block = min(BLOCK_DAYS, nday)
    nblocks = int(math.ceil(nday / block))
    out = np.full(n_boot, np.nan)
    for draw in range(n_boot):
        wm = np.ones(wallets.size)
        tm = np.ones(nday)
        if mode in ("wallet", "crossed"):
            wm = np.bincount(rng.integers(0, wallets.size, wallets.size),
                             minlength=wallets.size).astype(float)
        if mode in ("time", "crossed"):
            starts = rng.integers(0, nday - block + 1, nblocks)
            picked = np.concatenate([np.arange(s, s + block) for s in starts])[:nday]
            tm = np.bincount(picked, minlength=nday).astype(float)
        wa, wb = wm[aw] * tm[ad], wm[bw] * tm[bd]
        na, nb = wa.sum(), wb.sum()
        if na > 0 and nb > 0:
            out[draw] = float(wa @ a["net_bp"] / na - wb @ b["net_bp"] / nb)
    invalid = float(np.mean(~np.isfinite(out)))
    return out[np.isfinite(out)], invalid


def _resample_mean(book: dict[str, np.ndarray], rng, mode: str,
                   calendar_lo: int, calendar_hi: int,
                   n_boot: int = N_BOOT) -> tuple[np.ndarray, float]:
    wallets, wi = np.unique(book["wallet"], return_inverse=True)
    nday = calendar_hi - calendar_lo + 1
    day = book["signal_ts"] // DAY_MS - calendar_lo
    if nday <= 0 or np.any((day < 0) | (day >= nday)):
        raise RuntimeError("book rows outside frozen evaluation calendar")
    block = min(BLOCK_DAYS, nday)
    nb = int(math.ceil(nday / block))
    out = np.full(n_boot, np.nan)
    for draw in range(n_boot):
        wm = np.ones(wallets.size)
        tm = np.ones(nday)
        if mode in ("wallet", "crossed"):
            wm = np.bincount(rng.integers(0, wallets.size, wallets.size),
                             minlength=wallets.size).astype(float)
        if mode in ("time", "crossed"):
            starts = rng.integers(0, nday - block + 1, nb)
            picked = np.concatenate([np.arange(s, s + block) for s in starts])[:nday]
            tm = np.bincount(picked, minlength=nday).astype(float)
        weight = wm[wi] * tm[day]
        if weight.sum() > 0:
            out[draw] = float(weight @ book["net_bp"] / weight.sum())
    invalid = float(np.mean(~np.isfinite(out)))
    return out[np.isfinite(out)], invalid


def _support(book: dict[str, np.ndarray], calendar_lo: int) -> dict[str, int]:
    blocks = np.unique((book["signal_ts"] // DAY_MS - calendar_lo) // BLOCK_DAYS)
    return {"wallets": int(np.unique(book["wallet"]).size),
            "occupied_calendar_blocks": int(blocks.size)}


def _not_estimable(delta: float, reason: str, sa: dict, sb: dict) -> dict[str, object]:
    return {"delta_bp": delta, "inference_status": "SPARSE_NOT_ESTIMABLE",
            "inference_reason": reason, "support_a": sa, "support_b": sb,
            "wallet_ci95": None, "time_ci95": None, "crossed_ci95": None,
            "crossed_p_two_sided": None, "crossed_mde80_bp": None,
            "crossed_power_at_plus5": None, "plus5_control_pass": False,
            "holm_eligible": False}


def compare(a: dict[str, np.ndarray], b: dict[str, np.ndarray], seed: int,
            calendar_lo: int, calendar_hi: int,
            n_boot: int = N_BOOT) -> dict[str, object]:
    delta = _point(a) - _point(b)
    sa, sb = _support(a, calendar_lo), _support(b, calendar_lo)
    if (not a["net_bp"].size or not b["net_bp"].size
            or min(sa["wallets"], sb["wallets"]) < MIN_INFER_WALLETS
            or min(sa["occupied_calendar_blocks"], sb["occupied_calendar_blocks"])
            < MIN_INFER_BLOCKS):
        return _not_estimable(delta, "fewer than 10 wallets or 10 occupied 7-day blocks", sa, sb)
    wb, iw = _resample_delta(a, b, np.random.default_rng(seed), "wallet",
                             calendar_lo, calendar_hi, n_boot)
    tb, it = _resample_delta(a, b, np.random.default_rng(seed + 1), "time",
                             calendar_lo, calendar_hi, n_boot)
    cb, ic = _resample_delta(a, b, np.random.default_rng(seed + 2), "crossed",
                             calendar_lo, calendar_hi, n_boot)
    if max(iw, it, ic) > MAX_INVALID_BOOT_FRAC:
        out = _not_estimable(delta, "bootstrap zero-denominator rate exceeds 1%", sa, sb)
        out["invalid_draw_fraction"] = {"wallet": iw, "time": it, "crossed": ic}
        return out
    def ci(x: np.ndarray) -> list[float]:
        return [float(np.quantile(x, .025)), float(np.quantile(x, .975))]
    noise = cb - cb.mean()
    critical = float(np.quantile(noise, .975))
    mde80 = critical - float(np.quantile(noise, .20))
    power5 = float(np.mean(noise + 5.0 > critical))
    p = float((1 + np.sum(np.abs(noise) >= abs(delta))) / (cb.size + 1))
    p_null5 = float((1 + np.sum(noise <= delta - 5.0)) / (cb.size + 1))
    per_fold, per_coin = {}, {}
    for fold in FOLDS:
        am, bm = a["fold"] == fold, b["fold"] == fold
        per_fold[str(fold)] = (float(a["net_bp"][am].mean() - b["net_bp"][bm].mean())
                               if am.any() and bm.any() else None)
    for coin in MAJORS:
        am, bm = a["coin"] == coin, b["coin"] == coin
        per_coin[coin] = (float(a["net_bp"][am].mean() - b["net_bp"][bm].mean())
                          if am.any() and bm.any() else None)
    return {"delta_bp": delta, "wallet_ci95": ci(wb), "time_ci95": ci(tb),
            "crossed_ci95": ci(cb), "crossed_p_two_sided": p,
            "p_null_plus5_one_sided": p_null5,
            "crossed_mde80_bp": mde80, "crossed_power_at_plus5": power5,
            "plus5_control_pass": power5 >= .80, "n_boot": n_boot,
            "block_days": BLOCK_DAYS, "per_fold_delta_bp": per_fold,
            "folds_positive": sum(v is not None and v > 0 for v in per_fold.values()),
            "per_coin_delta_bp": per_coin,
            "coins_positive": sum(v is not None and v > 0 for v in per_coin.values()),
            "inference_status": "ESTIMABLE", "holm_eligible": True,
            "support_a": sa, "support_b": sb,
            "invalid_draw_fraction": {"wallet": iw, "time": it, "crossed": ic}}


def _missingness_arm(cap: dict[str, np.ndarray]) -> dict[str, object]:
    n = cap["wallet"].size
    analyzed = cap["outcome_supported"] & cap["actual_outcome_available"]
    excluded = ~analyzed
    actual_excluded = excluded & cap["actual_outcome_available"]
    per_fold = {}
    for fold in FOLDS:
        m = cap["fold"] == fold
        per_fold[str(fold)] = {
            "accepted_capacity": int(m.sum()), "excluded": int(np.sum(m & excluded)),
            "excluded_rate": float(np.mean(excluded[m])) if m.any() else None,
        }
    def strata(values: np.ndarray) -> dict[str, dict[str, object]]:
        out = {}
        for v in np.unique(values):
            m = values == v
            out[str(v)] = {"accepted_capacity": int(m.sum()),
                           "excluded": int(np.sum(excluded & m)),
                           "excluded_rate": float(np.mean(excluded[m]))}
        return out
    hour = (cap["signal_ts"] // 3_600_000) % 24
    day = cap["signal_ts"] // DAY_MS
    return {
        "accepted_capacity": int(n), "analyzed": int(analyzed.sum()),
        "excluded": int(excluded.sum()),
        "excluded_rate": float(excluded.mean()) if n else math.nan,
        "genuinely_unpriced": int(np.sum(~cap["actual_outcome_available"])),
        "accepted_entry_context_reservations": int(np.sum(~cap["entry_context_available"])),
        "excluded_actual_coin_mean_net_bp": (
            float(cap["net_bp"][actual_excluded].mean()) if actual_excluded.any() else None),
        "per_fold": per_fold, "by_coin": strata(cap["coin"]),
        "by_utc_hour": strata(hour), "by_epoch_day": strata(day),
        "by_wallet": strata(cap["wallet"]),
    }


def _bound_book(cap: dict[str, np.ndarray], missing_value: float) -> dict[str, np.ndarray]:
    out = {k: v.copy() for k, v in cap.items()}
    out["net_bp"][~out["actual_outcome_available"]] = missing_value
    return out


def add_missingness_sensitivity(result: dict[str, object],
                                cap_a: dict[str, np.ndarray], cap_b: dict[str, np.ndarray],
                                actual_a: dict[str, np.ndarray], actual_b: dict[str, np.ndarray],
                                seed: int, calendar_lo: int, calendar_hi: int,
                                n_boot: int = N_BOOT) -> None:
    """Attach rate gates and uncertainty-aware actual/bounded missing-outcome sensitivities."""
    ma, mb = _missingness_arm(cap_a), _missingness_arm(cap_b)
    rate_ok = (
        ma["excluded_rate"] <= MAX_SUPPORT_LOSS
        and mb["excluded_rate"] <= MAX_SUPPORT_LOSS
        and abs(ma["excluded_rate"] - mb["excluded_rate"]) <= MAX_SUPPORT_RATE_IMBALANCE
        and all((v["excluded_rate"] is None or v["excluded_rate"] <= MAX_FOLD_SUPPORT_LOSS)
                for v in ma["per_fold"].values())
        and all((v["excluded_rate"] is None or v["excluded_rate"] <= MAX_FOLD_SUPPORT_LOSS)
                for v in mb["per_fold"].values())
    )
    actual_cmp = compare(actual_a, actual_b, seed + 1, calendar_lo, calendar_hi, n_boot)
    low_a, low_b = (_bound_book(cap_a, -MISSING_RETURN_BOUND_BP),
                    _bound_book(cap_b, MISSING_RETURN_BOUND_BP))
    high_a, high_b = (_bound_book(cap_a, MISSING_RETURN_BOUND_BP),
                      _bound_book(cap_b, -MISSING_RETURN_BOUND_BP))
    lower, il = _resample_delta(low_a, low_b, np.random.default_rng(seed + 2), "crossed",
                                calendar_lo, calendar_hi, n_boot)
    upper, iu = _resample_delta(high_a, high_b, np.random.default_rng(seed + 3), "crossed",
                                calendar_lo, calendar_hi, n_boot)
    valid = (rate_ok and result.get("inference_status") == "ESTIMABLE"
             and actual_cmp.get("inference_status") == "ESTIMABLE"
             and max(il, iu) <= MAX_INVALID_BOOT_FRAC)
    low_ci = ([float(np.quantile(lower, .025)), float(np.quantile(lower, .975))]
              if lower.size and il <= MAX_INVALID_BOOT_FRAC else None)
    high_ci = ([float(np.quantile(upper, .025)), float(np.quantile(upper, .975))]
               if upper.size and iu <= MAX_INVALID_BOOT_FRAC else None)
    upper_point = _point(high_a) - _point(high_b)
    upper_noise = upper - upper.mean() if upper.size else np.array([])
    upper_null_p = (float((1 + np.sum(upper_noise <= upper_point - 5.0))
                          / (upper_noise.size + 1)) if upper_noise.size else None)
    null_iut_p = (max(float(result["p_null_plus5_one_sided"]),
                      float(actual_cmp["p_null_plus5_one_sided"]), upper_null_p)
                  if valid and upper_null_p is not None else None)
    positive_pass = bool(
        valid and result["crossed_ci95"][0] > 0
        and actual_cmp["crossed_ci95"][0] > 0 and low_ci[0] > 0
    )
    null_pass = bool(
        valid and result["crossed_mde80_bp"] <= 5
        and result["crossed_ci95"][1] < 5
        and actual_cmp["crossed_ci95"][1] < 5 and high_ci[1] < 5
    )

    def required_missing_a(target: float) -> float | None:
        miss = int(np.sum(~cap_a["actual_outcome_available"]))
        if miss == 0:
            return None
        sa = float(np.nansum(cap_a["net_bp"]))
        sb = float(np.nansum(cap_b["net_bp"]))
        return float(((target + sb / cap_b["wallet"].size) * cap_a["wallet"].size - sa) / miss)

    result["missingness"] = {
        "arm_a": ma, "arm_b": mb, "rate_gates_pass": rate_ok,
        "all_actual_coin": actual_cmp,
        "bounded_stress_bp": MISSING_RETURN_BOUND_BP,
        "adverse_lower_crossed_ci95": low_ci, "favorable_upper_crossed_ci95": high_ci,
        "invalid_draw_fraction": {"lower": il, "upper": iu},
        "p_null_plus5_favorable_bound": upper_null_p,
        "p_null_plus5_intersection_union": null_iut_p,
        "required_arm_a_missing_mean_for_delta_zero": required_missing_a(0.0),
        "required_arm_a_missing_mean_for_delta_plus5": required_missing_a(5.0),
        "positive_sensitivity_pass": positive_pass, "null_sensitivity_pass": null_pass,
        "computation_status": "VALID" if valid else "NOT_ESTIMABLE",
        "status": "SENSITIVITY_COMPUTED" if valid else "MISSINGNESS_UNRESOLVED",
    }


def finalize_decision_flags(primary: dict[str, object],
                            secondary: dict[str, dict[str, object]], *,
                            formal_eligibility: bool = True) -> None:
    """Make missingness/multiplicity gates impossible to miss in downstream framing."""
    def base_flags(r: dict[str, object], *, q_required: bool) -> None:
        missing = r.get("missingness", {})
        estimable = r.get("inference_status") == "ESTIMABLE"
        rate_ok = bool(missing.get("rate_gates_pass"))
        positive = bool(
            estimable and rate_ok and r.get("delta_bp", math.nan) > 0
            and r.get("crossed_ci95") is not None and r["crossed_ci95"][0] > 0
            and missing.get("positive_sensitivity_pass")
            and (not q_required or r.get("holm_q", 1.0) <= .05)
        )
        method_null = bool(
            estimable and rate_ok and r.get("crossed_mde80_bp") is not None
            and r["crossed_mde80_bp"] <= 5 and missing.get("null_sensitivity_pass")
            and r.get("plus5_control_pass")
            and (not q_required or r.get("null_plus5_holm_q", 1.0) <= .05)
        )
        r["within_run_positive_direction"] = positive
        r["within_run_null_resolution_pass"] = method_null
        r["positive_promotion_eligible"] = positive and formal_eligibility
        r["method_null_eligible"] = method_null and formal_eligibility
        if not formal_eligibility:
            r["verdict_status"] = "BURNED_ADAPTIVE_CANDIDATE_DIAGNOSTIC"
            return
        if not estimable:
            r["verdict_status"] = r.get("inference_status", "NOT_ESTIMABLE")
        elif not rate_ok or missing.get("computation_status") != "VALID":
            r["verdict_status"] = "MISSINGNESS_UNRESOLVED"
        elif positive:
            r["verdict_status"] = "POSITIVE_ELIGIBLE_POST_HOC"
        elif method_null:
            r["verdict_status"] = "METHOD_NULL_ELIGIBLE_POST_HOC"
        else:
            r["verdict_status"] = "INCONCLUSIVE"

    base_flags(primary, q_required=False)
    for result in secondary.values():
        base_flags(result, q_required=True)


def holm_adjust(results: dict[str, dict[str, object]]) -> None:
    ordered = sorted(results, key=lambda k: (
        float(results[k]["crossed_p_two_sided"])
        if results[k].get("crossed_p_two_sided") is not None else 1.0, k))
    running = 0.0
    m = len(ordered)
    for rank, name in enumerate(ordered):
        p = (float(results[name]["crossed_p_two_sided"])
             if results[name].get("crossed_p_two_sided") is not None else 1.0)
        running = max(running, (m - rank) * p)
        results[name]["holm_q"] = min(1.0, running)


def holm_adjust_null(results: dict[str, dict[str, object]]) -> None:
    """Separate four-test Holm family for method-null H0: improvement >= +5bp."""
    ordered = sorted(results, key=lambda k: (
        float(results[k]["missingness"]["p_null_plus5_intersection_union"])
        if results[k]["missingness"].get("p_null_plus5_intersection_union") is not None
        else 1.0, k))
    running = 0.0
    m = len(ordered)
    for rank, name in enumerate(ordered):
        p = results[name]["missingness"].get("p_null_plus5_intersection_union")
        p = float(p) if p is not None else 1.0
        running = max(running, (m - rank) * p)
        results[name]["null_plus5_holm_q"] = min(1.0, running)


def _book_stats(book: dict[str, np.ndarray], seed: int,
                calendar_lo: int, calendar_hi: int) -> dict[str, object]:
    bp = book["net_bp"]
    if bp.size == 0:
        return {"n_entries": 0, "crossed_ci95": None}
    wb, iw = _resample_mean(book, np.random.default_rng(seed), "wallet",
                            calendar_lo, calendar_hi)
    tb, it = _resample_mean(book, np.random.default_rng(seed + 1), "time",
                            calendar_lo, calendar_hi)
    cb, ic = _resample_mean(book, np.random.default_rng(seed + 2), "crossed",
                            calendar_lo, calendar_hi)
    wallet_usd = {w: float(bp[book["wallet"] == w].sum() * 1e-4 * UNIT_USD)
                  for w in np.unique(book["wallet"])}
    fold_usd = {int(f): float(bp[book["fold"] == f].sum() * 1e-4 * UNIT_USD)
                for f in FOLDS if np.any(book["fold"] == f)}
    bw, bf = max(wallet_usd, key=wallet_usd.get), max(fold_usd, key=fold_usd.get)
    nw, nf, nh = book["wallet"] != bw, book["fold"] != bf, book["coin"] != "HYPE"
    per_fold = {str(f): (float(bp[book["fold"] == f].mean())
                         if np.any(book["fold"] == f) else None) for f in FOLDS}
    support = _support(book, calendar_lo)

    def usable_ci(draws: np.ndarray, invalid: float) -> list[float] | None:
        if invalid > MAX_INVALID_BOOT_FRAC or draws.size == 0:
            return None
        return [float(np.quantile(draws, .025)), float(np.quantile(draws, .975))]

    return {
        "n_entries": int(bp.size), "n_wallets": int(len(wallet_usd)),
        "net_bp_per_entry": float(bp.mean()),
        "wallet_ci95": usable_ci(wb, iw), "time_ci95": usable_ci(tb, it),
        "crossed_ci95": usable_ci(cb, ic),
        "inference_status": (
            "ESTIMABLE" if min(support.values()) >= 10 and max(iw, it, ic) <= .01
            else "SPARSE_NOT_ESTIMABLE"
        ),
        "support": support,
        "invalid_draw_fraction": {"wallet": iw, "time": it, "crossed": ic},
        "net_usd": float(bp.sum() * 1e-4 * UNIT_USD), "hit_rate": float((bp > 0).mean()),
        "median_bp": float(np.median(bp)), "p90_bp": float(np.quantile(bp, .9)),
        "p99_bp": float(np.quantile(bp, .99)), "per_fold_bp": per_fold,
        "folds_positive": sum(v is not None and v > 0 for v in per_fold.values()),
        "drop_best_wallet": {"wallet": bw, "net_bp": float(bp[nw].mean()) if nw.any() else None},
        "drop_best_fold": {"fold": bf, "net_bp": float(bp[nf].mean()) if nf.any() else None},
        "exclude_HYPE_net_bp": float(bp[nh].mean()) if nh.any() else None,
        "top5_wallet_abs_pnl_share": float(
            sum(sorted((abs(v) for v in wallet_usd.values()), reverse=True)[:5])
            / sum(abs(v) for v in wallet_usd.values())
        ) if sum(abs(v) for v in wallet_usd.values()) else None,
    }


def validate_roster_profile(rosters: dict, profile: StudyProfile) -> None:
    registered = rosters.get("config", {})
    expected_identity = {
        "experiment_id": profile.experiment_id,
        "half_life_days": profile.half_life_days,
    }
    got_identity = {k: registered.get(k) for k in expected_identity}
    if got_identity != expected_identity or rosters.get("architecture") != profile.architecture:
        raise RuntimeError(
            f"roster/profile mismatch: got {got_identity}, arch={rosters.get('architecture')}; "
            f"expected {expected_identity}, arch={profile.architecture}"
        )


def run(*, profile: StudyProfile) -> dict:
    rosters_path = profile.rosters
    entries_dir = profile.derived / "entries"
    output = profile.derived / "book_report.json"
    rosters = json.loads(rosters_path.read_text())
    validate_roster_profile(rosters, profile)
    con = lake.connect()
    parts = {a: [] for a in ARMS}
    funnels = {a: {} for a in ARMS}
    cache_hashes = {}
    fold_cutoffs: dict[str, int] = {}
    for fold in FOLDS:
        fr = rosters["folds"][str(fold)]["rosters"]
        current_selector_spec = _selector_cache_spec(con, fold, profile=profile)
        registered_selector_hash = rosters["folds"][str(fold)].get(
            "panel_cache_spec_sha256"
        )
        if _sha256_json(current_selector_spec) != registered_selector_hash:
            raise RuntimeError(f"fold {fold}: stale roster formation lineage/config")
        union = sorted({w for arm in ARMS for w in fr[arm]})
        print(f"[dynamic-t book] fold {fold}: {len(union)} union wallets", flush=True)
        ep, sp, qp = _cache_fold(
            con, fold, union, entries_dir=entries_dir, profile=profile
        )
        fold_meta = json.loads(
            (entries_dir / f"cache_{fold}.meta.json").read_text()
        )
        cache_hashes[str(fold)] = _sha256_json(fold_meta)
        fold_cutoffs[str(fold)] = int(fold_meta["common_signal_cutoff_ms"])
        ent, sig, sh = _read(ep), _read(sp), _read(qp)
        online = shock_days(sh)
        for arm in ARMS:
            p, fun = _arm_fold(ent, sig, fr[arm], fold, online, arm in SHOCK_ARMS)
            parts[arm].append(p)
            funnels[arm][str(fold)] = fun
            print(f"  {arm}: {fun}", flush=True)
    con.close()
    capacity = {a: _concat(parts[a], kind="capacity") for a in ARMS}
    actual = {a: _concat(parts[a], kind="actual") for a in ARMS}
    books = {a: _concat(parts[a], kind="supported") for a in ARMS}
    smart_capacity = {a: _concat(parts[a], smart=True, kind="capacity") for a in ARMS}
    smart_actual = {a: _concat(parts[a], smart=True, kind="actual") for a in ARMS}
    smart = {a: _concat(parts[a], smart=True, kind="supported") for a in ARMS}
    calendar_lo = _day_epoch(20251101)
    calendar_hi = fold_cutoffs["202606"] // DAY_MS
    code_paths = (Path(__file__), Path(__file__).with_name("dynamic_t_quality.py"),
                  Path(__file__).with_name("alt_fresh_validate.py"),
                  Path(__file__).with_name("filtered_quality.py"))
    rep: dict[str, object] = {
        "status": "POST-HOC BURNED DIAGNOSTIC; NOT FORWARD EVIDENCE",
        "verdict_eligible": False,
        "config": {"unit_usd": UNIT_USD, "wallet_cap_usd": WALLET_CAP_USD,
                   "experiment_id": profile.experiment_id,
                   "half_life_days": profile.half_life_days,
                   "architecture": profile.architecture,
                   "coin_cap_usd": COIN_CAP_USD, "notional_min": NOTL_MIN,
                   "hold_h": 8, "cost_bp": COST_BP, "n_boot": N_BOOT,
                   "block_days": BLOCK_DAYS, "seed": SEED,
                   "evaluation_calendar_epoch_days": [calendar_lo, calendar_hi],
                   "fold_common_cutoffs_ms": fold_cutoffs,
                   "code_commit": lake.git_describe(), "code_sha256": _code_sha256(*code_paths),
                   "rosters_sha256": hashlib.sha256(rosters_path.read_bytes()).hexdigest(),
                   "fold_cache_spec_sha256": cache_hashes},
        "funnels": funnels, "books": {}, "primary": {}, "secondary": {},
    }
    for j, arm in enumerate(ARMS):
        rep["books"][arm] = _book_stats(
            books[arm], SEED + 100 + j, calendar_lo, calendar_hi)
        rep["books"][arm + "_SMART"] = _book_stats(
            smart[arm], SEED + 200 + j, calendar_lo, calendar_hi)
        print(f"{arm}: n={books[arm]['net_bp'].size:,} net={_point(books[arm]):+.2f}bp; "
              f"smart n={smart[arm]['net_bp'].size:,} net={_point(smart[arm]):+.2f}bp", flush=True)
    rep["primary"] = compare(
        books["EW_T30"], books["TSTAT_COMMON30"], SEED, calendar_lo, calendar_hi)
    add_missingness_sensitivity(
        rep["primary"], capacity["EW_T30"], capacity["TSTAT_COMMON30"],
        actual["EW_T30"], actual["TSTAT_COMMON30"], SEED + 1_000,
        calendar_lo, calendar_hi)
    second = {
        "EW_HAC_minus_HAC": compare(
            books["EW_HAC_T30"], books["HAC_T30"], SEED + 10, calendar_lo, calendar_hi),
        "SHOCK_minus_EW": compare(
            books["EW_T_SHOCK30"], books["EW_T30"], SEED + 20, calendar_lo, calendar_hi),
        "COPY_EW_minus_COPY_TSTAT": compare(
            books["EW_T_COPY30"], books["TSTAT_COPY30"], SEED + 30,
            calendar_lo, calendar_hi),
        "EW_SMART_minus_TSTAT_SMART": compare(
            smart["EW_T30"], smart["TSTAT_COMMON30"], SEED + 40,
            calendar_lo, calendar_hi),
    }
    sensitivity_inputs = {
        "EW_HAC_minus_HAC": (capacity["EW_HAC_T30"], capacity["HAC_T30"],
                              actual["EW_HAC_T30"], actual["HAC_T30"]),
        "SHOCK_minus_EW": (capacity["EW_T_SHOCK30"], capacity["EW_T30"],
                            actual["EW_T_SHOCK30"], actual["EW_T30"]),
        "COPY_EW_minus_COPY_TSTAT": (
            capacity["EW_T_COPY30"], capacity["TSTAT_COPY30"],
            actual["EW_T_COPY30"], actual["TSTAT_COPY30"]),
        "EW_SMART_minus_TSTAT_SMART": (
            smart_capacity["EW_T30"], smart_capacity["TSTAT_COMMON30"],
            smart_actual["EW_T30"], smart_actual["TSTAT_COMMON30"]),
    }
    for j, (name, inp) in enumerate(sensitivity_inputs.items()):
        add_missingness_sensitivity(
            second[name], *inp, SEED + 2_000 + j * 10, calendar_lo, calendar_hi)
    holm_adjust(second)
    holm_adjust_null(second)
    finalize_decision_flags(
        rep["primary"], second,
        formal_eligibility=profile.experiment_id != "hl60",
    )
    rep["secondary"] = second
    tmp = output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=1))
    tmp.replace(output)
    print("PRIMARY:", rep["primary"], flush=True)
    print(f"-> {output}")
    return rep


if __name__ == "__main__":
    raise SystemExit(
        "Select a frozen profile explicitly; use `python -m "
        "research.studies.copy_cohort.dynamic_t_hl60`."
    )
