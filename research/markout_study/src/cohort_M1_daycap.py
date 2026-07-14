"""
Stage M1 DECISIVE TEST — day-capped copy strategy: is the day-weighted wallet persistence a tradable,
incremental edge or generic reversal? Pre-registered, two families reported SEPARATELY.

Design (frozen): (1) aggregate episodes by wallet x calendar-day; (2) fixed capital per wallet-day = the day's
MEAN episode return (extra trades -> no extra exposure; opposite dirs net in the mean); (3) exit = fixed 4h
(frozen, where persistence was found); copied entry = next-bar close (~<=5min latency); (4) net = gross - per-coin
round-trip cost (proxy, upper bound); (5) SAME daily-capital rule applied to the mechanical fade; (6) rank TRAIN
wallets by SHRUNK mean daily alpha (day_net - day_fade); (7) filter min active days + concentration; (8) freeze
top 20 + all rules; (9) judge on untouched TEST; (10) day-block bootstrap + Romano-Wolf across the frozen 20.
Family A (copyability): E[day-capped net copied return] > 0. Family B (incremental info): E[day alpha vs fade] > 0.
MOTIVATED BY PRIOR INSPECTION OF THIS DATA -> strongest confirmation still needs forward data. Not merged.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; H4 = int(mk.H_MS[5]); COINS = ["BTC", "ETH", "SOL", "HYPE"]
COST = {"BTC": 5.0, "ETH": 5.0, "SOL": 8.0, "HYPE": 8.0}      # round-trip bp proxy (upper bound)
RNG = np.random.default_rng(0)
def msf(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = msf(2026, 2, 1); TEST_LO = msf(2026, 3, 1)

df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "split")
lookups = mk._load_bars()
recs = []
for coin in COINS:
    e = df.filter(pl.col("coin") == coin)
    if e.height == 0: continue
    b = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float); lk = lookups[coin]
    ent = mk._next_bar_close_vec(lk, b); ex = mk._next_bar_close_vec(lk, b + H4); past = mk._next_bar_close_vec(lk, b - H4)
    with np.errstate(invalid="ignore", divide="ignore"):
        move = ex / ent - 1.0
        wret = d * move * BP                                  # wallet copied gross (bp)
        fret = -np.sign(ent / past - 1.0) * move * BP         # mechanical fade gross (bp), same entry/exit
    net = wret - COST[coin]                                   # Family-A net copied (cost applied to the $1 day-slice)
    alpha = wret - fret                                       # Family-B incremental (cost cancels: both pay it)
    day = (b // 86_400_000)
    fin = np.isfinite(wret) & np.isfinite(fret)
    for i in np.where(fin)[0]:
        recs.append((e["wallet"][int(i)], coin, int(day[i]), e["split"][int(i)], float(net[i]), float(alpha[i])))
E = pl.DataFrame(recs, schema=["wallet", "coin", "day", "split", "net", "alpha"], orient="row")
print(f"priced episodes: {E.height}", flush=True)

# ---- (2) day-capped: wallet-day MEAN (fixed capital per wallet-day) ----
wd = E.group_by("wallet", "split", "day").agg(net=pl.col("net").mean(), alpha=pl.col("alpha").mean(),
                                              coin=pl.col("coin").first(), nep=pl.len())

def per_wallet(sp):
    g = wd.filter(pl.col("split") == sp).group_by("wallet").agg(
        net_m=pl.col("net").mean(), net_sd=pl.col("net").std(),
        alpha_m=pl.col("alpha").mean(), alpha_sd=pl.col("alpha").std(), nd=pl.len())
    return g
tr = per_wallet("train").rename({c: f"tr_{c}" for c in ["net_m", "net_sd", "alpha_m", "alpha_sd", "nd"]})
te = per_wallet("test").rename({c: f"te_{c}" for c in ["net_m", "net_sd", "alpha_m", "alpha_sd", "nd"]})
W = tr.join(te, on="wallet", how="left")     # PATCH #11: LEFT join -> test presence must NOT gate selection

# ---- (6) shrink TRAIN daily alpha (James-Stein) ; (7) filters ----
W = W.filter((pl.col("tr_nd") >= 30) & pl.col("tr_alpha_sd").is_not_null())   # PATCH #11: TRAIN-only selection eligibility
m = W["tr_alpha_m"].to_numpy(); s2 = (W["tr_alpha_sd"].to_numpy() ** 2) / W["tr_nd"].to_numpy()
mu = m.mean(); tau2 = max(0.0, m.var() - s2.mean()); B = tau2 / (tau2 + s2)
W = W.with_columns(shrunk_tr_alpha=pl.Series(mu + B * (m - mu)))
print(f"eligible wallets (>=30 TRAIN days, TRAIN-only selection): {W.height} | tau2={tau2:.1f} median B={np.median(B):.2f}")

# concentration on TRAIN (top-day, top-token share of cumulative alpha magnitude)
conc = (wd.filter(pl.col("split") == "train").join(W.select("wallet"), on="wallet", how="inner")
        .with_columns(a=pl.col("alpha")))
topday = conc.group_by("wallet").agg(topday_sh=(pl.col("a").abs().max() / pl.col("a").abs().sum()))
toptok = (E.filter(pl.col("split") == "train").join(W.select("wallet"), on="wallet", how="inner")
          .group_by("wallet", "coin").agg(s=pl.col("alpha").abs().sum())
          .group_by("wallet").agg(toptok_sh=(pl.col("s").max() / pl.col("s").sum())))
W = W.join(topday, on="wallet", how="left").join(toptok, on="wallet", how="left")
W = W.filter((pl.col("topday_sh") < 0.5) & (pl.col("toptok_sh") < 0.7))     # low concentration

# ---- (8) freeze top 20 by shrunk train alpha (TRAIN-only selection) ----
top = W.sort("shrunk_tr_alpha", descending=True).head(20)
picks = top["wallet"].to_list()                              # FROZEN top-20 on TRAIN only
MIN_TE = 15   # pre-registered data-sufficiency / attrition bar (STAGE_M1 arch §10), on test-day COUNT only (no outcome) -> no leak
ev = top.filter(pl.col("te_nd") >= MIN_TE)["wallet"].to_list()   # PATCH #11: evaluable subset; rest = attrition (unevaluable)
attr = [w for w in picks if w not in ev]
print(f"\n=== FROZEN TOP-20 (train-only selection); evaluable (>= {MIN_TE} test days): {len(ev)}/20 | attrition {len(attr)} (insufficient test coverage, dropped NOT failed) ===")

# ---- (9)+(10) TEST evaluation: day-block bootstrap over the evaluable frozen wallets ----
tw = wd.filter((pl.col("split") == "test") & pl.col("wallet").is_in(ev))
days = np.sort(tw["day"].unique().to_numpy()); di = {int(x): i for i, x in enumerate(days)}
wi = {w: i for i, w in enumerate(ev)}
NW, ND = len(ev), len(days)
Anet = np.full((NW, ND), np.nan); Aal = np.full((NW, ND), np.nan)
for w, dd, n, a in zip(tw["wallet"], tw["day"], tw["net"], tw["alpha"]):
    Anet[wi[w], di[int(dd)]] = n; Aal[wi[w], di[int(dd)]] = a
def wmean(M): return np.array([np.nanmean(M[i]) if np.isfinite(M[i]).any() else np.nan for i in range(NW)])
te_net, te_al = wmean(Anet), wmean(Aal)
trmap_net = dict(zip(top["wallet"].to_list(), top["tr_net_m"].to_list()))
trmap_al = dict(zip(top["wallet"].to_list(), top["tr_alpha_m"].to_list()))
tr_net = np.array([trmap_net[w] for w in ev]); tr_al = np.array([trmap_al[w] for w in ev])

# basket day-block bootstrap (resample test days jointly)
B_BOOT = 5000
bn = np.empty(B_BOOT); ba = np.empty(B_BOOT)
for bnum in range(B_BOOT):
    pick = RNG.integers(0, ND, ND)
    bn[bnum] = np.nanmean([np.nanmean(Anet[i, pick]) for i in range(NW)])
    ba[bnum] = np.nanmean([np.nanmean(Aal[i, pick]) for i in range(NW)])
def ci_p(boot):
    lo, hi = np.percentile(boot, [2.5, 97.5]); p = (boot <= 0).mean(); return lo, hi, p
An_lo, An_hi, An_p = ci_p(bn); Aa_lo, Aa_hi, Aa_p = ci_p(ba)

# per-wallet Romano-Wolf (one-sided, day-block max-t), moderated SE
se_al = np.array([np.nanstd(Aal[i]) / np.sqrt(np.isfinite(Aal[i]).sum()) for i in range(NW)])
s0 = np.nanmedian(se_al); se_al_m = np.sqrt((4 * s0 ** 2 + se_al ** 2) / 5)
t_al = te_al / se_al_m
maxt = np.empty(B_BOOT)
for bnum in range(B_BOOT):
    pick = RNG.integers(0, ND, ND)
    m_b = np.array([np.nanmean(Aal[i, pick]) for i in range(NW)])
    maxt[bnum] = np.nanmax((m_b - te_al) / se_al_m)
rw_p = np.array([(maxt >= t_al[i]).mean() for i in range(NW)])   # single-step RW adj p (conservative)

print(f"\n{'wallet':>10s} {'tr_net':>7s} {'te_net':>7s} {'tr_alpha':>8s} {'te_alpha':>8s} {'RWp_B':>6s} {'nd':>3s} {'topday':>6s} {'toptok':>6s}")
for i, w in enumerate(ev):
    r = top.filter(pl.col("wallet") == w)
    print(f"{w[:10]:>10s} {tr_net[i]:>7.1f} {te_net[i]:>7.1f} {tr_al[i]:>8.1f} {te_al[i]:>8.1f} {rw_p[i]:>6.3f} "
          f"{int(r['te_nd'][0]):>3d} {float(r['topday_sh'][0]):>6.2f} {float(r['toptok_sh'][0]):>6.2f}")

print(f"\n=== BASKET (equal-weight across {NW} evaluable frozen wallets), TEST, day-block bootstrap ===")
print(f"  A  copyability   net copied return: train {np.nanmean(tr_net):+.2f}  TEST {np.nanmean(te_net):+.2f} bp "
      f"[{An_lo:+.2f},{An_hi:+.2f}]  one-sided p(>0)={An_p:.4f}")
print(f"  B  incremental   alpha over fade  : train {np.nanmean(tr_al):+.2f}  TEST {np.nanmean(te_al):+.2f} bp "
      f"[{Aa_lo:+.2f},{Aa_hi:+.2f}]  one-sided p(>0)={Aa_p:.4f}")
print(f"  RW-survivors (B, adj p<0.05): {(rw_p<0.05).sum()}/{NW} | (A basket cost={list(COST.values())} bp/rt)")
# concentration of the basket's TEST alpha (PATCH #8: |.| share, matching the wallet-level filter convention)
tb = tw.group_by("day").agg(a=pl.col("alpha").mean())
aa = tb["a"].abs(); topd = float(aa.max() / aa.sum()) if float(aa.sum()) > 0 else float("nan")
print(f"  basket TEST alpha top-day share (abs): {topd:.2f}")

# persist frozen artifacts for the RAM-free robustness battery (per-episode priced net/alpha for the frozen 20)
E.filter(pl.col("wallet").is_in(picks)).write_parquet("out/cohort_M1_ep.parquet")
top.write_parquet("out/cohort_M1_top.parquet")
Path("out/cohort_M1_frozen.txt").write_text("EV\n" + "\n".join(ev) + "\nATTR\n" + "\n".join(attr) + "\n")

te_net_m = float(np.nanmean(te_net)); te_al_m = float(np.nanmean(te_al))
A_ok = An_lo > 0; B_ok = Aa_lo > 0
print("\n=== VERDICT ===")
if A_ok and B_ok:      print("(1) Day-capped strategy is PROFITABLE and BEATS FADE.")
elif A_ok and not B_ok: print("(2) Day-capped strategy is PROFITABLE but does NOT beat fade (likely generic reversal component).")
elif (not A_ok) and B_ok: print("(2b) Beats fade but net-of-cost not profitable — informative, not deployable as-is.")
elif te_al_m > 0 and Aa_p > 0.05 and te_net_m <= 0: print("(3) Daily persistence exists statistically but is NOT economically tradable after costs.")
elif te_al_m > 0 and te_net_m > 0: print("(0) INCONCLUSIVE-leaning-positive: both point estimates >0 but CIs include 0 (not falsified, not confirmed).")
else: print("(4) Daily persistence does NOT survive the matched fade test.")
print("NOTE: motivated by prior inspection of this data; TEST window is not virgin -> strongest confirmation needs forward data.")
