"""
Stage M2 — RECURRENCE diagnostic (the right test the user asked for): is the problem the exact top-20 cutoff, or is
there no stable skill? Rolling monthly chronological folds; rank wallets each TRAIN month, measure the NEXT month;
record how often each wallet recurs in the TOP DECILE across independent periods; test recurrence vs the luck null;
evaluate the WHOLE top decile + a repeat-ranker basket (not just top-20). RAM-light: neut_{4,8,24}h already in the
parquet, NO bar pricing. Deterministic. Not a strategy build — a stable-skill measurement.
"""
import numpy as np, polars as pl
from scipy import stats as st
RNG = np.random.default_rng(0)
MIN_D = 8          # a wallet is eligible in a month if it has >= MIN_D active days (day-weighted rank needs coverage)
DEC = 0.10         # top decile
REPEAT_K = 3       # "repeat ranker" = top-decile in >= this many eligible months

df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "b_ts", "neut_4h", "neut_8h", "neut_24h")
df = df.with_columns(month=pl.from_epoch(pl.col("b_ts"), time_unit="ms").dt.strftime("%Y-%m"),
                     day=(pl.col("b_ts") // 86_400_000))
# day-weighted per wallet-month (mean over days of the daily mean) at each horizon
wmd = df.group_by("wallet", "month", "day").agg(d4=pl.col("neut_4h").mean(), d8=pl.col("neut_8h").mean(), d24=pl.col("neut_24h").mean())
wm = wmd.group_by("wallet", "month").agg(m4=pl.col("d4").mean(), s4=pl.col("d4").std(),
                                         m8=pl.col("d8").mean(), m24=pl.col("d24").mean(), nd=pl.len())
wm = wm.filter(pl.col("nd") >= MIN_D)
months = sorted(wm["month"].unique().to_list())
print(f"months: {months[0]}..{months[-1]} ({len(months)}) | eligible wallet-months (nd>={MIN_D}): {wm.height}")

def shrink(sub):  # James-Stein within a month, on day-weighted m4
    m = sub["m4"].to_numpy(); sd = sub["s4"].to_numpy(); n = sub["nd"].to_numpy()
    s2 = np.where(n > 1, sd ** 2 / n, np.nanmedian(sd) ** 2 / n)
    mu = m.mean(); tau2 = max(0.0, m.var() - np.nanmean(s2))
    if tau2 <= 0.0:                      # AUDIT FIX: shrinkage undefined (cross-wallet var < sampling var) ->
        return m.copy()                 # B=0 would collapse EVERY score to mu and flag 100% as top-decile. Rank raw m4.
    B = tau2 / (tau2 + s2)
    return mu + B * (m - mu)

# per-month shrunk score + top-decile flag
frames = []
for mo in months:
    sub = wm.filter(pl.col("month") == mo)
    sh = shrink(sub); thr = np.quantile(sh, 1 - DEC)
    frames.append(sub.with_columns(shrunk=pl.Series(sh)).with_columns(top=pl.Series((sh >= thr).astype(int))))
WM = pl.concat(frames)

# ---------- (1) adjacent-fold rank-IC at 4h/8h/24h (train-month shrunk -> next-month raw) ----------
print("\n=== [1] adjacent-fold rank-IC: shrunk train-month rank -> next-month day-weighted markout ===")
for hz, col in [("4h", "m4"), ("8h", "m8"), ("24h", "m24")]:
    ics = []
    for i in range(len(months) - 1):
        a = WM.filter(pl.col("month") == months[i]).select("wallet", "shrunk")
        b = WM.filter(pl.col("month") == months[i + 1]).select("wallet", nxt=pl.col(col))
        j = a.join(b, on="wallet", how="inner")
        if j.height >= 20:
            rho = st.spearmanr(j["shrunk"].to_numpy(), j["nxt"].to_numpy())[0]
            if np.isfinite(rho): ics.append(rho)
    ics = np.array(ics); npos = int((ics > 0).sum())
    sgn = st.binomtest(npos, len(ics), 0.5).pvalue
    boot = np.array([np.mean(ics[RNG.integers(0, len(ics), len(ics))]) for _ in range(5000)])
    print(f"  {hz:3}: mean IC {ics.mean():+.3f} [{np.percentile(boot,2.5):+.3f},{np.percentile(boot,97.5):+.3f}] "
          f"| folds +/tot {npos}/{len(ics)} sign-p={sgn:.3f} | per-fold {np.round(ics,2).tolist()}")

# ---------- (2) whole-top-decile forward performance vs the field (pooled across folds) ----------
print("\n=== [2] top-DECILE forward performance (next-month day-wtd 4h markout), pooled across folds ===")
diffs, tops, rests = [], [], []
for i in range(len(months) - 1):
    a = WM.filter(pl.col("month") == months[i]).select("wallet", "top")
    b = WM.filter(pl.col("month") == months[i + 1]).select("wallet", nxt=pl.col("m4"))
    j = a.join(b, on="wallet", how="inner")
    if j.height < 20: continue
    t = j.filter(pl.col("top") == 1)["nxt"].to_numpy(); r = j.filter(pl.col("top") == 0)["nxt"].to_numpy()
    if len(t) and len(r): diffs.append(t.mean() - r.mean()); tops.append(t.mean()); rests.append(r.mean())
diffs = np.array(diffs)
boot = np.array([np.mean(diffs[RNG.integers(0, len(diffs), len(diffs))]) for _ in range(5000)])
print(f"  top-decile next-month mean {np.mean(tops):+.2f} bp vs field {np.mean(rests):+.2f} bp | "
      f"DIFF {diffs.mean():+.2f} [{np.percentile(boot,2.5):+.2f},{np.percentile(boot,97.5):+.2f}] | "
      f"folds top>field {int((diffs>0).sum())}/{len(diffs)} sign-p={st.binomtest(int((diffs>0).sum()),len(diffs),0.5).pvalue:.3f}")

# ---------- (3) top-decile -> top-decile transition vs the 0.10 base rate ----------
print("\n=== [3] persistence of the RANK: P(top-decile next month | top-decile this month) ===")
n11 = n1 = 0
for i in range(len(months) - 1):
    a = WM.filter(pl.col("month") == months[i]).select("wallet", t0=pl.col("top"))
    b = WM.filter(pl.col("month") == months[i + 1]).select("wallet", t1=pl.col("top"))
    j = a.join(b, on="wallet", how="inner")
    n1 += int(j.filter(pl.col("t0") == 1).height); n11 += int(j.filter((pl.col("t0") == 1) & (pl.col("t1") == 1)).height)
p_cond = n11 / n1 if n1 else float("nan")
bt = st.binomtest(n11, n1, DEC, alternative="greater")
print(f"  P(top|top) = {p_cond:.3f} (n={n1})  vs base {DEC:.2f}  -> lift x{p_cond/DEC:.2f}, one-sided p={bt.pvalue:.4f}")

# ---------- (4) RECURRENCE vs the binomial luck null ----------
print("\n=== [4] recurrence: how many wallets hit the top decile repeatedly vs the luck null ===")
rec = WM.group_by("wallet").agg(n_elig=pl.len(), n_top=pl.col("top").sum())
rec = rec.filter(pl.col("n_elig") >= 3)   # need >=3 chances to speak of recurrence
ne = rec["n_elig"].to_numpy(); nt = rec["n_top"].to_numpy()
for K in [2, 3, 4]:
    obs = int((nt >= K).sum())
    exp = float(np.sum([1 - st.binom.cdf(K - 1, n, DEC) for n in ne]))
    # pooled Poisson-binomial tail via simulation for a p-value on the COUNT
    sim = np.array([int((RNG.binomial(ne, DEC) >= K).sum()) for _ in range(5000)])
    p = (sim >= obs).mean()
    print(f"  wallets top-decile in >= {K} months: observed {obs}  vs luck-expected {exp:.1f}  (sim p(obs>=)={p:.4f})")
top_recur = rec.filter(pl.col("n_top") >= REPEAT_K).sort("n_top", descending=True)
print(f"  REPEAT rankers (top-decile in >= {REPEAT_K} months): {top_recur.height} wallets")
print("   ", [f"{w[:8]}:{int(t)}/{int(e)}" for w, e, t in zip(top_recur['wallet'], top_recur['n_elig'], top_recur['n_top'])][:25])

# ---------- (5) repeat-ranker basket forward performance (leave-out: judge each in months AFTER it qualified) ----------
print(f"\n=== [5] repeat-ranker basket ( >= {REPEAT_K} prior top-decile months ) forward day-wtd 4h markout ===")
# for each month m (from the 4th onward), a wallet qualifies if it was top-decile in >=REPEAT_K of months < m; measure its month-m markout
qual_perf, field_perf = [], []
for i in range(len(months)):
    prior = months[:i]
    if len(prior) < REPEAT_K: continue
    hist = WM.filter(pl.col("month").is_in(prior)).group_by("wallet").agg(nt=pl.col("top").sum())
    q = set(hist.filter(pl.col("nt") >= REPEAT_K)["wallet"].to_list())
    cur = WM.filter(pl.col("month") == months[i]).select("wallet", "m4")
    if not q or cur.height < 20: continue
    qv = cur.filter(pl.col("wallet").is_in(list(q)))["m4"].to_numpy()
    fv = cur.filter(~pl.col("wallet").is_in(list(q)))["m4"].to_numpy()
    if len(qv): qual_perf.append(qv.mean()); field_perf.append(fv.mean())
if qual_perf:
    d = np.array(qual_perf) - np.array(field_perf)
    boot = np.array([np.mean(d[RNG.integers(0, len(d), len(d))]) for _ in range(5000)])
    print(f"  repeat-ranker months: {len(qual_perf)} | basket {np.mean(qual_perf):+.2f} bp vs field {np.mean(field_perf):+.2f} bp | "
          f"DIFF {d.mean():+.2f} [{np.percentile(boot,2.5):+.2f},{np.percentile(boot,97.5):+.2f}] | +folds {int((d>0).sum())}/{len(d)}")
else:
    print("  (insufficient months for a forward repeat-ranker basket)")
print("\nNOTE: neut_4h drift-stripped markout (no fade, no cost) — this measures STABLE-SKILL RECURRENCE, not deployability.")
