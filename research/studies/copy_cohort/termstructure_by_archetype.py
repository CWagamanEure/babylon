"""Markout term structure decomposed by census archetype — DESCRIPTIVE (burned folds).

Decomposition of the existing E1 measurement (arm-T cohort alt flat taker opens,
5-horizon gross markouts vs local asset_ctx mid, <=90s staleness — exactly
construction_study.py's E1) by the pre-existing kmeans archetype labels in
data/derived/copy_cohort/cohort_census.json. No new selection; post-hoc clusters.

Thesis under test (user's): HFT/bot wallets drag the pooled curve toward short
horizons; excluding them the remaining archetypes peak later (8-24h).

Per archetype x horizon (all entries and the >=$250-notional subset):
n_entries, robust wallet-fold-equal bp (winsor p95 |mk| within cell, wf>=3),
1000-rep wallet-cluster bootstrap CI. Plus pooled curve and pooled-ex-{HFT,dust}.

    python -m research.studies.copy_cohort.termstructure_by_archetype
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from research.data.markout import REPO_ROOT
from . import lake
from .alt_fresh_validate import _ctx_parts

COHORTS = REPO_ROOT / "data" / "derived" / "copy_cohort" / "alt_universe_cohorts.json"
CENSUS = REPO_ROOT / "data" / "derived" / "copy_cohort" / "cohort_census.json"
CONSTRUCTION = REPO_ROOT / "data" / "derived" / "copy_cohort" / "construction_report.json"
CACHE_DIR = REPO_ROOT / "data" / "derived" / "copy_cohort" / "termstructure_by_archetype"
OUT = REPO_ROOT / "data" / "derived" / "copy_cohort" / "termstructure_by_archetype_report.json"
MAJORS = ("BTC", "ETH", "SOL", "HYPE")
HORIZONS = (("1h", 3_600_000), ("4h", 14_400_000), ("8h", 28_800_000),
            ("24h", 86_400_000), ("48h", 172_800_000))
STALE_MS = 90_000
SEED = 20260716
N_BOOT = 1000
MIN_NOTL = 250.0

# census cluster id -> short tag (order fixes cell rng indexing)
ARCH_ORDER = ["dust", "midtaker", "grinder", "hft", "specialist", "puremaker"]
CLUSTER_TAG = {0: "dust", 1: "midtaker", 2: "grinder", 3: "hft", 4: "specialist",
               None: "puremaker"}


def _fold_entries(con, fold: int, wallets: list[str]) -> Path:
    """E1 entries (alt flat taker opens) + notl + 5-horizon markouts, cached per fold."""
    part = CACHE_DIR / f"fold={fold}" / "part.parquet"
    if part.exists():
        return part
    part.parent.mkdir(parents=True, exist_ok=True)
    ctx = _ctx_parts(fold)
    if not ctx:
        raise RuntimeError(f"no asset_ctx for fold {fold}")
    majors = ",".join(f"'{m}'" for m in MAJORS)
    ctx_list = ",".join(f"'{p}'" for p in ctx)
    con.execute("CREATE OR REPLACE TEMP TABLE cw AS SELECT * FROM (SELECT UNNEST(?) AS wallet)",
                [sorted(wallets)])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ent AS
        SELECT o.wallet, o.coin, o.ts, o.dir_sign, CAST(o.notl AS DOUBLE) AS notl
        FROM read_parquet('{lake.ope_month_glob(fold)}') o JOIN cw USING (wallet)
        WHERE o.coin NOT IN ({majors})""")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE ctx AS
        SELECT coin, ts, mid_px FROM read_parquet([{ctx_list}]) WHERE mid_px IS NOT NULL""")
    ctes = ["p0 AS (SELECT e.*, c.mid_px AS px0, c.ts AS ts0 "
            "FROM ent e ASOF LEFT JOIN ctx c ON e.coin = c.coin AND e.ts >= c.ts)"]
    sel, prev = [], "p0"
    for i, (h, ms) in enumerate(HORIZONS):
        cur = f"h{i}"
        ctes.append(f"{cur} AS (SELECT {prev}.*, c.mid_px AS px_{h}, c.ts AS tse_{h} "
                    f"FROM {prev} ASOF LEFT JOIN ctx c "
                    f"ON {prev}.coin = c.coin AND ({prev}.ts + {ms}) >= c.ts)")
        sel.append(f"CASE WHEN px0 IS NOT NULL AND px0 > 0 AND (ts - ts0) <= {STALE_MS} "
                   f"AND px_{h} IS NOT NULL AND ((ts + {ms}) - tse_{h}) <= {STALE_MS} "
                   f"THEN dir_sign * (px_{h} - px0) / px0 * 1e4 END AS mk_{h}")
        prev = cur
    tmp = str(part) + ".tmp"
    con.execute("COPY (WITH " + ",\n".join(ctes)
                + f" SELECT wallet, notl, {', '.join(sel)} FROM {prev})"
                + f" TO '{tmp}' (FORMAT PARQUET, COMPRESSION zstd)")
    Path(tmp).replace(part)
    return part


def _cell(mk, wallet, fold, rng):
    """Robust wallet-fold-equal cell (same spec as construction_study._cell, 1000-rep boot)."""
    fin = np.isfinite(mk)
    mk, wallet, fold = mk[fin], wallet[fin], fold[fin]
    out = {"n_entries": int(mk.size), "n_wf": 0, "robust": None}
    if mk.size == 0:
        return out
    key = np.char.add(np.char.add(wallet, "|"), fold.astype("U6"))
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    wf_wal = np.array([k.split("|")[0] for k in uk])
    out["n_wf"] = int(uk.size)
    out["raw_point_bp"] = float((np.bincount(inv, weights=mk) / cnt).mean())
    lim = float(np.percentile(np.abs(mk), 95))
    kept = cnt >= 3
    if not kept.any():
        return out
    wf_mean = (np.bincount(inv, weights=np.clip(mk, -lim, lim)) / cnt)[kept]
    kw = wf_wal[kept]
    uwal = np.unique(kw)
    groups = [wf_mean[kw == x] for x in uwal]
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        pick = rng.integers(0, len(groups), len(groups))
        stats[b] = float(np.mean(np.concatenate([groups[i] for i in pick])))
    out["robust"] = {"point_bp": float(wf_mean.mean()),
                     "n_robust_entries": int(cnt[kept].sum()),
                     "n_wf_robust": int(kept.sum()), "n_wallets": int(uwal.size),
                     "winsor_lim_bp": lim,
                     "ci": [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))],
                     "p_gt0": float((stats > 0).mean())}
    return out


def run():
    cohorts = json.loads(COHORTS.read_text())
    census = json.loads(CENSUS.read_text())
    arch = {w["wallet"]: CLUSTER_TAG.get(w["cluster"], "unknown") for w in census["wallets"]}
    cluster_labels = {CLUSTER_TAG[None if k == "-1" else int(k)]: v["label"]
                      for k, v in census["clusters"].items()}

    con = lake.connect()
    import duckdb  # noqa: F401  (con is duckdb; local reads reuse it)
    cols = {k: [] for k in ("wallet", "fold", "notl")}
    mks = {h: [] for h, _ in HORIZONS}
    for fold_s in sorted(cohorts["folds"]):
        fold = int(fold_s)
        members = cohorts["folds"][fold_s]["arms"]["T"]["members"]
        print(f"[termstructure] fold {fold}: E1 entries + markouts ...", flush=True)
        part = _fold_entries(con, fold, sorted(members))
        d = con.execute(f"SELECT * FROM read_parquet('{part.as_posix()}')").fetchnumpy()
        n = d["wallet"].size
        cols["wallet"].append(np.asarray(d["wallet"], str))
        cols["fold"].append(np.full(n, fold))
        cols["notl"].append(np.ma.filled(d["notl"], np.nan)
                            if np.ma.isMaskedArray(d["notl"]) else np.asarray(d["notl"], float))
        for h, _ in HORIZONS:
            a = d[f"mk_{h}"]
            mks[h].append(np.ma.filled(a, np.nan) if np.ma.isMaskedArray(a)
                          else np.asarray(a, float))
    wallet = np.concatenate(cols["wallet"])
    fold = np.concatenate(cols["fold"])
    notl = np.concatenate(cols["notl"])
    mk = {h: np.concatenate(v) for h, v in mks.items()}
    ent_arch = np.array([arch.get(w, "unknown") for w in wallet])

    subsets = {"all": np.ones(wallet.size, bool), "ge250": notl >= MIN_NOTL}
    slices = ({"pooled": np.ones(wallet.size, bool)}
              | {a: ent_arch == a for a in ARCH_ORDER}
              | {"pooled_ex_hft_dust": ~np.isin(ent_arch, ("hft", "dust"))})
    slice_names = list(slices)
    report = {"label": "DESCRIPTIVE — archetype x horizon decomposition of the E1 markout "
                       "term structure (burned folds 202511-202606; post-hoc census clusters; "
                       "no new selection, no significance claims)",
              "config": {"entries": "E1 alt flat taker opens (construction_study spec)",
                         "markout": "gross dir-signed bp vs asset_ctx mid, backward ASOF, "
                                    "<=90s both ends",
                         "robust_spec": "winsor p95 |mk| within cell, wf>=3, wallet-fold-equal",
                         "n_boot": N_BOOT, "seed": SEED, "min_notl_usd": MIN_NOTL,
                         "archetypes": cluster_labels},
              "results": {}}
    for sub_i, (sub, smask) in enumerate(subsets.items()):
        res = {}
        for sl_i, name in enumerate(slice_names):
            m = slices[name] & smask
            row = {}
            for hi, (h, _) in enumerate(HORIZONS):
                rng = np.random.default_rng(SEED + 100_000 * sub_i + 1000 * sl_i + hi)
                row[h] = _cell(mk[h][m], wallet[m], fold[m], rng)
            res[name] = row
        # entry-count shares at 8h (finite-markout entries)
        fin8 = np.isfinite(mk["8h"]) & smask
        tot = int(fin8.sum())
        res["_share_8h"] = {a: {"n": int((ent_arch[fin8] == a).sum()),
                                "share": float((ent_arch[fin8] == a).mean()) if tot else None}
                            for a in ARCH_ORDER}
        report["results"][sub] = res

    # sanity anchor: pooled/all must reproduce construction_report E1 cells
    cons = json.loads(CONSTRUCTION.read_text())["cells"]["E1"]
    sane = all(abs(report["results"]["all"]["pooled"][h]["raw_point_bp"]
                   - cons[h]["raw_point_bp"]) <= 0.1
               and report["results"]["all"]["pooled"][h]["n_entries"] == cons[h]["n_entries"]
               for h, _ in HORIZONS)
    report["sanity"] = {"pooled_all_matches_construction_E1": sane}
    OUT.write_text(json.dumps(report, indent=1))

    for sub in subsets:
        print(f"\n=== subset: {sub} ===")
        print(f"{'slice':>20} " + " ".join(f"{h:>22}" for h, _ in HORIZONS))
        for name in slice_names:
            row = report["results"][sub][name]
            def fmt(c):
                r = c["robust"]
                if not r:
                    return f"(n={c['n_entries']})".rjust(22)
                return f"{r['point_bp']:+6.1f}[{r['ci'][0]:+6.1f},{r['ci'][1]:+6.1f}]".rjust(22)
            print(f"{name:>20} " + " ".join(fmt(row[h]) for h, _ in HORIZONS)
                  + f"  n8h={row['8h']['n_entries']:,}")
        print("shares@8h: " + " ".join(
            f"{a}={v['share']:.1%}({v['n']:,})" for a, v in report["results"][sub]["_share_8h"].items()))
    print(f"\nsanity pooled==construction E1: {sane}\n-> {OUT}")
    if not sane:
        raise RuntimeError("SANITY FAIL: pooled/all does not reproduce construction_report E1")
    return report


if __name__ == "__main__":
    run()
