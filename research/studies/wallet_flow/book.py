"""book — the tradeability test: turn the informed-cohort signal into a factor-neutral MAJORS book and
measure it NET of realistic majors execution cost.

NB the literal "condition the xsec ALT reversal on wallet flow" is impossible today: the reversal runs on
alts, wallet flow exists only for the 4 majors (fills tape is majors-only). So this is the majors-only
tradeability probe of the wallet signal itself — the thing that answers "is ANY of this net-positive?"
before we spend on the alt-fills backfill. Majors spreads are far tighter (~1-3 bp) than the ADV-capped
alt spreads (~9 bp) behind the ../xsec_statarb 36 bp wall, so the cost is re-measured from asset_ctx, not
assumed.

Construction (causal, A3): each hour t form cross-sectional rank weights over the 4 majors from cohort_flow(t)
(known at end of t) — dollar-neutral (demeaned ranks), gross leverage 1. Hold end-of-t -> end-of-t+1; realized
leg PnL = fwd_resid_i(t) (already beta-neutral to the LOO major index, so the book is factor-neutral).
Cost = turnover Σ|Δw| × per-crossing (half-spread from asset_ctx impact px + taker fee). Compare the informed
cohort vs a RANDOM same-size cohort vs OFI. Conviction lever: full 4-name book vs top/bottom-name-only.

  .venv/bin/python -m research.studies.wallet_flow.book
"""
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import flow
from research.studies.wallet_flow.flow import (
    build_resid, build_wallet_tables, register_resid, freeze_cohort, test_panel,
    TEST_MONTH, MIN_TRAIN_BKT, COHORT_Q, SCRATCH,
)

MAJORS = flow.MAJORS
FEE_BP = 4.5           # taker fee per crossing (matches gate.py)
HOURS_PER_YR = 24 * 365
BOOT = 2000
H = 1                  # the signal is a 1h phenomenon (walkforward: 2h is noise)


def _halfspread_bp(con):
    """Median per-coin half-spread (bp of mid) on majors over the TEST span, from asset_ctx impact px."""
    q = con.execute(f"""
        SELECT coin, 1e4*median((impact_ask_px-impact_bid_px)/2.0/NULLIF(mid_px,0)) AS hs_bp
        FROM asset_ctx
        WHERE coin IN {MAJORS} AND mid_px>0 AND impact_ask_px>0 AND impact_bid_px>0
              AND (ts - ts%3600000) >= (SELECT min(h) FROM (
                    SELECT (ts-ts%3600000) h FROM asset_ctx WHERE coin='BTC') )
        GROUP BY coin
    """).fetchall()
    return {r[0]: float(r[1]) for r in q}


def _pivot(tp):
    """test_panel dict -> time-sorted [T,4] matrices for cohort_flow, ofi, fwd_resid (NaN where absent)."""
    coin = np.asarray(tp["coin"], dtype=object)
    hh = tp["h"].astype(np.int64)
    ci = {c: i for i, c in enumerate(MAJORS)}
    uh = np.unique(hh); ridx = {h: i for i, h in enumerate(uh)}
    T = len(uh)
    cf = np.full((T, 4), np.nan); of = np.full((T, 4), np.nan); fr = np.full((T, 4), np.nan)
    for k in range(len(coin)):
        i = ridx[hh[k]]; j = ci[str(coin[k])]
        cf[i, j] = tp["cohort_flow"][k]; of[i, j] = tp["ofi"][k]; fr[i, j] = tp["fwd_resid"][k]
    return uh, cf, of, fr


def _rank_weights(sig, topbottom=False):
    """Cross-sectional dollar-neutral rank weights per row over finite entries; gross leverage 1.
    topbottom=True -> hold only the extreme long & short name (drop the middle)."""
    T, C = sig.shape
    W = np.zeros((T, C))
    for t in range(T):
        f = np.isfinite(sig[t])
        n = f.sum()
        if n < 2:
            continue
        r = np.argsort(np.argsort(sig[t, f])).astype(float)
        w = r - r.mean()
        if topbottom and n > 2:
            keep = (r == r.min()) | (r == r.max())
            w = np.where(keep, w, 0.0)
        s = np.abs(w).sum()
        if s > 0:
            W[t, f] = w / s
    return W


def _pnl(W, fr, hs_bp):
    """gross, cost, net per-period bp series. cost = Σ|Δw|×(halfspread+fee), fwd fills NaN->0 (flat)."""
    frz = np.where(np.isfinite(fr), fr, 0.0)
    gross = 1e4 * np.sum(W * frz, axis=1)                      # bp
    dW = np.abs(np.diff(W, axis=0, prepend=np.zeros((1, W.shape[1]))))
    perc = hs_bp + FEE_BP                                       # per-crossing cost per coin, bp
    cost = np.sum(dW * perc[None, :], axis=1)
    return gross, cost, gross - cost


def _sharpe(x):
    m = x[np.isfinite(x)]
    if len(m) < 10 or m.std() == 0:
        return np.nan
    return m.mean() / m.std() * np.sqrt(HOURS_PER_YR)


def _boot_sharpe_ci(net, hours, seed=0, n=BOOT):
    rng = np.random.default_rng(seed)
    uh = np.unique(hours); idx = {h: np.nonzero(hours == h)[0] for h in uh}
    s = []
    for _ in range(n):
        pick = rng.integers(0, len(uh), size=len(uh))
        sel = np.concatenate([idx[uh[p]] for p in pick])
        s.append(_sharpe(net[sel]))
    s = np.array([v for v in s if np.isfinite(v)])
    return tuple(np.percentile(s, [2.5, 97.5])) if len(s) > 10 else (np.nan, np.nan)


def _report(name, W, fr, hours, hs):
    gross, cost, net = _pnl(W, fr, hs)
    gm, cm, nm = np.nanmean(gross), np.nanmean(cost), np.nanmean(net)
    sr = _sharpe(net); lo, hi = _boot_sharpe_ci(net, hours)
    be = "yes" if gm > cm else "no"
    print(f"  {name:22s} gross={gm:+6.2f}  cost={cm:5.2f}  net={nm:+6.2f} bp/hr  "
          f"netSR={sr:+5.2f} [{lo:+.2f},{hi:+.2f}]  gross>cost? {be}")
    return dict(gross=gm, cost=cm, net=nm, sr=sr)


def run():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='900MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'")
    con.execute("SET preserve_insertion_order=false")
    print("[1/3] residual panel ...")
    panel = build_resid(con)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM fills ORDER BY month").fetchall()]
    print(f"[2/3] wallet flow tables (cached): {months}")
    build_wallet_tables(con, months)
    register_resid(con, panel, H)

    hs_map = _halfspread_bp(con)
    hs = np.array([hs_map.get(c, 3.0) for c in MAJORS])
    print("\nmajors half-spread (bp of mid, from asset_ctx impact px):")
    for c in MAJORS:
        print(f"    {c:5s} {hs_map.get(c, float('nan')):.2f} bp  -> per-crossing cost {hs_map.get(c,3.0)+FEE_BP:.2f} bp")

    # informed cohort
    informed, npool = freeze_cohort(con, H)
    tp = test_panel(con, H)
    hours, cf, of, fr = _pivot(tp)
    print(f"\n[3/3] test span buckets={len(hours):,}; informed cohort={len(informed):,} (pool {npool:,})")

    # random same-size cohort baseline
    wq = con.execute(f"""WITH j AS (SELECT wb.wallet, sign(wb.flow)*r.fwd_resid a FROM wb
        JOIN resid r ON wb.coin=r.coin AND wb.h=r.h
        WHERE wb.mth<{TEST_MONTH} AND wb.flow<>0 AND r.fwd_resid IS NOT NULL)
        SELECT wallet FROM j GROUP BY wallet HAVING count(*)>={MIN_TRAIN_BKT}""").fetchnumpy()
    pool = np.asarray(wq["wallet"], dtype=object)
    rng = np.random.default_rng(0)
    rand = pool[rng.choice(len(pool), size=len(informed), replace=False)]
    con.register("cohort_src", {"wallet": np.array([str(w) for w in rand], dtype=object)})
    con.execute("CREATE OR REPLACE TEMP TABLE cohort AS SELECT * FROM cohort_src"); con.unregister("cohort_src")
    tp_r = test_panel(con, H); _, cf_r, _, _ = _pivot(tp_r)

    print("\n=== FACTOR-NEUTRAL MAJORS BOOK, 1h hold, t+1 entry, realistic majors cost ===")
    print("full 4-name cross-sectional rank book:")
    _report("informed cohort", _rank_weights(cf), fr, hours, hs)
    _report("random cohort", _rank_weights(cf_r), fr, hours, hs)
    _report("OFI (order flow)", _rank_weights(of), fr, hours, hs)
    print("top/bottom-name-only (concentrated, lower turnover per name):")
    _report("informed cohort", _rank_weights(cf, topbottom=True), fr, hours, hs)
    _report("random cohort", _rank_weights(cf_r, topbottom=True), fr, hours, hs)

    # break-even: zero-cost gross tells the ceiling; implied allowable per-crossing cost
    g, c, _ = _pnl(_rank_weights(cf), fr, hs)
    gsr = _sharpe(g); glo, ghi = _boot_sharpe_ci(g, hours, seed=9)
    dW = np.abs(np.diff(_rank_weights(cf), axis=0, prepend=np.zeros((1, 4)))).sum(1).mean()
    print(f"\nzero-cost (maker/free) gross ceiling = {np.nanmean(g):+.2f} bp/hr, "
          f"grossSR={gsr:+.2f} [{glo:+.2f},{ghi:+.2f}]; mean turnover={dW:.2f}/hr; "
          f"break-even per-crossing cost = {np.nanmean(g)/dW if dW>0 else float('nan'):.2f} bp "
          f"(taker ~{hs.mean()+FEE_BP:.1f} bp; maker fee~0 + half-spread {hs.mean():.2f} bp)")
    con.close()


if __name__ == "__main__":
    run()
