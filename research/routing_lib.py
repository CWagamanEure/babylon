#!/usr/bin/env python3
"""Frozen evaluation machinery for the buy-skill router.

Everything in this module is held fixed across the wallet-score bake-off (notebook 06): the
episode universe, the first-signal entry, the stateful portfolio simulator, the costs, the
latency, the slot limit, the stationary bootstrap, and the placebo procedure. The bake-off
varies ONLY the wallet score. The functions are the same ones notebook 05 ran inline; 06
asserts it reproduces 05's S0 numbers before comparing anything.
"""
import numpy as np
import pandas as pd

BASE = "/Users/corywagamaneure/incerto-research/candle-rolloff-fade"

# ---- frozen strategy constants (identical to 05 / frozen_spec_v2_candidate.yaml) ----
H_PRIMARY = 240
HORIZONS = (30, 60, 120, 240, 480)
SPLIT = pd.Timestamp("2026-04-01", tz="UTC")
FEE_BPS, SLIP_BPS = 4.5, 2.0
HALF_SPREAD = {0: 20.0, 1: 8.0, 2: 4.0}
LATENCY_M = 1
SLOTS = 8
NBOOT = 4000
MEAN_BLOCK = 5


class Frame:
    """Calendar + bootstrap indices + price matrix, built once and shared by every score."""

    def __init__(self, events, seed=20260726):
        self.rng = np.random.default_rng(seed)
        self.E = events
        self.CAL = pd.DatetimeIndex(sorted(events.ts.dt.floor("D").unique()))
        self.NDAY = len(self.CAL)
        self.day_pos = {d: i for i, d in enumerate(self.CAL)}
        z = np.load(f"{BASE}/data/cache_price_matrix.npz", allow_pickle=True)
        self.P = z["P"]
        self.PIDX = pd.DatetimeIndex(z["idx"]).tz_localize("UTC")
        self.cols = list(z["cols"])
        self.cpos = {c: j for j, c in enumerate(self.cols)}
        self.pos_ts = {t: i for i, t in enumerate(self.PIDX)}
        self.IB = self.cpos["BTC"]
        self.LOGRET = np.diff(np.log(self.P), axis=0)
        self.BOOT = self.stationary_boot()

    def stationary_boot(self, B=NBOOT, mean_block=MEAN_BLOCK):
        idx = np.empty((B, self.NDAY), dtype=int)
        for b in range(B):
            out = np.empty(self.NDAY, dtype=int); i = 0
            while i < self.NDAY:
                s = int(self.rng.integers(0, self.NDAY))
                L = min(int(self.rng.geometric(1/mean_block)), self.NDAY - i)
                out[i:i+L] = (s + np.arange(L)) % self.NDAY; i += L
            idx[b] = out
        return idx

    def daily_vec(self, ts, r):
        d = pd.DataFrame({"ts": pd.Series(ts).reset_index(drop=True),
                          "r": np.asarray(r, dtype=float)}).dropna()
        v = np.zeros(self.NDAY)
        if not len(d):
            return v
        port = d.groupby("ts").r.mean()
        day = port.groupby(port.index.floor("D")).mean()
        for k, val in day.items():
            if k in self.day_pos:
                v[self.day_pos[k]] = val
        return v

    def ci(self, v):
        draws = v[self.BOOT].mean(axis=1)
        return dict(mean=v.mean()*1e4, lo=np.percentile(draws, 2.5)*1e4,
                    hi=np.percentile(draws, 97.5)*1e4, p_gt0=float((draws > 0).mean()))

    def clustered_t(self, ts, r):
        s = pd.Series(np.asarray(r, dtype=float), index=pd.Series(ts).reset_index(drop=True).values).dropna()
        if len(s) < 5:
            return np.nan
        day = s.groupby(pd.DatetimeIndex(s.index).floor("D")).mean()
        return day.mean()/(day.std(ddof=1)/np.sqrt(len(day))) if len(day) > 2 else np.nan

    def simulate(self, entries, w, latency=LATENCY_M, slots=SLOTS, hold=H_PRIMARY,
                 costs=True, label=""):
        """fixed-capital, slot-limited portfolio -> (daily vector, stats)"""
        d = entries.assign(w=np.asarray(w, dtype=float)).sort_values("ts")
        pnl = np.zeros(len(self.P))
        turnover = 0.0
        free_at = np.zeros(slots); taken = skipped = 0
        for r in d.itertuples():
            i0 = self.pos_ts.get(r.ts); j = self.cpos.get(r.coin)
            if i0 is None or j is None or not np.isfinite(r.w) or r.w == 0:
                continue
            i0 += latency
            i1 = min(i0 + hold, len(self.P) - 1)
            if i1 <= i0:
                continue
            s = int(np.argmin(free_at))
            if free_at[s] > i0:
                skipped += 1; continue
            free_at[s] = i1
            size = (1.0/slots) * min(abs(r.w), 1.0)
            seg = np.nan_to_num(self.LOGRET[i0:i1, j] - self.LOGRET[i0:i1, self.IB])
            pnl[i0:i1] += np.sign(r.w) * size * seg
            turnover += 2*size
            if costs:
                pnl[i0] -= size * r.cost_bps/1e4
            taken += 1
        daily = pd.Series(pnl, index=self.PIDX).groupby(self.PIDX.floor("D")).sum()
        v = np.zeros(self.NDAY)
        for k, val in daily.items():
            if k in self.day_pos:
                v[self.day_pos[k]] = val
        c = self.ci(v)
        eq = np.cumsum(v)
        sharpe = v.mean()/v.std(ddof=1)*np.sqrt(365) if v.std() > 0 else np.nan
        return v, dict(sim=label, trades=taken, skipped=skipped, daily_bps=c["mean"],
                       lo=c["lo"], hi=c["hi"], p_gt0=c["p_gt0"], sharpe=sharpe,
                       max_dd_bps=float((np.maximum.accumulate(eq) - eq).max())*1e4,
                       active_days=float((v != 0).mean()),
                       turnover_per_day=turnover/self.NDAY)


def first_signals(E):
    """one entry per anchored episode: the first B0-eligible event. Frozen universe."""
    d = E[E.eligible].sort_values(["epi_id", "ts"])
    f = d.groupby("epi_id").head(1).copy()
    return f[f[f"adj{H_PRIMARY}"].notna()]


def trade_stats(fr, entries, w, tag=""):
    """per-trade and daily-estimand statistics for a routed weight vector"""
    w = np.asarray(w, dtype=float)
    r = w * entries[f"adj{H_PRIMARY}"].values
    cost = np.abs(np.clip(w, -1, 1)) * entries.cost_bps.values/1e4
    g, n = fr.ci(fr.daily_vec(entries.ts, r)), fr.ci(fr.daily_vec(entries.ts, r - cost))
    out = dict(tag=tag, n=len(entries), gross_per_trade=np.nanmean(r)*1e4,
               net_per_trade=np.nanmean(r - cost)*1e4, median_bps=np.nanmedian(r)*1e4,
               hit=float(np.nanmean(r > 0)), daily_gross=g["mean"], lo=g["lo"], hi=g["hi"],
               p_gt0=g["p_gt0"], daily_net=n["mean"], net_lo=n["lo"], net_hi=n["hi"],
               net_p=n["p_gt0"], day_t=fr.clustered_t(entries.ts, r))
    for h in HORIZONS:
        out[f"h{h}"] = np.nanmean(w * entries[f"adj{h}"].values)*1e4
    for lbl, m in (("pre_apr", entries.ts < SPLIT), ("apr_jul", entries.ts >= SPLIT)):
        out[f"{lbl}_bps"] = np.nanmean((w * entries[f"adj{H_PRIMARY}"].values)[m.values])*1e4
    return out
