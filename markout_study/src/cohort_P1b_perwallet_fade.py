"""
Per-wallet: is each cohort wallet individually a FADER (enters against the trailing move), and how consistently?
For every train entry: trailing 8h & 4h move; contrarian if dir opposes the move (dir * move < 0). Per wallet: mean
signed-trailing-in-direction (bp; <0 = fader) and fade-fraction (share of entries that are contrarian). Summarize what
% of the 121-wallet cohort are net faders + how homogeneous. Compare vs ordinary wallets. RAM-light-ish, one pass.
"""
import sys
from pathlib import Path
import numpy as np, polars as pl
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mkcommon as mk

BP = 1e4; COINS = ["BTC", "ETH", "SOL", "HYPE"]; TRAIN_HI = 1_769_904_000_000
H8 = 28800_000; H4 = 14400_000; MINE = 20                            # min train entries to classify a wallet
cohort = set(l.strip() for l in open("out/cohort_M_frozen.txt") if l.strip() and not l.startswith("#"))
df = pl.read_parquet("out/cohort_K_entries.parquet").select("wallet", "coin", "b_ts", "dir").filter(pl.col("b_ts") < TRAIN_HI)
lookups = mk._load_bars()

rows = []
for coin in COINS:
    e = df.filter(pl.col("coin") == coin); lk = lookups[coin]
    ts = e["b_ts"].to_numpy(); d = e["dir"].to_numpy().astype(float); w = e["wallet"].to_numpy()
    ent = mk._next_bar_close_vec(lk, ts)
    with np.errstate(invalid="ignore", divide="ignore"):
        m8 = ent / mk._next_bar_close_vec(lk, ts - H8) - 1.0
        m4 = ent / mk._next_bar_close_vec(lk, ts - H4) - 1.0
    ok = np.isfinite(m8) & np.isfinite(m4)
    for wi, di, a, b in zip(w[ok], d[ok], (d[ok] * m8[ok] * BP), (d[ok] * m4[ok] * BP)):
        rows.append((wi, float(a), float(b)))
R = pl.DataFrame(rows, schema=["wallet", "s8", "s4"], orient="row")
pw = R.group_by("wallet").agg(
    n=pl.len(), mean_s8=pl.col("s8").mean(), med_s8=pl.col("s8").median(),
    fade_frac8=(pl.col("s8") < 0).mean(), fade_frac4=(pl.col("s4") < 0).mean()).filter(pl.col("n") >= MINE)
pw = pw.with_columns(rec=pl.col("wallet").is_in(list(cohort)))
pw.write_parquet("out/cohort_P1b_perwallet.parquet")                 # committed per-wallet fade data (for report histogram + reproducibility)

for lab, g in [("COHORT (121 recurring)", True), ("ORDINARY", False)]:
    s = pw.filter(pl.col("rec") == g)
    N = s.height
    net_fader = s.filter(pl.col("mean_s8") < 0).height                # net-negative signed-trailing = fades on average
    strong = s.filter(pl.col("fade_frac8") >= 0.60).height            # >=60% of entries are contrarian
    veryhomog = s.filter(pl.col("fade_frac8") >= 0.70).height
    print(f"\n{lab}  (N={N} wallets, >= {MINE} train entries)")
    print(f"  net faders (mean signed-trailing-8h < 0)      : {net_fader}/{N} = {100*net_fader/N:.0f}%")
    print(f"  consistent faders (>=60% of entries contrarian): {strong}/{N} = {100*strong/N:.0f}%")
    print(f"  strong/homogeneous (>=70% contrarian)          : {veryhomog}/{N} = {100*veryhomog/N:.0f}%")
    ff = s["fade_frac8"].to_numpy()
    print(f"  fade-fraction distribution: p10={np.percentile(ff,10):.2f} p25={np.percentile(ff,25):.2f} "
          f"median={np.median(ff):.2f} p75={np.percentile(ff,75):.2f} p90={np.percentile(ff,90):.2f}")
    print(f"  per-wallet mean signed-trailing-8h: median {s['mean_s8'].median():+.0f}bp "
          f"[p25 {np.percentile(s['mean_s8'].to_numpy(),25):+.0f}, p75 {np.percentile(s['mean_s8'].to_numpy(),75):+.0f}]")
