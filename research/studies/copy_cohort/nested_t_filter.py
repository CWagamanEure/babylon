"""Parity-locked nested dynamic t selector on burned majors folds."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT

from . import lake
from .adaptive_rq_filter import context_rv_catalog, exact_context_paths, exact_hhi
from .alt_fresh_validate import MAJORS
from .dynamic_t_quality import FOLDS, ND_MIN, day_to_ordinal, formation_months, month_start
from .filtered_quality import (
    PANELS as FILTERED_PANELS,
)
from .filtered_quality import (
    _code_sha256,
    _sha256_json,
    source_manifest_fingerprint,
)
from .informed import t_to_z, two_groups
from .majors_native import FROZEN, _select_top100

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "nested_t_filter"
PANELS = DERIVED / "panels"
OUT = DERIVED / "rosters.json"
ARCH = Path(__file__).with_name("NESTED_T_FILTER_ARCH.md")

CAP = Decimal("100000")
TOP_K = 30
BOT_MAX = 500.0
BLOWUP_USD = -100_000.0
HALF_LIVES = (60.0, 120.0)
ATOL = 1e-9
RTOL = 1e-12

ARMS = (
    "LEGACY_STATIC_T30",
    "STATIC_T30",
    "IDENTITY_Q0_T30",
    "STATIC_E30",
    "KF60_T30",
    "KF120_T30",
    "KF60_R_VOL_T30",
    "KF60_R_BREADTH_T30",
    "KF60_BLOWUP_T30",
    "KF120_ALL_T30",
    "STATIC_BOT500_T30",
    "KF120_ALL_BOT500_T30",
)


def dependency_hashes() -> dict[str, str]:
    names = (
        "adaptive_rq_filter.py",
        "alt_fresh_validate.py",
        "dynamic_t_quality.py",
        "filtered_quality.py",
        "informed.py",
        "majors_native.py",
    )
    return {name: _file_sha256(Path(__file__).with_name(name)) for name in names}


@dataclass(frozen=True)
class Panel:
    wallet: np.ndarray
    day: np.ndarray
    ordinal: np.ndarray
    day_pnl: np.ndarray
    day_notional: np.ndarray
    x: np.ndarray
    hhi: np.ndarray
    n_liq: np.ndarray
    n_open: np.ndarray
    fills_per_day: np.ndarray
    r_vol: np.ndarray
    start_ordinal: int
    end_ordinal: int


def normalized_x(pnl: Decimal, notional: Decimal) -> float:
    p, n = Decimal(pnl), Decimal(notional)
    if n <= 0:
        return math.nan
    return float(p * min(Decimal(1), CAP / n))


def q_ratio(half_life: float) -> float:
    k = 1.0 - 2.0 ** (-1.0 / float(half_life))
    return k * k / (1.0 - k)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _panel_spec(con, fold: int, context_paths: list[Path]) -> dict[str, object]:
    months = formation_months(fold)
    ctx = [
        {"path": str(p), "size": p.stat().st_size, "sha256": _file_sha256(p)} for p in context_paths
    ]
    return {
        "schema": "nested-t-panel-v1",
        "fold": fold,
        "formation_months": months,
        "source_lineage": lake.validated_lineage(con, months, ("alt_universe_wallet_coin_day",)),
        "context": ctx,
        "context_sha256": _sha256_json(ctx),
        "architecture_sha256": _file_sha256(ARCH),
        "code_sha256": _code_sha256(Path(__file__)),
        "dependency_hashes": dependency_hashes(),
        "formula": "majors (pnl-fee)*min(1,100000/notional); no builder fee",
    }


def cache_panel(con, fold: int, context_paths: list[Path]) -> Path:
    PANELS.mkdir(parents=True, exist_ok=True)
    path = PANELS / f"daily_{fold}.parquet"
    meta = PANELS / f"daily_{fold}.meta.json"
    spec = _panel_spec(con, fold, context_paths)
    if path.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return path
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in formation_months(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH allact AS (
        SELECT lower(wallet) AS wallet, SUM(n_fills)::DOUBLE AS all_fills,
               COUNT(DISTINCT day)::DOUBLE AS all_active_days
        FROM read_parquet([{globs}]) GROUP BY lower(wallet)
      ), wc AS (
        SELECT lower(wallet) AS wallet,coin,day,
          SUM(CAST(pnl AS DECIMAL(38,12))) - SUM(CAST(fee AS DECIMAL(38,12))) AS day_pnl,
          SUM(CAST(notional AS DECIMAL(38,12))) AS coin_notional,
          SUM(n_liq)::BIGINT AS n_liq, SUM(n_open_flat)::BIGINT AS n_open_flat
        FROM read_parquet([{globs}]) WHERE coin IN ({majors})
        GROUP BY lower(wallet),coin,day
      ), wd AS (
        SELECT wallet,day,SUM(day_pnl) AS day_pnl,SUM(coin_notional) AS day_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='BTC'),0) AS btc_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='ETH'),0) AS eth_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='SOL'),0) AS sol_notional,
          COALESCE(SUM(coin_notional) FILTER(WHERE coin='HYPE'),0) AS hype_notional,
          SUM(n_liq)::BIGINT AS n_liq,SUM(n_open_flat)::BIGINT AS n_open_flat
        FROM wc GROUP BY wallet,day HAVING SUM(coin_notional)>0
      )
      SELECT wd.*,allact.all_fills/NULLIF(allact.all_active_days,0) AS fills_per_day
      FROM wd JOIN allact USING(wallet) ORDER BY wallet,day
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post = lake.validated_lineage(con, formation_months(fold), ("alt_universe_wallet_coin_day",))
    if post["sha256"] != spec["source_lineage"]["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: source mutated during panel build")
    tmp.replace(path)
    mt = meta.with_suffix(".json.tmp")
    mt.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mt.replace(meta)
    return path


def lagged_r_vol(months: list[int], rv: dict[int, float]) -> dict[int, float]:
    expected = [int(v.replace("-", "")) for v in lake.expected_iso_days(months)]
    valid_prior: list[float] = []
    out: dict[int, float] = {}
    for day in expected:
        if not valid_prior:
            out[day] = 1.0
        elif len(valid_prior) < 5:
            out[day] = 1.0
        else:
            ratio = valid_prior[-1] / float(np.median(valid_prior[-20:]))
            out[day] = float(np.clip(ratio * ratio, 0.5, 4.0))
        if day in rv and np.isfinite(rv[day]) and rv[day] > 0:
            valid_prior.append(float(rv[day]))
    return out


def load_panel(path: Path, fold: int, r_vol: dict[int, float]) -> Panel:
    d = pq.read_table(path).to_pydict()
    wallet = np.asarray(d["wallet"], str)
    day = np.asarray(d["day"], np.int64)
    pnl = d["day_pnl"]
    notional = d["day_notional"]
    x = np.asarray([normalized_x(p, n) for p, n in zip(pnl, notional, strict=True)])
    ordinal = np.asarray([day_to_ordinal(v) for v in day], np.int64)
    wallets, starts, counts = np.unique(wallet, return_index=True, return_counts=True)
    expected_starts = np.r_[0, np.cumsum(counts[:-1])]
    if not np.array_equal(starts, expected_starts):
        raise RuntimeError(f"fold {fold}: wallet rows are not contiguous and ordered")
    same_wallet = wallet[1:] == wallet[:-1]
    if np.any(ordinal[1:][same_wallet] <= ordinal[:-1][same_wallet]):
        raise RuntimeError(f"fold {fold}: duplicate or non-increasing wallet/day rows")
    sx = np.add.reduceat(x, starts)
    mean = sx / counts
    centered = x - np.repeat(mean, counts)
    ss = np.add.reduceat(centered * centered, starts)
    eligible_group = (counts >= ND_MIN) & (ss > 0) & np.isfinite(ss)
    eligible_row = np.repeat(eligible_group, counts)
    cn = [d[f"{c.lower()}_notional"] for c in MAJORS]
    hhi = np.full(wallet.size, np.nan)
    for j in np.flatnonzero(eligible_row):
        hhi[j] = exact_hhi([a[j] for a in cn], notional[j])
    start, end = (
        month_start(formation_months(fold)[0]).toordinal(),
        month_start(fold).toordinal() - 1,
    )
    if np.any((ordinal < start) | (ordinal > end)):
        raise RuntimeError(f"fold {fold}: panel row outside formation")
    return Panel(
        wallet,
        day,
        ordinal,
        np.asarray([float(v) for v in pnl], float),
        np.asarray([float(v) for v in notional], float),
        x,
        hhi,
        np.asarray(d["n_liq"], float),
        np.asarray(d["n_open_flat"], float),
        np.asarray(d["fills_per_day"], float),
        np.asarray([r_vol.get(int(v), 1.0) for v in day], float),
        start,
        end,
    )


def reference_path(con, fold: int) -> Path:
    """Independently materialized literal legacy-x panel from the prior audited pipeline."""
    path = FILTERED_PANELS / f"daily_{fold}.parquet"
    meta = path.with_suffix(".meta.json")
    if not path.exists() or not meta.exists():
        raise RuntimeError(f"fold {fold}: independent reference panel is absent")
    spec = json.loads(meta.read_text())
    expected = source_manifest_fingerprint(con, formation_months(fold))
    expected_config = {
        "majors": list(MAJORS),
        "cap_usd": 100_000.0,
        "nd_min": ND_MIN,
        "recency_days": 30,
        "min_cross_section": 200,
        "fee_formula": "sum(pnl)-sum(fee)-sum(coalesce(builder_fee,0))",
        "legacy_fee_formula": "sum(pnl)-sum(fee)",
    }
    expected_code = _code_sha256(Path(__file__).with_name("filtered_quality.py"))
    if (
        spec.get("cache_schema") != "filtered-quality-panel-v2"
        or spec.get("source_manifest") != expected
        or spec.get("formation_months") != formation_months(fold)
        or spec.get("config") != expected_config
        or spec.get("code_sha256") != expected_code
    ):
        raise RuntimeError(f"fold {fold}: independent reference lineage is stale")
    return path


def reference_rows(con, fold: int) -> dict[str, np.ndarray]:
    tab = pq.read_table(
        reference_path(con, fold), columns=["wallet", "day", "day_notional", "legacy_x"]
    )
    d = tab.to_pydict()
    notional = np.asarray(d["day_notional"], float)
    x = np.asarray(d["legacy_x"], float)
    pnl = x / np.minimum(1.0, float(CAP) / np.maximum(notional, 1e-12))
    return {
        "wallet": np.asarray(d["wallet"], str),
        "day": np.asarray(d["day"], np.int64),
        "day_pnl": pnl,
        "day_notional": notional,
        "x": x,
    }


def reference_scores(con, fold: int) -> dict[str, np.ndarray]:
    path = reference_path(con, fold)
    return con.execute(f"""
      SELECT lower(wallet) AS wallet,count(*)::BIGINT AS nd,avg(legacy_x) AS mu,
        stddev_samp(legacy_x) AS sd,
        avg(legacy_x)/(stddev_samp(legacy_x)/sqrt(count(*))) AS t
      FROM read_parquet('{path.as_posix()}') GROUP BY lower(wallet)
      HAVING count(*)>={ND_MIN} AND stddev_samp(legacy_x)>0
      ORDER BY wallet
    """).fetchnumpy()


def static_scores(panel: Panel) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    wallets, starts, counts = np.unique(panel.wallet, return_index=True, return_counts=True)
    mean = np.add.reduceat(panel.x, starts) / counts
    centered = panel.x - np.repeat(mean, counts)
    ss = np.add.reduceat(centered * centered, starts)
    sd = np.full(wallets.size, np.nan)
    valid_n = counts >= ND_MIN
    sd[valid_n] = np.sqrt(ss[valid_n] / (counts[valid_n] - 1))
    score = np.full(wallets.size, np.nan)
    good = valid_n & np.isfinite(sd) & (sd > 0)
    score[good] = mean[good] / (sd[good] / np.sqrt(counts[good]))
    return wallets, counts.astype(float), sd, score


def align_reference_scores(panel: Panel, ref: dict[str, np.ndarray]) -> dict[str, object]:
    wallets, nd, sd, score = static_scores(panel)
    good = np.isfinite(score)
    wallets, nd, sd, score = wallets[good], nd[good], sd[good], score[good]
    rw = ref["wallet"].astype(str)
    if not np.array_equal(wallets, rw) or not np.array_equal(
        nd.astype(np.int64), np.asarray(ref["nd"], np.int64)
    ):
        raise RuntimeError("full eligible wallet/nd parity failed")
    starts = np.searchsorted(panel.wallet, wallets, side="left")
    mu = np.asarray(
        [
            np.mean(panel.x[int(st) : int(st + n)])
            for st, n in zip(starts, nd.astype(int), strict=True)
        ],
        float,
    )
    maxima: dict[str, float] = {}
    for key, cand in (("mu", mu), ("sd", sd), ("t", score)):
        expected = np.asarray(ref[key], float)
        if not np.allclose(cand, expected, atol=ATOL, rtol=RTOL):
            raise RuntimeError(f"summary {key} parity failed max={np.max(np.abs(cand - expected))}")
        maxima[f"max_abs_{key}"] = float(np.max(np.abs(cand - expected)))
    return {"n_eligible": int(wallets.size), **maxima}


def _align_reference(panel: Panel, ref: dict[str, np.ndarray]) -> dict[str, object]:
    rw, rd = ref["wallet"].astype(str), np.asarray(ref["day"], np.int64)
    if not np.array_equal(panel.wallet, rw) or not np.array_equal(panel.day, rd):
        raise RuntimeError("wallet-day reference parity failed")
    checks = {
        "day_pnl": np.asarray(ref["day_pnl"], float),
        "day_notional": np.asarray(ref["day_notional"], float),
        "x": np.asarray(ref["x"], float),
    }
    candidate = {"day_pnl": panel.day_pnl, "day_notional": panel.day_notional, "x": panel.x}
    maxima: dict[str, float] = {}
    for key in checks:
        if not np.allclose(candidate[key], checks[key], atol=ATOL, rtol=RTOL):
            raise RuntimeError(
                f"daily {key} parity failed max={np.max(np.abs(candidate[key] - checks[key]))}"
            )
        maxima[f"max_abs_{key}"] = float(np.max(np.abs(candidate[key] - checks[key])))
    return {"n_rows": int(panel.x.size), **maxima}


def kalman_score(
    x: np.ndarray,
    ordinal: np.ndarray,
    end_ordinal: int,
    r_mult: np.ndarray,
    *,
    half_life: float | None,
    shock: np.ndarray | None = None,
) -> float:
    x, ordinal, r_mult = (
        np.asarray(x, float),
        np.asarray(ordinal, np.int64),
        np.asarray(r_mult, float),
    )
    if x.size < 2 or not (x.shape == ordinal.shape == r_mult.shape):
        return math.nan
    r = float(np.var(x, ddof=1))
    if not np.isfinite(r) or r <= 0 or np.any(~np.isfinite(r_mult)) or np.any(r_mult <= 0):
        return math.nan
    q = 0.0 if half_life is None else r * q_ratio(half_life)
    ss = np.zeros(x.size, bool) if shock is None else np.asarray(shock, bool)
    theta, p = float(x[0]), r
    if ss[0]:
        theta = min(theta, -3.0 * math.sqrt(r))
        p = max(p, r)
        rr = r * float(r_mult[0])
        gain = p / (p + rr)
        theta += gain * (float(x[0]) - theta)
        p *= 1.0 - gain
    cursor = int(ordinal[0])
    for obs, dd, mm, broken in zip(x[1:], ordinal[1:], r_mult[1:], ss[1:], strict=True):
        gap = int(dd) - cursor
        if gap <= 0:
            return math.nan
        p += gap * q
        if broken:
            theta, p = min(theta, -3.0 * math.sqrt(r)), max(p, r)
        rr = r * float(mm)
        gain = p / (p + rr)
        theta += gain * (float(obs) - theta)
        p *= 1.0 - gain
        cursor = int(dd)
    p += (int(end_ordinal) - cursor) * q
    return float(theta / math.sqrt(p)) if p > 0 and np.isfinite(p) else math.nan


def topk(wallets: np.ndarray, score: np.ndarray, mask: np.ndarray | None = None) -> list[str]:
    good = np.isfinite(score) if mask is None else np.isfinite(score) & np.asarray(mask, bool)
    w, s = wallets[good], score[good]
    if w.size < TOP_K:
        raise RuntimeError(f"top-k pool only {w.size}")
    return w[np.lexsort((w, -s))[:TOP_K]].tolist()


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    out = np.empty(values.size, float)
    out[order] = np.arange(values.size, dtype=float)
    return out


def score_fold(panel: Panel, frozen: set[str]) -> tuple[dict[str, list[str]], dict[str, object]]:
    wallets, nd, sd, static = static_scores(panel)
    starts = np.searchsorted(panel.wallet, wallets, side="left")
    counts = nd.astype(int)
    ident = np.full(wallets.size, np.nan)
    scores = {
        name: np.full(wallets.size, np.nan)
        for name in ("KF60", "KF120", "KF60_R_VOL", "KF60_R_BREADTH", "KF60_BLOWUP", "KF120_ALL")
    }
    fpd = np.full(wallets.size, np.nan)
    for j in np.flatnonzero(np.isfinite(static)):
        st, n = starts[j], counts[j]
        sl = slice(int(st), int(st + n))
        xx, oo = panel.x[sl], panel.ordinal[sl]
        one = np.ones(n)
        breadth = np.maximum(panel.n_open[sl], 0.25) / (4.0 * panel.hhi[sl])
        rb = np.clip(np.power(breadth, -0.5), 0.5, 4.0)
        rv = panel.r_vol[sl]
        shock = (panel.n_liq[sl] > 0) | (xx <= BLOWUP_USD)
        ident[j] = kalman_score(xx, oo, panel.end_ordinal, one, half_life=None)
        scores["KF60"][j] = kalman_score(xx, oo, panel.end_ordinal, one, half_life=60)
        scores["KF120"][j] = kalman_score(xx, oo, panel.end_ordinal, one, half_life=120)
        scores["KF60_R_VOL"][j] = kalman_score(xx, oo, panel.end_ordinal, rv, half_life=60)
        scores["KF60_R_BREADTH"][j] = kalman_score(xx, oo, panel.end_ordinal, rb, half_life=60)
        scores["KF60_BLOWUP"][j] = kalman_score(
            xx, oo, panel.end_ordinal, one, half_life=60, shock=shock
        )
        scores["KF120_ALL"][j] = kalman_score(
            xx, oo, panel.end_ordinal, np.clip(rv * rb, 0.25, 16), half_life=120, shock=shock
        )
        fpd[j] = panel.fills_per_day[int(st)]
    eligible = np.isfinite(static)
    if not np.allclose(ident[eligible], static[eligible], atol=ATOL, rtol=RTOL):
        raise RuntimeError(
            f"Q0 identity failed max={np.max(np.abs(ident[eligible] - static[eligible]))}"
        )
    static_top = topk(wallets, static)
    if static_top != topk(wallets, ident):
        raise RuntimeError("Q0 top30 identity failed")
    z = t_to_z(static[eligible], nd[eligible] - 1)
    tg = two_groups(z)
    p = np.full(wallets.size, np.nan)
    p[eligible] = tg["p_informed"]
    pos = eligible & (static > 0)
    pe = p.copy()
    pe[~pos] = np.nan
    # local-fdr primary, signed t tie, wallet final tie.
    ew, ep = wallets[np.isfinite(pe)], pe[np.isfinite(pe)]
    et = static[np.isfinite(pe)]
    efron = ew[np.lexsort((ew, -et, -ep))[:TOP_K]].tolist()
    bot = eligible & np.isfinite(fpd) & (fpd <= BOT_MAX)
    rosters = {
        "STATIC_T30": static_top,
        "IDENTITY_Q0_T30": topk(wallets, ident),
        "STATIC_E30": efron,
        "KF60_T30": topk(wallets, scores["KF60"]),
        "KF120_T30": topk(wallets, scores["KF120"]),
        "KF60_R_VOL_T30": topk(wallets, scores["KF60_R_VOL"]),
        "KF60_R_BREADTH_T30": topk(wallets, scores["KF60_R_BREADTH"]),
        "KF60_BLOWUP_T30": topk(wallets, scores["KF60_BLOWUP"]),
        "KF120_ALL_T30": topk(wallets, scores["KF120_ALL"]),
        "STATIC_BOT500_T30": topk(wallets, static, bot),
        "KF120_ALL_BOT500_T30": topk(wallets, scores["KF120_ALL"], bot),
    }
    legacy_mask = eligible & np.asarray([w not in frozen for w in wallets])
    rosters["LEGACY_STATIC_T30"] = topk(wallets, static, legacy_mask)
    diag: dict[str, object] = {"n_eligible": int(eligible.sum()), "n_bot500": int(bot.sum())}
    for key, values in scores.items():
        common = eligible & np.isfinite(values)
        corr = float(np.corrcoef(_rank(static[common]), _rank(values[common]))[0, 1])
        arm = key + "_T30"
        diag[arm] = {
            "spearman_vs_static": corr,
            "overlap_vs_static": len(set(rosters[arm]) & set(static_top)),
        }
    return rosters, diag


def run() -> dict[str, object]:
    DERIVED.mkdir(parents=True, exist_ok=True)
    con = lake.connect(mem="4GB", threads=2)
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    report: dict[str, object] = {
        "status": "BURNED_PARITY_LOCKED_SELECTOR_DIAGNOSTIC",
        "positive_promotion_eligible": False,
        "method_null_eligible": False,
        "config": {
            "arms": list(ARMS),
            "cap": float(CAP),
            "nd_min": ND_MIN,
            "bot_max": BOT_MAX,
            "half_lives": list(HALF_LIVES),
            "architecture_sha256": _file_sha256(ARCH),
            "code_sha256": _code_sha256(Path(__file__)),
            "dependency_hashes": dependency_hashes(),
            "code_commit": lake.git_describe(),
        },
        "folds": {},
    }
    for fold in FOLDS:
        print(f"[nested selector] {fold}", flush=True)
        months = formation_months(fold)
        ctx = exact_context_paths(months)
        rv, invalid = context_rv_catalog(ctx)
        rvol = lagged_r_vol(months, rv)
        path = cache_panel(con, fold, ctx)
        panel = load_panel(path, fold, rvol)
        ref = reference_rows(con, fold)
        parity = _align_reference(panel, ref)
        parity.update(align_reference_scores(panel, reference_scores(con, fold)))
        rosters, diag = score_fold(panel, frozen)
        published = _select_top100(con, fold, frozen)[:TOP_K]
        if rosters["LEGACY_STATIC_T30"] != published:
            raise RuntimeError(f"fold {fold}: legacy roster parity failed")
        if any(len(v) != TOP_K or len(set(v)) != TOP_K for v in rosters.values()):
            raise RuntimeError(f"fold {fold}: exact top30 invariant")
        report["folds"][str(fold)] = {
            "panel_path": str(path),
            "panel_meta_sha256": _file_sha256(path.with_suffix(".meta.json")),
            "panel_source_lineage": json.loads(path.with_suffix(".meta.json").read_text())[
                "source_lineage"
            ],
            "panel_context_sha256": json.loads(path.with_suffix(".meta.json").read_text())[
                "context_sha256"
            ],
            "reference_path": str(reference_path(con, fold)),
            "reference_meta_sha256": _file_sha256(
                reference_path(con, fold).with_suffix(".meta.json")
            ),
            "panel_parity": parity,
            "invalid_context_days": {str(k): v for k, v in invalid.items()},
            "rosters": rosters,
            "diagnostics": diag,
            "slow_filter_warning": diag["KF120_T30"]["overlap_vs_static"] < 15,
            "slow_all_filter_warning": diag["KF120_ALL_T30"]["overlap_vs_static"] < 15,
        }
    report["rosters_sha256"] = _sha256_json({f: v["rosters"] for f, v in report["folds"].items()})
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=1, sort_keys=True))
    tmp.replace(OUT)
    con.close()
    return report


if __name__ == "__main__":
    run()
