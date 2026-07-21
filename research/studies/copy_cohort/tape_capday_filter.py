"""TAPE CAPDAY + FILTER GRID — majors-tape recreation of the capday top-30 copy strat.

Architecture: TAPE_CAPDAY_FILTER_ARCH.md v1.1 (post 4-agent audit; tags S*/C*/FW*/D* refer to it).
BURNED folds 202511-202606 — candidate-ranking/descriptive only. Data: local node_fills majors tape
+ asset_ctx ONLY (no lake / no Postgres; importing `.lake` here is forbidden — FW1).

    python -m research.studies.copy_cohort.tape_capday_filter
"""
from __future__ import annotations

import glob as globmod
import hashlib
import json
import subprocess
from pathlib import Path

import duckdb
import numpy as np

from research.data import schema
from research.lib.cv import MONTHS, as_of_cutoff_ms
from research.lib.stats import t_ppf

assert "lake" not in dir(), "FW1: lake import forbidden in this module"

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA = REPO_ROOT / "data"
FILLS_GLOB = str(DATA / "raw" / "fills" / "month=*" / "day=*" / "*.parquet")   # leaf-only (D7)
CTX_DIR = DATA / "raw" / "asset_ctx"
DERIVED = DATA / "derived" / "copy_cohort"
CACHE = DERIVED / "tape_capday_filter"
OUT = DERIVED / "tape_capday_filter_report.json"
FROZEN133 = DERIVED / "frozen_alt_universe.json"

MAJORS = schema.MAJORS                          # BTC/ETH/SOL/HYPE
FOLDS = tuple(MONTHS[3:])                        # 202511..202606
CAP = 100_000.0
ND_MIN = 15
NOTL_MIN = 250.0
K = 30
HOURS = (1, 4, 8, 24)
PRIMARY_H = 8
STALE_MS = 90_000
RT_COST_BP = 2.6
RT_STRESS_BP = 5.5
CLIP_USD = 1_000.0
N_BOOT = 4000
SEED = 20260720
CARE_BP = 5.0
# arm order is frozen (seed indexing): F0..F5, FALL, FRTS
ARMS = ("F0", "F1_BOT", "F2_MAKER", "F3_DUST", "F4_LIQ", "F5_1DAY", "FALL", "FRTS")
TH = {"bot_fills_per_day": 500.0, "maker_taker_share": 0.10, "dust_med_notl": 250.0,
      "oneday_conc": 0.50}

CONFIG = {
    "arch": "TAPE_CAPDAY_FILTER_ARCH.md v1.1", "stamp": "BURNED candidate-ranking/descriptive",
    "majors": list(MAJORS), "folds": list(FOLDS), "cap": CAP, "nd_min": ND_MIN, "k": K,
    "notl_min": NOTL_MIN, "hours": list(HOURS), "primary": "FALL@8h (repo-standard horizon, "
    "itself burned-fold-selected — S4)", "thresholds": TH, "stale_ms": STALE_MS,
    "rt_cost_bp": RT_COST_BP, "rt_stress_bp": RT_STRESS_BP, "clip_usd": CLIP_USD,
    "n_boot": N_BOOT, "seed": SEED, "care_bp": CARE_BP,
    "entry_rule": "order (wallet,coin,oid) whose min-(ts,event_index) fill is flat "
                  "(DECIMAL(38,18)=0), crossed, dir Open*, unflagged; notional=sum abs(sz)*px over "
                  "same-dir fills of the oid; NULL-oid -> (block_number,event_index) single-fill key",
    "f3_no_formation_open": "FAIL (no flat opens -> cannot verify dust; declared, not tuned)",
    "formation_flags": "includes zhash/liq/vault-flagged fills EXCEPT dir='Net Child Vaults' (C5/D5)",
    "fills_schema_version": schema.SCHEMA_VERSION,
    "ctx_limits": "ctx ends 2026-06-29 (fold 202606 right-censored); 20260530 partial (D1/FW2)",
}


def _git() -> str:
    try:
        return subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True,
                              text=True, cwd=REPO_ROOT).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _ctx_parts(month: int) -> list[str]:
    y, mm = divmod(month, 100)
    nxt = (y + 1) * 100 + 1 if mm == 12 else month + 1
    parts = globmod.glob(str(CTX_DIR / f"month={month}" / "day=*" / "ctx.parquet"))
    parts += [p for p in globmod.glob(str(CTX_DIR / f"month={nxt}" / "day=*" / "ctx.parquet"))
              if int(p.split("day=")[1][:8]) <= nxt * 100 + 3]
    return sorted(parts)


def _sha() -> str:
    payload = dict(CONFIG)
    payload["ctx_parts_per_fold"] = {str(f): len(_ctx_parts(f)) for f in FOLDS}   # D4
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _month_start_ms(month: int) -> int:
    y, mm = divmod(month, 100)
    prev = (y - 1) * 100 + 12 if mm == 1 else month - 1
    return as_of_cutoff_ms(prev)


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    # RAM safety (8 GB machine): hard cap + disk spill + no order preservation
    spill = CACHE / "_duckdb_spill"
    spill.mkdir(parents=True, exist_ok=True)
    con.execute("SET memory_limit='4GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=4")
    con.execute(f"SET temp_directory='{spill.as_posix()}'")
    con.execute("SET max_temp_directory_size='4GiB'")
    con.execute(f"""CREATE OR REPLACE VIEW f AS
        SELECT * FROM read_parquet('{FILLS_GLOB}', hive_partitioning=true, union_by_name=true)""")
    return con


# ---- entry CTE (shared: formation F3 feature + test-month book) — §4 rule -----------------------
def _entries_sql(months: list[int], t0: int, t1: int, wallet_pred: str = "TRUE") -> str:
    majors = ",".join(f"'{m}'" for m in MAJORS)
    mlist = ",".join(str(m) for m in months)
    return f"""
    WITH raw AS NOT MATERIALIZED (
      SELECT wallet, coin, ts, event_index, dir, oid,
             TRY_CAST(px AS DOUBLE) * abs(TRY_CAST(sz AS DOUBLE)) AS notl,
             (crossed AND TRY_CAST(start_position AS DECIMAL(38,18)) = 0
              AND dir IN ('Open Long', 'Open Short')
              AND NOT (({schema.ZHASH_SQL}) OR ({schema.LIQ_ORIGIN_SQL}) OR ({schema.VAULT_SQL}))
             ) AS head_ok
      FROM f
      WHERE month IN ({mlist}) AND coin IN ({majors}) AND ts >= {t0} AND ts < {t1}
        AND ({wallet_pred})
    ),
    -- DISK/RAM safety (8GB RAM, ~1GB free disk — no spill allowed): aggregate ONLY fills that
    -- belong to orders with a flat-open taker fill (small set), never the whole tape.
    head_oids AS (
      SELECT DISTINCT wallet, coin, oid FROM raw WHERE head_ok AND oid IS NOT NULL
    ),
    cand AS NOT MATERIALIZED (
      SELECT r.* FROM raw r JOIN head_oids USING (wallet, coin, oid)
    ),
    g1 AS (
      SELECT wallet, coin, oid,
             arg_min(dir, struct_pack(t := ts, e := event_index)) AS dir0,
             arg_min(head_ok, struct_pack(t := ts, e := event_index)) AS first_is_head,
             min(ts) AS ts, COUNT(*) AS nf_all
      FROM cand GROUP BY 1, 2, 3
    ),
    g2 AS (
      SELECT wallet, coin, oid, dir, SUM(notl) AS notl, COUNT(*) AS nf
      FROM cand GROUP BY 1, 2, 3, 4
    ),
    oid_entries AS (
      SELECT g1.wallet, g1.coin, g1.ts,
             CASE WHEN g1.dir0 = 'Open Long' THEN 1 ELSE -1 END AS dir_sign,
             FALSE AS null_oid, g2.notl AS notional, g1.nf_all - g2.nf AS n_mixed_dir_fills
      FROM g1 JOIN g2 ON g1.wallet = g2.wallet AND g1.coin = g2.coin
                     AND g1.oid = g2.oid AND g2.dir = g1.dir0
      WHERE g1.first_is_head
    ),
    nulloid_entries AS (          -- NULL-oid head fills = single-fill entries (D2 fallback)
      SELECT wallet, coin, ts,
             CASE WHEN dir = 'Open Long' THEN 1 ELSE -1 END AS dir_sign,
             TRUE AS null_oid, notl AS notional, 0 AS n_mixed_dir_fills
      FROM raw WHERE head_ok AND oid IS NULL
    )
    SELECT * FROM oid_entries UNION ALL SELECT * FROM nulloid_entries"""


def _formation_features(con, fold: int, sha: str) -> Path:
    p = CACHE / f"feat_{fold}_{sha}.parquet"
    if p.exists():
        return p
    fm = _formation_months(fold)
    t0, t1 = _month_start_ms(fm[0]), _month_start_ms(fold)          # ts-based (FW3)
    majors = ",".join(f"'{m}'" for m in MAJORS)
    mlist = ",".join(str(m) for m in fm)
    fd = CACHE / f"featday_{fold}_{sha}.parquet"      # checkpoint: heavy scan survives a crash
    if fd.exists():
        con.execute(f"CREATE OR REPLACE TEMP TABLE feats_t AS "
                    f"SELECT * FROM read_parquet('{fd.as_posix()}')")
    else:
        con.execute(f"""CREATE OR REPLACE TEMP TABLE feats_t AS
      WITH base AS (
        SELECT wallet, day, crossed,
               TRY_CAST(closed_pnl AS DOUBLE) AS pnl, TRY_CAST(fee AS DOUBLE) AS fee,
               TRY_CAST(px AS DOUBLE) * abs(TRY_CAST(sz AS DOUBLE)) AS notl,
               ({schema.LIQ_ORIGIN_SQL}) AS own_liq,
               (fee_token IS NOT NULL AND fee_token <> 'USDC') AS alt_fee,
               abs(TRY_CAST(fee AS DOUBLE)) AS abs_fee
        FROM f
        WHERE month IN ({mlist}) AND coin IN ({majors}) AND ts >= {t0} AND ts < {t1}
          AND NOT ({schema.VAULT_SQL})
      ),
      wd AS (
        SELECT wallet, day,
               SUM(pnl) - SUM(fee) AS day_pnl, SUM(notl) AS day_notl, COUNT(*) AS n_fills,
               SUM(CASE WHEN crossed THEN 1 ELSE 0 END) AS n_taker,
               SUM(CASE WHEN own_liq THEN 1 ELSE 0 END) AS n_own_liq,
               SUM(CASE WHEN alt_fee THEN abs_fee ELSE 0 END) AS alt_fee_abs,
               SUM(abs_fee) AS fee_abs
        FROM base GROUP BY wallet, day
      ),
      capd AS (
        SELECT *, day_pnl * LEAST(1.0, {CAP} / day_notl) AS cap_pnl
        FROM wd WHERE day_notl > 0
      )
      SELECT wallet, COUNT(*) AS nd, SUM(cap_pnl) / COUNT(*) AS metric,
             SUM(n_fills) * 1.0 / COUNT(*) AS fills_per_day,
             SUM(n_taker) * 1.0 / NULLIF(SUM(n_fills), 0) AS taker_share,
             SUM(n_own_liq) AS n_own_liq,
             CASE WHEN SUM(abs(cap_pnl)) > 0
                  THEN MAX(abs(cap_pnl)) / SUM(abs(cap_pnl)) ELSE 0 END AS conc,
             SUM(alt_fee_abs) AS alt_fee_abs, SUM(fee_abs) AS fee_abs
      FROM capd GROUP BY wallet""")
        fdt = fd.with_suffix(".tmp.parquet")
        con.execute(f"COPY feats_t TO '{fdt.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)")
        fdt.rename(fd)
    print(f"  fold {fold}: wallet-day features done", flush=True)
    # F3 feature: entry-grouped formation flat opens, ELIGIBLE wallets only (RAM safety)
    tmp = p.with_suffix(".tmp.parquet")
    con.execute(f"""COPY (
      WITH opens AS (
        SELECT wallet, median(notional) AS med_open_notl, COUNT(*) AS n_open
        FROM ({_entries_sql(fm, t0, t1,
                            f"wallet IN (SELECT wallet FROM feats_t WHERE nd >= {ND_MIN})")})
        GROUP BY wallet
      )
      SELECT feats_t.*, opens.med_open_notl, COALESCE(opens.n_open, 0) AS n_open
      FROM feats_t LEFT JOIN opens USING (wallet)
    ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    tmp.rename(p)                                     # atomic: no half-written cache reads as done
    print(f"  fold {fold}: formation features cached", flush=True)
    return p


def _rosters(featp: Path) -> tuple[dict[str, list[str]], dict]:
    lc = duckdb.connect()
    d = lc.execute(f"""SELECT wallet, nd, metric, fills_per_day, taker_share, n_own_liq, conc,
                       med_open_notl, n_open, alt_fee_abs, fee_abs
                       FROM read_parquet('{featp.as_posix()}') WHERE nd >= {ND_MIN}""").fetchnumpy()
    lc.close()
    w = d["wallet"].astype(str)
    metric = np.asarray(d["metric"], float)
    fee_abs, alt_fee = float(np.nansum(d["fee_abs"])), float(np.nansum(d["alt_fee_abs"]))
    assert fee_abs == 0 or alt_fee / fee_abs <= 1e-3, "non-USDC fee share > 0.1% — resolve first (§2)"
    med = np.asarray(d["med_open_notl"], float)
    passes = {
        "F1_BOT": np.asarray(d["fills_per_day"], float) < TH["bot_fills_per_day"],
        "F2_MAKER": np.nan_to_num(np.asarray(d["taker_share"], float)) >= TH["maker_taker_share"],
        "F3_DUST": np.where(np.isnan(med), False, med >= TH["dust_med_notl"]),   # no opens -> FAIL
        "F4_LIQ": np.asarray(d["n_own_liq"], float) == 0,
        "F5_1DAY": np.asarray(d["conc"], float) <= TH["oneday_conc"],
    }
    passes["FALL"] = np.logical_and.reduce(list(passes.values()))

    def top30(mask):
        idx = np.flatnonzero(mask & np.isfinite(metric))
        order = idx[np.lexsort((w[idx], -metric[idx]))]
        return w[order[:K]].tolist()

    rosters = {"F0": top30(np.ones(w.size, bool))}
    for a in ("F1_BOT", "F2_MAKER", "F3_DUST", "F4_LIQ", "F5_1DAY", "FALL"):
        rosters[a] = top30(passes[a])
    f0set = rosters["F0"]
    rosters["FRTS"] = [x for x in f0set if passes["FALL"][np.flatnonzero(w == x)[0]]]
    funnel = {"pool_eligible": int(w.size),
              "pass_counts": {a: int(m.sum()) for a, m in passes.items()},
              "f0_screened_out_by": {a: [x for x in f0set
                                         if not passes[a][np.flatnonzero(w == x)[0]]]
                                     for a in ("F1_BOT", "F2_MAKER", "F3_DUST", "F4_LIQ",
                                               "F5_1DAY")},
              "frts_size": len(rosters["FRTS"])}
    return rosters, funnel


def _fold_entries(con, fold: int, wallets: list[str], sha: str) -> Path:
    p = CACHE / f"ent_{fold}_{sha}.parquet"
    if p.exists():
        return p
    parts = _ctx_parts(fold)
    assert parts, f"no ctx for fold {fold}"
    t0, t1 = _month_start_ms(fold), as_of_cutoff_ms(fold)
    ctx_list = ",".join(f"'{x}'" for x in parts)
    con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT UNNEST(?) AS wallet", [wallets])
    joins, cols = [], []
    prev = "p0"
    for h in HOURS:
        ms = h * 3_600_000
        joins.append(f"p{h} AS (SELECT {prev}.*, c.mid_px AS px{h}, c.ts AS px{h}_ts "
                     f"FROM {prev} ASOF LEFT JOIN ctx c ON {prev}.coin = c.coin "
                     f"AND ({prev}.ts + {ms}) >= c.ts)")
        cols.append(f"CASE WHEN px0 IS NOT NULL AND px{h} IS NOT NULL AND px0 > 0 "
                    f"AND (ts - px0_ts) <= {STALE_MS} AND ((ts + {ms}) - px{h}_ts) <= {STALE_MS} "
                    f"THEN dir_sign * (px{h} - px0) / px0 * 1e4 END AS mk{h}")
        prev = f"p{h}"
    con.execute(f"""COPY (
      WITH ent2 AS (
        SELECT e.* FROM ({_entries_sql([fold], t0, t1, "wallet IN (SELECT wallet FROM cw)")}) e
        WHERE e.notional >= {NOTL_MIN}
      ),
      ctx AS (SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}])
              WHERE mid_px IS NOT NULL AND mid_px > 0),
      p0 AS (SELECT ent2.*, c.mid_px AS px0, c.ts AS px0_ts
             FROM ent2 ASOF LEFT JOIN ctx c ON ent2.coin = c.coin AND ent2.ts >= c.ts),
      {",".join(joins)}
      SELECT wallet, coin, ts, dir_sign, notional, null_oid, n_mixed_dir_fills, {",".join(cols)}
      FROM {prev}
    ) TO '{p.with_suffix(".tmp.parquet").as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    p.with_suffix(".tmp.parquet").rename(p)
    print(f"  fold {fold}: entries cached ({len(wallets)} wallets)", flush=True)
    return p


def _np(a, dtype=float):
    if np.ma.isMaskedArray(a):
        fill = np.nan if dtype is float else (False if dtype is bool else 0)
        a = np.ma.filled(a.astype(float) if dtype is float else a, fill)
    return np.asarray(a, dtype)


def _cell(mk, wallet, fold, rng, winsor_lim=None):
    """majors_native robust cell spec; optional common winsor limit (S1)."""
    out = {"n_entries": int(mk.size)}
    if mk.size == 0:
        return out
    out["n_wallets"] = int(np.unique(wallet).size)
    wf = np.char.add(np.char.add(wallet, "|"), fold.astype(str))
    lim = float(np.percentile(np.abs(mk), 95)) if winsor_lim is None else float(winsor_lim)
    out["winsor_lim_bp"] = lim
    mk_w = np.clip(mk, -lim, lim)
    uk, inv = np.unique(wf, return_inverse=True)
    cnt = np.bincount(inv)
    keep = cnt[inv] >= 3
    if not keep.any():
        out["robust"] = None
        return out
    uk2, inv2 = np.unique(wf[keep], return_inverse=True)
    wf_mean = np.bincount(inv2, weights=mk_w[keep]) / np.bincount(inv2)
    wf_wal = np.array([k.split("|")[0] for k in uk2])
    wf_fold = np.array([int(k.split("|")[1]) for k in uk2])
    out["n_robust_wf"] = int(uk2.size)
    out["robust_point_bp"] = float(wf_mean.mean())
    uw, winv = np.unique(wf_wal, return_inverse=True)
    s, c = np.bincount(winv, weights=wf_mean), np.bincount(winv).astype(float)
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        m = np.bincount(rng.integers(0, uw.size, uw.size), minlength=uw.size)
        stats[b] = (m @ s) / (m @ c)
    stats = stats[np.isfinite(stats)]
    se = float(stats.std(ddof=1))
    out["ci"] = [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))]
    out["p_gt0"] = float((stats > 0).mean())
    out["boot_se"] = se
    out["mde_bp"] = round(2.8 * se, 2)
    pf = {str(fl): (float(wf_mean[wf_fold == fl].mean()) if (wf_fold == fl).any() else None)
          for fl in FOLDS}
    out["per_fold_mean_bp"] = pf
    sg = [v for v in pf.values() if v is not None]
    out["per_fold_signs"] = f"{sum(1 for v in sg if v > 0)}/{len(sg)} folds > 0"
    return {**out, "_wf": (wf_wal, wf_fold, wf_mean)}


def _contrast(cellA, cellB, rng):
    """A−B paired delta: paired t 7df + wallet-cluster paired bootstrap; quote wider (S2)."""
    if "_wf" not in cellA or "_wf" not in cellB:
        return {"status": "undefined (empty arm)"}
    wA, fA, mA = cellA["_wf"]
    wB, fB, mB = cellB["_wf"]
    deltas, folds_used = [], []
    for fl in FOLDS:
        a, b = mA[fA == fl], mB[fB == fl]
        if a.size and b.size:
            deltas.append(float(a.mean() - b.mean()))
            folds_used.append(fl)
    d = np.asarray(deltas)
    out = {"n_folds": int(d.size), "fold_deltas_bp": dict(zip(map(str, folds_used), deltas)),
           "sign_count": f"{int((d > 0).sum())}/{d.size} folds > 0"}
    if d.size >= 5:                                   # t_ppf raises below df=4
        se_t = float(d.std(ddof=1) / np.sqrt(d.size))
        tq = t_ppf(0.975, d.size - 1)
        out["point_bp"] = float(d.mean())
        out["ci_t7"] = [float(d.mean() - tq * se_t), float(d.mean() + tq * se_t)]
        out["mde_bp_t"] = round((t_ppf(0.975, d.size - 1) + t_ppf(0.80, d.size - 1)) * se_t, 2)
        # p for BH (two-sided paired t via boot-free normal approx on t stat)
        tstat = d.mean() / se_t if se_t > 0 else 0.0
        out["t_stat"] = float(tstat)
    uw = np.unique(np.concatenate([wA, wB]))
    idxA = np.searchsorted(uw, wA)
    idxB = np.searchsorted(uw, wB)
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        m = np.bincount(rng.integers(0, uw.size, uw.size), minlength=uw.size).astype(float)
        na, nb = m[idxA].sum(), m[idxB].sum()
        stats[b] = ((m[idxA] @ mA) / na if na else np.nan) - ((m[idxB] @ mB) / nb if nb else np.nan)
    stats = stats[np.isfinite(stats)]
    if stats.size:
        out["ci_wallet_boot"] = [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))]
        wA_, wB_ = out.get("ci_t7"), out["ci_wallet_boot"]
        if wA_:
            out["ci_quoted"] = wA_ if (wA_[1] - wA_[0]) >= (wB_[1] - wB_[0]) else wB_
            out["ci_quoted_family"] = "t7" if out["ci_quoted"] == wA_ else "wallet_boot"
    return out


def _book(e, mask, label):
    """Equal-$1k descriptive book at 8h (S8: wider of day-block and wallet-cluster CI)."""
    mk = e["mk8"][mask]
    ok = np.isfinite(mk)
    mk, ts, wal = mk[ok], e["ts"][mask][ok], e["wallet"][mask][ok]
    if mk.size == 0:
        return {"label": label, "n": 0}
    net = mk - RT_COST_BP
    pnl = net / 1e4 * CLIP_USD
    exit_day = ((ts + PRIMARY_H * 3_600_000) // 86_400_000).astype(int)
    ud, dinv = np.unique(exit_day, return_inverse=True)
    daily = np.bincount(dinv, weights=pnl)
    span = int(ud.max() - ud.min() + 1)
    full = np.zeros(span)
    full[ud - ud.min()] = daily
    sharpe = float(full.mean() / full.std(ddof=1) * np.sqrt(365)) if full.std(ddof=1) > 0 else None
    rng = np.random.default_rng(SEED + 777)
    boots = {}
    for fam, key in (("day_block", exit_day), ("wallet", wal)):
        uk, kinv = np.unique(key, return_inverse=True)
        s, c = np.bincount(kinv, weights=net), np.bincount(kinv).astype(float)
        st = np.empty(N_BOOT)
        for b in range(N_BOOT):
            m = np.bincount(rng.integers(0, uk.size, uk.size), minlength=uk.size)
            st[b] = (m @ s) / (m @ c)
        st = st[np.isfinite(st)]
        boots[fam] = [float(np.quantile(st, .025)), float(np.quantile(st, .975))]
    wider = max(boots.values(), key=lambda ci: ci[1] - ci[0])
    return {"label": label, "n": int(mk.size), "gross_bp": float(mk.mean()),
            "net_bp": float(net.mean()), "net_bp_stress": float((mk - RT_STRESS_BP).mean()),
            "net_usd": float(pnl.sum()), "ann_sharpe_daily": sharpe,
            "ci_net_bp": {"quoted_wider": wider, **boots},
            "active_days": int((full != 0).sum()), "span_days": span}


def _bh(pvals: dict) -> dict:
    items = [(k, v) for k, v in pvals.items() if v is not None]
    m = len(items)
    order = sorted(items, key=lambda kv: kv[1])
    out, prev = {}, 1.0
    for rank_from_end in range(m, 0, -1):
        k, p = order[rank_from_end - 1]
        q = min(prev, p * m / rank_from_end)
        out[k] = round(q, 4)
        prev = q
    return out


def run():
    CACHE.mkdir(parents=True, exist_ok=True)
    sha = _sha()
    frozen133 = set(json.loads(FROZEN133.read_text())["distinct_wallets"]) \
        if FROZEN133.exists() else set()
    con = _connect()
    rep = {"config": {**CONFIG, "code_commit": _git(), "config_sha": sha,
                      "ctx_parts_per_fold": {str(f): len(_ctx_parts(f)) for f in FOLDS}},
           "folds": {}, "cells": {}, "contrasts": {}, "books": {}, "diagnostics": {}}

    rows = {k: [] for k in ("wallet", "coin", "ts", "dir_sign", "notional", "null_oid",
                            "n_mixed_dir_fills", "fold")} | {f"mk{h}": [] for h in HOURS}
    membership = {a: set() for a in ARMS}          # (wallet, fold) pairs per arm
    dragger_wf = {a: set() for a in ("F1_BOT", "F2_MAKER", "F3_DUST", "F4_LIQ", "F5_1DAY")}
    for fold in FOLDS:
        featp = _formation_features(con, fold, sha)
        rosters, funnel = _rosters(featp)
        union = sorted(set().union(*[set(r) for r in rosters.values()],
                                   *[set(v) for v in funnel["f0_screened_out_by"].values()]))
        entp = _fold_entries(con, fold, union, sha)
        lc = duckdb.connect()
        d = lc.execute(f"SELECT * FROM read_parquet('{entp.as_posix()}')").fetchnumpy()
        lc.close()
        n = d["wallet"].size
        for k in ("wallet", "coin"):
            rows[k].append(d[k].astype(str))
        for k in ("ts", "dir_sign", "notional"):
            rows[k].append(_np(d[k]))
        rows["null_oid"].append(_np(d["null_oid"], bool))
        rows["n_mixed_dir_fills"].append(_np(d["n_mixed_dir_fills"]))
        rows["fold"].append(np.full(n, fold))
        for h in HOURS:
            rows[f"mk{h}"].append(_np(d[f"mk{h}"]))
        for a in ARMS:
            membership[a] |= {(x, fold) for x in rosters[a]}
        for a, lst in funnel["f0_screened_out_by"].items():
            dragger_wf[a] |= {(x, fold) for x in lst}
        rep["folds"][str(fold)] = {
            "funnel": {k: (v if k != "f0_screened_out_by" else {kk: len(vv) for kk, vv in v.items()})
                       for k, v in funnel.items()},
            "rosters_n": {a: len(rosters[a]) for a in ARMS},
            "f0_x_fall_overlap": len(set(rosters["F0"]) & set(rosters["FALL"])),
            "frozen133_overlap": {a: len(set(rosters[a]) & frozen133) for a in ("F0", "FALL")},
            "n_entries_union": n,
        }
        print(f"fold {fold}: pool {funnel['pool_eligible']:,}, FRTS {funnel['frts_size']}, "
              f"entries {n:,}", flush=True)
    con.close()
    e = {k: np.concatenate(v) for k, v in rows.items()}
    wf_pairs = list(zip(e["wallet"], e["fold"].astype(int)))
    in_arm = {a: np.array([p in membership[a] for p in wf_pairs]) for a in ARMS}

    # ---- 32 cells ------------------------------------------------------------------------------
    cells_wf = {}
    for ai, a in enumerate(ARMS):
        for hi, h in enumerate(HOURS):
            mk = e[f"mk{h}"]
            m = in_arm[a] & np.isfinite(mk)
            rng = np.random.default_rng(SEED + 1000 * ai + hi)
            cell = _cell(mk[m], e["wallet"][m], e["fold"][m], rng)
            cells_wf[(a, h)] = cell
            rep["cells"][f"{a}@{h}h"] = {k: v for k, v in cell.items() if k != "_wf"}
            if "robust_point_bp" in cell:
                ci = cell.get("ci", [np.nan, np.nan])
                print(f"{a:>8} @{h:>2}h n={cell['n_entries']:>6,} robust={cell['robust_point_bp']:+.1f}bp "
                      f"CI[{ci[0]:+.1f},{ci[1]:+.1f}] {cell.get('per_fold_signs','')}", flush=True)

    # ---- contrasts with COMMON winsor (S1) + paired designs (S2) + decomposition (S3) ----------
    pvals = {}
    for pair in (("FALL", "F0"), ("FRTS", "F0"), ("FALL", "FRTS")):
        for hi, h in enumerate(HOURS):
            mk = e[f"mk{h}"]
            both = (in_arm[pair[0]] | in_arm[pair[1]]) & np.isfinite(mk)
            lim = float(np.percentile(np.abs(mk[both]), 95)) if both.any() else None
            cc = {}
            for arm in pair:
                m = in_arm[arm] & np.isfinite(mk)
                rng = np.random.default_rng(SEED + 50_000 + 1000 * ARMS.index(arm) + hi)
                cc[arm] = _cell(mk[m], e["wallet"][m], e["fold"][m], rng, winsor_lim=lim)
            rng = np.random.default_rng(SEED + 90_000 + 100 * HOURS.index(h) + len(pair[0]))
            ct = _contrast(cc[pair[0]], cc[pair[1]], rng)
            # unwinsorized sensitivity
            ccu = {}
            for arm in pair:
                m = in_arm[arm] & np.isfinite(mk)
                ccu[arm] = _cell(mk[m], e["wallet"][m], e["fold"][m],
                                 np.random.default_rng(1), winsor_lim=float("inf"))
            du = _contrast(ccu[pair[0]], ccu[pair[1]], np.random.default_rng(2))
            ct["unwinsorized_point_bp"] = du.get("point_bp")
            key = f"{pair[0]}-{pair[1]}@{h}h"
            rep["contrasts"][key] = ct
            if pair == ("FALL", "F0") and "t_stat" in ct:
                from math import erf, sqrt
                pvals[key] = 2 * (1 - 0.5 * (1 + erf(abs(ct["t_stat"]) / sqrt(2))))
            if "point_bp" in ct:
                print(f"{key:>16}: {ct['point_bp']:+.2f}bp quoted CI {ct.get('ci_quoted')} "
                      f"({ct.get('ci_quoted_family')}) {ct['sign_count']}", flush=True)
    rep["contrasts"]["bh_q_fall_minus_f0"] = _bh(pvals)
    cleared = [k for k, c in rep["cells"].items()
               if c.get("ci") and (c["ci"][0] > 0 or c["ci"][1] < 0)]
    rep["contrasts"]["grid_tally"] = {"cells_ci_clear_0": cleared,
                                      "k_of_32": len(cleared),
                                      "expected_under_global_null": round(32 * 0.05, 1)}

    # ---- books, draggers, frozen-133 sensitivity ----------------------------------------------
    rep["books"]["F0@8h"] = _book(e, in_arm["F0"], "F0@8h equal-$1k")
    rep["books"]["FALL@8h"] = _book(e, in_arm["FALL"], "FALL@8h equal-$1k")
    for a, wfset in dragger_wf.items():
        m = np.array([p in wfset for p in wf_pairs]) & np.isfinite(e["mk8"])
        rep["diagnostics"][f"dragger_{a}_mk8_mean_bp"] = \
            (float(e["mk8"][m].mean()) if m.any() else None)   # funnel diagnostic ONLY (S7)
    m = in_arm["FALL"] & np.isfinite(e["mk8"]) & \
        np.array([w not in frozen133 for w in e["wallet"]])
    rep["diagnostics"]["fall_8h_ex_frozen133_mean_bp"] = float(e["mk8"][m].mean()) if m.any() else None
    rep["diagnostics"]["null_oid_entries"] = int(e["null_oid"].sum())
    rep["diagnostics"]["entries_with_mixed_dir_fills"] = int((e["n_mixed_dir_fills"] > 0).sum())
    rep["diagnostics"]["missing_mk_by_h"] = {str(h): int((~np.isfinite(e[f"mk{h}"])).sum())
                                             for h in HOURS}

    OUT.write_text(json.dumps(rep, indent=1, default=str))
    print(f"-> {OUT}")
    return rep


if __name__ == "__main__":
    run()
