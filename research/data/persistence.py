"""OOS PERSISTENCE — does entry-timing skill measured in period 1 predict skill in period 2 (never selected on)?

The deployment question. Split time at SPLIT; compute period-local timing_alpha (global-μ variant, so
regime/week-selection counts as skill) per (wallet,coin,horizon), using ONLY that period's episodes and ONLY
that period's minutes for μ (t+h ≤ period_end) — no cross-period leakage. Two readouts per horizon:

  (1) RANK PERSISTENCE: Spearman(p1_est, p2_est) across wallets active in both — does past rank-predict future?
  (2) DEPLOYMENT SIM: select skilled on p1 (est>0 & lb>0, n_weeks>=6); measure the selected cohort's p2 mean
      timing_alpha + CI (across wallets = cross-unit) + sign fraction (binomial vs 50%) + LIFT over non-selected.
      MDE reported so a flat result is an EARNED null only if MDE <= care-about (CLAUDE.md gate), else INCONCLUSIVE.

    python -m research.data.persistence
"""
from __future__ import annotations

import math
import numpy as np
import duckdb

from .markout import HORIZONS, COINS, REPO_ROOT
from .features_markout import ENTRY_LAG_MAX_S

import sys
HZ = ["1h", "2h", "4h", "8h"]
SPLIT_DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-02-01"
SPLIT = f"epoch_ms(TIMESTAMP '{SPLIT_DATE} 00:00:00')"
P1 = ("0", SPLIT)
P2 = (SPLIT, "epoch_ms(TIMESTAMP '2026-06-29 00:00:00')")
MIN_WK_SEL = 6     # power gate for p1 selection
MIN_WK_EVAL = 3    # min p2 weeks to be evaluable
CARE_BP = 8.0      # care-about effect size (from the screen)


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT / '.tmp'}'")
    return c


def _period_sql(coin, hname, lo, hi):
    h = HORIZONS[hname]
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
    return f"""
    WITH mu_g AS (SELECT avg(fwd_ret_{hname}) mug FROM read_parquet('{fwd}')
                  WHERE fwd_ret_{hname} IS NOT NULL AND ts >= {lo} AND (ts + {h}) <= {hi}),
    ep AS (
      SELECT m.wallet, m.entry_bar_ts // 86400000 AS day,
             strftime(make_timestamp(m.entry_bar_ts*1000), '%G%V') AS week,
             m.raw_markout_{hname} - m.dir_sign*(SELECT mug FROM mu_g) AS ta
      FROM read_parquet('{mk}') m
      WHERE m.raw_markout_{hname} IS NOT NULL AND NOT m.entry_after_close AND m.entry_lag_s <= {ENTRY_LAG_MAX_S}
        AND m.entry_bar_ts >= {lo} AND m.entry_bar_ts < {hi} AND (m.entry_bar_ts + {h}) <= {hi}
        AND m.close_ts <= {hi}),
    daily  AS (SELECT wallet, day, week, avg(ta) dm FROM ep GROUP BY 1,2,3),
    weekly AS (SELECT wallet, week, avg(dm) wm FROM daily GROUP BY 1,2),
    wk AS (SELECT wallet, count(*) n_weeks, avg(wm) est, stddev_samp(wm) sd FROM weekly GROUP BY 1),
    epc AS (SELECT wallet, count(*) n_ep FROM ep GROUP BY 1)
    SELECT wk.wallet, '{coin}' AS coin, '{hname}' AS horizon, n_weeks, n_ep,
           est, est - 1.96*sd/sqrt(n_weeks) AS lb
    FROM wk JOIN epc USING(wallet)"""


def _build(con, tag, lo, hi):
    con.execute(f"CREATE OR REPLACE TEMP TABLE {tag} AS " +
                " UNION ALL ".join(f"({_period_sql(c, h, lo, hi)})" for c in COINS for h in HZ))


def run():
    con = _con()
    _build(con, "p1", *P1); _build(con, "p2", *P2)
    j = con.execute("""CREATE OR REPLACE TEMP TABLE j AS
      SELECT p1.wallet, p1.coin, p1.horizon,
             p1.est e1, p1.lb lb1, p1.n_weeks w1, p2.est e2, p2.lb lb2, p2.n_weeks w2
      FROM p1 JOIN p2 USING(wallet, coin, horizon)""")
    print(f"split at 2026-02-01 | p1=[2025-08,2026-02) p2=[2026-02,2026-06) | care-about={CARE_BP}bp\n")

    print(f"{'hz':>4} | {'both-active':>11} | {'Spearman rho':>12} {'p':>8} | "
          f"{'sel(p1)':>7} {'p2 mean':>8} {'95% CI':>16} {'sign+%':>7} {'MDE':>6} {'lift':>6} | verdict")
    for h in HZ:
        # (1) rank persistence across wallets active-and-powered in both
        both = con.execute(f"""SELECT e1, e2 FROM j WHERE horizon='{h}' AND w1>={MIN_WK_EVAL} AND w2>={MIN_WK_EVAL}""").fetchnumpy()
        e1, e2 = np.asarray(both["e1"], float), np.asarray(both["e2"], float)
        nb = len(e1)
        if nb >= 20:
            r1 = np.argsort(np.argsort(e1)); r2 = np.argsort(np.argsort(e2))
            rho = float(np.corrcoef(r1, r2)[0, 1])
            tstat = rho * math.sqrt((nb - 2) / max(1e-9, 1 - rho * rho))
            # two-sided normal approx p
            pear = 0.5 * math.erfc(abs(tstat) / math.sqrt(2)) * 2
        else:
            rho, pear = float("nan"), float("nan")

        # (2) deployment sim: select on p1, evaluate p2
        sel = con.execute(f"""SELECT e2, w2 FROM j
           WHERE horizon='{h}' AND e1>0 AND lb1>0 AND w1>={MIN_WK_SEL} AND w2>={MIN_WK_EVAL}""").fetchnumpy()
        se2 = np.asarray(sel["e2"], float)
        unsel = con.execute(f"""SELECT avg(e2) FROM j
           WHERE horizon='{h}' AND NOT (e1>0 AND lb1>0 AND w1>={MIN_WK_SEL}) AND w2>={MIN_WK_EVAL}""").fetchone()[0]
        ns = len(se2)
        if ns >= 10:
            m = float(np.mean(se2)); sd = float(np.std(se2, ddof=1)); sem = sd / math.sqrt(ns)
            ci = (m - 1.96 * sem, m + 1.96 * sem)
            signpos = float(np.mean(se2 > 0)) * 100
            mde = (1.96 + 0.84) * sem                       # two-sided a=.05, power .80
            lift = m - (unsel if unsel is not None else 0.0)
            if ci[0] > 0:
                verdict = "PERSISTS (CI>0)"
            elif mde <= CARE_BP and ci[1] < CARE_BP:
                verdict = "earned null (MDE<=care)"
            else:
                verdict = f"INCONCLUSIVE (MDE={mde:.1f})"
        else:
            m = ci = signpos = mde = lift = float("nan"); verdict = "too few selected"
        print(f"{h:>4} | {nb:>11,} | {rho:>+12.3f} {pear:>8.1e} | "
              f"{ns:>7,} {m:>+8.2f} [{ci[0]:>+6.2f},{ci[1]:>+6.2f}] {signpos:>6.1f}% {mde:>6.2f} {lift:>+6.2f} | {verdict}")

    print("\nnote: p2 mean = selected cohort's OUT-OF-SAMPLE timing_alpha (bp); CI/sign across wallets (cross-unit);")
    print("lift = selected − non-selected p2 mean; verdict earns 'null' only if MDE<=care-about (else INCONCLUSIVE).")


if __name__ == "__main__":
    run()
