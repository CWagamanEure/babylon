"""Filtered relative trader-quality selector (architecture 2026-07-18).

Burned-fold construction run only.  Each fold builds total-fee-net, $100k daily-notional-
normalized majors PnL, rank-normalizes the active cross-section, fits the frozen pooled
homoskedastic AR(1) grid, and emits monthly top-30 rosters for KF/TSTAT/EMA/LASTZ plus the
literal published majors-native roster.

    python -m research.studies.copy_cohort.filtered_quality
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from research.lib.stats import inv_norm

from . import lake
from .alt_fresh_validate import MAJORS
from .majors_native import FROZEN as PUBLISHED_FROZEN
from .majors_native import _select_top100 as _published_top100

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "filtered_quality"
PANELS = DERIVED / "panels"
OUT = DERIVED / "rosters.json"

FOLDS = tuple(MONTHS[3:])
CAP_USD = 100_000.0
ND_MIN = 15
RECENCY_DAYS = 30
MIN_CROSS_SECTION = 200
TOP_K = 30
EMA_HALF_LIFE = 21.0

# Frozen before outcomes: deliberately small exact grid, no optimizer/model search.
PHI_GRID = (0.0, 0.25, 0.50, 0.75, 0.90, 0.97, 0.995)
LAMBDA_GRID = (0.05, 0.10, 0.20, 0.35, 0.50, 0.70, 0.90)


@dataclass(frozen=True)
class Panel:
    wallet: np.ndarray
    day: np.ndarray
    ordinal: np.ndarray
    x: np.ndarray
    legacy_x: np.ndarray
    z: np.ndarray
    eligible_wallets: np.ndarray
    start_ordinal: int
    end_ordinal: int
    skipped_days: tuple[int, ...]


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return list(MONTHS[i - 3:i])


def _month_start(month: int) -> date:
    return date(month // 100, month % 100, 1)


def _day_to_ordinal(day: int) -> int:
    s = str(int(day))
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])).toordinal()


def capacity_normalized(net_pnl: np.ndarray, notional: np.ndarray) -> np.ndarray:
    """Total-fee-net daily PnL scaled down to a $100k notional budget; never scale up."""
    p = np.asarray(net_pnl, float)
    n = np.asarray(notional, float)
    out = np.full(p.shape, np.nan)
    ok = np.isfinite(p) & np.isfinite(n) & (n > 0)
    out[ok] = p[ok] * np.minimum(1.0, CAP_USD / n[ok])
    return out


def average_rank_normal(values: np.ndarray) -> np.ndarray:
    """Ascending average-tie ranks -> inverse-normal percentiles; rank 1 is worst."""
    v = np.asarray(values, float)
    if v.size == 0 or not np.isfinite(v).all():
        raise ValueError("rank input must be non-empty and finite")
    order = np.argsort(v, kind="stable")
    ranks = np.empty(v.size, float)
    sv = v[order]
    start = 0
    while start < v.size:
        end = start + 1
        while end < v.size and sv[end] == sv[start]:
            end += 1
        ranks[order[start:end]] = 0.5 * ((start + 1) + end)
        start = end
    u = (ranks - 0.5) / v.size
    return np.array([inv_norm(float(q)) for q in u], float)


def _sha256_json(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _code_sha256(*paths: Path) -> str:
    h = hashlib.sha256()
    for path in paths:
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def source_manifest_fingerprint(con, months: list[int]) -> dict[str, object]:
    """Hash the exact upstream daily manifests used by a formation/evaluation window."""
    globs = [lake.MANIFEST.replace("date=*", f"date={lake.month_dates(m)}") for m in months]
    marks = ",".join("?" for _ in globs)
    rows = con.execute(
        f"""SELECT day, status, source_etag, source_size, schema_version, code_commit
            FROM read_json_auto([{marks}], union_by_name=true)
            ORDER BY day""",
        globs,
    ).fetchall()
    if not rows:
        raise RuntimeError(f"no source manifests found for months={months}")
    payload = [[str(v) if v is not None else None for v in row] for row in rows]
    return {"months": months, "n_manifests": len(rows), "sha256": _sha256_json(payload)}


def _panel_cache_spec(con, fold: int) -> dict[str, object]:
    months = _formation_months(fold)
    return {
        "cache_schema": "filtered-quality-panel-v2",
        "fold": fold,
        "formation_months": months,
        "source_manifest": source_manifest_fingerprint(con, months),
        "code_sha256": _code_sha256(Path(__file__)),
        "config": {
            "majors": list(MAJORS), "cap_usd": CAP_USD, "nd_min": ND_MIN,
            "recency_days": RECENCY_DAYS, "min_cross_section": MIN_CROSS_SECTION,
            "fee_formula": "sum(pnl)-sum(fee)-sum(coalesce(builder_fee,0))",
            "legacy_fee_formula": "sum(pnl)-sum(fee)",
        },
    }


def _cache_panel(con, fold: int) -> Path:
    PANELS.mkdir(parents=True, exist_ok=True)
    path = PANELS / f"daily_{fold}.parquet"
    meta = path.with_suffix(".meta.json")
    spec = _panel_cache_spec(con, fold)
    if path.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return path
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in _formation_months(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
        WITH wd AS (
          SELECT wallet, day,
                 SUM(pnl) - SUM(fee) - SUM(COALESCE(builder_fee, 0)) AS net_pnl,
                 SUM(pnl) - SUM(fee) AS legacy_net_pnl,
                 SUM(notional) AS day_notional
          FROM read_parquet([{globs}])
          WHERE coin IN ({majors})
          GROUP BY wallet, day
        )
        SELECT wallet, day,
               CAST(net_pnl AS DOUBLE) AS net_pnl,
               CAST(day_notional AS DOUBLE) AS day_notional,
               CAST(net_pnl * LEAST(1, {CAP_USD} / NULLIF(day_notional, 0)) AS DOUBLE) AS x,
               CAST(legacy_net_pnl * LEAST(1, {CAP_USD} / NULLIF(day_notional, 0))
                    AS DOUBLE) AS legacy_x
        FROM wd
        WHERE day_notional > 0
        ORDER BY wallet, day
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    tmp.replace(path)
    mtmp = meta.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mtmp.replace(meta)
    return path


def _load_panel(path: Path, fold: int) -> Panel:
    d = pq.read_table(path).to_pydict()
    wallet = np.asarray(d["wallet"], dtype=str)
    day = np.asarray(d["day"], dtype=np.int64)
    x = np.asarray(d["x"], float)
    legacy_x = np.asarray(d["legacy_x"], float)
    finite = np.isfinite(x) & np.isfinite(legacy_x)
    wallet, day, x, legacy_x = (wallet[finite], day[finite], x[finite], legacy_x[finite])
    ordinal = np.array([_day_to_ordinal(v) for v in day], np.int64)

    uw, inv = np.unique(wallet, return_inverse=True)
    count = np.bincount(inv)
    sx = np.bincount(inv, weights=x)
    sx2 = np.bincount(inv, weights=x * x)
    var = np.full(uw.size, np.nan)
    gt1 = count > 1
    var[gt1] = (sx2[gt1] - sx[gt1] ** 2 / count[gt1]) / (count[gt1] - 1)
    last = np.full(uw.size, np.iinfo(np.int64).min)
    np.maximum.at(last, inv, ordinal)
    cutoff = _month_start(fold).toordinal()
    elig = (count >= ND_MIN) & np.isfinite(var) & (var > 0) & (last >= cutoff - RECENCY_DAYS)
    keep = elig[inv]
    wallet, day, ordinal, x, legacy_x = (
        wallet[keep], day[keep], ordinal[keep], x[keep], legacy_x[keep]
    )

    z = np.full(x.size, np.nan)
    skipped: list[int] = []
    order = np.argsort(ordinal, kind="stable")
    so = ordinal[order]
    lo = 0
    while lo < order.size:
        hi = lo + 1
        while hi < order.size and so[hi] == so[lo]:
            hi += 1
        idx = order[lo:hi]
        if idx.size >= MIN_CROSS_SECTION:
            z[idx] = average_rank_normal(x[idx])
        else:
            skipped.append(int(day[idx[0]]))
        lo = hi
    good = np.isfinite(z)
    wallet, day, ordinal, x, legacy_x, z = (
        wallet[good], day[good], ordinal[good], x[good], legacy_x[good], z[good]
    )

    # All confirmatory arms use one rankable post-skip universe.  This prevents a wallet
    # with no usable observation from retaining a KF prior while TSTAT is non-finite.
    uw2, inv2 = np.unique(wallet, return_inverse=True)
    count2 = np.bincount(inv2, minlength=uw2.size)
    sx2 = np.bincount(inv2, weights=x, minlength=uw2.size)
    sxx2 = np.bincount(inv2, weights=x * x, minlength=uw2.size)
    var2 = np.full(uw2.size, np.nan)
    gt1 = count2 > 1
    var2[gt1] = (sxx2[gt1] - sx2[gt1] ** 2 / count2[gt1]) / (count2[gt1] - 1)
    last2 = np.full(uw2.size, np.iinfo(np.int64).min)
    np.maximum.at(last2, inv2, ordinal)
    rankable = ((count2 >= ND_MIN) & np.isfinite(var2) & (var2 > 0)
                & (last2 >= cutoff - RECENCY_DAYS))
    keep2 = rankable[inv2]
    wallet, day, ordinal, x, legacy_x, z = (
        wallet[keep2], day[keep2], ordinal[keep2], x[keep2], legacy_x[keep2], z[keep2]
    )
    eligible_wallets = uw2[rankable]
    if eligible_wallets.size < TOP_K:
        raise RuntimeError(f"fold {fold}: only {eligible_wallets.size} common rankable wallets")
    start = _month_start(_formation_months(fold)[0]).toordinal()
    end = _month_start(fold).toordinal() - 1
    return Panel(wallet, day, ordinal, x, legacy_x, z, eligible_wallets, start, end,
                 tuple(skipped))


def _panel_by_day(
    panel: Panel,
) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray], np.ndarray]:
    wallets = np.asarray(sorted(panel.eligible_wallets.tolist()), dtype=str)
    wi = {w: i for i, w in enumerate(wallets)}
    order = np.argsort(panel.ordinal, kind="stable")
    days, obs_idx, obs_z = [], [], []
    lo = 0
    while lo < order.size:
        hi = lo + 1
        while hi < order.size and panel.ordinal[order[hi]] == panel.ordinal[order[lo]]:
            hi += 1
        rows = order[lo:hi]
        days.append(int(panel.ordinal[rows[0]]))
        obs_idx.append(np.array([wi[w] for w in panel.wallet[rows]], np.int64))
        obs_z.append(panel.z[rows].astype(float))
        lo = hi
    return np.asarray(days, np.int64), obs_idx, obs_z, wallets


def kalman_gap(theta: np.ndarray, variance: np.ndarray, phi: float, lam: float,
               gap: int) -> tuple[np.ndarray, np.ndarray]:
    """Exact g-day stationary AR(1) prediction."""
    if gap < 0:
        raise ValueError("gap must be non-negative")
    f = phi ** gap
    q = lam * (1.0 - phi * phi)
    if gap == 0:
        qgap = 0.0
    elif abs(phi - 1.0) < 1e-12:
        qgap = q * gap
    else:
        qgap = q * (1.0 - phi ** (2 * gap)) / (1.0 - phi * phi)
    return f * theta, (f * f) * variance + qgap


def _kf_likelihood_and_state(
    panel: Panel, phi: float, lam: float,
) -> tuple[float, np.ndarray, np.ndarray]:
    days, obs_idx, obs_z, wallets = _panel_by_day(panel)
    theta = np.zeros(wallets.size)
    variance = np.full(wallets.size, lam)
    r = 1.0 - lam
    last_day = panel.start_ordinal - 1
    nll = 0.0
    nobs = 0
    for day, idx, zz in zip(days, obs_idx, obs_z, strict=True):
        theta, variance = kalman_gap(theta, variance, phi, lam, int(day - last_day))
        innov = zz - theta[idx]
        s = variance[idx] + r
        if not np.isfinite(s).all() or (s <= 0).any():
            return math.inf, theta, variance
        nll += 0.5 * float(np.sum(np.log(2 * np.pi * s) + innov * innov / s))
        nobs += idx.size
        k = variance[idx] / s
        theta[idx] += k * innov
        variance[idx] *= 1.0 - k
        last_day = int(day)
    theta, variance = kalman_gap(theta, variance, phi, lam, panel.end_ordinal - last_day)
    return nll / max(nobs, 1), theta, variance


def fit_kalman(panel: Panel) -> tuple[float, float, np.ndarray, np.ndarray, bool]:
    """Exact frozen grid; lexicographic (nll, phi, lambda) tie break."""
    best: tuple[float, float, float, np.ndarray, np.ndarray] | None = None
    for phi in PHI_GRID:
        for lam in LAMBDA_GRID:
            nll, theta, variance = _kf_likelihood_and_state(panel, phi, lam)
            cand = (nll, phi, lam, theta, variance)
            if np.isfinite(nll) and (best is None or cand[:3] < best[:3]):
                best = cand
    if best is None or panel.z.size < 1_000:
        ema, _ = ema_scores(panel)
        return math.nan, math.nan, ema, np.full(ema.size, np.nan), True
    _, phi, lam, theta, variance = best
    return phi, lam, theta, variance, False


def _score_by_wallet(panel: Panel, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    wallets = np.asarray(sorted(panel.eligible_wallets.tolist()), dtype=str)
    if values.size != wallets.size:
        raise ValueError("score length does not match eligible-wallet universe")
    return wallets, np.asarray(values, float)


def tstat_scores(panel: Panel, values: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    wallets = np.asarray(sorted(panel.eligible_wallets.tolist()), dtype=str)
    wi = {w: i for i, w in enumerate(wallets)}
    inv = np.array([wi[w] for w in panel.wallet], np.int64)
    n = np.bincount(inv)
    values = panel.x if values is None else np.asarray(values, float)
    if values.shape != panel.x.shape:
        raise ValueError("tstat values do not match panel")
    sx = np.bincount(inv, weights=values, minlength=wallets.size)
    sx2 = np.bincount(inv, weights=values * values, minlength=wallets.size)
    var = np.full(wallets.size, np.nan)
    ok = n > 1
    var[ok] = (sx2[ok] - sx[ok] ** 2 / n[ok]) / (n[ok] - 1)
    score = np.full(wallets.size, np.nan)
    good = ok & (var > 0)
    score[good] = (sx[good] / n[good]) / np.sqrt(var[good] / n[good])
    return wallets, score


def ema_scores(panel: Panel) -> tuple[np.ndarray, np.ndarray]:
    days, obs_idx, obs_z, wallets = _panel_by_day(panel)
    score = np.zeros(wallets.size)
    decay = 0.5 ** (1.0 / EMA_HALF_LIFE)
    last = panel.start_ordinal - 1
    for day, idx, zz in zip(days, obs_idx, obs_z, strict=True):
        score *= decay ** int(day - last)
        score[idx] += (1.0 - decay) * zz
        last = int(day)
    score *= decay ** (panel.end_ordinal - last)
    return wallets, score


def lastz_scores(panel: Panel) -> tuple[np.ndarray, np.ndarray]:
    wallets = np.asarray(sorted(panel.eligible_wallets.tolist()), dtype=str)
    wi = {w: i for i, w in enumerate(wallets)}
    score = np.full(wallets.size, np.nan)
    last = np.full(wallets.size, -1, np.int64)
    for w, day, z in zip(panel.wallet, panel.ordinal, panel.z, strict=True):
        i = wi[w]
        if day > last[i]:
            score[i], last[i] = z, day
    score[last < panel.end_ordinal - RECENCY_DAYS + 1] = np.nan
    return wallets, score


def topk(wallets: np.ndarray, score: np.ndarray, k: int = TOP_K) -> list[str]:
    good = np.isfinite(score)
    w, s = wallets[good], score[good]
    if w.size < k:
        raise RuntimeError(f"need exactly {k} finite scores; found {w.size}")
    order = np.lexsort((w, -s))
    out = w[order[:k]].tolist()
    if len(out) != k or len(set(out)) != k:
        raise RuntimeError(f"top-k invariant failed for k={k}")
    return out


def run() -> dict:
    DERIVED.mkdir(parents=True, exist_ok=True)
    con = lake.connect()
    published_frozen = set(json.loads(PUBLISHED_FROZEN.read_text())["distinct_wallets"])
    rep = {
        "status": "CANDIDATE-RANKING ONLY; burned folds 202511-202606",
        "architecture": "FILTERED_TRADER_QUALITY_ARCH.md",
        "config": {
            "folds": list(FOLDS), "formation_months": 3, "cap_usd": CAP_USD,
            "nd_min": ND_MIN, "recency_days": RECENCY_DAYS,
            "min_cross_section": MIN_CROSS_SECTION, "top_k": TOP_K,
            "ema_half_life_days": EMA_HALF_LIFE,
            "phi_grid": list(PHI_GRID), "lambda_grid": list(LAMBDA_GRID),
            "code_commit": lake.git_describe(),
            "code_sha256": _code_sha256(Path(__file__)),
        },
        "folds": {},
    }
    for fold in FOLDS:
        print(f"[selector] fold {fold}: cache/load daily panel", flush=True)
        panel = _load_panel(_cache_panel(con, fold), fold)
        tw, ts = tstat_scores(panel)
        ltw, lts = tstat_scores(panel, panel.legacy_x)
        ew, es = ema_scores(panel)
        lw, ls = lastz_scores(panel)
        phi, lam, ks, kp, fallback = fit_kalman(panel)
        kw, ks = _score_by_wallet(panel, ks)
        published = _published_top100(con, fold, published_frozen)[:TOP_K]
        if len(published) != TOP_K or len(set(published)) != TOP_K:
            raise RuntimeError(f"fold {fold}: published comparator does not have exactly {TOP_K}")
        rosters = {
            "KF_REL": topk(kw, ks), "TSTAT30": topk(tw, ts),
            "LEGACY_TSTAT30": topk(ltw, lts),
            "EMA30": topk(ew, es), "LASTZ30": topk(lw, ls),
            "PUBLISHED_MAJORS30": published,
        }
        overlap = {f"KF_x_{name}": len(set(rosters["KF_REL"]) & set(ws))
                   for name, ws in rosters.items() if name != "KF_REL"}
        rep["folds"][str(fold)] = {
            "n_panel_obs": int(panel.z.size),
            "n_eligible": int(panel.eligible_wallets.size),
            "skipped_days": list(panel.skipped_days),
            "phi": None if not np.isfinite(phi) else float(phi),
            "lambda": None if not np.isfinite(lam) else float(lam),
            "fallback_ema": bool(fallback),
            "rosters": rosters,
            "overlap": overlap,
            "kf_posterior_sd_median": (None if fallback else float(np.median(np.sqrt(kp)))),
        }
        print(f"  elig={panel.eligible_wallets.size:,} obs={panel.z.size:,} "
              f"phi={phi} lambda={lam} fallback={fallback} overlap={overlap}", flush=True)
    con.close()
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=1))
    tmp.replace(OUT)
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
