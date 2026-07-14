"""Precompute mk6 (leak-free 6h markout, cohort-INDEPENDENT) for ALL majors TEST entries.
Also per-wallet total majors-entry counts (for activity-matched placebo)."""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl
sys.path.insert(0, "src")
from mkcommon import _load_bars, _next_bar_close_vec, COST_BPS

OUT = Path("out"); COINS = ["BTC", "ETH", "SOL", "HYPE"]; BP = 1e4
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TEST_LO = _ms(2026, 3, 1); H6 = 6 * 3_600_000; DAY = 86_400_000; WEEK = 7 * DAY


def fwd(L, t, h):
    e = _next_bar_close_vec(L, t); x = _next_bar_close_vec(L, t + h)
    with np.errstate(all="ignore"): r = x / e - 1.0
    r[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
    return r


def main():
    lk = _load_bars()
    parts = []
    for c in COINS:
        L = lk[c]
        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter((pl.col("coin") == c) & (pl.col("b_ts") >= TEST_LO))
              .select("wallet", "b_ts", "dir").collect())
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(float)
        mk6 = d * fwd(L, b, H6) * BP
        parts.append(ec.with_columns(
            pl.Series("coin", [c] * ec.height), pl.Series("mk6", mk6),
            pl.Series("cost", np.full(b.size, COST_BPS[c])),
            pl.Series("day", b // DAY), pl.Series("week", b // WEEK)))
    E = pl.concat(parts)
    E.write_parquet(OUT / "consensus_master.parquet")
    print(f"master majors TEST table: {E.height:,} rows, {E['wallet'].n_unique():,} wallets")
    # per-wallet total majors entry counts over ALL time (selection universe grain)
    pw = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
          .filter(pl.col("coin").is_in(COINS)).group_by("wallet").agg(n=pl.len()).collect())
    pw.write_parquet(OUT / "consensus_wallet_counts.parquet")
    print(f"per-wallet counts: {pw.height:,} wallets")


if __name__ == "__main__":
    main()
