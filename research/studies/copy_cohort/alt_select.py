"""Alt-universe cohort selection — Arms C/T/P per ALT_UNIVERSE_PREREG.md (+ addendum), from the lake.

Per fold T (202511..202606): formation = 3 calendar months < T from lake wallet_coin_day. Per wallet:
capped daily pnl series (CAP=100k across ALL coins), nd, mean, sd, t-stat, EB z / P_informed (two-groups
on the full eligible pool). Cohorts: top-30 per arm (C=level, T=t-stat, P=posterior). Scale = median
formation flat-open notional (lake open_entries), LARGE = top half within fold per arm.

Outputs:
  data/derived/copy_cohort/alt_universe_cohorts.json      cohorts + scale + provenance
  data/derived/copy_cohort/informedness/fold=T/pool.parquet   per-wallet score table (the deliverable)

    python -m research.studies.copy_cohort.alt_select            # all folds (frozen research run)
    python -m research.studies.copy_cohort.alt_select 202511     # one fold (frozen research run)
    python -m research.studies.copy_cohort.alt_select --month 202607   # ROLLING mode (prospective)

Rolling mode (`--month YYYYMM`): scores an ARBITRARY month M with formation = the 3 calendar months
strictly before M (calendar arithmetic, not the research MONTHS list). Refuses M if the lake lacks
wallet_coin_day partitions for any formation month. Writes informedness/fold=M/pool.parquet plus a
merge-don't-truncate update of data/derived/copy_cohort/rolling_cohorts.json (the frozen
alt_universe_cohorts.json is NEVER touched). Same frozen method params; code_commit stamped via
lake.git_describe(). Prospective only — historical research folds are not re-run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake
from .informed import t_to_z, two_groups

CAP = 100_000.0
ND_MIN = 15
TOP_K = 30
OUT_JSON = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_universe_cohorts.json"
ROLLING_JSON = REPO_ROOT / "data" / "derived" / "copy_cohort" / "rolling_cohorts.json"
INF_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "informedness"
FOLDS = MONTHS[3:]


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=REPO_ROOT).stdout.strip()
    except Exception:
        return "unknown"


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


def _prev_month(m: int) -> int:
    y, mo = divmod(m, 100)
    return (y - 1) * 100 + 12 if mo == 1 else y * 100 + (mo - 1)


def _calendar_formation(month: int) -> list[int]:
    """3 calendar months strictly before `month` (pure calendar arithmetic — rolling mode)."""
    y, mo = divmod(month, 100)
    if not (2000 <= y <= 2100 and 1 <= mo <= 12):
        raise SystemExit(f"bad month {month}: expected YYYYMM")
    out, m = [], month
    for _ in range(3):
        m = _prev_month(m)
        out.append(m)
    return out[::-1]


def _lake_month_days(con, month: int) -> int:
    """Number of wallet_coin_day date= partitions the lake holds for `month`."""
    return con.execute("SELECT count(*) FROM glob(?)", [lake.wcd_month_glob(month)]).fetchone()[0]


def _pool_panel(con, months: list[int]):
    """Per-wallet formation stats from lake wallet_coin_day (capped daily pnl across ALL coins)."""
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in months)
    d = con.execute(f"""
        WITH wd AS (
          SELECT wallet, day,
                 SUM(CAST(pnl AS DOUBLE)) - SUM(CAST(fee AS DOUBLE)) AS day_pnl,
                 SUM(CAST(notional AS DOUBLE))                       AS day_notional,
                 SUM(n_fills) AS n_fills, SUM(n_taker) AS n_taker,
                 SUM(n_open_flat) AS n_open_flat, SUM(n_liq) AS n_liq
          FROM read_parquet([{globs}])
          GROUP BY wallet, day
        ),
        capd AS (
          SELECT wallet, day,
                 day_pnl * LEAST(1.0, {CAP} / GREATEST(day_notional, 1e-12)) AS cap_pnl,
                 n_fills, n_taker, n_open_flat, n_liq
          FROM wd
        )
        SELECT wallet,
               count(*)                        AS nd,
               avg(cap_pnl)                    AS mu,
               stddev_samp(cap_pnl)            AS sd,
               sum(cap_pnl)                    AS tot_cap,
               sum(n_fills) AS n_fills, sum(n_taker) AS n_taker,
               sum(n_open_flat) AS n_open_flat, sum(n_liq) AS n_liq
        FROM capd GROUP BY wallet
        HAVING count(*) >= {ND_MIN} AND stddev_samp(cap_pnl) > 0
    """).fetchnumpy()
    return d


def _scale_of(con, wallets: list[str], months: list[int]) -> dict[str, float]:
    """Median formation flat-open notional per wallet (lake open_entries)."""
    if not wallets:
        return {}
    globs = ",".join(f"'{lake.ope_month_glob(m)}'" for m in months)
    con.execute("CREATE OR REPLACE TEMP TABLE sel AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets)])
    rows = con.execute(f"""
        SELECT o.wallet, median(CAST(o.notl AS DOUBLE)) AS med_notl
        FROM read_parquet([{globs}]) o JOIN sel USING (wallet)
        GROUP BY o.wallet""").fetchall()
    return {w: float(m) for w, m in rows}


def build_fold(con, fold: int, months: list[int] | None = None) -> dict:
    if months is None:
        months = _formation_months(fold)
    d = _pool_panel(con, months)
    w = d["wallet"].astype(str)
    nd = np.asarray(d["nd"], float)
    mu = np.asarray(d["mu"], float)
    sd = np.asarray(d["sd"], float)
    metric_c = np.asarray(d["tot_cap"], float) / nd
    t = mu / (sd / np.sqrt(nd))
    z = t_to_z(t, nd - 1)
    tg = two_groups(z)
    p_inf = tg["p_informed"]

    def top(key, tie=None):
        # AUDIT FIX 2026-07-17 (MED): total deterministic ordering for ALL arms — primary
        # key desc, then tie desc, then wallet asc as the final tie-break (previously
        # argsort left key-ties in arbitrary order). PROSPECTIVE ONLY: the frozen
        # alt_universe_cohorts.json was generated pre-fix and is NOT re-run; this governs
        # future selections.
        keys = (w,) + ((-tie,) if tie is not None else ()) + (-key,)
        return np.lexsort(keys)[:TOP_K]

    arms = {"C": top(metric_c), "T": top(t), "P": top(p_inf, tie=t)}
    sel_wallets = sorted({w[i] for idx in arms.values() for i in idx})
    scale = _scale_of(con, sel_wallets, months)

    # per-fold informedness table (FULL eligible pool — the reusable deliverable)
    INF_DIR.mkdir(parents=True, exist_ok=True)
    part = INF_DIR / f"fold={fold}"
    part.mkdir(exist_ok=True)
    con.execute("CREATE OR REPLACE TEMP TABLE inf AS SELECT * FROM (SELECT "
                "UNNEST(?) AS wallet, UNNEST(?) AS nd, UNNEST(?) AS mu_capday, UNNEST(?) AS sd_capday, "
                "UNNEST(?) AS metric_capday, UNNEST(?) AS t_stat, UNNEST(?) AS z, UNNEST(?) AS p_informed)",
                [w.tolist(), nd.tolist(), mu.tolist(), sd.tolist(),
                 metric_c.tolist(), t.tolist(), z.tolist(), p_inf.tolist()])
    con.execute(f"COPY inf TO '{(part / 'pool.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)")

    out = {"formation_months": months, "pool_size": int(w.size),
           "null_fit": {"mu0": tg["mu0"], "sigma0": tg["sigma0"], "pi0": tg["pi0"]},
           "arms": {}}
    for arm, idx in arms.items():
        members = {}
        med = [scale.get(w[i]) for i in idx]
        known = sorted([m for m in med if m is not None])
        thr = known[len(known) // 2] if known else None      # top half = LARGE
        for j, i in enumerate(idx):
            m = med[j]
            members[w[i]] = {
                "metric_capday": float(metric_c[i]), "t": float(t[i]), "z": float(z[i]),
                "p_informed": float(p_inf[i]), "nd": int(nd[i]),
                "scale_med_notl": (float(m) if m is not None else None),
                "large": (bool(m >= thr) if (m is not None and thr is not None) else None),
            }
        out["arms"][arm] = {"members": members, "scale_threshold": thr}
    return out


def run_rolling(month: int) -> int:
    """Rolling scoring for one arbitrary month (prospective operation, not the research folds)."""
    months = _calendar_formation(month)
    con = lake.connect()
    missing = [m for m in months if _lake_month_days(con, m) == 0]
    if missing:
        print(f"[alt_select --month {month}] REFUSED: lake has no wallet_coin_day partitions for "
              f"formation month(s) {missing} (formation={months})", file=sys.stderr)
        return 1
    print(f"[alt_select] ROLLING month {month}  formation={months}", flush=True)
    fold = build_fold(con, month, months=months)
    fold["code_commit"] = lake.git_describe()
    fold["mode"] = "rolling"

    # merge-don't-truncate (audit F2): load existing, update this fold only, rewrite
    if ROLLING_JSON.exists():
        rep = json.loads(ROLLING_JSON.read_text())
    else:
        rep = {"config": {"cap": CAP, "nd_min": ND_MIN, "top_k": TOP_K,
                          "prereg": "ALT_UNIVERSE_PREREG.md (+addendum)",
                          "mode": "rolling"},
               "folds": {}}
    rep["folds"][str(month)] = fold
    ROLLING_JSON.write_text(json.dumps(rep, indent=1, default=str))

    nf = fold["null_fit"]
    print(f"  pool={fold['pool_size']:,}  null(mu0={nf['mu0']:+.2f}, s0={nf['sigma0']:.2f}, "
          f"pi0={nf['pi0']:.3f})", flush=True)
    for arm in ("C", "T", "P"):
        mem = fold["arms"][arm]["members"]
        ov = {"C", "T", "P"} - {arm}
        print(f"  arm {arm}: top{TOP_K}; overlap " +
              ", ".join(f"{o}={len(set(mem) & set(fold['arms'][o]['members']))}" for o in sorted(ov)),
              flush=True)
    print(f"-> {ROLLING_JSON}")
    print(f"-> {INF_DIR / f'fold={month}' / 'pool.parquet'}")
    return 0


def main(argv):
    if argv and argv[0] == "--month":
        if len(argv) != 2:
            print("usage: alt_select --month YYYYMM", file=sys.stderr)
            return 2
        return run_rolling(int(argv[1]))
    folds = [int(a) for a in argv] or FOLDS
    con = lake.connect()
    rep = {"config": {"cap": CAP, "nd_min": ND_MIN, "top_k": TOP_K,
                      "prereg": "ALT_UNIVERSE_PREREG.md (+addendum)",
                      "code_commit": _git_commit()},
           "folds": {}}
    for fold in folds:
        print(f"[alt_select] fold {fold} ...", flush=True)
        rep["folds"][str(fold)] = build_fold(con, fold)
        f = rep["folds"][str(fold)]
        print(f"  pool={f['pool_size']:,}  null(mu0={f['null_fit']['mu0']:+.2f}, "
              f"s0={f['null_fit']['sigma0']:.2f}, pi0={f['null_fit']['pi0']:.3f})", flush=True)
        for arm in ("C", "T", "P"):
            mem = f["arms"][arm]["members"]
            ov = {"C", "T", "P"} - {arm}
            print(f"  arm {arm}: top{TOP_K}; overlap " +
                  ", ".join(f"{o}={len(set(mem) & set(f['arms'][o]['members']))}" for o in sorted(ov)),
                  flush=True)
    OUT_JSON.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
