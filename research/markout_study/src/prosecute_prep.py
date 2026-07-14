"""
PROSECUTE-THE-POSITIVE prep: build a per-entry neutralized table for majors with everything
the 6 attacks need. neut = dir*(fwd24_i - coin-day mean fwd24 over ALL bars).
Split TRAIN Aug'25-Jan'26 / TEST Mar-Jun'26 (Feb embargo).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mkcommon import _load_bars, _next_bar_close_vec

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "out"
SCR = Path("/private/tmp/claude-501/-Users-corywagamaneure-bablyon/75266807-b43e-492d-ac36-5ce0eb00d694/scratchpad")
COINS = ["BTC", "ETH", "SOL", "HYPE"]; H24 = 24 * 3_600_000; BP = 1e4
BAR = 300_000; LAG = 15 * 60_000  # 15-min follower lag
def _ms(y, m, d): return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)
TRAIN_HI = _ms(2026, 2, 1); TEST_LO = _ms(2026, 3, 1)


def main():
    lk = _load_bars()
    parts = []
    for c in COINS:
        L = lk[c]; bt = L[0].astype(np.int64)
        e = _next_bar_close_vec(L, bt); x = _next_bar_close_vec(L, bt + H24)
        with np.errstate(all="ignore"): fwd = x / e - 1.0
        fwd[~(np.isfinite(e) & (e > 0) & np.isfinite(x) & (x > 0))] = np.nan
        # 15-min-lag copier: enter at bar+15m, exit 24h later
        el = _next_bar_close_vec(L, bt + LAG); xl = _next_bar_close_vec(L, bt + LAG + H24)
        with np.errstate(all="ignore"): fwdl = xl / el - 1.0
        fwdl[~(np.isfinite(el) & (el > 0) & np.isfinite(xl) & (xl > 0))] = np.nan
        # coin-day mean fwd over ALL bars (the market benchmark)
        day = bt // 86_400_000
        bg = pl.DataFrame({"day": day, "f": fwd}).filter(pl.col("f").is_finite())
        dmean = dict(zip(*bg.group_by("day").agg(pl.col("f").mean()).to_dict(as_series=False).values()))
        # lag benchmark: coin-day mean of lagged fwd
        bgl = pl.DataFrame({"day": day, "f": fwdl}).filter(pl.col("f").is_finite())
        dmeanl = dict(zip(*bgl.group_by("day").agg(pl.col("f").mean()).to_dict(as_series=False).values()))

        ec = (pl.scan_parquet(OUT / "entries" / "part_*.parquet")
              .filter(pl.col("coin") == c).select("wallet", "b_ts", "dir", "notl").collect())
        b = ec["b_ts"].to_numpy(); d = ec["dir"].to_numpy().astype(np.float64)
        i = np.clip(np.searchsorted(bt, b), 0, bt.size - 1)
        edays = b // 86_400_000
        dben = np.array([dmean.get(k, np.nan) for k in edays])
        dbenl = np.array([dmeanl.get(k, np.nan) for k in edays])
        raw = d * fwd[i]
        neut = raw - d * dben
        raw_lag = d * fwdl[i]
        neut_lag = raw_lag - d * dbenl
        hour = ((b // 3_600_000) % 24).astype(np.int64)
        parts.append(ec.with_columns(
            pl.Series("coin", [c] * ec.height),
            pl.Series("day", edays),
            pl.Series("hour", hour),
            pl.Series("bar", (b // BAR) * BAR),
            pl.Series("raw", raw),
            pl.Series("neut", neut),
            pl.Series("neut_lag", neut_lag),
        ).filter(pl.col("neut").is_finite()))
    E = pl.concat(parts)
    # light winsor at train p99.9 magnitude of neut (matches wallet_level_persistence)
    cap = float(np.nanpercentile(np.abs(E.filter(pl.col("b_ts") < TRAIN_HI)["neut"].to_numpy()), 99.9))
    E = E.with_columns(pl.col("neut").clip(-cap, cap), pl.col("neut_lag").clip(-cap, cap))
    split = np.where(E["b_ts"].to_numpy() < TRAIN_HI, "train",
                     np.where(E["b_ts"].to_numpy() >= TEST_LO, "test", "embargo"))
    E = E.with_columns(pl.Series("split", split))
    E.write_parquet(SCR / "prosecute_entries.parquet")
    print("wrote", SCR / "prosecute_entries.parquet", "rows", E.height, "cap_bp", cap * BP)
    print(E.group_by("split").agg(pl.len(), pl.col("wallet").n_unique().alias("nw")))


if __name__ == "__main__":
    main()
