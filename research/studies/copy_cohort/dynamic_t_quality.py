"""Post-hoc burned-fold dynamic t-quality selectors.

Implements ``DYNAMIC_T_QUALITY_ARCH.md``.  The primary changes only calendar time
weights on a common rankable pool; shock, HAC, and copyability variants are explicit
secondaries.  Output is diagnostic, never forward evidence.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS

from . import lake
from .alt_fresh_validate import MAJORS
from .filtered_quality import _code_sha256, _sha256_json
from .majors_native import FROZEN as PUBLISHED_FROZEN
from .majors_native import _select_top100 as _published_top100

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort" / "dynamic_t_quality"
PANELS = DERIVED / "panels"
OUT = DERIVED / "rosters.json"

FOLDS = tuple(MONTHS[3:])
CAP_USD = 100_000.0
ND_MIN = 15
RECENCY_DAYS = 30
TOP_K = 30
HALF_LIFE_DAYS = 21.0
N_EFF_MIN = 8.0
HAC_LAGS = 7
BLOWUP_USD = 10_000.0
QUARANTINE_DAYS = 30
COPY_MIN_OPENS = 5
BOT_FILLS_PER_DAY = 1_000.0
TAKER_SHARE_MIN = 0.10


@dataclass(frozen=True)
class StudyProfile:
    experiment_id: str
    half_life_days: float
    architecture: str
    derived: Path

    @property
    def panels(self) -> Path:
        return self.derived / "panels"

    @property
    def rosters(self) -> Path:
        return self.derived / "rosters.json"


HL21_PROFILE = StudyProfile(
    "hl21", 21.0, "DYNAMIC_T_QUALITY_ARCH.md", DERIVED,
)
HL60_PROFILE = StudyProfile(
    "hl60", 60.0, "LONG_HALF_LIFE_ARCH.md",
    REPO_ROOT / "data" / "derived" / "copy_cohort" / "dynamic_t_quality_hl60",
)


@dataclass(frozen=True)
class Panel:
    wallet: np.ndarray
    day: np.ndarray
    ordinal: np.ndarray
    x: np.ndarray
    n_liq: np.ndarray
    n_open_flat: np.ndarray
    fills_per_day: np.ndarray
    taker_share: np.ndarray
    start_ordinal: int
    end_ordinal: int


def formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return list(MONTHS[i - 3:i])


def month_start(month: int) -> date:
    return date(month // 100, month % 100, 1)


def day_to_ordinal(day: int) -> int:
    s = str(int(day))
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])).toordinal()


def normalized_x(net_pnl: Decimal, day_notional: Decimal) -> float:
    """Form the exact rational normalization in Decimal, then enter float scoring."""
    if day_notional <= 0:
        return math.nan
    scale = min(Decimal(1), Decimal(100_000) / day_notional)
    return float(net_pnl * scale)


def weighted_stats(x: np.ndarray, age_days: np.ndarray, *,
                   half_life: float) -> tuple[float, float, float]:
    """Reliability-weight mean, unbiased variance, and Kish effective N."""
    x = np.asarray(x, float)
    age = np.asarray(age_days, float)
    if x.size < 2 or x.shape != age.shape or not np.isfinite(x).all():
        return math.nan, math.nan, math.nan
    w = np.power(2.0, -age / half_life)
    sw = float(w.sum())
    sw2 = float(w @ w)
    denom = sw - sw2 / sw if sw > 0 else math.nan
    if not np.isfinite(denom) or denom <= 0:
        return math.nan, math.nan, math.nan
    mu = float(w @ x / sw)
    var = float(w @ ((x - mu) ** 2) / denom)
    neff = sw * sw / sw2
    return mu, var, neff


def ordinary_t(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    if x.size < 2:
        return math.nan
    sd = float(np.std(x, ddof=1))
    return float(np.mean(x) / (sd / math.sqrt(x.size))) if sd > 0 else math.nan


def ew_t(x: np.ndarray, ordinal: np.ndarray, end_ordinal: int, *,
         half_life: float) -> tuple[float, float]:
    mu, var, neff = weighted_stats(
        x, end_ordinal - np.asarray(ordinal, np.int64), half_life=half_life
    )
    if not np.isfinite(var) or var <= 0 or not np.isfinite(neff) or neff < N_EFF_MIN:
        return math.nan, neff
    return float(mu / math.sqrt(var / neff)), neff


def hac_t(x: np.ndarray, ordinal: np.ndarray, end_ordinal: int,
          *, weighted: bool, half_life: float) -> float:
    """Seven-calendar-day Bartlett HAC t-like score on active-day observations."""
    x = np.asarray(x, float)
    ordinal = np.asarray(ordinal, np.int64)
    if x.size < 2:
        return math.nan
    w = (np.power(2.0, -(end_ordinal - ordinal) / half_life)
         if weighted else np.ones(x.size))
    sw = float(w.sum())
    mu = float(w @ x / sw)
    grid = np.zeros(end_ordinal - int(ordinal.min()) + 1)
    grid[ordinal - int(ordinal.min())] = w * (x - mu) / sw
    vm = float(grid @ grid)
    for lag in range(1, HAC_LAGS + 1):
        vm += 2.0 * (1.0 - lag / (HAC_LAGS + 1.0)) * float(grid[lag:] @ grid[:-lag])
    return float(mu / math.sqrt(vm)) if np.isfinite(vm) and vm > 0 else math.nan


def latest_shock_index(x: np.ndarray, n_liq: np.ndarray, ordinal: np.ndarray) -> int | None:
    shock = (np.asarray(n_liq, float) > 0) | (np.asarray(x, float) <= -BLOWUP_USD)
    ii = np.flatnonzero(shock)
    if ii.size == 0:
        return None
    return int(ii[np.argmax(np.asarray(ordinal)[ii])])


def topk(wallets: np.ndarray, score: np.ndarray, k: int = TOP_K) -> list[str]:
    good = np.isfinite(score)
    w, s = np.asarray(wallets, str)[good], np.asarray(score, float)[good]
    if w.size < k:
        raise RuntimeError(f"need exactly {k} finite scores; found {w.size}")
    order = np.lexsort((w, -s))
    out = w[order[:k]].tolist()
    if len(out) != k or len(set(out)) != k:
        raise RuntimeError("exact unique top-k invariant failed")
    return out


def _cache_spec(con, fold: int, *, profile: StudyProfile) -> dict[str, object]:
    months = formation_months(fold)
    return {
        "cache_schema": "dynamic-t-panel-v3",
        "experiment_id": profile.experiment_id,
        "half_life_days": profile.half_life_days,
        "architecture": profile.architecture,
        "fold": fold,
        "formation_months": months,
        "source_lineage": lake.validated_lineage(
            con, months, ("alt_universe_wallet_coin_day",)
        ),
        "code_sha256": _code_sha256(
            Path(__file__), Path(__file__).with_name("filtered_quality.py")
        ),
        "config": {
            "majors": list(MAJORS), "cap_usd": CAP_USD,
            "money_type": "DECIMAL(38,12)",
            "fee_formula": "sum(pnl)-sum(fee)-sum(coalesce(builder_fee,0))",
        },
    }


def cache_panel(con, fold: int, *, profile: StudyProfile) -> Path:
    profile.panels.mkdir(parents=True, exist_ok=True)
    path = profile.panels / f"daily_{fold}.parquet"
    meta = profile.panels / f"daily_{fold}.meta.json"
    spec = _cache_spec(con, fold, profile=profile)
    if path.exists() and meta.exists() and json.loads(meta.read_text()) == spec:
        return path
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in formation_months(fold))
    majors = ",".join(f"'{c}'" for c in MAJORS)
    tmp = path.with_suffix(".parquet.tmp")
    con.execute(f"""COPY (
      WITH allact AS (
        SELECT wallet, SUM(n_fills)::DOUBLE AS n_fills_all,
               SUM(n_taker)::DOUBLE AS n_taker_all,
               COUNT(DISTINCT day)::DOUBLE AS n_days_all
        FROM read_parquet([{globs}]) GROUP BY wallet
      ), md AS (
        SELECT wallet, day,
          SUM(CAST(pnl AS DECIMAL(38,12)))
            - SUM(CAST(fee AS DECIMAL(38,12)))
            - SUM(COALESCE(CAST(builder_fee AS DECIMAL(38,12)), 0)) AS net_pnl,
          SUM(CAST(notional AS DECIMAL(38,12))) AS day_notional,
          SUM(n_liq)::BIGINT AS n_liq,
          SUM(n_open_flat)::BIGINT AS n_open_flat
        FROM read_parquet([{globs}]) WHERE coin IN ({majors})
        GROUP BY wallet, day
      )
      SELECT md.wallet, md.day, md.net_pnl, md.day_notional,
        md.n_liq, md.n_open_flat,
        allact.n_fills_all/NULLIF(allact.n_days_all,0) AS fills_per_day,
        allact.n_taker_all/NULLIF(allact.n_fills_all,0) AS taker_share
      FROM md JOIN allact USING(wallet) WHERE md.day_notional > 0
      ORDER BY md.wallet, md.day
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    post = lake.validated_lineage(
        con, formation_months(fold), ("alt_universe_wallet_coin_day",)
    )
    if post["sha256"] != spec["source_lineage"]["sha256"]:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"fold {fold}: formation objects mutated during materialization")
    tmp.replace(path)
    mtmp = meta.with_suffix(".json.tmp")
    mtmp.write_text(json.dumps(spec, indent=1, sort_keys=True))
    mtmp.replace(meta)
    return path


def load_panel(path: Path, fold: int) -> Panel:
    d = pq.read_table(path).to_pydict()
    wallet = np.asarray(d["wallet"], str)
    day = np.asarray(d["day"], np.int64)
    x = np.array([normalized_x(p, n)
                  for p, n in zip(d["net_pnl"], d["day_notional"], strict=True)], float)
    n_liq = np.asarray(d["n_liq"], float)
    n_open = np.asarray(d["n_open_flat"], float)
    fpd = np.asarray(d["fills_per_day"], float)
    taker = np.asarray(d["taker_share"], float)
    finite = np.isfinite(x)
    start = month_start(formation_months(fold)[0]).toordinal()
    end = month_start(fold).toordinal() - 1
    return Panel(wallet[finite], day[finite],
                 np.array([day_to_ordinal(v) for v in day[finite]], np.int64),
                 x[finite], n_liq[finite], n_open[finite], fpd[finite], taker[finite],
                 start, end)


def score_panel(panel: Panel, *, half_life_days: float) -> tuple[
    dict[str, tuple[np.ndarray, np.ndarray]], dict[str, object]
]:
    wallets, starts, counts = np.unique(panel.wallet, return_index=True, return_counts=True)
    static = np.full(wallets.size, np.nan)
    ew = np.full(wallets.size, np.nan)
    neff = np.full(wallets.size, np.nan)
    hs = np.full(wallets.size, np.nan)
    hew = np.full(wallets.size, np.nan)
    base = np.zeros(wallets.size, bool)
    shock_ew = np.full(wallets.size, np.nan)
    copy_static = np.full(wallets.size, np.nan)
    copy_ew = np.full(wallets.size, np.nan)
    shock_valid = np.zeros(wallets.size, bool)
    copy_valid = np.zeros(wallets.size, bool)
    literal_valid = np.zeros(wallets.size, bool)

    for j, w in enumerate(wallets):
        ii = slice(int(starts[j]), int(starts[j] + counts[j]))
        if not np.all(panel.wallet[ii] == w):
            raise RuntimeError("panel must be sorted by wallet")
        xx, oo = panel.x[ii], panel.ordinal[ii]
        static[j] = ordinary_t(xx)
        ew[j], neff[j] = ew_t(
            xx, oo, panel.end_ordinal, half_life=half_life_days
        )
        literal_valid[j] = xx.size >= ND_MIN and np.isfinite(static[j])
        base[j] = (xx.size >= ND_MIN and np.isfinite(static[j]) and np.isfinite(ew[j])
                   and oo.max() >= panel.end_ordinal - RECENCY_DAYS + 1)
        if base[j]:
            hs[j] = hac_t(
                xx, oo, panel.end_ordinal, weighted=False,
                half_life=half_life_days,
            )
            hew[j] = hac_t(
                xx, oo, panel.end_ordinal, weighted=True,
                half_life=half_life_days,
            )

        si = latest_shock_index(xx, panel.n_liq[ii], oo)
        keep = np.ones(xx.size, bool)
        quarantined = False
        if si is not None:
            shock_ord = int(oo[si])
            keep = oo >= shock_ord
            quarantined = panel.end_ordinal + 1 - shock_ord <= QUARANTINE_DAYS
        xk, ok = xx[keep], oo[keep]
        st = ordinary_t(xk)
        et, _ = ew_t(xk, ok, panel.end_ordinal, half_life=half_life_days)
        if si is None:
            valid = bool(base[j])
        else:
            valid = (not quarantined and xk.size >= 8 and np.isfinite(st)
                     and np.isfinite(et) and ok.max() >= panel.end_ordinal - RECENCY_DAYS + 1)
        if valid:
            shock_valid[j] = True
            shock_ew[j] = et

        opens = float(panel.n_open_flat[ii].sum())
        fpd = float(panel.fills_per_day[int(starts[j])])
        tk = float(panel.taker_share[int(starts[j])])
        copy_ok = (valid and opens >= COPY_MIN_OPENS and np.isfinite(fpd)
                   and fpd <= BOT_FILLS_PER_DAY and np.isfinite(tk) and tk >= TAKER_SHARE_MIN)
        if copy_ok:
            copy_valid[j] = True
            copy_static[j], copy_ew[j] = st, et

    common = base
    if common.sum() < TOP_K:
        raise RuntimeError(f"common primary pool only {common.sum()}")
    hac_common = common & np.isfinite(hs) & np.isfinite(hew)
    if hac_common.sum() < TOP_K:
        raise RuntimeError(f"common HAC pool only {hac_common.sum()}")
    if shock_valid.sum() < TOP_K or copy_valid.sum() < TOP_K:
        raise RuntimeError(
            f"short secondary pools shock={shock_valid.sum()} copy={copy_valid.sum()}"
        )

    unrestricted = literal_valid
    scores = {
        "TSTAT30": (wallets[unrestricted], static[unrestricted]),
        "TSTAT_COMMON30": (wallets[common], static[common]),
        "EW_T30": (wallets[common], ew[common]),
        "HAC_T30": (wallets[hac_common], hs[hac_common]),
        "EW_HAC_T30": (wallets[hac_common], hew[hac_common]),
        "EW_T_SHOCK30": (wallets[shock_valid], shock_ew[shock_valid]),
        "TSTAT_COPY30": (wallets[copy_valid], copy_static[copy_valid]),
        "EW_T_COPY30": (wallets[copy_valid], copy_ew[copy_valid]),
    }
    diag = {
        "n_wallets": int(wallets.size), "n_unrestricted": int(unrestricted.sum()),
        "n_common": int(common.sum()), "n_hac_common": int(hac_common.sum()),
        "n_shock_valid": int(shock_valid.sum()), "n_copy_valid": int(copy_valid.sum()),
        "common_overlap_hac": int(np.sum(common & hac_common)),
        "n_eff_common_median": float(np.median(neff[common])),
    }
    return scores, diag


def run(*, profile: StudyProfile) -> dict:
    profile.derived.mkdir(parents=True, exist_ok=True)
    con = lake.connect()
    published_frozen = set(json.loads(PUBLISHED_FROZEN.read_text())["distinct_wallets"])
    rep = {
        "status": "POST-HOC BURNED DIAGNOSTIC; NOT FORWARD EVIDENCE",
        "architecture": profile.architecture,
        "config": {
            "experiment_id": profile.experiment_id,
            "folds": list(FOLDS), "cap_usd": CAP_USD, "nd_min": ND_MIN,
            "half_life_days": profile.half_life_days, "n_eff_min": N_EFF_MIN,
            "hac_lags": HAC_LAGS, "blowup_usd": BLOWUP_USD,
            "quarantine_days": QUARANTINE_DAYS, "copy_min_opens": COPY_MIN_OPENS,
            "bot_fills_per_day": BOT_FILLS_PER_DAY, "taker_share_min": TAKER_SHARE_MIN,
            "code_commit": lake.git_describe(),
            "code_sha256": _code_sha256(
                Path(__file__), Path(__file__).with_name("filtered_quality.py")
            ),
        },
        "folds": {},
    }
    for fold in FOLDS:
        print(f"[dynamic-t selector] fold {fold}", flush=True)
        panel_path = cache_panel(con, fold, profile=profile)
        panel_spec = json.loads(
            (profile.panels / f"daily_{fold}.meta.json").read_text()
        )
        panel = load_panel(panel_path, fold)
        scores, diag = score_panel(panel, half_life_days=profile.half_life_days)
        rosters = {name: topk(*value) for name, value in scores.items()}
        published = _published_top100(con, fold, published_frozen)[:TOP_K]
        if len(published) != TOP_K or len(set(published)) != TOP_K:
            raise RuntimeError(f"fold {fold}: invalid published roster")
        rosters["PUBLISHED_MAJORS30"] = published
        rep["folds"][str(fold)] = {
            **diag, "n_panel_obs": int(panel.x.size), "rosters": rosters,
            "panel_cache_spec_sha256": _sha256_json(panel_spec),
            "formation_source_lineage_sha256": panel_spec["source_lineage"]["sha256"],
            "overlap": {f"EW_x_{a}": len(set(rosters["EW_T30"]) & set(ws))
                        for a, ws in rosters.items() if a != "EW_T30"},
        }
        print(f"  {diag} overlaps={rep['folds'][str(fold)]['overlap']}", flush=True)
    con.close()
    tmp = profile.rosters.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=1))
    tmp.replace(profile.rosters)
    print(f"-> {profile.rosters}")
    return rep


if __name__ == "__main__":
    raise SystemExit(
        "Select a frozen profile explicitly; use `python -m "
        "research.studies.copy_cohort.dynamic_t_hl60`."
    )
