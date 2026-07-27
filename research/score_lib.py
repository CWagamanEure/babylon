#!/usr/bin/env python3
"""Wallet-score and router construction, extracted verbatim from notebook 06 so that later
notebooks import the same code rather than a copy of it.

Scores: S0 (incumbent 30m per-fill t on net-buyer days), S1 (day-level classical),
S2 (robust day-level Huber/MAD), S3 (shrunk robust empirical Bayes).
Routers: A (rank-share top 20%), B (continuous score-weighted percentile).

Frozen parameters live here as module constants; notebook 06's frozen-degrees-of-freedom table
is the authority on what they mean.
"""
import glob

import numpy as np
import pandas as pd
from scipy import stats as sps

BASE = "/Users/corywagamaneure/incerto-research/candle-rolloff-fade"

MIN_UNITS = 15         # trailing units required to be scored (S1/S2/S3)
MIN_FILLS_0 = 100      # S0's own requirement
HUBER_C = 1.345
MAD_CONST = 0.6745
TRAIL_MONTHS = 3
TOP_Q = 0.20


# ------------------------------------------------------------------ inputs
def load_buyer_rows(FIRST):
    """signal-window net buyers at each first-signal event"""
    cols = ["event_id", "address", "seg", "tk_buy_notl", "tk_sell_notl"]
    want = set(FIRST.event_id); parts = []
    for f in sorted(glob.glob(f"{BASE}/data/panel_event_wallet/*.parquet")):
        d = pd.read_parquet(f, columns=cols)
        d = d[(d.seg.astype(str) == "sig") & d.event_id.isin(want)]
        if len(d):
            parts.append(d)
    BR = pd.concat(parts, ignore_index=True)
    BR = BR[BR.tk_buy_notl > BR.tk_sell_notl][["event_id", "address", "tk_buy_notl"]]
    return BR.merge(FIRST[["event_id", "fold", "ts"]], on="event_id")


def load_units():
    """wallet x coin x day buy-side 4h market-adjusted markout units"""
    parts = []
    for f in sorted(glob.glob(f"{BASE}/data/wallet_units/*.parquet")):
        d = pd.read_parquet(f, columns=["address", "coin", "buy_notl", "mo240"])
        d["day"] = f.split("/")[-1][:10]
        parts.append(d)
    U = pd.concat(parts, ignore_index=True).dropna(subset=["mo240"])
    U["month"] = U.day.str[:7]
    U["address"] = U.address.astype("category")
    return U


def load_wallet_months():
    """monthly net-buyer-day aggregates -- the source S0 is built from"""
    parts = []
    for f in sorted(glob.glob(f"{BASE}/data/fills_agg/wallet_day/*.parquet")):
        d = pd.read_parquet(f, columns=["address", "n_taker", "taker_notl", "s_notl",
                                        "mo30s", "mo30sq", "n_coins", "max_fill",
                                        "maker_notl"])
        d = d[d.s_notl > 0]
        d["month"] = f.split("/")[-1][:7]
        parts.append(d)
    wb = pd.concat(parts, ignore_index=True)
    return (wb.groupby(["address", "month"])
              .agg(n=("n_taker", "sum"), notl=("taker_notl", "sum"), s=("mo30s", "sum"),
                   sq=("mo30sq", "sum"), days=("n_taker", "size"),
                   coins=("n_coins", "mean"), max_fill=("max_fill", "max"),
                   maker_notl=("maker_notl", "sum")).reset_index())


def folds_from(mb, first="2025-11", last="2026-07"):
    months = sorted(mb.month.unique())
    return [m for m in months[TRAIL_MONTHS:] if first <= m <= last], months


# ------------------------------------------------------------------ S0
def trailing_S0(mb, FOLDS, months_all):
    """incumbent score: t = mean/(sd/sqrt(n)) of 30m markouts, fills as observations"""
    out = {}
    for m in FOLDS:
        i = months_all.index(m)
        tr = (mb[mb.month.isin(months_all[i-TRAIL_MONTHS:i])].groupby("address")
                .agg(n=("n", "sum"), s=("s", "sum"), sq=("sq", "sum")))
        tr = tr[tr.n >= MIN_FILLS_0]
        mean = tr.s/tr.n
        var = (tr.sq/tr.n - mean**2).clip(lower=1e-12)
        out[m] = pd.DataFrame({"address": tr.index, "score": (mean/np.sqrt(var/tr.n)).values,
                               "n_units": tr.n.values})
    return out


# ------------------------------------------------------------------ S1 / S2 / S3
def _grouped(u):
    u = u.sort_values("address_code", kind="stable")
    x = u.mo240.to_numpy(dtype=float)
    codes = u.address_code.to_numpy()
    starts = np.r_[0, np.flatnonzero(np.diff(codes)) + 1]
    n = np.diff(np.r_[starts, len(codes)])
    return x, codes[starts], starts, n


def huber_location(x, starts, n, scale, c=HUBER_C, iters=25):
    mu = np.add.reduceat(x, starts)/n
    for _ in range(iters):
        s = np.repeat(np.where(scale > 0, scale, np.inf), n)
        z = (x - np.repeat(mu, n))/s
        step = np.add.reduceat(np.clip(z, -c, c)*s, starts)/n
        mu = mu + step
        if np.nanmax(np.abs(step)) < 1e-12:
            break
    return mu


def build_scores(kind, U, FOLDS):
    out = {}
    for m in FOLDS:
        p = pd.Period(m, "M")
        lo = (p - TRAIL_MONTHS).start_time.strftime("%Y-%m-%d")
        last_day = (p.start_time - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        u = U[(U.day >= lo) & (U.day < last_day)]      # leakage guard: final day dropped
        u = u.assign(address_code=u.address.cat.codes)
        cnt = u.groupby("address_code", observed=True).mo240.size()
        u = u[u.address_code.isin(set(cnt[cnt >= MIN_UNITS].index))]
        if not len(u):
            continue
        u = u.sort_values("address_code", kind="stable").reset_index(drop=True)
        x, codes, starts, n = _grouped(u)
        mean = np.add.reduceat(x, starts)/n
        var = np.add.reduceat(x**2, starts)/n - mean**2
        sd = np.sqrt(np.clip(var, 1e-18, None))*np.sqrt(n/np.maximum(n-1, 1))
        if kind == "S1":
            score, extra = mean/(sd/np.sqrt(n)), {}
        else:
            med = u.groupby("address_code", observed=True, sort=True).mo240.median().to_numpy()
            mad = (u.assign(d=(u.mo240 - np.repeat(med, n)).abs())
                     .groupby("address_code", observed=True, sort=True).d.median().to_numpy())
            scale = np.where(mad > 0, mad/MAD_CONST, sd)
            mu = huber_location(x, starts, n, scale)
            se = scale/np.sqrt(n)
            if kind == "S2":
                score = mu/se
                extra = {"huber_mu": mu, "robust_se": se, "median": med, "unit_sd": sd}
            else:
                v = se**2
                mu0 = np.average(mu, weights=1/np.maximum(v, 1e-18))
                tau2 = max(float(np.var(mu, ddof=1) - np.mean(v)), 1e-12)
                post = (mu/v + mu0/tau2)/(1/v + 1/tau2)
                post_sd = np.sqrt(1/(1/v + 1/tau2))
                score = post
                extra = {"huber_mu": mu, "post_sd": post_sd, "raw": mu, "unit_sd": sd,
                         "robust_scale": scale, "p_alpha_pos": sps.norm.cdf(post/post_sd),
                         "shrink": 1 - tau2/(tau2 + v), "tau2": np.repeat(tau2, len(mu))}
        cats = u.address.cat.categories
        out[m] = pd.DataFrame({"address": cats[codes], "score": score, "n_units": n, **extra})
    return out


# ------------------------------------------------------------------ routers
def router_weights(scores_by_fold, BR, top_q=TOP_Q):
    """rank-share (A) and continuous percentile (B) aggregates per event"""
    out = []
    for fold, sc in scores_by_fold.items():
        b = BR[BR.fold == fold]
        if not len(b) or not len(sc):
            continue
        s = sc.dropna(subset=["score"]).copy()
        s["pct"] = s.score.rank(pct=True, method="first")
        s["is_top"] = s.score >= s.score.quantile(1 - top_q)
        j = b.merge(s[["address", "pct", "is_top"]], on="address", how="left")
        tot = j.groupby("event_id").tk_buy_notl.sum()
        scored = j.assign(x=j.tk_buy_notl.where(j.pct.notna(), 0.0)).groupby("event_id").x.sum()
        topn = j.assign(x=j.tk_buy_notl.where(j.is_top.fillna(False), 0.0)).groupby("event_id").x.sum()
        qsum = j.assign(x=(j.tk_buy_notl*j.pct).fillna(0.0)).groupby("event_id").x.sum()
        out.append(pd.DataFrame({"event_id": tot.index, "tot": tot.values, "scored": scored.values,
                                 "top_notl": topn.values, "qsum": qsum.values}))
    D = pd.concat(out, ignore_index=True)
    D["share"] = D.top_notl/D.tot.clip(lower=1.0)
    D["coverage"] = D.scored/D.tot.clip(lower=1.0)
    D["quality"] = D.qsum/D.scored.clip(lower=1.0)
    D["wA"] = 2*D.share - 1
    D["wB"] = np.clip(2*D.quality - 1, -1, 1)
    return D


def attach(FIRST, weights):
    return FIRST.merge(weights, on="event_id", how="left")
