"""Phase-1 verification + re-computation for report v4. Light (no new bar pricing): uses cohort_K_entries + entry_features.
Produces out/v4.json for figures and prints an audit summary. Calendar-day cluster bootstrap throughout."""
import json; import numpy as np, polars as pl
RNG = np.random.default_rng(0); NB = 2000; BP = 1e4
df = pl.read_parquet("out/cohort_K_entries.parquet").with_columns(day=(pl.col("b_ts")//86_400_000),
        month=pl.from_epoch(pl.col("b_ts"), time_unit="ms").dt.strftime("%Y-%m"))
ef = pl.read_parquet("out/entry_features.parquet").with_columns(day=(pl.col("b_ts")//86_400_000))
COINS = ["BTC", "ETH", "SOL", "HYPE"]; OUT = {}

def daycluster_mean(vals, days, w=None):
    """day-cluster bootstrap of a (weighted) mean; resample unique calendar days with replacement."""
    ud = np.unique(days); idx = {int(d): i for i, d in enumerate(ud)}
    di = np.array([idx[int(d)] for d in days])
    # per-day sums for fast bootstrap
    if w is None: w = np.ones(len(vals))
    sw = np.zeros(len(ud)); swv = np.zeros(len(ud))
    np.add.at(sw, di, w); np.add.at(swv, di, w*vals)
    pt = swv.sum()/sw.sum()
    bs = np.empty(NB)
    for b in range(NB):
        s = RNG.integers(0, len(ud), len(ud)); bs[b] = swv[s].sum()/sw[s].sum() if sw[s].sum() > 0 else np.nan
    return float(pt), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), float(np.mean(bs <= 0))

# ---- (10) effective sample info ----
eff = {"entries": df.height, "calendar_days": df["day"].n_unique(), "active_wallets": df["wallet"].n_unique(),
       "wallet_days": df.select("wallet", "day").unique().height,
       "wallet_coin_days": df.select("wallet", "coin", "day").unique().height}
for c in COINS:
    s = df.filter(pl.col("coin") == c); eff[f"{c}_days"] = s["day"].n_unique()
OUT["effective_sample"] = eff
print("EFFECTIVE SAMPLE:", eff)

# ---- (2) long vs short, raw & neutralized, by coin x horizon + counts + CI ----
ls = {}
for c in COINS:
    ls[c] = {}
    for sgn, lab in [(1, "long"), (-1, "short")]:
        s = df.filter((pl.col("coin") == c) & (pl.col("dir") == sgn))
        ls[c][lab] = {"n": s.height}
        for h in ["1h", "8h", "24h"]:
            for kind in ["raw", "neut"]:
                v = s[f"{kind}_{h}"].to_numpy(); d = s["day"].to_numpy(); ok = np.isfinite(v)
                pt, lo, hi, _ = daycluster_mean(v[ok], d[ok])
                ls[c][lab][f"{kind}_{h}"] = [round(pt, 2), round(lo, 1), round(hi, 1)]
OUT["long_short"] = ls
print("\nLONG/SHORT 24h (raw | neut):")
for c in COINS:
    print(f"  {c}: long raw {ls[c]['long']['raw_24h'][0]:+.1f} neut {ls[c]['long']['neut_24h'][0]:+.1f} (n={ls[c]['long']['n']}) | "
          f"short raw {ls[c]['short']['raw_24h'][0]:+.1f} neut {ls[c]['short']['neut_24h'][0]:+.1f} (n={ls[c]['short']['n']})")

# ---- (3) conditional: fixed-quantile bins + counts + day-cluster CI + TRAIN linear slope ----
cond = {}
E = ef.select("coin", "split", "day", "trail_8h", "raw_8h").drop_nulls().filter(
    pl.col("trail_8h").is_finite() & pl.col("raw_8h").is_finite())
qedges = np.quantile(E["trail_8h"].to_numpy(), np.linspace(0.05, 0.95, 10))  # fixed pooled quantile knots
for c in COINS:
    s = E.filter(pl.col("coin") == c); t = s["trail_8h"].to_numpy(); y = s["raw_8h"].to_numpy(); d = s["day"].to_numpy()
    b = np.digitize(t, qedges); bins = []
    for k in range(len(qedges)+1):
        m = b == k
        if m.sum() < 200: bins.append(None); continue
        pt, lo, hi, _ = daycluster_mean(y[m], d[m])
        bins.append([float(np.median(t[m])), round(pt, 1), round(lo, 1), round(hi, 1), int(m.sum())])
    # TRAIN-only linear slope of subsequent markout on signed pre-entry move
    tr = s.filter(pl.col("split") == "train"); tt = tr["trail_8h"].to_numpy(); yy = tr["raw_8h"].to_numpy(); dd = tr["day"].to_numpy()
    slope = np.polyfit(tt, yy, 1)[0]
    ud = np.unique(dd); idx = {int(x): i for i, x in enumerate(ud)}; dic = np.array([idx[int(x)] for x in dd])
    sl_bs = []
    for _ in range(1000):
        ssd = RNG.integers(0, len(ud), len(ud)); mask = np.isin(dic, ssd)
        if mask.sum() > 100: sl_bs.append(np.polyfit(tt[mask], yy[mask], 1)[0])
    sl_bs = np.array(sl_bs)
    cond[c] = {"bins": bins, "train_slope_per_bp": round(float(slope), 4),
               "slope_ci": [round(float(np.percentile(sl_bs, 2.5)), 4), round(float(np.percentile(sl_bs, 97.5)), 4)],
               "slope_p_ge0": round(float(np.mean(sl_bs >= 0)), 4)}
OUT["conditional"] = cond
print("\nCONDITIONAL train slope (subsequent 8h markout per bp of signed pre-entry move):")
for c in COINS: print(f"  {c}: slope {cond[c]['train_slope_per_bp']:+.4f} CI {cond[c]['slope_ci']} p(>=0)={cond[c]['slope_p_ge0']}")

# ---- (4) size within coin x month: equal & notional weighted, counts, CI, 1h & 8h ----
size = {}
dd = df.with_columns(q=pl.col("notl").rank().over(["coin", "month"]) / pl.len().over(["coin", "month"]))
dd = dd.with_columns(quint=(pl.col("q")*5).ceil().clip(1, 5))
for h in ["1h", "8h"]:
    size[h] = {}
    for qi in range(1, 6):
        s = dd.filter(pl.col("quint") == qi); v = s[f"raw_{h}"].to_numpy(); n = s["notl"].to_numpy(); day = s["day"].to_numpy()
        ok = np.isfinite(v)
        ew = daycluster_mean(v[ok], day[ok]); nw = daycluster_mean(v[ok], day[ok], w=n[ok])
        size[h][qi] = {"n": int(ok.sum()), "equal": [round(ew[0], 2), round(ew[1], 1), round(ew[2], 1)],
                       "notl": [round(nw[0], 2), round(nw[1], 1), round(nw[2], 1)]}
OUT["size"] = size
print("\nSIZE 8h equal-weighted by within-coin-month quintile:", [size["8h"][q]["equal"][0] for q in range(1, 6)])

# ---- (5) recurrence permutation null (neut_8h, 11 months) ----
wmd = df.group_by("wallet", "month", "day").agg(m=pl.col("neut_8h").mean())
wm = wmd.group_by("wallet", "month").agg(mm=pl.col("m").mean(), nd=pl.len()).filter(pl.col("nd") >= 8)
months = sorted(wm["month"].unique().to_list())
month_wallets = {}; top_obs = {}
for mo in months:
    sub = wm.filter(pl.col("month") == mo); w = sub["wallet"].to_numpy(); v = sub["mm"].to_numpy()
    k = max(1, int(round(0.10*len(w)))); topw = set(w[np.argsort(-v)[:k]])
    month_wallets[mo] = (w, k); top_obs[mo] = topw
from collections import Counter
cnt = Counter()
for mo in months:
    for w in top_obs[mo]: cnt[w] += 1
obs = {K: sum(1 for v in cnt.values() if v >= K) for K in [2, 3, 4]}
perm = {2: [], 3: [], 4: []}
for _ in range(NB):
    pc = Counter()
    for mo in months:
        w, k = month_wallets[mo]; sel = RNG.choice(len(w), k, replace=False)
        for i in sel: pc[w[i]] += 1
    for K in [2, 3, 4]: perm[K].append(sum(1 for v in pc.values() if v >= K))
rec = {K: {"observed": obs[K], "perm_mean": round(float(np.mean(perm[K])), 1),
           "perm_p": round(float(np.mean(np.array(perm[K]) >= obs[K])), 4)} for K in [2, 3, 4]}
OUT["recurrence_perm"] = rec
print("\nRECURRENCE permutation null (neut_8h):", rec)

# ---- (6) fixed-121 validation full inference ----
frozen = set(l.strip() for l in open("out/cohort_M_frozen.txt") if l.strip() and not l.startswith("#"))
te = df.filter(pl.col("split") == "test").with_columns(coh=pl.col("wallet").is_in(list(frozen)))
wcd = te.group_by("wallet", "coin", "day", "coh").agg(m=pl.col("neut_8h").mean())
wcd = wcd.filter(pl.col("m").is_finite())
coh = wcd.filter(pl.col("coh")); fld = wcd.filter(~pl.col("coh"))
active = coh["wallet"].n_unique()
# day-cluster bootstrap of cohort-minus-field (wallet-coin-day weighted)
alldays = np.sort(te["day"].unique().to_numpy())
cv = coh["m"].to_numpy(); cd = coh["day"].to_numpy(); fv = fld["m"].to_numpy(); fd = fld["day"].to_numpy()
def diff_boot():
    uc = {int(x): i for i, x in enumerate(alldays)}
    ci_ = np.array([uc[int(x)] for x in cd]); fi_ = np.array([uc[int(x)] for x in fd])
    csum = np.zeros(len(alldays)); ccnt = np.zeros(len(alldays)); fsum = np.zeros(len(alldays)); fcnt = np.zeros(len(alldays))
    np.add.at(csum, ci_, cv); np.add.at(ccnt, ci_, 1); np.add.at(fsum, fi_, fv); np.add.at(fcnt, fi_, 1)
    pt = csum.sum()/ccnt.sum() - fsum.sum()/fcnt.sum(); bs = np.empty(NB)
    for b in range(NB):
        s = RNG.integers(0, len(alldays), len(alldays))
        cc = ccnt[s].sum(); ff = fcnt[s].sum()
        bs[b] = (csum[s].sum()/cc - fsum[s].sum()/ff) if cc > 0 and ff > 0 else np.nan
    return float(pt), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), float(np.mean(bs <= 0))
dpt, dlo, dhi, dp = diff_boot()
# wallet vs fade (alpha) at cohort validation entries, day-capped: fade = -sign(trail_8h)*raw_8h
efc = ef.filter((pl.col("split") == "test") & pl.col("wallet").is_in(list(frozen))).select("coin", "day", "trail_8h", "raw_8h").drop_nulls().filter(pl.col("trail_8h").is_finite() & pl.col("raw_8h").is_finite())
alpha = efc["raw_8h"].to_numpy() - (-np.sign(efc["trail_8h"].to_numpy())*efc["raw_8h"].to_numpy())
apt, alo, ahi, ap = daycluster_mean(alpha, efc["day"].to_numpy())
concoin = {c: round(float(coh.filter(pl.col("coin") == c)["m"].mean() or np.nan), 1) for c in COINS}
OUT["fixed121"] = {"selected": len(frozen), "active_validation": active, "attrition": len(frozen)-active,
    "wallet_coin_days": coh.height, "calendar_days": int(len(alldays)),
    "diff_vs_field_bp": round(dpt, 2), "ci": [round(dlo, 1), round(dhi, 1)], "p": round(dp, 3),
    "cost_adj_bp": round(dpt-7.0, 2), "alpha_vs_fade_bp": round(apt, 2), "alpha_ci": [round(alo, 1), round(ahi, 1)], "alpha_p": round(ap, 3),
    "by_coin": concoin}
print("\nFIXED-121:", OUT["fixed121"])

# ---- (11) rolling decile-by-decile next-month markout (4h & 8h) + field + month-by-month top-minus-field ----
roll = {}
for hz, col in [("4h", "neut_4h"), ("8h", "neut_8h")]:
    wmd = df.group_by("wallet", "month", "day").agg(m=pl.col(col).mean())
    wm = wmd.group_by("wallet", "month").agg(mm=pl.col("m").mean(), nd=pl.len()).filter(pl.col("nd") >= 8)
    dec_series = {k: [] for k in range(1, 11)}; field_series = []; topdiff = []
    for i in range(len(months)-1):
        a = wm.filter(pl.col("month") == months[i]).with_columns(dec=(pl.col("mm").rank()/pl.len()*10).ceil().clip(1, 10)).select("wallet", "dec")
        b = wm.filter(pl.col("month") == months[i+1]).select("wallet", nxt=pl.col("mm"))
        j = a.join(b, on="wallet", how="inner")
        if j.height < 30: continue
        fld_m = j["nxt"].mean(); field_series.append(fld_m)
        for k in range(1, 11):
            v = j.filter(pl.col("dec") == k)["nxt"]
            if v.len(): dec_series[k].append(float(v.mean()))
        top = j.filter(pl.col("dec") == 10)["nxt"].mean()
        topdiff.append((months[i+1], round(float(top-fld_m), 2)))
    def mci(a):
        a = np.array(a); bs = np.array([np.mean(a[RNG.integers(0, len(a), len(a))]) for _ in range(2000)])
        return [round(float(a.mean()), 2), round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]
    roll[hz] = {"deciles": {k: mci(dec_series[k]) for k in range(1, 11) if dec_series[k]},
                "field": mci(field_series), "topdiff_by_month": topdiff}
OUT["rolling_decile"] = roll
print("\nROLLING DECILE 8h (decile: mean next-month):", {k: roll["8h"]["deciles"][k][0] for k in roll["8h"]["deciles"]})

json.dump(OUT, open("out/v4.json", "w"), indent=0)
print("\nsaved out/v4.json")
