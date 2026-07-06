"""Figures for the informed-wallets team report (train-side ONLY — no test_* fields).
Writes PNGs to scratch_conv/report_figs/. The same code lives in the report notebook."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "scratch_conv/mlscreen"
FIG = REPO / "notebooks/report_figs"; FIG.mkdir(exist_ok=True)
H = [1, 2, 4, 8, 12, 24, 48, 72, 168]
DAY = 86_400_000
T0 = 1754006400000
plt.rcParams.update({"figure.dpi": 120, "axes.grid": True, "grid.alpha": 0.3})

# ---- fig 1: the filter funnel -------------------------------------------------
months = ["202510", "202511", "202512", "202601", "202602", "202603"]
df = pl.concat([pl.read_parquet(OUT / f"stats_{m}.parquet") for m in months])
agg = (df.group_by("taker").agg(
    n_orders=pl.col("n_orders").sum(),
    mean_notional=(pl.col("mean_notional") * pl.col("n_orders")).sum() / pl.col("n_orders").sum(),
    days=pl.col("days").sum(), t_min=pl.col("t_min").min(), t_max=pl.col("t_max").max())
    .with_columns(span=((pl.col("t_max") - pl.col("t_min")) / DAY).clip(1))
    .with_columns(tpd=pl.col("n_orders") / pl.col("span")))
steps = [
    ("all takers", pl.lit(True)),
    (">=150 orders", pl.col("n_orders") >= 150),
    ("<=20k orders", pl.col("n_orders") <= 20000),
    (">=25 active days", pl.col("days") >= 25),
    ("0.5-15 orders/day", (pl.col("tpd") >= 0.5) & (pl.col("tpd") <= 15)),
    (">=$500 mean order", pl.col("mean_notional") >= 500),
]
counts, cur = [], pl.lit(True)
for name, cond in steps:
    cur = cur & cond
    counts.append((name, agg.filter(cur).height))
fig, ax = plt.subplots(figsize=(8, 4))
names = [c[0] for c in counts]; vals = [c[1] for c in counts]
ax.bar(range(len(vals)), vals, color=["#777"] + ["#3b7dd8"] * (len(vals) - 1))
ax.set_yscale("log"); ax.set_xticks(range(len(vals)))
ax.set_xticklabels(names, rotation=20, ha="right", fontsize=8)
for i, v in enumerate(vals):
    ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=8)
ax.set_title("Wallet filter funnel")
fig.tight_layout(); fig.savefig(FIG / "01_funnel.png"); plt.close(fig)

# ---- load markout profiles ----------------------------------------------------
rows = [json.loads(l) for l in open(OUT / "markout2.jsonl") if l.strip()]
P = np.array([r["train_pnl"] for r in rows])
N = np.array([r["train_n"] for r in rows])
B = np.array([r["train_bps_sum"] for r in rows])
i24 = H.index(24)
elig = N[:, i24] >= 30
P, N, B = P[elig], N[elig], B[elig]
top = np.argsort(-P[:, i24])[:50]
field_bps = B.sum(axis=0) / np.maximum(N.sum(axis=0), 1)
top_bps = B[top].sum(axis=0) / np.maximum(N[top].sum(axis=0), 1)

# ---- fig 2: term structure ----------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(H, top_bps, "o-", color="#2a9d2a", label="top-50 (ranked by train 24h $PnL)")
ax.plot(H, field_bps, "s-", color="#c44", label=f"field ({elig.sum():,} eligible wallets)")
ax.axhline(0, color="k", lw=0.8)
ax.set_xscale("log"); ax.set_xticks(H); ax.set_xticklabels([f"{h}h" if h < 168 else "1wk" for h in H])
ax.set_ylabel("markout, bps per entry (equal-weight)"); ax.set_xlabel("horizon after entry")
ax.set_title("Markout term structure (train window)")
ax.legend()
fig.tight_layout(); fig.savefig(FIG / "02_term_structure.png"); plt.close(fig)

# ---- fig 3: per-wallet 24h bps distribution ------------------------------------
wb = B[:, i24] / np.maximum(N[:, i24], 1)
fig, ax = plt.subplots(figsize=(8, 4))
ax.hist(np.clip(wb, -300, 300), bins=80, color="#888", alpha=0.8, label="field")
ax.hist(np.clip(wb[top], -300, 300), bins=40, color="#2a9d2a", alpha=0.9, label="top-50")
ax.axvline(0, color="k", lw=0.8); ax.set_yscale("log")
ax.set_xlabel("per-wallet mean 24h markout (bps/entry, clipped ±300)")
ax.set_title("Per-wallet 24h markout")
ax.legend()
fig.tight_layout(); fig.savefig(FIG / "03_wallet_dist.png"); plt.close(fig)

# ---- figs 4-6 from the per-entry extract --------------------------------------
import datetime as _dt
e = pl.read_parquet(OUT / "top50_entries.parquet").with_columns(
    cmonth=pl.from_epoch("ts", time_unit="ms").dt.strftime("%Y-%m"))   # CALENDAR months
btc = pl.scan_parquet([OUT / f"bars_{m}.parquet" for m in months]) \
    .filter(pl.col("coin") == "BTC").collect().sort("bar")
bt, bc = btc["bar"].to_numpy(), btc["close"].to_numpy()
SPLIT_MS = T0 + 243 * DAY
mo = e.group_by("cmonth").agg(pnl=pl.col("m24").sum()).sort("cmonth")
xs, pnls, brets = [], [], []
for cm, pnl in mo.iter_rows():
    y, m = int(cm[:4]), int(cm[5:])
    a = int(_dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    b = int(_dt.datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    b = min(b, SPLIT_MS)
    ia, ib = np.searchsorted(bt, a), min(np.searchsorted(bt, b) - 1, bc.size - 1)
    xs.append(_dt.datetime(y, m, 1).strftime("%b")); pnls.append(pnl / 1e6)
    brets.append((bc[ib] / bc[ia] - 1) * 100 if 0 <= ia < bc.size and ib > ia else np.nan)
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(xs, pnls, color="#2a9d2a", label="top-50 24h markout PnL ($M)")
ax2 = ax.twinx(); ax2.plot(xs, brets, "ko--", label="BTC monthly %"); ax2.set_ylabel("BTC %")
ax.set_ylabel("$M"); ax.set_title("Monthly markout PnL vs BTC")
ax.legend(loc="upper left"); ax2.legend(loc="upper right"); ax2.grid(False)
fig.tight_layout(); fig.savefig(FIG / "04_monthly_vs_btc.png"); plt.close(fig)

per_w = e.group_by("w").agg(long_frac=(pl.col("dir") == 1).mean(),
                            bps=(pl.col("m24") / pl.col("notional")).mean() * 1e4,
                            notl=pl.col("notional").sum())
fig, ax = plt.subplots(figsize=(8, 4.5))
s = np.sqrt(per_w["notl"].to_numpy()) / 300
ax.scatter(per_w["long_frac"], per_w["bps"], s=s, alpha=0.6, color="#3b7dd8")
ax.axhline(0, color="k", lw=0.8); ax.axvline(0.5, color="k", lw=0.5, ls=":")
ax.set_xlabel("fraction of entries LONG"); ax.set_ylabel("mean 24h markout (bps)")
ax.set_title("Direction mix vs 24h markout (bubble = notional)")
fig.tight_layout(); fig.savefig(FIG / "05_direction.png"); plt.close(fig)

rc = e.group_by("coin").agg(pnl=pl.col("m24").sum()).sort("pnl", descending=True)
top_coins = rc.head(10)
fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(top_coins["coin"].to_list(), (top_coins["pnl"] / 1e6).to_list(), color="#3b7dd8")
ax.set_ylabel("$M"); ax.set_title("24h markout PnL by coin (top-50)")
fig.tight_layout(); fig.savefig(FIG / "06_coins.png"); plt.close(fig)

# ---- fig 7: example term-structure shapes -------------------------------------
curves = B[top] / np.maximum(N[top], 1)
def cls(c):
    early, mid, late = c[:3].mean(), c[5], c[7]
    if mid > 5 and late > 0.7 * mid: return "plateau"
    if early > 5 and late < 0.3 * early: return "spike"
    return "other"
fig, ax = plt.subplots(figsize=(8, 4.5))
shown = {"plateau": 0, "spike": 0, "other": 0}
for c in curves:
    k = cls(c)
    if shown[k] >= 3: continue
    shown[k] += 1
    color = {"plateau": "#2a9d2a", "spike": "#c44", "other": "#999"}[k]
    ax.plot(H, c, "-", color=color, alpha=0.7,
            label=k if shown[k] == 1 else None)
ax.axhline(0, color="k", lw=0.8); ax.set_xscale("log"); ax.set_xticks(H)
ax.set_xticklabels([f"{h}h" if h < 168 else "1wk" for h in H])
ax.set_ylabel("bps/entry"); ax.set_title("Example wallet term structures")
ax.legend()
fig.tight_layout(); fig.savefig(FIG / "07_shapes.png"); plt.close(fig)

print("figures written:", sorted(p.name for p in FIG.glob("*.png")))

# ---- fig 8: roster monthly activity (calendar months) ---------------------------
act = e.group_by("cmonth").agg(nw=pl.col("w").n_unique(), n=pl.len()).sort("cmonth")
fig, ax = plt.subplots(figsize=(8, 4))
xs8 = [_dt.datetime(int(c[:4]), int(c[5:]), 1).strftime("%b") for c in act["cmonth"].to_list()]
ax.bar(xs8, act["nw"].to_list(), color="#3b7dd8", label="active wallets (of 50)")
ax.set_ylim(0, 55); ax.axhline(50, color="k", lw=0.5, ls=":")
ax2 = ax.twinx(); ax2.plot(xs8, act["n"].to_list(), "ko--", label="entries"); ax2.grid(False)
ax.set_title("Top-50 wallets active per month")
ax.legend(loc="lower left"); ax2.legend(loc="lower right")
fig.tight_layout(); fig.savefig(FIG / "08_roster_monthly_activity.png"); plt.close(fig)

# ---- fig 9: months-active distribution, field vs top-50 -------------------------
top_w = set(np.array([r["w"] for r, k in zip(rows, elig) if k])[top])
stats_frames = [pl.read_parquet(OUT / f"stats_{m}.parquet").select("taker").unique()
                .with_columns(month=pl.lit(m)) for m in months]
pres = pl.concat(stats_frames).group_by("taker").agg(k=pl.len())
elig_w = set(np.array([r["w"] for r, k in zip(rows, elig) if k]))
pres_e = pres.filter(pl.col("taker").is_in(list(elig_w)))
fig, ax = plt.subplots(figsize=(8, 4))
ka = pres_e["k"].to_numpy()
kt = pres_e.filter(pl.col("taker").is_in(list(top_w)))["k"].to_numpy()
w_field = np.ones_like(ka) / ka.size
w_top = np.ones_like(kt) / max(kt.size, 1)
ax.hist(ka, bins=np.arange(0.5, 7.5), weights=w_field, alpha=0.6, color="#888", label="eligible field")
ax.hist(kt, bins=np.arange(0.5, 7.5), weights=w_top, alpha=0.7, color="#2a9d2a", label="top-50")
ax.set_xlabel("months with trading activity (of 6 train months)")
ax.set_ylabel("fraction of wallets")
ax.set_title("Months active: top-50 vs field")
ax.legend()
fig.tight_layout(); fig.savefig(FIG / "09_active_months_hist.png"); plt.close(fig)

# ---- fig 10: frequency and size distributions -----------------------------------
tpd_all = agg["tpd"].to_numpy(); mnot_all = agg["mean_notional"].to_numpy()
in_top = np.array([w in top_w for w in agg["taker"].to_list()])
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4))
a1.hist(np.clip(tpd_all, 0, 40), bins=60, color="#888", alpha=0.7, label="all takers")
for x in np.clip(tpd_all[in_top], 0, 40):
    a1.axvline(x, color="#2a9d2a", alpha=0.25, lw=1)
a1.axvspan(0.5, 15, color="#3b7dd8", alpha=0.08)
a1.set_yscale("log"); a1.set_xlabel("orders/day"); a1.set_title("Trade frequency")
a1.legend()
vals = np.clip(mnot_all, 10, 1e7)
a2.hist(vals, bins=np.logspace(1, 7, 60), color="#888", alpha=0.7)
for x in np.clip(mnot_all[in_top], 10, 1e7):
    a2.axvline(x, color="#2a9d2a", alpha=0.25, lw=1)
a2.axvline(500, color="#3b7dd8")
a2.set_xscale("log"); a2.set_yscale("log")
a2.set_xticks([1e2, 1e3, 1e4, 1e5, 1e6])
a2.set_xticklabels(["$100", "$1k", "$10k", "$100k", "$1M"])
a2.set_xlabel("mean order notional"); a2.set_title("Mean order size")
fig.tight_layout(); fig.savefig(FIG / "10_freq_size_dist.png"); plt.close(fig)

# ---- fig 11: per-wallet monthly PnL heatmap (calendar; inactive = grey) ----------
wmp = (e.group_by(["w", "cmonth"]).agg(pnl=pl.col("m24").sum())
       .pivot(values="pnl", index="w", on="cmonth"))
month_cols = sorted([c for c in wmp.columns if c != "w"])
M = wmp.select(month_cols).to_numpy().astype(float)          # NaN where inactive
order2 = np.argsort(-np.nansum(np.abs(M), axis=1))
M = M[order2]
S = np.sign(M) * np.log1p(np.abs(M))
fig, ax = plt.subplots(figsize=(6, 8))
vm = np.nanmax(np.abs(S))
cmap = plt.get_cmap("RdYlGn").copy(); cmap.set_bad("#cccccc")
im = ax.imshow(np.ma.masked_invalid(S), aspect="auto", cmap=cmap, vmin=-vm, vmax=vm)
ax.set_xticks(range(len(month_cols)))
ax.set_xticklabels([_dt.datetime(int(c[:4]), int(c[5:]), 1).strftime("%b") for c in month_cols])
ax.set_ylabel("top-50 wallets (sorted by |PnL|)"); ax.set_yticks([])
ax.set_title("Monthly markout PnL per wallet")
fig.colorbar(im, shrink=0.6, label="sign x log(1+|$PnL|); grey = inactive")
fig.tight_layout(); fig.savefig(FIG / "11_monthly_heatmap.png"); plt.close(fig)

print("extra figures 08-11 written")

# ---- fig 12: cohort distribution comparison (all takers vs eligible vs top-50) ----
elig_set = elig_w
def three_hist(ax, all_v, el_v, top_v, bins, xlabel, logx=False):
    for v, c, lab, a in ((all_v, "#999", "all takers", .55),
                         (el_v, "#3b7dd8", "eligible", .55),
                         (top_v, "#2a9d2a", "top-50", .75)):
        v = np.asarray(v, dtype=float)
        v = v[np.isfinite(v)]
        w = np.ones_like(v) / max(v.size, 1)
        ax.hist(v, bins=bins, weights=w, alpha=a, color=c, label=lab)
    if logx: ax.set_xscale("log")
    ax.set_xlabel(xlabel)
el_mask = np.array([w in elig_set for w in agg["taker"].to_list()])
tp_mask = np.array([w in top_w for w in agg["taker"].to_list()])
fig, axes = plt.subplots(2, 3, figsize=(13, 7))
a = axes.ravel()
no = agg["n_orders"].to_numpy(); dy = agg["days"].to_numpy()
tp = agg["tpd"].to_numpy(); mv = agg["mean_notional"].to_numpy()
three_hist(a[0], no, no[el_mask], no[tp_mask], np.logspace(0, 5, 40), "total taker orders", logx=True)
three_hist(a[1], dy, dy[el_mask], dy[tp_mask], np.arange(0, 190, 6), "active days")
three_hist(a[2], np.clip(tp, 0, 40), np.clip(tp[el_mask], 0, 40), np.clip(tp[tp_mask], 0, 40),
           np.arange(0, 41, 1), "orders/day")
three_hist(a[3], np.clip(mv, 1, 1e7), np.clip(mv[el_mask], 1, 1e7), np.clip(mv[tp_mask], 1, 1e7),
           np.logspace(0, 7, 40), "mean order notional ($)", logx=True)
pres_all = pres["k"].to_numpy()
pres_top = pres.filter(pl.col("taker").is_in(list(top_w)))["k"].to_numpy()
three_hist(a[4], pres_all, pres_e["k"].to_numpy(), pres_top, np.arange(0.5, len(months)+1.5), f"months active (of {len(months)})")
# per-wallet 24h skill: eligible vs top-50 (not computable for all takers)
a[5].hist(np.clip(wb, -250, 250), bins=60, weights=np.ones_like(wb)/wb.size,
          alpha=0.6, color="#3b7dd8", label="eligible")
a[5].hist(np.clip(wb[top], -250, 250), bins=30, weights=np.ones_like(wb[top])/wb[top].size,
          alpha=0.75, color="#2a9d2a", label="top-50")
a[5].axvline(0, color="k", lw=0.8); a[5].set_xlabel("mean 24h markout (bps/entry, clipped at ±250)")
for ax_ in a: ax_.legend(fontsize=7)
fig.suptitle("Cohort distributions", y=1.0)
fig.tight_layout(); fig.savefig(FIG / "12_cohort_dists.png"); plt.close(fig)
print("fig 12 written")
