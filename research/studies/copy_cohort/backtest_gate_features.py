"""Formation features for the ARCHETYPE GATE variant of backtest_book.py (DESCRIPTIVE lane).

Per (fold, wallet) for the Book-A K100 liquid-alt selections: coin breadth, taker share,
active days (distinct calendar days AND wallet-coin-day rows) over the 3 formation months
strictly before the fold — from lake wallet_coin_day. Cached to
data/derived/copy_cohort/backtest_gate_features.parquet.

Run: .venv/bin/python research/studies/copy_cohort/backtest_gate_features.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path = [p for p in sys.path if not p.endswith("copy_cohort")]

import importlib.util
import json

ROOT = Path("/Users/corywagamaneure/bablyon")
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("lake", ROOT / "research/studies/copy_cohort/lake.py")
lake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lake)

from research.lib.cv import MONTHS  # noqa: E402

import duckdb  # noqa: E402
import numpy as np  # noqa: E402

DERIVED = ROOT / "data/derived/copy_cohort"
OUT = DERIVED / "backtest_gate_features.parquet"
FOLDS = MONTHS[3:]


def _top100(fold: int, frozen: set[str]) -> list[str]:
    con = duckdb.connect()
    d = con.execute(f"""SELECT wallet, t_stat
                        FROM read_parquet('{(DERIVED / 'informedness' / f'fold={fold}' / 'pool.parquet').as_posix()}')
                        WHERE t_stat IS NOT NULL""").fetchnumpy()
    con.close()
    w = d["wallet"].astype(str)
    t = np.asarray(d["t_stat"], float)
    keep = np.array([x not in frozen for x in w])
    w, t = w[keep], t[keep]
    order = np.lexsort((w, -t))
    return w[order[:100]].tolist()


def main() -> None:
    frozen = set(json.loads((DERIVED / "frozen_alt_universe.json").read_text())["distinct_wallets"])
    con = lake.connect(mem="6GB", threads=4)
    rows = []
    for fold in FOLDS:
        i = MONTHS.index(fold)
        months = MONTHS[i - 3:i]
        wallets = _top100(fold, frozen)
        wl = ",".join(f"'{w}'" for w in wallets)
        globs = [lake.wcd_month_glob(m) for m in months]
        res = con.execute(f"""
            SELECT wallet,
                   count(DISTINCT day)                 AS f_nd,
                   count(*)                            AS f_ncd,
                   count(DISTINCT coin)                AS f_coin_breadth,
                   sum(n_taker)::DOUBLE / sum(n_fills) AS f_taker_share
            FROM read_parquet({globs})
            WHERE wallet IN ({wl})
            GROUP BY wallet
        """).fetchall()
        got = {r[0] for r in res}
        for w, nd, ncd, cb, tk in res:
            rows.append({"fold": fold, "wallet": w, "f_nd": nd, "f_ncd": ncd,
                         "f_coin_breadth": cb, "f_taker_share": tk})
        for w in wallets:
            if w not in got:
                rows.append({"fold": fold, "wallet": w, "f_nd": 0, "f_ncd": 0,
                             "f_coin_breadth": 0, "f_taker_share": None})
        print(fold, "done:", len(res), "/", len(wallets), flush=True)
    tmp = OUT.with_suffix(".jsonl")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    lc = duckdb.connect()
    lc.execute(f"COPY (SELECT * FROM read_json_auto('{tmp.as_posix()}')) TO '{OUT.as_posix()}' (FORMAT PARQUET)")
    tmp.unlink()
    print("wrote", OUT, len(rows), "rows")


if __name__ == "__main__":
    main()
