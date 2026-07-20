"""MAJORS counterpart of tweedie_entry_book: per-trade shape of the majors-native K30 @8h book.
Reuses majors_native's selection (majors-only capped-PnL t-stat top-30) + entry cache (majors flat
taker opens, notl>=$250, all horizons). Same RAW per-trade diagnostics as the alt version, on mk8.
Descriptive, burned folds.
"""
from __future__ import annotations

import json

import numpy as np

from research.studies.copy_cohort import lake
from research.studies.copy_cohort.majors_native import (
    FOLDS, FROZEN, _fold_entries, _select_top100,
)
from research.studies.copy_cohort.tweedie_entry_book import _leave_out_top, _pct_shares


def main():
    frozen = set(json.loads(FROZEN.read_text())["distinct_wallets"])
    con = lake.connect(mem="4GB")
    MK, NOTL, WAL = [], [], []
    for f in FOLDS:
        top30 = _select_top100(con, f, frozen)[:30]
        d = _fold_entries(con, f, top30)
        mk8 = np.asarray(d["mk8"], float)
        notl = np.asarray(d["notl"], float)
        wal = d["wallet"].astype(str)
        rk = np.asarray(d["rk"], int)
        keep = (rk < 30) & np.isfinite(mk8) & np.isfinite(notl) & (notl > 0)  # entries cache is top-100
        MK.append(mk8[keep]); NOTL.append(notl[keep]); WAL.append(wal[keep])
    mk = np.concatenate(MK); notl = np.concatenate(NOTL); wal = np.concatenate(WAL)
    n = mk.size

    dist = {
        "n_entries": int(n), "n_wallets": int(np.unique(wal).size),
        "per_trade_hit_rate": float((mk > 0).mean()),
        "mean_bp": float(mk.mean()), "median_bp": float(np.median(mk)),
        "p10_bp": float(np.percentile(mk, 10)), "p90_bp": float(np.percentile(mk, 90)),
        "p99_bp": float(np.percentile(mk, 99)), "min_bp": float(mk.min()), "max_bp": float(mk.max()),
    }
    books = {}
    for name, size in (("equal_$1k", np.full(n, 1000.0)), ("notional", notl)):
        contrib = size * mk / 1e4
        books[name] = {
            "net_usd": float(contrib.sum()), "gross_turnover_usd": float(size.sum()),
            "net_bp_on_turnover": float(contrib.sum() / size.sum() * 1e4),
            "concentration": _pct_shares(contrib),
            "leave_out_top_winners_net_usd": _leave_out_top(contrib),
        }
    report = {"stamp": "descriptive, burned folds, majors-native K30 @8h, RAW (no winsor)",
              "distribution": dist, "dollar_books": books}
    json.dump(report, open("data/derived/copy_cohort/majors_entry_book_report.json", "w"), indent=1)

    print(f"MAJORS K30@8h  ENTRIES n={dist['n_entries']}  wallets={dist['n_wallets']}")
    print(f"PER-TRADE hit rate = {dist['per_trade_hit_rate']*100:.1f}%   "
          f"mean={dist['mean_bp']:.1f}bp  median={dist['median_bp']:.1f}bp")
    print(f"tail: p90={dist['p90_bp']:.0f}  p99={dist['p99_bp']:.0f}  max={dist['max_bp']:.0f}  "
          f"p10={dist['p10_bp']:.0f}  min={dist['min_bp']:.0f}")
    for name, b in books.items():
        c = b["concentration"]; lo = b["leave_out_top_winners_net_usd"]
        print(f"\n[{name}] net=${b['net_usd']:,.0f} on ${b['gross_turnover_usd']:,.0f} "
              f"({b['net_bp_on_turnover']:.1f}bp)")
        print(f"  top1%={c['top1pct']:.2f} top5%={c['top5pct']:.2f} top10%={c['top10pct']:.2f} of net")
        print(f"  drop-top: {', '.join(f'{k}=${v:,.0f}' for k,v in lo.items())}")


if __name__ == "__main__":
    main()
