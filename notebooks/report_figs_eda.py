"""EDA + wallet-fingerprint figures (13-21) for the informed-wallets report.
Train-side only: entry conditioning uses PRE-entry data (allowed — it is context, not scoring);
all price series and entries are clipped to the train window. Run after report_figs.py."""
import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scratch_conv"))
from mlscreen2 import (ALL_MONTHS, DAY_MS, MARKOUT_HOURS, OUT, SPLIT, T0,
                      TRAIN_MONTHS, _load_bars)

FIG = REPO / "notebooks/report_figs"
SPLIT_MS = T0 + SPLIT * DAY_MS
plt.rcParams.update({"figure.dpi": 120, "axes.grid": True, "grid.alpha": 0.3})
MAJORS = {"BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE"}

e = pl.read_parquet(OUT / "top50_entries.parquet")
rows = [json.loads(l) for l in open(OUT / "markout2.jsonl") if l.strip()]
i24 = MARKOUT_HOURS.index(24)
elig_rows = [r for r in rows if r["train_n"][i24] >= 30]
top_idx = np.argsort(-np.array([r["train_pnl"][i24] for r in elig_rows]))[:50]
top_w = [elig_rows[i]["w"] for i in top_idx]
lookups = _load_bars()

# ---- fig 13: tape overview -------------------------------------------------------
train_bars = [OUT / f"bars_{m}.parquet" for m in TRAIN_MONTHS if (OUT / f"bars_{m}.parquet").exists()]
bars_daily = (pl.scan_parquet(train_bars)
              .with_columns(day=(pl.col("bar") // DAY_MS))
              .group_by("day").agg(coins=pl.col("coin").n_unique(), bars=pl.len())
              .sort("day").collect(engine="streaming"))
stats_m = []
for m in TRAIN_MONTHS:
    f = OUT / f"stats_{m}.parquet"
    if f.exists():
        d = pl.read_parquet(f)
        stats_m.append((m, d.height, float((d["n_orders"] * d["mean_notional"]).sum())))
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
days = [dt.datetime.fromtimestamp(d * 86400, dt.timezone.utc) for d in bars_daily["day"].to_list()]
a1.plot(days, bars_daily["coins"].to_list(), color="#3b7dd8")
a1.set_title("Listed perps trading per day"); a1.tick_params(axis="x", rotation=30)
xs = [m[-2:] + "/" + m[2:4] for m, _, _ in stats_m]
a2.bar(xs, [v / 1e9 for _, _, v in stats_m], color="#888")
a2.set_ylabel("$B taker notional"); a2.set_title("Monthly taker volume")
ax22 = a2.twinx(); ax22.plot(xs, [n / 1e3 for _, n, _ in stats_m], "ko--"); ax22.set_ylabel("k wallets")
ax22.grid(False)
fig.tight_layout(); fig.savefig(FIG / "13_tape_overview.png"); plt.close(fig)

# ---- fig 14: wallet demographics -------------------------------------------------
allstats = pl.concat([pl.read_parquet(OUT / f"stats_{m}.parquet")
                      for m in TRAIN_MONTHS if (OUT / f"stats_{m}.parquet").exists()])
dem = (allstats.group_by("taker")
       .agg(t_min=pl.col("t_min").min(), t_max=pl.col("t_max").max(),
            vol=(pl.col("n_orders") * pl.col("mean_notional")).sum()))
life = ((dem["t_max"] - dem["t_min"]) / DAY_MS).to_numpy()
vol = np.sort(dem["vol"].to_numpy())[::-1]
cum = np.cumsum(vol) / vol.sum()
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
a1.hist(np.clip(life, 0, 190), bins=60, color="#888"); a1.set_yscale("log")
a1.set_xlabel("wallet lifespan (days, train window)"); a1.set_title("Wallet lifespans")
frac = np.arange(1, vol.size + 1) / vol.size
a2.plot(frac * 100, cum * 100, color="#3b7dd8")
a2.set_xscale("log"); a2.set_xlabel("% of wallets (by volume rank)")
a2.set_ylabel("% of taker volume"); a2.set_title("Volume concentration")
a2.axvline(1, color="k", ls=":", lw=0.8)
fig.tight_layout(); fig.savefig(FIG / "14_demographics.png"); plt.close(fig)

# ---- helper: last-closed bar price at t (pre-entry context is allowed) ------------
def px_at(lk, ts):
    times, closes = lk
    j = np.searchsorted(times, ts, side="right") - 1
    ok = (j >= 0) & (j < closes.size)
    return np.where(ok, closes[np.clip(j, 0, closes.size - 1)], np.nan)

# ---- fig 15: entry style (momentum vs contrarian) --------------------------------
style_rows = []
for (w, coin), g in e.group_by(["w", "coin"]):
    lk = lookups.get(str(coin))
    if lk is None:
        continue
    t = g["ts"].to_numpy(); d = g["dir"].to_numpy()
    p0 = px_at(lk, t); p4 = px_at(lk, t - 4 * 3_600_000)
    ok = np.isfinite(p0) & np.isfinite(p4) & (p4 > 0)
    if ok.sum() == 0:
        continue
    style_rows.append(pl.DataFrame({"w": [str(w)] * int(ok.sum()),
                                    "s": (d[ok] * (p0[ok] / p4[ok] - 1) * 1e4)}))
sty = pl.concat(style_rows).group_by("w").agg(style=pl.col("s").median(), n=pl.len())
sv = sty["style"].to_numpy()
fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(np.clip(sv, -120, 120), bins=30, color="#3b7dd8")
ax.axvline(0, color="k", lw=0.8)
ax.set_xlabel("median dir x prior-4h return (bps)   <-- contrarian | momentum -->")
ax.set_title("Entry style per wallet (top-50)")
fig.tight_layout(); fig.savefig(FIG / "15_entry_style.png"); plt.close(fig)
print(f"fig15 style: contrarian {(sv<0).sum()}/50, momentum {(sv>0).sum()}/50")

# ---- fig 16: hour-of-day x weekday entry heatmap ----------------------------------
ts = e["ts"].to_numpy()
dts = [(dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc)) for x in ts[::7]]  # sample for speed
H = np.zeros((7, 24))
for d_ in dts:
    H[d_.weekday(), d_.hour] += 1
fig, ax = plt.subplots(figsize=(9, 3.5))
im = ax.imshow(H / H.sum(), aspect="auto", cmap="viridis")
ax.set_yticks(range(7)); ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
ax.set_xlabel("UTC hour"); ax.set_title("Entry timing (top-50, share of entries)")
fig.colorbar(im, shrink=0.8)
fig.tight_layout(); fig.savefig(FIG / "16_entry_timing.png"); plt.close(fig)

# ---- fig 17: sizing fingerprint ---------------------------------------------------
szf = e.group_by("w").agg(cv=pl.col("notional").std() / pl.col("notional").mean(),
                          eqw=(pl.col("m24") / pl.col("notional")).mean() * 1e4)
fig, ax = plt.subplots(figsize=(8, 4.5))
cvv, eqv = szf["cv"].to_numpy(), szf["eqw"].to_numpy()
ax.scatter(cvv, eqv, color="#3b7dd8", alpha=0.7)
neg = eqv < 0
ax.scatter(cvv[neg], eqv[neg], color="#c44", label="negative per-entry (size-timers)")
ax.axhline(0, color="k", lw=0.8)
ax.set_xlabel("entry-size coefficient of variation (uniform sizer <-> conviction sizer)")
ax.set_ylabel("per-entry 24h markout (bps)")
ax.set_title("Sizing fingerprint vs per-entry skill")
ax.legend()
fig.tight_layout(); fig.savefig(FIG / "17_sizing.png"); plt.close(fig)

# ---- fig 18: term-structure heatmap (50 x 9) --------------------------------------
B = np.array([elig_rows[i]["train_bps_sum"] for i in top_idx])
N = np.array([elig_rows[i]["train_n"] for i in top_idx])
WM = B / np.maximum(N, 1)
order = np.argsort(-(WM[:, MARKOUT_HOURS.index(72)]))
fig, ax = plt.subplots(figsize=(7, 8))
im = ax.imshow(np.clip(WM[order], -200, 200), aspect="auto", cmap="RdYlGn", vmin=-200, vmax=200)
ax.set_xticks(range(9)); ax.set_xticklabels([f"{h}h" if h < 168 else "1wk" for h in MARKOUT_HOURS])
ax.set_yticks([]); ax.set_ylabel("top-50 wallets (sorted by 72h markout)")
ax.set_title("Markout term structure per wallet")
fig.colorbar(im, shrink=0.6, label="bps/entry (clipped ±200)")
fig.tight_layout(); fig.savefig(FIG / "18_term_heatmap.png"); plt.close(fig)

# ---- fig 19: co-entry clustering ---------------------------------------------------
cd = e.with_columns(day=(pl.col("ts") // DAY_MS)).select(["w", "coin", "day"]).unique()
sets = {str(w): set(zip(g["coin"].to_list(), g["day"].to_list()))
        for (w,), g in cd.group_by("w")}
ws = [w for w in top_w if w in sets]
n = len(ws)
J = np.zeros((n, n))
for i in range(n):
    for j in range(i, n):
        a, b = sets[ws[i]], sets[ws[j]]
        J[i, j] = J[j, i] = len(a & b) / max(len(a | b), 1)
# spectral ordering by Fiedler vector (numpy only)
W = J.copy(); np.fill_diagonal(W, 0)
L = np.diag(W.sum(1)) - W
vals, vecs = np.linalg.eigh(L)
order = np.argsort(vecs[:, 1])
fig, ax = plt.subplots(figsize=(7, 6.5))
im = ax.imshow(J[order][:, order], cmap="viridis", vmin=0, vmax=min(1.0, J[~np.eye(n, dtype=bool)].max()))
ax.set_xticks([]); ax.set_yticks([])
ax.set_title("Co-entry overlap between top-50 wallets (Jaccard of coin-days)")
fig.colorbar(im, shrink=0.7)
fig.tight_layout(); fig.savefig(FIG / "19_coentry.png"); plt.close(fig)

# ---- fig 20: within-train persistence (half 1 vs half 2) ---------------------------
half_ms = T0 + (SPLIT // 2) * DAY_MS
pers = []
for (w,), g in e.group_by("w"):
    a = g.filter(pl.col("ts") < half_ms); b = g.filter(pl.col("ts") >= half_ms)
    if a.height >= 20 and b.height >= 20:
        pers.append(((a["m24"] / a["notional"]).mean() * 1e4,
                     (b["m24"] / b["notional"]).mean() * 1e4))
pers = np.array(pers)
fig, ax = plt.subplots(figsize=(6.5, 6))
ax.scatter(pers[:, 0], pers[:, 1], color="#2a9d2a", alpha=0.75)
ax.axhline(0, color="k", lw=0.8); ax.axvline(0, color="k", lw=0.8)
lim = np.nanpercentile(np.abs(pers), 98)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
r = np.corrcoef(pers[:, 0], pers[:, 1])[0, 1]
q = ((pers[:, 0] > 0) & (pers[:, 1] > 0)).mean()
ax.set_xlabel("per-entry 24h markout, train half 1 (bps)")
ax.set_ylabel("train half 2 (bps)")
ax.set_title(f"Within-train persistence (top-50): r={r:+.2f}, both-halves-positive={q:.0%}")
fig.tight_layout(); fig.savefig(FIG / "20_persistence.png"); plt.close(fig)
print(f"fig20 persistence: n={pers.shape[0]}, r={r:+.2f}, both-pos={q:.0%}")

# ---- fig 21: vignettes -------------------------------------------------------------
picks = ["0xe31c865988c9c0401773d5ea04062179662afeea",
         "0xe9c888b87f2c8723a08d105a18bcd5cbb101770f"]
fig, axes = plt.subplots(2, 1, figsize=(10, 7))
for ax, w in zip(axes, picks):
    g = e.filter(pl.col("w") == w)
    if g.height == 0:
        continue
    topcoin = (g.group_by("coin").agg(a=pl.col("m24").abs().sum())
               .sort("a", descending=True)["coin"][0])
    lk = lookups[topcoin]
    mask = lk[0] < SPLIT_MS
    tt = lk[0][mask][::36]; cc = lk[1][mask][::36]   # 3-hourly samples
    ax.plot([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc) for x in tt], cc,
            color="#888", lw=1)
    gg = g.filter(pl.col("coin") == topcoin)
    ge = gg["ts"].to_numpy(); gd = gg["dir"].to_numpy(); gn = gg["notional"].to_numpy()
    p = px_at(lk, ge)
    for d_, c_, m_ in ((1, "#2a9d2a", "^"), (-1, "#c44", "v")):
        k = gd == d_
        ax.scatter([dt.datetime.fromtimestamp(x / 1000, dt.timezone.utc) for x in ge[k]],
                   p[k], s=np.sqrt(gn[k]) / 8, color=c_, marker=m_, alpha=0.55, zorder=3)
    ax.set_title(f"{w[:10]}…  entries on {topcoin} (▲ long, ▼ short; size = notional)")
    ax.tick_params(axis="x", rotation=20)
fig.tight_layout(); fig.savefig(FIG / "21_vignettes.png"); plt.close(fig)
print("EDA figures 13-21 written")
