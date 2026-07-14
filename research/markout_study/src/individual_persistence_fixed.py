"""
FIXED wallet OOS-persistence rebuild (supersedes individual_persistence.py; see FINDINGS_LEDGER 2026-07-11).

The old per_close() avg-cost ledger had two confirmed bugs: (1) it seeded position=0 at the tape start,
ignoring each wallet's true pre-tape `start_position` (carry-in warm-start) — corrupting ~15-20% of wallets and
producing physically-impossible te_vw (-2042bp/+1073bp); (2) it mis-handled zhash TWAP sub-fills. Both are avoided
here by NOT reconstructing an avg-cost ledger at all: we use Hyperliquid's OWN authoritative per-fill `closed_pnl`
from the restored node_fills tape (data/raw/fills), which is computed on the wallet's TRUE running position (pre-tape
carry included). Validated: sum(closed_pnl) for 0xb28c HYPE test = +$128,542, matching HL vs the buggy ledger's -$5.36M.

Estimand (unchanged in spirit): per closing fill, realized copy-return in bps of the CLOSED notional.
  closed_notional = min(|sz|, |start_position|) * px   (exact closed portion; start_position is pre-fill position)
  bps            = closed_pnl / closed_notional * 1e4
Aggregated per wallet per window (TRAIN ts<Feb1 2026 / TEST ts>=Mar1 2026), for ALL fills and TAKER-only (crossed).

Crash-safe: POLARS_MAX_THREADS capped, streamed + month-batched (never loads the full ~1.1B-row tape at once).
Output: out/individual_persistence_fixed.parquet + printed comparison to the old -0.102 / -30.9bp numbers.
"""
import os
os.environ.setdefault("POLARS_MAX_THREADS", "4")  # avoid core oversubscription (crash guard)
import glob
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
FILLS = str(ROOT / "data/raw/fills/month=*/day=*/hour*.parquet")
OUT = Path(__file__).resolve().parents[1] / "out"
COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = ms(2026, 2, 1); TEST_LO = ms(2026, 3, 1)
MIN_TRAIN_FILLS = 2000
MIN_CLOSES = 20


def month_globs():
    months = sorted({p.split("month=")[1].split("/")[0]
                     for p in glob.glob(str(ROOT / "data/raw/fills/month=*/day=*/hour*.parquet"))})
    return [(m, str(ROOT / f"data/raw/fills/month={m}/day=*/hour*.parquet")) for m in months]


def universe(mglobs):
    """wallets with >= MIN_TRAIN_FILLS majors fills before TRAIN_HI (matches the old universe definition)."""
    acc = None
    for m, g in mglobs:
        if m > "202602":
            continue  # train window ends Feb 1; no later month can contribute
        part = (pl.scan_parquet(g).filter(pl.col("ts") < TRAIN_HI)
                .group_by("wallet").agg(n=pl.len()).collect(engine="streaming"))
        acc = part if acc is None else (pl.concat([acc, part]).group_by("wallet").agg(n=pl.col("n").sum()))
        print(f"  universe scan {m}: running wallets={acc.height}", flush=True)
    uni = acc.filter(pl.col("n") >= MIN_TRAIN_FILLS)
    return set(uni["wallet"].to_list())


def window_expr():
    return (pl.when(pl.col("ts") < TRAIN_HI).then(pl.lit("tr"))
            .when(pl.col("ts") >= TEST_LO).then(pl.lit("te"))
            .otherwise(pl.lit("gap")).alias("win"))


def partial_stats(g, uni):
    """per-month partial sufficient stats per (wallet, win) for ALL and TAKER closes."""
    lf = (pl.scan_parquet(g)
          .filter(pl.col("wallet").is_in(uni))
          .with_columns(pl.col("closed_pnl").cast(pl.Float64),
                        pl.col("sz").cast(pl.Float64), pl.col("px").cast(pl.Float64),
                        pl.col("start_position").cast(pl.Float64))
          .filter(pl.col("closed_pnl") != 0.0)
          .with_columns((pl.min_horizontal(pl.col("sz").abs(), pl.col("start_position").abs()) * pl.col("px"))
                        .alias("cn"))
          .filter(pl.col("cn") > 0)
          .with_columns((pl.col("closed_pnl") / pl.col("cn") * BP).alias("bps"), window_expr()))
    def agg(over):
        return (over.group_by(["wallet", "win"]).agg(
            n=pl.len(), spnl=pl.col("closed_pnl").sum(), scn=pl.col("cn").sum(),
            sb=pl.col("bps").sum(), sb2=(pl.col("bps") ** 2).sum()))
    allc = agg(lf).with_columns(pl.lit("all").alias("kind"))
    takc = agg(lf.filter(pl.col("crossed"))).with_columns(pl.lit("tak").alias("kind"))
    return pl.concat([allc, takc]).collect(engine="streaming")


def combine(parts):
    return (pl.concat(parts).group_by(["wallet", "win", "kind"])
            .agg(n=pl.col("n").sum(), spnl=pl.col("spnl").sum(), scn=pl.col("scn").sum(),
                 sb=pl.col("sb").sum(), sb2=pl.col("sb2").sum()))


def to_table(comb):
    """pivot (wallet,win,kind) sufficient stats -> one row/wallet with tr_*/te_* for all & taker."""
    comb = comb.with_columns(
        vw=(pl.col("spnl") / pl.col("scn") * BP),
        mean=(pl.col("sb") / pl.col("n")),
        var=((pl.col("sb2") / pl.col("n")) - (pl.col("sb") / pl.col("n")) ** 2))
    comb = comb.with_columns(
        t=pl.when(pl.col("n") > 1)
        .then(pl.col("mean") / ((pl.col("var") * pl.col("n") / (pl.col("n") - 1)).sqrt() / pl.col("n").sqrt()))
        .otherwise(0.0))
    rows = {}
    for r in comb.iter_rows(named=True):
        d = rows.setdefault(r["wallet"], {})
        pre = f'{r["win"]}_{r["kind"]}'  # e.g. tr_all, te_tak
        d[f"{pre}_n"] = r["n"]; d[f"{pre}_vw"] = r["vw"]; d[f"{pre}_bps"] = r["mean"]; d[f"{pre}_t"] = r["t"]
    out = []
    for w, d in rows.items():
        if d.get("tr_all_n", 0) >= MIN_CLOSES and d.get("te_all_n", 0) >= MIN_CLOSES:
            out.append({"wallet": w, **d})
    return pl.DataFrame(out)


def spearman(a, b):
    try:
        from scipy.stats import spearmanr
        return float(spearmanr(a, b).correlation)
    except Exception:
        ar = np.argsort(np.argsort(a)); br = np.argsort(np.argsort(b))
        return float(np.corrcoef(ar, br)[0, 1])


def boot_ci(x, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    bs = np.array([rng.choice(x, x.size).mean() for _ in range(n)])
    return x.mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def main():
    mglobs = month_globs()
    print(f"months: {[m for m, _ in mglobs]}", flush=True)
    print("PASS 1 — universe (>=2000 train majors fills):", flush=True)
    uni = universe(mglobs)
    print(f"  universe size: {len(uni)}", flush=True)
    print("PASS 2 — closed_pnl sufficient stats (month-batched):", flush=True)
    parts = []
    for m, g in mglobs:
        parts.append(partial_stats(g, uni))
        print(f"  stats {m} done", flush=True)
    R = to_table(combine(parts))
    OUT.mkdir(exist_ok=True)
    R.write_parquet(OUT / "individual_persistence_fixed.parquet")
    print(f"\nwallets with >=20 closes both windows: {R.height}", flush=True)

    # ---- headline comparison to the OLD buggy numbers ----
    trv, tev = R["tr_all_vw"].to_numpy(), R["te_all_vw"].to_numpy()
    print(f"\n[ALL-fills]  Spearman(tr_vw, te_vw) = {spearman(trv, tev):+.3f}  (N={R.height})   [old buggy: -0.102]")
    if "tr_tak_vw" in R.columns:
        m = R.filter(pl.col("tr_tak_n").fill_null(0) >= MIN_CLOSES).filter(pl.col("te_tak_n").fill_null(0) >= MIN_CLOSES)
        print(f"[TAKER-only] Spearman(tr_vw, te_vw) = {spearman(m['tr_tak_vw'].to_numpy(), m['te_tak_vw'].to_numpy()):+.3f}  (N={m.height})")

    print(f"\n{'train selector':30s} {'#':>5s} {'test vw-bps':>11s} {'%te>0':>7s}")
    def rep(mask, lab):
        s = R.filter(mask)
        if s.height < 5: print(f"  {lab:28s} {s.height:>5d}  (few)"); return
        tv = s["te_all_vw"].to_numpy()
        print(f"  {lab:28s} {s.height:>5d} {np.mean(tv):>+10.2f} {100*np.mean(tv>0):>6.0f}%")
    rep(pl.col("tr_all_n") > 0, "ALL high-N wallets")
    rep(pl.col("tr_all_vw") > 0, "train profitable (vw>0)")
    rep(pl.col("tr_all_t") >= 2, "train t>=2")
    rep(pl.col("tr_all_t") >= 3, "train t>=3 (tight)")
    rep(pl.col("tr_all_t") >= 4, "train t>=4")

    win = R.filter(pl.col("tr_all_t") >= 3)
    if win.height >= 5:
        mu, lo, hi = boot_ci(win["te_all_vw"].to_numpy())
        print(f"\n  train-t>=3 winners OOS vw-bps: {mu:+.2f}  95%CI [{lo:+.2f}, {hi:+.2f}]  (n={win.height})   [old buggy: -30.9 [-72.9,+10.3]]")
    # taker-only winners cohort (the copyable actionable number)
    if "tr_tak_t" in R.columns:
        wt = R.filter((pl.col("tr_tak_t").fill_null(-9) >= 3) & (pl.col("te_tak_n").fill_null(0) >= MIN_CLOSES))
        if wt.height >= 5:
            mu, lo, hi = boot_ci(wt["te_tak_vw"].to_numpy())
            print(f"  TAKER train-t>=3 winners OOS vw-bps: {mu:+.2f}  95%CI [{lo:+.2f}, {hi:+.2f}]  (n={wt.height})")

    print("\nTop 15 by TRAIN t (all-fills):")
    with pl.Config(tbl_rows=20, fmt_str_lengths=12):
        print(R.sort("tr_all_t", descending=True).head(15).select(
            pl.col("wallet").str.slice(0, 10), "tr_all_n", pl.col("tr_all_vw").round(1),
            pl.col("tr_all_t").round(1), "te_all_n", pl.col("te_all_vw").round(1), pl.col("te_all_t").round(1)))


if __name__ == "__main__":
    main()
