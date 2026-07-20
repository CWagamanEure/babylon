"""Burned-fold book comparison for the filtered trader-quality selector.

Consumes ``filtered_quality/rosters.json``.  Pulls the union roster's block-collapsed majors
flat opens, prices 8h markouts, applies identical $2.5k/concurrency/coin-cap mechanics, and
reports KF-REL versus same-input TSTAT30.  Historical output is candidate-ranking only.

    python -m research.studies.copy_cohort.filtered_quality_book
"""
from __future__ import annotations

import calendar
import hashlib
import heapq
import json
import math
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from research.lib.stats import inv_norm

from . import lake
from .alt_fresh_validate import MAJORS, STALE_MS, _ctx_parts
from .filtered_quality import (
    DERIVED,
    FOLDS,
    _code_sha256,
    _sha256_json,
    source_manifest_fingerprint,
)
from .filtered_quality import OUT as ROSTERS_PATH

ENTRIES = DERIVED / "entries"
OUT = DERIVED / "book_report.json"
UNIT_USD = 2_500.0
COIN_CAP_USD = 50_000.0
NOTL_MIN = 250.0
HOLD_MS = 8 * 3_600_000
COST_BP = 5.5
N_BOOT = 10_000
BLOCK_DAYS = 7
SEED = 20260718
TOP_HALF = 15
DAY_MS = 86_400_000


def collapse_candidates(wallet: np.ndarray, coin: np.ndarray, ts: np.ndarray, direction: np.ndarray,
                        notional: np.ndarray) -> dict[str, np.ndarray]:
    """Block-collapse `(wallet,coin,ts,dir)` and drop conflicting-direction timestamp keys."""
    rows: dict[tuple[str, str, int, int], float] = {}
    dirs: dict[tuple[str, str, int], set[int]] = {}
    for w, c, t, d, n in zip(wallet, coin, ts, direction, notional, strict=True):
        base = (str(w), str(c), int(t))
        dirs.setdefault(base, set()).add(int(d))
        key = (*base, int(d))
        rows[key] = rows.get(key, 0.0) + float(n)
    keep = [(key, n) for key, n in rows.items() if len(dirs[key[:3]]) == 1]
    keep.sort(key=lambda z: (z[0][2], z[0][0], z[0][1], z[0][3]))
    return {
        "wallet": np.array([k[0] for k, _ in keep], dtype=str),
        "coin": np.array([k[1] for k, _ in keep], dtype=str),
        "ts": np.array([k[2] for k, _ in keep], np.int64),
        "dir": np.array([k[3] for k, _ in keep], np.int64),
        "notl": np.array([n for _, n in keep], float),
    }


def _cache_fold(con, fold: int, wallets: list[str]) -> tuple[Path, Path]:
    ENTRIES.mkdir(parents=True, exist_ok=True)
    ep = ENTRIES / f"entries_{fold}.parquet"
    sp = ENTRIES / f"signals_{fold}.parquet"
    meta = ENTRIES / f"cache_{fold}.meta.json"
    ctx = _ctx_parts(fold)
    if not ctx:
        raise RuntimeError(f"fold {fold}: no local asset_ctx parts")
    ctx_files = [{"path": str(p), "size": Path(p).stat().st_size,
                  "mtime_ns": Path(p).stat().st_mtime_ns} for p in ctx]
    eval_days = sorted(int(Path(p).parent.name.removeprefix("day=")) for p in ctx
                       if f"month={fold}" in str(p))
    if not eval_days:
        raise RuntimeError(f"fold {fold}: no evaluation-month context")
    expected_prefix = list(range(fold * 100 + 1, max(eval_days) + 1))
    if eval_days != expected_prefix:
        raise RuntimeError(f"fold {fold}: internal asset_ctx day gap: {eval_days}")
    ctx_list = ",".join(f"'{p}'" for p in ctx)
    ctx_max_ts = int(con.execute(
        f"SELECT MAX(ts) FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL"
    ).fetchone()[0])
    entry_cutoff_ts = ctx_max_ts - HOLD_MS
    full_days = calendar.monthrange(fold // 100, fold % 100)[1]
    spec = {
        "cache_schema": "filtered-quality-book-v3",
        "fold": fold,
        "roster_sha256": _sha256_json(sorted(wallets)),
        "n_union_wallets": len(set(wallets)),
        "source_manifest": source_manifest_fingerprint(con, [fold]),
        "ctx_files_sha256": _sha256_json(ctx_files),
        "ctx_files": ctx_files,
        "evaluation_ctx_days": eval_days,
        "evaluation_month_complete": len(eval_days) == full_days,
        "entry_cutoff_ts": entry_cutoff_ts,
        "cutoff_rule": "entry_ts <= max_available_ctx_ts - hold_ms (common to all arms)",
        "code_sha256": _code_sha256(
            Path(__file__), Path(__file__).with_name("filtered_quality.py"),
            Path(__file__).with_name("alt_fresh_validate.py")
        ),
        "config": {"majors": list(MAJORS), "notional_min": NOTL_MIN,
                   "hold_ms": HOLD_MS, "stale_ms": STALE_MS},
    }
    if ep.exists() and sp.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return ep, sp
    con.execute("CREATE OR REPLACE TEMP TABLE fq_wallets AS SELECT UNNEST(?) AS wallet",
                [sorted(wallets)])
    majors = ",".join(f"'{c}'" for c in MAJORS)
    raw = f"""
      SELECT o.wallet, o.coin, o.ts, o.dir_sign,
             SUM(CAST(o.notl AS DOUBLE)) AS notl
      FROM read_parquet('{lake.ope_month_glob(fold)}') o
      JOIN fq_wallets USING (wallet)
      WHERE o.coin IN ({majors}) AND o.ts <= {entry_cutoff_ts}
      GROUP BY o.wallet, o.coin, o.ts, o.dir_sign
    """
    amb = """SELECT wallet, coin, ts FROM blk GROUP BY wallet, coin, ts
             HAVING COUNT(DISTINCT dir_sign) > 1"""
    stmp = sp.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH blk AS ({raw}), amb AS ({amb})
      SELECT b.wallet, b.coin, b.ts, b.dir_sign, b.notl,
             (a.wallet IS NOT NULL) AS is_ambiguous
      FROM blk b LEFT JOIN amb a USING(wallet, coin, ts)
      ORDER BY b.ts, b.wallet, b.coin, b.dir_sign
    ) TO '{stmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    stmp.replace(sp)

    etmp = ep.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH blk AS ({raw}), amb AS ({amb}),
      ent AS (
        SELECT b.* FROM blk b ANTI JOIN amb a USING(wallet, coin, ts)
        WHERE b.notl >= {NOTL_MIN}
      ),
      ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL),
      p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS px0_ts
             FROM ent e ASOF LEFT JOIN ctx c ON e.coin=c.coin AND e.ts>=c.ts),
      p8 AS (SELECT p0.*, c.mid_px AS px8, c.ts AS px8_ts
             FROM p0 ASOF LEFT JOIN ctx c ON p0.coin=c.coin AND (p0.ts+{HOLD_MS})>=c.ts)
      SELECT wallet, coin, ts, dir_sign, notl,
             CASE WHEN px0 IS NOT NULL AND px8 IS NOT NULL AND px0 > 0
                        AND (ts-px0_ts) <= {STALE_MS}
                        AND ((ts+{HOLD_MS})-px8_ts) <= {STALE_MS}
                  THEN dir_sign * (px8-px0)/px0*1e4 END AS gross_bp
      FROM p8 ORDER BY ts, wallet, coin, dir_sign
    ) TO '{etmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    etmp.replace(ep)
    mtmp = meta.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mtmp.replace(meta)
    return ep, sp


def _read(path: Path) -> dict[str, np.ndarray]:
    d = pq.read_table(path).to_pydict()
    out = {k: np.asarray(v) for k, v in d.items()}
    for k in ("wallet", "coin"):
        if k in out:
            out[k] = out[k].astype(str)
    for k in ("ts", "dir_sign"):
        if k in out:
            out[k] = out[k].astype(np.int64)
    for k in ("notl", "gross_bp"):
        if k in out:
            out[k] = np.asarray(out[k], float)
    if "is_ambiguous" in out:
        out["is_ambiguous"] = out["is_ambiguous"].astype(bool)
    return out


def accept_book(ent: dict[str, np.ndarray], *, return_funnel: bool = False):
    """Deterministic priceable-first acceptance, one wallet-coin/8h and $50k per coin."""
    order = np.lexsort((ent["dir"], ent["coin"], ent["wallet"], ent["ts"]))
    open_until: dict[tuple[str, str], int] = {}
    coin_heap: dict[str, list[int]] = {}
    keep: list[int] = []
    concurrency_skips = 0
    cap_skips = 0
    for i in order:
        w, c, t = str(ent["wallet"][i]), str(ent["coin"][i]), int(ent["ts"][i])
        if open_until.get((w, c), -1) > t:
            concurrency_skips += 1
            continue
        h = coin_heap.setdefault(c, [])
        while h and h[0] <= t:
            heapq.heappop(h)
        if (len(h) + 1) * UNIT_USD > COIN_CAP_USD:
            cap_skips += 1
            continue
        ex = t + HOLD_MS
        open_until[(w, c)] = ex
        heapq.heappush(h, ex)
        keep.append(int(i))
    out = np.asarray(keep, np.int64)
    if return_funnel:
        return out, {"n_concurrency_skips": concurrency_skips, "n_coin_cap_skips": cap_skips}
    return out


def consensus_other_counts(entries: dict[str, np.ndarray], signals: dict[str, np.ndarray],
                           top_half: set[str]) -> np.ndarray:
    """Distinct other top-half wallets with same coin+dir signal in `[t-6h,t)`."""
    out = np.zeros(entries["ts"].size, np.int64)
    ekey = np.char.add(np.char.add(entries["coin"], "|"), entries["dir"].astype(str))
    skey = np.char.add(np.char.add(signals["coin"], "|"), signals["dir"].astype(str))
    win = 6 * 3_600_000
    for key in np.unique(ekey):
        ei = np.flatnonzero(ekey == key)
        si = np.flatnonzero(skey == key)
        eo = ei[np.argsort(entries["ts"][ei], kind="stable")]
        so = si[np.argsort(signals["ts"][si], kind="stable")]
        last: dict[str, int] = {}
        j = 0
        for idx in eo:
            t, w = int(entries["ts"][idx]), str(entries["wallet"][idx])
            while j < so.size and int(signals["ts"][so[j]]) < t:
                sw = str(signals["wallet"][so[j]])
                last[sw] = int(signals["ts"][so[j]])
                j += 1
            out[idx] = sum(1 for sw, lt in last.items()
                           if sw != w and sw in top_half and lt >= t - win)
    return out


def _arm_fold(entries: dict[str, np.ndarray], signals: dict[str, np.ndarray], roster: list[str],
              fold: int) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    rset = set(roster)
    m = np.array([w in rset for w in entries["wallet"]]) & np.isfinite(entries["gross_bp"])
    e = {
        "wallet": entries["wallet"][m], "coin": entries["coin"][m],
        "ts": entries["ts"][m], "dir": entries["dir_sign"][m],
        "gross_bp": entries["gross_bp"][m],
    }
    sr = np.array([w in rset for w in signals["wallet"]])
    ambiguous = (signals["is_ambiguous"] if "is_ambiguous" in signals
                 else np.zeros(sr.size, bool))
    s = sr & ~ambiguous
    sig = {"wallet": signals["wallet"][s], "coin": signals["coin"][s],
           "ts": signals["ts"][s], "dir": signals["dir_sign"][s]}
    acc, skips = accept_book(e, return_funnel=True)
    top = set(roster[:TOP_HALF])
    cons = consensus_other_counts(e, sig, top)
    ung = np.zeros(e["ts"].size, bool)
    ung[acc] = True
    smart = ung & (cons >= 1)
    out = {k: e[k][ung] for k in e}
    out["net_bp"] = out.pop("gross_bp") - COST_BP
    out["fold"] = np.full(out["ts"].size, fold, np.int64)
    out["smart"] = smart[ung]
    return out, {
        "n_collapsed_pre_ambiguity": int(sr.sum()),
        "n_ambiguous_direction_rows_dropped": int(np.sum(sr & ambiguous)),
        "n_collapsed_signals": int(s.sum()),
        "n_below_notional_min": int(np.sum(s & (signals["notl"] < NOTL_MIN))),
        "n_threshold_candidates": int(np.sum(s & (signals["notl"] >= NOTL_MIN))),
        "n_priceable_candidates": int(e["ts"].size),
        "n_unpriceable": int(np.sum(np.array([w in rset for w in entries["wallet"]])
                                    & ~np.isfinite(entries["gross_bp"]))),
        **skips, "n_accepted": int(acc.size), "n_smart": int(smart.sum()),
    }


def _concat(parts: list[dict[str, np.ndarray]], smart: bool = False) -> dict[str, np.ndarray]:
    keys = ("wallet", "coin", "ts", "dir", "net_bp", "fold", "smart")
    out = {k: np.concatenate([p[k] for p in parts]) for k in keys}
    if smart:
        m = out["smart"]
        out = {k: v[m] for k, v in out.items()}
    return out


def _point(book: dict[str, np.ndarray]) -> float:
    return float(np.mean(book["net_bp"])) if book["net_bp"].size else math.nan


def wallet_boot_delta(a: dict[str, np.ndarray], b: dict[str, np.ndarray], rng,
                      n_boot: int = N_BOOT) -> np.ndarray:
    wallets = np.unique(np.concatenate([a["wallet"], b["wallet"]]))
    ai = {w: np.flatnonzero(a["wallet"] == w) for w in wallets}
    bi = {w: np.flatnonzero(b["wallet"] == w) for w in wallets}
    asum = np.array([a["net_bp"][ai[w]].sum() for w in wallets])
    acnt = np.array([ai[w].size for w in wallets], float)
    bsum = np.array([b["net_bp"][bi[w]].sum() for w in wallets])
    bcnt = np.array([bi[w].size for w in wallets], float)
    out = np.full(n_boot, np.nan)
    for j in range(n_boot):
        mult = np.bincount(rng.integers(0, wallets.size, wallets.size), minlength=wallets.size)
        na, nb = mult @ acnt, mult @ bcnt
        if na > 0 and nb > 0:
            out[j] = (mult @ asum) / na - (mult @ bsum) / nb
    return out[np.isfinite(out)]


def time_boot_delta(a: dict[str, np.ndarray], b: dict[str, np.ndarray], rng,
                    n_boot: int = N_BOOT, block: int = BLOCK_DAYS) -> np.ndarray:
    lo = min(int(a["ts"].min()), int(b["ts"].min())) // DAY_MS
    hi = max(int(a["ts"].max()), int(b["ts"].max())) // DAY_MS
    n = hi - lo + 1
    asum, acnt, bsum, bcnt = (np.zeros(n) for _ in range(4))
    ad = a["ts"] // DAY_MS - lo
    bd = b["ts"] // DAY_MS - lo
    np.add.at(asum, ad, a["net_bp"])
    np.add.at(acnt, ad, 1)
    np.add.at(bsum, bd, b["net_bp"])
    np.add.at(bcnt, bd, 1)
    block = max(1, min(block, n))
    nb = int(np.ceil(n / block))
    out = np.full(n_boot, np.nan)
    for j in range(n_boot):
        starts = rng.integers(0, n - block + 1, nb)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        na, nn = acnt[idx].sum(), bcnt[idx].sum()
        if na > 0 and nn > 0:
            out[j] = asum[idx].sum() / na - bsum[idx].sum() / nn
    return out[np.isfinite(out)]


def _component_ci(x: np.ndarray) -> list[float]:
    return [float(np.quantile(x, .025)), float(np.quantile(x, .975))]


def compare(a: dict[str, np.ndarray], b: dict[str, np.ndarray], seed: int) -> dict:
    delta = _point(a) - _point(b)
    wb = wallet_boot_delta(a, b, np.random.default_rng(seed))
    tb = time_boot_delta(a, b, np.random.default_rng(seed + 1))
    wci, tci = _component_ci(wb), _component_ci(tb)
    bind = [min(wci[0], tci[0]), max(wci[1], tci[1])]
    se = max(float(np.std(wb, ddof=1)), float(np.std(tb, ddof=1)))
    mde_diag = (inv_norm(.975) + inv_norm(.80)) * se
    wp = min(1.0, 2 * min((np.sum(wb <= 0) + 1) / (wb.size + 1),
                          (np.sum(wb >= 0) + 1) / (wb.size + 1)))
    tp = min(1.0, 2 * min((np.sum(tb <= 0) + 1) / (tb.size + 1),
                          (np.sum(tb >= 0) + 1) / (tb.size + 1)))
    per_fold = {}
    for fold in FOLDS:
        am, bm = a["fold"] == fold, b["fold"] == fold
        per_fold[str(fold)] = (float(a["net_bp"][am].mean() - b["net_bp"][bm].mean())
                               if am.any() and bm.any() else None)
    per_coin = {}
    for coin in MAJORS:
        am, bm = a["coin"] == coin, b["coin"] == coin
        per_coin[coin] = (float(a["net_bp"][am].mean() - b["net_bp"][bm].mean())
                          if am.any() and bm.any() else None)
    return {
        "delta_bp": delta, "wallet_ci95": wci, "timeblock_ci95": tci,
        "binding_ci95": bind,
        "descriptive_two_sided_p_wallet": wp,
        "descriptive_two_sided_p_timeblock": tp,
        "normal_mde80_diag_bp": float(mde_diag),
        "empirical_mde_status": "NOT RUN; burned candidate ranking cannot support a null verdict",
        "per_fold_delta_bp": per_fold,
        "folds_positive": int(sum(v is not None and v > 0 for v in per_fold.values())),
        "per_coin_delta_bp": per_coin,
        "coins_positive": int(sum(v is not None and v > 0 for v in per_coin.values())),
        "n_boot": N_BOOT, "block_days": BLOCK_DAYS,
    }


def _book_stats(book: dict[str, np.ndarray]) -> dict:
    bp = book["net_bp"]
    wallet_means = {w: float(bp[book["wallet"] == w].mean()) for w in np.unique(book["wallet"])}
    per_fold = {str(f): (float(bp[book["fold"] == f].mean())
                         if np.any(book["fold"] == f) else None) for f in FOLDS}
    per_coin = {c: (float(bp[book["coin"] == c].mean())
                    if np.any(book["coin"] == c) else None) for c in MAJORS}
    total_usd = float(bp.sum() * 1e-4 * UNIT_USD)
    ranked = sorted(wallet_means.items(), key=lambda z: z[1], reverse=True)
    wallet_usd = {w: float(bp[book["wallet"] == w].sum() * 1e-4 * UNIT_USD)
                  for w in np.unique(book["wallet"])}
    fold_usd = {int(f): float(bp[book["fold"] == f].sum() * 1e-4 * UNIT_USD) for f in FOLDS}
    best_wallet = max(wallet_usd, key=wallet_usd.get)
    best_fold = max(fold_usd, key=fold_usd.get)
    no_wallet = book["wallet"] != best_wallet
    no_fold = book["fold"] != best_fold
    no_hype = book["coin"] != "HYPE"
    return {
        "n_entries": int(bp.size), "n_wallets": int(len(wallet_means)),
        "net_bp_per_entry": float(bp.mean()), "net_usd": total_usd,
        "hit_rate": float((bp > 0).mean()), "median_bp": float(np.median(bp)),
        "p90_bp": float(np.quantile(bp, .90)), "p99_bp": float(np.quantile(bp, .99)),
        "per_fold_bp": per_fold,
        "folds_positive": int(sum(v is not None and v > 0 for v in per_fold.values())),
        "per_coin_bp": per_coin,
        "top5_wallet_mean_bp": ranked[:5],
        "top5_wallet_pnl_share": (
            float(sum(sorted(wallet_usd.values(), reverse=True)[:5]) / total_usd)
            if total_usd != 0 else None
        ),
        "drop_best_wallet": {
            "wallet": best_wallet, "net_bp_per_entry": float(bp[no_wallet].mean())
        },
        "drop_best_fold": {"fold": best_fold, "net_bp_per_entry": float(bp[no_fold].mean())},
        "exclude_HYPE_net_bp_per_entry": float(bp[no_hype].mean()) if no_hype.any() else None,
    }


def run() -> dict:
    rosters = json.loads(ROSTERS_PATH.read_text())
    con = lake.connect()
    arms = ("KF_REL", "TSTAT30", "LEGACY_TSTAT30", "EMA30", "LASTZ30",
            "PUBLISHED_MAJORS30")
    parts = {a: [] for a in arms}
    funnels = {a: {} for a in arms}
    cache_spec_sha256 = {}
    for fold in FOLDS:
        fr = rosters["folds"][str(fold)]["rosters"]
        union = sorted({w for a in arms for w in fr[a]})
        print(f"[book] fold {fold}: pull/cache {len(union)} union wallets", flush=True)
        ep, sp = _cache_fold(con, fold, union)
        cache_spec_sha256[str(fold)] = _sha256_json(json.loads(
            (ENTRIES / f"cache_{fold}.meta.json").read_text()
        ))
        ent, sig = _read(ep), _read(sp)
        for arm in arms:
            p, funnel = _arm_fold(ent, sig, fr[arm], fold)
            parts[arm].append(p)
            funnels[arm][str(fold)] = funnel
            print(f"  {arm}: {funnel}", flush=True)
    con.close()

    books = {a: _concat(parts[a]) for a in arms}
    smart = {a: _concat(parts[a], smart=True) for a in arms}
    rep = {
        "status": "CANDIDATE-RANKING ONLY; burned folds 202511-202606; no OOS claim",
        "verdict_eligible": False,
        "config": {"unit_usd": UNIT_USD, "coin_cap_usd": COIN_CAP_USD,
                   "notional_min": NOTL_MIN, "hold_h": 8, "cost_bp": COST_BP,
                   "n_boot": N_BOOT, "block_days": BLOCK_DAYS, "seed": SEED,
                   "code_commit": lake.git_describe(),
                   "code_sha256": _code_sha256(
                       Path(__file__), Path(__file__).with_name("filtered_quality.py"),
                       Path(__file__).with_name("alt_fresh_validate.py")
                   ),
                   "rosters_sha256": hashlib.sha256(ROSTERS_PATH.read_bytes()).hexdigest(),
                   "fold_cache_spec_sha256": cache_spec_sha256},
        "funnels": funnels, "books": {}, "primary": {}, "secondary": {},
    }
    for arm in arms:
        rep["books"][arm] = _book_stats(books[arm])
        rep["books"][arm + "_SMART"] = _book_stats(smart[arm])
        print(f"{arm}: n={books[arm]['net_bp'].size:,} net={_point(books[arm]):+.2f}bp; "
              f"smart n={smart[arm]['net_bp'].size:,} net={_point(smart[arm]):+.2f}bp", flush=True)
    rep["primary"] = compare(books["KF_REL"], books["TSTAT30"], SEED)
    rep["secondary"]["KF_minus_EMA"] = compare(books["KF_REL"], books["EMA30"], SEED + 10)
    rep["secondary"]["KF_minus_LASTZ"] = compare(books["KF_REL"], books["LASTZ30"], SEED + 20)
    rep["secondary"]["KF_minus_PUBLISHED"] = compare(
        books["KF_REL"], books["PUBLISHED_MAJORS30"], SEED + 30)
    rep["secondary"]["KF_SMART_minus_TSTAT_SMART"] = compare(
        smart["KF_REL"], smart["TSTAT30"], SEED + 40)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=1))
    tmp.replace(OUT)
    print("PRIMARY KF-TSTAT:", rep["primary"], flush=True)
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
