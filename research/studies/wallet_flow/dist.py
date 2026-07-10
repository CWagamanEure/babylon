"""dist — return-distribution diagnostic on the informed-cohort majors book.

Question (user): is the per-hour PnL fat-tailed, and does the TAIL drag the mean down? Two opposite readings,
both tested here:
  - LEFT-tail drag (median/trimmed >> mean, negative skew): the typical hour is better than the mean -> a
    conditional 'avoid the bad state' strategy could clear cost. ENCOURAGING.
  - RIGHT-tail support (median/trimmed << mean, positive skew): the +1.51 gross is a few lucky big hours ->
    fragile, maker ceiling overstated. OVER-CARRY RISK (report it if so, don't hide it).

Then WHERE/WHEN: gross by coin, by signal-conviction decile, by hour-of-day, and how many hours clear cost.
Descriptive pass — any conviction/state gate that looks live must then be re-tested with the walk-forward
discipline (this is IN-SAMPLE structure-finding, flagged as such; conviction uses a full-sample z = non-causal).

  .venv/bin/python -m research.studies.wallet_flow.dist
"""
import numpy as np
from research.data.db import connect
from research.studies.wallet_flow import flow
from research.studies.wallet_flow.flow import (
    build_resid, build_wallet_tables, register_resid, freeze_cohort, test_panel, SCRATCH,
)
from research.studies.wallet_flow.book import _pivot, _rank_weights, _halfspread_bp, _pnl, FEE_BP

MAJORS = flow.MAJORS
H = 1


def _stats(x, label):
    x = x[np.isfinite(x)]
    n = len(x); mu = x.mean(); med = np.median(x); sd = x.std()
    tr10 = np.mean(np.sort(x)[int(0.1*n):int(0.9*n)])            # 10% two-sided trimmed mean
    z = (x - mu) / sd
    skew = np.mean(z**3); kurt = np.mean(z**4)                    # excess kurt = kurt-3
    pcts = np.percentile(x, [1, 5, 25, 50, 75, 95, 99])
    print(f"\n{label} (n={n}):")
    print(f"  mean={mu:+.3f}  median={med:+.3f}  trimmed10={tr10:+.3f}  std={sd:.2f}  "
          f"skew={skew:+.2f}  exKurt={kurt-3:+.1f}")
    print(f"  pctiles [1,5,25,50,75,95,99] = " + " ".join(f"{p:+.1f}" for p in pcts))
    # tail attribution: how much of the total sum comes from the worst / best 5% of hours
    s = np.sort(x); tot = x.sum()
    w5 = s[:max(1, int(0.05*n))].sum(); b5 = s[-max(1, int(0.05*n)):].sum()
    print(f"  Σ={tot:+.0f}; worst5%={w5:+.0f} ({100*w5/tot if tot!=0 else 0:+.0f}% of Σ), "
          f"best5%={b5:+.0f} ({100*b5/tot if tot!=0 else 0:+.0f}% of Σ)")
    return dict(mu=mu, med=med, tr10=tr10, skew=skew)


def run():
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='900MB'; SET threads=1")
    con.execute(f"SET temp_directory='{SCRATCH}/duckspill'")
    con.execute("SET preserve_insertion_order=false")
    print("[1/3] residual panel ...")
    panel = build_resid(con)
    months = [int(r[0]) for r in con.execute("SELECT DISTINCT month FROM fills ORDER BY month").fetchall()]
    print(f"[2/3] wallet flow tables (cached)")
    build_wallet_tables(con, months)
    register_resid(con, panel, H)
    hs_map = _halfspread_bp(con); hs = np.array([hs_map.get(c, 3.0) for c in MAJORS])

    informed, npool = freeze_cohort(con, H)
    tp = test_panel(con, H)
    hours, cf, of, fr = _pivot(tp)
    W = _rank_weights(cf)
    gross, cost, net = _pnl(W, fr, hs)
    print(f"[3/3] test span buckets={len(hours):,}; cohort={len(informed):,}")
    print(f"\n=== PER-HOUR BOOK PnL DISTRIBUTION (informed, full 4-name, bp/hr) ===")
    _stats(gross, "GROSS bp/hr")
    _stats(net, "NET bp/hr (after ~5-6bp taker cost)")
    cm = np.nanmean(cost)
    print(f"\n  mean cost/hr = {cm:.2f} bp (steady, turnover-driven)")
    print(f"  hours with gross>0: {100*np.mean(gross>0):.0f}%   gross>cost(that hr): "
          f"{100*np.mean(gross>cost):.0f}%   net>0: {100*np.mean(net>0):.0f}%")

    # per-coin leg contributions (w_i * fr_i), and per-coin gross if traded alone vs index
    print(f"\n=== PER-COIN leg contribution (mean bp/hr the coin adds to book gross) ===")
    leg = 1e4 * W * np.where(np.isfinite(fr), fr, 0.0)
    for i, c in enumerate(MAJORS):
        col = leg[:, i]; active = W[:, i] != 0
        print(f"  {c:5s} mean leg={np.nanmean(col):+.3f}  |  when active (n={active.sum():4d}): "
              f"mean={np.nanmean(col[active]):+.3f}  median={np.median(col[active]):+.3f}")

    # conviction: cross-sectional spread of the signal each hour (range of within-coin-z cohort flow).
    # NON-CAUSAL z (full-sample) -> descriptive only.
    zc = np.full_like(cf, np.nan)
    for i in range(4):
        col = cf[:, i]; f = np.isfinite(col)
        if f.sum() > 10 and col[f].std() > 0:
            zc[f, i] = (col[f] - col[f].mean()) / col[f].std()
    conv = np.nanmax(zc, axis=1) - np.nanmin(zc, axis=1)          # spread of standardized signal
    print(f"\n=== GROSS by SIGNAL-CONVICTION decile (spread of z(cohort_flow); NON-CAUSAL, descriptive) ===")
    ok = np.isfinite(conv) & np.isfinite(gross)
    cv, gr, ct = conv[ok], gross[ok], cost[ok]
    order = np.argsort(cv); dec = np.array_split(order, 10)
    print(f"  {'decile':>6} {'conv':>7} {'grossμ':>8} {'costμ':>7} {'netμ':>8} {'gross>cost%':>11}")
    for d, idx in enumerate(dec):
        print(f"  {d+1:>6} {cv[idx].mean():>7.2f} {gr[idx].mean():>+8.2f} {ct[idx].mean():>7.2f} "
              f"{(gr[idx]-ct[idx]).mean():>+8.2f} {100*np.mean(gr[idx]>ct[idx]):>10.0f}%")

    # hour-of-day (UTC)
    hod = (hours // 3600000) % 24
    print(f"\n=== GROSS by hour-of-day (UTC) — top/bottom 4 by mean gross ===")
    hh = np.array([(h, gross[hod == h].mean(), (gross[hod==h]-cost[hod==h]).mean(), int((hod==h).sum()))
                   for h in range(24)])
    o = np.argsort(-hh[:, 1])
    for h in np.concatenate([o[:4], o[-4:]]):
        r = hh[h]
        print(f"  h{int(r[0]):02d}Z  grossμ={r[1]:+.2f}  netμ={r[2]:+.2f}  (n={int(r[3])})")
    con.close()


if __name__ == "__main__":
    run()
