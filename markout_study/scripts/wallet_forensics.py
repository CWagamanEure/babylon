"""
Wallet forensics for 2 persistent-winner wallets, full cross-coin book.
Memory-safe: scan_parquet + filter to wallet, one month at a time, concat small results.
"""
import glob
from datetime import datetime, timezone
import numpy as np
import polars as pl

TAPE = sorted(glob.glob("../scratch_conv/mlscreen/cand2_*.parquet"))
MAJORS = ["BTC", "ETH", "SOL", "HYPE"]
BP = 1e4

WALLETS = [
    "0x0ddf9bae2af4b874b96d287a5ad42eb47138a902",
    "0x5fffee2555a15899ad656c1a80f1b35cd0b2c0c1",
]


def load_wallet(wal):
    frames = []
    for f in TAPE:
        df = (pl.scan_parquet(f)
              .filter(pl.col("wallet") == wal)
              .select("ts", "tid", "coin", "px", "sz", "crossed", "zhash")
              .collect())
        if df.height:
            frames.append(df)
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames).sort(["ts", "tid"])


def per_close_full(px, sz, ts, crossed):
    """avg-cost ledger, per coin already. Returns list of dict per closing event incl whether close fill is taker."""
    q = avg = 0.0
    out = []
    for p, s, t, cr in zip(px, sz, ts, crossed):
        if q == 0.0 or (s > 0) == (q > 0):
            avg = (avg * abs(q) + p * abs(s)) / (abs(q) + abs(s))
            q += s
        else:
            c = min(abs(s), abs(q))
            realized = c * (p - avg) * (1.0 if q > 0 else -1.0)
            out.append((t, realized, c * p, cr))
            nq = q + s
            if (nq > 0) != (q > 0) and nq != 0.0:
                avg = p
            q = nq
            if abs(q) < 1e-12:
                q = 0.0
                avg = 0.0
    return out


def analyze(wal):
    print(f"\n{'='*90}\nWALLET {wal}\n{'='*90}")
    df = load_wallet(wal)
    if df.height == 0:
        print("NO DATA")
        return
    n = df.height
    print(f"total fills across full tape (all coins, all 11 months): {n}")

    coins = df["coin"].unique().to_list()
    print(f"distinct coins traded: {len(coins)}")

    # notional per fill
    df = df.with_columns((pl.col("px") * pl.col("sz").abs()).alias("notl"))
    tot_notl = df["notl"].sum()
    by_coin = (df.group_by("coin").agg(notl=pl.col("notl").sum(), n=pl.len())
               .sort("notl", descending=True))
    print("\nTop 10 coins by notional:")
    with pl.Config(tbl_rows=12):
        print(by_coin.head(10).with_columns((pl.col("notl") / tot_notl * 100).round(2).alias("pct_notl")))

    majors_notl = by_coin.filter(pl.col("coin").is_in(MAJORS))["notl"].sum()
    majors_share = majors_notl / tot_notl
    print(f"\nMAJORS (BTC/ETH/SOL/HYPE) notional share: {majors_share*100:.2f}%   (n coins total = {len(coins)})")

    # taker share overall (size-weighted by notional)
    taker_notl = df.filter(pl.col("crossed"))["notl"].sum()
    taker_share_all = taker_notl / tot_notl
    print(f"overall size-weighted TAKER share (crossed=true): {taker_share_all*100:.2f}%")

    # per-coin ledger reconstruction (full book) to find closing fills + holding time + taker share on closes
    all_closes = []
    hold_times = []
    for coin, g in df.group_by("coin", maintain_order=True):
        g = g.sort(["ts", "tid"])
        px = g["px"].to_numpy(); sz = g["sz"].to_numpy(); ts = g["ts"].to_numpy(); cr = g["crossed"].to_numpy()
        # track open time to compute holding time: redo ledger tracking open ts per lot (simple approx:
        # use "time position was last opened from flat" -> time of this close for round trips starting flat)
        q = 0.0
        open_ts = None
        for p, s, t, crf in zip(px, sz, ts, cr):
            if q == 0.0:
                open_ts = t
            if q == 0.0 or (s > 0) == (q > 0):
                q += s
            else:
                c = min(abs(s), abs(q))
                realized = c * (p - 0) * 0  # placeholder, real realized computed in per_close_full below
                nq = q + s
                if open_ts is not None:
                    hold_times.append(t - open_ts)
                q = nq
                if abs(q) < 1e-12:
                    q = 0.0
                else:
                    open_ts = t  # partial reduces reset ref point roughly (approx)
        closes = per_close_full(px, sz, ts, cr)
        for c in closes:
            all_closes.append((coin[0] if isinstance(coin, tuple) else coin, *c))

    cdf = pl.DataFrame(all_closes, schema=["coin", "ts", "realized", "notl", "close_is_taker"], orient="row")
    cdf = cdf.with_columns(pl.col("close_is_taker").cast(pl.Boolean))
    print(f"\ntotal closing events (all coins): {cdf.height}")
    if cdf.height:
        vw_all = cdf["realized"].sum() / cdf["notl"].sum() * BP
        eqw_all = (cdf["realized"] / cdf["notl"] * BP).mean()
        print(f"FULL-BOOK (all {len(coins)} coins) realized: vw_bps={vw_all:+.2f}  eqw_bps={eqw_all:+.2f}  total realized $={cdf['realized'].sum():,.0f}")

        maj = cdf.filter(pl.col("coin").is_in(MAJORS))
        if maj.height:
            vw_m = maj["realized"].sum() / maj["notl"].sum() * BP
            eqw_m = (maj["realized"] / maj["notl"] * BP).mean()
            print(f"MAJORS-ONLY  ({maj.height} closes) realized: vw_bps={vw_m:+.2f}  eqw_bps={eqw_m:+.2f}  total realized $={maj['realized'].sum():,.0f}")

        alt = cdf.filter(~pl.col("coin").is_in(MAJORS))
        if alt.height:
            vw_a = alt["realized"].sum() / alt["notl"].sum() * BP
            eqw_a = (alt["realized"] / alt["notl"] * BP).mean()
            print(f"ALTS-ONLY    ({alt.height} closes) realized: vw_bps={vw_a:+.2f}  eqw_bps={eqw_a:+.2f}  total realized $={alt['realized'].sum():,.0f}")

        # taker share ON CLOSING fills (size-weighted)
        taker_close_notl = cdf.filter(pl.col("close_is_taker"))["notl"].sum()
        taker_close_share = taker_close_notl / cdf["notl"].sum()
        print(f"\nsize-weighted TAKER share on CLOSING fills: {taker_close_share*100:.2f}%")

        # biggest single closes (realized $) -- look for outliers driving vw
        print("\nTop 5 largest-|realized$| closing events (full book):")
        top_c = cdf.sort(pl.col("realized").abs(), descending=True).head(5)
        with pl.Config(tbl_rows=8):
            print(top_c)

    if hold_times:
        ht = np.array(hold_times) / 60000.0  # minutes
        print(f"\nholding time (approx, ms between position-open and a reducing/closing fill), n={ht.size}:")
        print(f"  median={np.median(ht):.2f} min  p25={np.percentile(ht,25):.2f}  p75={np.percentile(ht,75):.2f}  mean={ht.mean():.2f}")

    # simultaneous cross-coin offsetting check: for each 1-minute bucket, is wallet long some coins & short others
    # in similar $ notional (hedge behavior)? Look at net signed notional by coin per hour.
    df2 = df.with_columns((pl.col("sz") * pl.col("px")).alias("signed_notl"),
                           (pl.col("ts") // 3_600_000 * 3_600_000).alias("hour"))
    hourly = df2.group_by(["hour", "coin"]).agg(net=pl.col("signed_notl").sum()).sort("hour")
    # for each hour compute sum(net) vs sum(|net|) across coins traded that hour -> low ratio = offsetting
    agg = hourly.group_by("hour").agg(net_sum=pl.col("net").sum(), abs_sum=pl.col("net").abs().sum(), ncoins=pl.len())
    agg = agg.filter(pl.col("ncoins") >= 2)
    if agg.height:
        agg = agg.with_columns((pl.col("net_sum").abs() / pl.col("abs_sum")).alias("directional_ratio"))
        print(f"\nHours with >=2 coins traded: {agg.height}")
        print(f"  median |net exposure| / |gross exposure| across coins in same hour: {agg['directional_ratio'].median():.3f}")
        print(f"  (near 0 = strongly offsetting/hedged; near 1 = same-direction across coins)")


if __name__ == "__main__":
    for w in WALLETS:
        analyze(w)
