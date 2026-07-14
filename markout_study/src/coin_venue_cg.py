"""
COIN VENUE-DOMINANCE via CoinGecko (ground-truth "does HL or Binance lead this coin?").

Replaces the confounded 1-min oracle lead-lag (coin_venue_class.py) with real cross-venue perp volume share.
The user's axis: HL_share = HL_perp_vol / (HL + peer-venue perp_vol). High => HL is the primary venue (leads
price discovery) => a wallet's directional edge there is real venue-specific alpha, not lagged Binance beta.

Denominator = LEGIT tier-1 perp venues only (Binance, OKX, Bybit, Gate, Bitget). We deliberately EXCLUDE the
known wash-volume venues (toobit/weex/mxc/coinup/orangex/coinw/...) that would falsely inflate global volume.
We report two shares: vs Binance alone (the coin the user named) and vs the legit-major basket.

~6 CoinGecko calls total (HL + 5 venues), each returns all contracts in one response. Rate-limit-safe spacing.
Output: out/coin_venue_cg.parquet + printed buckets, joined to our cand2 trading universe.
"""
import time
import urllib.request
import json
from pathlib import Path
import glob
import polars as pl

OUT = Path(__file__).resolve().parents[1] / "out"
PEERS = ["binance_futures", "okex_swap", "bybit", "gate_futures", "bitget_futures"]  # legit tier-1 only


def cg(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=40))


def venue_vol(exchange_id):
    """base-symbol -> summed 24h USD perp volume (and OI) for one derivatives exchange."""
    d = cg(f"https://api.coingecko.com/api/v3/derivatives/exchanges/{exchange_id}?include_tickers=all")
    vol, oi = {}, {}
    for t in d.get("tickers", []):
        if t.get("contract_type") != "perpetual":
            continue
        base = (t.get("base") or "").upper()
        if not base:
            continue
        cv = t.get("converted_volume") or {}
        v = cv.get("usd")
        if v is None:
            continue
        vol[base] = vol.get(base, 0.0) + float(v)
        oiu = t.get("open_interest_usd")
        if oiu:
            oi[base] = oi.get(base, 0.0) + float(oiu)
    return vol, oi


def norm(sym):
    """crude cross-venue base normalization (k-prefix / 1000-prefix meme scaling)."""
    s = sym.upper()
    if s.startswith("1000") and len(s) > 4:
        return "k" + s[4:]
    return s


def main():
    print("pulling HL derivatives ...")
    hl_vol, hl_oi = venue_vol("hyperliquid")
    hl_vol = {norm(k): v for k, v in hl_vol.items()}
    hl_oi = {norm(k): v for k, v in hl_oi.items()}
    print(f"  HL perp coins: {len(hl_vol)}")

    peer_vol = {}   # coin -> {venue: usd_vol}
    for ex in PEERS:
        time.sleep(2.5)
        try:
            v, _ = venue_vol(ex)
            for k, val in v.items():
                peer_vol.setdefault(norm(k), {})[ex] = val
            print(f"  {ex}: {len(v)} coins")
        except Exception as e:
            print(f"  {ex} FAILED: {type(e).__name__} {str(e)[:80]}")

    # our trading universe (cand2 coins)
    cand2 = sorted(glob.glob(str(Path(__file__).resolve().parents[2] / "scratch_conv/mlscreen/cand2_*.parquet")))
    universe = set(pl.scan_parquet(cand2[0]).select(pl.col("coin").unique()).collect()["coin"].to_list())

    rows = []
    allcoins = set(hl_vol) | set(peer_vol)
    for c in sorted(allcoins):
        hv = hl_vol.get(c, 0.0)
        pv = peer_vol.get(c, {})
        binv = pv.get("binance_futures", 0.0)
        majv = sum(pv.values())
        share_bin = hv / (hv + binv) if (hv + binv) > 0 else None
        share_maj = hv / (hv + majv) if (hv + majv) > 0 else None
        rows.append(dict(coin=c, in_universe=c in universe, hl_vol_usd=hv, binance_vol_usd=binv,
                         major_peer_vol_usd=majv, hl_oi_usd=hl_oi.get(c, 0.0),
                         hl_share_vs_binance=share_bin, hl_share_vs_majors=share_maj,
                         on_binance=binv > 0, n_peer_venues=len(pv)))
    R = pl.DataFrame(rows).sort("hl_share_vs_majors", descending=True, nulls_last=True)
    OUT.mkdir(exist_ok=True)
    R.write_parquet(OUT / "coin_venue_cg.parquet")
    print(f"\nwrote {R.height} coins -> out/coin_venue_cg.parquet\n")

    uni = R.filter(pl.col("in_universe") & (pl.col("hl_vol_usd") > 1e6))
    print(f"=== our-universe coins with >$1M/day HL vol: {uni.height} ===")
    with pl.Config(tbl_rows=60, fmt_str_lengths=12):
        print("\n--- HL-LEADS (top HL share, our universe) ---")
        print(uni.head(30).select("coin", "hl_share_vs_majors", "hl_share_vs_binance", "on_binance",
                                  "hl_vol_usd", "binance_vol_usd", "hl_oi_usd"))
        print("\n--- BINANCE-LED (bottom HL share, our universe) ---")
        print(uni.tail(15).select("coin", "hl_share_vs_majors", "hl_share_vs_binance", "hl_vol_usd", "binance_vol_usd"))
    print("\n=== our 4 study majors ===")
    print(R.filter(pl.col("coin").is_in(["BTC", "ETH", "SOL", "HYPE"]))
          .select("coin", "hl_share_vs_majors", "hl_share_vs_binance", "on_binance", "hl_vol_usd", "binance_vol_usd"))


if __name__ == "__main__":
    main()
