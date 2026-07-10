"""Split-sample discover -> confirm, done right (user spec 2026-07-09), split-SYMMETRIC for a two-way cross-check.

One direction:
  DISCOVERY period: screen traders (episode-based hygiene IN that period); for each survivor pick
    best_horizon = argmax over {1h,2h,4h,8h} of that-period timing_alpha est. FREEZE (trader, horizon).
  CONFIRMATION period (disjoint, never seen in discovery): re-screen (>=200 orders etc IN the test period),
    require drop-best-day robustness, then ONE p-value per trader at ONLY its frozen horizon via day-block
    bootstrap. NO second argmax. BH-FDR across the trader p-values.

Run BOTH directions and intersect:
  FORWARD  = discover on [Aug..Jan], confirm on [Feb..Jun]
  REVERSE  = discover on [Feb..Jun], confirm on [Aug..Jan]
A trader that survives FDR in BOTH (each half held out once, disjoint confirmation data) is about as real as
this data allows. Survivors written to data/derived/confirmed_traders/.

POSTSCRIPT (2026-07-09 4-agent swarm — the settled verdict): the "replicated" reading was OVER-CARRIED.
Fisher's independence assumption is empirically false (cross-half corr of timing_alpha r=+0.04..0.08, z<=18 —
a persistent per-trader STRUCTURAL component, not proof of skill); 3 of the 4 lose money; the 4th is an
uncopyable maker. Settled label: "reproducible sub-cost structural residual, skill unproven." Do NOT read
replicated.parquet as a confirmed-trader list.

    python -m research.data.discover_confirm
"""
from __future__ import annotations
import math
import numpy as np
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from .markout import HORIZONS, COINS, REPO_ROOT
from .family_wf import _fcol  # MaskedArray NULL fix (audit 2026-07-10)
from .features_markout import ENTRY_LAG_MAX_S
from .persistence import _period_sql

HZ = ["1h", "2h", "4h", "8h"]
AUG = "0"
SPLIT = "epoch_ms(TIMESTAMP '2026-02-01')"
END = "epoch_ms(TIMESTAMP '2026-06-29')"
MIN_WK_DISC = 6
B = 10000              # audit-F4: floor 1/(B+1) must sit well below Q/m so isolated signals can survive BH
Q = 0.10
MIN_DAYS = 10         # audit-F3: day-block bootstrap needs enough DISTINCT days to be valid (few-day => fluke)
CARE_BP = 8.0
SEED = 20260709
OUT = REPO_ROOT / "data" / "derived" / "confirmed_traders"

# screener gate, applied IN each period (discovery must be real+clean to be a candidate; confirmation must be
# real+clean to be confirmable). Measured from the episode lake.
MIN_ORDERS = 200
MIN_WEEKS = 8
MIN_VOL_USD = 1e6
TWAP_MAX = 0.30
LIQ_MAX = 0.10


def _con():
    c = duckdb.connect(); c.execute("SET enable_progress_bar=false"); c.execute("PRAGMA memory_limit='4GB'")
    c.execute("PRAGMA threads=2"); c.execute(f"SET temp_directory='{REPO_ROOT/'.tmp'}'")
    return c


def _hygiene(con, lo, hi):
    """Episode-based screener over [lo,hi): >=MIN_ORDERS fills, >=MIN_WEEKS weeks, >=MIN_VOL_USD notional,
    twap/liq shares under threshold. Returns set of (wallet,coin)."""
    ep = str(REPO_ROOT / "data/derived/episodes/month=*/episodes.parquet")
    rows = con.execute(f"""SELECT wallet, coin FROM (
        SELECT wallet, coin,
          sum(n_taker_fills + n_maker_fills) n_ord,
          count(DISTINCT strftime(make_timestamp(close_ts*1000), '%G%V')) n_wk,
          sum(initial_notional_usd + total_added_notional_usd) vol_usd,
          sum(n_flagged_fills)::DOUBLE/nullif(sum(n_taker_fills + n_maker_fills),0) twap_sh,
          sum(n_liq_fills)::DOUBLE/nullif(sum(n_taker_fills + n_maker_fills),0) liq_sh
        FROM read_parquet('{ep}', hive_partitioning=true)
        WHERE close_ts >= {lo} AND close_ts < {hi} GROUP BY wallet, coin)
      WHERE n_ord>={MIN_ORDERS} AND n_wk>={MIN_WEEKS} AND vol_usd>={MIN_VOL_USD}
        AND coalesce(twap_sh,0)<{TWAP_MAX} AND coalesce(liq_sh,0)<{LIQ_MAX}""").fetchall()
    return {(w, c) for (w, c) in rows}


def _frozen(con, lo, hi, elig):
    """Discovery: among eligible traders, freeze each one's best-horizon by that-period timing_alpha est
    (require max est>0, n_weeks>=6). Returns dict (wallet,coin)->horizon."""
    con.execute("CREATE OR REPLACE TEMP TABLE d1 AS " +
                " UNION ALL ".join(f"({_period_sql(c, h, lo, hi)})" for c in COINS for h in HZ))
    rows = con.execute(f"""
      WITH best AS (SELECT wallet, coin, horizon, est,
                      row_number() OVER (PARTITION BY wallet,coin ORDER BY est DESC) rn
                    FROM d1 WHERE n_weeks>={MIN_WK_DISC})
      SELECT wallet, coin, horizon FROM best WHERE rn=1 AND est>0""").fetchall()
    return {(w, c): h for (w, c, h) in rows if (w, c) in elig}


def _p2_episodes(con, coin, wallets, lo, hi):
    """Confirmation per-episode timing_alpha at all horizons + day, for the frozen wallets of this coin."""
    mk = str(REPO_ROOT / f"data/derived/episodes_markout/coin={coin}/part-b*.parquet")
    fwd = str(REPO_ROOT / f"data/derived/fwd_returns/coin={coin}/part.parquet")
    mus = {h: f"(SELECT avg(fwd_ret_{h}) FROM read_parquet('{fwd}') WHERE fwd_ret_{h} IS NOT NULL AND ts>={lo} AND (ts+{HORIZONS[h]})<={hi})" for h in HZ}
    ta = ", ".join(f"m.raw_markout_{h} - m.dir_sign*{mus[h]} AS ta_{h}" for h in HZ)
    cond = " OR ".join(f"(m.raw_markout_{h} IS NOT NULL AND (m.entry_bar_ts+{HORIZONS[h]})<={hi})" for h in HZ)
    con.execute("CREATE OR REPLACE TEMP TABLE wl(wallet VARCHAR)")
    con.executemany("INSERT INTO wl VALUES (?)", [(w,) for w in wallets])
    return con.execute(f"""SELECT m.wallet, m.entry_bar_ts//86400000 AS day, {ta}
      FROM read_parquet('{mk}') m JOIN wl USING(wallet)
      WHERE m.entry_bar_ts>={lo} AND m.entry_bar_ts<{hi} AND m.close_ts<={hi}
        AND NOT m.entry_after_close AND m.entry_lag_s<={ENTRY_LAG_MAX_S} AND ({cond})""").fetchnumpy()


def _trader_stat(vals, days, rng):
    """One trader's confirmation stat: day-block bootstrap p (H0: mean<=0) + point estimate + a day-clustered
    MDE. Returns None if too few DISTINCT days for a valid block bootstrap (audit-F3). MDE uses the
    between-day SE so a flat result can be judged powered-vs-blind (audit-F2)."""
    uday, inv = np.unique(days, return_inverse=True)
    nd = len(uday)
    if nd < MIN_DAYS:
        return None
    idx = [np.where(inv == k)[0] for k in range(nd)]
    daymeans = np.array([vals[i].mean() for i in idx])
    obs = float(np.mean(vals))
    se = float(np.std(daymeans, ddof=1)) / math.sqrt(nd)          # day-clustered SE
    mde = (1.96 + 0.84) * se
    if obs <= 0:
        return 1.0, obs, len(vals), nd, mde
    means = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, nd, size=nd)
        means[b] = vals[np.concatenate([idx[k] for k in pick])].mean()
    p = (1 + int(np.sum(means <= 0))) / (B + 1)
    return p, obs, len(vals), nd, mde


def _fisher(pf, pr):
    """Combine two INDEPENDENT one-sided p's (disjoint holdouts) -> chi2, df=4; SF closed-form for df=4."""
    x = -2.0 * (math.log(pf) + math.log(pr))
    return math.exp(-x / 2.0) * (1.0 + x / 2.0)


def _bh(pairs):
    """pairs=[(p,key)]; return set of survivor keys at BH-FDR q=Q, and the threshold."""
    m = len(pairs)
    if not m:
        return set(), 0.0
    pv = sorted(pairs)
    k_star, thr = 0, 0.0
    for k, (p, key) in enumerate(pv, 1):
        if p <= (k / m) * Q:
            k_star, thr = k, p
    return {key for (p, key) in pv[:k_star]}, thr


def _drop_best_day_ok(vals, days):
    ud = np.unique(days)
    if len(ud) < 2:
        return float(np.mean(vals)) > 0
    dmean = {k: vals[days == k].mean() for k in ud}
    best = max(dmean, key=dmean.get)
    return float(vals[days != best].mean()) > 0


def one_direction(con, name, disc, conf, rng):
    d_elig = _hygiene(con, *disc)
    frozen = _frozen(con, *disc, d_elig)
    c_elig = _hygiene(con, *conf)
    frozen_c = {(w, c): h for (w, c), h in frozen.items() if (w, c) in c_elig}
    print(f"[{name}] discover-eligible={len(d_elig):,} frozen={len(frozen):,} test-eligible={len(frozen_c):,}")
    recs, ndrop = [], 0
    for coin in COINS:
        wc = {w: h for (w, c), h in frozen_c.items() if c == coin}
        if not wc:
            continue
        e = _p2_episodes(con, coin, list(wc), *conf)
        wal = np.asarray(e["wallet"], dtype=object); day = np.asarray(e["day"])
        ta = {h: _fcol(e, f"ta_{h}") for h in HZ}
        order = np.argsort(wal, kind="stable")
        wal, day = wal[order], day[order]; ta = {h: ta[h][order] for h in HZ}
        uq, first = np.unique(wal, return_index=True); bounds = np.append(np.sort(first), len(wal))
        for gi in range(len(uq)):
            s, ez = bounds[gi], bounds[gi + 1]; w = wal[s]; h = wc[w]
            v = ta[h][s:ez]; d = day[s:ez]; mm = ~np.isnan(v); vv, dd = v[mm], d[mm]
            if len(vv) < 5:
                continue
            st = _trader_stat(vv, dd, rng)     # NO confirmation-outcome pre-filter (drop-best-day would
            if st is None:                     # select on the test outcome and contaminate the p-value family).
                continue                       # Only the outcome-INDEPENDENT distinct-day floor (audit-F3) gates.
            p, obs, n, nd, mde = st
            recs.append({"key": (w, coin), "h": h, "p": p, "alpha": obs, "n": n, "nd": nd, "mde": mde,
                         "dbd_ok": _drop_best_day_ok(vv, dd)})   # kept as a reported robustness FLAG, not a gate
    d = {r["key"]: r for r in recs}
    surv, thr = _bh([(r["p"], r["key"]) for r in recs])
    medmde = float(np.median([r["mde"] for r in recs])) if recs else float("nan")
    print(f"[{name}] tested(>= {MIN_DAYS}d) {len(recs):,}; median per-trader MDE={medmde:.1f}bp "
          f"(care={CARE_BP}); single-arm BH-FDR q={Q} -> {len(surv)} survive (p<={thr:.4g})")
    return d, surv


def _cohort(name, d):
    """Powered cross-trader test (audit-F2): is the MEAN confirmation alpha of the frozen cohort > 0? CI + sign
    across traders (cross-unit), + cohort MDE. This is the powered version of the per-trader question."""
    a = np.array([r["alpha"] for r in d.values()])
    n = len(a)
    m, sd = a.mean(), a.std(ddof=1); sem = sd / math.sqrt(n)
    signpos = 100 * np.mean(a > 0)
    mde = (1.96 + 0.84) * sem
    ci = (m - 1.96 * sem, m + 1.96 * sem)
    verdict = "COHORT edge>0 (CI>0)" if ci[0] > 0 else (
        "cohort earned-null (MDE<=care)" if mde <= CARE_BP and ci[1] < CARE_BP else f"cohort INCONCLUSIVE (MDE={mde:.1f})")
    print(f"[{name}] cohort n={n:,} mean_alpha={m:+.2f}bp CI[{ci[0]:+.2f},{ci[1]:+.2f}] sign+={signpos:.1f}% "
          f"MDE={mde:.2f} -> {verdict}")


def run():
    rng = np.random.default_rng(SEED)
    con = _con()
    fwd, fwd_s = one_direction(con, "FORWARD", (AUG, SPLIT), (SPLIT, END), rng)
    rev, rev_s = one_direction(con, "REVERSE", (SPLIT, END), (AUG, SPLIT), rng)
    print()
    _cohort("FORWARD", fwd); _cohort("REVERSE", rev)

    # POWERED replication (audit-F1): Fisher-combine the two INDEPENDENT (disjoint-holdout) per-trader p's,
    # then BH across traders tested in BOTH arms. This is the powered replacement for the hard intersection.
    both_keys = set(fwd) & set(rev)
    comb = [( _fisher(fwd[k]["p"], rev[k]["p"]), k) for k in both_keys]
    csurv, cthr = _bh(comb)
    print(f"\n=== REPLICATION: {len(both_keys):,} traders tested in BOTH disjoint holdouts ===")
    print(f"Fisher-combined p, BH-FDR q={Q}: {len(csurv)} replicate (combined p<={cthr:.4g})")
    # cross-unit sign test: of forward survivors, how many have reverse alpha>0?
    fs = [k for k in fwd_s if k in rev]
    if fs:
        rpos = np.array([rev[k]["alpha"] for k in fs]) > 0
        k_, n_ = int(rpos.sum()), len(fs)
        # binomial one-sided p vs 0.5
        from math import comb as C
        pbin = sum(C(n_, i) for i in range(k_, n_ + 1)) / 2 ** n_
        print(f"sign test: of {n_} forward-survivors testable in reverse, {k_} ({100*k_/n_:.0f}%) have reverse "
              f"alpha>0 (binomial p={pbin:.3g} vs 50%)")

    OUT.mkdir(parents=True, exist_ok=True)
    recs = []
    for k in sorted(csurv, key=lambda k: _fisher(fwd[k]["p"], rev[k]["p"])):
        w, c = k; f, r = fwd[k], rev[k]
        recs.append({"wallet": w, "coin": c, "fwd_hz": f["h"], "fwd_p": f["p"], "fwd_alpha_bp": round(f["alpha"], 1),
                     "fwd_n": f["n"], "fwd_nd": f["nd"], "rev_hz": r["h"], "rev_p": r["p"],
                     "rev_alpha_bp": round(r["alpha"], 1), "rev_n": r["n"], "rev_nd": r["nd"],
                     "fisher_p": _fisher(f["p"], r["p"])})
        print(f"   {w[:14]}… {c:4s} fwd@{f['h']}={f['alpha']:+.0f}bp(nd{f['nd']}) "
              f"rev@{r['h']}={r['alpha']:+.0f}bp(nd{r['nd']}) fisher_p={_fisher(f['p'],r['p']):.3g}")
    if recs:
        pq.write_table(pa.Table.from_pylist(recs), OUT / "replicated.parquet")
    print(f"\nwritten -> {OUT}/replicated.parquet ({len(recs)} traders)")


if __name__ == "__main__":
    run()
