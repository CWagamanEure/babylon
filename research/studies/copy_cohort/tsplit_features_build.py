"""HYPOTHESIS-GENERATION: formation-side features separating arm-T-only vs T∩P memberships.

Groups were defined USING forward returns (T-only forward +49bp vs T∩P +2.7bp), so any feature
found here is a hypothesis only — requires registered confirmation on new data.

Builds per-(fold, wallet) formation features (3 formation months, strictly before fold) from the
incerto lake (wallet_coin_day + open_entries) plus the cohort-json selector stats, labels each
T membership T-only vs T∩P (P-only as contrast), writes:
  data/derived/copy_cohort/tsplit_features.parquet
Run: .venv/bin/python research/studies/copy_cohort/tsplit_features_build.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# copy_cohort/selectors.py shadows stdlib `selectors` when this dir is sys.path[0]
sys.path = [p for p in sys.path if not p.endswith("copy_cohort")]

import importlib.util
import json

ROOT = Path("/Users/corywagamaneure/bablyon")
spec = importlib.util.spec_from_file_location("lake", ROOT / "research/studies/copy_cohort/lake.py")
lake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lake)

MAJORS = ("BTC", "ETH", "SOL")
OUT = ROOT / "data/derived/copy_cohort/tsplit_features.parquet"


def main() -> None:
    cohorts = json.load(open(ROOT / "data/derived/copy_cohort/alt_universe_cohorts.json"))
    con = lake.connect(mem="6GB", threads=4)

    rows = []  # one row per membership (fold, wallet, group)
    for fold, fd in sorted(cohorts["folds"].items()):
        months = fd["formation_months"]
        T = fd["arms"]["T"]["members"]
        P = fd["arms"]["P"]["members"]
        Tset, Pset = set(T), set(P)
        wallets = sorted(Tset | Pset)
        wl = ",".join(f"'{w}'" for w in wallets)

        wcd_globs = [lake.wcd_month_glob(m) for m in months]
        ope_globs = [lake.ope_month_glob(m) for m in months]

        wcd = con.execute(f"""
            SELECT wallet,
                   count(DISTINCT day)                    AS f_nd,
                   sum(n_fills)                           AS f_n_fills,
                   sum(n_taker)::DOUBLE / sum(n_fills)    AS f_taker_share,
                   count(DISTINCT coin)                   AS f_coin_breadth,
                   sum(notional)::DOUBLE                  AS f_notional,
                   sum(CASE WHEN coin IN {MAJORS} THEN notional ELSE 0 END)::DOUBLE
                       / sum(notional)::DOUBLE            AS f_majors_share,
                   sum(n_open_flat)                       AS f_n_open_flat,
                   sum(n_liq)                             AS f_n_liq,
                   sum(pnl)::DOUBLE                       AS f_pnl,
                   sum(fee + builder_fee)::DOUBLE         AS f_fee
            FROM read_parquet({wcd_globs})
            WHERE wallet IN ({wl})
            GROUP BY wallet
        """).fetchall()
        wcd_cols = ["f_nd", "f_n_fills", "f_taker_share", "f_coin_breadth", "f_notional",
                    "f_majors_share", "f_n_open_flat", "f_n_liq", "f_pnl", "f_fee"]
        wcd_map = {r[0]: dict(zip(wcd_cols, r[1:])) for r in wcd}

        ope = con.execute(f"""
            SELECT wallet,
                   count(*)                                            AS e_n_entries,
                   count(DISTINCT date)                                AS e_nd,
                   median(notl)::DOUBLE                                AS e_med_notl,
                   quantile_cont(notl, 0.9)::DOUBLE                    AS e_p90_notl,
                   avg(CASE WHEN notl < 100 THEN 1.0 ELSE 0.0 END)     AS e_dust_share
            FROM read_parquet({ope_globs})
            WHERE wallet IN ({wl})
            GROUP BY wallet
        """).fetchall()
        ope_cols = ["e_n_entries", "e_nd", "e_med_notl", "e_p90_notl", "e_dust_share"]
        ope_map = {r[0]: dict(zip(ope_cols, r[1:])) for r in ope}

        for w in wallets:
            in_t, in_p = w in Tset, w in Pset
            group = "T_only" if (in_t and not in_p) else ("T_and_P" if in_t else "P_only")
            rec = (T.get(w) or P.get(w))
            row = {
                "fold": int(fold), "wallet": w, "group": group,
                "sel_t": rec["t"], "sel_z": rec["z"], "sel_p_informed": rec["p_informed"],
                "sel_nd": rec["nd"], "sel_scale_med_notl": rec["scale_med_notl"],
                "sel_large": bool(rec["large"]), "sel_metric_capday": rec["metric_capday"],
            }
            wc = wcd_map.get(w, {})
            op = ope_map.get(w, {})
            row.update({c: wc.get(c) for c in wcd_cols})
            row.update({c: op.get(c) for c in ope_cols})
            # derived rates
            nd = row["f_nd"] or None
            row["f_fills_per_day"] = (row["f_n_fills"] / nd) if nd else None
            row["f_notional_per_day"] = (row["f_notional"] / nd) if nd else None
            row["f_openflat_per_day"] = (row["f_n_open_flat"] / nd) if nd else None
            end = row["e_nd"] or None
            row["e_entries_per_day"] = (row["e_n_entries"] / end) if end else None
            rows.append(row)
        print(fold, "done:", len(wallets), "wallets,", len(wcd_map), "wcd,", len(ope_map), "ope", flush=True)

    # write parquet via duckdb from json lines (no pandas)
    tmp = OUT.with_suffix(".jsonl")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    con.execute(f"COPY (SELECT * FROM read_json_auto('{tmp}')) TO '{OUT}' (FORMAT PARQUET)")
    tmp.unlink()
    print("wrote", OUT, len(rows), "rows")


if __name__ == "__main__":
    main()
