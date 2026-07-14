"""Phase 6-12 recomputation for report v6. Light. Fixed-cohort absolute/field/fade inference x 3 weightings;
time-block sensitivities (day-cluster, 7d & 5d OVERLAPPING moving-block, by-month, LOMO); coin decomposition
(per-coin, coin-balanced, leave-one-coin-out, ex-SOL); train-only-clean subset; rolling fold ICs; behavioral
equal-wallet. Writes out/v6.json."""
import json; import numpy as np, polars as pl
from scipy import stats as st
RNG = np.random.default_rng(0); NB = 2000
COINS = ["BTC", "ETH", "SOL", "HYPE"]; COST = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0}
df = pl.read_parquet("out/cohort_K_entries.parquet").with_columns(day=(pl.col("b_ts")//86_400_000),
        month=pl.from_epoch(pl.col("b_ts"), time_unit="ms").dt.strftime("%Y-%m"))
ef = pl.read_parquet("out/entry_features.parquet")
frozen = [l.strip() for l in open("out/cohort_M_frozen.txt") if l.strip() and not l.startswith("#")]
clean = set(l.strip() for l in open("out/cohort_K_trainonly.txt") if l.strip())
frozen_clean = [w for w in frozen if w in clean]
OUT = {"cost_table": COST, "n_frozen": len(frozen), "n_frozen_clean": len(frozen_clean)}

base = (df.filter(pl.col("split") == "test").select("wallet", "coin", "b_ts", "day", "month", "dir", "raw_8h", "neut_8h")
          .join(ef.select("wallet", "coin", "b_ts", "trail_8h"), on=["wallet", "coin", "b_ts"], how="left"))
base = base.with_columns(cost=pl.col("coin").replace_strict(COST, default=10.0)).with_columns(
    net8=pl.col("raw_8h")-pl.col("cost"), fade=-pl.col("trail_8h").sign()*pl.col("raw_8h")).filter(
    pl.col("raw_8h").is_finite() & pl.col("neut_8h").is_finite())

def daycells(frame, valcol, scheme):
    keys = {"wcd": ["wallet", "coin", "day"], "wd": ["wallet", "day"], "ew": ["wallet"]}[scheme]
    clus = "wallet" if scheme == "ew" else "day"
    cell = frame.group_by(keys).agg(cv=pl.col(valcol).mean(), cl=pl.col(clus).first())
    g = cell.group_by("cl").agg(csum=pl.col("cv").sum(), ccnt=pl.len())
    return g["cl"].to_numpy(), g["csum"].to_numpy().astype(float), g["ccnt"].to_numpy().astype(float)

def pt(cs, cn): return cs.sum()/cn.sum()
def resample_single(cs, cn, gen):
    out = np.empty(NB)
    for b in range(NB):
        idx = gen(); c = cn[idx].sum(); out[b] = cs[idx].sum()/c if c > 0 else np.nan
    return out
def ci_p(bs, side="gt"):
    lo, hi = np.nanpercentile(bs, [2.5, 97.5]); p = np.mean(bs <= 0) if side == "gt" else np.mean(bs >= 0)
    return round(float(lo), 1), round(float(hi), 1), round(float(p), 3)

def single_infer(frame, valcol, scheme):
    cl, cs, cn = daycells(frame, valcol, scheme); n = len(cl)
    bs = resample_single(cs, cn, lambda: RNG.integers(0, n, n))
    lo, hi, p = ci_p(bs); return [round(pt(cs, cn), 2), lo, hi, p]

def diff_infer(cohf, fldf, valcol, scheme, blockgen=None):
    clc, csc, cnc = daycells(cohf, valcol, scheme); clf, csf, cnf = daycells(fldf, valcol, scheme)
    U = np.union1d(clc, clf); ic = {x: i for i, x in enumerate(U)}
    sc = np.zeros(len(U)); nc = np.zeros(len(U)); sf = np.zeros(len(U)); nf = np.zeros(len(U))
    for x, s, nn in zip(clc, csc, cnc): sc[ic[x]] += s; nc[ic[x]] += nn
    for x, s, nn in zip(clf, csf, cnf): sf[ic[x]] += s; nf[ic[x]] += nn
    d = pt(csc, cnc) - pt(csf, cnf); gen = blockgen(U) if blockgen else (lambda: RNG.integers(0, len(U), len(U)))
    bs = np.empty(NB)
    for b in range(NB):
        s = gen(); a1 = nc[s].sum(); a2 = nf[s].sum()
        bs[b] = (sc[s].sum()/a1 - sf[s].sum()/a2) if a1 > 0 and a2 > 0 else np.nan
    lo, hi, p = ci_p(bs); return [round(float(d), 2), lo, hi, p]

# overlapping moving-block generator over ORDERED units (days); final block truncates to N
def moving_block(L):
    def mk(U):
        order = np.argsort(U); N = len(U); nb = int(np.ceil(N / L)); starts = np.arange(0, N - L + 1)
        def gen():
            picks = [order[s:s+L] for s in RNG.choice(starts, nb, replace=True)]
            return np.concatenate(picks)[:N]
        return gen
    return mk

SCHEMES = [("ew", "equal-wallet"), ("wd", "wallet-day"), ("wcd", "wallet-coin-day")]
def cohort_block(cohset):
    coh = base.filter(pl.col("wallet").is_in(list(cohset))); fld = base.filter(~pl.col("wallet").is_in(list(cohset)))
    r = {"active": coh["wallet"].n_unique(), "wallet_days": coh.select("wallet", "day").unique().height}
    for sch, nm in SCHEMES:
        r[sch] = {"A_gross": single_infer(coh, "raw_8h", sch), "A_costadj": single_infer(coh, "net8", sch),
                  "B_field": diff_infer(coh, fld, "neut_8h", sch),
                  "C_fade": single_infer(coh.filter(pl.col("trail_8h").is_finite()).with_columns(d=pl.col("raw_8h")-pl.col("fade")), "d", sch)}
    return r, coh, fld
OUT["fixed_full"], coh, fld = cohort_block(set(frozen))
OUT["fixed_clean"], _, _ = cohort_block(set(frozen_clean))
print("FIXED-121 full — A_costadj (gross) / B_field / C_fade by weighting:")
for s, nm in SCHEMES:
    a = OUT["fixed_full"][s]; print(f"  {nm:16s} Ag {a['A_gross'][0]:+.1f}{a['A_gross'][1:]} Ac {a['A_costadj'][0]:+.1f}{a['A_costadj'][1:]} B {a['B_field'][0]:+.1f}{a['B_field'][1:]} C {a['C_fade'][0]:+.1f}{a['C_fade'][1:]}")
print(f"clean-108 B (wd): {OUT['fixed_clean']['wd']['B_field']}")

# time-block sensitivities for B (wallet-day)
tb = {"day_cluster": diff_infer(coh, fld, "neut_8h", "wd"),
      "moving_block_7d": diff_infer(coh, fld, "neut_8h", "wd", blockgen=moving_block(7)),
      "moving_block_5d": diff_infer(coh, fld, "neut_8h", "wd", blockgen=moving_block(5))}
by_month = {}; months = sorted(base["month"].unique().to_list())
for mo in months:
    cm = coh.filter(pl.col("month") == mo); fm = fld.filter(pl.col("month") == mo)
    if cm.height > 20: by_month[mo] = diff_infer(cm, fm, "neut_8h", "wd")
lomo = {}
for mo in months:
    c2 = coh.filter(pl.col("month") != mo); f2 = fld.filter(pl.col("month") != mo)
    lomo[mo] = round(diff_infer(c2, f2, "neut_8h", "wd")[0], 2)
OUT["fixed_timeblocks"] = {"B_wallet_day": tb, "by_month": by_month, "leave_one_month_out": lomo}
print("\nB time-blocks (wd):", {k: v for k, v in tb.items()})
print("B by month:", {m: by_month[m][0] for m in by_month}); print("LOMO B:", lomo)

# coin decomposition
coindec = {}
for c in COINS:
    cc = coh.filter(pl.col("coin") == c); fc = fld.filter(pl.col("coin") == c)
    coindec[c] = {"A_gross": single_infer(cc, "raw_8h", "wd"), "B_field": diff_infer(cc, fc, "neut_8h", "wd"),
                  "C_fade": single_infer(cc.filter(pl.col("trail_8h").is_finite()).with_columns(d=pl.col("raw_8h")-pl.col("fade")), "d", "wd"),
                  "active": cc["wallet"].n_unique(), "wallet_days": cc.select("wallet", "day").unique().height}
coin_bal = round(float(np.mean([coindec[c]["B_field"][0] for c in COINS])), 2)
loo = {c: round(diff_infer(coh.filter(pl.col("coin") != c), fld.filter(pl.col("coin") != c), "neut_8h", "wd")[0], 2) for c in COINS}
OUT["coin_decomp"] = {"per_coin": coindec, "coin_balanced_B": coin_bal, "leave_one_coin_out_B": loo, "ex_SOL_B": loo["SOL"]}
print("\ncoin B:", {c: coindec[c]["B_field"][0] for c in COINS}, "| coin-balanced", coin_bal, "| ex-SOL", loo["SOL"])

# rolling fold ICs (Spearman rank of month-m neut_8h vs month-m+1), wallet-day, 10 folds
wmd = df.group_by("wallet", "month", "day").agg(m=pl.col("neut_8h").mean())
wm = wmd.group_by("wallet", "month").agg(mm=pl.col("m").mean(), nd=pl.len()).filter(pl.col("nd") >= 8)
mos = sorted(wm["month"].unique().to_list()); fold_ic = {}
for i in range(len(mos)-1):
    a = wm.filter(pl.col("month") == mos[i]).select("wallet", r=pl.col("mm"))
    b = wm.filter(pl.col("month") == mos[i+1]).select("wallet", nx=pl.col("mm"))
    j = a.join(b, on="wallet", how="inner")
    if j.height >= 30: fold_ic[mos[i+1]] = round(float(st.spearmanr(j["r"], j["nx"]).statistic), 3)
ics = np.array(list(fold_ic.values())); npos = int((ics > 0).sum())
lomo_ic = {m: round(float(np.mean([v for k, v in fold_ic.items() if k != m])), 3) for m in fold_ic}
OUT["rolling_ic"] = {"fold_ic": fold_ic, "mean": round(float(ics.mean()), 3), "median": round(float(np.median(ics)), 3),
    "std": round(float(ics.std()), 3), "n_folds": len(ics), "n_positive": npos,
    "sign_test_p": round(float(st.binomtest(npos, len(ics)).pvalue), 4), "lomo_mean_ic_range": [min(lomo_ic.values()), max(lomo_ic.values())],
    "resampling_unit": "adjacent-month folds (calendar time); each fold = one month-pair"}
print("\nrolling fold ICs:", fold_ic, "| mean", OUT["rolling_ic"]["mean"], "pos", npos, "/", len(ics), "sign-p", OUT["rolling_ic"]["sign_test_p"])

# behavioral equal-wallet (per-wallet median first, then compare medians across wallets)
eb = ef.with_columns(coh=pl.col("wallet").is_in(frozen),
    stretch=pl.when(pl.col("dir") > 0).then(-pl.col("dist_hi")).otherwise(pl.col("dist_lo")))
def ew_char(sub):
    pw = sub.group_by("wallet").agg(sig=pl.col("trail_8h").median(), ab=pl.col("atrail8").median(),
        str=pl.col("stretch").median(), vol=pl.col("vol2h").median())
    return {k: round(float(pw[v].median()), 1) for k, v in [("signed_pre8h", "sig"), ("abs_pre8h", "ab"), ("stretch", "str"), ("vol2h", "vol")]} | {"n_wallets": pw.height}
OUT["behavioral_equalwallet"] = {"recurring121": ew_char(eb.filter(pl.col("coh"))), "rest_cohort": ew_char(eb.filter(~pl.col("coh")))}
print("\nbehavioral EQUAL-WALLET recurring vs rest:", OUT["behavioral_equalwallet"])

json.dump(OUT, open("out/v6.json", "w"), indent=0)
print("\nsaved out/v6.json")
