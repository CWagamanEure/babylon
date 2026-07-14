"""
xsec_kalman — does CAUSAL smoothing (EMA / steady-state Kalman) of the per-alt V-trail signal cut turnover enough
to rescue the TAKER leg and/or tighten the MAKER leg?  (the one untested lever flagged by the signal-hunt swarm.)

Mechanism under test: the deployed book re-ranks S_a fresh each rebalance and only holds names the cohort traded
THIS hour → high name-turnover → the spread taxes every entry/exit. If a name's signal PERSISTS (belief carried
across quiet hours + exponentially averaged), membership is stickier → fewer entries/exits → less spread paid
(taker) / less adverse churn (maker). The tradeoff: a smoothed signal is STALER, so gross alpha decays. Net is the
question.

Smoother = per-alt scalar filter over the hour axis, STRICTLY CAUSAL (uses only S_a[≤t]) so it is leak-free by
construction:
    observed hour:  m_t = α·S_t + (1−α)·m_{t−1}        (α=1 ⇒ pure carry-forward / no exponential blend)
    quiet hour:     m_t = m_{t−1}  IF within `stale` hours of the last obs, else the belief is DROPPED (name exits)
`stale` = how many hours a belief survives with no fresh cohort trade. (α=1, stale=0) reproduces the deployed book
(name alive only the hour it trades, no blend) — the baseline the sweep must recover.

This is a steady-state Kalman filter on a random-walk state: α is the Kalman gain, `stale` bounds how long the
prior stands in for a missing observation. Rebalance TIMES are frozen to the baseline grid so every (α,stale) cell
is compared on identical rebalance timestamps — only the signal differs.

⚠️ Sweeping (α,stale) and picking the best is an in-sample search (multiple comparisons). A winner here is a
CANDIDATE, not a deployable number: it must clear across a RANGE of settings (not a knife-edge cell) and then be
frozen + confirmed forward on the follower's logged raw signal. Reports point est + day-block CI + per-fold sign.

    .venv/bin/python -m research.studies.wallet_flow.xsec_kalman          # build cache if needed, run the sweep
    .venv/bin/python -m research.studies.wallet_flow.xsec_kalman --rebuild  # force rebuild the panel cache
"""
from __future__ import annotations
import argparse, time, json
from pathlib import Path
import numpy as np

from research.data.db import connect
from research.studies.wallet_flow import alt_flow as A
from research.studies.wallet_flow import xsec_flow_step0 as S0
from research.studies.wallet_flow import xsec_flow_adjudicate as ADJ
from research.studies.wallet_flow import xsec_concentrated_book as CB

_T0 = time.time()
def _log(m): print(f"[{time.time()-_T0:6.1f}s] {m}", flush=True)

H_TRAIN = 4
REB = 4                                   # deployed harvest horizon
OUT = Path("data/derived/xsec_kalman")
CACHE = OUT / "panel_cache.npz"
DUCK_TMP = f"{A.SCRATCH}/duck_xs_kalman"

ALPHAS = (1.00, 0.60, 0.35, 0.20)         # 1.0 = pure carry-forward (no blend); <1 = exponential blend (Kalman gain)
STALES = (0, 4, 8, 24)                     # hours a belief survives a quiet cohort (0 = deployed baseline)
FOCUS = ("taker_top_smallclip", "taker_top_impact", "maker_earn_a30", "maker_earn_a50")


def build_cache():
    """Heavy one-time load: reproduce the concentrated-book leak-free panel + V-trail signal, dump arrays to npz."""
    OUT.mkdir(parents=True, exist_ok=True); Path(DUCK_TMP).mkdir(parents=True, exist_ok=True)
    con = connect(warn_missing=False)
    con.execute("SET memory_limit='1400MB'; SET threads=1")
    con.execute(f"SET temp_directory='{DUCK_TMP}'"); con.execute("SET preserve_insertion_order=false")
    A._daily_adv(con)
    alts = A.universe(con, A.UNIV_FORMATION, include_majors=False)
    coins = list(A.FACTORS) + alts
    panel = A.build_resid(con, coins)
    resid, hours = panel["resid"], panel["hours"]
    panel_month = panel["month"]; N = panel["N"]; hmin = int(hours[0]); ci = panel["ci"]
    alt_names = [c for c in coins if c not in A.FACTORS]
    alt_cols = [ci[c] for c in alt_names]; n_alt = len(alt_cols)
    col_to_ac = {ci[c]: k for k, c in enumerate(alt_names)}
    LAG_ac = S0.trailing_resid_mom(resid)[:, alt_cols]
    resid_alt = resid[:, alt_cols].astype(np.float64)

    inlist = "('" + "','".join(alt_names) + "')"
    hs_rows = con.execute(f"""SELECT coin, median((impact_ask_px-impact_bid_px)/nullif(mid_px,0)*1e4/2.0) hs
        FROM asset_ctx WHERE coin IN {inlist} AND month>={CB.CLEAN_MIN}
          AND impact_ask_px>0 AND impact_bid_px>0 AND mid_px>0 GROUP BY coin""").fetchall()
    hs_by_name = {c: float(h) for c, h in hs_rows}
    hs_arr = np.array([hs_by_name.get(alt_names[i], 3.25) for i in range(n_alt)], dtype=np.float64)
    hs_default = float(np.median(list(hs_by_name.values())))

    A.build_cohort_tables(con, coins)
    CROWD = np.full((N, n_alt), np.nan)
    ag = con.execute("SELECT coin, h, allflow FROM aagg WHERE coin NOT IN ('BTC','ETH')").fetchnumpy()
    ar = ((ag["h"].astype(np.int64) - hmin) // 3600000).astype(int); ok = (ar >= 0) & (ar < N)
    acx = np.array([col_to_ac.get(ci.get(str(c), -1), -1) for c in ag["coin"]])
    good = ok & (acx >= 0); CROWD[ar[good], acx[good]] = ag["allflow"].astype(float)[good]
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cid AS SELECT * FROM (VALUES
        {",".join(f"('{c}',{k})" for k, c in enumerate(alt_names))}) AS t(coin, ccode)""")
    con.execute("""CREATE OR REPLACE TEMP TABLE wid AS SELECT wallet,(row_number() OVER (ORDER BY wallet))-1 AS wcode
        FROM (SELECT DISTINCT wallet FROM awb WHERE coin NOT IN ('BTC','ETH') AND flow<>0)""")
    rows = con.execute(f"""SELECT w.wcode, c.ccode, ((wb.h-{hmin})//3600000)::INT AS r, wb.mth,
               CASE WHEN wb.flow>0 THEN 1 WHEN wb.flow<0 THEN -1 ELSE 0 END AS s
        FROM awb wb JOIN wid w USING(wallet) JOIN cid c ON wb.coin=c.coin WHERE wb.flow<>0""").fetchnumpy()
    nW = int(con.execute("SELECT count(*) FROM wid").fetchone()[0])
    wcode = rows["wcode"].astype(np.int32); ccode = rows["ccode"].astype(np.int32)
    r = rows["r"].astype(np.int32); mth = rows["mth"].astype(np.int32); s = rows["s"].astype(np.int8)
    keep = (r >= 0) & (r < N); wcode, ccode, r, mth, s = wcode[keep], ccode[keep], r[keep], mth[keep], s[keep]
    del rows
    _q_sim, q_trail = ADJ.build_q_fixed(wcode, r, s.astype(np.float64), N)
    months = sorted(set(int(x) for x in np.unique(mth))); folds = months[4:]
    first_row = {"_ms": {}}
    for m in folds:
        rr = r[mth == m]; first_row[m] = int(rr.min()); first_row["_ms"][m] = int(hours[rr.min()])
    U4 = S0.xsec_rank(S0.fwd_sum(resid, H_TRAIN), alt_cols)[:, alt_cols]
    _log("training V-trail signal ...")
    R, Cc, Uc, Smat = S0.run_horizon(H_TRAIN, wcode, ccode, r, mth, q_trail, U4, LAG_ac, nW, folds,
                                     first_row, (CROWD, LAG_ac, np.zeros((N, n_alt))), do_placebos=False, seed=S0.SEED)
    Smat = Smat.astype(np.float32)
    crowd = CROWD[R, Cc].copy(); lag = LAG_ac[R, Cc].copy()
    for a in (crowd, lag): a[~np.isfinite(a)] = 0.0
    s_inf = S0.residualize(Smat[:, :1], np.column_stack([crowd, lag]), R)[:, 0].astype(np.float64)
    disp = np.nanstd(LAG_ac, axis=1)

    np.savez(CACHE, R=R.astype(np.int32), Cc=Cc.astype(np.int32), s_inf=s_inf, hours=hours.astype(np.int64),
             panel_month=panel_month.astype(np.int32), disp=disp.astype(np.float64), resid_alt=resid_alt,
             hs_arr=hs_arr, hs_default=np.float64(hs_default), n_alt=np.int64(n_alt),
             folds=np.array(folds, dtype=np.int64))
    _log(f"cached panel arrays → {CACHE}  ({len(R):,} OOS cells, {n_alt} alts)")


def ema_smooth(SIG, alpha, stale):
    """Strictly-causal per-column EMA with carry-forward + staleness drop. SIG[t,a]=NaN when unobserved.
    Returns m[t,a] = live smoothed belief or NaN if no live belief."""
    N, Acol = SIG.shape
    m = np.full((N, Acol), np.nan)
    prev = np.full(Acol, np.nan)
    last = np.full(Acol, -1_000_000, dtype=np.int64)
    for t in range(N):
        obs = SIG[t]; has = np.isfinite(obs)
        fresh = has & (~np.isfinite(prev) | ((t - last) > stale))   # reinitialize (no live prior)
        blend = has & ~fresh
        prev = np.where(fresh, obs, prev)
        prev = np.where(blend, alpha * obs + (1.0 - alpha) * prev, prev)
        last = np.where(has, t, last)
        alive = np.isfinite(prev) & ((t - last) <= stale)
        prev = np.where(alive, prev, np.nan)                        # a dropped belief resets (fresh on return)
        m[t] = np.where(alive, prev, np.nan)
    return m


def run_sweep():
    d = np.load(CACHE, allow_pickle=False)
    R, Cc, s_inf = d["R"], d["Cc"], d["s_inf"]
    hours = d["hours"]; panel_month = d["panel_month"]; disp = d["disp"]; resid_alt = d["resid_alt"]
    hs_arr = d["hs_arr"]; hs_default = float(d["hs_default"]); n_alt = int(d["n_alt"]); N = len(hours)
    halfspread = {i: float(hs_arr[i]) for i in range(n_alt)}
    hour_month = {}

    # dense observed-signal matrix + baseline active-hour rebalance grid (frozen across all cells)
    SIG = np.full((N, n_alt), np.nan)
    obs_hours = set()
    for i in range(len(R)):
        if np.isfinite(s_inf[i]):
            SIG[int(R[i]), int(Cc[i])] = s_inf[i]; obs_hours.add(int(R[i]))
    base_hours = np.array(sorted(obs_hours), dtype=np.int64)
    reb_grid = base_hours[::REB]
    for t in reb_grid: hour_month[int(t)] = int(panel_month[int(t)])
    FVr = S0.fwd_sum(resid_alt, REB)                                # [N,n_alt] forward REB-hour resid return (frac)

    dlo, dhi = np.nanpercentile(disp[np.isfinite(disp)], [33.3, 66.6])
    mid_ok = {int(t): (dlo < disp[int(t)] <= dhi) for t in reb_grid}
    full_set = set(range(n_alt))

    def eval_cell(alpha, stale, regime):
        m = ema_smooth(SIG, alpha, stale) if (stale > 0 or alpha < 1.0) else SIG
        xs_arr, fvb, elig = {}, {}, {}
        for t in reb_grid:
            ti = int(t); row = m[ti]; nm = np.nonzero(np.isfinite(row))[0]
            if len(nm) < 4: continue
            xs_arr[ti] = (nm.astype(int), row[nm].astype(float))
            fvb[ti] = {int(a): float(FVr[ti, a]) * 1e4 for a in nm}
            elig[ti] = full_set if (regime == "all" or mid_ok[ti]) else set()
        keys = np.array(sorted(xs_arr), dtype=np.int64)
        if len(keys) < 8: return None
        sim = CB.simulate_raw(keys, xs_arr, fvb, halfspread, hs_default, 1, 0.10, 0.15, elig)
        if len(sim["hr"]) < 8: return None
        hrs = sim["hr"].astype(np.int64); shm = np.array([hour_month[int(t)] for t in hrs])
        cell = {"alpha": alpha, "stale": stale, "regime": regime, "n_steps": int(len(hrs)),
                "gross_bp_per_hr": float((sim["gross"] / REB).mean()), "mean_turnover": float(sim["turn"].mean()),
                "scenarios": {}}
        for lab, mult, fee, mode in CB.SCENARIOS:
            netph, _ = CB.scenario_net_series(sim, REB, fee, mode, mult, hs_default)
            ci95 = CB._dayblock_ci(netph, hrs, hours)
            pf = {int(mm): float(netph[shm == mm].mean()) for mm in sorted(set(shm.tolist()))}
            st = ADJ.sign_test([v for v in pf.values()])
            cell["scenarios"][lab] = {"net": float(netph.mean()), "ci95": ci95,
                                      "folds_pos": int(sum(1 for v in pf.values() if v > 0)),
                                      "n_folds": len(pf), "sign_p": st["p"]}
        return cell

    results = {"config": {"reb": REB, "alphas": list(ALPHAS), "stales": list(STALES),
                          "n_alt": n_alt, "impact_hs_median_bp": hs_default}, "all": {}, "mid": {}}
    for regime in ("all", "mid"):
        print(f"\n================ REGIME = {regime.upper()} ================")
        print(f"{'alpha':>5} {'stale':>5} {'gross/hr':>9} {'turn':>6}   " +
              "  ".join(f"{l.replace('taker_top_','tk_').replace('maker_earn_','mk_'):>22}" for l in FOCUS))
        base = eval_cell(1.0, 0, regime)                     # deployed baseline
        for alpha in ALPHAS:
            for stale in STALES:
                if alpha == 1.0 and stale == 0:
                    cell = base
                else:
                    cell = eval_cell(alpha, stale, regime)
                key = f"a{alpha}_s{stale}"
                results[regime][key] = cell
                if cell is None:
                    print(f"{alpha:>5} {stale:>5}   (thin)"); continue
                cols = []
                for lab in FOCUS:
                    sc = cell["scenarios"][lab]; lo, hi = sc["ci95"]
                    star = "*" if lo > 0 else (" " if hi > 0 else "-")
                    cols.append(f"{sc['net']:+5.2f}[{lo:+4.1f},{hi:+4.1f}]{sc['folds_pos']}/{sc['n_folds']}{star}")
                tag = "  <= BASELINE" if (alpha == 1.0 and stale == 0) else ""
                print(f"{alpha:>5} {stale:>5} {cell['gross_bp_per_hr']:>+8.3f} {cell['mean_turnover']:>6.2f}   " +
                      "  ".join(f"{c:>22}" for c in cols) + tag)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=float))
    _log(f"wrote {OUT/'results.json'}")
    print("\nLegend: net[CI_lo,CI_hi]folds+  '*'=CI excludes 0 (>0), '-'=CI wholly <0, ' '=straddles 0.")
    print("Baseline (a1.0 s0) must match compare_pooled reb4: taker_smallclip ~+1.42/hr, maker_a30 ~+4.35/hr.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="force rebuild the panel cache")
    a = ap.parse_args()
    if a.rebuild or not CACHE.exists():
        build_cache()
    else:
        _log(f"using cached panel {CACHE}")
    run_sweep()


if __name__ == "__main__":
    main()
