"""Majors-native K30 book term structure, bot-vs-human decomposition — DESCRIPTIVE.

Burned folds 202511-202606; decomposition of the EXISTING cached majors_native
K30 measurements (data/derived/copy_cohort/majors_native/entries_*.parquet — the
frozen book's entries with all 5 horizon markouts already attached); no new
selection. Mirrors termstructure_by_archetype (alts) on the majors book.

Classification (mechanical, per wallet-fold, from lake wallet_coin_day over the
fold's 3-month formation window, all coins — same features the census used):
    BOT-LIKE  iff fills_per_day > 1000 OR taker_share < 0.1
    HUMAN     otherwise
Census kmeans labels only cover arm-T wallets, so majors-native wallets are
classified directly; overlap with census labels reported where both exist.

Per {ALL, HUMAN, BOT} x {1h,4h,8h,24h,48h}: n entries, robust wallet-fold-equal
bp (winsor p95 |mk| within cell, wf>=3), 1000-rep wallet-cluster bootstrap CI.

    python -m research.studies.copy_cohort.majors_archetype
"""
from __future__ import annotations

import json

import duckdb
import numpy as np

from research.data.markout import REPO_ROOT
from research.lib.cv import MONTHS
from . import lake

DERIVED = REPO_ROOT / "data" / "derived" / "copy_cohort"
CACHE = DERIVED / "majors_native"
FROZEN = DERIVED / "frozen_alt_universe.json"
CENSUS = DERIVED / "cohort_census.json"
CLS_CACHE = DERIVED / "majors_archetype_classification.json"
OUT = DERIVED / "majors_archetype_report.json"
DOC = REPO_ROOT / "research" / "studies" / "copy_cohort" / "COHORT_CENSUS.md"

FOLDS = MONTHS[3:]                     # 202511..202606
HOURS = (1, 4, 8, 24, 48)
K = 30
N_BOOT = 1000
SEED = 20260716
FPD_BOT = 1000.0
TAKER_BOT = 0.10
CLUSTER_TAG = {0: "dust", 1: "midtaker", 2: "grinder", 3: "hft", 4: "specialist",
               None: "puremaker"}


def _formation_months(fold: int) -> list[int]:
    i = MONTHS.index(fold)
    return MONTHS[i - 3:i]


def _top30(fold: int, frozen: set[str]) -> list[str]:
    """Deterministic top-30 from the cached selection pool (majors_native._select_top100 spec)."""
    lc = duckdb.connect()
    d = lc.execute(f"SELECT wallet, t_stat FROM read_parquet("
                   f"'{(CACHE / f'sel_{fold}.parquet').as_posix()}') "
                   "WHERE t_stat IS NOT NULL").fetchnumpy()
    lc.close()
    w = d["wallet"].astype(str)
    t = np.asarray(d["t_stat"], float)
    keep = np.array([x not in frozen for x in w])
    w, t = w[keep], t[keep]
    order = np.lexsort((w, -t))
    return w[order[:K]].tolist()


def _classify(con, fold: int, wallets: list[str]) -> dict[str, dict]:
    """fills/day + taker_share over the fold's formation window (all coins)."""
    globs = ",".join(f"'{lake.wcd_month_glob(m)}'" for m in _formation_months(fold))
    wl = ",".join(f"'{w}'" for w in wallets)
    rows = con.execute(f"""
        SELECT wallet,
               sum(n_fills)::DOUBLE / count(DISTINCT day)      AS fills_per_day,
               sum(n_taker)::DOUBLE / nullif(sum(n_fills), 0)  AS taker_share
        FROM read_parquet([{globs}])
        WHERE wallet IN ({wl})
        GROUP BY wallet""").fetchall()
    out = {}
    for w, fpd, tk in rows:
        bot = (fpd is not None and fpd > FPD_BOT) or (tk is not None and tk < TAKER_BOT)
        out[w] = {"fills_per_day": fpd, "taker_share": tk,
                  "label": "BOT" if bot else "HUMAN"}
    for w in wallets:                       # selected => has formation wcd rows, but be safe
        out.setdefault(w, {"fills_per_day": None, "taker_share": None, "label": "HUMAN"})
    return out


def _cell(mk, wallet, fold, rng):
    """Robust wallet-fold-equal cell (majors_native._cell_inference spec, 1000-rep boot)."""
    out = {"n_entries": int(mk.size),
           "n_wallets": int(np.unique(wallet).size) if mk.size else 0}
    if mk.size == 0:
        out["robust"] = None
        return out
    wf_key = np.char.add(np.char.add(wallet, "|"), fold.astype(str))
    uk, inv = np.unique(wf_key, return_inverse=True)
    out["n_wf"] = int(uk.size)
    out["raw_point_bp"] = float((np.bincount(inv, weights=mk) / np.bincount(inv)).mean())
    lim = float(np.percentile(np.abs(mk), 95))
    cnt = np.bincount(inv)
    keep = cnt[inv] >= 3
    if not keep.any():
        out["robust"] = None
        return out
    uk2, inv2 = np.unique(wf_key[keep], return_inverse=True)
    wf_mean = np.bincount(inv2, weights=np.clip(mk, -lim, lim)[keep]) / np.bincount(inv2)
    wf_wal = np.array([k.split("|")[0] for k in uk2])
    wf_fold = np.array([int(k.split("|")[1]) for k in uk2])
    uw, winv = np.unique(wf_wal, return_inverse=True)
    s = np.bincount(winv, weights=wf_mean)
    c = np.bincount(winv).astype(float)
    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        m = np.bincount(rng.integers(0, uw.size, uw.size), minlength=uw.size)
        stats[b] = (m @ s) / (m @ c)
    stats = stats[np.isfinite(stats)]
    pf = {str(f): (float(wf_mean[wf_fold == f].mean()) if (wf_fold == f).any() else None)
          for f in FOLDS}
    signs = [v for v in pf.values() if v is not None]
    out["robust"] = {
        "point_bp": float(wf_mean.mean()),
        "n_robust_entries": int(keep.sum()), "n_wf_robust": int(uk2.size),
        "n_wallets": int(uw.size), "winsor_lim_bp": lim,
        "ci": [float(np.quantile(stats, .025)), float(np.quantile(stats, .975))],
        "p_gt0": float((stats > 0).mean()),
        "per_fold_mean_bp": pf,
        "per_fold_signs": f"{sum(1 for v in signs if v > 0)}/{len(signs)} folds > 0"}
    return out


def run():
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    census = json.loads(CENSUS.read_text())
    census_arch = {w["wallet"]: CLUSTER_TAG.get(w["cluster"], "unknown")
                   for w in census["wallets"]}

    # ---- per-fold classification (cached; lake wcd formation-window features) ----
    if CLS_CACHE.exists():
        cls = json.loads(CLS_CACHE.read_text())
    else:
        con = lake.connect()
        cls = {}
        for f in FOLDS:
            top = _top30(f, frozen)
            cls[str(f)] = _classify(con, f, top)
            nb = sum(1 for v in cls[str(f)].values() if v["label"] == "BOT")
            print(f"[classify] fold {f}: {len(top)} K30 wallets, {nb} BOT / "
                  f"{len(top) - nb} HUMAN", flush=True)
        CLS_CACHE.write_text(json.dumps(cls, indent=1))

    per_fold_counts = {}
    census_overlap = {"n_wf_in_census": 0, "agree": 0,
                      "census_hft_as_bot": 0, "census_hft_total": 0, "cross": {}}
    for f in FOLDS:
        c = cls[str(f)]
        nb = sum(1 for v in c.values() if v["label"] == "BOT")
        per_fold_counts[str(f)] = {"k30": len(c), "bot": nb, "human": len(c) - nb}
        for w, v in c.items():
            if w in census_arch:
                a = census_arch[w]
                census_overlap["n_wf_in_census"] += 1
                key = f"{a}->{v['label']}"
                census_overlap["cross"][key] = census_overlap["cross"].get(key, 0) + 1
                is_bot_census = a in ("hft", "puremaker")
                if is_bot_census == (v["label"] == "BOT"):
                    census_overlap["agree"] += 1
                if a == "hft":
                    census_overlap["census_hft_total"] += 1
                    census_overlap["census_hft_as_bot"] += v["label"] == "BOT"

    # ---- load cached K30 entries (markouts already attached) ----
    rows = {k: [] for k in ("wallet", "fold")} | {f"mk{h}": [] for h in HOURS}
    lc = duckdb.connect()
    for f in FOLDS:
        d = lc.execute(f"SELECT * FROM read_parquet("
                       f"'{(CACHE / f'entries_{f}.parquet').as_posix()}') "
                       f"WHERE rk < {K}").fetchnumpy()
        n = d["wallet"].size
        rows["wallet"].append(d["wallet"].astype(str))
        rows["fold"].append(np.full(n, f))
        for h in HOURS:
            a = d[f"mk{h}"]
            rows[f"mk{h}"].append(np.ma.filled(a, np.nan) if np.ma.isMaskedArray(a)
                                  else np.asarray(a, float))
    lc.close()
    e = {k: np.concatenate(v) for k, v in rows.items()}
    ent_label = np.array([cls[str(f)][w]["label"]
                          for w, f in zip(e["wallet"], e["fold"])])

    slices = {"ALL": np.ones(e["wallet"].size, bool),
              "HUMAN": ent_label == "HUMAN",
              "BOT": ent_label == "BOT"}
    report = {"label": "DESCRIPTIVE — bot-vs-human decomposition of the majors-native K30 "
                       "book term structure (burned folds 202511-202606; frozen cached "
                       "entries/markouts reused; mechanical formation-window bot criteria; "
                       "no new selection, no significance claims)",
              "config": {"entries": "cached majors_native K30 (rk<30), MAJORS flat taker "
                                    "opens, notl>=$250",
                         "markout": "gross dir-signed bp vs asset_ctx mid, backward ASOF, "
                                    "<=90s both ends (cached at book build)",
                         "bot_criteria": f"fills_per_day > {FPD_BOT:g} OR taker_share < "
                                         f"{TAKER_BOT:g} over the fold's 3-month formation "
                                         "window (lake wallet_coin_day, all coins)",
                         "robust_spec": "winsor p95 |mk| within cell, wf>=3, "
                                        "wallet-fold-equal",
                         "n_boot": N_BOOT, "seed": SEED},
              "classification": {"per_fold": per_fold_counts,
                                 "census_overlap": census_overlap},
              "results": {}}
    for si, (name, m0) in enumerate(slices.items()):
        row = {}
        for hi, h in enumerate(HOURS):
            mk = e[f"mk{h}"]
            m = m0 & np.isfinite(mk)
            rng = np.random.default_rng(SEED + 1000 * si + hi)
            row[f"{h}h"] = _cell(mk[m], e["wallet"][m], e["fold"][m], rng)
        report["results"][name] = row

    OUT.write_text(json.dumps(report, indent=1))
    print(f"\n{'slice':>7} " + " ".join(f"{h}h".rjust(24) for h in HOURS))
    for name in slices:
        def fmt(c):
            r = c["robust"]
            if not r:
                return f"(n={c['n_entries']})".rjust(24)
            return (f"{r['point_bp']:+6.1f}"
                    f"[{r['ci'][0]:+7.1f},{r['ci'][1]:+7.1f}]").rjust(24)
        row = report["results"][name]
        print(f"{name:>7} " + " ".join(fmt(row[f'{h}h']) for h in HOURS)
              + f"  n1h={row['1h']['n_entries']:,} wal={row['1h']['n_wallets']}")
    print("counts/fold:", {f: (v["bot"], v["human"]) for f, v in per_fold_counts.items()})
    print("census overlap:", census_overlap)
    print(f"-> {OUT}")
    return report


if __name__ == "__main__":
    run()
