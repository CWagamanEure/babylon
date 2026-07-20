"""Powered burned-fold ablation of adaptive R, slow Q, and blowup handling.

Implements ``ADAPTIVE_RQ_FILTER_ARCH.md``.  The load-bearing outcome is an
end-of-day, coin-neutral measurement factor; it is intentionally not a trading
return.  Historical outputs are diagnostics and can never be promoted.
"""

from __future__ import annotations

import calendar
import gc
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT

from . import lake
from .alt_fresh_validate import MAJORS
from .dynamic_t_quality import (
    FOLDS,
    N_EFF_MIN,
    ND_MIN,
    RECENCY_DAYS,
    day_to_ordinal,
    ew_t,
    formation_months,
    month_start,
    normalized_x,
    ordinary_t,
)
from .filtered_quality import _code_sha256, _sha256_json

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "adaptive_rq_filter"
PANELS = DERIVED / "panels"
SCORES = DERIVED / "scores"
CONTRIB = DERIVED / "contributions"
OUT = DERIVED / "factor_report.json"
ARCH = Path(__file__).with_name("ADAPTIVE_RQ_FILTER_ARCH.md")
PROFILE_ID = "adaptive_rq_powered_v1"

ARMS = (
    "KF60_BASE",
    "KF60_R_BREADTH",
    "KF60_R_VOL",
    "KF60_Q_SLOW",
    "KF60_BLOWUP",
    "KF60_ALL",
    "EW60",
    "TSTAT_COMMON",
)
SHOCK_ARMS = {"KF60_BLOWUP", "KF60_ALL"}
PRIMARY = "KF60_ALL__minus__EW60"
SECONDARIES = {
    "R_BREADTH__minus__BASE": ("KF60_R_BREADTH", "KF60_BASE"),
    "R_VOL__minus__BASE": ("KF60_R_VOL", "KF60_BASE"),
    "Q_SLOW__minus__BASE": ("KF60_Q_SLOW", "KF60_BASE"),
    "BLOWUP__minus__BASE": ("KF60_BLOWUP", "KF60_BASE"),
    "ALL__minus__BASE": ("KF60_ALL", "KF60_BASE"),
    "BASE__minus__EW60": ("KF60_BASE", "EW60"),
    "ALL__minus__TSTAT_COMMON": ("KF60_ALL", "TSTAT_COMMON"),
}
CONTRASTS = {PRIMARY: ("KF60_ALL", "EW60"), **SECONDARIES}

HALF_LIFE = 60.0
CAP_USD = Decimal("100000")
BLOWUP_USD = -10_000.0
QUARANTINE_DAYS = 30
MIN_ACTIVE_BASE = 200
MIN_FORMATION_POOL = 30
MIN_ARM_COIN = 30
MIN_FOLD_COVERAGE = 0.90
N_BOOT = 10_000
BLOCK_DAYS = 7
SEED = 20260718
MIN_INFER_WALLETS = 10
MIN_INFER_BLOCKS = 10
MAX_INVALID_BOOT_FRAC = 0.01
CARE_BP = 5.0
K60 = 1.0 - 2.0 ** (-1.0 / HALF_LIFE)
Q60 = K60 * K60 / (1.0 - K60)
QSLOW = Q60 / 4.0
KSLOW = (-QSLOW + math.sqrt(QSLOW * QSLOW + 4.0 * QSLOW)) / 2.0
DAY_MS = 86_400_000


@dataclass(frozen=True)
class DailyPanel:
    wallet: np.ndarray
    day: np.ndarray
    ordinal: np.ndarray
    x: np.ndarray
    hhi: np.ndarray
    n_liq: np.ndarray
    n_open_flat: np.ndarray
    r_vol: np.ndarray
    start_ordinal: int
    end_ordinal: int


@dataclass(frozen=True)
class FoldScores:
    wallets: np.ndarray
    score: dict[str, np.ndarray]
    raw_v: dict[str, np.ndarray]
    eligible: dict[str, np.ndarray]
    final30_shock: np.ndarray
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class ContrastRows:
    wallet: np.ndarray
    coin: np.ndarray
    day: np.ndarray
    fold: np.ndarray
    z: np.ndarray
    d2: np.ndarray
    lattice_day: np.ndarray
    lattice_fold: np.ndarray
    universe_wallet: np.ndarray


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _context_records(paths: list[Path]) -> list[dict[str, object]]:
    return [{"path": str(p), "size": p.stat().st_size, "sha256": _file_sha256(p)} for p in paths]


def _expected_days(months: list[int]) -> list[int]:
    return [int(v.replace("-", "")) for v in lake.expected_iso_days(months)]


def exact_context_paths(months: list[int]) -> list[Path]:
    """Return exactly one local context part for each requested calendar day."""
    paths: list[Path] = []
    for month in months:
        paths.extend(
            sorted(
                (REPO_ROOT / "data" / "raw" / "asset_ctx" / f"month={month}").glob(
                    "day=*/ctx.parquet"
                )
            )
        )
    got = [int(p.parent.name.removeprefix("day=")) for p in paths]
    expected = _expected_days(months)
    if got != expected or len(got) != len(set(got)):
        raise RuntimeError(
            f"asset_ctx exact-date coverage failed months={months}: "
            f"missing={sorted(set(expected) - set(got))[:8]} "
            f"extra={sorted(set(got) - set(expected))[:8]}"
        )
    return paths


def _day_start_ms(day: int) -> int:
    s = str(day)
    dt = datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def context_rv_catalog(paths: list[Path]) -> tuple[dict[int, float], dict[int, str]]:
    """Compute exact 5-minute major RV and fail on any duplicate coin/timestamp."""
    rv: dict[int, float] = {}
    invalid: dict[int, str] = {}
    for path in paths:
        day = int(path.parent.name.removeprefix("day="))
        tab = pq.read_table(path, columns=["coin", "ts", "mid_px"])
        coin_all = np.asarray(tab["coin"].to_numpy(zero_copy_only=False), str)
        ts_all = np.asarray(tab["ts"].to_numpy(zero_copy_only=False), np.int64)
        day_start = _day_start_ms(day)
        if np.any((ts_all < day_start) | (ts_all >= day_start + DAY_MS)):
            raise RuntimeError(f"out-of-day context timestamp in {path}")
        order = np.lexsort((ts_all, coin_all))
        if order.size > 1:
            co, to = coin_all[order], ts_all[order]
            if np.any((co[1:] == co[:-1]) & (to[1:] == to[:-1])):
                raise RuntimeError(f"duplicate (coin,ts) in {path}")
        px_all = np.asarray(tab["mid_px"].to_numpy(zero_copy_only=False), float)
        targets = day_start + np.arange(288, dtype=np.int64) * 300_000
        coin_rv: list[float] = []
        reason: str | None = None
        for coin in MAJORS:
            m = (coin_all == coin) & np.isfinite(px_all) & (px_all > 0)
            ts, px = ts_all[m], px_all[m]
            so = np.argsort(ts, kind="stable")
            ts, px = ts[so], px[so]
            idx = np.searchsorted(ts, targets, side="left")
            if idx.size != 288 or np.any(idx >= ts.size):
                reason = f"{coin}:missing_target"
                break
            chosen_ts, chosen_px = ts[idx], px[idx]
            if np.any(chosen_ts > targets + 90_000):
                reason = f"{coin}:target_stale"
                break
            ret = np.diff(np.log(chosen_px))
            value = float(math.sqrt(float(ret @ ret)))
            if (
                ret.size != 287
                or not np.isfinite(ret).all()
                or not np.isfinite(value)
                or value <= 0
            ):
                reason = f"{coin}:invalid_rv"
                break
            coin_rv.append(value)
        if reason is not None or len(coin_rv) != len(MAJORS):
            invalid[day] = reason or "incomplete_majors"
            continue
        value = float(math.sqrt(float(np.mean(np.square(coin_rv)))))
        if not np.isfinite(value) or value <= 0:
            invalid[day] = "invalid_market_rv"
        else:
            rv[day] = value
    return rv, invalid


def fold_r_vol(months: list[int], rv: dict[int, float]) -> dict[int, float]:
    """Squared current/prior-20 valid-RV ratio, reset at formation start."""
    prior: list[float] = []
    out: dict[int, float] = {}
    for day in _expected_days(months):
        if day not in rv:
            continue
        ratio = 1.0
        if len(prior) >= 5:
            ratio = float(np.clip(rv[day] / np.median(prior[-20:]), 0.5, 4.0))
        out[day] = ratio * ratio
        prior.append(rv[day])
    return out


def cache_identity_payload(profile_id: str) -> dict[str, str]:
    """Identity fields shared by every adaptive-R/Q cache and report."""
    return {
        "profile_id": profile_id,
        "architecture_sha256": _file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
    }


def _panel_spec(
    con, fold: int, context_records: list[dict[str, object]], invalid_days: dict[int, str]
) -> dict[str, object]:
    months = formation_months(fold)
    expected = set(_expected_days(months))
    keep = [
        r
        for r in context_records
        if int(Path(str(r["path"])).parent.name.removeprefix("day=")) in expected
    ]
    return {
        "cache_schema": "adaptive-rq-formation-v3-exact-wallet-day",
        **cache_identity_payload(PROFILE_ID),
        "fold": fold,
        "formation_months": months,
        "source_lineage": lake.validated_lineage(con, months, ("alt_universe_wallet_coin_day",)),
        "context_files": keep,
        "context_files_sha256": _sha256_json(keep),
        "invalid_context_days": {
            str(d): invalid_days[d] for d in _expected_days(months) if d in invalid_days
        },
        "config": {
            "majors": list(MAJORS),
            "cap_usd": str(CAP_USD),
            "fee_formula": "sum(pnl)-sum(fee)-sum(coalesce(builder_fee,0))",
            "money_type": "DECIMAL(38,12)",
        },
    }


def cache_formation_panel(
    con, fold: int, context_records: list[dict[str, object]], invalid_days: dict[int, str]
) -> Path:
    PANELS.mkdir(parents=True, exist_ok=True)
    path = PANELS / f"formation_wc_{fold}.parquet"
    meta = path.with_suffix(".meta.json")
    spec = _panel_spec(con, fold, context_records, invalid_days)
    if path.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return path
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in formation_months(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH wc AS (
        SELECT lower(wallet) AS wallet,coin,day,
          SUM(CAST(pnl AS DECIMAL(38,12)))
            - SUM(CAST(fee AS DECIMAL(38,12)))
            - SUM(COALESCE(CAST(builder_fee AS DECIMAL(38,12)),0)) AS net_pnl,
          SUM(CAST(notional AS DECIMAL(38,12))) AS coin_notional,
          SUM(n_liq)::BIGINT AS n_liq,
          SUM(n_open_flat)::BIGINT AS n_open_flat
        FROM read_parquet([{globs}]) WHERE coin IN ({majors})
        GROUP BY lower(wallet),coin,day HAVING coin_notional>0
      ), wd AS (
        SELECT wallet,day,SUM(net_pnl) AS net_pnl,
          SUM(coin_notional) AS day_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='BTC'),0) AS btc_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='ETH'),0) AS eth_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='SOL'),0) AS sol_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='HYPE'),0) AS hype_notional,
          SUM(n_liq)::BIGINT AS n_liq,
          SUM(n_open_flat)::BIGINT AS n_open_flat
        FROM wc GROUP BY wallet,day HAVING day_notional>0
      )
      SELECT wallet,day,net_pnl,day_notional,
        btc_notional,eth_notional,sol_notional,hype_notional,n_liq,n_open_flat
      FROM wd ORDER BY wallet,day
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post = lake.validated_lineage(con, formation_months(fold), ("alt_universe_wallet_coin_day",))
    if post["sha256"] != spec["source_lineage"]["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: formation WCD mutated")
    tmp.replace(path)
    mtmp = meta.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mtmp.replace(meta)
    return path


def load_daily_panel(path: Path, fold: int, r_vol: dict[int, float]) -> DailyPanel:
    d = pq.read_table(path).to_pydict()
    wallet_all = np.asarray(d["wallet"], str)
    day_all = np.asarray(d["day"], np.int64)
    start = month_start(formation_months(fold)[0]).toordinal()
    end = month_start(fold).toordinal() - 1
    context_index = np.flatnonzero(np.array([int(v) in r_vol for v in day_all], bool))
    wallet_ctx, day_ctx = wallet_all[context_index], day_all[context_index]
    unique_wallet, inverse, counts = np.unique(wallet_ctx, return_inverse=True, return_counts=True)
    max_day = np.zeros(unique_wallet.size, np.int64)
    np.maximum.at(max_day, inverse, day_ctx)
    possible_wallet = (counts >= ND_MIN) & (
        np.asarray([day_to_ordinal(v) for v in max_day], np.int64) >= end - RECENCY_DAYS + 1
    )
    selected = context_index[possible_wallet[inverse]]
    wallet, day = wallet_all[selected], day_all[selected]
    net_pnl = [d["net_pnl"][j] for j in selected]
    day_notional = [d["day_notional"][j] for j in selected]
    x = np.asarray(
        [normalized_x(Decimal(p), Decimal(n)) for p, n in zip(net_pnl, day_notional, strict=True)],
        float,
    )
    coin_notional = [[d[f"{coin.lower()}_notional"][j] for j in selected] for coin in MAJORS]
    hhi = np.asarray(
        [
            exact_hhi([values[j] for values in coin_notional], day_notional[j])
            for j in range(len(day_notional))
        ],
        float,
    )
    liq = np.asarray(d["n_liq"], float)[selected]
    opens = np.asarray(d["n_open_flat"], float)[selected]
    keep = np.isfinite(x) & np.isfinite(hhi) & (hhi > 0) & (hhi <= 1)
    wallet, day, x, hhi, liq, opens = (value[keep] for value in (wallet, day, x, hhi, liq, opens))
    rvol = np.asarray([r_vol[int(v)] for v in day], float)
    return DailyPanel(
        wallet,
        day,
        np.asarray([day_to_ordinal(v) for v in day], np.int64),
        x,
        hhi,
        liq,
        opens,
        rvol,
        start,
        end,
    )


def exact_hhi(coin_notionals: list[Decimal], day_notional: Decimal) -> float:
    """Match the v1 Decimal-share-then-float HHI construction exactly."""
    total = Decimal(day_notional)
    if total <= 0:
        return math.nan
    shares = np.asarray([float(Decimal(v) / total) for v in coin_notionals], float)
    return float(shares @ shares)


def robust_observations(x: np.ndarray) -> tuple[np.ndarray, float]:
    x = np.asarray(x, float)
    med = float(np.median(x))
    scale = 1.4826 * float(np.median(np.abs(x - med)))
    if not np.isfinite(scale) or scale <= 0:
        scale = float(np.std(x, ddof=1)) if x.size >= 2 else math.nan
    if not np.isfinite(scale) or scale <= 0:
        return np.full(x.size, np.nan), math.nan
    return np.clip(x / scale, -5.0, 5.0), scale


def kalman_state_score(
    ordinal: np.ndarray,
    y: np.ndarray,
    r: np.ndarray,
    *,
    start_ordinal: int,
    end_ordinal: int,
    q: float,
    p0: float,
    shock: np.ndarray | None = None,
) -> tuple[float, float, float]:
    """Random-walk filter with calendar prediction gaps and optional shock resets."""
    ordinal = np.asarray(ordinal, np.int64)
    y, r = np.asarray(y, float), np.asarray(r, float)
    if not (ordinal.size and ordinal.shape == y.shape == r.shape):
        return math.nan, math.nan, math.nan
    theta, p, cursor = 0.0, float(p0), int(start_ordinal - 1)
    shock_arr = np.zeros(ordinal.size, bool) if shock is None else np.asarray(shock, bool)
    for dd, obs, rr, broken in zip(ordinal, y, r, shock_arr, strict=True):
        gap = int(dd) - cursor
        if gap <= 0 or not np.isfinite(obs) or not np.isfinite(rr) or rr <= 0:
            return math.nan, math.nan, math.nan
        p += gap * q
        if broken:
            theta = min(theta, -3.0)
            p = max(p, 1.0)
        gain = p / (p + rr)
        theta += gain * (obs - theta)
        p = (1.0 - gain) * p
        cursor = int(dd)
    p += (end_ordinal - cursor) * q
    score = theta / math.sqrt(p) if p > 0 and np.isfinite(p) else math.nan
    return float(score), float(theta), float(p)


def average_tie_percentile(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, float)
    if not values.size or not np.isfinite(values).all():
        raise ValueError("rank values must be nonempty and finite")
    order = np.argsort(values, kind="stable")
    sorted_v = values[order]
    rank = np.empty(values.size, float)
    st = 0
    while st < values.size:
        en = st + 1
        while en < values.size and sorted_v[en] == sorted_v[st]:
            en += 1
        rank[order[st:en]] = 0.5 * ((st + 1) + en)
        st = en
    return (rank - 0.5) / values.size


def score_panel(panel: DailyPanel) -> FoldScores:
    wallets, starts, counts = np.unique(panel.wallet, return_index=True, return_counts=True)
    score = {arm: np.full(wallets.size, np.nan) for arm in ARMS}
    base = np.zeros(wallets.size, bool)
    shock_gate = np.zeros(wallets.size, bool)
    neff = np.full(wallets.size, np.nan)
    scales = np.full(wallets.size, np.nan)
    for j, (st, n) in enumerate(zip(starts, counts, strict=True)):
        sl = slice(int(st), int(st + n))
        xx, oo = panel.x[sl], panel.ordinal[sl]
        if xx.size < ND_MIN or oo.max() < panel.end_ordinal - RECENCY_DAYS + 1:
            continue
        static = ordinary_t(xx)
        ew, neff[j] = ew_t(xx, oo, panel.end_ordinal, half_life=HALF_LIFE)
        yy, scales[j] = robust_observations(xx)
        dispersion = float(np.std(xx, ddof=1)) if xx.size >= 2 else math.nan
        valid = (
            xx.size >= ND_MIN
            and np.isfinite(dispersion)
            and dispersion > 0
            and np.isfinite(static)
            and np.isfinite(ew)
            and neff[j] >= N_EFF_MIN
            and oo.max() >= panel.end_ordinal - RECENCY_DAYS + 1
            and np.isfinite(scales[j])
        )
        if not valid:
            continue
        shock = (panel.n_liq[sl] > 0) | (xx <= BLOWUP_USD)
        shock_gate[j] = bool(np.any(shock & (oo >= panel.end_ordinal - 29)))
        breadth = np.maximum(panel.n_open_flat[sl], 0.25) / (4.0 * panel.hhi[sl])
        r_breadth = np.clip(np.power(breadth, -0.5), 0.5, 4.0)
        r_vol = panel.r_vol[sl]
        specs = {
            "KF60_BASE": (np.ones(xx.size), Q60, K60, None),
            "KF60_R_BREADTH": (r_breadth, Q60, K60, None),
            "KF60_R_VOL": (r_vol, Q60, K60, None),
            "KF60_Q_SLOW": (np.ones(xx.size), QSLOW, KSLOW, None),
            "KF60_BLOWUP": (np.ones(xx.size), Q60, K60, shock),
            "KF60_ALL": (np.clip(r_breadth * r_vol, 0.125, 64.0), QSLOW, KSLOW, shock),
        }
        for arm, (rr, q, p0, ss) in specs.items():
            score[arm][j] = kalman_state_score(
                oo,
                yy,
                rr,
                start_ordinal=panel.start_ordinal,
                end_ordinal=panel.end_ordinal,
                q=q,
                p0=p0,
                shock=ss,
            )[0]
        score["EW60"][j] = ew
        score["TSTAT_COMMON"][j] = static
        base[j] = all(np.isfinite(score[arm][j]) for arm in ARMS)
    eligible: dict[str, np.ndarray] = {}
    raw_v: dict[str, np.ndarray] = {}
    for arm in ARMS:
        mask = base & (~shock_gate if arm in SHOCK_ARMS else True)
        if int(mask.sum()) < MIN_FORMATION_POOL:
            raise RuntimeError(f"arm {arm}: formation pool only {mask.sum()}")
        eligible[arm] = mask
        raw = np.full(wallets.size, np.nan)
        pct = average_tie_percentile(score[arm][mask])
        raw[mask] = 2.0 * pct - 1.0
        raw_v[arm] = raw
    diag = {
        "n_wallets": int(wallets.size),
        "n_common_base": int(base.sum()),
        "n_final30_shock": int(np.sum(base & shock_gate)),
        "pool_sizes": {arm: int(eligible[arm].sum()) for arm in ARMS},
        "n_eff_median": float(np.median(neff[base])),
        "robust_scale_median": float(np.median(scales[base])),
    }
    return FoldScores(wallets, score, raw_v, eligible, shock_gate, diag)


def save_scores(fold: int, scores: FoldScores) -> Path:
    SCORES.mkdir(parents=True, exist_ok=True)
    payload: dict[str, pa.Array] = {"wallet": pa.array(scores.wallets)}
    for arm in ARMS:
        payload[f"score__{arm}"] = pa.array(scores.score[arm])
        payload[f"raw_v__{arm}"] = pa.array(scores.raw_v[arm])
        payload[f"eligible__{arm}"] = pa.array(scores.eligible[arm])
    payload["final30_shock"] = pa.array(scores.final30_shock)
    path = SCORES / f"scores_{fold}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(pa.table(payload), tmp, compression="zstd")
    tmp.replace(path)
    return path


def _eval_spec(con, fold: int, wallets: np.ndarray) -> dict[str, object]:
    return {
        "cache_schema": "adaptive-rq-eval-v1",
        **cache_identity_payload(PROFILE_ID),
        "fold": fold,
        "wallets_sha256": _sha256_json(sorted(np.asarray(wallets, str).tolist())),
        "source_lineage": lake.validated_lineage(con, [fold], ("alt_universe_wallet_coin_day",)),
    }


def cache_evaluation_panel(con, fold: int, wallets: np.ndarray) -> Path:
    PANELS.mkdir(parents=True, exist_ok=True)
    path = PANELS / f"evaluation_wc_{fold}.parquet"
    meta = path.with_suffix(".meta.json")
    spec = _eval_spec(con, fold, wallets)
    if path.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return path
    con.execute(
        "CREATE OR REPLACE TEMP TABLE arq_wallets AS SELECT UNNEST(?) wallet",
        [sorted(np.asarray(wallets, str).tolist())],
    )
    majors = ",".join(f"'{c}'" for c in MAJORS)
    glob = lake.wcd_month_glob(fold)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      SELECT lower(x.wallet) AS wallet,x.coin,x.day,
        SUM(CAST(x.pnl AS DECIMAL(38,12)))
          - SUM(CAST(x.fee AS DECIMAL(38,12)))
          - SUM(COALESCE(CAST(x.builder_fee AS DECIMAL(38,12)),0)) AS net_pnl,
        SUM(CAST(x.notional AS DECIMAL(38,12))) AS coin_notional,
        SUM(x.n_liq)::BIGINT AS n_liq
      FROM read_parquet('{glob}') x JOIN arq_wallets w ON lower(x.wallet)=w.wallet
      WHERE x.coin IN ({majors})
      GROUP BY lower(x.wallet),x.coin,x.day HAVING coin_notional>0
      ORDER BY wallet,day,coin
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post = lake.validated_lineage(con, [fold], ("alt_universe_wallet_coin_day",))
    if post["sha256"] != spec["source_lineage"]["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: evaluation WCD mutated")
    tmp.replace(path)
    mtmp = meta.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mtmp.replace(meta)
    return path


def _evaluation_rows(path: Path) -> dict[int, dict[str, object]]:
    d = pq.read_table(path).to_pydict()
    wallet = np.asarray(d["wallet"], str)
    coin = np.asarray(d["coin"], str)
    day = np.asarray(d["day"], np.int64)
    net, notl = d["net_pnl"], d["coin_notional"]
    n_liq = np.asarray(d["n_liq"], float)
    keys = np.char.add(np.char.add(wallet, "|"), day.astype(str))
    _, starts, counts = np.unique(keys, return_index=True, return_counts=True)
    out: dict[int, dict[str, object]] = {}
    for st, n in zip(starts, counts, strict=True):
        sl = slice(int(st), int(st + n))
        total_n = sum((Decimal(v) for v in notl[sl]), Decimal(0))
        total_p = sum((Decimal(v) for v in net[sl]), Decimal(0))
        if total_n <= 0:
            continue
        scale = min(Decimal(1), CAP_USD / total_n)
        dd, ww = int(day[st]), wallet[st]
        rec = out.setdefault(dd, {"x": {}, "shock": set(), "active": set()})
        rec["active"].add(ww)
        for k in range(int(st), int(st + n)):
            value = float(Decimal(net[k]) * scale) * 0.1
            if np.isfinite(value):
                rec["x"][(ww, coin[k])] = value
        norm_total = float(total_p * scale)
        if float(n_liq[sl].sum()) > 0 or norm_total <= BLOWUP_USD:
            rec["shock"].add(ww)
    return out


def _arm_coin_weights(
    scores: FoldScores, arm: str, active: set[str], quarantined: set[str]
) -> dict[str, float] | None:
    idx = {w: j for j, w in enumerate(scores.wallets)}
    members = sorted(
        w
        for w in active
        if w in idx
        and scores.eligible[arm][idx[w]]
        and (arm not in SHOCK_ARMS or w not in quarantined)
    )
    if len(members) < MIN_ARM_COIN:
        return None
    vals = np.array([scores.raw_v[arm][idx[w]] for w in members], float)
    vals -= vals.mean()
    denom = float(np.abs(vals).sum())
    if not np.isfinite(denom) or denom <= 0:
        return None
    weights = vals / (4.0 * denom)
    if not math.isclose(float(weights.sum()), 0.0, abs_tol=1e-12):
        raise RuntimeError("coin weight neutrality failed")
    if not math.isclose(float(np.abs(weights).sum()), 0.25, abs_tol=1e-12):
        raise RuntimeError("coin gross-weight invariant failed")
    return dict(zip(members, weights, strict=True))


def build_fold_factor(
    fold: int, scores: FoldScores, eval_path: Path
) -> tuple[dict[str, ContrastRows], dict[str, object], dict[str, set[str]]]:
    rows = _evaluation_rows(eval_path)
    ndays = calendar.monthrange(fold // 100, fold % 100)[1]
    calendar_days = [fold * 100 + d for d in range(1, ndays + 1)]
    q_until: dict[str, int] = {}
    accum = {
        name: {"wallet": [], "coin": [], "day": [], "fold": [], "z": [], "d2": []}
        for name in CONTRASTS
    }
    contrast_universe = {name: set() for name in CONTRASTS}
    arm_daily = {arm: [] for arm in ARMS}
    excluded: dict[str, list[str]] = {}
    kept: list[int] = []
    arm_wallet_support = {arm: set() for arm in ARMS}
    for dd in calendar_days:
        rec = rows.get(dd, {"x": {}, "shock": set(), "active": set()})
        active: set[str] = rec["active"]
        reasons: list[str] = []
        if len(active) < MIN_ACTIVE_BASE:
            reasons.append(f"active_base={len(active)}<{MIN_ACTIVE_BASE}")
        ordinal = day_to_ordinal(dd)
        quarantined = {w for w, until in q_until.items() if ordinal <= until}
        weights: dict[str, dict[tuple[str, str], float]] = {arm: {} for arm in ARMS}
        for arm in ARMS:
            for coin in MAJORS:
                active_coin = {w for (w, c) in rec["x"] if c == coin}
                cw = _arm_coin_weights(scores, arm, active_coin, quarantined)
                if cw is None:
                    reasons.append(f"{arm}:{coin}:short_or_degenerate")
                    continue
                for w, value in cw.items():
                    weights[arm][(w, coin)] = value
        if not reasons:
            kept.append(dd)
            for arm in ARMS:
                arm_wallet_support[arm].update(w for w, _ in weights[arm])
                value = sum(w * rec["x"][key] for key, w in weights[arm].items())
                arm_daily[arm].append(float(value))
            for name, (a, b) in CONTRASTS.items():
                keys = set(weights[a]) | set(weights[b])
                contrast_universe[name].update(w for w, _ in keys)
                for key in keys:
                    delta_w = weights[a].get(key, 0.0) - weights[b].get(key, 0.0)
                    if delta_w == 0:
                        continue
                    w, coin = key
                    z = delta_w * float(rec["x"].get(key, 0.0))
                    ac = accum[name]
                    ac["wallet"].append(w)
                    ac["coin"].append(coin)
                    ac["day"].append(dd)
                    ac["fold"].append(fold)
                    ac["z"].append(z)
                    ac["d2"].append(delta_w * delta_w)
        else:
            excluded[str(dd)] = reasons
        for w in rec["shock"]:
            q_until[w] = ordinal + QUARANTINE_DAYS
    result = {
        name: ContrastRows(
            np.asarray(v["wallet"], str),
            np.asarray(v["coin"], str),
            np.asarray(v["day"], np.int64),
            np.asarray(v["fold"], np.int64),
            np.asarray(v["z"], float),
            np.asarray(v["d2"], float),
            np.asarray(kept, np.int64),
            np.full(len(kept), fold, np.int64),
            np.asarray(sorted(contrast_universe[name]), str),
        )
        for name, v in accum.items()
    }
    diag = {
        "calendar_days": len(calendar_days),
        "kept_days": len(kept),
        "coverage": len(kept) / len(calendar_days),
        "kept_day_values": kept,
        "excluded_days": excluded,
        "arm_mean_bp_day": {
            arm: (float(np.mean(v)) if v else None) for arm, v in arm_daily.items()
        },
        "arm_wallet_support": {arm: len(v) for arm, v in arm_wallet_support.items()},
    }
    return result, diag, arm_wallet_support


def concat_rows(parts: list[ContrastRows]) -> ContrastRows:
    fields = (
        "wallet",
        "coin",
        "day",
        "fold",
        "z",
        "d2",
        "lattice_day",
        "lattice_fold",
        "universe_wallet",
    )
    return ContrastRows(*(np.concatenate([getattr(p, field) for p in parts]) for field in fields))


def _time_counts(
    rng: np.random.Generator, n_boot: int, calendar_n: int, retained_index: np.ndarray
) -> np.ndarray:
    block = min(BLOCK_DAYS, calendar_n)
    nblocks = int(math.ceil(calendar_n / block))
    out = np.zeros((n_boot, retained_index.size), np.int16)
    for j in range(n_boot):
        starts = rng.integers(0, calendar_n - block + 1, nblocks)
        picked = np.concatenate([np.arange(s, s + block) for s in starts])[:calendar_n]
        out[j] = np.bincount(picked, minlength=calendar_n)[retained_index]
    return out


def factor_bootstrap(
    rows: ContrastRows, c0: float, seed: int, mode: str, n_boot: int = N_BOOT
) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    wallets = np.unique(rows.universe_wallet)
    days = np.unique(rows.lattice_day)
    if wallets.size == 0 or days.size == 0:
        return np.array([]), np.array([]), {"original": 1.0, "fixed_injection": 1.0}
    wallet_index = {w: j for j, w in enumerate(wallets)}
    day_index = {int(d): j for j, d in enumerate(days)}
    wi = np.asarray([wallet_index[w] for w in rows.wallet], np.int64)
    di = np.asarray([day_index[int(d)] for d in rows.day], np.int64)
    zmat = np.zeros((wallets.size, days.size), float)
    d2mat = np.zeros_like(zmat)
    np.add.at(zmat, (wi, di), rows.z)
    np.add.at(d2mat, (wi, di), rows.d2)
    lo = day_to_ordinal(int(days.min()))
    hi = day_to_ordinal(int(days.max()))
    retained = np.asarray([day_to_ordinal(int(d)) - lo for d in days], np.int64)
    rng = np.random.default_rng(seed)
    batch = 100
    original = np.full(n_boot, np.nan)
    injected = np.full(n_boot, np.nan)
    for st in range(0, n_boot, batch):
        en = min(n_boot, st + batch)
        nb = en - st
        if mode in ("wallet", "crossed"):
            wm = rng.multinomial(
                wallets.size, np.full(wallets.size, 1.0 / wallets.size), size=nb
            ).astype(float)
        else:
            wm = np.ones((nb, wallets.size), float)
        if mode in ("time", "crossed"):
            tm = _time_counts(rng, nb, hi - lo + 1, retained).astype(float)
        else:
            tm = np.ones((nb, days.size), float)
        denom = tm.sum(axis=1)
        oz = wm @ zmat
        iz = wm @ (zmat + c0 * d2mat)
        good = denom > 0
        original[st:en][good] = np.sum(oz[good] * tm[good], axis=1) / denom[good]
        injected[st:en][good] = np.sum(iz[good] * tm[good], axis=1) / denom[good]
    bad_original = ~np.isfinite(original)
    bad_injected = ~np.isfinite(injected)
    bad_pair = bad_original | bad_injected
    return (
        original[~bad_pair],
        injected[~bad_pair],
        {
            "original": float(np.mean(bad_original)),
            "fixed_injection": float(np.mean(bad_injected)),
        },
    )


def _ci(x: np.ndarray) -> list[float] | None:
    if not x.size:
        return None
    return [float(np.quantile(x, 0.025)), float(np.quantile(x, 0.975))]


def top5_wallet_abs_contribution_share(rows: ContrastRows) -> float | None:
    """Share of absolute wallet-level contrast contribution supplied by top five."""
    wallets, inverse = np.unique(rows.wallet, return_inverse=True)
    if not wallets.size:
        return None
    total = np.zeros(wallets.size, float)
    np.add.at(total, inverse, rows.z)
    absolute = np.abs(total)
    denom = float(absolute.sum())
    if not np.isfinite(denom) or denom <= 0:
        return None
    return float(np.sort(absolute)[-5:].sum() / denom)


def compare_factor(
    rows: ContrastRows,
    fold_diag: dict[str, dict[str, object]],
    arm_support: dict[str, set[str]],
    arms: tuple[str, str],
    seed: int,
    n_boot: int = N_BOOT,
) -> dict[str, object]:
    days = np.unique(rows.lattice_day)
    wallets = np.unique(rows.universe_wallet)
    if not days.size or not wallets.size or float(rows.d2.sum()) <= 0:
        return {"inference_status": "NOT_ESTIMABLE", "resolution_capable": False}
    point = float(rows.z.sum() / days.size)
    c0 = CARE_BP * days.size / float(rows.d2.sum())
    injected_point = float((rows.z + c0 * rows.d2).sum() / days.size)
    if not math.isclose(injected_point - point, CARE_BP, abs_tol=1e-10):
        raise RuntimeError("fixed +5 point injection invariant failed")
    draws: dict[str, np.ndarray] = {}
    injected_draws: dict[str, np.ndarray] = {}
    invalid: dict[str, dict[str, float]] = {}
    for j, mode in enumerate(("wallet", "time", "crossed")):
        draws[mode], injected_draws[mode], invalid[mode] = factor_bootstrap(
            rows, c0, seed + 100 * j, mode, n_boot
        )
    crossed = draws["crossed"]
    if not crossed.size:
        return {"inference_status": "NOT_ESTIMABLE", "resolution_capable": False}
    u = crossed - crossed.mean()
    critical = float(np.quantile(u, 0.975))
    mde = critical - float(np.quantile(u, 0.20))
    power = float(np.mean(u + CARE_BP > critical))
    p_two = float((1 + np.sum(np.abs(u) >= abs(point))) / (u.size + 1))
    p_null = float((1 + np.sum(u <= point - CARE_BP)) / (u.size + 1))
    shift = injected_draws["crossed"] - crossed
    shift_ci = _ci(shift)
    coverage_ok = all(float(v["coverage"]) >= MIN_FOLD_COVERAGE for v in fold_diag.values())
    calendar_lo = day_to_ordinal(int(days.min()))
    blocks = np.unique(
        (np.array([day_to_ordinal(int(d)) for d in days]) - calendar_lo) // BLOCK_DAYS
    )
    per_arm_support = {arm: int(len(arm_support[arm])) for arm in arms}
    support_ok = (
        wallets.size >= MIN_INFER_WALLETS
        and blocks.size >= MIN_INFER_BLOCKS
        and min(per_arm_support.values()) >= MIN_INFER_WALLETS
    )
    control_ok = bool(shift_ci is not None and shift_ci[0] > 0)
    invalid_ok = max(v for mode in invalid.values() for v in mode.values()) <= MAX_INVALID_BOOT_FRAC
    resolution = bool(
        mde <= CARE_BP
        and power >= 0.80
        and control_ok
        and invalid_ok
        and coverage_ok
        and support_ok
    )
    per_fold = {}
    for fold in FOLDS:
        m = rows.fold == fold
        nday = int(np.sum(rows.lattice_fold == fold))
        per_fold[str(fold)] = float(rows.z[m].sum() / nday) if nday else None
    per_coin = {}
    for coin in MAJORS:
        m = rows.coin == coin
        per_coin[coin] = float(rows.z[m].sum() / days.size)
    d_abs = np.sqrt(rows.d2) * abs(c0)
    return {
        "inference_status": "ESTIMABLE",
        "point_bp_day": point,
        "wallet_ci95": _ci(draws["wallet"]),
        "time_ci95": _ci(draws["time"]),
        "crossed_ci95": _ci(crossed),
        "crossed_p_two_sided": p_two,
        "p_null_plus5_one_sided": p_null,
        "crossed_mde80_bp": mde,
        "shifted_noise_power_at_plus5": power,
        "critical_q975": critical,
        "fixed_injection": {
            "c0": c0,
            "point_bp_day": injected_point,
            "point_shift_bp_day": injected_point - point,
            "crossed_ci95": _ci(injected_draws["crossed"]),
            "paired_shift_ci95": shift_ci,
            "recovery_pass": control_ok,
            "median_abs_cell_perturbation_bp": float(np.median(d_abs)),
            "max_abs_cell_perturbation_bp": float(np.max(d_abs)),
            "zero_contrast_days": int(sum(not np.any(rows.d2[rows.day == d] > 0) for d in days)),
        },
        "invalid_draw_fraction": invalid,
        "n_boot": n_boot,
        "support": {
            "global_wallets": int(wallets.size),
            "nonzero_difference_wallets": int(np.unique(rows.wallet).size),
            "occupied_calendar_blocks": int(blocks.size),
            "days": int(days.size),
            "per_arm_global_wallets": per_arm_support,
        },
        "coverage_gate_pass": coverage_ok,
        "support_gate_pass": support_ok,
        "concentration": {
            "top5_wallet_abs_contribution_share": (top5_wallet_abs_contribution_share(rows))
        },
        "resolution_capable": resolution,
        "per_fold_delta_bp_day": per_fold,
        "folds_positive": sum(v is not None and v > 0 for v in per_fold.values()),
        "per_coin_delta_bp_day": per_coin,
        "coins_positive": sum(v > 0 for v in per_coin.values()),
    }


def holm(results: dict[str, dict[str, object]], pkey: str, outkey: str) -> None:
    ordered = sorted(results, key=lambda k: (float(results[k].get(pkey, 1.0)), k))
    running = 0.0
    m = len(ordered)
    for j, name in enumerate(ordered):
        running = max(running, (m - j) * float(results[name].get(pkey, 1.0)))
        results[name][outkey] = min(1.0, running)


def _save_contributions(name: str, rows: ContrastRows) -> Path:
    CONTRIB.mkdir(parents=True, exist_ok=True)
    path = CONTRIB / f"{name}.parquet"
    tmp = path.with_suffix(".parquet.tmp")
    days = np.unique(rows.lattice_day)
    c0 = (
        CARE_BP * days.size / float(rows.d2.sum())
        if days.size and float(rows.d2.sum()) > 0
        else math.nan
    )
    pq.write_table(
        pa.table(
            {
                "wallet": rows.wallet,
                "coin": rows.coin,
                "day": rows.day,
                "fold": rows.fold,
                "z": rows.z,
                "d2": rows.d2,
                "z_fixed_injected": rows.z + c0 * rows.d2,
                "abs_cell_perturbation_bp": np.sqrt(rows.d2) * abs(c0),
            }
        ),
        tmp,
        compression="zstd",
    )
    tmp.replace(path)
    sidecar = path.with_suffix(".lattice.json")
    stmp = sidecar.with_suffix(".json.tmp")
    stmp.write_text(
        json.dumps(
            {
                "lattice_day": rows.lattice_day.tolist(),
                "lattice_fold": rows.lattice_fold.tolist(),
                "universe_wallet": sorted(np.unique(rows.universe_wallet).tolist()),
                "c0": c0,
            },
            indent=1,
            sort_keys=True,
        )
    )
    stmp.replace(sidecar)
    return path


def validate_profile(profile_id: str) -> None:
    if profile_id != PROFILE_ID:
        raise RuntimeError(f"explicit frozen profile required: {PROFILE_ID}")


def run(*, profile_id: str, n_boot: int = N_BOOT) -> dict[str, object]:
    validate_profile(profile_id)
    if n_boot != N_BOOT:
        raise RuntimeError(f"frozen adaptive profile requires n_boot={N_BOOT}")
    DERIVED.mkdir(parents=True, exist_ok=True)
    all_months = sorted({m for fold in FOLDS for m in formation_months(fold)})
    ctx_paths = exact_context_paths(all_months)
    print(f"[adaptive-rq] hashing {len(ctx_paths)} formation context files", flush=True)
    context_before = _context_records(ctx_paths)
    rv, invalid_ctx = context_rv_catalog(ctx_paths)
    con = lake.connect()
    fold_scores: dict[int, FoldScores] = {}
    score_hashes: dict[str, str] = {}
    panel_specs: dict[str, object] = {}
    evaluation_specs: dict[str, object] = {}
    fold_rows: dict[str, list[ContrastRows]] = {name: [] for name in CONTRASTS}
    fold_diag: dict[str, dict[str, object]] = {}
    arm_support = {arm: set() for arm in ARMS}
    for fold in FOLDS:
        print(f"[adaptive-rq] formation fold {fold}", flush=True)
        months = formation_months(fold)
        path = cache_formation_panel(con, fold, context_before, invalid_ctx)
        panel = load_daily_panel(path, fold, fold_r_vol(months, rv))
        scores = score_panel(panel)
        score_path = save_scores(fold, scores)
        score_hashes[str(fold)] = _file_sha256(score_path)
        fold_scores[fold] = scores
        panel_specs[str(fold)] = json.loads(path.with_suffix(".meta.json").read_text())
        print(f"  {scores.diagnostics}", flush=True)
    context_after = _context_records(ctx_paths)
    if context_after != context_before:
        raise RuntimeError("formation asset_ctx mutated during materialization")
    for fold in FOLDS:
        print(f"[adaptive-rq] evaluation factor fold {fold}", flush=True)
        base_wallets = fold_scores[fold].wallets[fold_scores[fold].eligible["EW60"]]
        eval_path = cache_evaluation_panel(con, fold, base_wallets)
        evaluation_specs[str(fold)] = json.loads(eval_path.with_suffix(".meta.json").read_text())
        parts, diag, fold_support = build_fold_factor(fold, fold_scores[fold], eval_path)
        for arm in ARMS:
            arm_support[arm].update(fold_support[arm])
        fold_diag[str(fold)] = {**fold_scores[fold].diagnostics, **diag}
        for name, rows in parts.items():
            fold_rows[name].append(rows)
        print(f"  coverage={diag['coverage']:.3f} kept={diag['kept_days']}", flush=True)
    con.close()
    combined = {name: concat_rows(parts) for name, parts in fold_rows.items()}
    for name, rows in combined.items():
        _save_contributions(name, rows)
    fold_rows.clear()
    gc.collect()
    results: dict[str, dict[str, object]] = {}
    for j, name in enumerate(CONTRASTS):
        print(f"[adaptive-rq] inference contrast {name}", flush=True)
        rows = combined.pop(name)
        results[name] = compare_factor(
            rows,
            fold_diag,
            arm_support,
            CONTRASTS[name],
            SEED + 10_000 * j,
            n_boot,
        )
        del rows
        gc.collect()
    secondary_results = {name: results[name] for name in SECONDARIES}
    holm(secondary_results, "crossed_p_two_sided", "holm_q")
    holm(secondary_results, "p_null_plus5_one_sided", "null_plus5_holm_q")
    for name, result in results.items():
        result["positive_promotion_eligible"] = False
        result["method_null_eligible"] = False
        result["verdict_status"] = "BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC"
        if name == PRIMARY:
            result["within_run_positive_direction"] = bool(
                result.get("resolution_capable")
                and result.get("point_bp_day", math.nan) > 0
                and result.get("crossed_ci95", [-math.inf])[0] > 0
            )
            result["within_run_null_resolution_pass"] = bool(
                result.get("resolution_capable")
                and result.get("crossed_ci95", [math.inf, math.inf])[1] < CARE_BP
            )
        elif name in SECONDARIES:
            result["within_run_positive_direction"] = bool(
                result.get("resolution_capable")
                and result.get("point_bp_day", math.nan) > 0
                and result.get("crossed_ci95", [-math.inf])[0] > 0
                and result.get("holm_q", 1.0) <= 0.05
            )
            result["within_run_null_resolution_pass"] = bool(
                result.get("resolution_capable")
                and result.get("crossed_ci95", [math.inf, math.inf])[1] < CARE_BP
                and result.get("null_plus5_holm_q", 1.0) <= 0.05
            )
    primary_powered = bool(results[PRIMARY].get("resolution_capable"))
    for fold, expected in score_hashes.items():
        if _file_sha256(SCORES / f"scores_{fold}.parquet") != expected:
            raise RuntimeError(f"score artifact {fold} mutated before factor report commit")
    rep = {
        "status": "BURNED_ADAPTIVE_COMPONENT_DIAGNOSTIC",
        "profile_id": PROFILE_ID,
        "architecture": ARCH.name,
        "architecture_sha256": _file_sha256(ARCH),
        "code_commit": lake.git_describe(),
        "code_sha256": _code_sha256(Path(__file__)),
        "config": {
            "arms": list(ARMS),
            "profile_id": PROFILE_ID,
            "primary": PRIMARY,
            "contrasts": {k: list(v) for k, v in CONTRASTS.items()},
            "k60": K60,
            "q60": Q60,
            "kslow": KSLOW,
            "qslow": QSLOW,
            "slow_implied_half_life_days": -math.log(2.0) / math.log(1.0 - KSLOW),
            "n_boot": n_boot,
            "care_bp_day": CARE_BP,
            "min_active_base": MIN_ACTIVE_BASE,
            "min_formation_pool": MIN_FORMATION_POOL,
            "min_arm_coin": MIN_ARM_COIN,
            "min_fold_coverage": MIN_FOLD_COVERAGE,
            "factor_interpretation": "non-executable end-of-day active-wallet measurement",
        },
        "invalid_context_days": {str(k): v for k, v in sorted(invalid_ctx.items())},
        "context_files_sha256": _sha256_json(context_before),
        "panel_specs_sha256": _sha256_json(panel_specs),
        "score_files_sha256": score_hashes,
        "evaluation_specs_sha256": _sha256_json(evaluation_specs),
        "evaluation_specs": evaluation_specs,
        "folds": fold_diag,
        "results": results,
        "primary_resolution_capable": primary_powered,
        "conditional_book_action": (
            "RUN_DIRECTION_INDEPENDENT"
            if primary_powered
            else "STOP_AVAILABLE_BURNED_DATA_CANNOT_RESOLVE_ADAPTIVE_FILTER"
        ),
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=1, sort_keys=True))
    tmp.replace(OUT)
    print(f"-> {OUT}", flush=True)
    return rep


if __name__ == "__main__":
    raise SystemExit(
        "Generic execution is disabled; use `python -m "
        "research.studies.copy_cohort.adaptive_rq_run`."
    )
