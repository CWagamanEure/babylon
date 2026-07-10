"""STEELMAN attack on the OOS-persistence null. Parametrized split date + selection knob + per-coin + walk-forward.
Mirrors research.data.persistence but generalized. period-local global-μ (no cross-period leak).

    python -m research.data.persist_attack multisplit
    python -m research.data.persist_attack walkforward
    python -m research.data.persist_attack knobs 2026-02-01
    python -m research.data.persist_attack percoin 2026-02-01
"""
from __future__ import annotations

import math
import sys
import numpy as np
import duckdb

from .markout import HORIZONS, COINS, REPO_ROOT
from .features_markout import ENTRY_LAG_MAX_S

HZ = ["1h", "2h", "4h", "8h"]
MIN_WK_SEL = 6
MIN_WK_EVAL = 3
CARE_BP = 8.0
DATA_END = "epoch_ms(TIMESTAMP '2026-06-29 00:00:00')"


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT / '.tmp'}'")
    return c


def _period_sql(coin, hname, lo, hi, muvar="g"):
    """period-local timing_alpha. muvar='g' global-mu, 'w' weekly-mu."""
    h = HORIZONS[hname]
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
    if muvar == "g":
        mu_cte = f"""mu AS (SELECT avg(fwd_ret_{hname}) mug FROM read_parquet('{fwd}')
                     WHERE fwd_ret_{hname} IS NOT NULL AND ts >= {lo} AND (ts + {h}) <= {hi})"""
        ta = f"m.raw_markout_{hname} - m.dir_sign*(SELECT mug FROM mu)"
        join = ""
    else:
        mu_cte = f"""mu AS (SELECT iso_week, avg(fwd_ret_{hname}) muw FROM read_parquet('{fwd}')
                     WHERE fwd_ret_{hname} IS NOT NULL AND ts >= {lo} AND (ts + {h}) <= {hi} GROUP BY iso_week)"""
        ta = f"m.raw_markout_{hname} - m.dir_sign*mw.muw"
        join = "LEFT JOIN mu mw ON mw.iso_week = strftime(make_timestamp(m.entry_bar_ts*1000), '%G%V')"
    return f"""
    WITH {mu_cte},
    ep AS (
      SELECT m.wallet, m.entry_bar_ts // 86400000 AS day,
             strftime(make_timestamp(m.entry_bar_ts*1000), '%G%V') AS week,
             {ta} AS ta
      FROM read_parquet('{mk}') m {join}
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


def _build(con, tag, lo, hi, muvar="g"):
    con.execute(f"CREATE OR REPLACE TEMP TABLE {tag} AS " +
                " UNION ALL ".join(f"({_period_sql(c, h, lo, hi, muvar)})" for c in COINS for h in HZ))


def _join(con):
    con.execute("""CREATE OR REPLACE TEMP TABLE j AS
      SELECT p1.wallet, p1.coin, p1.horizon,
             p1.est e1, p1.lb lb1, p1.n_weeks w1, p2.est e2, p2.lb lb2, p2.n_weeks w2
      FROM p1 JOIN p2 USING(wallet, coin, horizon)""")


def _sel_stats(se2):
    ns = len(se2)
    if ns < 10:
        return None
    m = float(np.mean(se2)); sd = float(np.std(se2, ddof=1)); sem = sd / math.sqrt(ns)
    ci = (m - 1.96 * sem, m + 1.96 * sem)
    signpos = float(np.mean(se2 > 0)) * 100
    # exact binomial two-sided sign test vs 50%
    k = int(np.sum(se2 > 0)); n = int(np.sum(se2 != 0))
    from math import comb
    if n > 0:
        pk = sum(comb(n, i) for i in range(0, n + 1) if abs(i - n / 2) >= abs(k - n / 2)) / 2 ** n
    else:
        pk = float("nan")
    mde = (1.96 + 0.84) * sem
    return dict(ns=ns, m=m, ci=ci, signpos=signpos, sign_p=pk, mde=mde)


def _rank(con, h):
    both = con.execute(f"SELECT e1,e2 FROM j WHERE horizon='{h}' AND w1>={MIN_WK_EVAL} AND w2>={MIN_WK_EVAL}").fetchnumpy()
    e1, e2 = np.asarray(both["e1"], float), np.asarray(both["e2"], float)
    nb = len(e1)
    if nb < 20:
        return nb, float("nan"), float("nan")
    r1 = np.argsort(np.argsort(e1)); r2 = np.argsort(np.argsort(e2))
    rho = float(np.corrcoef(r1, r2)[0, 1])
    t = rho * math.sqrt((nb - 2) / max(1e-9, 1 - rho * rho))
    p = math.erfc(abs(t) / math.sqrt(2))
    return nb, rho, p


def _deploy(con, h, sel_clause):
    sel = con.execute(f"SELECT e2 FROM j WHERE horizon='{h}' AND w2>={MIN_WK_EVAL} AND ({sel_clause})").fetchnumpy()
    return _sel_stats(np.asarray(sel["e2"], float))


DEFAULT_SEL = f"e1>0 AND lb1>0 AND w1>={MIN_WK_SEL}"


def _report_split(con, label):
    print(f"\n=== {label} ===")
    print(f"{'hz':>4} | {'both':>6} {'rho':>7} {'p':>8} | {'sel':>5} {'p2mean':>7} {'95%CI':>16} {'sgn%':>5} {'signp':>7} {'MDE':>5} | verdict")
    for h in HZ:
        nb, rho, rp = _rank(con, h)
        d = _deploy(con, h, DEFAULT_SEL)
        if d is None:
            print(f"{h:>4} | {nb:>6} {rho:>+7.3f} {rp:>8.1e} | too few"); continue
        ci = d["ci"]
        if ci[0] > 0:
            v = "PERSISTS(CI>0)"
        elif d["mde"] <= CARE_BP and ci[1] < CARE_BP:
            v = "earned null"
        else:
            v = f"INCONCLUSIVE(MDE={d['mde']:.1f})"
        print(f"{h:>4} | {nb:>6} {rho:>+7.3f} {rp:>8.1e} | {d['ns']:>5} {d['m']:>+7.2f} "
              f"[{ci[0]:>+6.2f},{ci[1]:>+6.2f}] {d['signpos']:>4.0f}% {d['sign_p']:>7.1e} {d['mde']:>5.2f} | {v}")


def multisplit():
    for sp in ["2025-11-01", "2026-01-01", "2026-02-01", "2026-04-01"]:
        con = _con()
        S = f"epoch_ms(TIMESTAMP '{sp} 00:00:00')"
        _build(con, "p1", "0", S); _build(con, "p2", S, DATA_END); _join(con)
        _report_split(con, f"split {sp}  p1=[08-01,{sp})  p2=[{sp},06-29)")
        con.close()


def walkforward(muvar="g"):
    """consecutive train->test folds; pooled p2-mean of default-selected cohort across folds (sign test)."""
    edges = ["2025-08-01", "2025-10-01", "2025-12-01", "2026-02-01", "2026-04-01", "2026-06-29"]
    # fold k: train [edges[k], edges[k+1]) select, test [edges[k+1], edges[k+2]) evaluate
    print(f"\n=== WALK-FORWARD (train fold -> next fold OOS)  mu={muvar} ===")
    pooled = {h: [] for h in HZ}
    for k in range(len(edges) - 2):
        tr_lo, tr_hi = f"epoch_ms(TIMESTAMP '{edges[k]} 00:00:00')", f"epoch_ms(TIMESTAMP '{edges[k+1]} 00:00:00')"
        te_lo, te_hi = tr_hi, f"epoch_ms(TIMESTAMP '{edges[k+2]} 00:00:00')"
        con = _con()
        # shorter folds -> relax week gate to 3 for selection (2-month folds)
        _build(con, "p1", tr_lo, tr_hi, muvar); _build(con, "p2", te_lo, te_hi, muvar); _join(con)
        print(f"\n fold {k}: train[{edges[k]},{edges[k+1]}) -> test[{edges[k+1]},{edges[k+2]})")
        for h in HZ:
            sel = con.execute(f"SELECT e2 FROM j WHERE horizon='{h}' AND w2>={MIN_WK_EVAL} "
                              f"AND e1>0 AND lb1>0 AND w1>=3").fetchnumpy()
            se2 = np.asarray(sel["e2"], float)
            d = _sel_stats(se2)
            if d is None:
                print(f"   {h}: too few ({len(se2)})"); continue
            pooled[h].extend(se2.tolist())
            print(f"   {h}: n={d['ns']:>4} p2mean={d['m']:>+6.2f} CI[{d['ci'][0]:>+6.2f},{d['ci'][1]:>+6.2f}] sgn={d['signpos']:.0f}%")
        con.close()
    print("\n POOLED across folds (selected cohort OOS timing_alpha):")
    for h in HZ:
        d = _sel_stats(np.asarray(pooled[h], float))
        if d:
            print(f"   {h}: N={d['ns']:>4} mean={d['m']:>+6.2f} CI[{d['ci'][0]:>+6.2f},{d['ci'][1]:>+6.2f}] "
                  f"sgn={d['signpos']:.0f}% signp={d['sign_p']:.1e} MDE={d['mde']:.2f}")


def knobs(sp):
    con = _con()
    S = f"epoch_ms(TIMESTAMP '{sp} 00:00:00')"
    _build(con, "p1", "0", S); _build(con, "p2", S, DATA_END); _join(con)
    print(f"\n=== SELECTION-KNOB sweep, split {sp} ===")
    # for each horizon, try: default, top-decile e1, top-quartile e1, stricter lb1>2, lb1>4
    for h in HZ:
        print(f"\n horizon {h}:")
        # compute e1 quantiles among powered p1 wallets
        q = con.execute(f"SELECT quantile_cont(e1,0.9), quantile_cont(e1,0.75) FROM j "
                        f"WHERE horizon='{h}' AND w1>={MIN_WK_SEL} AND w2>={MIN_WK_EVAL}").fetchone()
        knobset = [
            ("default e1>0&lb1>0", DEFAULT_SEL),
            (f"top-decile e1>{q[0]:.1f}", f"w1>={MIN_WK_SEL} AND e1>{q[0]}"),
            (f"top-quartile e1>{q[1]:.1f}", f"w1>={MIN_WK_SEL} AND e1>{q[1]}"),
            ("lb1>2", f"w1>={MIN_WK_SEL} AND lb1>2"),
            ("lb1>4", f"w1>={MIN_WK_SEL} AND lb1>4"),
        ]
        for name, cl in knobset:
            d = _deploy(con, h, cl)
            if d is None:
                print(f"   {name:24s}: too few"); continue
            print(f"   {name:24s}: n={d['ns']:>4} p2mean={d['m']:>+6.2f} "
                  f"CI[{d['ci'][0]:>+6.2f},{d['ci'][1]:>+6.2f}] sgn={d['signpos']:.0f}% MDE={d['mde']:.2f}")
    # weekly-mu variant, default selection
    print("\n WEEKLY-MU variant (intra-week timing floor), default selection:")
    _build(con, "p1", "0", S, "w"); _build(con, "p2", S, DATA_END, "w"); _join(con)
    for h in HZ:
        d = _deploy(con, h, DEFAULT_SEL)
        nb, rho, rp = _rank(con, h)
        if d:
            print(f"   {h}: n={d['ns']:>4} p2mean={d['m']:>+6.2f} CI[{d['ci'][0]:>+6.2f},{d['ci'][1]:>+6.2f}] "
                  f"sgn={d['signpos']:.0f}% | rho={rho:+.3f} p={rp:.1e}")


def percoin(sp):
    con = _con()
    S = f"epoch_ms(TIMESTAMP '{sp} 00:00:00')"
    _build(con, "p1", "0", S); _build(con, "p2", S, DATA_END); _join(con)
    print(f"\n=== PER-COIN breakdown, split {sp}, default selection ===")
    for h in HZ:
        print(f"\n horizon {h}:")
        for coin in COINS:
            sel = con.execute(f"SELECT e2 FROM j WHERE horizon='{h}' AND coin='{coin}' AND w2>={MIN_WK_EVAL} "
                              f"AND {DEFAULT_SEL}").fetchnumpy()
            se2 = np.asarray(sel["e2"], float)
            d = _sel_stats(se2)
            both = con.execute(f"SELECT e1,e2 FROM j WHERE horizon='{h}' AND coin='{coin}' "
                               f"AND w1>={MIN_WK_EVAL} AND w2>={MIN_WK_EVAL}").fetchnumpy()
            e1c, e2c = np.asarray(both["e1"], float), np.asarray(both["e2"], float)
            if len(e1c) >= 20:
                r1 = np.argsort(np.argsort(e1c)); r2 = np.argsort(np.argsort(e2c))
                rho = float(np.corrcoef(r1, r2)[0, 1])
            else:
                rho = float("nan")
            if d is None:
                print(f"   {coin:5s}: sel too few ({len(se2)}) rho={rho:+.3f}"); continue
            print(f"   {coin:5s}: n={d['ns']:>4} p2mean={d['m']:>+6.2f} CI[{d['ci'][0]:>+6.2f},{d['ci'][1]:>+6.2f}] "
                  f"sgn={d['signpos']:.0f}% signp={d['sign_p']:.1e} rho={rho:+.3f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "multisplit"
    arg = sys.argv[2] if len(sys.argv) > 2 else "2026-02-01"
    {"multisplit": multisplit, "walkforward": lambda: walkforward(arg if cmd == "walkforward" and len(sys.argv) > 2 else "g"),
     "walkforward_w": lambda: walkforward("w"),
     "knobs": lambda: knobs(arg), "percoin": lambda: percoin(arg)}[cmd]()
