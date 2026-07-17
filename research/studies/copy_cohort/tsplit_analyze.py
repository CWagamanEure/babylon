"""HYPOTHESIS-GENERATION analysis: which formation features separate T-only from T∩P.

Reads data/derived/copy_cohort/tsplit_features.parquet; Mann-Whitney (normal approx, tie-corrected)
per feature T-only vs T∩P, rank-biserial effect size; P-only medians as contrast; simple
one-variable explanation check; writes research/studies/copy_cohort/TSPLIT_HYPOTHESIS.md.
Run: .venv/bin/python research/studies/copy_cohort/tsplit_analyze.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path = [p for p in sys.path if not p.endswith("copy_cohort")]

import math

import duckdb
import numpy as np

ROOT = Path("/Users/corywagamaneure/bablyon")
PARQ = ROOT / "data/derived/copy_cohort/tsplit_features.parquet"
MD = ROOT / "research/studies/copy_cohort/TSPLIT_HYPOTHESIS.md"

FEATURES = [
    # (column, label)
    ("sel_t", "selector t-stat"),
    ("sel_z", "selector z"),
    ("sel_p_informed", "p_informed"),
    ("sel_nd", "selector nd (active days)"),
    ("sel_scale_med_notl", "scale_med_notl ($)"),
    ("sel_metric_capday", "capday metric"),
    ("f_nd", "formation active days (wcd)"),
    ("f_n_fills", "n fills (3mo)"),
    ("f_fills_per_day", "fills / active day"),
    ("f_taker_share", "taker share"),
    ("f_coin_breadth", "coin breadth"),
    ("f_notional", "total notional ($)"),
    ("f_notional_per_day", "notional / active day ($)"),
    ("f_majors_share", "majors (BTC/ETH/SOL) notional share"),
    ("f_n_open_flat", "n open-from-flat"),
    ("f_openflat_per_day", "open-from-flat / day"),
    ("f_n_liq", "n liquidation fills"),
    ("f_pnl", "pnl total ($)"),
    ("f_fee", "fee total ($)"),
    ("e_n_entries", "n entries (3mo)"),
    ("e_entries_per_day", "entries / active day"),
    ("e_med_notl", "median entry notional ($)"),
    ("e_p90_notl", "p90 entry notional ($)"),
    ("e_dust_share", "dust entry share (<$100)"),
]


def mannwhitney(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Two-sided MW U test, normal approx with tie correction. Returns (p, rank_biserial)."""
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    allv = np.concatenate([x, y])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv))
    sv = allv[order]
    i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    r1 = ranks[:n1].sum()
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    n = n1 + n2
    _, cnt = np.unique(allv, return_counts=True)
    tie = (cnt**3 - cnt).sum()
    var = n1 * n2 / 12.0 * ((n + 1) - tie / (n * (n - 1)))
    if var <= 0:
        return 1.0, 0.0
    zval = (u1 - mu - (0.5 if u1 > mu else -0.5)) / math.sqrt(var)
    p = 2.0 * 0.5 * math.erfc(abs(zval) / math.sqrt(2.0))
    rb = 2.0 * u1 / (n1 * n2) - 1.0  # >0: group1 (T-only) larger
    return p, rb


def main() -> None:
    con = duckdb.connect()
    cols = ["fold", "wallet", '"group"'] + [c for c, _ in FEATURES]
    data = con.execute(f"SELECT {','.join(cols)} FROM read_parquet('{PARQ}')").fetchall()
    arr = {c: np.array([r[i + 3] for r in data], dtype=object) for i, (c, _) in enumerate(FEATURES)}
    grp = np.array([r[2] for r in data])
    masks = {g: grp == g for g in ("T_only", "T_and_P", "P_only")}
    print({g: int(m.sum()) for g, m in masks.items()})

    def vals(col, g):
        v = arr[col][masks[g]]
        v = np.array([float(x) for x in v if x is not None and not (isinstance(x, float) and math.isnan(x))])
        return v

    results = []
    for col, label in FEATURES:
        xt = vals(col, "T_only")
        xi = vals(col, "T_and_P")
        xp = vals(col, "P_only")
        p, rb = mannwhitney(xt, xi)
        results.append({
            "col": col, "label": label,
            "med_Tonly": float(np.median(xt)) if len(xt) else float("nan"),
            "med_TandP": float(np.median(xi)) if len(xi) else float("nan"),
            "med_Ponly": float(np.median(xp)) if len(xp) else float("nan"),
            "n_Tonly": len(xt), "n_TandP": len(xi),
            "p": p, "rb": rb,
        })
    results.sort(key=lambda r: (math.isnan(r["p"]), r["p"]))

    def fmt(v):
        if isinstance(v, float) and math.isnan(v):
            return "nan"
        a = abs(v)
        if a >= 1000:
            return f"{v:,.0f}"
        if a >= 10:
            return f"{v:.1f}"
        return f"{v:.3g}"

    print(f"{'feature':38s} {'T-only med':>12s} {'T∩P med':>12s} {'P-only med':>12s} {'p(MW)':>8s} {'rb':>6s}")
    for r in results:
        print(f"{r['label']:38s} {fmt(r['med_Tonly']):>12s} {fmt(r['med_TandP']):>12s} "
              f"{fmt(r['med_Ponly']):>12s} {r['p']:8.2g} {r['rb']:6.2f}")

    # ---- one-variable explanation check on the top features + candidate rule search ----
    # For each top feature, best single threshold (by balanced accuracy) separating T-only vs T∩P.
    print("\nsingle-threshold separation (balanced accuracy) for top-8 features:")
    thr_rows = []
    for r in results[:8]:
        col = r["col"]
        xt, xi = vals(col, "T_only"), vals(col, "T_and_P")
        cand = np.unique(np.concatenate([xt, xi]))
        best = (0.5, None, None)
        for c in cand:
            for sgn in (1, -1):  # T-only = feature*sgn <= c*sgn
                tp = (sgn * xt <= sgn * c).mean()
                tn = (sgn * xi > sgn * c).mean()
                ba = 0.5 * (tp + tn)
                if ba > best[0]:
                    best = (ba, c, "<=" if sgn == 1 else ">=")
        thr_rows.append((r["label"], col, best))
        print(f"  {r['label']:38s} T-only {best[2]} {fmt(best[1])}  bal-acc {best[0]:.2f}")

    # save markdown
    lines = [
        "# T-only vs T∩P formation-feature split — HYPOTHESIS-GENERATION",
        "",
        "**⚠️ HYPOTHESIS-GENERATION ONLY.** The groups (T-only forward robust +49bp vs T∩P +2.7bp)",
        "were defined *using forward returns*; every feature below was screened against those",
        "labels, ~24 features tested with no multiplicity control. Any candidate rule REQUIRES",
        "registered confirmation on new (post-202606) data before it is evidence of anything.",
        "",
        f"Unit = arm-T membership (fold, wallet), folds 202511–202606: "
        f"{int(masks['T_only'].sum())} T-only, {int(masks['T_and_P'].sum())} T∩P "
        f"({int(masks['P_only'].sum())} P-only shown as contrast — the −33bp group).",
        "Formation features = 3 formation months strictly before the fold (leakage-safe by",
        "construction); sources: lake wallet_coin_day, open_entries, cohort-json selector stats.",
        "Table: `data/derived/copy_cohort/tsplit_features.parquet`; build/analyze scripts alongside this file.",
        "",
        "| feature | T-only med | T∩P med | P-only med | MW p | rank-biserial |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(f"| {r['label']} | {fmt(r['med_Tonly'])} | {fmt(r['med_TandP'])} | "
                     f"{fmt(r['med_Ponly'])} | {r['p']:.2g} | {r['rb']:+.2f} |")
    lines += ["", "## Single-threshold separation (top features)", ""]
    for label, col, (ba, c, op) in thr_rows:
        lines.append(f"- {label}: T-only {op} {fmt(c)} → balanced accuracy {ba:.2f}")
    MD.write_text("\n".join(lines) + "\n")
    print("wrote", MD)


if __name__ == "__main__":
    main()
