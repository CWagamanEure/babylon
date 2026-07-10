"""ATTACK 4 — does p1 realized-PnL rank predict p2 realized-PnL? (the actual copy-trade quantity, not timing_alpha)
Per (wallet,coin): sum realized_net_usd per period; also per-notional bp. Rank persistence + top-cohort OOS.

    python -m research.data.persist_pnl 2026-02-01
"""
from __future__ import annotations
import sys, math
import numpy as np
import duckdb
from .markout import COINS, REPO_ROOT

DATA_END = "epoch_ms(TIMESTAMP '2026-06-29 00:00:00')"
MIN_EP = 20  # min episodes per period to be evaluable


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT / '.tmp'}'")
    return c


def _period(con, tag, lo, hi):
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    con.execute(f"""CREATE OR REPLACE TEMP TABLE {tag} AS
      SELECT wallet, coin, count(*) n_ep,
             sum(realized_net_usd) pnl_net,
             sum(realized_net_usd)/nullif(sum(initial_notional_usd),0)*1e4 pnl_bp,
             sum(initial_notional_usd) notl
      FROM read_parquet('{ep}', hive_partitioning=true)
      WHERE coin IN ({','.join(chr(39)+c+chr(39) for c in COINS)}) AND NOT inherited_basis
        AND close_ts IS NOT NULL AND close_ts >= {lo} AND close_ts < {hi}
      GROUP BY 1,2""")


def run(sp):
    con = _con()
    S = f"epoch_ms(TIMESTAMP '{sp} 00:00:00')"
    _period(con, "p1", "0", S); _period(con, "p2", S, DATA_END)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE j AS
      SELECT p1.wallet, p1.coin, p1.n_ep n1, p1.pnl_net net1, p1.pnl_bp bp1, p1.notl notl1,
             p2.n_ep n2, p2.pnl_net net2, p2.pnl_bp bp2, p2.notl notl2
      FROM p1 JOIN p2 USING(wallet,coin)
      WHERE p1.n_ep>={MIN_EP} AND p2.n_ep>={MIN_EP}""")
    d = con.execute("SELECT net1,net2,bp1,bp2 FROM j WHERE bp1 IS NOT NULL AND bp2 IS NOT NULL").fetchnumpy()
    net1, net2 = np.asarray(d["net1"], float), np.asarray(d["net2"], float)
    bp1, bp2 = np.asarray(d["bp1"], float), np.asarray(d["bp2"], float)
    n = len(net1)
    print(f"\n=== PnL persistence, split {sp}, wallet-coins active(>= {MIN_EP} eps) both periods: {n:,} ===")

    def rho(a, b):
        r1 = np.argsort(np.argsort(a)); r2 = np.argsort(np.argsort(b))
        rr = float(np.corrcoef(r1, r2)[0, 1])
        t = rr * math.sqrt((n - 2) / max(1e-9, 1 - rr * rr))
        return rr, math.erfc(abs(t) / math.sqrt(2))

    for name, a, b in [("net$ USD", net1, net2), ("pnl per notional (bp)", bp1, bp2)]:
        rr, p = rho(a, b)
        print(f" Spearman {name:22s}: rho={rr:+.3f} p={p:.2e}")

    # top-cohort OOS: select p1 winners (net1>0 & bp1>0), measure p2
    for name, sel_a, eval_b in [("net$", net1, net2), ("bp", bp1, bp2)]:
        for qname, thr in [("p1>0", 0.0), ("top-decile p1", np.quantile(sel_a, 0.9)),
                           ("top-quartile p1", np.quantile(sel_a, 0.75))]:
            mask = sel_a > thr
            sub = eval_b[mask]
            if len(sub) < 10:
                continue
            m = float(np.mean(sub)); sem = float(np.std(sub, ddof=1)) / math.sqrt(len(sub))
            signpos = float(np.mean(sub > 0)) * 100
            print(f" select {name:4s} {qname:16s} n={len(sub):>4} -> p2 mean={m:>+10.2f} "
                  f"CI[{m-1.96*sem:>+10.2f},{m+1.96*sem:>+10.2f}] sgn+={signpos:.0f}%")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "2026-02-01")
