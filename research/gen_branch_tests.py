#!/usr/bin/env python3
"""Generate 04_event_wallet_branch_tests.ipynb -- non-nested branch tests on the
event x wallet x episode panel.

Why this notebook exists (2026-07-26 correction to ladder A-H): the ladder was a *nested*
sequence of filters, each row conditioning on every row above it, and rows C-H did not in
fact test their labeled hypotheses because the wallet identity behind the flow was missing.
This notebook replaces it with:

  * one common episode-level universe and estimand (anchored 8h episodes, one entry per
    episode, equal-weighted timestamp portfolio, mean daily policy return over the fixed
    calendar so selectivity is priced in);
  * BRANCHES, not a ladder -- each branch changes exactly one dimension relative to the same
    baseline, so a branch's result is attributable to its own hypothesis;
  * wallet-resolved features from the panel: real unique smart buyers, buy-side skill joined
    to the actual buyers, initiation read off position paths, opening share of *smart* flow,
    crowd measured against the matched population;
  * stateful entry policies as a separate branch dimension (the ladder tested only
    first-signal);
  * day-block bootstrap on the paired difference vs the baseline, plus a bootstrap max-t
    step-down over the whole branch family.

This runs on the SPENT discovery sample (2025-11-02 .. 2026-07-22). Nothing here validates
anything; the output is a ranked, honestly-priced set of candidate hypotheses. The post-
2026-07-22 holdout is not touched.
"""

import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []
md = lambda t: C.append(nbf.v4.new_markdown_cell(t))
code = lambda s: C.append(nbf.v4.new_code_cell(s))

# --------------------------------------------------------------------------- intro
md(r"""# Event × wallet × episode — non-nested branch tests

**What the correction demanded.** The A–H ladder's rows C–H did not test their labels:
buy-skill sets were never joined to flow (C was a no-op), `n_top` was summed across 5-minute
buckets instead of counting unique wallets (E), initiation used the generic cohort's daily
aggregate position (D), "opening share" was all-flow rather than smart flow (F), and the
crowd normalizer compared mismatched populations (G). Row B tested one episode policy, not
statefulness. The verdict was therefore *unvalidated and fragile*, *not falsified*, and the
required build was: an **event × wallet × episode panel** from a targeted fills re-read, then
**non-nested branch tests** against a **common episode-level baseline**, with stateful entry
policies and day-block inference on **actual position paths**.

That panel is `data/panel_event_wallet/` (built by `build_event_wallet_panel.py`): one row per
event × wallet × time-segment, carrying score-as-of, side, notional, position before/after/
delta, open–close class and entry time, for every wallet trading the coin in
[t−30m, t+240m] around each of the 12,725 burst events.

**Estimand (fixed once, used everywhere).**

1. Episodes are **anchored**: the first unassigned event of a coin opens an episode covering
   [t, t+8h); the next event after that span opens the next episode. (The ladder's gap-chained
   rule let busy coins chain for weeks — up to 427 events in one "episode" — which makes
   "one entry per episode" meaningless.)
2. A policy makes **at most one entry per episode**.
3. Entries sharing a timestamp are equal-weighted into a **timestamp portfolio**.
4. The headline statistic is the **mean daily policy return over the fixed 263-day calendar**,
   with 0 on days the policy does not trade. This is what makes non-nested branches
   comparable: a branch that trades a quarter as often must earn four times as much per trade
   to beat the baseline. Per-trade conditional means are reported alongside, never as the
   headline.
5. Inference is a **day-block bootstrap** that resamples calendar days and recomputes that same
   statistic; branch-vs-baseline differences are computed **paired on the same resampled days**.
6. Family-wise error over the branch family is controlled by a **bootstrap max-t step-down**.

**Direction and horizon**: policies are long-only follow-the-smart-buy (the frozen v1 stratum),
BTC-adjusted, primary horizon 4h, with 2h/8h shown.

**Sample discipline**: everything below is the spent discovery sample. No branch here is
validated by this notebook — a surviving branch is a *candidate* for a pre-registered v2 spec
evaluated on the untouched post-2026-07-22 holdout.""")

# --------------------------------------------------------------------------- setup
code(r'''import glob, os, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 80)

BASE    = "/Users/corywagamaneure/incerto-research/candle-rolloff-fade"
OUT_DIR = f"{BASE}/data/branch_out"; os.makedirs(OUT_DIR, exist_ok=True)
RNG     = np.random.default_rng(20260726)
NBOOT   = 4000
HORIZONS = (30, 60, 120, 240, 480)
H_PRIMARY = 240
SPLIT   = pd.Timestamp("2026-04-01", tz="UTC")   # known regime break (audit v2: ~2026-04-06)

# frozen cost model (frozen_spec.yaml)
FEE_BPS, SLIP_BPS = 4.5, 2.0
HALF_SPREAD = {0: 20.0, 1: 8.0, 2: 4.0}          # illiquid / mid / liquid tercile

EV = pd.read_parquet(f"{BASE}/data/panel_events.parquet")
print(f"events {len(EV):,} | anchored episodes {EV.epi_id.nunique():,} | "
      f"coins {EV.coin.nunique()} | {EV.ts.min().date()} .. {EV.ts.max().date()}")
print("episode size (anchored):", EV.groupby("epi_id").size().describe()[["mean","50%","max"]].round(2).to_dict())
print("episode size (ladder's chained rule):", EV.groupby("epi_chain_id").size().describe()[["mean","50%","max"]].round(2).to_dict())''')

code(r'''# ---- panel load (event x wallet x segment) --------------------------------
PCOLS = ["event_id","address","seg","grp","score_t","score_dec","n","notl","tk_buy_notl",
         "tk_sell_notl","open_notl","close_notl","liq_notl","max_clip","first_rel_s",
         "pos_before","pos_after","pos_delta","signed_sz"]
files = sorted(glob.glob(f"{BASE}/data/panel_event_wallet/*.parquet"))
# only the signal window is needed here; the post-event segments stay on disk (they exist for
# the arrival work, and loading all of them would not fit comfortably in this machine's RAM)
parts = []
for f in files:
    d = pd.read_parquet(f, columns=PCOLS)
    parts.append(d[d.seg.astype(str) == "sig"])
PAN = pd.concat(parts, ignore_index=True); del parts
print(f"signal-window panel rows {len(PAN):,} | events covered {PAN.event_id.nunique():,}/{len(EV):,} | "
      f"wallets {PAN.address.nunique():,} | day files {len(files)}")

# position-path integrity: within a segment, pos_after - pos_before must equal the signed size
rel = ((PAN.pos_delta - PAN.signed_sz).abs()
       / PAN[["pos_before","pos_after"]].abs().max(axis=1).clip(lower=1))
bad = rel > 1e-6
print(f"position-path check: {int(bad.sum())} of {len(PAN):,} signal-window rows break "
      f"pos_after - pos_before == signed size ({bad.mean():.2e})")
if bad.any():
    print("  affected events:", PAN.loc[bad, "event_id"].value_counts().head().to_dict())
    print("  (a handful of coin-minutes where the venue's start_position does not reconcile "
          "with the fill stream; position-based features are read as signs, not magnitudes)")''')

# --------------------------------------------------------------------------- features
md(r"""## 1. Wallet-resolved event features

Everything the ladder claimed to condition on, rebuilt from wallet-level rows in the **signal
window** `seg == "sig"` = [t−15m, t] — exactly the frozen spec's window (burst bucket + prior
two), so these are strict upgrades of the `attrib_5m` features, not a different specification.

| feature | ladder version (defective) | here |
|---|---|---|
| smart share / imbalance | top-cohort notional from 5m aggregate | same, but wallet-resolved (identical by construction — the control) |
| unique smart buyers | `n_top` summed over buckets (double counts) | `nunique(address)` among top-decile buyers |
| buy-skill | fold membership only; never joined to flow | per-wallet buy-side score joined to the wallets actually buying |
| initiation | prior-day aggregate position of the whole cohort | each smart buyer's own `pos_before` at the event |
| opening share | open share of **all** flow | open share of **smart** flow, and from the position path |
| crowd | non-smart notional ÷ whole-market typical volume | non-smart notional ÷ **that coin's own trailing non-smart** signal-window norm |""")

code(r'''# ---- buy-side skill, walk-forward, joined to wallets (fixes ladder row C) ----
wd = sorted(glob.glob(f"{BASE}/data/fills_agg/wallet_day/*.parquet"))
fr = []
for f in wd:
    d = pd.read_parquet(f, columns=["address","n_taker","s_notl","mo30s","mo30sq"])
    d = d[d.s_notl > 0]                      # net-buyer days only -> buy-side skill
    d["month"] = f.split("/")[-1][:7]
    fr.append(d)
wb = pd.concat(fr, ignore_index=True)
mb = (wb.groupby(["address","month"])
        .agg(n=("n_taker","sum"), s=("mo30s","sum"), sq=("mo30sq","sum")).reset_index())
months = sorted(mb.month.unique())
bs = []
for i in range(3, len(months)):
    tr = mb[mb.month.isin(months[i-3:i])].groupby("address").agg(n=("n","sum"), s=("s","sum"), sq=("sq","sum"))
    tr = tr[tr.n >= 100]
    mean = tr.s/tr.n; var = (tr.sq/tr.n - mean**2).clip(lower=1e-12)
    t = mean/np.sqrt(var/tr.n)
    dec = pd.qcut(t.rank(method="first"), 10, labels=False)
    bs.append(pd.DataFrame({"address": tr.index, "fold": months[i],
                            "buy_t": t.values, "buy_dec": dec.values.astype("int8")}))
BUY = pd.concat(bs, ignore_index=True)
print(f"buy-skill: {len(BUY):,} address-folds over {BUY.fold.nunique()} folds "
      f"(walk-forward, trailing 3 months, >=100 net-buyer-day fills)")''')

code(r'''# ---- signal-window wallet rows, with score-as-of and buy-skill on the SAME wallets ----
sig = PAN.merge(
    EV[["event_id","coin","ts","fold","sgn","epi_id","epi_rank"]], on="event_id", how="inner")
sig = sig.merge(BUY, on=["address","fold"], how="left")

sig["tk_notl"]  = sig.tk_buy_notl + sig.tk_sell_notl
sig["tk_net"]   = sig.tk_buy_notl - sig.tk_sell_notl
sig["is_top"]   = sig.grp.eq("top")
sig["is_bot"]   = sig.grp.eq("bot")
sig["is_buyer"] = sig.tk_net > 0
# initiation from the position path: the wallet was flat-or-short before its first fill and
# ended long -> it OPENED the exposure at this event, rather than adding to a standing one.
sig["dec_notl"]    = sig.buy_dec * sig.tk_buy_notl
sig["opened_long"] = (sig.pos_before <= 0) & (sig.pos_after > 0)
sig["added_long"]  = (sig.pos_before > 0)  & (sig.pos_delta > 0)

def wsum(mask, col):
    return sig[col].where(mask, 0.0).groupby(sig.event_id).sum()

top_buy   = sig.is_top & sig.is_buyer
bot_flow  = sig.is_bot
F = pd.DataFrame({
    "tot":            sig.groupby("event_id").tk_notl.sum(),
    "smart_tot":      wsum(sig.is_top, "tk_notl"),
    "smart_net":      wsum(sig.is_top, "tk_net"),
    "dumb_tot":       wsum(bot_flow, "tk_notl"),
    "dumb_net":       wsum(bot_flow, "tk_net"),
    "smart_buy_notl": wsum(top_buy, "tk_buy_notl"),
    "nonsmart_notl":  wsum(~sig.is_top, "tk_notl"),
    # --- unique buyers, actually unique (fixes E) ---
    "n_smart_buyers": sig[top_buy].groupby("event_id").address.nunique(),
    "n_buyers":       sig[sig.is_buyer].groupby("event_id").address.nunique(),
    # --- initiation from position paths (fixes D) ---
    "smart_open_notl": wsum(top_buy & sig.opened_long, "tk_buy_notl"),
    "smart_add_notl":  wsum(top_buy & sig.added_long,  "tk_buy_notl"),
    "n_smart_openers": sig[top_buy & sig.opened_long].groupby("event_id").address.nunique(),
    # --- opening share of SMART flow via the venue open/close class (fixes F) ---
    "smart_openclass_notl": wsum(top_buy, "open_notl"),
    "smart_allclass_notl":  wsum(top_buy, "notl"),
    # --- buy-side skill joined to the buyers who actually traded (fixes C) ---
    # NOTE: buy_dec >= 8 is the top TWO deciles (top 20%), not the top decile. That is
    # deliberate -- the buy-side score is estimated on net-buyer days only, so it is noisier
    # than the all-flow score and a wider bucket keeps the cell populated -- but it is a
    # different definition from the frozen spec's top-decile cohort and is labelled as such.
    "buyskill_notl":   wsum(sig.is_buyer & sig.buy_dec.ge(8), "tk_buy_notl"),
    "buyer_buy_notl":  wsum(sig.is_buyer, "tk_buy_notl"),
    "scored_buy_notl": wsum(sig.is_buyer & sig.buy_dec.notna(), "tk_buy_notl"),
    "buyskill10_notl": wsum(sig.is_buyer & sig.buy_dec.eq(9), "tk_buy_notl"),   # strict top decile
    "n_buyskill":      sig[sig.is_buyer & sig.buy_dec.ge(8)].groupby("event_id").address.nunique(),
    "dec_notl":        wsum(sig.is_buyer & sig.buy_dec.notna(), "dec_notl"),
    "liq_notl":        sig.groupby("event_id").liq_notl.sum(),
}).fillna(0.0)

F["smart_share"]   = F.smart_tot / F.tot.clip(lower=1.0)
F["smart_imb"]     = F.smart_net / F.smart_tot.clip(lower=1.0)
F["dumb_share"]    = F.dumb_tot / F.tot.clip(lower=1.0)
F["dumb_imb"]      = F.dumb_net / F.dumb_tot.clip(lower=1.0)
F["init_share"]    = F.smart_open_notl / F.smart_buy_notl.clip(lower=1.0)
F["openclass_share"] = F.smart_openclass_notl / F.smart_allclass_notl.clip(lower=1.0)
F["buyskill_share"] = F.buyskill_notl / F.buyer_buy_notl.clip(lower=1.0)
# `share` folds two different things together: how much of the buy flow came from wallets
# with enough history to be scored (coverage), and how good those scored wallets were
# (quality). Unscored wallets are unknown, not unskilled -- both are carried separately.
F["buyskill10_share"] = F.buyskill10_notl / F.buyer_buy_notl.clip(lower=1.0)
F["bs_coverage"] = F.scored_buy_notl / F.buyer_buy_notl.clip(lower=1.0)
F["bs_quality"]  = F.buyskill_notl / F.scored_buy_notl.clip(lower=1.0)
F["bs_decile"]   = F.dec_notl / F.scored_buy_notl.clip(lower=1.0)   # notional-wtd mean decile
E = EV.merge(F.reset_index(), on="event_id", how="inner")
print(f"events with signal-window flow: {len(E):,}/{len(EV):,}")
print(E[["smart_share","smart_imb","dumb_share","n_smart_buyers","init_share",
         "openclass_share","buyskill_share"]].describe().round(3).to_string())''')

code(r'''# ---- crowd, normalized against the MATCHED population (fixes G) ----
# baseline = the coin's own trailing-30-day median non-smart signal-window taker notional,
# computed from prior events only. Strictly backward-looking; no cross-population mixing.
E = E.sort_values("ts").reset_index(drop=True)
crowd = np.full(len(E), np.nan)
for coin, g in E.groupby("coin", sort=False):
    t = g.ts.values; v = g.nonsmart_notl.values; idx = g.index.values
    for k in range(len(g)):
        lo = t[k] - np.timedelta64(30, "D")
        prior = v[(t < t[k]) & (t >= lo)]
        if len(prior) >= 5:
            crowd[idx[k]] = v[k] / max(np.median(prior), 1.0)
E["crowd_ratio_matched"] = crowd
# the ladder's version, kept only as the contrast it is: whole-market daily volume / 96
cf = pd.read_parquet(f"{BASE}/data/coin_day_cohort_flow.parquet")[["coin","day","tot"]]
cf["day"] = cf.day + pd.Timedelta(days=1)
E = E.merge(cf.rename(columns={"tot":"liq_prev"}), on=["coin","day"], how="left")
E["crowd_ratio_ladder"] = E.nonsmart_notl / (E.liq_prev / 96)
print(E[["crowd_ratio_matched","crowd_ratio_ladder"]].describe().round(2).to_string())
print("matched-crowd coverage:", f"{E.crowd_ratio_matched.notna().mean():.1%}")''')

# --------------------------------------------------------------------------- returns
code(r'''# ---- forward returns (BTC-adjusted), entry at the event minute ----
z = np.load(f"{BASE}/data/cache_price_matrix.npz", allow_pickle=True)
P, PIDX, COLS = z["P"], pd.DatetimeIndex(z["idx"]).tz_localize("UTC"), list(z["cols"])
cpos = {c: j for j, c in enumerate(COLS)}; pos_ts = {t: i for i, t in enumerate(PIDX)}
IB = cpos["BTC"]

i_ = E.ts.map(pos_ts).to_numpy(); j_ = E.coin.map(cpos).to_numpy()
ok = pd.notna(i_) & pd.notna(j_)
i_ = np.where(ok, i_, 0).astype(int); j_ = np.where(ok, j_, 0).astype(int)
p0 = np.where(ok, P[i_, j_], np.nan); b0 = np.where(ok, P[i_, IB], np.nan)
for h in HORIZONS:
    ih = np.minimum(i_ + h, len(P) - 1)
    valid = ok & (i_ + h < len(P))
    p1 = np.where(valid, P[ih, j_], np.nan); b1 = np.where(valid, P[ih, IB], np.nan)
    E[f"adj{h}"] = (p1/p0 - 1) - (b1/b0 - 1)
    E[f"raw{h}"] = p1/p0 - 1
E["lq_tercile"] = pd.qcut(E.liq_prev.rank(method="first"), 3, labels=False)
E["cost_bps"]   = 2*(FEE_BPS + SLIP_BPS) + 2*E.lq_tercile.map(HALF_SPREAD).fillna(8.0)
print(f"return coverage @{H_PRIMARY}m: {E[f'adj{H_PRIMARY}'].notna().mean():.1%}")''')

# --------------------------------------------------------------------------- estimand
md(r"""## 2. The common estimand and its inference

A *policy* is a function from the event table to at most one entry per episode. Every policy is
scored the same way:

* per entry: direction-signed BTC-adjusted return at horizon *h*, gross and net of the frozen
  cost model (4.5bps fee + 2bps slip + liquidity-tercile half-spread, both sides);
* simultaneous entries → equal-weighted timestamp portfolio;
* **daily policy return** = mean of that day's timestamp portfolios, **0 on days with no
  entry**, over the fixed 263-day calendar;
* headline = mean daily policy return; CI = day-block bootstrap (resample days with
  replacement, recompute);
* branch vs baseline = **paired** difference on the same resampled days.

The zero-on-no-trade convention is what makes non-nested branches comparable at all: a filter
that removes trades must pay for the days it sits out.""")

code(r'''CAL = pd.DatetimeIndex(sorted(EV.ts.dt.floor("D").unique()))         # fixed calendar
NDAY = len(CAL); day_pos = {d: i for i, d in enumerate(CAL)}

def daily_series(entries, h=H_PRIMARY, net=False):
    """entries: df with ts, dir, adj{h}, cost_bps -> (daily vector over CAL, per-trade returns)"""
    if len(entries) == 0:
        return np.zeros(NDAY), np.array([])
    r = entries["dir"].values * entries[f"adj{h}"].values
    if net:
        r = r - entries.cost_bps.values/1e4
    d = pd.DataFrame({"ts": entries.ts.reset_index(drop=True), "r": r}).dropna()
    if len(d) == 0:
        return np.zeros(NDAY), np.array([])
    port = d.groupby("ts").r.mean()
    day = port.groupby(port.index.floor("D")).mean()
    v = np.zeros(NDAY)
    for dd, val in day.items():
        v[day_pos[dd]] = val
    return v, d.r.values

def stationary_boot(B=NBOOT, mean_block=5):
    """Stationary bootstrap: geometric blocks of ~5 trading days, wrapped.

    Resampling days independently (the first version of this notebook) preserves the
    within-day cross-section but destroys serial dependence between adjacent days, which
    is exactly the dependence the program has repeatedly found (regime persistence, weekly
    clustering). Blocks keep it.
    """
    idx = np.empty((B, NDAY), dtype=int)
    for b in range(B):
        out = np.empty(NDAY, dtype=int); i = 0
        while i < NDAY:
            start = int(RNG.integers(0, NDAY)); L = min(int(RNG.geometric(1/mean_block)), NDAY - i)
            out[i:i+L] = (start + np.arange(L)) % NDAY
            i += L
        idx[b] = out
    return idx

BOOT_IDX = stationary_boot()

def stat_ci(v, boot=None):
    boot = BOOT_IDX if boot is None else boot
    draws = v[boot].mean(axis=1)
    return dict(mean=v.mean()*1e4, lo=np.percentile(draws, 2.5)*1e4,
                hi=np.percentile(draws, 97.5)*1e4, p_gt0=float((draws > 0).mean()),
                t=v.mean()/(v.std(ddof=1)/np.sqrt(len(v))) if v.std() > 0 else np.nan)

def summarize(name, entries, h=H_PRIMARY):
    v_g, r_g = daily_series(entries, h, net=False)
    v_n, r_n = daily_series(entries, h, net=True)
    sg, sn = stat_ci(v_g), stat_ci(v_n)
    return dict(branch=name, n_trades=len(r_g), n_epi=entries.epi_id.nunique(),
                trade_days=int((v_g != 0).sum()),
                daily_gross=sg["mean"], lo=sg["lo"], hi=sg["hi"], p_gt0=sg["p_gt0"], t=sg["t"],
                daily_net=sn["mean"], net_lo=sn["lo"], net_hi=sn["hi"], net_p=sn["p_gt0"],
                per_trade_gross=r_g.mean()*1e4 if len(r_g) else np.nan,
                per_trade_net=r_n.mean()*1e4 if len(r_n) else np.nan,
                median_bps=np.median(r_g)*1e4 if len(r_g) else np.nan,
                hit=float((r_g > 0).mean()) if len(r_g) else np.nan)''')

# --------------------------------------------------------------------------- replication
md(r"""## 3. Where the v1 discovery numbers came from

Before testing any branch, locate the baseline. `smart_burst_follow_v1` was frozen off a
discovery cell of **+29bps @30m (t=2.4) rising to +107bps @8h (t=2.3), n=1,262** — the same
smart-buy × dumb-flat stratum this notebook uses as B0. The comparison below holds the *rule*
fixed and varies only the **unit of observation**:

* **event level** — every qualifying event counted separately, day-clustered t (what the
  discovery cell reported);
* **episode level** — one entry per anchored 8h episode, the estimand of this notebook;
* **de-overlapped** — additionally drop entries whose horizon window overlaps a prior entry in
  the same coin.

If the discovery number survives all three, the frozen spec was sound and the branches are
about improving it. If it does not, the branches are about whether anything can be recovered.""")

code(r'''# ---- the frozen v1 rule, wallet-resolved, and the two episode-level machines ----
BASE_MASK = (E.sgn > 0) & (E.smart_share >= 0.05) & (E.smart_imb >= 0.5) \
            & ~((E.dumb_share >= 0.05) & (E.dumb_imb.abs() >= 0.5))
E["eligible"] = BASE_MASK
print(f"eligible events {int(BASE_MASK.sum()):,} in {E[BASE_MASK].epi_id.nunique():,} episodes")
E.to_parquet(f"{BASE}/data/branch_events.parquet", index=False)   # consumed by notebook 05

def entries_from(mask, pick="first", key=None):
    """one entry per episode from the masked events; `pick` selects WHICH event."""
    d = E[mask].copy()
    if len(d) == 0:
        return d.assign(**{"dir": []})
    d = d.sort_values(["epi_id","ts"])
    if pick == "first":
        sel = d.groupby("epi_id").head(1)
    elif pick == "second":                       # requires a second eligible event
        sel = d.groupby("epi_id").nth(1)
    elif pick == "max":                          # strongest signal in the episode
        sel = d.loc[d.groupby("epi_id")[key].idxmax()]
    elif pick == "cum":                          # first event where cumulative smart buy > 2x
        d["cum"] = d.groupby("epi_id").smart_buy_notl.cumsum()
        d["thr"] = d.groupby("epi_id").smart_buy_notl.transform("first")*2
        sel = d[d.cum >= d.thr].groupby("epi_id").head(1)
    else:
        raise ValueError(pick)
    return sel.assign(**{"dir": 1.0})

def deoverlap(v, h=H_PRIMARY):
    """drop any entry whose horizon window overlaps a prior entry in the same coin"""
    keep, last = [], {}
    for r in v.sort_values("ts").itertuples():
        if r.coin in last and (r.ts - last[r.coin]).total_seconds()/60 < h:
            continue
        last[r.coin] = r.ts; keep.append(r.Index)
    return v.loc[keep]

B0 = entries_from(BASE_MASK, "first")

def cell_stat(d, h):
    r = (d["dir"]*d[f"adj{h}"]).dropna()
    if len(r) < 5:
        return "     few"
    day = r.groupby(d.loc[r.index, "ts"].dt.floor("D")).mean()
    t = day.mean()/(day.std(ddof=1)/np.sqrt(len(day)))
    return f"{r.mean()*1e4:+7.1f}(t{t:+.1f})"

units = [("event level (discovery unit)", E[BASE_MASK].assign(**{"dir": 1.0})),
         ("episode level, first signal",   B0),
         ("episode level, de-overlapped",  deoverlap(B0))]
print(f"{'unit':32s} {'n':>6s} " + " ".join(f"{h:>14}" for h in HORIZONS))
REPL = []
for lbl, d in units:
    print(f"{lbl:32s} {len(d):6d} " + " ".join(f"{cell_stat(d, h):>14}" for h in HORIZONS))
    REPL.append(dict(unit=lbl, n=len(d),
                     **{f"h{h}": (d['dir']*d[f'adj{h}']).mean()*1e4 for h in HORIZONS}))
pd.DataFrame(REPL).to_csv(f"{OUT_DIR}/discovery_replication.csv", index=False)
print("\nfrozen-spec discovery cell for reference: +29bps @30m (t=2.4), +107bps @8h (t=2.3), n=1,262")''')

# --------------------------------------------------------------------------- policies
md(r"""## 4. Baseline and branches

**B0 (baseline)** is the frozen v1 rule expressed at episode level: eligible events are
smart-buy (top-decile share ≥5%, signed imbalance ≥ +0.5) with the bottom-decile cohort flat,
direction long; the entry is the **first** eligible event in the episode.

Each branch changes **one** thing:

| branch | dimension changed | hypothesis it actually tests |
|---|---|---|
| B1 | skill definition | buy-side skill (net-buyer-day markouts) identifies better buyers than all-flow skill |
| B2 | initiation | flow from wallets *opening* exposure beats flow from wallets *adding* |
| B3 | consensus | ≥2 / ≥3 *unique* smart buyers beats one wallet's print |
| B4 | opening flow | majority of *smart* flow being position-opening matters |
| B5 | crowd | absence of matched-population crowd matters |
| B6 | entry policy | stateful entry (max-signal / second-signal / cumulative-threshold) beats first-signal |
| B7 | liquidation hygiene | no liquidation prints in the window |

Branches are not composed with each other — that is the whole point. Composition is what turned
the ladder into an un-attributable filter chain.""")

code(r'''BRANCHES = {
    "B0 baseline (frozen v1, first signal)":      B0,
    "B1 buy-skill(top20%) share >=50% of buy flow": entries_from(BASE_MASK & (E.buyskill_share >= 0.5), "first"),
    "B1b buy-skill(top20%) wallets present (>=2)": entries_from(BASE_MASK & (E.n_buyskill >= 2), "first"),
    "B2 initiation: >=50% smart buy from flat":   entries_from(BASE_MASK & (E.init_share >= 0.5), "first"),
    "B2b initiation: >=2 smart openers":          entries_from(BASE_MASK & (E.n_smart_openers >= 2), "first"),
    "B3 consensus: >=2 unique smart buyers":      entries_from(BASE_MASK & (E.n_smart_buyers >= 2), "first"),
    "B3b consensus: >=3 unique smart buyers":     entries_from(BASE_MASK & (E.n_smart_buyers >= 3), "first"),
    "B4 smart opening-class share >=50%":         entries_from(BASE_MASK & (E.openclass_share >= 0.5), "first"),
    "B5 crowd absent (matched, ratio<=2)":        entries_from(BASE_MASK & (E.crowd_ratio_matched <= 2.0), "first"),
    "B5b crowd absent (ladder normalizer)":       entries_from(BASE_MASK & (E.crowd_ratio_ladder <= 2.0), "first"),
    "B6 entry: max smart-buy notional in epi":    entries_from(BASE_MASK, "max", key="smart_buy_notl"),
    "B6b entry: max smart imbalance in epi":      entries_from(BASE_MASK, "max", key="smart_imb"),
    "B6c entry: second signal in episode":        entries_from(BASE_MASK, "second"),
    "B6d entry: cumulative smart buy >= 2x first": entries_from(BASE_MASK, "cum"),
    "B7 no liquidation prints in window":         entries_from(BASE_MASK & (E.liq_notl <= 0), "first"),
}
RES = pd.DataFrame([summarize(k, v) for k, v in BRANCHES.items()])
print(RES.round(2).to_string(index=False))
RES.to_csv(f"{OUT_DIR}/branch_summary.csv", index=False)''')

# --------------------------------------------------------------------------- paired
md(r"""## 5. Paired branch-vs-baseline differences (day-block, same resampled days)

The table above tells you what each branch earns. It does not tell you whether a branch is
*different from the baseline* — that needs the paired difference, because branch and baseline
share most of their trading days and their sampling errors are strongly correlated.

Two readings are reported for every branch:

* **Δ daily** — the difference in mean daily policy return, paired on resampled days. This is
  the decision-relevant number and prices selectivity.
* **partition** — the non-nested decomposition: episodes taken by *both*, by the *baseline
  only*, and by the *branch only*, with the mean per-trade return in each. A branch is
  informative when what it drops (baseline-only) is worse than what it keeps.""")

code(r'''def paired(name, entries, h=H_PRIMARY):
    v_b, _ = daily_series(B0, h); v_x, _ = daily_series(entries, h)
    d = v_x - v_b
    draws = d[BOOT_IDX].mean(axis=1)
    ep_b = set(B0.epi_id); ep_x = set(entries.epi_id)
    def m(sel):
        r = (sel["dir"]*sel[f"adj{h}"]).dropna()
        return r.mean()*1e4 if len(r) else np.nan, len(r)
    both  = m(B0[B0.epi_id.isin(ep_b & ep_x)])
    bonly = m(B0[B0.epi_id.isin(ep_b - ep_x)])
    xonly = m(entries[entries.epi_id.isin(ep_x - ep_b)])
    return dict(branch=name, d_daily=d.mean()*1e4,
                d_lo=np.percentile(draws,2.5)*1e4, d_hi=np.percentile(draws,97.5)*1e4,
                p_better=float((draws > 0).mean()),
                both_bps=both[0], n_both=both[1],
                base_only_bps=bonly[0], n_base_only=bonly[1],
                branch_only_bps=xonly[0], n_branch_only=xonly[1])

PAIR = pd.DataFrame([paired(k, v) for k, v in BRANCHES.items() if not k.startswith("B0")])
print(PAIR.round(2).to_string(index=False))
PAIR.to_csv(f"{OUT_DIR}/branch_paired.csv", index=False)''')

# --------------------------------------------------------------------------- maxT
md(r"""## 6. Family-wise error: bootstrap max-t step-down

Under the null that no branch differs from the baseline, the largest of many correlated
t-statistics is not distributed like one t-statistic. The step-down procedure recentres each
paired difference at its own mean (imposing the null), bootstraps the family jointly on the
same block resamples, and compares each observed |t| to the distribution of the family
maximum, dropping confirmed branches and repeating.

**Which branches belong in the family matters.** Two of them can never become strategies:
the `pick="max"` entry policies (B6, B6b) choose the strongest signal *within the episode*,
which requires knowing the episode's later events at entry time, and B5b is a diagnostic
control that deliberately uses the defective normalizer. Charging an executable candidate a
multiplicity penalty for tests that could never be deployed is a penalty for nothing. The
**confirmatory family** is the ex-ante executable branches; the full family is reported beside
it so the difference is visible rather than assumed.""")

code(r'''# ex-ante executable? (look-ahead entry policies and the diagnostic control are not)
EXECUTABLE = {k: not (("max " in k) or k.startswith("B5b")) for k in BRANCHES}
print("excluded from the confirmatory family:",
      [k for k, v in EXECUTABLE.items() if not v])

names = [k for k in BRANCHES if not k.startswith("B0")]
D = np.column_stack([daily_series(BRANCHES[k])[0] - daily_series(B0)[0] for k in names])
sd0 = D.std(0, ddof=1); sd0[sd0 == 0] = np.inf     # a branch identical to B0 has t = 0
obs_t = D.mean(0)/(sd0/np.sqrt(NDAY))
Dc = D - D.mean(0)                                  # impose the null
boot_t = np.empty((NBOOT, len(names)))
for b in range(NBOOT):
    s = Dc[BOOT_IDX[b]]
    sd = s.std(0, ddof=1); sd[sd == 0] = np.inf
    boot_t[b] = s.mean(0)/(sd/np.sqrt(NDAY))

def stepdown(members):
    """max-t step-down over the given subset of `names`; returns {branch: p_adj}"""
    cols = [i for i, n in enumerate(names) if n in members]
    order = sorted(cols, key=lambda i: -abs(obs_t[i]))
    alive = list(order); padj = {}; prev = 0.0
    for i in order:
        mx = np.abs(boot_t[:, alive]).max(axis=1)
        p = max(float((mx >= abs(obs_t[i])).mean()), prev)      # enforce monotonicity
        padj[names[i]] = prev = p
        alive.remove(i)
    return padj

conf_members = [n for n in names if EXECUTABLE[n]]
p_conf = stepdown(conf_members)
p_full = stepdown(names)
STEP = pd.DataFrame({"branch": names, "t_paired": obs_t,
                     "p_stepdown": [p_conf.get(n, np.nan) for n in names],
                     "p_stepdown_full_family": [p_full[n] for n in names],
                     "confirmatory": [EXECUTABLE[n] for n in names]}).sort_values("t_paired", key=np.abs, ascending=False)
print(STEP.round(3).to_string(index=False))
STEP.to_csv(f"{OUT_DIR}/branch_stepdown.csv", index=False)
print(f"\nconfirmatory family: {len(conf_members)} branches; full family: {len(names)}")
print("branches surviving FWER 5% (confirmatory):",
      STEP[STEP.p_stepdown < 0.05].branch.tolist() or "NONE")
print("""
Reading: a step-down p of 0.3 is not evidence of no effect. It says the discovery sample,
after paying for every branch examined, cannot *establish* the branch on its own. Whether a
branch deserves one pre-registered holdout test is a different question with a different bar --
see section 9.""")''')

# --------------------------------------------------------------------------- robustness
md(r"""## 7. Robustness the correction asked for by name

* **Period split** — the program's established finding is a regime break near 2026-04-06.
  A branch that only works before the break is a historical artifact, not a live candidate.
* **Horizon** — 2h / 4h / 8h; the 4h primary is frozen, the others are shape checks.
* **Overlap and clustering** — anchored episodes bound each entry, but a 4h horizon can still
  run into the next episode of the same coin, and simultaneous entries across coins were the
  inflation channel caught in audit v2. Both are measured, not assumed away.
* **Skew** — the review flagged +6.4bps mean against a −50bps median. Mean, median and hit
  rate are reported together for every branch.""")

code(r'''rows = []
for k, v in BRANCHES.items():
    pre  = v[v.ts < SPLIT]; post = v[v.ts >= SPLIT]
    r = {"branch": k}
    for lbl, sub in (("pre-Apr26", pre), ("Apr-Jul26", post)):
        vv, rr = daily_series(sub)
        s = stat_ci(vv)
        r[f"{lbl}_daily"] = s["mean"]; r[f"{lbl}_p"] = s["p_gt0"]; r[f"{lbl}_n"] = len(rr)
    for h in HORIZONS:
        r[f"h{h}"] = stat_ci(daily_series(v, h)[0])["mean"]
    rows.append(r)
SPLITTAB = pd.DataFrame(rows)
print(SPLITTAB.round(2).to_string(index=False))
SPLITTAB.to_csv(f"{OUT_DIR}/branch_periods.csv", index=False)''')

code(r'''# ---- overlap / clustering / skew diagnostics on the baseline and top branches ----
def diagnostics(name, v, h=H_PRIMARY):
    d = v.sort_values("ts")
    ov = d.sort_values(["coin","ts"]).groupby("coin").ts.diff().dt.total_seconds().div(60)
    same_ts = d.groupby("ts").size()
    r = (d["dir"]*d[f"adj{h}"]).dropna()
    bycoin = (d["dir"]*d[f"adj{h}"]).groupby(d.coin).sum()
    top_coin = float(bycoin.max()/bycoin.sum()) if len(bycoin) and bycoin.sum() != 0 else np.nan
    return dict(branch=name, n=len(d), top_coin_share=top_coin, n_coins=d.coin.nunique(),
                pct_overlapping=float((ov < h).mean()),
                max_same_ts=int(same_ts.max()) if len(same_ts) else 0,
                pct_in_multi_ts=float((same_ts[same_ts > 1].sum())/max(len(d),1)),
                mean_bps=r.mean()*1e4, median_bps=r.median()*1e4, hit=float((r>0).mean()),
                p05=r.quantile(.05)*1e4, p95=r.quantile(.95)*1e4)

DIAG = pd.DataFrame([diagnostics(k, v) for k, v in BRANCHES.items()])
print(DIAG.round(3).to_string(index=False))
DIAG.to_csv(f"{OUT_DIR}/branch_diagnostics.csv", index=False)''')

code(r'''# ---- de-overlapped variant (definition in section 3) ----
DEOV = pd.DataFrame([summarize(k + " [de-overlapped]", deoverlap(v)) for k, v in BRANCHES.items()])
print(DEOV[["branch","n_trades","daily_gross","lo","hi","p_gt0","per_trade_gross","daily_net"]]
      .round(2).to_string(index=False))
DEOV.to_csv(f"{OUT_DIR}/branch_deoverlapped.csv", index=False)''')

# --------------------------------------------------------------------------- control
md(r"""## 8. Control: does the wallet-resolved rebuild change the *baseline* itself?

The ladder's row-A features came from `attrib_5m`. B0 here is the same rule computed from
wallet-level rows. If the two disagree materially, the ladder's row A was measuring something
other than what it said — worth knowing before interpreting any branch.""")

code(r'''old = None
try:
    old = pd.read_parquet(f"{BASE}/data/spec_events.parquet")
except Exception as e:
    print("spec_events.parquet unavailable:", e)
if old is not None:
    o = old.copy(); o["event_id"] = o.coin + "|" + o.ts.dt.strftime("%Y%m%dT%H%M")
    cmp = E.merge(o[["event_id","smart_share","smart_imb","dumb_share","n_top_buy"]],
                  on="event_id", suffixes=("_new","_old"), how="inner")
    print(f"overlapping events: {len(cmp):,}")
    for c in ("smart_share","smart_imb","dumb_share"):
        print(f"  {c:12s} corr={cmp[f'{c}_new'].corr(cmp[f'{c}_old']):.4f}  "
              f"mean new {cmp[f'{c}_new'].mean():.4f} vs old {cmp[f'{c}_old'].mean():.4f}")
    print(f"  n_top_buy (summed, ladder) vs unique smart buyers: "
          f"mean {cmp.n_top_buy.mean():.2f} vs {cmp.n_smart_buyers.mean():.2f}, "
          f"corr={cmp.n_top_buy.corr(cmp.n_smart_buyers):.3f}, "
          f"inflation factor {cmp.n_top_buy.sum()/max(cmp.n_smart_buyers.sum(),1):.2f}x")''')

# --------------------------------------------------------------------------- verdict
md(r"""## 9. Verdict and disposition

Two different questions, two different bars. Conflating them is how a discovery sample ends up
either overselling noise or discarding its one coherent lead.

**Bar 1 — is a branch established *on this sample*?** Requires step-down FWER 5% on the paired
difference, a positive net daily return whose CI excludes zero, and no regime confinement.
Nothing can realistically clear this: it is the bar for calling something proven without a
holdout, and the whole point of holding out post-2026-07-22 data is not to need it.

**Bar 2 — does a branch deserve the one pre-registered holdout test?** A holdout can be spent
exactly once, so this bar is about coherence, not significance:

* the paired difference vs baseline is positive with a CI excluding zero *before* multiplicity;
* the sign is stable across horizons (30m → 8h) and across the April regime break;
* it is not carried by one coin or a handful of days;
* it survives de-overlapping;
* it states an economic mechanism that could plausibly generalize, rather than a filter that
  happens to select good trades.

A branch that fails Bar 1 but passes Bar 2 is a **candidate**, and the honest disposition is one
pre-registered test — not "no successor".

**Selectivity theatre** (per-trade mean up, daily estimand down) remains a disqualifier under
either bar, and the daily-estimand number is a *comparison* statistic, not a strategy return:
it equal-weights a day with ten winning entries against a day with one loser. A candidate's
economics have to be settled by an actual portfolio simulation (notebook 05), not by this
column.""")

code(r'''cand = (STEP.merge(RES, on="branch").merge(PAIR[["branch","d_daily","p_better"]], on="branch")
        .merge(SPLITTAB[["branch","pre-Apr26_daily","Apr-Jul26_daily","Apr-Jul26_p"]], on="branch"))
cand["pass_fwer"] = cand.p_stepdown < 0.05
cand["pass_net"]  = (cand.daily_net > 0) & (cand.net_lo > 0)
cand["pass_regime"] = cand["Apr-Jul26_daily"] > 0
cand["ESTABLISHED"] = cand.pass_fwer & cand.pass_net & cand.pass_regime      # Bar 1
# Bar 2: coherence, pre-multiplicity -- does this deserve the single holdout test?
dia = DIAG.set_index("branch"); dev = DEOV.assign(b=DEOV.branch.str.replace(r" \[de-overlapped\]", "", regex=True)).set_index("b")
spl = SPLITTAB.set_index("branch")
cand["b2_paired_ci"]  = cand.branch.map(PAIR.set_index("branch").d_lo) > 0
cand["b2_horizons"]   = cand.branch.map(lambda b: all(spl.loc[b, f"h{h}"] > 0 for h in HORIZONS))
cand["b2_regimes"]    = cand.pass_regime & (cand["pre-Apr26_daily"] > 0)
cand["b2_breadth"]    = cand.branch.map(lambda b: (dia.loc[b, "top_coin_share"] < 0.5) & (dia.loc[b, "n_coins"] >= 50))
cand["b2_deoverlap"]  = cand.branch.map(lambda b: dev.loc[b, "daily_gross"] > 0)
cand["b2_executable"] = cand.branch.map(EXECUTABLE)
cand["CANDIDATE"] = (cand.b2_paired_ci & cand.b2_horizons & cand.b2_regimes
                     & cand.b2_breadth & cand.b2_deoverlap & cand.b2_executable)
b0_pt = RES[RES.branch.str.startswith("B0")].iloc[0].per_trade_gross
cand["selectivity_theatre"] = (cand.per_trade_gross > b0_pt) & (cand.d_daily < 0)
cols = ["branch","t_paired","p_stepdown","daily_gross","daily_net","d_daily","p_better",
        "per_trade_gross","n_trades","pre-Apr26_daily","Apr-Jul26_daily","ESTABLISHED",
        "b2_paired_ci","b2_horizons","b2_regimes","b2_breadth","b2_deoverlap","b2_executable",
        "CANDIDATE","selectivity_theatre"]
V = cand[cols].sort_values(["CANDIDATE","p_better"], ascending=False)
print(V.round(3).to_string(index=False))
V.to_csv(f"{OUT_DIR}/verdict.csv", index=False)

established = V[V.ESTABLISHED].branch.tolist()
winners = V[V.CANDIDATE].branch.tolist()
theatre = V[V.selectivity_theatre].branch.tolist()
b0 = RES[RES.branch.str.startswith("B0")].iloc[0]
print(f"""
================================ VERDICT ================================
baseline B0: daily {b0.daily_gross:+.2f}bps gross / {b0.daily_net:+.2f}bps net
             [{b0.lo:+.2f},{b0.hi:+.2f}] P(>0)={b0.p_gt0:.2f}
             {b0.n_trades} trades, per-trade {b0.per_trade_gross:+.1f}bps gross,
             median {b0.median_bps:+.1f}bps, hit {b0.hit:.0%}

Bar 1 -- established on the discovery sample : {established or 'NONE (expected; that is what the holdout is for)'}
Bar 2 -- deserves the one pre-registered test : {winners or 'NONE'}
selectivity theatre (per-trade up, daily down): {theatre or 'none'}

Hypotheses from the correction note, now actually tested:
  buy-skill joined to flow      -> B1 / B1b
  true initiation (position path)-> B2 / B2b
  unique smart consensus        -> B3 / B3b
  crowd absence (matched pop.)  -> B5   (B5b shows what the mismatched normalizer did)
  statefulness beyond first-signal -> B6 / B6b / B6c / B6d

A Bar-2 candidate is NOT a validated strategy. It goes to notebook 05 for the routing
formulation, the score placebo and a stateful portfolio simulation before anything is frozen.
=========================================================================""")''')

nb["cells"] = C
nbf.write(nb, "04_event_wallet_branch_tests.ipynb")
print(f"wrote 04_event_wallet_branch_tests.ipynb with {len(C)} cells")
