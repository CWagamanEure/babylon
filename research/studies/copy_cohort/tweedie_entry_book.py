"""Entry-level (per-trade) shape of the arm-T copy book — the 'sharper question': is the edge a
steady grind or a few-big-winners lottery? Keeps every forward entry (does NOT collapse to per-wallet
means, and reports RAW, un-winsorized, so the tail is visible). Descriptive, burned folds.

Metrics on the arm-T frozen roster's forward test-month flat-open 8h alt markouts:
  - per-TRADE hit rate (fraction of individual entries > 0)  [vs the wallet-level rate we had]
  - return distribution: mean, median, p10/p90, and the mean-vs-median gap (right-skew tell)
  - PnL concentration: share of total NET book PnL from the top 1% / 5% / 10% of trades by
    contribution, and leave-out-top-N (does the book survive removing the biggest winners?)
  - two dollar books: equal-$ per entry, and actual-notional-sized.
"""
from __future__ import annotations

import glob
import json

import numpy as np

from research.studies.copy_cohort import alt_fresh_validate as afv
from research.studies.copy_cohort import lake


def _pct_shares(contrib):
    """Share of total (net) PnL held by the top q% of entries by contribution."""
    c = np.sort(contrib)[::-1]
    tot = c.sum()
    out = {}
    n = c.size
    for q in (0.01, 0.05, 0.10):
        k = max(1, int(np.ceil(q * n)))
        out[f"top{int(q*100)}pct"] = float(c[:k].sum() / tot) if tot != 0 else None
    return out


def _leave_out_top(contrib, ks=(1, 3, 5, 10)):
    order = np.argsort(contrib)[::-1]
    tot = contrib.sum()
    return {f"drop_top{k}": float(tot - contrib[order[:k]].sum()) for k in ks}


def main():
    cohorts = json.load(open("data/derived/copy_cohort/alt_universe_cohorts.json"))
    con = lake.connect(mem="4GB")
    MK, NOTL, WAL, FOLD = [], [], [], []
    for pf in sorted(glob.glob("data/derived/copy_cohort/informedness/fold=*/pool.parquet")):
        fold = int(pf.split("fold=")[1].split("/")[0])
        if str(fold) not in cohorts["folds"]:
            continue
        wallets = list(cohorts["folds"][str(fold)]["arms"]["T"]["members"].keys())
        d = afv._forward_entries(con, fold, wallets)
        if d is None:
            continue
        mk = afv._np(d["mk"])
        notl = afv._np(d["notl"])
        wal = d["wallet"].astype(str)
        ok = np.isfinite(mk) & np.isfinite(notl) & (notl > 0)
        MK.append(mk[ok]); NOTL.append(notl[ok]); WAL.append(wal[ok])
        FOLD.append(np.full(int(ok.sum()), fold))
    mk = np.concatenate(MK); notl = np.concatenate(NOTL)
    wal = np.concatenate(WAL); fold = np.concatenate(FOLD)
    n = mk.size

    # per-trade distribution (RAW)
    dist = {
        "n_entries": int(n), "n_wallets": int(np.unique(wal).size),
        "per_trade_hit_rate": float((mk > 0).mean()),
        "mean_bp": float(mk.mean()), "median_bp": float(np.median(mk)),
        "p10_bp": float(np.percentile(mk, 10)), "p90_bp": float(np.percentile(mk, 90)),
        "p99_bp": float(np.percentile(mk, 99)), "min_bp": float(mk.min()), "max_bp": float(mk.max()),
    }

    # dollar books: contribution_i = size_i * mk_i/1e4  ($ pnl per entry)
    books = {}
    for name, size in (("equal_$1k", np.full(n, 1000.0)), ("notional", notl)):
        contrib = size * mk / 1e4
        net = float(contrib.sum())
        books[name] = {
            "net_usd": net, "gross_turnover_usd": float(size.sum()),
            "net_bp_on_turnover": float(net / size.sum() * 1e4),
            "concentration": _pct_shares(contrib),
            "leave_out_top_winners_net_usd": _leave_out_top(contrib),
            "n_positive_entries": int((contrib > 0).sum()),
        }

    report = {"stamp": "descriptive, burned folds, arm-T roster forward 8h alt markout, RAW (no winsor)",
              "distribution": dist, "dollar_books": books}
    json.dump(report, open("data/derived/copy_cohort/tweedie_entry_book_report.json", "w"), indent=1)

    print(f"ENTRIES n={dist['n_entries']}  wallets={dist['n_wallets']}")
    print(f"PER-TRADE hit rate = {dist['per_trade_hit_rate']*100:.1f}%   "
          f"mean={dist['mean_bp']:.1f}bp  median={dist['median_bp']:.1f}bp  "
          f"(mean>>median ⇒ right-skew/lottery)")
    print(f"tail: p90={dist['p90_bp']:.0f}  p99={dist['p99_bp']:.0f}  max={dist['max_bp']:.0f}  "
          f"p10={dist['p10_bp']:.0f}  min={dist['min_bp']:.0f}")
    for name, b in books.items():
        c = b["concentration"]
        lo = b["leave_out_top_winners_net_usd"]
        print(f"\n[{name}] net=${b['net_usd']:,.0f} on ${b['gross_turnover_usd']:,.0f} turnover "
              f"({b['net_bp_on_turnover']:.1f}bp)")
        print(f"  top1%={c['top1pct']:.2f} top5%={c['top5pct']:.2f} top10%={c['top10pct']:.2f} "
              f"of net PnL")
        print(f"  drop-top: {', '.join(f'{k}=${v:,.0f}' for k,v in lo.items())}")


if __name__ == "__main__":
    main()
