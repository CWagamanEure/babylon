"""Phase-1 v5 recomputation. Light. Fixes: fixed-121 estimands A/B/C x 3 weightings; recurrence train-only vs full;
pooled slope with coin+month FE; 5-day block CI for 24h; canonical static rho; direction-aligned behavioral medians.
Writes out/v5.json."""
import json; import numpy as np, polars as pl
RNG = np.random.default_rng(0); NB = 2000
COINS = ["BTC", "ETH", "SOL", "HYPE"]; COST = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0}
df = pl.read_parquet("out/cohort_K_entries.parquet").with_columns(day=(pl.col("b_ts")//86_400_000),
        month=pl.from_epoch(pl.col("b_ts"), time_unit="ms").dt.strftime("%Y-%m"))
ef = pl.read_parquet("out/entry_features.parquet")
frozen = [l.strip() for l in open("out/cohort_M_frozen.txt") if l.strip() and not l.startswith("#")]
OUT = {"cost_table": COST}

# ============ FIXED-121: estimands A (absolute), B (minus non-cohort field), C (minus matched fade) x 3 weightings ============
base = (df.filter(pl.col("split") == "test").select("wallet", "coin", "b_ts", "day", "month", "dir", "raw_8h", "neut_8h")
          .join(ef.select("wallet", "coin", "b_ts", "trail_8h"), on=["wallet", "coin", "b_ts"], how="left"))
base = base.with_columns(coh=pl.col("wallet").is_in(frozen), cost=pl.col("coin").replace_strict(COST, default=10.0))
base = base.with_columns(net8=pl.col("raw_8h")-pl.col("cost"), fade=-pl.col("trail_8h").sign()*pl.col("raw_8h"))
base = base.filter(pl.col("raw_8h").is_finite() & pl.col("neut_8h").is_finite())

def cells(frame, valcol, scheme):
    """return per-cluster (day or wallet) sum & count of cell-means under the weighting scheme."""
    if scheme == "wcd":  keys = ["wallet", "coin", "day"]; clus = "day"
    elif scheme == "wd": keys = ["wallet", "day"];         clus = "day"
    else:                keys = ["wallet"];                clus = "wallet"
    cell = frame.group_by(keys).agg(cv=pl.col(valcol).mean(), cl=pl.col(clus).first())
    g = cell.group_by("cl").agg(csum=pl.col("cv").sum(), ccnt=pl.len())
    return g["cl"].to_numpy(), g["csum"].to_numpy(), g["ccnt"].to_numpy()

def pt(csum, ccnt): return csum.sum()/ccnt.sum()

def boot_single(csum, ccnt):
    n = len(csum); bs = np.empty(NB)
    for b in range(NB):
        s = RNG.integers(0, n, n); cc = ccnt[s].sum(); bs[b] = csum[s].sum()/cc if cc > 0 else np.nan
    return float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), float(np.mean(bs <= 0))

def boot_diff(cl_c, cs_c, cn_c, cl_f, cs_f, cn_f):
    U = np.union1d(cl_c, cl_f); ic = {x: i for i, x in enumerate(U)}
    sc = np.zeros(len(U)); nc = np.zeros(len(U)); sf = np.zeros(len(U)); nf = np.zeros(len(U))
    for x, ss, nn in zip(cl_c, cs_c, cn_c): sc[ic[x]] += ss; nc[ic[x]] += nn
    for x, ss, nn in zip(cl_f, cs_f, cn_f): sf[ic[x]] += ss; nf[ic[x]] += nn
    d = pt(cs_c, cn_c) - pt(cs_f, cn_f); bs = np.empty(NB)
    for b in range(NB):
        s = RNG.integers(0, len(U), len(U)); a1 = nc[s].sum(); a2 = nf[s].sum()
        bs[b] = (sc[s].sum()/a1 - sf[s].sum()/a2) if a1 > 0 and a2 > 0 else np.nan
    return float(d), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), float(np.mean(bs <= 0))

coh = base.filter(pl.col("coh")); fld = base.filter(~pl.col("coh"))
f121 = {}
SCHEMES = [("wd", "wallet-day (primary)"), ("ew", "equal-wallet"), ("wcd", "wallet-coin-day (sensitivity)")]
for sch, name in SCHEMES:
    # counts
    d = {"scheme": name, "selected": len(frozen), "active": coh["wallet"].n_unique(),
         "wallet_days": coh.select("wallet", "day").unique().height,
         "wallet_coin_days": coh.select("wallet", "coin", "day").unique().height,
         "calendar_days": coh["day"].n_unique()}
    # A absolute (gross + cost-adjusted)
    clg, csg, cng = cells(coh, "raw_8h", sch); d["A_gross"] = round(pt(csg, cng), 2)
    cli, csi, cni = cells(coh, "net8", sch);   d["A_costadj"] = round(pt(csi, cni), 2)
    # B cohort - non-cohort field (neut_8h, no cost)
    clc, csc, cnc = cells(coh, "neut_8h", sch); clf, csf, cnf = cells(fld, "neut_8h", sch)
    Bd, Blo, Bhi, Bp = boot_diff(clc, csc, cnc, clf, csf, cnf)
    d["B_minus_field"] = [round(Bd, 2), round(Blo, 1), round(Bhi, 1), round(Bp, 3)]
    # C cohort - matched fade (raw - fade, single group)
    clx, csx, cnx = cells(coh.filter(pl.col("trail_8h").is_finite()), "raw_8h", sch)
    clz, csz, cnz = cells(coh.filter(pl.col("trail_8h").is_finite()), "fade", sch)
    # C = weighted mean(raw) - weighted mean(fade) over same cohort cells
    Cval = coh.filter(pl.col("trail_8h").is_finite()).with_columns(diff=pl.col("raw_8h")-pl.col("fade"))
    clcd, cscd, cncd = cells(Cval, "diff", sch); Clo, Chi, Cp2 = boot_single(cscd, cncd)
    d["C_minus_fade"] = [round(pt(cscd, cncd), 2), round(Clo, 1), round(Chi, 1), round(1-Cp2 if pt(cscd,cncd)<0 else Cp2, 3)]
    f121[sch] = d

# concentration (wallet-day scheme, B on neut_8h): largest wallet/coin/month contribution + drop-largest-wallet
cw = coh.group_by("wallet").agg(m=pl.col("neut_8h").mean(), n=pl.len()).sort("m", descending=True)
topw = cw["wallet"][0]
clc2, csc2, cnc2 = cells(coh.filter(pl.col("wallet") != topw), "neut_8h", "wd"); clf2, csf2, cnf2 = cells(fld, "neut_8h", "wd")
Bd2, _, _, _ = boot_diff(clc2, csc2, cnc2, clf2, csf2, cnf2)
bycoin = {c: round(float(coh.filter(pl.col("coin") == c)["neut_8h"].mean() or np.nan), 1) for c in COINS}
bymonth = coh.group_by("month").agg(m=pl.col("neut_8h").mean()).sort("month")
OUT["fixed121"] = {"schemes": f121, "conc_by_coin": bycoin,
    "conc_drop_top_wallet_B": round(Bd2, 2), "top_wallet_mean": round(float(cw["m"][0]), 1),
    "by_month": {r["month"]: round(r["m"], 1) for r in bymonth.iter_rows(named=True)}}
print("FIXED-121 B (cohort - non-cohort field, neut_8h):")
for s, _ in SCHEMES: print(f"  {f121[s]['scheme']:<26} A_gross {f121[s]['A_gross']:+.1f} A_costadj {f121[s]['A_costadj']:+.1f} | "
    f"B {f121[s]['B_minus_field'][0]:+.1f} {f121[s]['B_minus_field'][:3][1:]} p={f121[s]['B_minus_field'][3]} | "
    f"C_fade {f121[s]['C_minus_fade'][0]:+.1f} p={f121[s]['C_minus_fade'][3]}")
print(f"  drop-top-wallet B(wd) = {Bd2:+.1f} (top wallet mean {cw['m'][0]:+.1f})")

# ============ RECURRENCE: train-only (6mo) vs full (11mo) permutation ============
from collections import Counter
def recurrence(frame, label):
    wmd = frame.group_by("wallet", "month", "day").agg(m=pl.col("neut_8h").mean())
    wm = wmd.group_by("wallet", "month").agg(mm=pl.col("m").mean(), nd=pl.len()).filter(pl.col("nd") >= 8)
    months = sorted(wm["month"].unique().to_list()); mw = {}; top = {}
    for mo in months:
        sub = wm.filter(pl.col("month") == mo); w = sub["wallet"].to_numpy(); v = sub["mm"].to_numpy()
        k = max(1, int(round(0.10*len(w)))); mw[mo] = (w, k); top[mo] = set(w[np.argsort(-v)[:k]])
    cnt = Counter()
    for mo in months:
        for w in top[mo]: cnt[w] += 1
    obs = {K: sum(1 for v in cnt.values() if v >= K) for K in [2, 3, 4]}
    perm = {2: [], 3: [], 4: []}
    for _ in range(NB):
        pc = Counter()
        for mo in months:
            w, k = mw[mo]; sel = RNG.choice(len(w), k, replace=False)
            for i in sel: pc[w[i]] += 1
        for K in [2, 3, 4]: perm[K].append(sum(1 for v in pc.values() if v >= K))
    return {"n_months": len(months), **{f"ge{K}": {"obs": obs[K], "null": round(float(np.mean(perm[K])), 1),
            "p": round(float(np.mean(np.array(perm[K]) >= obs[K])), 4)} for K in [2, 3, 4]}}
OUT["recurrence"] = {"train_only": recurrence(df.filter(pl.col("split") == "train"), "train"),
                     "full_exploratory": recurrence(df, "full")}
print("\nRECURRENCE train-only:", OUT["recurrence"]["train_only"])
print("RECURRENCE full (exploratory):", OUT["recurrence"]["full_exploratory"])

# ============ POOLED conditional slope: raw_8h ~ trail_8h + coin FE + month FE + vol ============
P = (df.filter(pl.col("split") == "train").select("wallet", "coin", "b_ts", "month", "day", "raw_8h")
       .join(ef.select("wallet", "coin", "b_ts", "trail_8h", "vol2h"), on=["wallet", "coin", "b_ts"], how="left"))
P = P.filter(pl.col("raw_8h").is_finite() & pl.col("trail_8h").is_finite() & pl.col("vol2h").is_finite())
coins_d = P.select("coin").to_dummies(); months_d = P.select("month").to_dummies()
X = np.column_stack([P["trail_8h"].to_numpy(), P["vol2h"].to_numpy(),
                     coins_d.to_numpy()[:, 1:], months_d.to_numpy()[:, 1:], np.ones(P.height)])
y = P["raw_8h"].to_numpy(); day = P["day"].to_numpy()
beta = np.linalg.lstsq(X, y, rcond=None)[0]; slope = beta[0]
ud = np.unique(day); idx = {int(x): i for i, x in enumerate(ud)}; di = np.array([idx[int(x)] for x in day])
sl_bs = []
for _ in range(600):
    s = RNG.integers(0, len(ud), len(ud)); mask = np.isin(di, s)
    if mask.sum() > 1000:
        b = np.linalg.lstsq(X[mask], y[mask], rcond=None)[0]; sl_bs.append(b[0])
sl_bs = np.array(sl_bs)
OUT["pooled_slope"] = {"slope_per_bp": round(float(slope), 4),
    "ci95_2sided": [round(float(np.percentile(sl_bs, 2.5)), 4), round(float(np.percentile(sl_bs, 97.5)), 4)],
    "p_1sided_ge0": round(float(np.mean(sl_bs >= 0)), 4), "n": int(P.height), "controls": "coin FE + month FE + vol2h; day-cluster bootstrap"}
print("\nPOOLED slope:", OUT["pooled_slope"])

# ============ 24h: day-cluster vs 5-day non-overlapping moving-block ============
def block24(coin):
    s = df if coin == "ALL" else df.filter(pl.col("coin") == coin)
    v = s["raw_24h"].to_numpy(); dd = s["day"].to_numpy(); ok = np.isfinite(v); v, dd = v[ok], dd[ok]
    ud = np.sort(np.unique(dd)); di = {int(x): i for i, x in enumerate(ud)}
    dsum = np.zeros(len(ud)); dcnt = np.zeros(len(ud)); dix = np.array([di[int(x)] for x in dd])
    np.add.at(dsum, dix, v); np.add.at(dcnt, dix, 1.0); pt0 = dsum.sum()/dcnt.sum()
    # day-cluster
    bs1 = np.array([dsum[si].sum()/dcnt[si].sum() for si in (RNG.integers(0, len(ud), len(ud)) for _ in range(NB))])
    # 5-day non-overlapping blocks
    nb = len(ud)//5; blocks = [np.arange(i*5, i*5+5) for i in range(nb)]
    bs2 = np.empty(NB)
    for b in range(NB):
        pick = [blocks[j] for j in RNG.integers(0, nb, nb)]; ii = np.concatenate(pick)
        bs2[b] = dsum[ii].sum()/dcnt[ii].sum()
    return {"pt": round(float(pt0), 2), "daycluster": [round(float(np.percentile(bs1, 2.5)), 1), round(float(np.percentile(bs1, 97.5)), 1)],
            "block5d": [round(float(np.percentile(bs2, 2.5)), 1), round(float(np.percentile(bs2, 97.5)), 1)]}
OUT["h24_blocks"] = {c: block24(c) for c in ["BTC", "ALL"]}
print("\n24h day-cluster vs 5-day block:", OUT["h24_blocks"])

# ============ canonical static rho (one definition, used everywhere) ============
w = (df.group_by("wallet").agg(
        tr=pl.col("raw_8h").filter(pl.col("split") == "train").mean(), ntr=pl.col("split").filter(pl.col("split") == "train").len(),
        va=pl.col("raw_8h").filter(pl.col("split") == "test").mean(), nva=pl.col("split").filter(pl.col("split") == "test").len())
     .filter((pl.col("ntr") >= 30) & (pl.col("nva") >= 20)))
tr = w["tr"].to_numpy(); va = w["va"].to_numpy(); ok = np.isfinite(tr) & np.isfinite(va)
OUT["static_rho"] = {"pearson": round(float(np.corrcoef(tr[ok], va[ok])[0, 1]), 3),
    "spearman": round(float(pl.DataFrame({"a": tr[ok], "b": va[ok]}).select(pl.corr("a", "b", method="spearman"))[0, 0]), 3),
    "n": int(ok.sum()), "def": ">=30 train & >=20 test entries; raw_8h wallet means"}
print("\nSTATIC rho:", OUT["static_rho"])

# ============ behavioral direction-aligned medians: recurring-121 vs rest-of-cohort ============
eb = ef.with_columns(coh=pl.col("wallet").is_in(frozen),
    stretch=pl.when(pl.col("dir") > 0).then(-pl.col("dist_hi")).otherwise(pl.col("dist_lo")))
def meds(frame):
    def m(col): a = frame[col].to_numpy(); a = a[np.isfinite(a)]; return round(float(np.median(a)), 1) if len(a) else None
    return {"n": frame.height, "signed_pre8h": m("trail_8h"), "abs_pre8h": m("atrail8"), "stretch": m("stretch"), "vol2h": m("vol2h")}
OUT["behavioral"] = {"recurring121": meds(eb.filter(pl.col("coh"))), "rest_cohort": meds(eb.filter(~pl.col("coh"))),
    "recurring_long": meds(eb.filter(pl.col("coh") & (pl.col("dir") > 0))), "recurring_short": meds(eb.filter(pl.col("coh") & (pl.col("dir") < 0)))}
print("\nBEHAVIORAL (dir-aligned) recurring vs rest:", OUT["behavioral"]["recurring121"], OUT["behavioral"]["rest_cohort"])

json.dump(OUT, open("out/v5.json", "w"), indent=0)
print("\nsaved out/v5.json")
