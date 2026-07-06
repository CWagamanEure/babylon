"""
Stage M2 DEPLOYABILITY gate — the decile instrument (not top-20) day-capped, at 8h (persistence peak) & 4h, tested
(a) NET of realistic + campaign cost and (b) ALPHA vs the mechanical fade (skill vs generic reversal). Wallet AND fade
priced on the SAME next-bar-close basis so cost cancels in alpha. Rank TRAIN day-weighted GROSS wallet markout; freeze
top decile (long-only = deployable) + bottom decile (for the L-S reference); judge TEST with a joint day-block bootstrap.
This is the load-bearing test: does the powered persistence survive the fade + cost? RAM: one heavy pricing pass.
"""
import sys
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; COINS = ["BTC", "ETH", "SOL", "HYPE"]
H = {"8h": 8 * 3600 * 1000, "4h": 4 * 3600 * 1000}
COST_REAL = {"BTC": 6.0, "ETH": 6.0, "SOL": 7.0, "HYPE": 9.0}      # realistic HL round-trip (audit #6)
COST_CAMP = {"BTC": 8.0, "ETH": 8.0, "SOL": 10.0, "HYPE": 14.0}    # campaign stress
MIN_TR, MIN_TE = 10, 8; RNG = np.random.default_rng(0)

df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir", "split")
lookups = mk._load_bars(); recs = []
for coin in COINS:
    e = df.filter(pl.col("coin") == coin)
    if e.height == 0: continue
    b = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float); lk = lookups[coin]
    ent = mk._next_bar_close_vec(lk, b); cols = {}
    fin = np.isfinite(ent)
    for hz, hm in H.items():
        ex = mk._next_bar_close_vec(lk, b + hm); past = mk._next_bar_close_vec(lk, b - hm)
        with np.errstate(invalid="ignore", divide="ignore"):
            move = ex / ent - 1.0
            cols[f"w{hz}"] = d * move * BP                          # wallet copied gross
            cols[f"f{hz}"] = -np.sign(ent / past - 1.0) * move * BP  # mechanical fade gross, same entry/exit
        fin &= np.isfinite(cols[f"w{hz}"]) & np.isfinite(cols[f"f{hz}"])
    day = b // 86_400_000
    for i in np.where(fin)[0]:
        recs.append((e["wallet"][int(i)], coin, int(day[i]), e["split"][int(i)],
                     float(cols["w8h"][i]), float(cols["f8h"][i]), float(cols["w4h"][i]), float(cols["f4h"][i])))
E = pl.DataFrame(recs, schema=["wallet", "coin", "day", "split", "w8", "f8", "w4", "f4"], orient="row")
print(f"priced episodes: {E.height}", flush=True)
E = E.with_columns(
    n8r=pl.col("w8") - pl.col("coin").replace_strict(COST_REAL, default=0.0), a8=pl.col("w8") - pl.col("f8"),
    n8c=pl.col("w8") - pl.col("coin").replace_strict(COST_CAMP, default=0.0),
    n4r=pl.col("w4") - pl.col("coin").replace_strict(COST_REAL, default=0.0), a4=pl.col("w4") - pl.col("f4"))
# day-cap: wallet-split-day mean (equal capital per wallet-day)
wd = E.group_by("wallet", "split", "day").agg([pl.col(c).mean().alias(c) for c in ["w8", "n8r", "n8c", "a8", "w4", "n4r", "a4"]])

def perwallet(sp):
    return wd.filter(pl.col("split") == sp).group_by("wallet").agg(
        [pl.col(c).mean().alias(c) for c in ["w8", "n8r", "n8c", "a8", "w4", "n4r", "a4"]] + [pl.len().alias("nd")])
tr = perwallet("train"); te = perwallet("test")

def matrix(wallets, col):
    w = wd.filter((pl.col("split") == "test") & pl.col("wallet").is_in(wallets)).group_by("wallet", "day").agg(v=pl.col(col).mean())
    ds = np.sort(w["day"].unique().to_numpy()); wi = {x: i for i, x in enumerate(wallets)}; di = {int(x): i for i, x in enumerate(ds)}
    M = np.full((len(wallets), len(ds)), np.nan)
    for x, dd, v in zip(w["wallet"], w["day"], w["v"]):
        if x in wi: M[wi[x], di[int(dd)]] = v
    return M
def ew(M): return np.nanmean([np.nanmean(M[i]) if np.isfinite(M[i]).any() else np.nan for i in range(M.shape[0])])
def ci(M):
    ND = M.shape[1]; bs = np.empty(3000)
    for b in range(3000):
        p = RNG.integers(0, ND, ND)
        with np.errstate(invalid="ignore"): bs[b] = ew(M[:, p])
    return ew(M), float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5)), float((bs <= 0).mean())

for hz, gross, netr, netc, alp in [("8h", "w8", "n8r", "n8c", "a8"), ("4h", "w4", "n4r", None, "a4")]:
    j = tr.filter(pl.col("nd") >= MIN_TR).join(te.filter(pl.col("nd") >= MIN_TE).select("wallet"), on="wallet", how="inner")
    thr_hi = j[gross].quantile(0.90); thr_lo = j[gross].quantile(0.10)
    topd = j.filter(pl.col(gross) >= thr_hi)["wallet"].to_list()
    botd = j.filter(pl.col(gross) <= thr_lo)["wallet"].to_list()
    print(f"\n===== {hz}: rank on TRAIN day-weighted GROSS wallet markout | eligible {j.height} | top decile {len(topd)}, bottom {len(botd)} =====")
    g, glo, ghi, gp = ci(matrix(topd, gross)); print(f"  top-decile GROSS (long-only):        {g:+.2f} bp [{glo:+.2f},{ghi:+.2f}] p={gp:.4f}")
    nr, nrlo, nrhi, nrp = ci(matrix(topd, netr)); print(f"  top-decile NET realistic cost:        {nr:+.2f} bp [{nrlo:+.2f},{nrhi:+.2f}] p={nrp:.4f}")
    if netc:
        nc, nclo, nchi, ncp = ci(matrix(topd, netc)); print(f"  top-decile NET campaign cost (stress):{nc:+.2f} bp [{nclo:+.2f},{nchi:+.2f}] p={ncp:.4f}")
    a, alo, ahi, ap = ci(matrix(topd, alp)); print(f"  top-decile ALPHA vs mechanical fade:  {a:+.2f} bp [{alo:+.2f},{ahi:+.2f}] p={ap:.4f}   <-- skill-vs-reversal discriminator")
    # decile long-short (gross + alpha), for reference
    tgt = ew(matrix(topd, gross)); btm = ew(matrix(botd, gross))
    tga = ew(matrix(topd, alp)); bta = ew(matrix(botd, alp))
    print(f"  decile L-S gross: top {tgt:+.2f} - bottom {btm:+.2f} = {tgt-btm:+.2f} bp | L-S alpha-vs-fade: {tga-bta:+.2f} bp")

print("\nNOTE: wallet & fade both next-bar-close entry -> cost cancels in ALPHA. GROSS/NET = what a top-decile copier earns;")
print("ALPHA vs fade = does wallet identity beat a costless mechanical contrarian at the same entries (skill vs generic reversal).")
