"""
COIN VENUE-LEADERSHIP CLASSIFIER (the "does HL lead or follow Binance?" axis).

Hypothesis under test: a wallet's directional edge is real, copyable venue-specific alpha on coins where
HYPERLIQUID *leads* price discovery, but only lagged beta-to-Binance (uncopyable) on coins where HL follows.
Our whole study capped at BTC/ETH/SOL/HYPE = 3 Binance-led coins + 1 HL-native (HYPE) that we kept *dropping*.

We need NO Binance data: HL publishes `oracle_px` (median of external CEX spot prices, i.e. ~Binance) AND its
own traded `mark_px`. Lead-lag between them IS the venue-leadership signal:
  lead_corr  = corr(r_mark[t-1], r_oracle[t])   # HL move predicts next oracle move -> HL LEADS
  follow_corr= corr(r_oracle[t-1], r_mark[t])   # oracle predicts next HL move       -> HL FOLLOWS
  lead_score = lead_corr - follow_corr          # > 0 => HL leads price discovery

RAM-safe: streams ONE day-file at a time (never the fills tape, never the whole ctx), accumulating per-coin
sufficient statistics (n, sums, sums-of-squares, cross-sums) for each correlation; within-day returns only
(drops ~1 cross-midnight minute/day, negligible). Output: out/coin_venue_class.parquet + printed buckets.
Descriptive scaffolding only; makes NO edge claim by itself.
"""
import glob
from collections import defaultdict
from pathlib import Path
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
CTX_GLOB = str(ROOT / "data/raw/asset_ctx/month=*/day=*/ctx.parquet")
OUT = Path(__file__).resolve().parents[1] / "out"
BP = 1e4
SAMPLE_MONTHS = ["202510", "202512", "202602"]   # light 3-month sample; classification is robust to it
KNOWN_BINANCE = {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "LTC", "BCH", "DOT",
                 "TRX", "NEAR", "APT", "ARB", "OP", "SUI", "ATOM", "FIL", "INJ", "TIA", "SEI"}
HL_NATIVE_HINT = {"HYPE", "PURR"}


class Acc:
    """Streaming sufficient stats for corr(x,y): n, Sx, Sy, Sxx, Syy, Sxy."""
    __slots__ = ("n", "sx", "sy", "sxx", "syy", "sxy")
    def __init__(self):
        self.n = self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0
    def push(self, x, y):
        g = np.isfinite(x) & np.isfinite(y)
        x, y = x[g], y[g]
        if x.size == 0:
            return
        self.n += x.size; self.sx += x.sum(); self.sy += y.sum()
        self.sxx += (x * x).sum(); self.syy += (y * y).sum(); self.sxy += (x * y).sum()
    def corr(self):
        n = self.n
        if n < 200:
            return np.nan
        cov = self.sxy - self.sx * self.sy / n
        vx = self.sxx - self.sx * self.sx / n
        vy = self.syy - self.sy * self.sy / n
        if vx <= 0 or vy <= 0:
            return np.nan
        return float(cov / np.sqrt(vx * vy))


def main():
    files = sorted(f for f in glob.glob(CTX_GLOB) if any(f"month={mm}" in f for mm in SAMPLE_MONTHS))
    print(f"asset_ctx day-files (months {SAMPLE_MONTHS}): {len(files)}")
    lead = defaultdict(Acc); follow = defaultdict(Acc); contemp = defaultdict(Acc)
    meta = defaultdict(lambda: dict(n=0, oi=0.0, vlm=0.0, prem_sq=0.0, prem_n=0))

    for k, f in enumerate(files):
        df = (pl.read_parquet(f, columns=["ts", "coin", "oracle_px", "mark_px",
                                          "open_interest", "day_ntl_vlm", "premium"])
              .sort(["coin", "ts"]))
        for (coin,), g in df.group_by(["coin"], maintain_order=True):
            o = g["oracle_px"].to_numpy().astype(float)
            m = g["mark_px"].to_numpy().astype(float)
            if o.size < 30:
                continue
            with np.errstate(all="ignore"):
                r_o = np.diff(np.log(o)); r_m = np.diff(np.log(m))
            contemp[coin].push(r_m, r_o)
            if r_o.size >= 2:
                lead[coin].push(r_m[:-1], r_o[1:])      # HL(t-1) -> oracle(t)
                follow[coin].push(r_o[:-1], r_m[1:])    # oracle(t-1) -> HL(t)
            md = meta[coin]; md["n"] += o.size
            md["oi"] += float(np.nansum(g["open_interest"].to_numpy().astype(float) * m))
            md["vlm"] += float(np.nansum(g["day_ntl_vlm"].to_numpy().astype(float)))
            pr = g["premium"].to_numpy().astype(float); pr = pr[np.isfinite(pr)]
            md["prem_sq"] += float((pr * pr).sum()); md["prem_n"] += pr.size
        if (k + 1) % 20 == 0:
            print(f"  {k+1}/{len(files)} day-files")

    rows = []
    for coin, md in meta.items():
        lc, fc, cc = lead[coin].corr(), follow[coin].corr(), contemp[coin].corr()
        rows.append(dict(
            coin=coin, n_min=md["n"], lead_corr=lc, follow_corr=fc,
            lead_score=(lc - fc) if (np.isfinite(lc) and np.isfinite(fc)) else np.nan,
            contemp=cc, mean_oi_usd=md["oi"] / max(md["n"], 1),
            mean_day_vlm_usd=md["vlm"] / max(md["n"], 1),
            premium_bp_std=(np.sqrt(md["prem_sq"] / md["prem_n"]) * BP) if md["prem_n"] else np.nan))
    R = pl.DataFrame(rows).sort("lead_score", descending=True, nulls_last=True)
    OUT.mkdir(exist_ok=True)
    R.write_parquet(OUT / "coin_venue_class.parquet")
    print(f"\nwrote {R.height} coins -> out/coin_venue_class.parquet\n")

    liq = R.filter(pl.col("mean_day_vlm_usd") > 1e6)  # only rank coins with >$1M/day HL volume
    print(f"liquid coins (>$1M/day): {liq.height}")
    print("\n=== TOP 20 HL-LEADS (lead_score high, liquid) ===")
    with pl.Config(tbl_rows=20):
        print(liq.head(20).select("coin", "lead_score", "lead_corr", "follow_corr", "contemp",
                                  "mean_day_vlm_usd", "mean_oi_usd", "premium_bp_std"))
        print("\n=== BOTTOM 15 (BINANCE-LED: oracle leads HL) ===")
        print(liq.tail(15).select("coin", "lead_score", "lead_corr", "follow_corr", "contemp", "mean_day_vlm_usd"))
    print("\n=== our 4 study majors ===")
    print(R.filter(pl.col("coin").is_in(["BTC", "ETH", "SOL", "HYPE"]))
          .select("coin", "lead_score", "lead_corr", "follow_corr", "contemp", "mean_day_vlm_usd"))
    print("\n=== sanity: HL-native hints vs known-Binance ===")
    for name, s in [("HL_NATIVE_HINT", HL_NATIVE_HINT), ("KNOWN_BINANCE", KNOWN_BINANCE)]:
        sub = R.filter(pl.col("coin").is_in(list(s)))
        if sub.height:
            print(f"  {name}: n={sub.height} mean lead_score={sub['lead_score'].mean():.4f} "
                  f"median={sub['lead_score'].median():.4f}")


if __name__ == "__main__":
    main()
