"""Identity census of the arm-T alt-universe cohort (DESCRIPTIVE — no inference).

Who are the 145 distinct wallets ever selected into arm T (8 folds x 30)?
Per-wallet profile from the incerto lake (wallet_coin_day + open_entries, 202508-202606),
formation stats from alt_universe_cohorts.json, forward copy markout from
decay_anatomy_report.json. Clusters into archetypes via numpy kmeans (seeded).

Outputs: data/derived/copy_cohort/cohort_census.json
Run: .venv/bin/python -m research.studies.copy_cohort.cohort_census
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from research.studies.copy_cohort import lake

ROOT = Path(__file__).resolve().parents[3]
DERIVED = ROOT / "data" / "derived" / "copy_cohort"
OUT = DERIVED / "cohort_census.json"

MAJORS = {"BTC", "ETH", "SOL"}
DUST_USD = 20.0  # entry notional below this counts as dust
DAY_LO, DAY_HI = 20250801, 20260630
SEED = 20260716
K = 5

# Post-hoc labels for the seeded kmeans clusters (stable under fixed SEED/K/features);
# -1 = wallets with no open_entries rows (no copyable taker entries → pure-maker/flow bots).
ARCHETYPES = {
    0: "micro dust grinder (tiny taker accounts)",
    1: "aggressive mid-size taker (majors+alts, liq-prone)",
    2: "diversified alt grinder (maker-lean, high breadth)",
    3: "HFT / market-maker bot (institutional scale)",
    4: "single-alt specialist",
    -1: "pure maker / no copyable entries",
}


def load_cohort() -> dict[str, dict]:
    d = json.loads((DERIVED / "alt_universe_cohorts.json").read_text())
    w: dict[str, dict] = {}
    for fm, fold in d["folds"].items():
        for addr, m in fold["arms"]["T"]["members"].items():
            rec = w.setdefault(addr, {"months": [], "t": [], "z": [], "nd": [], "capday": [], "scale": [], "large": []})
            rec["months"].append(int(fm))
            rec["t"].append(m["t"]); rec["z"].append(m["z"]); rec["nd"].append(m["nd"])
            rec["capday"].append(m["metric_capday"]); rec["scale"].append(m["scale_med_notl"])
            rec["large"].append(bool(m["large"]))
    return w


def load_decay() -> dict[str, dict]:
    d = json.loads((DERIVED / "decay_anatomy_report.json").read_text())
    agg: dict[str, dict] = {}
    for r in d["wallet_folds"]:
        a = agg.setdefault(r["wallet"], {"quadrants": defaultdict(int), "copy_mk_sum": 0.0, "copy_n": 0})
        a["quadrants"][r["quadrant"]] += 1
        if r["copy_mk_bp"] is not None and r["copy_n"]:
            a["copy_mk_sum"] += r["copy_mk_bp"] * r["copy_n"]
            a["copy_n"] += r["copy_n"]
    out = {}
    for wlt, a in agg.items():
        out[wlt] = {
            "quadrants": dict(a["quadrants"]),
            "copy_mk_bp_wtd": (a["copy_mk_sum"] / a["copy_n"]) if a["copy_n"] else None,
            "copy_n_total": a["copy_n"],
        }
    return out


def lake_profiles(wallets: list[str]) -> dict[str, dict]:
    con = lake.connect(mem="6GB", threads=4)
    wl = ",".join(f"'{w}'" for w in wallets)
    wcd = con.execute(f"""
        SELECT wallet,
               sum(pnl)::DOUBLE                                    AS pnl,
               (sum(fee) + sum(coalesce(builder_fee, 0)))::DOUBLE  AS fees,
               sum(notional)::DOUBLE                               AS notional,
               count(DISTINCT day)                                 AS active_days,
               sum(n_fills)                                        AS n_fills,
               sum(n_taker)::DOUBLE / nullif(sum(n_fills),0)       AS taker_share,
               count(DISTINCT coin)                                AS coin_breadth,
               sum(CASE WHEN coin IN ('BTC','ETH','SOL') THEN notional ELSE 0 END)::DOUBLE
                   / nullif(sum(notional),0)::DOUBLE               AS majors_share,
               sum(n_liq)                                          AS n_liq
        FROM read_parquet('{lake.WCD}')
        WHERE day BETWEEN {DAY_LO} AND {DAY_HI} AND wallet IN ({wl})
        GROUP BY wallet
    """).fetchall()
    ope = con.execute(f"""
        SELECT wallet,
               count(*)                                            AS n_entries,
               count(DISTINCT date)                                AS entry_days,
               median(notl)::DOUBLE                                AS med_entry_notl,
               avg(CASE WHEN notl < {DUST_USD} THEN 1.0 ELSE 0.0 END) AS dust_share
        FROM read_parquet('{lake.OPE}')
        WHERE date BETWEEN DATE '2025-08-01' AND DATE '2026-06-30' AND wallet IN ({wl})
        GROUP BY wallet
    """).fetchall()
    prof: dict[str, dict] = {}
    for w, pnl, fees, notl, ad, nf, tk, cb, mj, nl in wcd:
        prof[w] = dict(pnl=pnl, fees=fees, notional=notl, active_days=ad,
                       fills_per_day=nf / ad if ad else 0.0, taker_share=tk,
                       coin_breadth=cb, majors_share=mj, n_liq=nl)
    for w, ne, ed, mn, ds in ope:
        prof.setdefault(w, {}).update(entries_per_day=ne / ed if ed else 0.0,
                                      med_entry_notl=mn, dust_share=ds, n_entries=ne)
    return prof


def kmeans(X: np.ndarray, k: int, seed: int, iters: int = 200) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # kmeans++ init
    C = X[rng.integers(len(X)), None]
    for _ in range(k - 1):
        d2 = ((X[:, None] - C[None]) ** 2).sum(-1).min(1)
        C = np.vstack([C, X[rng.choice(len(X), p=d2 / d2.sum())]])
    lab = np.zeros(len(X), int)
    for _ in range(iters):
        new = ((X[:, None] - C[None]) ** 2).sum(-1).argmin(1)
        if (new == lab).all():
            break
        lab = new
        for j in range(k):
            if (lab == j).any():
                C[j] = X[lab == j].mean(0)
    return lab


def main() -> None:
    cohort = load_cohort()
    decay = load_decay()
    wallets = sorted(cohort)
    print(f"distinct arm-T wallets: {len(wallets)}")
    prof = lake_profiles(wallets)

    def med_or_none(xs):
        xs = [x for x in xs if x is not None]
        return float(np.median(xs)) if xs else None

    rows = []
    for w in wallets:
        c = cohort[w]
        p = prof.get(w, {})
        d = decay.get(w, {})
        rows.append({
            "wallet": w,
            "n_selected": len(c["months"]),
            "months": c["months"],
            "form_t_med": med_or_none(c["t"]),
            "form_z_med": med_or_none(c["z"]),
            "form_nd_med": med_or_none(c["nd"]),
            "form_capday_med": med_or_none(c["capday"]),
            "form_scale_med": med_or_none(c["scale"]),
            "large_any": any(c["large"]),
            **{k: p.get(k) for k in ("pnl", "fees", "notional", "active_days", "fills_per_day",
                                     "taker_share", "coin_breadth", "majors_share", "n_liq",
                                     "entries_per_day", "med_entry_notl", "dust_share", "n_entries")},
            "copy_mk_bp_wtd": d.get("copy_mk_bp_wtd"),
            "copy_n_total": d.get("copy_n_total", 0),
            "quadrants": d.get("quadrants", {}),
        })

    # ---- clustering (log/rank-normalized features) ----
    feat_names = ["log_notional", "log_med_entry", "active_days", "log_fills_day",
                  "taker_share", "log_breadth", "majors_share", "dust_share"]
    ok = [r for r in rows if r["notional"] and r["med_entry_notl"] is not None]
    X = np.array([[np.log10(max(r["notional"], 1.0)),
                   np.log10(max(r["med_entry_notl"] or 1.0, 1.0)),
                   r["active_days"] or 0,
                   np.log10(max(r["fills_per_day"] or 0, 0.1)),
                   r["taker_share"] or 0.0,
                   np.log10(max(r["coin_breadth"] or 1, 1)),
                   r["majors_share"] or 0.0,
                   r["dust_share"] or 0.0] for r in ok])
    Z = (X - X.mean(0)) / X.std(0)
    lab = kmeans(Z, K, SEED)
    for r, l in zip(ok, lab):
        r["cluster"] = int(l)
    for r in rows:
        r.setdefault("cluster", None)
        r["archetype"] = ARCHETYPES[r["cluster"] if r["cluster"] is not None else -1]

    # cluster medians for labeling
    clusters = {}
    for j in list(range(K)) + [-1]:
        sub = [r for r in ok if r["cluster"] == j] if j >= 0 else [r for r in rows if r["cluster"] is None]
        if not sub:
            continue
        def med(k):
            xs = [r[k] for r in sub if r[k] is not None and not (isinstance(r[k], float) and np.isnan(r[k]))]
            return float(np.median(xs)) if xs else None
        copy_mks = [r["copy_mk_bp_wtd"] for r in sub if r["copy_mk_bp_wtd"] is not None]
        clusters[j] = {
            "label": ARCHETYPES.get(j, f"cluster_{j}"),
            "n": len(sub),
            "n_selected_med": med("n_selected"),
            "notional_med": med("notional"),
            "pnl_med": med("pnl"),
            "fees_med": med("fees"),
            "active_days_med": med("active_days"),
            "fills_per_day_med": med("fills_per_day"),
            "taker_share_med": med("taker_share"),
            "coin_breadth_med": med("coin_breadth"),
            "majors_share_med": med("majors_share"),
            "med_entry_notl_med": med("med_entry_notl"),
            "dust_share_med": med("dust_share"),
            "entries_per_day_med": med("entries_per_day"),
            "n_liq_total": int(sum(r["n_liq"] or 0 for r in sub)),
            "copy_mk_bp_wtd_med": float(np.median(copy_mks)) if copy_mks else None,
            "copy_mk_n_wallets": len(copy_mks),
            "copy_n_total": int(sum(r["copy_n_total"] for r in sub)),
            "copy_mk_bp_pooled": (
                float(sum(r["copy_mk_bp_wtd"] * r["copy_n_total"] for r in sub if r["copy_mk_bp_wtd"] is not None)
                      / max(sum(r["copy_n_total"] for r in sub if r["copy_mk_bp_wtd"] is not None), 1))
                if copy_mks else None),
        }

    out = {
        "label": "DESCRIPTIVE census — arm T, 8 folds, no inference",
        "config": {"majors": sorted(MAJORS), "dust_usd": DUST_USD, "window": [DAY_LO, DAY_HI],
                   "kmeans_k": K, "seed": SEED, "features": feat_names},
        "n_wallets": len(wallets),
        "n_memberships": sum(r["n_selected"] for r in rows),
        "clusters": clusters,
        "wallets": rows,
    }
    OUT.write_text(json.dumps(out, indent=1, default=str))
    print("wrote", OUT)
    for j, c in clusters.items():
        print(j, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()})


if __name__ == "__main__":
    main()
