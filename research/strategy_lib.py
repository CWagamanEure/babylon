#!/usr/bin/env python3
"""wallet_markout_router_v2 -- the frozen signal path, extracted verbatim from notebook 07.

This module is the single implementation of the selected strategy: the D0 wallet score
(`trailing_short_horizon_wallet_markout`), the event-quality aggregate, the trailing
empirical-CDF router, and the strict archetype-matched identity placebo. Notebooks 08 (PM
review), 09 (holdout) and the shadow runner all import from here so that presentation,
evaluation and live logging cannot drift from one another.

Execution machinery (portfolio simulator, stationary bootstrap, cost model) lives in
routing_lib.py; score/router plumbing shared with the bake-off lives in score_lib.py.

Nothing in this file may be changed without re-hashing and re-freezing the specification.
"""
import numpy as np
import pandas as pd

import score_lib as SL

BASE = "/Users/corywagamaneure/incerto-research/candle-rolloff-fade"

# ---- frozen constants (mirror frozen_spec_v2.yaml) ----
TRAIL_MONTHS = 3        # calendar months of trailing wallet history per vintage
MIN_FILLS = 100         # taker fills on net-buyer days required to be scored
MIN_HIST = 100          # prior eligible events required before the router takes risk
N_STRATA = 20           # propensity strata for the identity placebo
EPISODE_HOURS = 8
HOLD_MIN = 240
LATENCY_MIN = 1
SLOTS = 8


# ------------------------------------------------------------------ score
def build_d0(MB, FOLDS, MONTHS_ALL, trail=TRAIL_MONTHS, min_fills=MIN_FILLS):
    """trailing_short_horizon_wallet_markout: trailing mean 30m markout on net-buyer days.

    No standardization -- the t-stat's sd/sqrt(n) term was shown in notebook 07 to add no
    stable incremental event predictiveness (residual beta CI [-20, +386]).
    """
    out = {}
    for m in FOLDS:
        i = MONTHS_ALL.index(m)
        tr = (MB[MB.month.isin(MONTHS_ALL[i-trail:i])].groupby("address")
                .agg(n=("n", "sum"), s=("s", "sum")))
        tr = tr[tr.n >= min_fills]
        out[m] = pd.DataFrame({"address": tr.index, "score": (tr.s/tr.n).values,
                               "n_units": tr.n.values})
    return out


# ------------------------------------------------------------------ router
def trailing_cdf_weight(ts, q, min_hist=MIN_HIST):
    """w = clip(2u-1, -1, 1) where u is the event-quality percentile against STRICTLY PRIOR
    eligible first-signal events (expanding window). NaN until `min_hist` events exist."""
    order = np.argsort(np.asarray(ts.values), kind="stable")
    w = np.full(len(q), np.nan)
    hist = []
    for i in order:
        v = q[i]
        if len(hist) >= min_hist and np.isfinite(v):
            arr = np.asarray(hist)
            u = (np.sum(arr <= v) + 0.5)/(len(arr) + 1.0)
            w[i] = np.clip(2*u - 1, -1, 1)
        if np.isfinite(v):
            hist.append(v)
    return w


def route(FIRST, scores_by_fold, BR, min_hist=MIN_HIST):
    """first-signal entries -> event quality, coverage and router weight"""
    ent = SL.attach(FIRST, SL.router_weights(scores_by_fold, BR))
    ent["w_cal"] = trailing_cdf_weight(ent.ts, ent.quality.values, min_hist)
    return ent


# ------------------------------------------------------------------ evaluation
def full_eval(FR, ent, w, tag, RL, H=HOLD_MIN, horizons=(30, 60, 120, 240, 480)):
    """frozen per-trade + daily + portfolio statistics, with latency and leave-one-out"""
    w = np.asarray(w, dtype=float)
    w = np.where(np.isfinite(w), w, 0.0)
    st = RL.trade_stats(FR, ent, w, tag)
    _, sim = FR.simulate(ent, w, label=tag)
    for lat in (5, 15):
        _, s = FR.simulate(ent, w, latency=lat, label=tag)
        st[f"port_lat{lat}"] = s["daily_bps"]
    r = w*ent[f"adj{H}"].values
    km, kc = ent.ts.dt.strftime("%Y-%m"), ent.coin
    st["loo_month_min"] = min(FR.daily_vec(ent.ts[(km != k).values], r[(km != k).values]).mean()*1e4
                              for k in km.unique())
    st["loo_coin_min"] = min(FR.daily_vec(ent.ts[(kc != k).values], r[(kc != k).values]).mean()*1e4
                             for k in kc.unique() if (kc != k).sum() > 30)
    st.update(port_net=sim["daily_bps"], port_lo=sim["lo"], port_hi=sim["hi"],
              port_p=sim["p_gt0"], sharpe=sim["sharpe"], max_dd=sim["max_dd_bps"],
              turnover=sim["turnover_per_day"], active_days=sim["active_days"])
    return st, sim


def event_regression(FR, ent, qcol="quality", H=HOLD_MIN, B=2000):
    """adj{H} ~ event_quality with a CORRECT stationary bootstrap.

    Each replication reconstructs the event sample by appending every event of each sampled
    calendar day, once per time that day is drawn. A membership test (`np.isin`) would discard
    multiplicity and produce intervals that are too narrow.
    """
    m = ent[qcol].notna() & ent[f"adj{H}"].notna()
    e = ent[m]
    y = e[f"adj{H}"].values
    X = np.c_[np.ones(len(e)), e[qcol].values]
    beta = np.linalg.lstsq(X, y, rcond=None)[0][1]
    d = e.ts.dt.floor("D").map(FR.day_pos).values
    idx_by_day = {}
    for i, k in enumerate(d):
        idx_by_day.setdefault(int(k), []).append(i)
    idx_by_day = {k: np.asarray(v) for k, v in idx_by_day.items()}
    draws = np.empty(B)
    for b in range(B):
        parts = [idx_by_day[int(x)] for x in FR.BOOT[b] if int(x) in idx_by_day]
        if not parts:
            draws[b] = np.nan
            continue
        idx = np.concatenate(parts)
        draws[b] = np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][1]
    draws = draws[np.isfinite(draws)]
    return dict(beta_bps=beta*1e4, lo=np.percentile(draws, 2.5)*1e4,
                hi=np.percentile(draws, 97.5)*1e4, p_beta_gt0=float((draws > 0).mean()),
                n_events=int(len(e)), n_days=int(e.ts.dt.floor("D").nunique()), n_boot=len(draws))


# ------------------------------------------------------------------ identity placebo
def event_freq_asof(BR_ALL_sorted, fold):
    start = pd.Period(fold, "M").start_time.tz_localize("UTC")
    return BR_ALL_sorted[BR_ALL_sorted.ts < start].groupby("address").size()


def propensity_strata(sc_by_fold, MB, MONTHS_ALL, FOLDS, BR_ALL_sorted, n_strata=N_STRATA):
    """propensity strata from ex-ante observable archetype only -- no outcome data"""
    out = {}
    for m in FOLDS:
        if m not in sc_by_fold:
            continue
        i = MONTHS_ALL.index(m)
        tr = (MB[MB.month.isin(MONTHS_ALL[i-TRAIL_MONTHS:i])].groupby("address")
                .agg(n=("n", "sum"), notl=("notl", "sum"), s=("s", "sum"), sq=("sq", "sum"),
                     days=("days", "sum"), coins=("coins", "mean"), maker=("maker_notl", "sum")))
        mean = tr.s/tr.n
        sd = np.sqrt((tr.sq/tr.n - mean**2).clip(lower=1e-12))
        ef = event_freq_asof(BR_ALL_sorted, m).reindex(tr.index).fillna(0.0)
        X = pd.DataFrame({"log_n": np.log(tr.n.clip(lower=1)),
                          "log_notl": np.log(tr.notl.clip(lower=1)),
                          "avg_clip": np.log((tr.notl/tr.n.clip(lower=1)).clip(lower=1)),
                          "days": tr.days, "event_freq": np.log1p(ef),
                          "coin_conc": 1.0/tr.coins.clip(lower=1),
                          "taker_share": tr.notl/(tr.notl + tr.maker).clip(lower=1),
                          "mo_vol": np.log(sd.clip(lower=1e-9))}, index=tr.index).rank(pct=True)
        s = sc_by_fold[m].dropna(subset=["score"]).copy()
        X = X.reindex(s.address).fillna(0.5)
        y = (s.score >= s.score.quantile(0.8)).astype(float).values
        A = np.c_[np.ones(len(X)), X.values]
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        s["prop"] = A @ beta
        s["stratum"] = pd.qcut(s.prop.rank(method="first"), n_strata, labels=False,
                               duplicates="drop")
        out[m] = s
    return out


def perm_p(draws, real):
    """finite-permutation p: (1 + #{placebo >= real}) / (B + 1). Never 0."""
    return (1 + int((np.asarray(draws) >= real).sum()))/(len(draws) + 1)


def strict_placebo(FR, FIRST, BR, sc_by_fold, MB, MONTHS_ALL, FOLDS, BR_ALL_sorted, RL,
                   rng, nrep=150, nrep_port=60, H=HOLD_MIN):
    """shuffle scores only within propensity strata; rebuild the entire router each time"""
    prep = propensity_strata(sc_by_fold, MB, MONTHS_ALL, FOLDS, BR_ALL_sorted)
    ent_real = route(FIRST, sc_by_fold, BR)
    w_real = np.nan_to_num(ent_real.w_cal.values)
    r_real = w_real*ent_real[f"adj{H}"].values
    _, sim_real = FR.simulate(ent_real, w_real, label="")
    tr_, dl_, pt_ = [], [], []
    for rep in range(nrep):
        shuf = {}
        for m, s in prep.items():
            v = s.score.values.copy()
            for _, idx in s.groupby("stratum").indices.items():
                v[idx] = rng.permutation(v[idx])
            shuf[m] = s.assign(score=v)
        ent = route(FIRST, shuf, BR)
        w = np.nan_to_num(ent.w_cal.values)
        r = w*ent[f"adj{H}"].values
        tr_.append(np.nanmean(r)*1e4)
        dl_.append(FR.daily_vec(ent.ts, r).mean()*1e4)
        if rep < nrep_port:
            _, s_ = FR.simulate(ent, w, label="")
            pt_.append(s_["daily_bps"])
    tr_, dl_, pt_ = np.array(tr_), np.array(dl_), np.array(pt_)
    real_tr = np.nanmean(r_real)*1e4
    real_dl = FR.daily_vec(ent_real.ts, r_real).mean()*1e4
    return dict(real_trade=real_tr, plc_trade=tr_.mean(), incr_trade=real_tr - tr_.mean(),
                p_trade=perm_p(tr_, real_tr), n_perm_trade=len(tr_),
                real_daily=real_dl, plc_daily=dl_.mean(), incr_daily=real_dl - dl_.mean(),
                p_daily=perm_p(dl_, real_dl),
                real_port=sim_real["daily_bps"], plc_port=pt_.mean(),
                incr_port=sim_real["daily_bps"] - pt_.mean(),
                p_port=perm_p(pt_, sim_real["daily_bps"]), n_perm_port=len(pt_),
                plc_port_sd=float(pt_.std()),
                draws_trade=tr_, draws_daily=dl_, draws_port=pt_)
