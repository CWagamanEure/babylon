"""
Wallet forensics for 0x95995f30... and 0xff4cd382...  (task: maker/taker share, coin mix,
holding times, cross-coin hedging, and whether the majors-only avg-cost measure mismeasures them).
RAM-careful: scan + filter to target wallets per monthly file, collect small, concat.
"""
import glob
import numpy as np
import polars as pl

TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
TARGETS = [
    "0x95995f302ad58138d791ce49f9f3b1274e80c60a",
    "0xff4cd3826ecee12acd4329aada4a2d3419fc463c",
]
MAJORS = {"BTC", "ETH", "SOL", "HYPE"}
BP = 1e4


def load_wallet(w):
    parts = []
    for f in TAPE:
        d = (pl.scan_parquet(f)
             .filter(pl.col("wallet") == w)
             .select("ts", "tid", "coin", "px", "sz", "crossed", "zhash")
             .collect())
        if d.height:
            parts.append(d)
    if not parts:
        return pl.DataFrame()
    return pl.concat(parts).sort(["ts", "tid"])


def per_close_full(px, sz, ts, crossed, zhash):
    """avg-cost ledger over ALL fills (maker+taker, incl wash) -> list of
    (ts, realized_usd, closed_notional, is_close_taker, is_close_wash, hold_ms, open_ts)."""
    q = avg = 0.0
    open_ts = None
    out = []
    for p, s, t, cr, zh in zip(px, sz, ts, crossed, zhash):
        if q == 0.0:
            open_ts = t
        if q == 0.0 or (s > 0) == (q > 0):
            avg = (avg * abs(q) + p * abs(s)) / (abs(q) + abs(s))
            q += s
        else:
            c = min(abs(s), abs(q))
            hold = (t - open_ts) if open_ts is not None else None
            out.append((t, c * (p - avg) * (1.0 if q > 0 else -1.0), c * p, bool(cr), bool(zh), hold))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0:
                avg = p
                open_ts = t
            q = nq
            if abs(q) < 1e-12:
                q = 0.0
                avg = 0.0
                open_ts = None
    return out


def analyze(w):
    print(f"\n{'='*90}\nWALLET {w}\n{'='*90}")
    df = load_wallet(w)
    if df.height == 0:
        print("NO FILLS FOUND"); return
    n = df.height
    print(f"total fills (all coins, all 11 months): {n}")

    # --- coin mix / notional share ---
    notl = (df.with_columns((pl.col("px") * pl.col("sz").abs()).alias("notl"))
            .group_by("coin").agg(notl=pl.col("notl").sum(), n=pl.len())
            .sort("notl", descending=True))
    total_notl = notl["notl"].sum()
    majors_notl = notl.filter(pl.col("coin").is_in(MAJORS))["notl"].sum()
    print(f"distinct coins traded: {notl.height}")
    print(f"total notional: ${total_notl:,.0f}   majors notional share: {majors_notl/total_notl:.3f}")
    print("top 10 coins by notional:")
    with pl.Config(tbl_rows=10):
        print(notl.with_columns((pl.col("notl")/total_notl*100).round(2).alias("pct")).head(10))

    # --- size-weighted taker share overall ---
    taker_notl = (df.filter(pl.col("crossed"))
                  .select((pl.col("px")*pl.col("sz").abs()).sum()).item())
    print(f"\noverall size-weighted TAKER share (crossed=true): {taker_notl/total_notl:.4f}")
    zhash_notl = (df.filter(pl.col("zhash"))
                  .select((pl.col("px")*pl.col("sz").abs()).sum()).item())
    print(f"overall size-weighted ZHASH(wash) share: {zhash_notl/total_notl:.4f}")

    # --- per-coin avg-cost ledger: closing fills, taker share on CLOSES, hold time ---
    all_closes = []
    for coin, g in df.group_by("coin", maintain_order=False):
        g = g.sort(["ts", "tid"])
        recs = per_close_full(g["px"].to_numpy(), g["sz"].to_numpy(), g["ts"].to_numpy(),
                               g["crossed"].to_numpy(), g["zhash"].to_numpy())
        for t, r, cn, cr, zh, hold in recs:
            all_closes.append((coin[0] if isinstance(coin, tuple) else coin, t, r, cn, cr, zh, hold))

    C = pl.DataFrame(all_closes, schema=["coin", "ts", "realized", "notl", "taker", "wash", "hold_ms"],
                      orient="row")
    print(f"\ntotal closing events (all coins): {C.height}")
    close_notl = C["notl"].sum()
    taker_close_notl = C.filter(pl.col("taker"))["notl"].sum()
    wash_close_notl = C.filter(pl.col("wash"))["notl"].sum()
    print(f"size-weighted TAKER share ON CLOSING fills: {taker_close_notl/close_notl:.4f}")
    print(f"size-weighted WASH share ON CLOSING fills: {wash_close_notl/close_notl:.4f}")

    hold = C["hold_ms"].drop_nulls().to_numpy()
    if hold.size:
        print(f"holding time (ms) over all closes: median={np.median(hold):.0f} "
              f"({np.median(hold)/1000:.1f}s)  p10={np.percentile(hold,10):.0f}  "
              f"p90={np.percentile(hold,90):.0f} ({np.percentile(hold,90)/1000/60:.1f}min) "
              f"mean={hold.mean():.0f}")

    # realized PnL, ALL coins, both eqw and vw, excluding wash
    Cnw = C.filter(~pl.col("wash"))
    if Cnw.height >= 20:
        bps = (Cnw["realized"] / Cnw["notl"] * BP).to_numpy()
        vw = Cnw["realized"].sum() / Cnw["notl"].sum() * BP
        print(f"\nALL-COIN realized closes (ex-wash), n={Cnw.height}: eqw_bps_mean={bps.mean():+.2f} "
              f"t={bps.mean()/(bps.std()/np.sqrt(bps.size)):+.2f}  vw_bps={vw:+.2f}  "
              f"total realized $={Cnw['realized'].sum():,.0f}")
    Cw = C.filter(pl.col("wash"))
    if Cw.height:
        bpsw = (Cw["realized"] / Cw["notl"] * BP).to_numpy()
        print(f"WASH-flagged closes: n={Cw.height}  vw_bps={Cw['realized'].sum()/Cw['notl'].sum()*BP:+.2f}  "
              f"total realized $={Cw['realized'].sum():,.0f}  (excluded above)")

    # majors-only, matching study methodology (all fills incl maker, EXCLUDING wash check)
    Cm = C.filter(pl.col("coin").is_in(MAJORS))
    Cm_nw = Cm.filter(~pl.col("wash"))
    if Cm_nw.height >= 20:
        bps = (Cm_nw["realized"] / Cm_nw["notl"] * BP).to_numpy()
        vw = Cm_nw["realized"].sum() / Cm_nw["notl"].sum() * BP
        print(f"\nMAJORS-ONLY realized closes (ex-wash), n={Cm_nw.height}: eqw_bps={bps.mean():+.2f}  "
              f"vw_bps={vw:+.2f}  total realized $={Cm_nw['realized'].sum():,.0f}")
    Cm_w = Cm.filter(pl.col("wash"))
    if Cm_w.height:
        print(f"MAJORS wash-flagged closes: n={Cm_w.height}  "
              f"total realized $={Cm_w['realized'].sum():,.0f}  "
              f"vw_bps={Cm_w['realized'].sum()/Cm_w['notl'].sum()*BP:+.2f}")

    # total realized $ across ALL coins (the "are they actually profitable" question)
    total_realized_all = C["realized"].sum()
    total_realized_ex_wash = Cnw["realized"].sum()
    print(f"\n>>> TOTAL REALIZED $ (all coins, incl wash): ${total_realized_all:,.0f}")
    print(f">>> TOTAL REALIZED $ (all coins, ex-wash):    ${total_realized_ex_wash:,.0f}")

    # --- cross-coin hedge check: at any ts, net notional exposure across coins vs gross ---
    # build per-coin running position snapshots at fill times, sample overlap
    # Simplify: for each coin compute total signed notional traded (buy volume - sell volume)
    # and check if wallet holds simultaneous opposite-direction inventories across coins.
    # Use position sign at last fill per (coin, minute) bucket, then check same-timestamp cross-coin sign spread.
    df2 = df.with_columns((pl.col("ts") // 60000).alias("min_bucket"))
    pos = (df2.sort(["coin", "ts"])
           .with_columns(pl.col("sz").cum_sum().over("coin").alias("cum_pos")))
    # snapshot at end of each minute bucket per coin
    snap = (pos.group_by(["coin", "min_bucket"]).agg(pos=pl.col("cum_pos").last())
            .sort(["coin", "min_bucket"]))
    # pivot: for each min_bucket, how many coins have nonzero exposure, and sign diversity
    wide = snap.filter(pl.col("pos").abs() > 1e-9)
    per_bucket = wide.group_by("min_bucket").agg(
        n_coins_open=pl.len(),
        n_long=(pl.col("pos") > 0).sum(),
        n_short=(pl.col("pos") < 0).sum(),
    )
    multi = per_bucket.filter(pl.col("n_coins_open") >= 2)
    both_sides = multi.filter((pl.col("n_long") > 0) & (pl.col("n_short") > 0))
    print(f"\nminute-buckets with >=2 coins simultaneously open: {multi.height} / {per_bucket.height} total buckets")
    if multi.height:
        print(f"  of those, buckets with BOTH long AND short legs open across coins (hedge-like): "
              f"{both_sides.height} ({100*both_sides.height/multi.height:.1f}%)")
    print(f"max coins simultaneously open in one minute bucket: {per_bucket['n_coins_open'].max()}")

    return C


for w in TARGETS:
    analyze(w)
